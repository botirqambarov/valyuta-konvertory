"""tkinter GUI for the Soliq chek tahrirlash boti."""
from __future__ import annotations

import queue
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import api_key_store, theme
from .config import AppSettings, MAX_WORKER_COUNT
from .excel_io import load_excel
from .manager import Manager
from .report import FailedCheck
from .worker import WorkerState


class WorkerPanel(ttk.Frame):
    """One row in the workers area: status, progress, 'Парол киритилди' button."""

    def __init__(self, master: tk.Misc, worker_id: int, on_password_confirm) -> None:
        super().__init__(master, padding=4)
        self.worker_id = worker_id
        self.on_password_confirm = on_password_confirm

        self.title_lbl = ttk.Label(self, text=f"Воркер {worker_id}", width=10, font=("TkDefaultFont", 9, "bold"))
        self.status_lbl = ttk.Label(self, text="Кутилмоқда", width=32, anchor="w")
        self.progress = ttk.Progressbar(self, length=140, mode="determinate")
        self.progress_lbl = ttk.Label(self, text="0/0", width=8)
        self.passwd_btn = ttk.Button(
            self,
            text="Парол киритилди",
            command=lambda: self.on_password_confirm(self.worker_id),
            state=tk.DISABLED,
        )

        self.title_lbl.grid(row=0, column=0, padx=2)
        self.status_lbl.grid(row=0, column=1, padx=2, sticky="w")
        self.progress.grid(row=0, column=2, padx=2)
        self.progress_lbl.grid(row=0, column=3, padx=2)
        self.passwd_btn.grid(row=0, column=4, padx=2)

    def update_state(self, state: WorkerState) -> None:
        self.status_lbl.config(text=state.status)
        if state.progress_total > 0:
            self.progress.config(maximum=state.progress_total, value=state.progress_done)
        self.progress_lbl.config(text=f"{state.progress_done}/{state.progress_total}")
        if "парол кутилмоқда" in state.status.lower():
            self.passwd_btn.config(state=tk.NORMAL)
        else:
            self.passwd_btn.config(state=tk.DISABLED)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Soliq чек тахрирлаш боти")
        self.geometry("1020x780")

        self.settings = AppSettings()
        self.manager: Optional[Manager] = None
        self._msg_queue: queue.Queue = queue.Queue()
        self._panels: dict[int, WorkerPanel] = {}
        self._paused = False

        # --- saved UI prefs (theme + remembered api-key mode) ----------
        prefs = theme.load_prefs()
        self._dark_var = tk.BooleanVar(value=bool(prefs.get("dark", True)))
        # API key mode: "default" or "custom"
        default_available = api_key_store.has_default_key()
        saved_mode = prefs.get("api_key_mode", "default" if default_available else "custom")
        if saved_mode == "default" and not default_available:
            saved_mode = "custom"
        self._api_mode_var = tk.StringVar(value=saved_mode)
        self._api_remember_var = tk.BooleanVar(value=bool(prefs.get("remember_custom_key", True)))

        self._build_topbar()
        self._build_form()
        self._build_workers_area()
        self._build_log_area()
        self._build_controls()

        # Apply theme + key mode AFTER widgets exist
        self._apply_theme()
        self._on_api_mode_change()

        self.after(100, self._drain_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- UI building -----------------------------------------------------
    def _build_topbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 6, 8, 0))
        bar.pack(fill="x")
        ttk.Label(
            bar,
            text="Soliq чек тахрирлаш боти",
            font=("TkDefaultFont", 12, "bold"),
        ).pack(side="left")
        self._theme_btn = ttk.Checkbutton(
            bar,
            text="🌙 Тун режими",
            variable=self._dark_var,
            command=self._apply_theme,
        )
        self._theme_btn.pack(side="right")

    def _build_form(self) -> None:
        frm = ttk.LabelFrame(self, text="Созламалар", padding=8)
        frm.pack(fill="x", padx=8, pady=4)

        # Login type
        ttk.Label(frm, text="Логин тури:").grid(row=0, column=0, sticky="w")
        self.login_type_var = tk.StringVar(value="Корхона")
        ttk.Radiobutton(frm, text="Корхона", variable=self.login_type_var, value="Корхона").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(frm, text="ЯТТ", variable=self.login_type_var, value="ЯТТ").grid(row=0, column=2, sticky="w")

        # Company
        ttk.Label(frm, text="Корхона номи:").grid(row=1, column=0, sticky="w", pady=4)
        self.company_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.company_var, width=60).grid(row=1, column=1, columnspan=4, sticky="we")

        # Excel file
        ttk.Label(frm, text="Excel файл:").grid(row=2, column=0, sticky="w", pady=4)
        self.excel_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.excel_var, width=50).grid(row=2, column=1, columnspan=3, sticky="we")
        ttk.Button(frm, text="Танлаш…", command=self._pick_excel).grid(row=2, column=4, padx=4)

        # ZIP file
        ttk.Label(frm, text="ZIP файл (asos.zip):").grid(row=3, column=0, sticky="w", pady=4)
        self.zip_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.zip_var, width=50).grid(row=3, column=1, columnspan=3, sticky="we")
        ttk.Button(frm, text="Танлаш…", command=self._pick_zip).grid(row=3, column=4, padx=4)

        # Worker count
        ttk.Label(frm, text="Воркер сони (1-5):").grid(row=4, column=0, sticky="w", pady=4)
        self.worker_count_var = tk.IntVar(value=1)
        ttk.Spinbox(frm, from_=1, to=MAX_WORKER_COUNT, textvariable=self.worker_count_var, width=5).grid(row=4, column=1, sticky="w")

        # --- API key block (Gemini) -----------------------------------
        api_frame = ttk.LabelFrame(frm, text="Gemini API key", padding=6)
        api_frame.grid(row=5, column=0, columnspan=5, sticky="we", pady=(8, 2))

        default_available = api_key_store.has_default_key()
        default_label = (
            "Тайёр (default) кэлитдан фойдаланиш"
            if default_available
            else "Тайёр (default) кэлитдан фойдаланиш — киритилмаган"
        )
        rb_default = ttk.Radiobutton(
            api_frame, text=default_label,
            variable=self._api_mode_var, value="default",
            command=self._on_api_mode_change,
        )
        rb_default.grid(row=0, column=0, sticky="w", columnspan=3)
        if not default_available:
            rb_default.state(["disabled"])

        ttk.Radiobutton(
            api_frame, text="Ўз кэлитимни ишлатаман",
            variable=self._api_mode_var, value="custom",
            command=self._on_api_mode_change,
        ).grid(row=1, column=0, sticky="w", columnspan=3)

        ttk.Label(api_frame, text="API key:").grid(row=2, column=0, sticky="w", padx=(20, 4))
        self.api_key_var = tk.StringVar(value=api_key_store.load_custom_key())
        self._api_entry = ttk.Entry(api_frame, textvariable=self.api_key_var, width=52, show="*")
        self._api_entry.grid(row=2, column=1, sticky="we", padx=2)

        self._show_btn = ttk.Button(api_frame, text="Кўрсатиш", width=10, command=self._toggle_show_key)
        self._show_btn.grid(row=2, column=2, padx=4)

        self._remember_chk = ttk.Checkbutton(
            api_frame,
            text="Кэлитни эслаб қол (қайта киритиш шарт эмас)",
            variable=self._api_remember_var,
        )
        self._remember_chk.grid(row=3, column=0, columnspan=2, sticky="w", padx=(20, 0), pady=(2, 0))

        self._clear_cache_btn = ttk.Button(
            api_frame, text="Кэшни ўчириш",
            command=self._clear_cached_key, width=14,
        )
        self._clear_cache_btn.grid(row=3, column=2, padx=4, pady=(2, 0))

        for i in range(3):
            api_frame.columnconfigure(i, weight=1 if i == 1 else 0)
        for i in range(5):
            frm.columnconfigure(i, weight=1)

    def _build_workers_area(self) -> None:
        self.workers_frame = ttk.LabelFrame(self, text="Воркерлар", padding=4)
        self.workers_frame.pack(fill="x", padx=8, pady=4)
        self._rebuild_panels(self.worker_count_var.get())
        self.worker_count_var.trace_add("write", lambda *_: self._rebuild_panels(self.worker_count_var.get()))

    def _rebuild_panels(self, n: int) -> None:
        for w in self.workers_frame.winfo_children():
            w.destroy()
        self._panels.clear()
        for wid in range(1, max(1, min(int(n), MAX_WORKER_COUNT)) + 1):
            p = WorkerPanel(self.workers_frame, wid, self._on_password_confirm)
            p.pack(fill="x", pady=1)
            self._panels[wid] = p
        # Re-apply theme to newly created widgets
        if hasattr(self, "_dark_var"):
            self._apply_theme()

    def _build_log_area(self) -> None:
        frm = ttk.LabelFrame(self, text="Лог", padding=4)
        frm.pack(fill="both", expand=True, padx=8, pady=4)
        self.log_text = tk.Text(frm, height=14, wrap="word", state=tk.DISABLED)
        scroll = ttk.Scrollbar(frm, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _build_controls(self) -> None:
        frm = ttk.Frame(self, padding=4)
        frm.pack(fill="x", padx=8, pady=4)

        self.start_btn = ttk.Button(frm, text="Старт", command=self._start)
        self.pause_btn = ttk.Button(frm, text="Пауза", command=self._toggle_pause, state=tk.DISABLED)
        self.stop_btn = ttk.Button(frm, text="Стоп", command=self._stop, state=tk.DISABLED)

        self.start_btn.pack(side="left", padx=4)
        self.pause_btn.pack(side="left", padx=4)
        self.stop_btn.pack(side="left", padx=4)

        self.overall_progress = ttk.Progressbar(frm, length=300, mode="determinate")
        self.overall_progress.pack(side="right", padx=4)
        self.overall_lbl = ttk.Label(frm, text="0/0")
        self.overall_lbl.pack(side="right", padx=4)

    # --- theme + API key mode ------------------------------------------
    def _apply_theme(self) -> None:
        theme.apply_theme(self, dark=bool(self._dark_var.get()))
        # Keep current API-mode disable/enable state in sync visually
        self._on_api_mode_change()

    def _on_api_mode_change(self) -> None:
        mode = self._api_mode_var.get()
        custom = mode == "custom"
        state = (tk.NORMAL if custom else tk.DISABLED)
        for w in (self._api_entry, self._show_btn, self._remember_chk, self._clear_cache_btn):
            try:
                w.configure(state=state)
            except tk.TclError:
                pass

    def _toggle_show_key(self) -> None:
        try:
            shown = self._api_entry.cget("show") == ""
        except tk.TclError:
            shown = False
        new_show = "*" if shown else ""
        self._api_entry.configure(show=new_show)
        self._show_btn.configure(text="Кўрсатиш" if new_show else "Яшириш")

    def _clear_cached_key(self) -> None:
        api_key_store.clear_custom_key()
        self.api_key_var.set("")
        self._append_log("Сақланган кэлит ўчирилди.", "warn")

    # --- callbacks (potentially called from background thread) ----------
    def _post(self, item: tuple) -> None:
        """Thread-safe enqueue for the UI message queue."""
        self._msg_queue.put(item)

    def _log_cb(self, msg: str, level: str = "info") -> None:
        self._post(("log", msg, level))

    def _status_cb(self, state: WorkerState) -> None:
        self._post(("status", state))

    def _progress_cb(self, done: int, total: int) -> None:
        self._post(("overall", done, total))

    def _finished_cb(self, report_path: Optional[Path], failures: list[FailedCheck]) -> None:
        self._post(("finished", report_path, failures))

    # --- queue draining (main thread) -----------------------------------
    def _drain_queue(self) -> None:
        try:
            while True:
                item = self._msg_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    _, msg, level = item
                    self._append_log(msg, level)
                elif kind == "status":
                    _, state = item
                    panel = self._panels.get(state.worker_id)
                    if panel:
                        panel.update_state(state)
                elif kind == "overall":
                    _, done, total = item
                    if total > 0:
                        self.overall_progress.config(maximum=total, value=done)
                    self.overall_lbl.config(text=f"{done}/{total}")
                elif kind == "finished":
                    _, path, failures = item
                    self._on_finished(path, failures)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._drain_queue)

    def _append_log(self, msg: str, level: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert("end", f"[{ts}] {msg}\n", level)
        self.log_text.see("end")
        self.log_text.config(state=tk.DISABLED)

    def _on_finished(self, report_path: Optional[Path], failures: list[FailedCheck]) -> None:
        self.start_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        if failures:
            msg = f"Тугади. Хатоликлар: {len(failures)} та."
            if report_path:
                msg += f"\nҲисобот: {report_path}"
            messagebox.showwarning("Якун", msg)
        else:
            messagebox.showinfo("Якун", "Барча чеклар муваффақиятли тахрирланди.")

    # --- file pickers ----------------------------------------------------
    def _pick_excel(self) -> None:
        p = filedialog.askopenfilename(
            title="Excel файлни танланг",
            filetypes=[("Excel", "*.xlsx *.xls"), ("Барча файллар", "*.*")],
        )
        if p:
            self.excel_var.set(p)

    def _pick_zip(self) -> None:
        p = filedialog.askopenfilename(
            title="ZIP файлни танланг",
            filetypes=[("ZIP", "*.zip"), ("Барча файллар", "*.*")],
        )
        if p:
            self.zip_var.set(p)

    # --- control buttons -------------------------------------------------
    def _resolve_api_key(self) -> str:
        """Pick the right key based on current GUI mode."""
        if self._api_mode_var.get() == "default":
            return api_key_store.get_default_key()
        return self.api_key_var.get().strip()

    def _persist_prefs_and_key(self) -> None:
        prefs = {
            "dark": bool(self._dark_var.get()),
            "api_key_mode": self._api_mode_var.get(),
            "remember_custom_key": bool(self._api_remember_var.get()),
        }
        theme.save_prefs(prefs)

        # Save / clear custom key based on user preference
        if self._api_mode_var.get() == "custom" and self._api_remember_var.get():
            key = self.api_key_var.get().strip()
            if key:
                api_key_store.save_custom_key(key)

    def _start(self) -> None:
        excel_path = self.excel_var.get().strip()
        if not excel_path or not Path(excel_path).exists():
            messagebox.showerror("Хато", "Excel файл танланмаган ёки топилмади.")
            return
        api_key = self._resolve_api_key()
        if not api_key:
            if not messagebox.askyesno(
                "Огоҳлантириш",
                "Gemini API key киритилмаган. CAPTCHA босқичи муваффақиятсиз бўлади. Давом этасизми?",
            ):
                return

        try:
            groups = load_excel(excel_path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Excel ўқиш хатоси", str(e))
            return
        if not groups:
            messagebox.showerror("Хато", "Excel'да чек қаторлари топилмади.")
            return

        self.settings = AppSettings(
            login_type=self.login_type_var.get(),
            company_name=self.company_var.get().strip(),
            excel_path=excel_path,
            zip_path=self.zip_var.get().strip(),
            worker_count=int(self.worker_count_var.get()),
            gemini_api_key=api_key,
        )

        # Persist UI prefs + custom key cache (if enabled)
        self._persist_prefs_and_key()

        self._append_log(
            f"Жами {len(groups)} та чек топилди. Воркер сони: {self.settings.worker_count}.",
            "info",
        )
        self._append_log(
            f"API key манбаси: {'тайёр (default)' if self._api_mode_var.get() == 'default' else 'ўз кэлити'}",
            "info",
        )

        self.manager = Manager(
            settings=self.settings,
            groups=groups,
            log_callback=self._log_cb,
            status_callback=self._status_cb,
            progress_callback=self._progress_cb,
            finished_callback=self._finished_cb,
        )
        self.manager.start()

        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL, text="Пауза")
        self.stop_btn.config(state=tk.NORMAL)
        self._paused = False

    def _toggle_pause(self) -> None:
        if not self.manager:
            return
        if not self._paused:
            self.manager.pause()
            self.pause_btn.config(text="Давом этиш")
            self._paused = True
            self._append_log("Пауза қилинди.", "warn")
        else:
            self.manager.resume()
            self.pause_btn.config(text="Пауза")
            self._paused = False
            self._append_log("Давом этилмоқда.", "info")

    def _stop(self) -> None:
        if self.manager:
            self.manager.stop()
            self._append_log("Стоп юборилди — жорий чеклар якунлангач тўхтайди.", "warn")

    def _on_password_confirm(self, worker_id: int) -> None:
        if self.manager:
            self.manager.confirm_password(worker_id)
            self._append_log(f"[Воркер {worker_id}] парол тасдиқланди.", "info")

    def _on_close(self) -> None:
        try:
            self._persist_prefs_and_key()
        finally:
            self.destroy()
