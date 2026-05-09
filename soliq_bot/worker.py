"""Worker logic: one Playwright browser instance per worker."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PWTimeoutError,
    async_playwright,
)

from .captcha import solve_captcha
from .config import (
    ACTION_TIMEOUT_MS,
    HEADLESS,
    LOGIN_URL,
    NAV_TIMEOUT_MS,
    PROFILES_DIR,
    SELECTORS,
)
from .excel_io import CheckGroup, ProductRow
from .matching import SiteRow, match_rows
from .report import FailedCheck

log = logging.getLogger(__name__)


@dataclass
class WorkerState:
    worker_id: int
    status: str = "Кутилмоқда"
    progress_done: int = 0
    progress_total: int = 0
    password_entered_event: asyncio.Event | None = None
    pause_event: asyncio.Event | None = None
    stop_event: asyncio.Event | None = None
    current_check: str = ""

    def reset_progress(self, total: int) -> None:
        self.progress_done = 0
        self.progress_total = total


class Worker:
    """Drives one Chromium instance through the full edit flow."""

    def __init__(
        self,
        worker_id: int,
        login_type: str,
        company_name: str,
        zip_path: str,
        gemini_api_key: str,
        log_callback: Callable[[str, str], None],
        status_callback: Callable[[WorkerState], None],
    ) -> None:
        self.state = WorkerState(worker_id=worker_id)
        self.login_type = login_type
        self.company_name = company_name
        self.zip_path = zip_path
        self.gemini_api_key = gemini_api_key
        self._log = log_callback
        self._notify = status_callback

        self.context: BrowserContext | None = None
        self.page: Page | None = None

    # --- helpers --------------------------------------------------------
    def log(self, msg: str, level: str = "info") -> None:
        self._log(f"[Воркер {self.state.worker_id}] {msg}", level)

    def set_status(self, status: str) -> None:
        self.state.status = status
        self._notify(self.state)

    async def _wait_pause(self) -> None:
        if self.state.pause_event is not None:
            await self.state.pause_event.wait()

    def _stop_requested(self) -> bool:
        return self.state.stop_event is not None and self.state.stop_event.is_set()

    # --- launch ---------------------------------------------------------
    async def launch(self) -> None:
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        profile_dir = PROFILES_DIR / f"worker_{self.state.worker_id}"
        profile_dir.mkdir(parents=True, exist_ok=True)

        self._pw = await async_playwright().start()
        # Persistent context so e-IMZO certificates and cookies survive between runs.
        self.context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=HEADLESS,
            args=["--start-maximized"],
            viewport=None,
        )
        self.context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        self.context.set_default_timeout(ACTION_TIMEOUT_MS)
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

    async def close(self) -> None:
        try:
            if self.context is not None:
                await self.context.close()
        finally:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001
                pass

    # --- login ----------------------------------------------------------
    async def login(self) -> None:
        assert self.page is not None
        self.set_status("Логин қилинмоқда")
        self.log(f"Очилмоқда: {LOGIN_URL}")
        await self.page.goto(LOGIN_URL)

        # Login type (Корхона / ЯТТ)
        try:
            sel = (
                SELECTORS.login_type_company
                if self.login_type.lower().startswith("корхона")
                else SELECTORS.login_type_yatt
            )
            await self.page.locator(sel).first.click(timeout=ACTION_TIMEOUT_MS)
        except PWTimeoutError:
            self.log(f"Логин тури танланмади: {self.login_type}", "warn")

        # Company name
        if self.company_name:
            search = self.page.locator(SELECTORS.company_search_input).first
            await search.click()
            await search.fill(self.company_name)
            await asyncio.sleep(1.0)  # debounce
            try:
                await self.page.locator(SELECTORS.company_first_result).first.click(
                    timeout=ACTION_TIMEOUT_MS
                )
            except PWTimeoutError:
                self.log("Корхона рўйхатдан танланмади (биринчи натижа топилмади)", "warn")

        # Submit → triggers e-IMZO Java popup
        try:
            await self.page.locator(SELECTORS.login_submit).first.click(
                timeout=ACTION_TIMEOUT_MS
            )
        except PWTimeoutError:
            self.log("‘Кириш’ тугмаси топилмади", "warn")

    async def wait_for_password(self) -> bool:
        """Block until the user clicks 'Парол киритилди' OR Stop is pressed.

        Returns True if password was confirmed, False if stop was requested.
        """
        self.set_status("Java парол кутилмоқда")
        self.log("Java парол ойнаси кутилмоқда. GUI да ‘Парол киритилди’ тугмасини босинг.")
        if self.state.password_entered_event is None:
            return True

        waiters = [asyncio.ensure_future(self.state.password_entered_event.wait())]
        if self.state.stop_event is not None:
            waiters.append(asyncio.ensure_future(self.state.stop_event.wait()))

        try:
            done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
        except Exception:  # noqa: BLE001
            return False

        if self._stop_requested():
            self.log("Стоп юборилди — парол кутиш бекор қилинди.", "warn")
            return False
        self.log("Парол киритилди — давом этамиз.")
        return True

    # --- check edit -----------------------------------------------------
    async def edit_check(self, group: CheckGroup) -> None:
        """End-to-end edit flow for a single check."""
        assert self.page is not None
        self.state.current_check = f"{group.fm_number} / {group.check_number}"
        self.set_status(f"Чек тахрирланмоқда: {self.state.current_check}")

        # 1. Select FM number from dropdown
        try:
            await self.page.locator(SELECTORS.fm_dropdown).first.select_option(
                label=group.fm_number
            )
        except Exception:  # noqa: BLE001
            try:
                await self.page.locator(SELECTORS.fm_dropdown).first.select_option(
                    value=group.fm_number
                )
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"ФМ дропдаунда танланмади: {e}") from e

        # 2. Enter check number and search
        await self.page.locator(SELECTORS.check_number_input).first.fill(group.check_number)
        await self.page.locator(SELECTORS.search_button).first.click()
        await self.page.wait_for_load_state("networkidle")

        # 3. Open detail → edit
        await self.page.locator(SELECTORS.detail_button).first.click()
        await self.page.locator(SELECTORS.edit_button).first.click()
        await self.page.wait_for_load_state("networkidle")

        # 4. Read rows + match
        site_rows = await self._read_edit_rows()
        if not site_rows:
            raise RuntimeError("Тахрирлаш ойнасида қаторлар топилмади")

        mapping = match_rows(site_rows, group.rows)

        # 5. Apply changes per row
        for site_row in site_rows:
            ex_row: Optional[ProductRow] = mapping.get(site_row.index)
            if ex_row is None:
                continue
            await self._fill_row(site_row.index, ex_row)

        # 6. Recalculate cash/terminal
        await self._fix_payment(group.total_sum)

        # 7. Upload ZIP
        if self.zip_path:
            await self._upload_zip(self.zip_path)

        # 8. Solve CAPTCHA
        await self._solve_captcha()

        # 9. Save
        await self.page.locator(SELECTORS.save_button).first.click()
        await self.page.wait_for_load_state("networkidle")
        self.log(f"Чек {self.state.current_check} муваффақиятли сақланди")

    async def _read_edit_rows(self) -> list[SiteRow]:
        """Extract (index, name, sum) for every editable row in the modal."""
        assert self.page is not None
        rows: list[SiteRow] = []
        row_locators = self.page.locator(SELECTORS.edit_row_selector)
        count = await row_locators.count()
        for i in range(count):
            row = row_locators.nth(i)
            try:
                name = (await row.locator(SELECTORS.row_name_cell).first.inner_text()).strip()
            except Exception:  # noqa: BLE001
                name = ""
            try:
                sum_text = (await row.locator(SELECTORS.row_sum_cell).first.inner_text()).strip()
            except Exception:  # noqa: BLE001
                sum_text = ""
            sum_val = _parse_number(sum_text)
            rows.append(SiteRow(index=i, name=name, sum_value=sum_val))
        return rows

    async def _fill_row(self, idx: int, ex: ProductRow) -> None:
        assert self.page is not None
        row = self.page.locator(SELECTORS.edit_row_selector).nth(idx)
        amount_input = row.locator(SELECTORS.row_amount_input).first
        code_input = row.locator(SELECTORS.row_product_code_input).first

        await amount_input.fill("")
        await amount_input.type(_format_number(ex.qty))

        await code_input.fill("")
        await code_input.type(str(ex.code))

    async def _fix_payment(self, total: float) -> None:
        assert self.page is not None
        try:
            cash_field = self.page.locator(SELECTORS.cash_input).first
            term_field = self.page.locator(SELECTORS.terminal_input).first
            cash_val = _parse_number(await cash_field.input_value() or "0")
            term_val = _parse_number(await term_field.input_value() or "0")
            if abs((cash_val + term_val) - total) > 0.5:
                self.log(
                    f"Тўлов сумма мос келмаяпти "
                    f"(нақд={cash_val}, терминал={term_val}, жами={total}). "
                    f"Терминал=0, Нақд={total} қилиб созланмоқда."
                )
                await term_field.fill("0")
                await cash_field.fill(_format_number(total))
        except Exception as e:  # noqa: BLE001
            self.log(f"Тўлов суммасини текшириб бўлмади: {e}", "warn")

    async def _upload_zip(self, zip_path: str) -> None:
        assert self.page is not None
        path = Path(zip_path)
        if not path.exists():
            raise RuntimeError(f"ZIP файл топилмади: {zip_path}")
        await self.page.locator(SELECTORS.zip_file_input).first.set_input_files(str(path))
        self.log(f"ZIP юкланди: {path.name}")

    async def _solve_captcha(self) -> None:
        assert self.page is not None
        try:
            captcha_img = self.page.locator(SELECTORS.captcha_image).first
            if await captcha_img.count() == 0:
                return
            for attempt in range(3):
                img_bytes = await captcha_img.screenshot()
                text = solve_captcha(img_bytes, self.gemini_api_key)
                if not text:
                    self.log("CAPTCHA танишилмади", "warn")
                    continue
                self.log(f"CAPTCHA: {text}")
                inp = self.page.locator(SELECTORS.captcha_input).first
                await inp.fill("")
                await inp.type(text)
                return
        except Exception as e:  # noqa: BLE001
            self.log(f"CAPTCHA босқичи муваффақиятсиз: {e}", "warn")


# --- module-level helpers -----------------------------------------------
_NUM_RE = re.compile(r"[-+]?\d+(?:[\.,]\d+)?")


def _parse_number(text: str) -> float:
    if not text:
        return 0.0
    m = _NUM_RE.search(text.replace("\u00a0", "").replace(" ", ""))
    if not m:
        return 0.0
    return float(m.group(0).replace(",", "."))


def _format_number(v: float) -> str:
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.4f}".rstrip("0").rstrip(".")
