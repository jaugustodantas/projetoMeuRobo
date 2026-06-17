import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]

load_dotenv(ROOT_DIR / ".env")


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL não configurada no arquivo .env")

    return database_url


def get_linkedin_credentials() -> tuple[str, str] | None:
    email = os.getenv("LINKEDIN_EMAIL", "").strip()
    password = os.getenv("LINKEDIN_PASSWORD", "").strip()

    if not email or not password:
        return None

    return email, password


def get_browser_session_path() -> Path:
    return ROOT_DIR / "browser_session" / "linkedin_state.json"


def get_exports_dir() -> Path:
    exports_dir = ROOT_DIR / "exports"
    exports_dir.mkdir(exist_ok=True)
    return exports_dir
