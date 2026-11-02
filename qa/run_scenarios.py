"""QA adversarial (Lab 5) para TriageBot.

Ejecuta 10 escenarios adversariales contra la API JSON (/tickets) y la UI
(/ui/tickets), usando una BD SQLite temporal en /tmp y el clasificador
mockeado (sin llamadas reales al LLM). Vuelca los resultados en qa/REPORT.md.

No modifica nada en app/, templates/ ni tests/. Solo lee y ejecuta.

Uso: python qa/run_scenarios.py
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = Path(tempfile.gettempdir()) / "triagebot_qa_scenarios.db"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ.pop("OPENROUTER_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app import classifier, db  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
db.get_connection().close()  # crea la tabla antes del primer reset_db()

results: list[dict[str, str]] = []


def record(scenario: str, tested: str, expected: str, actual: str, bug: str) -> None:
    results.append(
        {"scenario": scenario, "tested": tested, "expected": expected, "actual": actual, "bug": bug}
    )


def reset_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM tickets")
    conn.commit()
    conn.close()


def fake_classify(title: str, description: str) -> dict:
    return {"category": "bug", "priority": "P1", "tags": []}


def describe(response) -> str:
    try:
        return f"{response.status_code} {json.dumps(response.json())[:200]}"
    except Exception:
        return f"{response.status_code} {response.text[:200]}"


# ---------------------------------------------------------------------------
# 1. Título vacío o solo espacios
# ---------------------------------------------------------------------------
def scenario_1() -> None:
    reset_db()
    classifier.classify_ticket = fake_classify

    r = client.post("/tickets", json={"title": "", "description": "Descripcion valida"})
    record(
        "1. Título vacío (API)",
        "POST /tickets con title=''",
        "422 (SPEC §3: title obligatorio, 1-200 tras trim)",
        describe(r),
        "no" if r.status_code == 422 else "sí",
    )

    r = client.post("/tickets", json={"title": "   ", "description": "Descripcion valida"})
    record(
        "1. Título solo espacios (API)",
        "POST /tickets con title='   '",
        "422 (SPEC §3: trim deja longitud 0)",
        describe(r),
        "no" if r.status_code == 422 else "sí",
    )

    r = client.post("/ui/tickets", data={"title": "", "description": "Descripcion valida"})
    created = client.get("/tickets").json()
    record(
        "1. Título vacío (UI)",
        "POST /ui/tickets con title=''",
        "200 con error junto al formulario, no crea ticket (SPEC §6)",
        f"{describe(r)} | tickets creados: {len(created)}",
        "no" if r.status_code == 200 and len(created) == 0 else "sí",
    )


# ---------------------------------------------------------------------------
# 2. Título de 5000, descripción de 5001
# ---------------------------------------------------------------------------
def scenario_2() -> None:
    reset_db()
    classifier.classify_ticket = fake_classify

    r = client.post(
        "/tickets", json={"title": "A" * 5000, "description": "Descripcion valida"}
    )
    record(
        "2. Título de 5000 caracteres (API)",
        "POST /tickets con title de 5000 chars (límite es 200)",
        "422 (SPEC §3: title máx. 200 caracteres)",
        describe(r),
        "no" if r.status_code == 422 else "sí",
    )

    r = client.post("/tickets", json={"title": "Algo", "description": "B" * 5001})
    record(
        "2. Descripción de 5001 caracteres (API)",
        "POST /tickets con description de 5001 chars (límite es 5000)",
        "422 (SPEC §3: description máx. 5000 caracteres)",
        describe(r),
        "no" if r.status_code == 422 else "sí",
    )

    r = client.post("/tickets", json={"title": "Algo", "description": "B" * 5000})
    record(
        "2. Descripción de exactamente 5000 (API, límite válido)",
        "POST /tickets con description de 5000 chars",
        "201 (SPEC §3: 1-5000 es rango válido)",
        describe(r),
        "no" if r.status_code == 201 else "sí",
    )


# ---------------------------------------------------------------------------
# 3. Emojis y unicode no latino
# ---------------------------------------------------------------------------
def scenario_3() -> None:
    reset_db()
    classifier.classify_ticket = fake_classify
    text = "🔥 La app 不工作"

    r = client.post("/tickets", json={"title": text, "description": text})
    ok_roundtrip = r.status_code == 201 and r.json()["title"] == text
    record(
        "3. Emojis/Unicode en título y descripción (API)",
        "POST /tickets con '🔥 La app 不工作' en title y description",
        "201, texto persistido y devuelto intacto (SPEC §9: debe aguantar Unicode)",
        f"{describe(r)} | roundtrip_ok={ok_roundtrip}",
        "no" if ok_roundtrip else "sí",
    )

    r2 = client.get("/tickets", params={"category": text})
    record(
        "3. Emojis/Unicode como filtro (API)",
        "GET /tickets?category=🔥 La app 不工作",
        "422 (SPEC §4: filtro con valor fuera del enum)",
        describe(r2),
        "no" if r2.status_code == 422 else "sí",
    )

    r3 = client.post("/ui/tickets", data={"title": text, "description": text})
    record(
        "3. Emojis/Unicode (UI)",
        "POST /ui/tickets con '🔥 La app 不工作'",
        "200, el ticket aparece en la tabla con el texto intacto (SPEC §9, §6)",
        f"{describe(r3)} | texto_presente={text in r3.text}",
        "no" if r3.status_code == 200 and text in r3.text else "sí",
    )


# ---------------------------------------------------------------------------
# 4. HTML/JS en título y descripción
# ---------------------------------------------------------------------------
def scenario_4() -> None:
    reset_db()
    classifier.classify_ticket = fake_classify
    payloads = ["<script>alert(1)</script>", '<img src=x onerror=alert(1)>']

    for payload in payloads:
        r = client.post("/tickets", json={"title": payload, "description": payload})
        record(
            f"4. HTML/JS en API ({payload[:20]}...)",
            f"POST /tickets con '{payload}' en title/description",
            "201, el valor se persiste literal en el JSON (la API no es HTML, §9 solo exige "
            "no ejecutar JS en el navegador)",
            describe(r),
            "no" if r.status_code == 201 else "sí",
        )

    for payload in payloads:
        r = client.post("/ui/tickets", data={"title": payload, "description": payload})
        escaped = payload not in r.text
        record(
            f"4. HTML/JS en UI ({payload[:20]}...)",
            f"POST /ui/tickets con '{payload}', se renderiza en _tickets_table.html",
            "200, el HTML sale escapado por Jinja2 (SPEC §9: nunca |safe con datos del usuario)",
            f"{describe(r)} | escaped={escaped}",
            "no" if r.status_code == 200 and escaped else "sí",
        )


# ---------------------------------------------------------------------------
# 5. Inyección SQL
# ---------------------------------------------------------------------------
def scenario_5() -> None:
    reset_db()
    classifier.classify_ticket = fake_classify
    payload = "'; DROP TABLE tickets;--"

    r = client.post("/tickets", json={"title": payload, "description": "Descripcion valida"})
    stored_literally = r.status_code == 201 and r.json()["title"] == payload
    r_list = client.get("/tickets")
    table_survives = r_list.status_code == 200
    record(
        "5. Inyección SQL en título (API)",
        f"POST /tickets con title=\"{payload}\", luego GET /tickets",
        "201, se guarda literal (consultas parametrizadas, SPEC §9), la tabla sigue existiendo",
        f"{describe(r)} | tabla_sigue_viva={table_survives} | guardado_literal={stored_literally}",
        "no" if stored_literally and table_survives else "sí",
    )

    r2 = client.get("/tickets", params={"category": payload})
    record(
        "5. Inyección SQL en filtro (API)",
        f"GET /tickets?category=\"{payload}\"",
        "422 (valor fuera del enum de category, SPEC §4) y la tabla sigue existiendo",
        describe(r2),
        "no" if r2.status_code == 422 else "sí",
    )


# ---------------------------------------------------------------------------
# 6. LLM caído
# ---------------------------------------------------------------------------
def scenario_6() -> None:
    reset_db()

    def raises(title, description):
        raise RuntimeError("LLM down")

    classifier.classify_ticket = raises
    r = client.post("/tickets", json={"title": "Algo", "description": "Descripcion valida"})
    record(
        "6a. classify_ticket lanza excepción",
        "POST /tickets con classify_ticket mockeado para lanzar RuntimeError",
        "201 con el fallback (category=question, priority=P3, tags=[]) — SPEC §4 y §5: "
        "nunca 500 por culpa del LLM",
        describe(r),
        "no" if r.status_code == 201 else "sí",
    )

    def garbage(title, description):
        return {"category": "not-a-category", "priority": "P9", "tags": "no-list"}

    classifier.classify_ticket = garbage
    r2 = client.post("/tickets", json={"title": "Algo2", "description": "Descripcion valida"})
    r2_get = client.get("/tickets")
    is_500 = r2.status_code == 500 or r2_get.status_code == 500
    record(
        "6b. classify_ticket devuelve JSON basura (category/priority/tags fuera de enum)",
        "POST /tickets con classify_ticket mockeado devolviendo category/priority inválidos, "
        "luego GET /tickets",
        "SPEC §9: el sistema debe aguantar sin 500 ante LLM caído/respuesta basura. "
        "SPEC §5.3 dice que classify_ticket ya valida category/priority y aplica fallback "
        "si no valen; main.py no vuelve a validar lo que recibe de classify_ticket",
        f"POST={describe(r2)} | GET_tras_eso={describe(r2_get)}",
        "sí" if is_500 else "no",
    )

    def slow(title, description):
        time.sleep(2)
        return fake_classify(title, description)

    classifier.classify_ticket = slow
    start = time.monotonic()
    r3 = client.post("/tickets", json={"title": "Algo3", "description": "Descripcion valida"})
    elapsed = time.monotonic() - start
    record(
        "6c. classify_ticket tarda (simulado, 2s)",
        "POST /tickets con classify_ticket mockeado para tardar 2s (simula timeout del LLM)",
        "SPEC §5.4 dice que el timeout/reintento de 15s es interno a classify_ticket; "
        "main.py no define un timeout propio por encima. No especificado si /tickets debe "
        "tener su propio límite de tiempo.",
        f"{describe(r3)} | tardó {elapsed:.1f}s",
        "no especificado",
    )

    classifier.classify_ticket = fake_classify


# ---------------------------------------------------------------------------
# 7. El mismo ticket enviado dos veces
# ---------------------------------------------------------------------------
def scenario_7() -> None:
    reset_db()
    classifier.classify_ticket = fake_classify
    payload = {"title": "Ticket duplicado", "description": "Misma descripcion exacta"}

    r1 = client.post("/tickets", json=payload)
    r2 = client.post("/tickets", json=payload)
    all_tickets = client.get("/tickets").json()
    record(
        "7. Mismo ticket enviado dos veces",
        "POST /tickets dos veces con el mismo title/description",
        "SPEC no menciona deduplicación ni idempotencia; cada POST crea un recurso nuevo",
        f"{describe(r1)} | {describe(r2)} | total_tickets={len(all_tickets)}",
        "no especificado",
    )


# ---------------------------------------------------------------------------
# 8. IDs malformados (API y UI, GET y PATCH)
# ---------------------------------------------------------------------------
def scenario_8() -> None:
    reset_db()
    classifier.classify_ticket = fake_classify
    bad_ids = ["-1", "0", "abc", "99999999999", "99999999999999999999"]

    for bad_id in bad_ids:
        r = client.get(f"/tickets/{bad_id}")
        is_404_or_422 = r.status_code in (404, 422)
        record(
            f"8. GET /tickets/{bad_id}",
            f"GET /tickets/{bad_id}",
            "404 si no existe, 422 si el tipo no es válido (SPEC §4/§9); nunca 500",
            describe(r),
            "no" if is_404_or_422 else "sí",
        )

    for bad_id in bad_ids:
        r = client.patch(f"/tickets/{bad_id}", json={"status": "closed"})
        is_404_or_422 = r.status_code in (404, 422)
        record(
            f"8. PATCH /tickets/{bad_id}",
            f"PATCH /tickets/{bad_id} con status=closed",
            "404 si no existe, 422 si el tipo no es válido (SPEC §4/§9); nunca 500",
            describe(r),
            "no" if is_404_or_422 else "sí",
        )

    for bad_id in bad_ids:
        r = client.patch(f"/ui/tickets/{bad_id}", data={"status": "closed"})
        is_404_or_422 = r.status_code in (404, 422)
        record(
            f"8. PATCH /ui/tickets/{bad_id}",
            f"PATCH /ui/tickets/{bad_id} con status=closed (form-data)",
            "404 si no existe, 422 si el tipo no es válido (SPEC §9); nunca 500",
            describe(r),
            "no" if is_404_or_422 else "sí",
        )


# ---------------------------------------------------------------------------
# 9. PATCH con valores inválidos
# ---------------------------------------------------------------------------
def scenario_9() -> None:
    reset_db()
    classifier.classify_ticket = fake_classify
    created = client.post("/tickets", json={"title": "Algo", "description": "Descripcion valida"})
    ticket_id = created.json()["id"]

    cases = [
        ("status inventado", {"status": "inventado"}),
        ("priority P9", {"priority": "P9"}),
        ("campo extra", {"status": "closed", "extra_field": "x"}),
        ("body vacío", {}),
    ]
    for name, body in cases:
        r = client.patch(f"/tickets/{ticket_id}", json=body)
        record(
            f"9. PATCH API con {name}",
            f"PATCH /tickets/{ticket_id} con {body}",
            "422 (SPEC §4: solo status/priority válidos, al menos uno, extra->422)",
            describe(r),
            "no" if r.status_code == 422 else "sí",
        )

    r = client.patch(
        f"/tickets/{ticket_id}", content="null", headers={"content-type": "application/json"}
    )
    record(
        "9. PATCH API con body null",
        f"PATCH /tickets/{ticket_id} con body JSON null",
        "422 (no es un objeto con status/priority)",
        describe(r),
        "no" if r.status_code == 422 else "sí",
    )

    r = client.patch(f"/ui/tickets/{ticket_id}", data={"status": "inventado"})
    record(
        "9. PATCH UI con status inventado",
        f"PATCH /ui/tickets/{ticket_id} con status=inventado (form-data)",
        "422, validado con TicketUpdate igual que la API (decisión de equipo tras el bug "
        "de priority=P9)",
        describe(r),
        "no" if r.status_code == 422 else "sí",
    )

    r = client.patch(f"/ui/tickets/{ticket_id}", data={})
    record(
        "9. PATCH UI sin campos",
        f"PATCH /ui/tickets/{ticket_id} sin status ni priority",
        "422 (igual que la API)",
        describe(r),
        "no" if r.status_code == 422 else "sí",
    )


# ---------------------------------------------------------------------------
# 10. 20 POSTs concurrentes
# ---------------------------------------------------------------------------
def scenario_10() -> None:
    reset_db()
    classifier.classify_ticket = fake_classify

    responses: list = [None] * 20
    errors: list[str] = []

    def do_post(i: int) -> None:
        try:
            responses[i] = client.post(
                "/tickets", json={"title": f"Concurrente {i}", "description": "Descripcion valida"}
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    threads = [threading.Thread(target=do_post, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = [r.status_code if r else None for r in responses]
    all_201 = all(s == 201 for s in statuses)
    ids = [r.json()["id"] for r in responses if r and r.status_code == 201]
    unique_ids = len(ids) == len(set(ids))
    total_in_db = len(client.get("/tickets").json())

    record(
        "10. 20 POSTs concurrentes",
        "20 threads lanzando POST /tickets en paralelo con el LLM mockeado",
        "SPEC §13: SQLite serializa escrituras, una conexión por petición basta; "
        "los 20 deben devolver 201 con ids únicos y los 20 deben quedar en la BD "
        "(SPEC §9: aguanta varios POST a la vez)",
        f"status_codes={statuses} | errores={errors} | ids_unicos={unique_ids} | "
        f"total_en_bd={total_in_db}",
        "no" if all_201 and unique_ids and total_in_db == 20 and not errors else "sí",
    )


SCENARIOS = [
    scenario_1,
    scenario_2,
    scenario_3,
    scenario_4,
    scenario_5,
    scenario_6,
    scenario_7,
    scenario_8,
    scenario_9,
    scenario_10,
]


def write_report() -> None:
    lines = [
        "# REPORT.md — QA adversarial (Lab 5)",
        "",
        "Generado automáticamente por `qa/run_scenarios.py`. BD temporal en "
        f"`{DB_PATH}`, clasificador mockeado (sin llamadas reales al LLM).",
        "",
        "| Escenario | Qué probaste | Esperado (SPEC) | Real | ¿Bug? |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        row = [r["scenario"], r["tested"], r["expected"], r["actual"], r["bug"]]
        row = [c.replace("|", "\\|").replace("\n", " ") for c in row]
        lines.append("| " + " | ".join(row) + " |")

    bugs = [r for r in results if r["bug"] == "sí"]
    lines += [
        "",
        f"## Resumen: {len(bugs)} bug(s) encontrados de {len(results)} pruebas.",
        "",
    ]
    if bugs:
        lines.append("Pruebas marcadas como bug:")
        for b in bugs:
            lines.append(f"- **{b['scenario']}**: real = {b['actual']}")
    else:
        lines.append("Ninguna.")

    report_path = ROOT / "qa" / "REPORT.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Informe escrito en {report_path}")


def main() -> None:
    for scenario in SCENARIOS:
        scenario()
    write_report()
    for r in results:
        print(f"[{r['bug']:>14}] {r['scenario']}")


if __name__ == "__main__":
    main()
