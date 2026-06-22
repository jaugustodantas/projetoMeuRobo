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


def _resolve_project_path(value: str, default: str) -> Path:
    path = Path(value.strip() or default)
    if path.is_absolute():
        return path

    return ROOT_DIR / path


def get_agente_rh_path() -> Path:
    return _resolve_project_path(
        os.getenv("AGENTE_RH_PATH", ""),
        "private/agent_context/agenteRh.md",
    )


def get_cv_path() -> Path:
    return _resolve_project_path(
        os.getenv("CV_PATH", ""),
        "private/agent_context/cv.md",
    )


def get_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não configurada no arquivo .env")

    return api_key


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.5").strip() or "gpt-5.5"


def get_ai_provider() -> str:
    provider = os.getenv("AI_PROVIDER", "ollama").strip().lower() or "ollama"
    if provider not in {"ollama", "openai"}:
        raise RuntimeError("AI_PROVIDER deve ser 'ollama' ou 'openai'")
    return provider


def get_ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").strip().rstrip("/")


def get_ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", "gemma3:4b").strip() or "gemma3:4b"


def get_ollama_num_ctx() -> int:
    try:
        num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
    except ValueError as exc:
        raise RuntimeError("OLLAMA_NUM_CTX deve ser um número inteiro") from exc

    if num_ctx < 8192:
        raise RuntimeError("OLLAMA_NUM_CTX deve ser pelo menos 8192")
    return num_ctx
