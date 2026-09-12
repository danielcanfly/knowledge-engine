from __future__ import annotations

from .m26_admin_audit import install_admin_audit
from .m26_admin_control_plane import install_admin_control_plane
from .m26_admin_corpus import install_admin_corpus, object_store_corpus_adapter_from_env
from .m26_admin_health import install_admin_health
from .m26_admin_ingestion import install_admin_ingestion_routes
from .m26_admin_overview import install_admin_overview
from .m26_admin_production import production_admin_runtime_from_env
from .m26_admin_settings import CANONICAL_ADMIN_API_VERSION, install_admin_settings
from .m26_admin_usage import install_admin_usage
from .m26_console_p05_ask_playground import router as playground_router
from .m26_golden_questions_admin import install_golden_questions_admin
from .m26_ingestion_runtime import (
    CombinedCapabilityProvider,
    build_runtime_ingestion_adapter_from_env,
)
from .m26_jobs_rollback_api import install_jobs_rollback_routes
from .m26_public_api import create_app as create_public_app
from .m26_qa_inbox_integration import install_qa_inbox
from .m26_sqlite_ingestion import SQLiteIngestionAdapter
from .m26_suggested_questions_admin import install_suggested_questions_admin


def create_app():
    app = create_public_app()
    production_admin = production_admin_runtime_from_env()
    durable_adapter = build_runtime_ingestion_adapter_from_env()
    durable_store = (
        durable_adapter.ledger if isinstance(durable_adapter, SQLiteIngestionAdapter) else None
    )
    if production_admin is None:
        install_admin_control_plane(app, idempotency_store=durable_store)
    else:
        install_admin_control_plane(
            app,
            capability_provider=CombinedCapabilityProvider(
                production_admin.capability_provider,
                durable_adapter,
            ),
            audit_sink=production_admin.store,
            idempotency_store=durable_store or production_admin.store,
        )
    if durable_adapter is not None:
        app.state.m26_durable_ingestion_adapter = durable_adapter
    install_admin_overview(app)
    install_admin_ingestion_routes(app, adapter=durable_adapter, include_job_reads=True)
    install_admin_corpus(app, adapter=object_store_corpus_adapter_from_env())
    install_qa_inbox(app)
    app.include_router(playground_router())
    install_suggested_questions_admin(app)
    install_admin_usage(app)
    install_admin_health(app)
    install_jobs_rollback_routes(
        app,
        evidence_provider=(
            durable_adapter.as_p09_provider() if durable_adapter is not None else None
        ),
        include_job_reads=False,
    )
    install_golden_questions_admin(app)
    install_admin_settings(app)
    install_admin_audit(app)
    app.title = "M26 LLM-Wiki Public + Admin API"
    app.version = CANONICAL_ADMIN_API_VERSION
    return app


app = create_app()


__all__ = ["app", "create_app"]
