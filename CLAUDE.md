# CLAUDE.md

TriageBot: app FastAPI interna que crea tickets de soporte, los clasifica con un LLM
(`gpt-oss-120b` vía OpenRouter) y los muestra en un tablero HTMX filtrable.

**Qué construir está en `SPEC.md`. Léelo antes de planificar o implementar nada.**
Si algo no está en el SPEC o es ambiguo, pregunta. No inventes requisitos.

## Stack (innegociable)

Python 3.11+ · FastAPI · Pydantic v2 · SQLite con `sqlite3` (sin ORM) · Jinja2 + HTMX +
Tailwind CDN · SDK `openai` contra OpenRouter · pytest · ruff.
No añadas dependencias sin preguntar.

## Comandos

```bash
pytest -v                       # tests (deben pasar antes de cada commit)
ruff check . && ruff format .   # lint + formato (CI falla si ruff falla)
uvicorn app.main:app --reload   # arrancar en local → http://127.0.0.1:8000
```

## Dónde va cada cosa

- `app/main.py`: solo rutas. Sin SQL y sin llamadas al LLM.
- `app/models.py`: schemas Pydantic y enums.
- `app/db.py`: todo el SQL.
- `app/classifier.py`: el ÚNICO archivo que habla con el LLM.
- `templates/`: HTML. Nada de HTML en strings dentro de Python.

## Trampas de los tests (léelas, rompen el CI si se ignoran)

1. Los tests hacen `monkeypatch.setattr("app.classifier.classify_ticket", ...)`.
   En `main.py` usa `from app import classifier` y llama a `classifier.classify_ticket(...)`.
   Con `from app.classifier import classify_ticket` el mock no se aplica.
2. Un test sustituye `classify_ticket` por una función que lanza excepción. El endpoint
   debe envolver la llamada en `try/except` y aplicar el fallback él también.
3. Los tests ponen `DATABASE_URL=sqlite:///<ruta>` **después** de importar la app y usan
   `TestClient(app)` sin `with`, así que no se ejecutan eventos de arranque. En `db.py`,
   lee `DATABASE_URL` en cada conexión (por defecto `sqlite:///triagebot.db`) y crea la
   tabla con `CREATE TABLE IF NOT EXISTS` al conectar. Nada de rutas fijadas al importar.

## Convenciones

- Código, nombres y commits en inglés. Textos de la interfaz en español.
- Type hints en todas las funciones. Funciones de menos de 30 líneas.
- SQL siempre con parámetros (`?`), nunca con f-strings.
- Fechas en UTC con `datetime.now(timezone.utc)`, serializadas en ISO 8601.
- Validación con Pydantic (`StringConstraints(strip_whitespace=True, ...)`), no a mano.
- Errores HTTP con `HTTPException`. Nunca dejes escapar una excepción del LLM.
- `logging`, no `print`. Nunca registres la API key.
- Jinja2 escapa por defecto: no uses `|safe` con datos del usuario.

## Flujo de trabajo

- Una rama por tarea (`feat/...`, `fix/...`, `docs/...`). Nunca commits directos a `main`.
- Planifica antes de cambios de más de un archivo y espera aprobación.
- Cambios pequeños: un commit por cosa que funciona, mensajes tipo `feat: add POST /tickets`.
- Antes de dar algo por terminado: `pytest -v` y `ruff check .` en verde, y enseña la salida.
- Si una decisión no está en el SPEC, propón añadirla a `SPEC.md` §13.

## Prohibido

- Modificar `tests/test_acceptance.py`.
- Hardcodear API keys. Se leen de `OPENROUTER_API_KEY` (cargada desde `.env`).
- Commitear `.env` o archivos `.db`.
- React, Vue o cualquier build de frontend.
