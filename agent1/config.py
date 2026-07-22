import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path("/opt/unsolved-channel")
AGENT_DIR = BASE_DIR / "agent1"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "output"

load_dotenv(AGENT_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()

MAX_ARTICLES_PER_QUERY = int(os.getenv("MAX_ARTICLES_PER_QUERY", "10"))
MAX_CASES_PER_RUN = int(os.getenv("MAX_CASES_PER_RUN", "25"))
MIN_ACCEPT_SCORE = int(os.getenv("MIN_ACCEPT_SCORE", "65"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "25"))

USER_AGENT = "Mozilla/5.0 (compatible; UnsolvedCaseResearchBot/1.0)"

SEARCH_QUERIES = [
    '"cold case" unsolved murder',
    '"unsolved disappearance" police',
    '"missing person" cold case investigation',
    '"unidentified person" police seeking information',
    '"cold case reopened" investigators',
    '"remains unidentified" police appeal',
    '"unsolved homicide" reward information',
    '"new evidence" cold case',
]
