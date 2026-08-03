from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from contingency_solver.core import (
    Branch,
    CandidateClassification,
    CandidateLine,
    CandidateResult,
    CandidateSettings,
    ConductorModel,
    LineLoadingSummary,
    generate_candidates,
    result_to_row,
    summarize_thermal_by_line,
    validate_conductor_models,
)
from contingency_solver.mock import (
    mock_baseline_overloads,
    mock_branches,
    mock_buses,
    mock_contingencies,
    mock_voltage_violations,
    simulate_results,
)
from contingency_solver.powerworld import PowerWorldReader, SchemaResolutionError, SimAutoCommandError, SimAutoUnavailableError
from contingency_solver.storage import (
    EXPORT_DIR,
    LOG_DIR,
    ensure_dirs,
    export_csv,
    export_excel,
    load_conductors,
    load_settings,
    restore_default_conductors,
    save_conductors,
    save_run_history,
)

APP_NAME = "Contingency Solver"
LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    ensure_dirs()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = RotatingFileHandler(LOG_DIR / "contingency_solver.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(formatter)
    root.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)


class ContingencySolverApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1280x820")
        self.minsize(1080, 720)

        self.settings = load_settings()
        self.thermal_results_min_loading_pct = float(self.settings.get("thermal_results_min_loading_pct", 90.0))
        self.system_mva_base, self.voltage_tolerance_kv, self.conductors = load_conductors()
        self.powerworld = PowerWorldReader()
        self.real_case_loaded = False

        self.buses = mock_buses()
        self.branches = mock_branches()
        self.contingencies = mock_contingencies()
        self.baseline_overloads = mock_baseline_overloads()
        self.baseline_summaries: list[LineLoadingSummary] = summarize_thermal_by_line(self.baseline_overloads)
        self.voltage_violations = mock_voltage_violations()
        self.selected_branch = self.branches[1]
        self.candidates: list[CandidateLine] = []
        self.results: list[CandidateResult] = []
        self.case_summary_message = "Mock data loaded."

        self._configure_style()
        self._build_layout()
        self._refresh_all()
        LOGGER.info("Tkinter application started.")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("Treeview", rowheight=24, background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Status.TLabel", foreground="#116329", font=("Segoe UI", 10, "bold"))

    def _build_layout(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        nav = ttk.Frame(self, padding=(8, 8), width=190)
        nav.grid(row=0, column=0, sticky="ns")
        nav.grid_propagate(False)
        self.nav_list = tk.Listbox(nav, activestyle="none", exportselection=False)
        for name in [
            "Case Setup",
            "Contingencies",
            "Baseline Results",
            "Candidate Setup",
            "Run Screening",
            "Results",
            "Conductor Models",
            "Settings",
            "Logs",
            "About",
        ]:
            self.nav_list.insert(tk.END, name)
        self.nav_list.pack(fill="both", expand=True)
        self.nav_list.selection_set(0)
        self.nav_list.bind("<<ListboxSelect>>", self._show_selected_page)

        self.pages = ttk.Frame(self, padding=12)
        self.pages.grid(row=0, column=1, sticky="nsew")
        self.pages.columnconfigure(0, weight=1)
        self.pages.rowconfigure(0, weight=1)
        self.page_frames: dict[str, ttk.Frame] = {}
        for name, builder in [
            ("Case Setup", self._build_case_page),
            ("Contingencies", self._build_contingencies_page),
            ("Baseline Results", self._build_baseline_page),
            ("Candidate Setup", self._build_candidate_page),
            ("Run Screening", self._build_run_page),
            ("Results", self._build_results_page),
            ("Conductor Models", self._build_conductor_page),
            ("Settings", self._build_settings_page),
            ("Logs", self._build_logs_page),
            ("About", self._build_about_page),
        ]:
            frame = ttk.Frame(self.pages)
            frame.grid(row=0, column=0, sticky="nsew")
            self.page_frames[name] = frame
            builder(frame)

        status = ttk.Frame(self, padding=(8, 3))
        status.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.connection_var = tk.StringVar(value="PowerWorld: mock")
        self.case_var = tk.StringVar(value="Case: Mock sample case")
        self.ctg_var = tk.StringVar(value="Contingency: CTG_102_103_LOSS")
        self.candidate_var = tk.StringVar(value="Candidates: 0")
        self.run_var = tk.StringVar(value="Run: idle")
        for var in (self.connection_var, self.case_var, self.ctg_var, self.candidate_var, self.run_var):
            ttk.Label(status, textvariable=var).pack(side="left", padx=(0, 18))
        self.page_frames["Case Setup"].tkraise()

    def _title(self, parent: ttk.Frame, title: str, subtitle: str) -> None:
        ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(parent, text=subtitle, wraplength=950).pack(anchor="w", pady=(0, 10))

    def _build_case_page(self, page: ttk.Frame) -> None:
        self._title(page, "Case Setup", "Mock mode is always available. Real PowerWorld case reading uses SimAuto and schema-controlled fields.")
        form = ttk.LabelFrame(page, text="Case")
        form.pack(fill="x", pady=6)
        self.case_path_var = tk.StringVar(value="Mock sample case - no confidential case loaded")
        self.connection_detail_var = tk.StringVar(value="MOCK MODE - simulated data")
        self.version_var = tk.StringVar(value="Unavailable in mock mode")
        self.bus_count_var = tk.StringVar()
        self.branch_count_var = tk.StringVar()
        self.supported_count_var = tk.StringVar()
        self.coordinate_var = tk.StringVar()
        rows = [
            ("PowerWorld connection", self.connection_detail_var),
            ("PowerWorld version", self.version_var),
            ("Case path", self.case_path_var),
            ("Bus count", self.bus_count_var),
            ("Branch count", self.branch_count_var),
            ("Supported-voltage bus count", self.supported_count_var),
            ("Coordinate data", self.coordinate_var),
        ]
        for row, (label, var) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            ttk.Label(form, textvariable=var).grid(row=row, column=1, sticky="w", padx=8, pady=4)
        buttons = ttk.Frame(page)
        buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text="Browse Case", command=self.browse_case).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Load Case", command=self.load_case).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Test SimAuto Connection", command=self.test_connection).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Reload Mock Data", command=self.reload_mock_data).pack(side="left")
        self.case_summary = tk.Text(page, height=10, wrap="word")
        self.case_summary.pack(fill="both", expand=True, pady=(8, 0))

    def _build_contingencies_page(self, page: ttk.Frame) -> None:
        self._title(page, "Contingencies", "Contingency definitions. The overload results you want are on Baseline Results.")
        self.ctg_search_var = tk.StringVar()
        self.ctg_search_var.trace_add("write", lambda *_: self._fill_contingencies())
        ttk.Entry(page, textvariable=self.ctg_search_var).pack(fill="x", pady=(0, 6))
        self.ctg_tree = self._tree(page, ("Name", "Category", "Skip", "Solved", "Actions"))

    def _build_baseline_page(self, page: ttk.Frame) -> None:
        self._title(page, "Baseline Results", "Line/transformer issue summary from ViolationCTG. Select a row to see every contingency that causes that line issue.")
        self.baseline_status_var = tk.StringVar(value="Status: mock contingency solved with thermal loading results.")
        ttk.Label(page, textvariable=self.baseline_status_var, style="Status.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(page, text="Line/Transformer Summary").pack(anchor="w", pady=(0, 4))
        self.baseline_tree = self._tree(page, ("Line/Transformer", "Contingency Count", "Worst Contingency", "Worst %", "Worst Value", "Worst Limit"), height=8)
        self.baseline_tree.bind("<<TreeviewSelect>>", lambda _event: self._fill_selected_line_details())
        ttk.Label(page, text="Selected Line/Transformer Contingency Details").pack(anchor="w", pady=(10, 4))
        self.baseline_detail_tree = self._tree(page, ("Contingency", "Category", "Limit", "Value", "% Loading"), height=8)
        ttk.Label(page, text="Voltage Violations are de-prioritized for now.").pack(anchor="w", pady=(10, 4))
        self.voltage_tree = self._tree(page, ("Bus", "Name", "Voltage pu", "Limit pu", "Type"), height=4)

    def _build_candidate_page(self, page: ttk.Frame) -> None:
        self._title(page, "Candidate Setup", "Generate same-voltage 115 kV and 230 kV candidate lines from bus coordinates.")
        controls = ttk.LabelFrame(page, text="Candidate Rules")
        controls.pack(fill="x", pady=(0, 8))
        self.radius_var = tk.DoubleVar(value=50.0)
        self.min_length_var = tk.DoubleVar(value=1.0)
        self.max_length_var = tk.DoubleVar(value=50.0)
        self.mode_var = tk.StringVar(value="endpoints")
        self.voltage_filter_var = tk.StringVar(value="115 and 230")
        self.max_candidates_var = tk.IntVar(value=250)
        entries = [
            ("Radius miles", ttk.Entry(controls, textvariable=self.radius_var, width=10)),
            ("Minimum line length", ttk.Entry(controls, textvariable=self.min_length_var, width=10)),
            ("Maximum line length", ttk.Entry(controls, textvariable=self.max_length_var, width=10)),
            ("Geographic mode", ttk.Combobox(controls, textvariable=self.mode_var, values=("endpoints", "midpoint"), width=14, state="readonly")),
            ("Voltage class", ttk.Combobox(controls, textvariable=self.voltage_filter_var, values=("115 and 230", "115 only", "230 only"), width=14, state="readonly")),
            ("Maximum candidates", ttk.Entry(controls, textvariable=self.max_candidates_var, width=10)),
        ]
        for index, (label, widget) in enumerate(entries):
            ttk.Label(controls, text=label).grid(row=index // 3, column=(index % 3) * 2, sticky="w", padx=8, pady=5)
            widget.grid(row=index // 3, column=(index % 3) * 2 + 1, sticky="w", padx=8, pady=5)
        ttk.Button(controls, text="Generate Candidates", command=self.generate_candidate_preview).grid(row=2, column=0, padx=8, pady=8, sticky="w")
        self.candidate_summary_var = tk.StringVar(value="No candidates generated yet.")
        ttk.Label(page, textvariable=self.candidate_summary_var).pack(anchor="w")
        self.candidate_tree = self._tree(page, ("From Bus", "From Name", "To Bus", "To Name", "Nominal kV", "Conductor", "Distance miles"))

    def _build_run_page(self, page: ttk.Frame) -> None:
        self._title(page, "Run Screening", "Mock screening populates representative ranked results. Real simulation starts in Phase 4.")
        ttk.Button(page, text="Run Mock Screening", command=self.run_mock_screening).pack(anchor="w")
        self.progress = ttk.Progressbar(page, mode="determinate")
        self.progress.pack(fill="x", pady=8)
        self.run_log = tk.Text(page, height=18, wrap="word")
        self.run_log.pack(fill="both", expand=True)

    def _build_results_page(self, page: ttk.Frame) -> None:
        self._title(page, "Results", "Sortable mock result table with CSV and Excel export.")
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="Export Excel", command=self.export_results_excel).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Export CSV", command=self.export_results_csv).pack(side="left")
        self.results_tree = self._tree(page, tuple(result_to_row(_empty_result()).keys()))

    def _build_conductor_page(self, page: ttk.Frame) -> None:
        self._title(page, "Conductor Models", "Edit conductor values and save them to JSON. Units are shown in the columns.")
        self.conductor_tree = self._tree(
            page,
            ("Key", "Name", "Nominal kV", "Bundle", "R ohm/mi", "X ohm/mi", "Charging type", "Charging/mi", "Rate A", "Rate B", "Rate C", "Circuits"),
            height=8,
        )
        buttons = ttk.Frame(page)
        buttons.pack(fill="x", pady=8)
        ttk.Button(buttons, text="Save Current Defaults", command=self.save_current_conductors).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Restore Defaults", command=self.restore_conductors).pack(side="left")
        ttk.Label(page, text="Phase 1/2 editor displays saved values. Inline editing will be expanded with validation dialogs as conductor data stabilizes.").pack(anchor="w")

    def _build_settings_page(self, page: ttk.Frame) -> None:
        self._title(page, "Settings", "Non-sensitive settings are persisted under user_data.")
        top = ttk.LabelFrame(page, text="Result Filters")
        top.pack(fill="x", pady=(0, 8))
        self.thermal_threshold_var = tk.DoubleVar(value=self.thermal_results_min_loading_pct)
        ttk.Label(top, text="Minimum line/transformer loading %").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(top, textvariable=self.thermal_threshold_var, width=10).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        ttk.Button(top, text="Save Settings", command=self.save_settings_from_ui).grid(row=0, column=2, sticky="w", padx=8, pady=6)
        self.settings_text = tk.Text(page, wrap="word")
        self.settings_text.pack(fill="both", expand=True)

    def _build_logs_page(self, page: ttk.Frame) -> None:
        self._title(page, "Logs", f"Logs are written to {LOG_DIR}. Diagnostic exports will exclude confidential case files.")
        self.logs_text = tk.Text(page, wrap="word")
        self.logs_text.pack(fill="both", expand=True)

    def _build_about_page(self, page: ttk.Frame) -> None:
        self._title(page, "About", "Contingency Solver")
        ttk.Label(
            page,
            text=(
                "Version 0.1.0\n\n"
                "Tkinter desktop application for transmission reinforcement screening.\n\n"
                "Mock mode is simulated and must not be used for engineering decisions. "
                "PowerWorld reading is available through SimAuto on Windows; baseline execution is next."
            ),
            wraplength=900,
        ).pack(anchor="w")

    def _tree(self, parent: ttk.Frame, columns: tuple[str, ...], height: int = 14) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=4)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        for column in columns:
            tree.heading(column, text=column, command=lambda c=column: self._sort_tree(tree, c, False))
            tree.column(column, width=120, anchor="w")
        return tree

    def _show_selected_page(self, _event: tk.Event) -> None:
        selection = self.nav_list.curselection()
        if not selection:
            return
        self.page_frames[self.nav_list.get(selection[0])].tkraise()

    def _refresh_all(self) -> None:
        self._refresh_case_metrics()
        self._fill_contingencies()
        self._fill_baseline()
        self._fill_conductors()
        self._fill_settings()
        self._fill_logs()

    def _refresh_case_metrics(self) -> None:
        supported = sum(1 for bus in self.buses if abs(bus.nominal_kv - 115.0) <= self.voltage_tolerance_kv or abs(bus.nominal_kv - 230.0) <= self.voltage_tolerance_kv)
        coords = sum(1 for bus in self.buses if bus.has_coordinates)
        self.bus_count_var.set(str(len(self.buses)))
        self.branch_count_var.set(str(len(self.branches)))
        self.supported_count_var.set(str(supported))
        self.coordinate_var.set(f"{coords} of {len(self.buses)} buses have valid coordinates")
        self._replace_text(
            self.case_summary,
            self.case_summary_message,
        )

    def _fill_contingencies(self) -> None:
        search = self.ctg_search_var.get().lower() if hasattr(self, "ctg_search_var") else ""
        rows = [
            (c.name, c.category, c.skipped, "" if c.solved is None else c.solved, c.action_count or 0)
            for c in self.contingencies
            if search in c.name.lower() or search in c.category.lower()
        ]
        self._set_tree_rows(self.ctg_tree, rows)

    def _fill_baseline(self) -> None:
        self.baseline_summaries = summarize_thermal_by_line(self.baseline_overloads)
        self.baseline_status_var.set(
            f"Line/transformer issues at or above {self.thermal_results_min_loading_pct:.1f}%: "
            f"{len(self.baseline_summaries)} | detail rows: {len(self.baseline_overloads)}"
        )
        self._set_tree_rows(
            self.baseline_tree,
            [
                (
                    summary.branch_key,
                    summary.result_count,
                    summary.worst_contingency,
                    f"{summary.worst_percent_loading:.2f}",
                    f"{summary.worst_mva:.2f}",
                    f"{summary.worst_rating_mva:.2f}",
                )
                for summary in self.baseline_summaries
            ],
        )
        self._fill_selected_line_details()
        self._set_tree_rows(self.voltage_tree, [(v.bus_number, v.bus_name, v.voltage_pu, v.limit_pu, v.violation_type) for v in self.voltage_violations])

    def _fill_selected_line_details(self) -> None:
        selected = self.baseline_tree.selection() if hasattr(self, "baseline_tree") else ()
        if selected:
            branch_key = str(self.baseline_tree.item(selected[0], "values")[0])
        elif self.baseline_summaries:
            branch_key = self.baseline_summaries[0].branch_key
        else:
            branch_key = ""

        rows = [
            row
            for row in self.baseline_overloads
            if (row.branch_key or "(No line/transformer label)") == branch_key
        ]
        rows.sort(key=lambda item: item.percent_loading, reverse=True)
        self._set_tree_rows(
            self.baseline_detail_tree,
            [
                (
                    row.contingency,
                    row.category,
                    f"{row.rating_mva:.2f}",
                    f"{row.mva:.2f}",
                    f"{row.percent_loading:.2f}",
                )
                for row in rows
            ],
        )

    def _fill_conductors(self) -> None:
        self._set_tree_rows(
            self.conductor_tree,
            [
                (
                    model.key,
                    model.name,
                    model.nominal_kv,
                    model.bundle_count,
                    model.resistance_ohm_per_mile,
                    model.reactance_ohm_per_mile,
                    model.charging_input_type,
                    model.charging_value_per_mile,
                    model.rate_a_mva,
                    model.rate_b_mva,
                    model.rate_c_mva,
                    model.circuit_count,
                )
                for model in self.conductors.values()
            ],
        )

    def _fill_settings(self) -> None:
        self._replace_text(self.settings_text, "\n".join(f"{key}: {value}" for key, value in self.settings.items()))

    def _fill_logs(self) -> None:
        log_path = LOG_DIR / "contingency_solver.log"
        self._replace_text(self.logs_text, log_path.read_text(encoding="utf-8")[-8000:] if log_path.exists() else "No log entries yet.")

    def browse_case(self) -> None:
        path = filedialog.askopenfilename(
            title="Select PowerWorld Case",
            filetypes=[("PowerWorld Cases", "*.pwb *.pwd *.aux"), ("All Files", "*.*")],
            initialdir=self.settings.get("last_case_directory", str(Path.cwd())),
        )
        if path:
            self.case_path_var.set(path)
            self.settings["last_case_directory"] = str(Path(path).parent)

    def test_connection(self) -> None:
        try:
            self.powerworld.client.connect()
            self.version_var.set(self.powerworld.client.get_version())
            self.connection_detail_var.set("Connected")
            self.connection_var.set("PowerWorld: connected")
            messagebox.showinfo(APP_NAME, "PowerWorld SimAuto connection succeeded.")
        except (SimAutoUnavailableError, SimAutoCommandError) as exc:
            LOGGER.exception("SimAuto connection failed.")
            messagebox.showerror(APP_NAME, self._readable_error(exc))

    def load_case(self) -> None:
        path = Path(self.case_path_var.get())
        if not path.exists():
            messagebox.showwarning(APP_NAME, "Select an existing PowerWorld case first.")
            return
        try:
            self.powerworld.open_case(path)
            self.buses, bus_attempt = self.powerworld.read_buses_with_diagnostics()
            self.branches, branch_attempt = self.powerworld.read_branches_with_diagnostics()
            self.contingencies, ctg_attempts = self.powerworld.read_contingencies_with_diagnostics()
            self.baseline_overloads, violation_attempts = self.powerworld.read_thermal_violations_with_diagnostics(
                self.thermal_results_min_loading_pct
            )
            self.voltage_violations = []
        except (SimAutoUnavailableError, SimAutoCommandError, SchemaResolutionError, ValueError) as exc:
            LOGGER.exception("PowerWorld case load failed.")
            messagebox.showerror(APP_NAME, self._readable_error(exc))
            return
        self.real_case_loaded = True
        self.selected_branch = self.branches[0] if self.branches else Branch(0, 0)
        self.candidates = []
        self.results = []
        self.case_var.set(f"Case: {path.name}")
        self.connection_var.set("PowerWorld: connected")
        self.case_summary_message = self._case_load_summary(path, bus_attempt, branch_attempt, ctg_attempts, violation_attempts)
        self._refresh_all()
        if not self.buses or not self.branches or not self.baseline_overloads:
            messagebox.showwarning(
                APP_NAME,
                "The case loaded, but one or more key PowerWorld tables returned zero rows. "
                "Open Case Setup to view the query diagnostics.",
            )

    def reload_mock_data(self) -> None:
        self.buses = mock_buses()
        self.branches = mock_branches()
        self.contingencies = mock_contingencies()
        self.baseline_overloads = mock_baseline_overloads()
        self.baseline_summaries = summarize_thermal_by_line(self.baseline_overloads)
        self.voltage_violations = mock_voltage_violations()
        self.selected_branch = self.branches[1]
        self.candidates = []
        self.results = []
        self.real_case_loaded = False
        self.case_path_var.set("Mock sample case - no confidential case loaded")
        self.connection_detail_var.set("MOCK MODE - simulated data")
        self.version_var.set("Unavailable in mock mode")
        self.connection_var.set("PowerWorld: mock")
        self.case_var.set("Case: Mock sample case")
        self.candidate_var.set("Candidates: 0")
        self.case_summary_message = "Mock data loaded."
        self._refresh_all()

    def save_settings_from_ui(self) -> None:
        try:
            threshold = float(self.thermal_threshold_var.get())
        except tk.TclError:
            messagebox.showerror(APP_NAME, "Minimum loading percent must be a number.")
            return
        if threshold < 0 or threshold > 200:
            messagebox.showerror(APP_NAME, "Minimum loading percent must be between 0 and 200.")
            return
        self.thermal_results_min_loading_pct = threshold
        self.settings["thermal_results_min_loading_pct"] = threshold
        from contingency_solver.storage import save_settings

        save_settings(self.settings)
        self._fill_settings()
        messagebox.showinfo(APP_NAME, "Settings saved. Reload the PowerWorld case to apply the result threshold.")

    def generate_candidate_preview(self) -> None:
        voltage_text = self.voltage_filter_var.get()
        voltage_classes = (115.0,) if voltage_text == "115 only" else (230.0,) if voltage_text == "230 only" else (115.0, 230.0)
        settings = CandidateSettings(
            radius_miles=float(self.radius_var.get()),
            minimum_length_miles=float(self.min_length_var.get()),
            maximum_length_miles=float(self.max_length_var.get()),
            voltage_classes=voltage_classes,
            voltage_tolerance_kv=self.voltage_tolerance_kv,
            study_area_mode=self.mode_var.get(),
            maximum_candidates=int(self.max_candidates_var.get()),
        )
        self.candidates, summary = generate_candidates(self.buses, self.branches, self.selected_branch, settings)
        self._set_tree_rows(
            self.candidate_tree,
            [(c.from_bus, c.from_bus_name, c.to_bus, c.to_bus_name, c.nominal_kv, c.conductor_key, f"{c.distance_miles:.2f}") for c in self.candidates],
        )
        self.candidate_summary_var.set(f"Buses found: {summary.buses_found} | Candidate pairs generated: {summary.candidates_generated}")
        self.candidate_var.set(f"Candidates: {len(self.candidates)}")
        self.run_log.insert("end", f"Generated {len(self.candidates)} candidates.\n")

    def run_mock_screening(self) -> None:
        if not self.candidates:
            self.generate_candidate_preview()
        self.results = simulate_results(self.candidates)
        self.progress.configure(maximum=max(1, len(self.results)), value=len(self.results))
        self.run_var.set("Run: mock complete")
        self.run_log.insert("end", f"Mock screening complete. {len(self.results)} results ranked.\n")
        save_run_history("CTG_102_103_LOSS", "102-103-1", self.settings, self.results)
        self._set_tree_rows(self.results_tree, [tuple(result_to_row(result).values()) for result in self.results])

    def save_current_conductors(self) -> None:
        errors = validate_conductor_models(self.conductors)
        if errors:
            messagebox.showerror(APP_NAME, "\n".join(errors))
            return
        save_conductors(self.system_mva_base, self.voltage_tolerance_kv, self.conductors)
        messagebox.showinfo(APP_NAME, "Conductor models saved.")

    def restore_conductors(self) -> None:
        restore_default_conductors()
        self.system_mva_base, self.voltage_tolerance_kv, self.conductors = load_conductors()
        self._fill_conductors()

    def export_results_excel(self) -> None:
        if not self.results:
            messagebox.showwarning(APP_NAME, "No results are available to export.")
            return
        path = filedialog.asksaveasfilename(title="Export Excel", defaultextension=".xlsx", initialdir=EXPORT_DIR, filetypes=[("Excel Workbook", "*.xlsx")])
        if path:
            export_excel(self.results, Path(path), self.conductors, self.settings)

    def export_results_csv(self) -> None:
        if not self.results:
            messagebox.showwarning(APP_NAME, "No results are available to export.")
            return
        path = filedialog.asksaveasfilename(title="Export CSV", defaultextension=".csv", initialdir=EXPORT_DIR, filetypes=[("CSV", "*.csv")])
        if path:
            export_csv(self.results, Path(path))

    def _set_tree_rows(self, tree: ttk.Treeview, rows: list[tuple[object, ...]]) -> None:
        tree.delete(*tree.get_children())
        for row in rows:
            tree.insert("", "end", values=row)

    def _sort_tree(self, tree: ttk.Treeview, column: str, reverse: bool) -> None:
        data = [(tree.set(item, column), item) for item in tree.get_children("")]
        data.sort(reverse=reverse)
        for index, (_, item) in enumerate(data):
            tree.move(item, "", index)
        tree.heading(column, command=lambda: self._sort_tree(tree, column, not reverse))

    def _replace_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def _readable_error(self, exc: Exception) -> str:
        if isinstance(exc, SimAutoCommandError):
            return f"PowerWorld operation failed.\n\nOperation: {exc.operation}\nRaw SimAuto error: {exc.raw_error}"
        return str(exc)

    def _case_load_summary(
        self,
        path: Path,
        bus_attempt: object,
        branch_attempt: object,
        ctg_attempts: list[object],
        violation_attempts: list[object],
    ) -> str:
        lines = [
            f"Real PowerWorld data loaded from: {path}",
            "",
            f"Bus count: {len(self.buses)}",
            f"Branch count: {len(self.branches)}",
            f"Contingency definition count: {len(self.contingencies)}",
            f"Line/transformer result count at or above {self.thermal_results_min_loading_pct:.1f}%: {len(self.baseline_overloads)}",
            "",
            "Baseline execution is not implemented yet; current thermal loading rows are read from saved ViolationCTG results in the case.",
            "",
            "Bus query:",
            self._format_attempt(bus_attempt),
            "",
            "Branch query:",
            self._format_attempt(branch_attempt),
            "",
            "ViolationCTG line/transformer result attempts:",
            "object type | filter | fields | rows | raw | error",
        ]
        for attempt in violation_attempts:
            object_type = getattr(attempt, "object_type", "")
            filter_name = getattr(attempt, "filter_name", "")
            fields = ", ".join(getattr(attempt, "fields", ()))
            row_count = getattr(attempt, "row_count", 0)
            raw_summary = getattr(attempt, "raw_summary", "")
            error = getattr(attempt, "error", "")
            lines.append(f"{object_type!r} | {filter_name!r} | {fields or '-'} | {row_count} | {raw_summary or '-'} | {error or '-'}")

        if self.baseline_overloads and self.buses and self.branches:
            return "\n".join(lines)

        lines.extend(
            [
                "",
                "Contingency definition attempts:",
                "object type | filter | fields | rows | raw | error",
            ]
        )
        for attempt in ctg_attempts:
            object_type = getattr(attempt, "object_type", "")
            filter_name = getattr(attempt, "filter_name", "")
            fields = ", ".join(getattr(attempt, "fields", ()))
            row_count = getattr(attempt, "row_count", 0)
            raw_summary = getattr(attempt, "raw_summary", "")
            error = getattr(attempt, "error", "")
            lines.append(f"{object_type!r} | {filter_name!r} | {fields or '-'} | {row_count} | {raw_summary or '-'} | {error or '-'}")
        lines.append("")
        lines.append("Send this diagnostic text back so the schema can be adjusted without guessing.")
        return "\n".join(lines)

    def _format_attempt(self, attempt: object) -> str:
        object_type = getattr(attempt, "object_type", "")
        filter_name = getattr(attempt, "filter_name", "")
        fields = ", ".join(getattr(attempt, "fields", ()))
        row_count = getattr(attempt, "row_count", 0)
        raw_summary = getattr(attempt, "raw_summary", "")
        error = getattr(attempt, "error", "")
        return (
            f"object={object_type!r} filter={filter_name!r} fields={fields or '-'} "
            f"rows={row_count} raw={raw_summary or '-'} error={error or '-'}"
        )


def _empty_result() -> CandidateResult:
    return CandidateResult(0, 0, CandidateClassification.NO_EFFECT, 0, "", 0, "", 0, "", 0, 0, 0, 0, 0, 0, False, 0, 0, 0, 0, 0, False, False, 0)


def main() -> int:
    configure_logging()
    app = ContingencySolverApp()
    app.mainloop()
    return 0
