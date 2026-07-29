# Contingency Solver

Contingency Solver is a professional Windows desktop application for transmission reinforcement screening. It is designed to connect to PowerWorld Simulator through the SimAuto COM interface, run a selected contingency, identify overloads, generate same-voltage candidate line additions from bus coordinates, and rank the candidates by their simulated effect.

The current build includes the Phase 1 mock-mode foundation plus initial Phase 2 SimAuto connection and case-reading support. It can test a PowerWorld SimAuto connection, open a selected case, inspect configured field alternatives, and read buses, branches, and contingencies when PowerWorld is available on Windows.

## Installation

Use Python 3.12 or a similarly stable version.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -r requirements.txt
```

On Linux/WSL test environments, use the equivalent `python3 -m venv .venv` and `.venv/bin/python`.

PowerWorld connectivity requires Windows, PowerWorld Simulator with SimAuto access, and `pywin32`. The dependency is included conditionally for Windows installs.

## Start in Mock Mode

```bash
python run_app.py
```

Mock mode loads simulated buses, branches, contingencies, baseline overloads, candidate lines, and ranked results. The UI labels mock data clearly. Do not use mock results for engineering decisions.

## PowerWorld and SimAuto

The project contains a central schema file at `config/powerworld_schema.json` where object types, candidate field names, and script commands are listed. During case reading, the adapter asks PowerWorld for available fields and resolves configured alternatives. If no configured alternative is available, the application stops with a readable error instead of guessing.

Use the Case Setup page to:

1. Test the SimAuto connection.
2. Select a `.pwb`, `.pwd`, or `.aux` case file.
3. Load the case.
4. Read bus, branch, and contingency tables through schema-resolved fields.

Baseline contingency execution is still planned for Phase 3.

## Conductor Models

Conductor models are stored in JSON and editable from the Conductor Models page. Values include nominal voltage, bundle count, resistance and reactance in ohms per mile, charging input type and value per mile, rates A/B/C in MVA, and circuit count.

The first version supports only 115 kV and 230 kV line models. Candidate simulations validate required conductor values before use.

## Candidate Generation

Phase 1 generates candidates from mock bus coordinates using the Haversine distance in miles. Candidates are rejected when they are cross-voltage, unsupported voltage, self-connections, duplicate pairs, existing direct branches, out-of-service buses, missing coordinates, or outside configured length/radius limits.

The default study area is centered around the selected overloaded branch endpoints. Midpoint mode is also available.

## Classifications and Scores

Mock results use the configured classification names: `SOLVED`, `SOLVED_WITH_TRADEOFF`, `IMPROVED`, `NO_EFFECT`, `WORSE`, `INTACT_FAILED`, `CONTINGENCY_FAILED`, and `ERROR`.

Scores store separate components for loading reduction, overload removal, new thermal violations, new voltage violations, line length, and solution failure so the ranking is transparent.

## Case Restoration

Real case restoration is planned for Phase 4. The intended default is to use a temporary working copy and reload it before every candidate unless a more reliable PowerWorld state-save/state-restore method is confirmed.

## Export

The Results page exports mock results to Excel or CSV. Excel workbooks include run summary, candidate results, candidate parameters, conductor models, run settings, and errors.

## Run Tests

```bash
pytest
```

## Confidentiality

The application should not store entire PowerWorld cases or confidential case data. Phase 1 stores only user settings, conductor models, logs, and optional mock run history in `user_data`.

## Known Limitations

Baseline contingency execution, branch insertion, real result collection, real case restoration, cancellation around COM calls, and Windows packaging are not implemented yet. PowerWorld case reading depends on the installed version exposing compatible fields or updating `config/powerworld_schema.json`.

## Troubleshooting

If PySide6 fails to start on a headless environment, set:

```bash
export QT_QPA_PLATFORM=offscreen
```

On Windows, launch from an activated virtual environment so `PySide6`, `pandas`, and `openpyxl` are available.
