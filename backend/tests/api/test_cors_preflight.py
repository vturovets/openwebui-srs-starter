"""Tests covering CORS preflight behaviour for the parse endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_parse_endpoint_allows_preflight_request() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.options(
        "/v1/parse",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") in {"*", "http://localhost:3000"}
    allow_methods = response.headers.get("access-control-allow-methods", "")
    assert "POST" in {method.strip() for method in allow_methods.split(",") if method.strip()}
