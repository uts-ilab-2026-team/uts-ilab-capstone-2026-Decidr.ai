from dotenv import load_dotenv
from loguru import logger

from decidr.constants import DATA_DIR
from decidr.constants import REPO_ROOT as PROJ_ROOT

# Load environment variables from .env file if it exists
load_dotenv()

# Paths (PROJ_ROOT / DATA_DIR are the single-source values from decidr.constants)
logger.info(f"PROJ_ROOT path is: {PROJ_ROOT}")

RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# If tqdm is installed, configure loguru with tqdm.write
# https://github.com/Delgan/loguru/issues/135
try:
    from tqdm import tqdm

    logger.remove(0)
    logger.add(lambda msg: tqdm.write(msg, end=""), colorize=True)
except ModuleNotFoundError:
    pass
