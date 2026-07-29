from pathlib import Path

from contingency_solver.constants import PROJECT_ROOT


def user_data_dir() -> Path:
    path = PROJECT_ROOT / "user_data"
    path.mkdir(exist_ok=True)
    return path


def log_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(exist_ok=True)
    return path


def exports_dir() -> Path:
    path = user_data_dir() / "exports"
    path.mkdir(exist_ok=True)
    return path
