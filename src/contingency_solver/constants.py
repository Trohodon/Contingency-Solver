from pathlib import Path

APP_NAME = "Contingency Solver"
MOCK_MODE_LABEL = "MOCK MODE - simulated data"
SUPPORTED_VOLTAGE_CLASSES = (115.0, 230.0)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "default_settings.json"
DEFAULT_CONDUCTOR_MODELS_PATH = CONFIG_DIR / "conductor_models.json"
