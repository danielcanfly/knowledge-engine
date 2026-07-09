from __future__ import annotations

from knowledge_engine.api import app


def test_public_ask_openapi_uses_wrapped_error_wire_format() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/v1/ask"]["post"]
    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    forbidden = operation["responses"]["403"]["content"]["application/json"]["schema"]
    unavailable = operation["responses"]["503"]["content"]["application/json"]["schema"]
    assert success["$ref"].endswith("/PublicAskResponse")
    assert forbidden["$ref"].endswith("/PublicErrorResponse")
    assert unavailable["$ref"].endswith("/PublicErrorResponse")
    error_schema = schema["components"]["schemas"]["PublicErrorResponse"]
    assert set(error_schema["properties"]) == {"detail"}
    assert error_schema["properties"]["detail"]["$ref"].endswith(
        "/PublicErrorDetail"
    )
