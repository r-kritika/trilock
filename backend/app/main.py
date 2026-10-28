import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routes_auth, routes_misc, routes_transactions, routes_users
from .biometrics.registry import BiometricRegistry, build_registry
from .config import Settings, get_settings
from .database import init_db, make_engine, make_session_factory
from .errors import install_error_handlers
from .services.fusion import load_policy_config
from .services.templates import TemplateStore

logging.basicConfig(level=logging.INFO)


def create_app(settings: Settings | None = None, registry: BiometricRegistry | None = None) -> FastAPI:
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
    app.state.templates = TemplateStore(settings.templates_dir, settings.template_key)
    app.state.risk_cfg, app.state.fusion_cfg = risk_cfg, fusion_cfg

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
    install_error_handlers(app)
    for r in (routes_misc.router, routes_auth.router, routes_users.router, routes_transactions.router):
        app.include_router(r, prefix="/api")
    return app


def get_app() -> FastAPI:
    return create_app()
