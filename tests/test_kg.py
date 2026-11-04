import json

from app import classifier, kg


def test_kg_has_30_consistent_entities():
    data = kg.load_kg()
    assert len(data["nodes"]) == 30
    for source, _, target in data["edges"]:
        assert source in data["nodes"] and target in data["nodes"]
    for comp in kg.component_ids():
        info = kg._component_info(data, comp)
        assert info["team"] is not None
        assert info["bug_priority"] in {"P1", "P2", "P3"}


def test_link_entities_matches_aliases_without_accents_and_whole_words():
    ids = {e["id"] for e in kg.link_entities("El CRM se cierra", "al abrir una oportunidad")}
    assert {"crm", "sig_fallo"} <= ids
    # "red" es un alias corto: no debe activarse dentro de "redactar".
    ids = {e["id"] for e in kg.link_entities("Quiero redactar mejor", "")}
    assert "red" not in ids
    ids = {e["id"] for e in kg.link_entities("Se ha caido la centralita", "")}
    assert {"telefonia", "sig_bloqueo"} <= ids


def test_rules_urgent_feature_and_bug_priority_from_criticality():
    urgent = kg.classify_with_rules("No puedo entrar al CRM", "Tengo una demo en 30 minutos")
    assert (urgent["category"], urgent["priority"]) == ("urgent", "P1")
    feature = kg.classify_with_rules("Propuesta: modo oscuro en la intranet", "Sería útil")
    assert (feature["category"], feature["priority"]) == ("feature_request", "P3")
    bug_alta = kg.classify_with_rules("El total de la factura sale mal en el ERP", "")
    assert (bug_alta["category"], bug_alta["priority"], bug_alta["team"]) == (
        "bug",
        "P2",
        "eq_aplicaciones",
    )
    assert bug_alta["explanation"]


def test_classify_with_kg_without_key_uses_graph_rules():
    result = classifier.classify_ticket_with_kg("Outlook duplica los correos", "")
    assert result["source"] == "kg_rules"
    assert result["tags"] == ["correo"]


def test_classify_with_kg_filters_tags_to_graph_components(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    seen = {}

    def fake_call(client, title, description, system_prompt="", extra_context=""):
        seen["context"] = extra_context
        return json.dumps(
            {"category": "bug", "priority": "P2", "tags": ["erp", "inventado"], "reason": "x"}
        )

    monkeypatch.setattr(classifier, "_build_client", lambda: None)
    monkeypatch.setattr(classifier, "_call_llm", fake_call)
    result = classifier.classify_ticket_with_kg("La factura sale mal en el ERP", "")
    assert result["source"] == "llm+kg"
    assert result["tags"] == ["erp"]
    assert "erp" in seen["context"]


def test_classify_with_kg_falls_back_to_rules_when_llm_fails(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    monkeypatch.setattr(classifier, "_build_client", lambda: None)

    def boom(*args, **kwargs):
        raise RuntimeError("LLM caído")

    monkeypatch.setattr(classifier, "_call_llm", boom)
    result = classifier.classify_ticket_with_kg("Toda la planta 3 se ha quedado sin red", "")
    assert (result["category"], result["priority"], result["source"]) == (
        "urgent",
        "P1",
        "kg_rules",
    )


def test_post_ticket_uses_graph_when_flag_is_on(client, monkeypatch):
    monkeypatch.setenv("TRIAGE_USE_KG", "1")
    response = client.post(
        "/tickets",
        json={"title": "El TPV de recepción no cobra", "description": "Cola de gente esperando"},
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["category"], body["priority"]) == ("urgent", "P1")
    assert body["tags"] == ["operaciones"]
