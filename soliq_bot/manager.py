"""Manager: spawn workers, distribute checks, collect failures."""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import AppSettings, LOGS_DIR
from .excel_io import CheckGroup
from .report import FailedCheck, write_report
from .worker import Worker, WorkerState

log = logging.getLogger(__name__)


class Manager:
    """Coordinates workers and the GUI thread.

    Threading model:
        * GUI runs in the main thread (tkinter).
        * Manager owns its own asyncio loop in a daemon thread.
        * GUI submits actions via `loop.call_soon_threadsafe`.
        * Workers report status via thread-safe callbacks back to the GUI.
    """

    def __init__(
        self,
        settings: AppSettings,
        groups: list[CheckGroup],
        log_callback: Callable[[str, str], None],
        status_callback: Callable[[WorkerState], None],
        progress_callback: Callable[[int, int], None],
        finished_callback: Callable[[Path | None, list[FailedCheck]], None],
    ) -> None:
        self.settings = settings
        self.groups = groups
        self._log = log_callback
        self._notify = status_callback
        self._progress = progress_callback
        self._finished = finished_callback

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._workers: dict[int, Worker] = {}
        self._failures: list[FailedCheck] = []
        self._failures_lock = threading.Lock()

        # Aggregated progress
        self._done = 0
        self._total = len(groups)

    # --- public API (thread-safe) ---------------------------------------
    def start(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

    def stop(self) -> None:
        if self._loop is None:
            return
        for w in self._workers.values():
            if w.state.stop_event is not None:
                self._loop.call_soon_threadsafe(w.state.stop_event.set)

    def pause(self) -> None:
        if self._loop is None:
            return
        for w in self._workers.values():
            ev = w.state.pause_event
            if ev is not None:
                self._loop.call_soon_threadsafe(ev.clear)

    def resume(self) -> None:
        if self._loop is None:
            return
        for w in self._workers.values():
            ev = w.state.pause_event
            if ev is not None:
                self._loop.call_soon_threadsafe(ev.set)

    def confirm_password(self, worker_id: int) -> None:
        if self._loop is None:
            return
        worker = self._workers.get(worker_id)
        if worker and worker.state.password_entered_event is not None:
            self._loop.call_soon_threadsafe(worker.state.password_entered_event.set)

    # --- internals ------------------------------------------------------
    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._loop.close()

    async def _main(self) -> None:
        try:
            n = max(1, min(self.settings.worker_count, 5))
            queues = self._partition_groups(n)

            tasks = []
            for wid in range(1, n + 1):
                if not queues[wid - 1]:
                    continue
                w = Worker(
                    worker_id=wid,
                    login_type=self.settings.login_type,
                    company_name=self.settings.company_name,
                    zip_path=self.settings.zip_path,
                    gemini_api_key=self.settings.gemini_api_key,
                    log_callback=self._log,
                    status_callback=self._notify,
                )
                w.state.password_entered_event = asyncio.Event()
                w.state.pause_event = asyncio.Event()
                w.state.pause_event.set()  # start un-paused
                w.state.stop_event = asyncio.Event()
                self._workers[wid] = w
                tasks.append(self._run_worker(w, queues[wid - 1]))

            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            report_path = None
            try:
                LOGS_DIR.mkdir(parents=True, exist_ok=True)
                if self._failures:
                    report_path = write_report(self._failures, LOGS_DIR)
            except Exception as e:  # noqa: BLE001
                self._log(f"Хатолар ҳисоботини ёзишда хато: {e}", "error")
            self._finished(report_path, list(self._failures))

    def _partition_groups(self, n: int) -> list[list[CheckGroup]]:
        buckets: list[list[CheckGroup]] = [[] for _ in range(n)]
        for i, g in enumerate(self.groups):
            buckets[i % n].append(g)
        return buckets

    async def _run_worker(self, w: Worker, my_groups: list[CheckGroup]) -> None:
        w.state.reset_progress(len(my_groups))
        w.set_status("Браузер очилмоқда")
        try:
            await w.launch()
        except Exception as e:  # noqa: BLE001
            w.log(f"Браузер очилмади: {e}", "error")
            return

        try:
            await w.login()
            confirmed = await w.wait_for_password()
        except Exception as e:  # noqa: BLE001
            w.log(f"Логин жараёнида хато: {e}", "error")
            self._record_failure_for_worker(w, my_groups, "Логин хатоси", str(e))
            await w.close()
            return

        if not confirmed:
            w.set_status("Тўхтатилди")
            await w.close()
            return

        for group in my_groups:
            if w._stop_requested():
                w.log("Тўхтатилди (стоп).", "warn")
                break
            await w._wait_pause()
            try:
                await w.edit_check(group)
            except Exception as e:  # noqa: BLE001
                w.log(f"Чекда хато: {group.fm_number}/{group.check_number} → {e}", "error")
                self._add_failure(
                    FailedCheck(
                        fm_number=group.fm_number,
                        check_number=group.check_number,
                        rows_count=len(group.rows),
                        error_type=type(e).__name__,
                        error_details=str(e),
                        worker=f"Воркер {w.state.worker_id}",
                        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    )
                )
            finally:
                w.state.progress_done += 1
                self._notify(w.state)
                self._done += 1
                self._progress(self._done, self._total)

        w.set_status("Якунланди")
        await w.close()

    # --- failure helpers -------------------------------------------------
    def _add_failure(self, f: FailedCheck) -> None:
        with self._failures_lock:
            self._failures.append(f)

    def _record_failure_for_worker(
        self,
        w: Worker,
        groups: list[CheckGroup],
        error_type: str,
        details: str,
    ) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for g in groups:
            self._add_failure(
                FailedCheck(
                    fm_number=g.fm_number,
                    check_number=g.check_number,
                    rows_count=len(g.rows),
                    error_type=error_type,
                    error_details=details,
                    worker=f"Воркер {w.state.worker_id}",
                    timestamp=ts,
                )
            )
