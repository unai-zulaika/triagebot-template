def fake_classification(category="bug", priority="P1", tags=None):
    return {"category": category, "priority": priority, "tags": tags or []}


def test_get_ticket_404_when_missing(client):
    response = client.get("/tickets/999999")
    assert response.status_code == 200  # forzado a fallar para probar el CI
    assert response.json() == {"detail": "Ticket not found"}


def test_get_ticket_200_when_exists(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: fake_classification())
    created = client.post("/tickets", json={"title": "Algo", "description": "Descripcion valida"})
    ticket_id = created.json()["id"]

    response = client.get(f"/tickets/{ticket_id}")

    assert response.status_code == 200
    assert response.json()["id"] == ticket_id


def test_list_tickets_rejects_invalid_filter_value(client):
    response = client.get("/tickets", params={"category": "not-a-category"})
    assert response.status_code == 422


def test_patch_ticket_404_when_missing(client):
    response = client.patch("/tickets/999999", json={"status": "closed"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


def test_patch_ticket_rejects_extra_field(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: fake_classification())
    created = client.post("/tickets", json={"title": "Algo", "description": "Descripcion valida"})
    ticket_id = created.json()["id"]

    response = client.patch(f"/tickets/{ticket_id}", json={"title": "otro"})

    assert response.status_code == 422


def test_patch_ticket_rejects_empty_body(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: fake_classification())
    created = client.post("/tickets", json={"title": "Algo", "description": "Descripcion valida"})
    ticket_id = created.json()["id"]

    response = client.patch(f"/tickets/{ticket_id}", json={})

    assert response.status_code == 422
