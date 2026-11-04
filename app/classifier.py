import copy
import json
import logging
import os
import re

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

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _fallback() -> dict:
    return copy.deepcopy(FALLBACK_CLASSIFICATION)


def _strip_code_fence(raw: str) -> str:
    match = _CODE_FENCE_RE.match(raw.strip())
    return match.group(1) if match else raw


def _build_client() -> OpenAI:
    return OpenAI(
        base_url=_BASE_URL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=_TIMEOUT_S,
    )


def _call_llm(
    client: OpenAI,
    title: str,
    description: str,
    system_prompt: str = _SYSTEM_PROMPT,
    extra_context: str = "",
) -> str:
    user_content = f"Titulo: {title}\n\nDescripcion: {description}"
    if extra_context:
        user_content = f"{extra_context}\n\n---\n{user_content}"
    response = client.chat.completions.create(
        model=_MODEL,
        temperature=0,
        timeout=_TIMEOUT_S,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content


def _parse_llm_response(raw: str | None) -> dict | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(_strip_code_fence(raw))
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_tags(raw_tags: object) -> list[str]:
    if not isinstance(raw_tags, list):
        return []
    tags: list[str] = []
    for tag in raw_tags:
        if not isinstance(tag, str):
            continue
        cleaned = tag.strip()
        if not cleaned or len(cleaned) > 30:
            continue
        tags.append(cleaned.lower())
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
        return _fallback()

    try:
        client = _build_client()
        raw_response: str | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                raw_response = _call_llm(client, title, description)
                break
            except Exception:
                logger.warning("LLM call failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
                if attempt == _MAX_ATTEMPTS:
                    return _fallback()

        data = _parse_llm_response(raw_response)
        if data is None:
            logger.warning("LLM response was not valid JSON object; using fallback")
            return _fallback()

        validated = _validate_classification(data)
        if validated is None:
            logger.warning("LLM response had invalid category/priority; using fallback")
            return _fallback()

        return validated
    except Exception:
        logger.exception("Unexpected error while classifying ticket; using fallback")
        return _fallback()


# --- Demo: clasificación con knowledge graph (rama demo/kg-classifier) ---

_KG_SYSTEM_PROMPT = (
    _SYSTEM_PROMPT
    + "\n\nAdemas recibes un knowledge graph de la empresa. Usalo:\n"
    "- tags: SOLO ids de componentes del grafo (max. 3), los afectados por el ticket.\n"
    "- Aplica las reglas de prioridad del grafo segun la criticidad del componente.\n"
    '- Anade la clave "reason": una frase corta que cite las entidades del grafo usadas.'
)


def classify_ticket_with_kg(title: str, description: str) -> dict:
    """Como classify_ticket, pero dando al LLM el knowledge graph como contexto.

    Devuelve category/priority/tags (tags restringidos a componentes del grafo) y,
    además, la clasificación por reglas del grafo y la razón del LLM. Si el LLM
    falla, usa la clasificación por reglas del grafo en vez del fallback genérico.
    """
    from app import kg  # import local: el modo normal no necesita el grafo

    rules = kg.classify_with_rules(title, description)
    base = {
        "category": rules["category"],
        "priority": rules["priority"],
        "tags": rules["tags"],
        "source": "kg_rules",
        "reason": "; ".join(rules["explanation"]),
        "kg": rules,
    }
    if not os.environ.get("OPENROUTER_API_KEY"):
        return base
    try:
        raw = _call_llm(
            _build_client(),
            title,
            description,
            system_prompt=_KG_SYSTEM_PROMPT,
            extra_context=kg.prompt_context(title, description),
        )
    except Exception:
        logger.warning("LLM+KG call failed; using KG rules")
        return base
    data = _parse_llm_response(raw)
    validated = _validate_classification(data) if data else None
    if validated is None:
        return base
    allowed = set(kg.component_ids())
    tags = [t for t in validated["tags"] if t in allowed] or rules["tags"]
    reason = data.get("reason") if isinstance(data.get("reason"), str) else ""
    return {**validated, "tags": tags[:5], "source": "llm+kg", "reason": reason, "kg": rules}
