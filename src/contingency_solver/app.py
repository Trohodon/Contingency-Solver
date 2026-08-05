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
    ThermalViolation,
    build_branch_pair_index,
    branch_display,
    generate_candidates,
    match_branches_for_issue,
    preview_candidate_electricals,
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
from contingency_solver.services.real_screening import RealScreeningContext, run_real_screening_batch
from contingency_solver.storage import (
    EXPORT_DIR,
    LOG_DIR,
    create_working_case_copy,
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
        self.original_case_path: Path | None = None
        self.working_case_path: Path | None = None

        self.buses = mock_buses()
        self.branches = mock_branches()
        self.branch_pair_index = build_branch_pair_index(self.branches)
        self.contingencies = mock_contingencies()
        self.baseline_overloads = mock_baseline_overloads()
        self.baseline_summaries: list[LineLoadingSummary] = summarize_thermal_by_line(self.baseline_overloads)
        self.voltage_violations = mock_voltage_violations()
        self.selected_branch = self.branches[1]
        self.selected_issue_key = self.selected_branch_label()
        self.selected_contingency_name = self._default_selected_contingency_name()
        self.candidates: list[CandidateLine] = []
        self.results: list[CandidateResult] = []
        self.case_summary_message = "Mock data loaded."
        self.real_batch_limit_var: tk.IntVar | None = None

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
        baseline_buttons = ttk.Frame(page)
        baseline_buttons.pack(fill="x", pady=(4, 8))
        ttk.Button(baseline_buttons, text="Use Selected Line Issue for Candidate Setup", command=self.use_selected_line_issue).pack(side="left")
        self.selected_issue_var = tk.StringVar(value=self._selected_context_label())
        ttk.Label(baseline_buttons, textvariable=self.selected_issue_var).pack(side="left", padx=(12, 0))
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
            ("Maximum candidate pairs", ttk.Entry(controls, textvariable=self.max_candidates_var, width=10)),
        ]
        for index, (label, widget) in enumerate(entries):
            ttk.Label(controls, text=label).grid(row=index // 3, column=(index % 3) * 2, sticky="w", padx=8, pady=5)
            widget.grid(row=index // 3, column=(index % 3) * 2 + 1, sticky="w", padx=8, pady=5)
        ttk.Button(controls, text="Generate Candidates", command=self.generate_candidate_preview).grid(row=2, column=0, padx=8, pady=8, sticky="w")
        self.candidate_study_branch_var = tk.StringVar(value=f"Study branch: {self.selected_issue_key}")
        self.candidate_study_contingency_var = tk.StringVar(value=f"Study contingency: {self.selected_contingency_name}")
        ttk.Label(controls, textvariable=self.candidate_study_branch_var).grid(row=2, column=1, columnspan=5, sticky="w", padx=8, pady=(8, 2))
        ttk.Label(controls, textvariable=self.candidate_study_contingency_var).grid(row=3, column=1, columnspan=5, sticky="w", padx=8, pady=(2, 8))
        self.candidate_summary_var = tk.StringVar(value="No candidates generated yet.")
        ttk.Label(page, textvariable=self.candidate_summary_var).pack(anchor="w")
        self.candidate_tree = self._tree(
            page,
            (
                "From Bus",
                "From Name",
                "To Bus",
                "To Name",
                "Nominal kV",
                "Conductor",
                "Distance miles",
                "R ohms",
                "X ohms",
                "R pu",
                "X pu",
                "LineC pu",
                "Rate A",
                "Validation",
            ),
        )

    def _build_run_page(self, page: ttk.Frame) -> None:
        self._title(page, "Run Screening", "Mock screening is simulated. PowerWorld screening preflight validates the selected real-case setup before candidate branch insertion is enabled.")
        buttons = ttk.Frame(page)
        buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="Run Mock Screening (Simulated)", command=self.run_mock_screening).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Run PowerWorld Screening Preflight", command=self.run_powerworld_preflight).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Probe Add One Candidate", command=self.probe_add_one_candidate).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Probe Add + Solve Intact", command=self.probe_add_and_solve_one_candidate).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Probe Add + Solve + Run CTG", command=self.probe_add_solve_and_run_contingency).pack(side="left")
        batch = ttk.Frame(page)
        batch.pack(fill="x", pady=(0, 8))
        self.real_batch_limit_var = tk.IntVar(value=5)
        ttk.Label(batch, text="Real batch candidate limit").pack(side="left", padx=(0, 6))
        ttk.Entry(batch, textvariable=self.real_batch_limit_var, width=8).pack(side="left", padx=(0, 6))
        ttk.Button(batch, text="Run Real Screening Batch", command=self.run_real_screening_batch).pack(side="left")
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

    def use_selected_line_issue(self) -> None:
        selected = self.baseline_tree.selection()
        if not selected:
            messagebox.showwarning(APP_NAME, "Select a line/transformer issue in Baseline Results first.")
            return

        summary_values = self.baseline_tree.item(selected[0], "values")
        issue_key = str(summary_values[0])
        contingency_name = self._selected_baseline_detail_contingency()
        if not contingency_name and len(summary_values) >= 3:
            contingency_name = str(summary_values[2])
        contingency_name = contingency_name or "(No contingency selected)"
        matches = match_branches_for_issue(issue_key, self.branches, self.buses, self.branch_pair_index)
        if not matches:
            messagebox.showwarning(
                APP_NAME,
                "Could not match this result row back to a branch in the case.\n\n"
                f"Result text:\n{issue_key}\n\n"
                "This usually means the PowerWorld result text does not include both bus numbers or both bus names.",
            )
            return

        branch = matches[0] if len(matches) == 1 else self._choose_branch_match(issue_key, matches)
        if branch is None:
            return

        self.selected_branch = branch
        self.selected_issue_key = issue_key
        self.selected_contingency_name = contingency_name
        self.selected_issue_var.set(self._selected_context_label(branch))
        self.candidate_study_branch_var.set(f"Study branch: {branch_display(branch, self.buses)}")
        self.candidate_study_contingency_var.set(f"Study contingency: {self.selected_contingency_name}")
        self.candidates = []
        self.candidate_var.set("Candidates: 0")
        self._set_tree_rows(self.candidate_tree, [])
        self.candidate_summary_var.set("Study branch selected. Generate candidates to preview nearby additions.")
        self._select_nav_page("Candidate Setup")

    def _selected_baseline_detail_contingency(self) -> str:
        selected = self.baseline_detail_tree.selection() if hasattr(self, "baseline_detail_tree") else ()
        if not selected:
            return ""
        values = self.baseline_detail_tree.item(selected[0], "values")
        return str(values[0]) if values else ""

    def _default_selected_contingency_name(self) -> str:
        if self.baseline_summaries:
            return self.baseline_summaries[0].worst_contingency
        if self.contingencies:
            return self.contingencies[0].name
        return "(No contingency selected)"

    def _selected_context_label(self, branch: Branch | None = None) -> str:
        branch_text = branch_display(branch, self.buses) if branch else self.selected_issue_key
        return f"Selected study branch: {branch_text} | Contingency: {self.selected_contingency_name}"

    def _choose_branch_match(self, issue_key: str, matches: list[Branch]) -> Branch | None:
        dialog = tk.Toplevel(self)
        dialog.title("Select Matching Branch")
        dialog.geometry("760x320")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text=f"Multiple branches match:\n{issue_key}", wraplength=720).pack(anchor="w", padx=10, pady=(10, 6))
        listbox = tk.Listbox(dialog, height=9, exportselection=False)
        listbox.pack(fill="both", expand=True, padx=10, pady=6)
        for branch in matches[:200]:
            listbox.insert(tk.END, branch_display(branch, self.buses))
        listbox.selection_set(0)

        selected: list[Branch | None] = [None]

        def accept() -> None:
            selection = listbox.curselection()
            if selection:
                selected[0] = matches[selection[0]]
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(buttons, text="Use Selected Branch", command=accept).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Cancel", command=cancel).pack(side="left")
        listbox.bind("<Double-Button-1>", lambda _event: accept())
        self.wait_window(dialog)
        return selected[0]

    def _select_nav_page(self, page_name: str) -> None:
        names = list(self.page_frames.keys())
        if page_name not in names:
            return
        index = names.index(page_name)
        self.nav_list.selection_clear(0, tk.END)
        self.nav_list.selection_set(index)
        self.nav_list.see(index)
        self.page_frames[page_name].tkraise()

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
            working_path = create_working_case_copy(path)
            self.powerworld.open_case(working_path)
            self.buses, bus_attempt = self.powerworld.read_buses_with_diagnostics()
            self.branches, branch_attempt = self.powerworld.read_branches_with_diagnostics()
            self.branch_pair_index = build_branch_pair_index(self.branches)
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
        self.original_case_path = path
        self.working_case_path = working_path
        self.selected_branch = self.branches[0] if self.branches else Branch(0, 0)
        self.selected_issue_key = self.selected_branch_label()
        self.baseline_summaries = summarize_thermal_by_line(self.baseline_overloads)
        self.selected_contingency_name = self._default_selected_contingency_name()
        self.candidates = []
        self.results = []
        self.case_var.set(f"Case: {path.name}")
        self.connection_var.set("PowerWorld: connected")
        self.case_summary_message = self._case_load_summary(path, bus_attempt, branch_attempt, ctg_attempts, violation_attempts)
        self.selected_issue_var.set(self._selected_context_label())
        self.candidate_study_branch_var.set(f"Study branch: {self.selected_issue_key}")
        self.candidate_study_contingency_var.set(f"Study contingency: {self.selected_contingency_name}")
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
        self.branch_pair_index = build_branch_pair_index(self.branches)
        self.contingencies = mock_contingencies()
        self.baseline_overloads = mock_baseline_overloads()
        self.baseline_summaries = summarize_thermal_by_line(self.baseline_overloads)
        self.voltage_violations = mock_voltage_violations()
        self.selected_branch = self.branches[1]
        self.selected_issue_key = self.selected_branch_label()
        self.selected_contingency_name = self._default_selected_contingency_name()
        self.candidates = []
        self.results = []
        self.real_case_loaded = False
        self.original_case_path = None
        self.working_case_path = None
        self.case_path_var.set("Mock sample case - no confidential case loaded")
        self.connection_detail_var.set("MOCK MODE - simulated data")
        self.version_var.set("Unavailable in mock mode")
        self.connection_var.set("PowerWorld: mock")
        self.case_var.set("Case: Mock sample case")
        self.candidate_var.set("Candidates: 0")
        self.case_summary_message = "Mock data loaded."
        self.selected_issue_var.set(self._selected_context_label())
        self.candidate_study_branch_var.set(f"Study branch: {self.selected_issue_key}")
        self.candidate_study_contingency_var.set(f"Study contingency: {self.selected_contingency_name}")
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
        previews = [preview_candidate_electricals(candidate, self.conductors, self.system_mva_base) for candidate in self.candidates]
        self._set_tree_rows(
            self.candidate_tree,
            [
                (
                    preview.candidate.from_bus,
                    preview.candidate.from_bus_name,
                    preview.candidate.to_bus,
                    preview.candidate.to_bus_name,
                    preview.candidate.nominal_kv,
                    preview.conductor_name or preview.candidate.conductor_key,
                    f"{preview.candidate.distance_miles:.2f}",
                    self._format_optional_float(preview.resistance_ohms, 4),
                    self._format_optional_float(preview.reactance_ohms, 4),
                    self._format_optional_float(preview.r_pu, 6),
                    self._format_optional_float(preview.x_pu, 6),
                    self._format_optional_float(preview.charging_pu, 6),
                    self._format_optional_float(preview.rate_a_mva, 2),
                    preview.validation_message,
                )
                for preview in previews
            ],
        )
        warning_text = f" | {'; '.join(summary.warnings)}" if summary.warnings else ""
        self.candidate_summary_var.set(
            f"Buses found: {summary.buses_found} | Candidate pairs generated: {summary.candidates_generated} "
            f"| candidate cap: {settings.maximum_candidates}{warning_text}"
        )
        self.candidate_var.set(f"Candidates: {len(self.candidates)}")
        self.run_log.insert("end", f"Generated {len(self.candidates)} candidates.\n")

    def selected_branch_label(self) -> str:
        return branch_display(self.selected_branch, self.buses) if self.selected_branch else "(No study branch selected)"

    def run_mock_screening(self) -> None:
        if self.real_case_loaded and not messagebox.askyesno(
            APP_NAME,
            "This will run simulated mock screening numbers on a real loaded case.\n\n"
            "Use this only to test the UI/export workflow. Continue?",
        ):
            return
        if not self.candidates:
            self.generate_candidate_preview()
        original_loading = self._selected_original_loading_pct()
        self.results = simulate_results(self.candidates, original_loading)
        self.progress.configure(maximum=max(1, len(self.results)), value=len(self.results))
        self.run_var.set("Run: mock complete")
        self.run_log.insert(
            "end",
            f"Mock screening complete. {len(self.results)} results ranked. Original loading used: {original_loading:.2f}%.\n",
        )
        save_run_history(self.selected_contingency_name, self.selected_issue_key, self.settings, self.results)
        self._set_tree_rows(self.results_tree, [tuple(result_to_row(result).values()) for result in self.results])

    def run_powerworld_preflight(self) -> None:
        if not self.real_case_loaded:
            messagebox.showwarning(APP_NAME, "Load a real PowerWorld case before running PowerWorld screening preflight.")
            return
        if not self.candidates:
            self.generate_candidate_preview()
        if not self.candidates:
            messagebox.showwarning(APP_NAME, "No candidate lines are available to validate.")
            return

        previews = [preview_candidate_electricals(candidate, self.conductors, self.system_mva_base) for candidate in self.candidates]
        errors = [preview.validation_message for preview in previews if preview.validation_message != "OK"]
        missing_context: list[str] = []
        if not self.selected_contingency_name or self.selected_contingency_name.startswith("("):
            missing_context.append("selected contingency")
        if not self.selected_branch or self.selected_branch.from_bus == self.selected_branch.to_bus:
            missing_context.append("selected study branch")
        if errors or missing_context:
            lines = ["PowerWorld screening preflight failed."]
            if missing_context:
                lines.append(f"Missing context: {', '.join(missing_context)}")
            if errors:
                lines.append("Candidate/conductor validation:")
                lines.extend(f"- {error}" for error in sorted(set(errors))[:12])
            text = "\n".join(lines)
            self.run_log.insert("end", text + "\n")
            messagebox.showerror(APP_NAME, text)
            return

        original_loading = self._selected_original_loading_pct()
        message = (
            "PowerWorld screening preflight passed.\n\n"
            f"Selected contingency: {self.selected_contingency_name}\n"
            f"Selected line issue: {self.selected_issue_key}\n"
            f"Original selected loading: {original_loading:.2f}%\n"
            f"Candidate count: {len(self.candidates)}\n\n"
            "Next implementation step is SimAuto candidate branch insertion and case restoration. "
            "No candidate has been added to the PowerWorld case by this preflight."
        )
        self.run_var.set("Run: real preflight passed")
        self.progress.configure(maximum=max(1, len(self.candidates)), value=0)
        self.run_log.insert("end", message + "\n")
        messagebox.showinfo(APP_NAME, message)

    def probe_add_one_candidate(self) -> None:
        prepared = self._prepare_candidate_probe()
        if prepared is None:
            return
        candidate, conductor_model = prepared

        try:
            attempt = self.powerworld.probe_add_candidate_branch(
                self.working_case_path,
                candidate,
                conductor_model,
                self.system_mva_base,
            )
        except (SimAutoUnavailableError, SimAutoCommandError, ValueError) as exc:
            LOGGER.exception("Candidate branch probe failed.")
            messagebox.showerror(APP_NAME, self._readable_error(exc))
            return

        text = self._format_attempt(attempt)
        self.run_log.insert("end", f"Candidate branch probe result:\n{text}\n")
        if getattr(attempt, "error", ""):
            messagebox.showerror(
                APP_NAME,
                "Candidate branch probe failed. The working case was reloaded after the attempt.\n\n"
                f"{getattr(attempt, 'error', '')}\n\n"
                "Open Logs or copy the Run Screening log so the PowerWorld command can be adjusted.",
            )
            return
        messagebox.showinfo(
            APP_NAME,
            "Candidate branch probe succeeded on the temporary working copy.\n\n"
            "The working copy was reloaded immediately after the probe so the candidate branch does not remain in the open case.",
        )

    def probe_add_and_solve_one_candidate(self) -> None:
        prepared = self._prepare_candidate_probe()
        if prepared is None:
            return
        candidate, conductor_model = prepared

        try:
            attempts = self.powerworld.probe_add_candidate_and_solve(
                self.working_case_path,
                candidate,
                conductor_model,
                self.system_mva_base,
            )
        except (SimAutoUnavailableError, SimAutoCommandError, ValueError) as exc:
            LOGGER.exception("Candidate add and intact solve probe failed.")
            messagebox.showerror(APP_NAME, self._readable_error(exc))
            return

        text = "\n".join(self._format_attempt(attempt) for attempt in attempts)
        self.run_log.insert("end", f"Candidate add + intact solve probe result:\n{text}\n")
        errors = [attempt.error for attempt in attempts if attempt.error]
        if errors:
            messagebox.showerror(
                APP_NAME,
                "Candidate add + intact solve probe failed. The working case was reloaded after the attempt.\n\n"
                f"{errors[-1]}\n\n"
                "Open Logs or copy the Run Screening log so the PowerWorld command can be adjusted.",
            )
            return
        messagebox.showinfo(
            APP_NAME,
            "Candidate add + intact solve probe succeeded on the temporary working copy.\n\n"
            "The working copy was reloaded immediately after the probe so the candidate branch does not remain in the open case.",
        )

    def probe_add_solve_and_run_contingency(self) -> None:
        prepared = self._prepare_candidate_probe()
        if prepared is None:
            return
        candidate, conductor_model = prepared
        if not self.selected_contingency_name or self.selected_contingency_name.startswith("("):
            messagebox.showwarning(APP_NAME, "Select a real contingency from Baseline Results before running the contingency probe.")
            return

        try:
            attempts, violations = self.powerworld.probe_add_candidate_solve_and_run_contingency(
                self.working_case_path,
                candidate,
                conductor_model,
                self.system_mva_base,
                self.selected_contingency_name,
                self.thermal_results_min_loading_pct,
            )
        except (SimAutoUnavailableError, SimAutoCommandError, ValueError) as exc:
            LOGGER.exception("Candidate add, solve, and contingency probe failed.")
            messagebox.showerror(APP_NAME, self._readable_error(exc))
            return

        text = "\n".join(self._format_attempt(attempt) for attempt in attempts)
        top_rows = "\n".join(
            f"- {row.contingency} | {row.branch_key} | {row.percent_loading:.2f}%"
            for row in violations[:10]
        )
        self.run_log.insert(
            "end",
            f"Candidate add + intact solve + contingency probe result:\n{text}\n"
            f"Thermal rows read: {len(violations)}\n{top_rows}\n",
        )
        errors = [attempt.error for attempt in attempts if attempt.error]
        if errors:
            messagebox.showerror(
                APP_NAME,
                "Candidate add + solve + contingency probe failed. The working case was reloaded after the attempt.\n\n"
                f"{errors[-1]}\n\n"
                "Copy the Run Screening log so the PowerWorld command can be adjusted.",
            )
            return
        messagebox.showinfo(
            APP_NAME,
            "Candidate add + solve + contingency probe succeeded on the temporary working copy.\n\n"
            f"Thermal rows read at or above {self.thermal_results_min_loading_pct:.1f}%: {len(violations)}\n\n"
            "The working copy was reloaded immediately after the probe so the candidate branch does not remain in the open case.",
        )

    def run_real_screening_batch(self) -> None:
        if not self.real_case_loaded or self.working_case_path is None:
            messagebox.showwarning(APP_NAME, "Load a real PowerWorld case before running real screening.")
            return
        if not self.candidates:
            self.generate_candidate_preview()
        if not self.candidates:
            messagebox.showwarning(APP_NAME, "No candidate lines are available to screen.")
            return
        if not self.selected_contingency_name or self.selected_contingency_name.startswith("("):
            messagebox.showwarning(APP_NAME, "Select a real contingency from Baseline Results before running real screening.")
            return
        limit = max(1, int(self.real_batch_limit_var.get() if self.real_batch_limit_var is not None else 5))
        if not messagebox.askyesno(
            APP_NAME,
            "Run real PowerWorld screening on the temporary working copy?\n\n"
            f"Candidates to process: {min(limit, len(self.candidates))}\n"
            f"Selected contingency: {self.selected_contingency_name}\n\n"
            "The original case will not be opened. The working copy is reloaded after every candidate.",
        ):
            return

        context = self._real_screening_context()
        self.run_var.set("Run: real screening running")
        self.progress.configure(maximum=min(limit, len(self.candidates)), value=0)
        self.run_log.insert("end", f"Starting real screening batch for {min(limit, len(self.candidates))} candidates.\n")
        try:
            self.results = run_real_screening_batch(self.powerworld, self.candidates, context, limit)
        except Exception as exc:
            LOGGER.exception("Real screening batch failed.")
            self.run_var.set("Run: real screening failed")
            messagebox.showerror(APP_NAME, str(exc))
            return

        self.progress.configure(value=len(self.results))
        self.run_var.set("Run: real screening complete")
        self._set_tree_rows(self.results_tree, [tuple(result_to_row(result).values()) for result in self.results])
        save_run_history(self.selected_contingency_name, self.selected_issue_key, self.settings, self.results)
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.classification.value] = counts.get(result.classification.value, 0) + 1
        self.run_log.insert("end", f"Real screening complete. Results: {counts}\n")
        messagebox.showinfo(APP_NAME, f"Real screening complete. {len(self.results)} candidates processed.")

    def _real_screening_context(self) -> RealScreeningContext:
        selected_rows = self._selected_baseline_rows()
        worst = max(selected_rows, key=lambda item: item.percent_loading) if selected_rows else None
        original_loading = self._selected_original_loading_pct()
        return RealScreeningContext(
            working_case_path=self.working_case_path,
            selected_contingency=self.selected_contingency_name,
            selected_issue_key=self.selected_issue_key,
            original_loading_pct=original_loading,
            original_mva=worst.mva if worst else 0.0,
            original_rating_mva=worst.rating_mva if worst else 0.0,
            baseline_violations=self.baseline_overloads,
            conductor_models=self.conductors,
            system_mva_base=self.system_mva_base,
            minimum_loading_pct=self.thermal_results_min_loading_pct,
            meaningful_improvement_threshold_pct_points=float(self.settings.get("meaningful_improvement_threshold_pct_points", 2.0)),
        )

    def _selected_baseline_rows(self) -> list[ThermalViolation]:
        return [
            row
            for row in self.baseline_overloads
            if (row.branch_key or "(No line/transformer label)") == self.selected_issue_key
        ]

    def _prepare_candidate_probe(self) -> tuple[CandidateLine, ConductorModel] | None:
        if not self.real_case_loaded or self.working_case_path is None:
            messagebox.showwarning(APP_NAME, "Load a real PowerWorld case before probing a candidate branch.")
            return None
        if not self.candidates:
            self.generate_candidate_preview()
        if not self.candidates:
            messagebox.showwarning(APP_NAME, "No candidate lines are available to probe.")
            return None

        candidate = self._selected_candidate_or_first()
        conductor_model = self.conductors.get(candidate.conductor_key)
        if conductor_model is None:
            messagebox.showerror(APP_NAME, f"No conductor model is configured for {candidate.conductor_key} kV.")
            return None
        preview = preview_candidate_electricals(candidate, self.conductors, self.system_mva_base)
        if preview.validation_message != "OK":
            messagebox.showerror(APP_NAME, preview.validation_message)
            return None
        return candidate, conductor_model

    def _selected_candidate_or_first(self) -> CandidateLine:
        selected = self.candidate_tree.selection() if hasattr(self, "candidate_tree") else ()
        if selected:
            children = list(self.candidate_tree.get_children(""))
            try:
                index = children.index(selected[0])
                return self.candidates[index]
            except (ValueError, IndexError):
                pass
        return self.candidates[0]

    def _selected_original_loading_pct(self) -> float:
        selected_detail = self.baseline_detail_tree.selection() if hasattr(self, "baseline_detail_tree") else ()
        if selected_detail:
            values = self.baseline_detail_tree.item(selected_detail[0], "values")
            if len(values) >= 5:
                return self._safe_float(values[4], 0.0)

        selected_summary = self.baseline_tree.selection() if hasattr(self, "baseline_tree") else ()
        if selected_summary:
            values = self.baseline_tree.item(selected_summary[0], "values")
            if len(values) >= 4:
                return self._safe_float(values[3], 0.0)

        if self.baseline_summaries:
            return self.baseline_summaries[0].worst_percent_loading
        return 0.0

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

    def _format_optional_float(self, value: float | None, decimals: int) -> str:
        if value is None:
            return ""
        return f"{value:.{decimals}f}"

    def _safe_float(self, value: object, default: float) -> float:
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return default

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
            f"Original selected PowerWorld case: {path}",
            f"Temporary working copy opened in PowerWorld: {self.working_case_path or '(not created)'}",
            "",
            "The original selected case is not opened for screening. Future candidate insertion/reruns must reload this working copy or create a fresh copy before each candidate.",
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
