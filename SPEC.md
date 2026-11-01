# SPEC.md — Contrato funcional de TriageBot

> Qué hace el sistema, no cómo se programa (eso está en `CLAUDE.md`).
> Fuente: `BRIEF.md` + `tests/test_acceptance.py`. Si algo no está aquí, se decide en
> equipo y se apunta en la §13 antes de implementarlo.

## 1. Objetivo

Aplicación web interna para que Soporte cree tickets en lenguaje natural, los vea
clasificados automáticamente por IA (categoría, prioridad, tags) y los gestione en un
tablero filtrable. Elimina la hora diaria de triage manual.

## 2. Stack (innegociable)

Python 3.11+ · FastAPI · Pydantic v2 · SQLite (`sqlite3` de la stdlib, sin ORM) ·
Jinja2 + HTMX + Tailwind por CDN · SDK `openai` apuntando a OpenRouter
(modelo `openai/gpt-oss-120b`) · pytest · ruff · GitHub Actions.

Nota: `requirements.txt` trae `anthropic`; hay que añadir `openai`. No se añaden más
dependencias sin acordarlo en equipo.

## 3. Modelo de datos

### Ticket

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | int | Autoincremental, lo genera SQLite |
| `title` | str | Obligatorio. Se hace trim; tras el trim, 1–200 caracteres |
| `description` | str | Obligatorio. Se hace trim; tras el trim, 1–5000 caracteres |
| `category` | str | `bug` · `feature_request` · `question` · `urgent` |
| `priority` | str | `P1` · `P2` · `P3` |
| `tags` | list[str] | 0–5 tags, minúsculas, cada una de 1–30 caracteres. Puede estar vacía |
| `status` | str | `open` · `in_progress` · `closed`. Al crear: `open` |
| `created_at` | datetime | UTC, ISO 8601, lo pone el servidor al crear |
| `updated_at` | datetime | UTC, ISO 8601. Igual a `created_at` al crear; cambia en cada PATCH |

- Los enums son exactos y en minúsculas (`P1`–`P3` en mayúscula). `"URGENT"` no vale.
- Inmutables tras la creación: `id`, `title`, `description`, `category`, `tags`, `created_at`.
- En SQLite, `tags` se guarda como texto JSON.

## 4. API JSON

Todas las respuestas de ticket devuelven el objeto completo de la §3.

| Método | Ruta | Entrada | Éxito | Errores |
|---|---|---|---|---|
| `POST` | `/tickets` | JSON `{title, description}` | `201` + ticket clasificado | `422` validación |
| `GET` | `/tickets` | query opcional `category`, `priority`, `status` | `200` + lista | `422` si un filtro no es un valor válido |
| `GET` | `/tickets/{id}` | — | `200` + ticket | `404` si no existe |
| `PATCH` | `/tickets/{id}` | JSON con `status` y/o `priority` | `200` + ticket actualizado | `404` no existe · `422` validación |
| `GET` | `/health` | — | `200` `{"status": "ok"}` | — |

Detalles:

- **POST /tickets** clasifica de forma síncrona dentro de la petición y devuelve el
  ticket ya clasificado y persistido. Si la clasificación falla por lo que sea, usa el
  fallback (§5) y responde `201` igualmente. Nunca `500` por culpa del LLM.
- **GET /tickets**: los filtros se combinan con AND. Sin filtros devuelve todos.
  Orden: más recientes primero (`created_at` descendente). Sin paginación.
- **PATCH**: solo acepta `status` y `priority`; al menos uno de los dos. Cualquier otro
  campo → `422`. Actualiza `updated_at`.
- Errores `404` con el formato estándar de FastAPI: `{"detail": "Ticket not found"}`.

## 5. Clasificador (`app/classifier.py`)

Contrato: `classify_ticket(title: str, description: str) -> dict` con claves
`category`, `priority`, `tags` que cumplen la §3.

1. Lee `OPENROUTER_API_KEY` del entorno. Si no existe → fallback sin llamar a la API.
2. Llama a OpenRouter (`base_url="https://openrouter.ai/api/v1"`,
   modelo `openai/gpt-oss-120b`, `temperature=0`, timeout 15 s) pidiendo **solo JSON**.
3. Valida la respuesta: JSON parseable, `category` y `priority` dentro de los enums
   exactos. Tags: se pasan a minúsculas, se descartan las que no sean texto o pasen de
   30 caracteres, máximo 5. Si `category` o `priority` no valen → fallback completo.
4. Si la llamada falla (red, timeout, error del SDK), reintenta **una vez**. Si vuelve a
   fallar → fallback.
5. **Fallback**: `{"category": "question", "priority": "P3", "tags": []}`.
6. Nunca propaga excepciones. Registra el fallo con `logging` (sin la API key).

Criterio de clasificación que se le da al modelo:

- `urgent`: bloquea a clientes o tiene un plazo inminente (demo, caída en producción).
- `bug`: algo que funcionaba o debería funcionar y falla.
- `feature_request`: piden algo nuevo o una mejora.
- `question`: dudas de uso, accesos, "¿cómo hago…?".
- Prioridad: `P1` impacto alto o urgente · `P2` impacto medio · `P3` bajo o sin prisa.

## 6. Frontend (`GET /`)

Una sola página HTML (Jinja2 + HTMX, sin React ni JS propio salvo HTMX):

1. **Formulario** de creación (título + descripción). Al enviar, crea el ticket y
   refresca la tabla sin recargar la página.
2. **Filtros** por categoría, prioridad y estado (selects). Al cambiar, refrescan la tabla.
3. **Tabla** con: id, título, categoría, prioridad, tags, estado, fecha de creación.
4. **Cambio manual** de estado y prioridad desde cada fila (select que guarda al cambiar).

Rutas HTML (devuelven fragmentos, no JSON; separadas de la API de la §4):

| Método | Ruta | Devuelve |
|---|---|---|
| `GET` | `/` | Página completa |
| `GET` | `/ui/tickets` | Fragmento `_tickets_table.html`, acepta los mismos filtros |
| `POST` | `/ui/tickets` | Crea desde formulario (form-data) y devuelve la tabla actualizada |
| `PATCH` | `/ui/tickets/{id}` | Cambia estado/prioridad (form-data) y devuelve la fila |

Errores de validación en el formulario: se muestran junto al formulario, no como JSON.

## 7. Tests obligatorios

`tests/test_acceptance.py` no se modifica. Comprueba:

1. `POST /tickets` válido → `201` con la clasificación y todos los campos.
2. El ticket queda persistido y aparece en `GET /tickets`.
3. Título o descripción vacíos, solo espacios o demasiado largos → `422`.
4. Si `classify_ticket` lanza una excepción → `201` con el fallback.
5. `PATCH` de estado y prioridad + filtro combinado por `category`, `priority` y `status`.

Además, tests propios del equipo en `tests/test_*.py` (no en el de aceptación) para:
el clasificador con respuestas inválidas del LLM (mockeado), `404`, y filtros con valor
inválido.

## 8. Criterios de aceptación (fin del Día 2)

- [ ] Repo en GitHub con commits de todo el equipo, integrados por PR.
- [ ] 5 tests de aceptación en verde.
- [ ] CI en verde en GitHub Actions (ruff + pytest) sobre el último commit de `main`.
- [ ] La app arranca con `uvicorn app.main:app --reload`.
- [ ] Se crea un ticket desde la web y aparece en el tablero, clasificado.
- [ ] README con instrucciones de arranque actualizadas.

## 9. QA adversarial (Día 2)

El sistema debe aguantar sin `500`: título vacío o de 5000+ caracteres, emojis y
Unicode, HTML/JS en la descripción (Jinja2 escapa por defecto; nunca `|safe` con datos
del usuario), inyección SQL (siempre consultas parametrizadas), LLM caído, ids negativos
o no numéricos (`404`/`422`), y varios POST a la vez.

## 10. Estructura de módulos

```
app/
  main.py        # FastAPI: rutas de la §4 y §6. Sin SQL ni llamadas al LLM
  models.py      # Schemas Pydantic y enums
  db.py          # Conexión SQLite, creación de tabla y operaciones CRUD
  classifier.py  # ÚNICO módulo que llama al LLM
templates/
  index.html
  _tickets_table.html
```

## 11. Fuera de alcance

Login, roles y permisos · React/Vue o frontend complejo · despliegue productivo o base
de datos gestionada · integración con email, Slack o formularios · paginación ·
borrar tickets · editar título, descripción o categoría.

## 12. No negociable

- No commitear `.env` ni hardcodear API keys.
- No propagar excepciones del SDK del LLM a los endpoints.
- No modificar `tests/test_acceptance.py` para que pase.
- Nada de push directo a `main`: rama + PR.

## 13. Decisiones del equipo

Ambigüedades del BRIEF resueltas por nosotros (añadid aquí las nuevas):

| Pregunta | Decisión |
|---|---|
| ¿Qué proveedor de IA? El BRIEF dice Claude | OpenRouter + `gpt-oss-120b`, por indicación del curso |
| ¿Se puede cambiar la categoría a mano? | No. Solo estado y prioridad (BRIEF §"Qué necesitamos") |
| ¿Paginación? | No. Volumen esperado de cientos de tickets |
| Diferencia entre tag y categoría | Categoría: una de 4, fija. Tags: etiquetas libres para buscar a ojo |
| Tickets creados a la vez | SQLite serializa escrituras; una conexión por petición basta |
