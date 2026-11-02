import pytest


def fake_classification(category="bug", priority="P1", tags=None):
    return {"category": category, "priority": priority, "tags": tags or []}


def test_classify_ticket_garbage_values_do_not_crash_the_api(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "not-a-category", "priority": "P9", "tags": "no-list"},
    )

    response = client.post("/tickets", json={"title": "Algo", "description": "Descripcion valida"})

    assert response.status_code == 201
    assert client.get("/tickets").status_code == 200


@pytest.mark.parametrize(
    "garbage_classification",
    [
        {"category": "bug", "priority": "P1", "tags": "no-list"},
        {"category": "bug", "priority": "P1", "tags": None},
        {"category": "bug", "priority": "P1", "tags": ["x" * 80]},
        {},
        None,
    ],
)
def test_classify_ticket_garbage_tags_or_empty_do_not_crash_the_api(
    client, monkeypatch, garbage_classification
):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: garbage_classification)

    response = client.post("/tickets", json={"title": "Algo", "description": "Descripcion valida"})

    assert response.status_code == 201
    assert client.get("/tickets").status_code == 200


def test_get_ticket_with_id_too_large_for_sqlite_returns_404(client):
    response = client.get("/tickets/99999999999999999999")
    assert response.status_code == 404


def test_patch_ticket_with_id_too_large_for_sqlite_returns_404(client):
    response = client.patch("/tickets/99999999999999999999", json={"status": "closed"})
    assert response.status_code == 404
