from __future__ import annotations

from .m26_admin_audit import install_admin_audit
from .m26_admin_control_plane import install_admin_control_plane
from .m26_admin_corpus import install_admin_corpus
from .m26_admin_health import install_admin_health
from .m26_admin_ingestion import install_admin_ingestion_routes
from .m26_admin_overview import install_admin_overview
from .m26_admin_qa import install_admin_qa
from .m26_admin_settings import install_admin_settings
from .m26_admin_usage import install_admin_usage
from .m26_console_p05_ask_playground import router as playground_router
from .m26_golden_questions_admin import install_golden_questions_admin
from .m26_jobs_rollback_api import install_jobs_rollback_routes
from .m26_suggested_questions_admin import install_suggested_questions_admin
from .m26_translation_gateway_public_api import create_app as create_public_app


def create_app():
    app = create_public_app()
    install_admin_control_plane(app)
    install_admin_overview(app)
    install_admin_ingestion_routes(app, include_job_reads=False)
    install_admin_corpus(app)
    install_admin_qa(app)
    app.include_router(playground_router())
    install_suggested_questions_admin(app)
    install_admin_usage(app)
    install_admin_health(app)
    install_jobs_rollback_routes(app)
    install_golden_questions_admin(app)
    install_admin_settings(app)
    install_admin_audit(app)
    app.title = "M26 LLM-Wiki Public + Admin API"
    return app


app = create_app()


__all__ = ["app", "create_app"]
