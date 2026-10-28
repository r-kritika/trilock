"""Application settings. Everything can be overridden with TRILOCK_* env vars or backend/.env."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRILOCK_", env_file=".env", extra="ignore")

    data_dir: Path = BACKEND_DIR / "data"
    models_dir: Path = BACKEND_DIR / "models"
    database_url: str | None = None
    template_key: str | None = None
    policy_file: Path | None = None
    active_policy: Literal["fixed", "risk_aware"] = "risk_aware"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # After this many non-approved attempts a transaction is locked as rejected.
    max_auth_attempts: int = 3

    # Upload limits
    max_image_bytes: int = 8 * 1024 * 1024
    max_audio_bytes: int = 12 * 1024 * 1024

    # Authentication / abuse limits
    allow_registration: bool = True            # open self-registration (prototype). Turn off for anything shared.
    session_hours: int = 8
    min_password_length: int = 10
    max_failed_logins: int = 5
    login_lock_minutes: int = 15
    biometric_failure_limit: int = 5           # failed biometric tries per user within the window
    biometric_window_minutes: int = 15
    # Showing raw and calibrated scores to ordinary users helps a demo but lets an attacker
    # hill-climb a sample against the matcher. Admins always see them.
    expose_scores_to_users: bool = True

    # Voice input constraints (seconds)
    voice_min_seconds: float = 2.0
    voice_max_seconds: float = 20.0

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'trilock.db'}"

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def evaluation_dir(self) -> Path:
        return self.data_dir / "evaluation"


@lru_cache
def get_settings() -> Settings:
    return Settings()
