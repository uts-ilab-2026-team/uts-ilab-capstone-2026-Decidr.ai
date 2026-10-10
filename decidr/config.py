import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Load environment variables from .env file if it exists
load_dotenv()

# Paths
PROJ_ROOT = Path(__file__).resolve().parents[1]
logger.info(f"PROJ_ROOT path is: {PROJ_ROOT}")

DATA_DIR = PROJ_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
EXTERNAL_DATA_DIR = DATA_DIR / "external"

MODELS_DIR = PROJ_ROOT / "models"

# Client data stays outside the repository. These values can be overridden in a
# local .env file on each team member's computer.
DEFAULT_CLIENT_DATA_ROOT = PROJ_ROOT.parent / "Decidr Capstone Project" / "04 Data" / "01 Raw"
CLIENT_DATA_ROOT = Path(os.getenv("DECIDR_CLIENT_DATA_ROOT", DEFAULT_CLIENT_DATA_ROOT))
PHASE1_DATA_DIR = Path(
    os.getenv("DECIDR_PHASE1_DATA_DIR", CLIENT_DATA_ROOT / "phase1_framework_development")
)
PHASE2_DATA_DIR = Path(
    os.getenv("DECIDR_PHASE2_DATA_DIR", CLIENT_DATA_ROOT / "phase2_model_development")
)
DATABASE_PATH = Path(os.getenv("DECIDR_DATABASE_PATH", PROCESSED_DATA_DIR / "evidence.sqlite3"))

REPORTS_DIR = PROJ_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

# If tqdm is installed, configure loguru with tqdm.write
# https://github.com/Delgan/loguru/issues/135
try:
    from tqdm import tqdm

    logger.remove(0)
    logger.add(lambda msg: tqdm.write(msg, end=""), colorize=True)
except ModuleNotFoundError:
    pass
