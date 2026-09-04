from __future__ import annotations

from .m26_admin_control_plane import install_admin_control_plane
from .m26_console_p05_ask_playground import router as playground_router
from .m26_translation_gateway_public_api import create_app as create_public_app


def create_app():
    app = create_public_app()
    install_admin_control_plane(app)
    app.include_router(playground_router())
    app.title = "M26 LLM-Wiki Public + Admin API"
    return app


app = create_app()


__all__ = ["app", "create_app"]
