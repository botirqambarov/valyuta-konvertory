"""Configuration: URLs, default selectors, defaults.

Note: The selectors for my3.soliq.uz are based on the technical specification.
If the site's HTML differs, adjust the SELECTORS dictionary below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://my3.soliq.uz"
LOGIN_URL = f"{BASE_URL}/login"

# Headless mode is OFF because the user must manually enter the Java password
# inside the e-IMZO popup; that requires a visible browser window.
HEADLESS = False

# Per-worker browser timeout (ms)
NAV_TIMEOUT_MS = 60_000
ACTION_TIMEOUT_MS = 30_000

# Where each worker stores its persistent Chromium user-data-dir.
# Each worker gets a separate folder so e-IMZO certificates do not mix.
PROFILES_DIR = Path.home() / ".soliq_bot_profiles"

# Logs directory
LOGS_DIR = Path.cwd() / "logs"

DEFAULT_WORKER_COUNT = 1
MAX_WORKER_COUNT = 5

# Google Gemini settings (for CAPTCHA)
# Tezkor + arzon model:
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_MAX_TOKENS = 64

# UI preferences cache
SETTINGS_DIR = Path.home() / ".soliq_bot"
UI_PREFS_FILE = SETTINGS_DIR / "ui_prefs.json"


# These selectors are placeholders that closely match the spec.
# They are centralised here so a non-developer can adjust them without
# touching the worker logic.
@dataclass
class Selectors:
    # Login page
    login_type_company: str = 'label:has-text("Корхона")'
    login_type_yatt: str = 'label:has-text("ЯТТ")'
    company_search_input: str = 'input[placeholder*="Корхона"], input[name="company"], input[type="search"]'
    company_first_result: str = '.search-results > *:first-child, [role="option"]:first-child'
    login_submit: str = 'button:has-text("Кириш")'

    # After e-IMZO popup → password is entered manually by user; bot waits for
    # confirmation via the GUI ("Парол киритилди" button).

    # Check search page
    fm_dropdown: str = 'select[name="fm"], [data-test="fm-select"]'
    check_number_input: str = 'input[name="check"], input[placeholder*="Чек"]'
    search_button: str = 'button:has-text("Қидириш")'

    # Search result row
    detail_button: str = 'button:has-text("Батафсил"), a:has-text("Батафсил")'

    # Detail modal
    edit_button: str = 'button:has-text("Таҳрирлаш")'

    # Edit modal — rows
    edit_row_selector: str = '[data-test="edit-row"], .edit-row, table tbody tr'
    row_amount_input: str = 'input[name*="amount"]'
    row_product_code_input: str = 'input[name*="productCode"]'
    row_sum_cell: str = '[data-test="row-sum"], td:nth-child(2)'
    row_name_cell: str = '[data-test="row-name"], td:nth-child(1)'

    # Payment fields
    cash_input: str = 'input[name="cash"], input[placeholder*="Нақд"]'
    terminal_input: str = 'input[name="terminal"], input[placeholder*="Терминал"]'
    total_amount_field: str = '[data-test="total-amount"], .total-amount'

    # ZIP upload
    zip_file_input: str = 'input[type="file"][accept*="zip"], input[type="file"]'

    # CAPTCHA
    captcha_image: str = 'img[alt*="captcha" i], img[src*="captcha" i]'
    captcha_input: str = 'input[name*="captcha" i]'

    # Save
    save_button: str = 'button:has-text("Сақлаш")'


SELECTORS = Selectors()


@dataclass
class AppSettings:
    login_type: str = "Корхона"  # or "ЯТТ"
    company_name: str = ""
    excel_path: str = ""
    zip_path: str = ""
    worker_count: int = DEFAULT_WORKER_COUNT
    gemini_api_key: str = ""
    selectors: Selectors = field(default_factory=Selectors)
