from fastapi.testclient import TestClient

from main import app


def test_health_endpoint_is_registered() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_auth_routes_return_404_when_unregistered() -> None:
    client = TestClient(app)

    for path in (
        "/api/v1/auth/bootstrap-admin",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
    ):
        response = client.get(path)
        assert response.status_code == 404, f"GET {path} should be 404, got {response.status_code}"


def test_review_items_routes_return_404_when_unregistered() -> None:
    client = TestClient(app)

    list_response = client.get("/api/v1/review-items")
    assert list_response.status_code == 404

    update_response = client.patch(
        "/api/v1/review-items",
        json={"id": "review-1", "status": "confirmed"},
    )
    assert update_response.status_code == 404
