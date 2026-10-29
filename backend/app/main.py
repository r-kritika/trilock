import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routes_auth, routes_misc, routes_recovery, routes_transactions, routes_users
from dataclasses import dataclass

from .biometrics.face import FaceModule
from .biometrics.liveness import FaceLiveness
from .biometrics.registry import BiometricRegistry, build_registry
from .biometrics.voice_liveness import SpokenChallenge
from .config import Settings, get_settings
from .database import init_db, make_engine, make_session_factory
from .errors import install_error_handlers
from .services.challenges import ChallengeStore
from .services.fusion import load_policy_config
from .services.templates import TemplateStore

logging.basicConfig(level=logging.INFO)


@dataclass
class LivenessServices:
    """face: head-turn checker, spoken: phrase checker. Either may be None (then liveness fails closed)."""
    face: object | None
    spoken: object | None

    def status(self) -> dict:
        spoken_ok, spoken_detail = self.spoken.status() if self.spoken else (False, "not configured")
        return {"face": {"available": self.face is not None, "detail": "head-turn challenge (landmark geometry)" if self.face else "face module unavailable"},
                "voice": {"available": spoken_ok, "detail": spoken_detail}}


def create_app(settings: Settings | None = None, registry: BiometricRegistry | None = None,
               liveness: LivenessServices | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.db_url)
    init_db(engine)
    risk_cfg, fusion_cfg = load_policy_config(settings.policy_file)

    app = FastAPI(title="TriLock API", version=routes_misc.VERSION,
                  description="Academic prototype: risk-adaptive multimodal biometric authentication for simulated banking.")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.registry = registry or build_registry(settings)
    face_module = app.state.registry.modules.get("face")
    app.state.liveness = liveness or LivenessServices(
        face=FaceLiveness(face_module) if isinstance(face_module, FaceModule) else None,
        spoken=SpokenChallenge(settings.models_dir, settings.spoken_words_needed))
    app.state.challenges = ChallengeStore(settings.liveness_ttl_seconds)
    app.state.templates = TemplateStore(settings.templates_dir, settings.template_key)
    app.state.risk_cfg, app.state.fusion_cfg = risk_cfg, fusion_cfg

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
    install_error_handlers(app)
    for r in (routes_misc.router, routes_auth.router, routes_users.router, routes_recovery.router, routes_transactions.router):
        app.include_router(r, prefix="/api")
    return app


def get_app() -> FastAPI:
    return create_app()
