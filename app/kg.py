"""Knowledge graph mínimo para clasificar tickets (demo).

No llama a ningún LLM: carga ``kg/kg.json``, busca en el texto del ticket las
entidades del grafo por sus alias y aplica unas reglas sencillas siguiendo las
aristas. ``classifier.classify_ticket_with_kg`` usa este módulo para darle
contexto al LLM.
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

KG_PATH = Path(__file__).resolve().parent.parent / "kg" / "kg.json"

_URGENT_SIGNALS = ("sig_bloqueo", "sig_plazo", "sig_seguridad")
_SIGNAL_CATEGORY_ORDER = ("bug", "feature_request", "question")  # desempate
_CRIT_RANK = {"crit_alta": 0, "crit_media": 1, "crit_baja": 2}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _alias_pattern(alias: str) -> re.Pattern:
    norm = re.escape(_normalize(alias))
    if alias[0].isalnum() and len(alias) <= 4:
        # Alias cortos ("red", "sms", "crm") solo como palabra completa.
        return re.compile(rf"\b{norm}\b")
    return re.compile(norm)


@lru_cache(maxsize=1)
def load_kg(path: str | None = None) -> dict:
    data = json.loads(Path(path or KG_PATH).read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = [tuple(e) for e in data["edges"]]
    patterns = {
        n["id"]: [(a, _alias_pattern(a)) for a in n.get("aliases", [])]
        for n in data["nodes"]
        if n.get("aliases")
    }
    return {"nodes": nodes, "edges": edges, "patterns": patterns}


def _neighbor(kg: dict, source: str, relation: str) -> str | None:
    for s, r, t in kg["edges"]:
        if s == source and r == relation:
            return t
    return None


def link_entities(title: str, description: str) -> list[dict]:
    """Devuelve las entidades del grafo que aparecen en el ticket."""
    kg = load_kg()
    norm_title, norm_desc = _normalize(title), _normalize(description)
    found = []
    for node_id, pats in kg["patterns"].items():
        hits_title = [a for a, p in pats if p.search(norm_title)]
        hits_desc = [a for a, p in pats if p.search(norm_desc)]
        if hits_title or hits_desc:
            node = kg["nodes"][node_id]
            found.append(
                {
                    "id": node_id,
                    "type": node["type"],
                    "label": node["label"],
                    "in_title": bool(hits_title),
                    "matched": sorted(set(hits_title + hits_desc)),
                }
            )
    return found


def _component_info(kg: dict, comp_id: str) -> dict:
    crit = _neighbor(kg, comp_id, "criticidad") or "crit_baja"
    team = _neighbor(kg, comp_id, "gestionado_por")
    return {
        "id": comp_id,
        "label": kg["nodes"][comp_id]["label"],
        "criticality": crit,
        "bug_priority": kg["nodes"][crit]["bug_priority"],
        "team": team,
        "team_label": kg["nodes"][team]["label"] if team else None,
    }


def classify_with_rules(title: str, description: str) -> dict:
    """Clasificación 100 % basada en el grafo (sin LLM), con su explicación."""
    kg = load_kg()
    entities = link_entities(title, description)
    signals = [e for e in entities if e["type"] == "signal"]
    components = [_component_info(kg, e["id"]) for e in entities if e["type"] == "component"]
    components.sort(key=lambda c: _CRIT_RANK.get(c["criticality"], 9))
    path: list[str] = []

    urgent_hits = [s for s in signals if s["id"] in _URGENT_SIGNALS]
    if urgent_hits:
        category, priority = "urgent", "P1"
        for s in urgent_hits:
            path.append(f"{s['id']} ({', '.join(s['matched'])}) --indica--> urgent")
        path.append("urgent ⇒ P1")
    else:
        scores = {c: 0 for c in _SIGNAL_CATEGORY_ORDER}
        for s in signals:
            target = _neighbor(kg, s["id"], "indica")
            if target in scores:
                scores[target] += 2 if s["in_title"] else 1
                path.append(f"{s['id']} ({', '.join(s['matched'])}) --indica--> {target}")
        best = max(scores.values())
        if best == 0:
            category = "question"
            path.append("ninguna señal ⇒ fallback question")
        else:
            category = next(c for c in _SIGNAL_CATEGORY_ORDER if scores[c] == best)
        if category == "bug" and components:
            main = components[0]
            priority = main["bug_priority"]
            path.append(f"bug en {main['id']} --criticidad--> {main['criticality']} ⇒ {priority}")
        else:
            priority = "P3"
            path.append(f"{category} ⇒ P3")

    main = components[0] if components else None
    if main:
        path.append(f"{main['id']} --gestionado_por--> {main['team']}")
    return {
        "category": category,
        "priority": priority,
        "tags": [c["id"] for c in components][:5],
        "component": main["id"] if main else None,
        "team": main["team"] if main else None,
        "entities": [e["id"] for e in entities],
        "explanation": path,
    }


def prompt_context(title: str, description: str) -> str:
    """Texto con el grafo y las entidades detectadas, para el prompt del LLM."""
    kg = load_kg()
    lines = ["Componentes del grafo (id: nombre | criticidad | equipo):"]
    for node_id, node in kg["nodes"].items():
        if node["type"] == "component":
            info = _component_info(kg, node_id)
            lines.append(f"- {node_id}: {node['label']} | {info['criticality']} | {info['team']}")
    lines.append(
        "Reglas del grafo: un bug en un componente de criticidad alta es P2; media o baja, "
        "P3. Negocio parado, plazo inminente o incidente de seguridad => urgent y P1. "
        "Peticiones de mejora y dudas => P3."
    )
    entities = link_entities(title, description)
    if entities:
        lines.append("Entidades detectadas en este ticket:")
        for e in entities:
            lines.append(f"- {e['id']} ({e['type']}), por: {', '.join(e['matched'])}")
    else:
        lines.append("No se ha detectado ninguna entidad del grafo en este ticket.")
    return "\n".join(lines)


def component_ids() -> list[str]:
    return [n for n, v in load_kg()["nodes"].items() if v["type"] == "component"]
