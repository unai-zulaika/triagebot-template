def fake_classification(category="bug", priority="P1", tags=None):
    return {"category": category, "priority": priority, "tags": tags or []}


def test_get_index_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_get_ui_tickets_returns_html(client):
    response = client.get("/ui/tickets")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_post_ui_tickets_creates_and_shows_in_table(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: fake_classification())

    response = client.post(
        "/ui/tickets", data={"title": "Algo roto", "description": "No funciona el login"}
    )

    assert response.status_code == 200
    assert "Algo roto" in response.text


def test_post_ui_tickets_empty_title_shows_error_and_does_not_create(client):
    response = client.post(
        "/ui/tickets", data={"title": "", "description": "Descripcion valida"}
    )

    assert response.status_code == 200
    assert "obligatorios" in response.text
    assert client.get("/tickets").json() == []


def test_patch_ui_ticket_invalid_priority_rejected_and_db_unchanged(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: fake_classification())
    client.post("/ui/tickets", data={"title": "Algo", "description": "Descripcion valida"})
    ticket_id = client.get("/tickets").json()[0]["id"]

    response = client.patch(f"/ui/tickets/{ticket_id}", data={"priority": "P9"})

    assert response.status_code == 422
    assert client.get(f"/tickets/{ticket_id}").json()["priority"] == "P1"


def test_patch_ui_ticket_without_fields_rejected(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: fake_classification())
    client.post("/ui/tickets", data={"title": "Algo", "description": "Descripcion valida"})
    ticket_id = client.get("/tickets").json()[0]["id"]

    response = client.patch(f"/ui/tickets/{ticket_id}", data={})

    assert response.status_code == 422


def test_post_ui_tickets_escapes_script_tag(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: fake_classification())

    response = client.post(
        "/ui/tickets",
        data={"title": "<script>alert(1)</script>", "description": "Descripcion valida"},
    )

    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
