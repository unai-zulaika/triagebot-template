import json
from unittest.mock import MagicMock, patch

import pytest

from app.classifier import FALLBACK_CLASSIFICATION, classify_ticket


def _mock_openai_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


@pytest.fixture
def with_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-tests")


@patch("app.classifier.OpenAI")
def test_classify_ticket_valid_response(mock_openai_cls, with_api_key):
    mock_client = MagicMock()
    payload = json.dumps({"category": "bug", "priority": "P1", "tags": ["Login", "crash"]})
    mock_client.chat.completions.create.return_value = _mock_openai_response(payload)
    mock_openai_cls.return_value = mock_client

    result = classify_ticket("Login roto", "No puedo entrar desde ayer")

    assert result == {"category": "bug", "priority": "P1", "tags": ["login", "crash"]}
    assert mock_client.chat.completions.create.call_count == 1


@patch("app.classifier.OpenAI")
def test_classify_ticket_broken_json_falls_back(mock_openai_cls, with_api_key):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response("esto no es json")
    mock_openai_cls.return_value = mock_client

    assert classify_ticket("Algo", "Pasa algo raro") == FALLBACK_CLASSIFICATION


@patch("app.classifier.OpenAI")
def test_classify_ticket_invalid_enum_falls_back(mock_openai_cls, with_api_key):
    mock_client = MagicMock()
    payload = json.dumps({"category": "URGENT", "priority": "P0", "tags": []})
    mock_client.chat.completions.create.return_value = _mock_openai_response(payload)
    mock_openai_cls.return_value = mock_client

    assert classify_ticket("Caida", "Produccion caida") == FALLBACK_CLASSIFICATION


@patch("app.classifier.OpenAI")
def test_classify_ticket_sdk_exception_retries_once_then_falls_back(mock_openai_cls, with_api_key):
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = ConnectionError("network down")
    mock_openai_cls.return_value = mock_client

    result = classify_ticket("Algo", "Descripcion")

    assert result == FALLBACK_CLASSIFICATION
    assert mock_client.chat.completions.create.call_count == 2


@patch("app.classifier.OpenAI")
def test_classify_ticket_without_api_key_skips_api_call(mock_openai_cls, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert classify_ticket("Algo", "Descripcion") == FALLBACK_CLASSIFICATION
    mock_openai_cls.assert_not_called()


@patch("app.classifier.OpenAI")
def test_classify_ticket_strips_and_drops_blank_tags(mock_openai_cls, with_api_key):
    mock_client = MagicMock()
    payload = json.dumps(
        {"category": "bug", "priority": "P2", "tags": ["  login  ", "   ", "crash"]}
    )
    mock_client.chat.completions.create.return_value = _mock_openai_response(payload)
    mock_openai_cls.return_value = mock_client

    result = classify_ticket("Algo", "Descripcion")

    assert result["tags"] == ["login", "crash"]


@patch("app.classifier.OpenAI")
def test_classify_ticket_strips_markdown_code_fence(mock_openai_cls, with_api_key):
    mock_client = MagicMock()
    fenced = (
        "```json\n"
        + json.dumps({"category": "feature_request", "priority": "P3", "tags": ["export"]})
        + "\n```"
    )
    mock_client.chat.completions.create.return_value = _mock_openai_response(fenced)
    mock_openai_cls.return_value = mock_client

    result = classify_ticket("Algo", "Descripcion")

    assert result == {"category": "feature_request", "priority": "P3", "tags": ["export"]}


@patch("app.classifier.OpenAI")
def test_classify_ticket_non_dict_json_falls_back(mock_openai_cls, with_api_key):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response(
        json.dumps(["bug", "P1"])
    )
    mock_openai_cls.return_value = mock_client

    result = classify_ticket("Algo", "Descripcion")

    assert result == FALLBACK_CLASSIFICATION
    assert result is not FALLBACK_CLASSIFICATION
