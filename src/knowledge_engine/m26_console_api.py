from __future__ import annotations

from .m26_admin_control_plane import install_admin_control_plane
from .m26_admin_settings import install_admin_settings
from .m26_translation_gateway_public_api import create_app as create_public_app


def create_app():
    app = create_public_app()
    install_admin_control_plane(app)
    install_admin_settings(app)
    app.title = "M26 LLM-Wiki Public + Admin API"
    return app


app = create_app()


__all__ = ["app", "create_app"]
