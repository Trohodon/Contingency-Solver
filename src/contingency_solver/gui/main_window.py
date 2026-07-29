from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from contingency_solver.analysis.candidate_generator import CandidateGenerationSettings, generate_candidates
from contingency_solver.constants import APP_NAME, MOCK_MODE_LABEL
from contingency_solver.gui.models.table_models import ObjectTableModel
from contingency_solver.gui.navigation import NavigationList
from contingency_solver.gui.pages.shared import page_title, panel
from contingency_solver.models.branch import Branch
from contingency_solver.models.bus import Bus
from contingency_solver.models.candidate import CandidateLine
from contingency_solver.models.conductor import ConductorModel
from contingency_solver.models.contingency import Contingency
from contingency_solver.models.run_result import CandidateResult
from contingency_solver.models.violation import ThermalViolation, VoltageViolation
from contingency_solver.powerworld.case_manager import CaseManager
from contingency_solver.powerworld.contingency_service import ContingencyService
from contingency_solver.powerworld.schema import SchemaResolutionError
from contingency_solver.powerworld.simauto_client import SimAutoClient, SimAutoCommandError, SimAutoUnavailableError
from contingency_solver.services.export_service import ExportService
from contingency_solver.services.history_service import HistoryService
from contingency_solver.services.mock_data import (
    mock_baseline_overloads,
    mock_branches,
    mock_buses,
    mock_contingencies,
    mock_voltage_violations,
    simulate_results,
)
from contingency_solver.services.settings_service import SettingsService
from contingency_solver.utilities.paths import exports_dir, log_dir
from contingency_solver.utilities.validation import validate_conductor_models

LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings_service = SettingsService()
        self.export_service = ExportService()
        self.history_service = HistoryService()
        self.settings = self.settings_service.load_settings()
        self.system_mva_base, self.voltage_tolerance_kv, self.conductor_models = self.settings_service.load_conductor_models()
        self.simauto_client = SimAutoClient()
        self.case_manager = CaseManager(self.simauto_client)
        self.contingency_service = ContingencyService(self.simauto_client)
        self.real_case_loaded = False

        self.buses: list[Bus] = mock_buses()
        self.branches: list[Branch] = mock_branches()
        self.contingencies: list[Contingency] = mock_contingencies()
        self.baseline_overloads: list[ThermalViolation] = mock_baseline_overloads()
        self.voltage_violations: list[VoltageViolation] = mock_voltage_violations()
        self.candidates: list[CandidateLine] = []
        self.results: list[CandidateResult] = []
        self.selected_branch = self.branches[1]

        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self._build_ui()
        self._apply_style()
        self._populate_initial_data()
        LOGGER.info("Application started with mock data available.")

    def _build_ui(self) -> None:
        page_names = [
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
        ]
        container = QWidget()
        root = QHBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        self.navigation = NavigationList(page_names)
        self.navigation.setFixedWidth(220)
        root.addWidget(self.navigation)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.setCentralWidget(container)

        self.case_page = self._case_setup_page()
        self.contingency_page = self._contingencies_page()
        self.baseline_page = self._baseline_page()
        self.candidate_page = self._candidate_page()
        self.run_page = self._run_screening_page()
        self.results_page = self._results_page()
        self.conductor_page = self._conductor_page()
        self.settings_page = self._settings_page()
        self.logs_page = self._logs_page()
        self.about_page = self._about_page()

        for page in [
            self.case_page,
            self.contingency_page,
            self.baseline_page,
            self.candidate_page,
            self.run_page,
            self.results_page,
            self.conductor_page,
            self.settings_page,
            self.logs_page,
            self.about_page,
        ]:
            self.stack.addWidget(page)
        self.navigation.page_changed.connect(self.stack.setCurrentIndex)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.connection_status = QLabel("PowerWorld: mock")
        self.case_status = QLabel("Case: Mock sample case")
        self.ctg_status = QLabel("Contingency: CTG_102_103_LOSS")
        self.candidate_status = QLabel("Candidates: 0")
        self.run_status = QLabel("Run: idle")
        for widget in [self.connection_status, self.case_status, self.ctg_status, self.candidate_status, self.run_status]:
            self.status.addPermanentWidget(widget)

        export_action = QAction("Export All Results", self)
        export_action.triggered.connect(self.export_all_results)
        self.menuBar().addMenu("File").addAction(export_action)

    def _case_setup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("Case Setup", "Load mock data for development or connect to PowerWorld Simulator through SimAuto."))
        grid = QGridLayout()
        info = panel()
        form = QFormLayout(info)
        self.case_path = QLineEdit("Mock sample case - no confidential case loaded")
        self.powerworld_connection_label = QLabel(MOCK_MODE_LABEL)
        self.powerworld_version_label = QLabel("Unavailable in mock mode")
        self.bus_count_label = QLabel(str(len(self.buses)))
        self.branch_count_label = QLabel(str(len(self.branches)))
        supported = len([bus for bus in self.buses if bus.nominal_kv in (115.0, 230.0)])
        self.supported_bus_count_label = QLabel(str(supported))
        coord = len([bus for bus in self.buses if bus.has_valid_coordinates])
        self.coordinate_summary_label = QLabel(f"{coord} of {len(self.buses)} buses have valid coordinates")
        form.addRow("PowerWorld connection", self.powerworld_connection_label)
        form.addRow("PowerWorld version", self.powerworld_version_label)
        form.addRow("Case path", self.case_path)
        form.addRow("Bus count", self.bus_count_label)
        form.addRow("Branch count", self.branch_count_label)
        form.addRow("Supported-voltage bus count", self.supported_bus_count_label)
        form.addRow("Coordinate data", self.coordinate_summary_label)
        self.working_dir = QLineEdit(str(Path.cwd() / "user_data" / "working"))
        form.addRow("Temporary working directory", self.working_dir)
        buttons = QHBoxLayout()
        browse = QPushButton("Browse Case")
        browse.clicked.connect(self.browse_case)
        buttons.addWidget(browse)
        self.load_case_button = QPushButton("Load Case")
        self.load_case_button.clicked.connect(self.load_selected_case)
        buttons.addWidget(self.load_case_button)
        mock = QPushButton("Reload Mock Data")
        mock.clicked.connect(self.reload_mock_data)
        buttons.addWidget(mock)
        test = QPushButton("Test SimAuto Connection")
        test.clicked.connect(self.test_simauto_connection)
        buttons.addWidget(test)
        form.addRow(buttons)
        grid.addWidget(info, 0, 0)

        summary = panel()
        summary_layout = QVBoxLayout(summary)
        summary_layout.addWidget(QLabel("Case Summary"))
        self.case_summary = QTextEdit()
        self.case_summary.setReadOnly(True)
        self.case_summary.setPlainText(
            "Mock case contains 115 kV and 230 kV buses, existing branches, one out-of-service bus, "
            "one unsupported 69 kV bus, and one bus without coordinates."
        )
        summary_layout.addWidget(self.case_summary)
        grid.addWidget(summary, 0, 1)
        layout.addLayout(grid)
        layout.addStretch()
        return page

    def _contingencies_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("Contingencies", "Searchable contingency list. Real cases use schema-resolved PowerWorld fields."))
        tools = QHBoxLayout()
        self.ctg_search = QLineEdit()
        self.ctg_search.setPlaceholderText("Search contingencies")
        tools.addWidget(self.ctg_search)
        run_baseline = QPushButton("Run Baseline")
        run_baseline.clicked.connect(lambda: self.stack.setCurrentIndex(2))
        tools.addWidget(run_baseline)
        layout.addLayout(tools)
        self.ctg_model = ObjectTableModel(
            self.contingencies,
            [
                ("Contingency Name", lambda c: c.name),
                ("Category", lambda c: c.category),
                ("Skip", lambda c: c.skipped),
                ("Solved", lambda c: "" if c.solved is None else c.solved),
                ("Actions", lambda c: c.action_count or 0),
            ],
        )
        self.ctg_proxy = QSortFilterProxyModel()
        self.ctg_proxy.setSourceModel(self.ctg_model)
        self.ctg_proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.ctg_proxy.setFilterKeyColumn(-1)
        self.ctg_search.textChanged.connect(self.ctg_proxy.setFilterFixedString)
        self.ctg_table = QTableView()
        self._configure_table(self.ctg_table, self.ctg_proxy)
        layout.addWidget(self.ctg_table, 1)
        self.ctg_details = QTextEdit()
        self.ctg_details.setReadOnly(True)
        self.ctg_details.setMaximumHeight(110)
        self.ctg_details.setPlainText("Select a contingency to inspect actions. Phase 1 mock action details are static.")
        layout.addWidget(self.ctg_details)
        return page

    def _baseline_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("Baseline Results", "Mock baseline from CTG_102_103_LOSS. Select one overload as the study target."))
        status = QLabel("Status: contingency solved with thermal overloads and one low-voltage violation.")
        status.setObjectName("StatusGood")
        layout.addWidget(status)
        self.baseline_model = ObjectTableModel(
            self.baseline_overloads,
            [
                ("Branch", lambda v: v.branch_key),
                ("From Bus", lambda v: v.from_bus),
                ("To Bus", lambda v: v.to_bus),
                ("Circuit", lambda v: v.circuit_id),
                ("MVA", lambda v: v.mva),
                ("Rating", lambda v: v.rating_mva),
                ("% Loading", lambda v: v.percent_loading),
            ],
        )
        self.baseline_table = QTableView()
        self._configure_table(self.baseline_table, self.baseline_model)
        layout.addWidget(self.baseline_table, 2)
        self.voltage_model = ObjectTableModel(
            self.voltage_violations,
            [
                ("Bus", lambda v: v.bus_number),
                ("Name", lambda v: v.bus_name),
                ("Voltage pu", lambda v: v.voltage_pu),
                ("Limit pu", lambda v: v.limit_pu),
                ("Type", lambda v: v.violation_type),
            ],
        )
        voltage_table = QTableView()
        self._configure_table(voltage_table, self.voltage_model)
        layout.addWidget(QLabel("Voltage Violations"))
        layout.addWidget(voltage_table, 1)
        return page

    def _candidate_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("Candidate Setup", "Generate same-voltage candidate lines near the selected overloaded branch endpoints."))
        controls = panel()
        form = QFormLayout(controls)
        self.radius_spin = self._double_spin(50.0, 1.0, 500.0)
        self.min_length_spin = self._double_spin(1.0, 0.0, 500.0)
        self.max_length_spin = self._double_spin(50.0, 0.1, 500.0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["endpoints", "midpoint"])
        self.max_candidates = QSpinBox()
        self.max_candidates.setRange(1, 5000)
        self.max_candidates.setValue(250)
        self.voltage_filter = QComboBox()
        self.voltage_filter.addItems(["115 and 230", "115 only", "230 only"])
        self.allow_existing = QCheckBox("Allow existing corridors")
        self.allow_existing.setEnabled(False)
        form.addRow("Radius in miles", self.radius_spin)
        form.addRow("Minimum line length", self.min_length_spin)
        form.addRow("Maximum line length", self.max_length_spin)
        form.addRow("Geographic mode", self.mode_combo)
        form.addRow("Voltage class", self.voltage_filter)
        form.addRow("Area filter", QLineEdit())
        form.addRow("Zone filter", QLineEdit())
        form.addRow("Owner filter", QLineEdit())
        form.addRow("Existing direct branches", self.allow_existing)
        form.addRow("Maximum candidates", self.max_candidates)
        generate = QPushButton("Generate Candidates")
        generate.clicked.connect(self.generate_candidate_preview)
        form.addRow(generate)
        layout.addWidget(controls)
        self.candidate_summary = QLabel("No candidates generated yet.")
        layout.addWidget(self.candidate_summary)
        self.candidate_model = ObjectTableModel([], self._candidate_columns())
        self.candidate_table = QTableView()
        self._configure_table(self.candidate_table, self.candidate_model)
        layout.addWidget(self.candidate_table, 1)
        return page

    def _run_screening_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("Run Screening", "Mock screening populates representative classifications and timing."))
        top = QHBoxLayout()
        run = QPushButton("Run")
        run.clicked.connect(self.run_mock_screening)
        cancel = QPushButton("Cancel")
        cancel.setEnabled(False)
        top.addWidget(run)
        top.addWidget(cancel)
        top.addStretch()
        layout.addLayout(top)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        stats = QGridLayout()
        self.current_candidate = QLabel("-")
        self.completed_count = QLabel("0")
        self.total_count = QLabel("0")
        self.current_stage = QLabel("Idle")
        self.elapsed = QLabel("0.0 s")
        self.average = QLabel("0.0 s")
        self.remaining = QLabel("0.0 s")
        for row, (label, widget) in enumerate(
            [
                ("Current candidate", self.current_candidate),
                ("Completed", self.completed_count),
                ("Total", self.total_count),
                ("Current stage", self.current_stage),
                ("Elapsed", self.elapsed),
                ("Average duration", self.average),
                ("Estimated remaining", self.remaining),
            ]
        ):
            stats.addWidget(QLabel(label), row, 0)
            stats.addWidget(widget, row, 1)
        layout.addLayout(stats)
        self.live_log = QTextEdit()
        self.live_log.setReadOnly(True)
        layout.addWidget(self.live_log, 1)
        return page

    def _results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("Results", "Sortable and filterable mock candidate ranking."))
        tools = QHBoxLayout()
        self.result_search = QLineEdit()
        self.result_search.setPlaceholderText("Search visible result rows")
        tools.addWidget(self.result_search)
        self.class_filter = QComboBox()
        self.class_filter.addItem("All classifications")
        self.class_filter.addItems(["SOLVED", "SOLVED_WITH_TRADEOFF", "IMPROVED", "NO_EFFECT", "WORSE", "INTACT_FAILED", "CONTINGENCY_FAILED", "ERROR"])
        tools.addWidget(self.class_filter)
        self.success_only = QCheckBox("Show successful only")
        tools.addWidget(self.success_only)
        export_visible = QPushButton("Export Visible Results")
        export_visible.clicked.connect(self.export_all_results)
        tools.addWidget(export_visible)
        export_all = QPushButton("Export All Results")
        export_all.clicked.connect(self.export_all_results)
        tools.addWidget(export_all)
        layout.addLayout(tools)
        self.result_model = ObjectTableModel([], self._result_columns())
        self.result_proxy = QSortFilterProxyModel()
        self.result_proxy.setSourceModel(self.result_model)
        self.result_proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.result_proxy.setFilterKeyColumn(-1)
        self.result_search.textChanged.connect(self.result_proxy.setFilterFixedString)
        self.results_table = QTableView()
        self._configure_table(self.results_table, self.result_proxy)
        layout.addWidget(self.results_table, 1)
        self.detail_panel = QTextEdit()
        self.detail_panel.setReadOnly(True)
        self.detail_panel.setMaximumHeight(170)
        self.detail_panel.setPlainText("Select a result row to inspect candidate parameters, score breakdown, and violations.")
        layout.addWidget(self.detail_panel)
        self.results_table.selectionModel().selectionChanged.connect(self.update_result_details)
        return page

    def _conductor_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("Conductor Models", "Enter utility-approved conductor parameters before real candidate simulations. Units are shown in column names."))
        self.conductor_table = QTableWidget(0, 12)
        self.conductor_table.setHorizontalHeaderLabels(
            [
                "Key",
                "Name",
                "Nominal kV",
                "Bundle count",
                "R ohm/mile",
                "X ohm/mile",
                "Charging type",
                "Charging value/mile",
                "Rate A MVA",
                "Rate B MVA",
                "Rate C MVA",
                "Circuit count",
            ]
        )
        layout.addWidget(self.conductor_table, 1)
        buttons = QHBoxLayout()
        save = QPushButton("Save")
        save.clicked.connect(self.save_conductors_from_table)
        restore = QPushButton("Restore Defaults")
        restore.clicked.connect(self.restore_default_conductors)
        export = QPushButton("Export")
        export.clicked.connect(self.export_conductors)
        import_button = QPushButton("Import")
        import_button.clicked.connect(self.import_conductors)
        for button in [save, restore, import_button, export]:
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.conductor_validation = QLabel("")
        layout.addWidget(self.conductor_validation)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("Settings", "Phase 1 settings are persisted as JSON and reused by mock screening."))
        form_box = panel()
        form = QFormLayout(form_box)
        form.addRow("Mock mode", QLabel("Enabled"))
        form.addRow("System MVA base", QLabel(str(self.system_mva_base)))
        form.addRow("Voltage tolerance kV", QLabel(str(self.voltage_tolerance_kv)))
        form.addRow("Meaningful improvement threshold", QLabel(f"{self.settings['meaningful_improvement_threshold_pct_points']} percentage points"))
        form.addRow("Run history database", QLabel("user_data/run_history.sqlite"))
        layout.addWidget(form_box)
        layout.addStretch()
        return page

    def _logs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("Logs", "Application logs are written to user_data/logs. Diagnostic export excludes PowerWorld cases."))
        tools = QHBoxLayout()
        tools.addWidget(QLineEdit())
        severity = QComboBox()
        severity.addItems(["All severities", "INFO", "WARNING", "ERROR"])
        tools.addWidget(severity)
        open_folder = QPushButton("Open Log Folder")
        open_folder.clicked.connect(lambda: QMessageBox.information(self, APP_NAME, str(log_dir())))
        tools.addWidget(open_folder)
        layout.addLayout(tools)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text, 1)
        return page

    def _about_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(page_title("About", "Contingency Solver is a transmission reinforcement screening tool."))
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            "Version 0.1.0\n\n"
            "Phase 1 foundation and mock GUI.\n\n"
            "Mock data is simulated and must not be used for engineering decisions. "
            "PowerWorld SimAuto integration, baseline execution, and candidate branch insertion are scheduled for later phases."
        )
        layout.addWidget(text)
        return page

    def _populate_initial_data(self) -> None:
        self._populate_conductor_table()
        self._update_case_metrics()

    def browse_case(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            self,
            "Select PowerWorld Case",
            self.settings.get("last_case_directory", str(Path.cwd())),
            "PowerWorld Cases (*.pwb *.pwd *.aux);;All Files (*.*)",
        )
        if not path_text:
            return
        path = Path(path_text)
        self.case_path.setText(str(path))
        self.settings["last_case_directory"] = str(path.parent)
        self.settings_service.save_settings(self.settings)

    def test_simauto_connection(self) -> None:
        try:
            self.simauto_client.connect()
            version = self.simauto_client.get_version() or "Connected"
        except (SimAutoUnavailableError, SimAutoCommandError) as exc:
            LOGGER.exception("SimAuto connection test failed.")
            self.powerworld_connection_label.setText("Connection failed")
            self.connection_status.setText("PowerWorld: unavailable")
            QMessageBox.critical(self, APP_NAME, self._readable_powerworld_error(exc))
            return
        self.powerworld_connection_label.setText("Connected")
        self.powerworld_version_label.setText(version)
        self.connection_status.setText("PowerWorld: connected")
        QMessageBox.information(self, APP_NAME, "PowerWorld SimAuto connection succeeded.")

    def load_selected_case(self) -> None:
        path = Path(self.case_path.text().strip())
        if not path.exists():
            QMessageBox.warning(self, APP_NAME, "Select an existing PowerWorld case file first.")
            return
        try:
            self.case_manager.open_case(path)
            self.buses = self.case_manager.read_buses(self.voltage_tolerance_kv)
            self.branches = self.case_manager.read_branches()
            self.contingencies = self.contingency_service.read_contingencies()
        except (FileNotFoundError, SimAutoUnavailableError, SimAutoCommandError, SchemaResolutionError, ValueError) as exc:
            LOGGER.exception("Case loading failed.")
            QMessageBox.critical(self, APP_NAME, self._readable_powerworld_error(exc))
            return

        self.real_case_loaded = True
        self.selected_branch = self.branches[0] if self.branches else Branch(0, 0)
        self.candidates = []
        self.results = []
        self.candidate_model.set_rows([])
        self.result_model.set_rows([])
        self.ctg_model.set_rows(self.contingencies)
        self.case_status.setText(f"Case: {path.name}")
        self.connection_status.setText("PowerWorld: connected")
        self.run_status.setText("Run: idle")
        self._update_case_metrics(path)
        self.case_summary.setPlainText(
            f"Loaded real PowerWorld case: {path}\n\n"
            f"Buses read: {len(self.buses)}\n"
            f"Branches read: {len(self.branches)}\n"
            f"Contingencies read: {len(self.contingencies)}\n\n"
            "Phase 2 reads case data only. Baseline contingency execution and real result collection start in Phase 3."
        )
        LOGGER.info("Loaded real case data from %s.", path)

    def reload_mock_data(self) -> None:
        self.buses = mock_buses()
        self.branches = mock_branches()
        self.contingencies = mock_contingencies()
        self.baseline_overloads = mock_baseline_overloads()
        self.voltage_violations = mock_voltage_violations()
        self.candidates = []
        self.results = []
        self.selected_branch = self.branches[1]
        self.real_case_loaded = False
        self.case_path.setText("Mock sample case - no confidential case loaded")
        self.ctg_model.set_rows(self.contingencies)
        self.candidate_model.set_rows([])
        self.result_model.set_rows([])
        self.case_status.setText("Case: Mock sample case")
        self.connection_status.setText("PowerWorld: mock")
        self.ctg_status.setText("Contingency: CTG_102_103_LOSS")
        self.candidate_status.setText("Candidates: 0")
        self.powerworld_connection_label.setText(MOCK_MODE_LABEL)
        self.powerworld_version_label.setText("Unavailable in mock mode")
        self._update_case_metrics()
        self.case_summary.setPlainText(
            "Mock case contains 115 kV and 230 kV buses, existing branches, one out-of-service bus, "
            "one unsupported 69 kV bus, and one bus without coordinates."
        )
        LOGGER.info("Reloaded mock data.")

    def _update_case_metrics(self, path: Path | None = None) -> None:
        supported = len(
            [
                bus
                for bus in self.buses
                if any(abs(bus.nominal_kv - supported_kv) <= self.voltage_tolerance_kv for supported_kv in (115.0, 230.0))
            ]
        )
        coord = len([bus for bus in self.buses if bus.has_valid_coordinates])
        self.bus_count_label.setText(str(len(self.buses)))
        self.branch_count_label.setText(str(len(self.branches)))
        self.supported_bus_count_label.setText(str(supported))
        self.coordinate_summary_label.setText(f"{coord} of {len(self.buses)} buses have valid coordinates")
        if path is not None:
            self.case_path.setText(str(path))

    def _readable_powerworld_error(self, exc: Exception) -> str:
        if isinstance(exc, SchemaResolutionError):
            return str(exc)
        if isinstance(exc, SimAutoCommandError):
            return f"PowerWorld operation failed.\n\nOperation: {exc.operation}\nRaw SimAuto error: {exc.raw_error}"
        return str(exc)

    def generate_candidate_preview(self) -> None:
        if not self.branches:
            QMessageBox.warning(self, APP_NAME, "No branches are available for candidate generation.")
            return
        if self.selected_branch.from_bus == 0 and self.selected_branch.to_bus == 0:
            QMessageBox.warning(self, APP_NAME, "Select a valid overloaded branch before generating candidates.")
            return
        voltage_text = self.voltage_filter.currentText()
        if voltage_text == "115 only":
            voltage_classes = (115.0,)
        elif voltage_text == "230 only":
            voltage_classes = (230.0,)
        else:
            voltage_classes = (115.0, 230.0)
        settings = CandidateGenerationSettings(
            radius_miles=float(self.radius_spin.value()),
            minimum_length_miles=float(self.min_length_spin.value()),
            maximum_length_miles=float(self.max_length_spin.value()),
            voltage_classes=voltage_classes,
            voltage_tolerance_kv=self.voltage_tolerance_kv,
            study_area_mode=self.mode_combo.currentText(),
            maximum_candidates=int(self.max_candidates.value()),
        )
        self.candidates, summary = generate_candidates(self.buses, self.branches, self.selected_branch, settings)
        self.candidate_model.set_rows(self.candidates)
        warning_text = " ".join(summary.warnings)
        self.candidate_summary.setText(
            f"Buses found: {summary.buses_found} | Candidate pairs generated: {summary.candidates_generated}. {warning_text}"
        )
        self.candidate_status.setText(f"Candidates: {len(self.candidates)}")
        source = "real case" if self.real_case_loaded else "mock"
        self.live_log.append(f"Generated {len(self.candidates)} candidates from {source} data.")
        LOGGER.info("Generated %s candidates from %s data.", len(self.candidates), source)

    def run_mock_screening(self) -> None:
        if not self.candidates:
            self.generate_candidate_preview()
        self.current_stage.setText("Collecting mock results")
        self.run_status.setText("Run: mock screening")
        self.total_count.setText(str(len(self.candidates)))
        self.progress.setMaximum(max(1, len(self.candidates)))
        self.progress.setValue(len(self.candidates))
        self.completed_count.setText(str(len(self.candidates)))
        if self.candidates:
            self.current_candidate.setText(f"{self.candidates[-1].from_bus}-{self.candidates[-1].to_bus}")
        self.results = simulate_results(self.candidates)
        self.result_model.set_rows(self.results)
        total_runtime = sum(result.runtime_seconds for result in self.results)
        average = total_runtime / len(self.results) if self.results else 0.0
        self.elapsed.setText(f"{total_runtime:.1f} s")
        self.average.setText(f"{average:.1f} s")
        self.remaining.setText("0.0 s")
        self.current_stage.setText("Complete")
        self.run_status.setText("Run: mock complete")
        self.live_log.append(f"Mock screening complete. {len(self.results)} results ranked.")
        self.history_service.save_mock_run("CTG_102_103_LOSS", "102-103-1", self.settings, self.results)
        self.stack.setCurrentIndex(5)
        LOGGER.info("Mock screening completed with %s results.", len(self.results))

    def export_all_results(self) -> None:
        if not self.results:
            QMessageBox.warning(self, APP_NAME, "No results are available to export.")
            return
        default_path = exports_dir() / "contingency_solver_mock_results.xlsx"
        path_text, _ = QFileDialog.getSaveFileName(self, "Export Results", str(default_path), "Excel Workbook (*.xlsx);;CSV (*.csv)")
        if not path_text:
            return
        path = Path(path_text)
        if path.suffix.lower() == ".csv":
            self.export_service.export_results_csv(self.results, path)
        else:
            self.export_service.export_results_excel(self.results, path, self.conductor_models, self.settings)
        QMessageBox.information(self, APP_NAME, f"Exported results to {path}")

    def update_result_details(self) -> None:
        indexes = self.results_table.selectionModel().selectedRows()
        if not indexes:
            return
        source_index = self.result_proxy.mapToSource(indexes[0])
        result = self.result_model.row_object(source_index.row())
        components = "\n".join(f"  {key}: {value:.2f}" for key, value in result.score_components.items())
        self.detail_panel.setPlainText(
            f"Candidate {result.from_bus} {result.from_bus_name} to {result.to_bus} {result.to_bus_name}\n"
            f"Classification: {result.classification}\n"
            f"Distance: {result.distance_miles:.2f} miles | Nominal kV: {result.nominal_kv:.0f}\n"
            f"Selected overload: {result.original_loading_pct:.2f}% -> {result.new_loading_pct:.2f}%\n"
            f"New thermal violations: {result.new_thermal_violation_count}; new voltage violations: {result.new_voltage_violation_count}\n"
            f"Score breakdown:\n{components}\n"
            f"Error: {result.error_message or 'None'}"
        )

    def save_conductors_from_table(self) -> None:
        models: dict[str, ConductorModel] = {}
        for row in range(self.conductor_table.rowCount()):
            key = self.conductor_table.item(row, 0).text().strip()
            models[key] = ConductorModel(
                key=key,
                name=self.conductor_table.item(row, 1).text().strip(),
                nominal_kv=float(self.conductor_table.item(row, 2).text()),
                bundle_count=int(float(self.conductor_table.item(row, 3).text())),
                resistance_ohm_per_mile=float(self.conductor_table.item(row, 4).text()),
                reactance_ohm_per_mile=float(self.conductor_table.item(row, 5).text()),
                charging_input_type=self.conductor_table.item(row, 6).text().strip(),
                charging_value_per_mile=float(self.conductor_table.item(row, 7).text()),
                rate_a_mva=float(self.conductor_table.item(row, 8).text()),
                rate_b_mva=float(self.conductor_table.item(row, 9).text()),
                rate_c_mva=float(self.conductor_table.item(row, 10).text()),
                circuit_count=int(float(self.conductor_table.item(row, 11).text())),
            )
        errors = validate_conductor_models(models)
        if errors:
            self.conductor_validation.setText("; ".join(errors))
            return
        self.conductor_models = models
        self.settings_service.save_conductor_models(self.system_mva_base, self.voltage_tolerance_kv, models)
        self.conductor_validation.setText("Conductor models saved.")
        LOGGER.info("Saved conductor models.")

    def restore_default_conductors(self) -> None:
        self.settings_service.restore_default_conductors()
        self.system_mva_base, self.voltage_tolerance_kv, self.conductor_models = self.settings_service.load_conductor_models()
        self._populate_conductor_table()

    def export_conductors(self) -> None:
        path_text, _ = QFileDialog.getSaveFileName(self, "Export Conductors", str(exports_dir() / "conductor_models.json"), "JSON (*.json)")
        if path_text:
            self.settings_service.export_conductors(Path(path_text))

    def import_conductors(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(self, "Import Conductors", str(Path.cwd()), "JSON (*.json)")
        if path_text:
            self.settings_service.import_conductors(Path(path_text))
            self.system_mva_base, self.voltage_tolerance_kv, self.conductor_models = self.settings_service.load_conductor_models()
            self._populate_conductor_table()

    def _populate_conductor_table(self) -> None:
        self.conductor_table.setRowCount(len(self.conductor_models))
        for row, model in enumerate(self.conductor_models.values()):
            values = [
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
            ]
            for column, value in enumerate(values):
                self.conductor_table.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))
        self.conductor_table.resizeColumnsToContents()

    def _candidate_columns(self) -> list[tuple[str, Any]]:
        return [
            ("From Bus", lambda c: c.from_bus),
            ("From Name", lambda c: c.from_bus_name),
            ("To Bus", lambda c: c.to_bus),
            ("To Name", lambda c: c.to_bus_name),
            ("Nominal kV", lambda c: c.nominal_kv),
            ("Conductor", lambda c: c.conductor_key),
            ("Distance miles", lambda c: c.distance_miles),
        ]

    def _result_columns(self) -> list[tuple[str, Any]]:
        return [
            ("Rank", lambda r: r.rank),
            ("Score", lambda r: r.score),
            ("Classification", lambda r: r.classification),
            ("From Bus", lambda r: r.from_bus),
            ("From Name", lambda r: r.from_bus_name),
            ("To Bus", lambda r: r.to_bus),
            ("To Name", lambda r: r.to_bus_name),
            ("Nominal kV", lambda r: r.nominal_kv),
            ("Conductor", lambda r: r.conductor_model),
            ("Distance", lambda r: r.distance_miles),
            ("Original %", lambda r: r.original_loading_pct),
            ("New %", lambda r: r.new_loading_pct),
            ("Reduction pp", lambda r: r.loading_reduction_pct_points),
            ("Original MVA", lambda r: r.original_mva),
            ("New MVA", lambda r: r.new_mva),
            ("Removed", lambda r: r.selected_overload_removed),
            ("New Thermal", lambda r: r.new_thermal_violation_count),
            ("Worst New Thermal", lambda r: r.worst_new_thermal_violation),
            ("New Voltage", lambda r: r.new_voltage_violation_count),
            ("Min V", lambda r: r.minimum_voltage),
            ("Max V", lambda r: r.maximum_voltage),
            ("Intact", lambda r: r.intact_solved),
            ("Contingency", lambda r: r.contingency_solved),
            ("Runtime", lambda r: r.runtime_seconds),
            ("Error", lambda r: r.error_message),
        ]

    def _configure_table(self, table: QTableView, model: Any) -> None:
        table.setModel(model)
        table.setSortingEnabled(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        table.resizeColumnsToContents()

    def _double_spin(self, value: float, minimum: float, maximum: float) -> Any:
        from PySide6.QtWidgets import QDoubleSpinBox

        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setValue(value)
        spin.setSuffix(" mi" if maximum > 100.0 else "")
        return spin

    def _apply_style(self) -> None:
        QApplication.instance().setStyleSheet(
            """
            QMainWindow, QWidget { background: #f6f7f9; color: #1f2933; font-size: 10pt; }
            #NavigationList { background: #202833; color: #e8edf2; border: 0; padding: 8px; }
            #NavigationList::item { padding: 10px 12px; border-radius: 4px; }
            #NavigationList::item:selected { background: #3b556f; color: white; }
            #PageTitle { font-size: 20pt; font-weight: 600; color: #14212b; }
            #PageSubtitle { color: #51606f; }
            #Panel { background: white; border: 1px solid #d8dee5; border-radius: 6px; padding: 10px; }
            QTableView, QTableWidget, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background: white; border: 1px solid #cfd6de; border-radius: 4px; padding: 4px;
            }
            QPushButton { background: #2f5f8f; color: white; border: 0; border-radius: 4px; padding: 7px 12px; }
            QPushButton:disabled { background: #aeb8c2; }
            QPushButton:hover { background: #254d75; }
            QHeaderView::section { background: #e8edf2; padding: 5px; border: 0; border-right: 1px solid #d1d8e0; }
            #StatusGood { color: #116329; font-weight: 600; }
            """
        )
