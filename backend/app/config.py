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
    # Lockouts are scoped to WHO failed (device and network), not to the whole account, so an attacker
    # cannot lock the real owner out. All counts are within the window below.
    login_lock_minutes: int = 15                # length of the counting window and of each block
    max_failed_logins: int = 5                  # unknown device or network, per account
    trusted_device_failed_logins: int = 10      # the owner's own known device (typos), per device
    ip_failed_logins: int = 20                  # one network address, across all accounts
    account_untrusted_failed_logins: int = 30   # all unknown sources together; known devices are exempt
    max_new_devices_per_day: int = 3            # new devices that may sign in to one account per 24 h
    established_device_hours: int = 24          # a device this old keeps working during an attack
    trust_proxy_headers: bool = False           # read X-Forwarded-For (only behind a proxy you control)
    # Changing biometrics on an account that already has some needs this many matching proof samples
    # (or all of them if fewer are enrolled), on top of the password.
    enrollment_proof_modalities: int = 2
    biometric_failure_limit: int = 5            # failed biometric tries per device/network
    biometric_user_failure_limit: int = 15      # per account across all sources; established devices exempt
    biometric_window_minutes: int = 15
    # Recovery when someone cannot provide their enrolled biometrics (see docs/SECURITY.md)
    recovery_cooling_hours: int = 24            # an admin cannot approve a request before this has passed
    probation_hours: int = 72                   # after a reset, high-value transactions stay disabled this long
    # Sign-in: password, then live face AND voice for accounts that have both enrolled (admins use the password only).
    # "off" gives password-only sign-in, for setups where the camera, microphone or recognizer are unavailable.
    login_biometrics: Literal["required", "off"] = "required"
    login_liveness: bool = True                 # require the head turn and the spoken words at sign-in
    preauth_minutes: int = 5                    # time allowed between the password and the biometric step
    preauth_max_attempts: int = 5               # biometric tries per password entry
    # Liveness (see docs/SECURITY.md for what it does and does not stop)
    liveness_required_from: Literal["low", "medium", "high", "critical", "never"] = "high"
    liveness_ttl_seconds: int = 90
    spoken_words_needed: int = 2                # of the 3 challenge words that must be recognised (measured: see EVALUATION.md)
    liveness_failure_limit: int = 10            # failed liveness challenges per device/network in the window
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
