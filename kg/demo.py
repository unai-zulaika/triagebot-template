"""Demo: clasificar tickets contra el knowledge graph y compararlo con el LLM.

Uso (desde la raíz del repo, con el venv activo):
    python -m kg.demo            # reglas del grafo + LLM + LLM con grafo
    python -m kg.demo --no-llm   # solo las reglas del grafo (sin red ni API key)

Genera kg/report.html (grafo interactivo + tabla de aciertos) y kg/results.json.
"""

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from app import classifier, kg

HERE = Path(__file__).resolve().parent
METHODS = [("kg", "Reglas del grafo"), ("llm", "Solo LLM"), ("llm_kg", "LLM + grafo")]


def _llm_available() -> tuple[bool, str]:
    if not os.environ.get("OPENROUTER_API_KEY"):
        return False, "no hay OPENROUTER_API_KEY en .env"
    try:
        classifier._call_llm(classifier._build_client(), "ping", "responde {}")
        return True, "ok"
    except Exception as exc:  # solo es un diagnóstico
        return False, f"{type(exc).__name__}: {exc}"[:160]


def _score(pred: dict | None, gold: dict) -> dict | None:
    if pred is None:
        return None
    return {
        "category": pred["category"] == gold["category"],
        "priority": pred["priority"] == gold["priority"],
        "component": (
            None if gold["component"] is None else gold["component"] in pred.get("tags", [])
        ),
    }


def run(use_llm: bool, limit: int | None) -> dict:
    tickets = json.loads((HERE / "gold.json").read_text(encoding="utf-8"))["tickets"]
    tickets = tickets[:limit] if limit else tickets
    rows = []
    for n, t in enumerate(tickets, 1):
        title, desc, gold = t["title"], t["description"], t["gold"]
        rules = kg.classify_with_rules(title, desc)
        preds = {"kg": rules, "llm": None, "llm_kg": None}
        if use_llm:
            preds["llm"] = classifier.classify_ticket(title, desc)
            preds["llm_kg"] = classifier.classify_ticket_with_kg(title, desc)
        row = {
            "seed_index": t["seed_index"],
            "split": t["split"],
            "title": title,
            "description": desc,
            "gold": gold,
            "entities": rules["entities"],
            "explanation": rules["explanation"],
            "preds": preds,
            "ok": {m: _score(preds[m], gold) for m, _ in METHODS},
        }
        rows.append(row)
        marks = "  ".join(
            f"{m}:{'✓' if (s := row['ok'][m]) and s['category'] and s['priority'] else '✗'}"
            for m, _ in METHODS
            if row["ok"][m] is not None
        )
        print(f"[{n:2}/{len(tickets)}] {title[:60]:60}  {marks}", flush=True)
    summary = {}
    for split in ("prueba", "diseño"):
        summary[split] = {}
        for m, label in METHODS:
            scored = [r["ok"][m] for r in rows if r["split"] == split and r["ok"][m] is not None]
            if not scored:
                continue
            k = len(scored)
            comps = [s["component"] for s in scored if s["component"] is not None]
            summary[split][m] = {
                "label": label,
                "n": k,
                "category": sum(s["category"] for s in scored) / k,
                "priority": sum(s["priority"] for s in scored) / k,
                "both": sum(s["category"] and s["priority"] for s in scored) / k,
                "component": sum(comps) / len(comps) if comps else 0.0,
            }
    return {"rows": rows, "summary": summary}


def print_summary(summary: dict) -> None:
    for split, title in (
        ("prueba", "PRUEBA: tickets que no se usaron para construir el grafo (la cifra honesta)"),
        ("diseño", "DISEÑO: tickets mirados al construir el grafo (cifra inflada)"),
    ):
        if not summary.get(split):
            continue
        print(f"\n{title}")
        header = f"{'Método':18} {'categoría':>10} {'prioridad':>10} {'ambas':>8}"
        print(f"  {header} {'componente':>11}")
        for s in summary[split].values():
            comp = "n/a" if s["label"] == "Solo LLM" else f"{s['component']:.0%}"
            print(
                f"  {s['label']:18} {s['category']:>10.0%} {s['priority']:>10.0%} "
                f"{s['both']:>8.0%} {comp:>11}   (n={s['n']})"
            )


def write_report(result: dict, llm_note: str) -> Path:
    data = kg.load_kg()
    graph = {
        "nodes": [
            {
                "id": n["id"],
                "label": n["label"],
                "type": n["type"],
                "aliases": n.get("aliases", []),
                "bug_priority": n.get("bug_priority"),
            }
            for n in data["nodes"].values()
        ],
        "edges": [{"from": s, "to": t, "label": r} for s, r, t in data["edges"]],
    }
    html = (HERE / "report_template.html").read_text(encoding="utf-8")
    html = (
        html.replace("__GRAPH__", json.dumps(graph, ensure_ascii=False))
        .replace("__RESULT__", json.dumps(result, ensure_ascii=False))
        .replace("__LLM_NOTE__", llm_note)
        .replace("__DATE__", time.strftime("%Y-%m-%d %H:%M"))
    )
    out = HERE / "report.html"
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-llm", action="store_true", help="solo reglas del grafo")
    parser.add_argument("--limit", type=int, default=None, help="solo los N primeros tickets")
    args = parser.parse_args()
    load_dotenv()

    use_llm, note = (False, "desactivado con --no-llm") if args.no_llm else _llm_available()
    if not use_llm:
        print(f"LLM no disponible ({note}): solo se ejecutan las reglas del grafo.\n")
    result = run(use_llm, args.limit)
    (HERE / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print_summary(result["summary"])
    out = write_report(result, "LLM: activo" if use_llm else f"LLM: no ejecutado ({note})")
    print(f"\nInforme: {out}\nÁbrelo con: open {out.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
