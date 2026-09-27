"""Configuration — loads credentials from .env."""

from __future__ import annotations

import os
from pathlib import Path

# Load .env from the change-investigator directory (or cwd)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
    else:
        load_dotenv()  # try cwd
except ImportError:
    pass  # dotenv optional; env vars may be set externally


def get_watsonx_url() -> str:
    url = os.environ.get("WATSONX_URL", "")
    if not url:
        raise EnvironmentError(
            "WATSONX_URL is not set. Copy .env.example to .env and fill in your credentials."
        )
    return url.rstrip("/")


def get_watsonx_apikey() -> str:
    key = os.environ.get("WATSONX_APIKEY", "")
    if not key:
        raise EnvironmentError(
            "WATSONX_APIKEY is not set. Copy .env.example to .env and fill in your credentials."
        )
    return key


def get_watsonx_project_id() -> str:
    pid = os.environ.get("WATSONX_PROJECT_ID", "")
    if not pid:
        raise EnvironmentError(
            "WATSONX_PROJECT_ID is not set. Copy .env.example to .env and fill in your credentials."
        )
    return pid


def get_model_id() -> str:
    return os.environ.get("WATSONX_MODEL_ID", "ibm/granite-3-3-8b-instruct")


def watsonx_configured() -> bool:
    """Return True if all watsonx credentials are present."""
    return all([
        os.environ.get("WATSONX_URL"),
        os.environ.get("WATSONX_APIKEY"),
        os.environ.get("WATSONX_PROJECT_ID"),
    ])
