import json
import logging
import os

from openai import OpenAI

from app.models import ALLOWED_CATEGORIES, ALLOWED_PRIORITIES

FALLBACK_CLASSIFICATION = {"category": "question", "priority": "P3", "tags": []}

_MODEL = "openai/gpt-oss-120b"
_BASE_URL = "https://openrouter.ai/api/v1"
_TIMEOUT_S = 15
_MAX_ATTEMPTS = 2  # 1 intento + 1 reintento

_SYSTEM_PROMPT = (
    "Eres un clasificador de tickets de soporte. Responde EXCLUSIVAMENTE con un "
    "objeto JSON, sin texto antes ni despues, sin markdown ni backticks, con "
    "exactamente estas claves:\n"
    '  "category": uno de "urgent", "bug", "feature_request", "question"\n'
    '  "priority": uno de "P1", "P2", "P3"\n'
    '  "tags": lista de hasta 5 strings cortos (max. 30 caracteres cada uno)\n\n'
    "Criterios:\n"
    "- urgent: bloquea a clientes o tiene un plazo inminente (demo, caida en "
    "produccion).\n"
    "- bug: algo que funcionaba o deberia funcionar y falla.\n"
    "- feature_request: piden algo nuevo o una mejora.\n"
    "- question: dudas de uso, accesos, \"como hago...?\".\n"
    "- Prioridad: P1 impacto alto o urgente - P2 impacto medio - P3 bajo o sin prisa."
)

logger = logging.getLogger(__name__)


def _build_client() -> OpenAI:
    return OpenAI(
        base_url=_BASE_URL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=_TIMEOUT_S,
    )


def _call_llm(client: OpenAI, title: str, description: str) -> str:
    response = client.chat.completions.create(
        model=_MODEL,
        temperature=0,
        timeout=_TIMEOUT_S,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Titulo: {title}\n\nDescripcion: {description}"},
        ],
    )
    return response.choices[0].message.content


def _parse_llm_response(raw: str | None) -> dict | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _normalize_tags(raw_tags: object) -> list[str]:
    if not isinstance(raw_tags, list):
        return []
    tags = [t.lower() for t in raw_tags if isinstance(t, str) and len(t) <= 30]
    return tags[:5]


def _validate_classification(data: dict) -> dict | None:
    category = data.get("category")
    priority = data.get("priority")
    if category not in ALLOWED_CATEGORIES or priority not in ALLOWED_PRIORITIES:
        return None
    return {
        "category": category,
        "priority": priority,
        "tags": _normalize_tags(data.get("tags")),
    }


def classify_ticket(title: str, description: str) -> dict:
    """Classify a support ticket using an LLM via OpenRouter, with a safe fallback."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set; using fallback classification")
        return FALLBACK_CLASSIFICATION

    client = _build_client()
    raw_response: str | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            raw_response = _call_llm(client, title, description)
            break
        except Exception:
            logger.warning("LLM call failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
            if attempt == _MAX_ATTEMPTS:
                return FALLBACK_CLASSIFICATION

    data = _parse_llm_response(raw_response)
    if data is None:
        logger.warning("LLM response was not valid JSON; using fallback")
        return FALLBACK_CLASSIFICATION

    validated = _validate_classification(data)
    if validated is None:
        logger.warning("LLM response had invalid category/priority; using fallback")
        return FALLBACK_CLASSIFICATION

    return validated
