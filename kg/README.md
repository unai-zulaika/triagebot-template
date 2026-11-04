# Demo: clasificación contra un knowledge graph

Rama `demo/kg-classifier`. No cambia el comportamiento normal de la app.

## Qué hay

| Archivo | Qué es |
|---|---|
| `kg/kg.json` | El grafo: 30 entidades (13 componentes, 4 equipos, 3 criticidades, 6 señales, 4 categorías) y 32 relaciones. |
| `app/kg.py` | Sin LLM. Busca las entidades en el ticket por sus alias y aplica reglas siguiendo las aristas. |
| `app/classifier.py` → `classify_ticket_with_kg` | El LLM recibe el grafo como contexto; los tags solo pueden ser componentes del grafo. Si el LLM falla, usa las reglas. |
| `kg/gold.json` | 50 tickets del seed etiquetados a mano: 30 de **diseño** (mirados al construir el grafo) y 20 de **prueba** (no mirados). |
| `kg/demo.py` | Compara reglas del grafo, solo LLM y LLM + grafo, y genera `kg/report.html`. |

## Cómo verlo

```bash
python -m kg.demo            # con LLM (necesita OPENROUTER_API_KEY en .env; ~100 llamadas)
python -m kg.demo --no-llm   # solo reglas del grafo, sin red
open kg/report.html
```

En el informe: clic en una fila → el grafo resalta las entidades encontradas y se ve el camino de las reglas. Clic en un nodo → sus alias y relaciones.

Para usarlo dentro de la app: `TRIAGE_USE_KG=1 uvicorn app.main:app --reload` (los tags pasan a ser ids de componentes del grafo).

## Cómo leer los números

Mira la columna **prueba**. La de diseño está inflada: los alias se escribieron mirando esos tickets.
