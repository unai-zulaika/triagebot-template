import logging

from fastapi import FastAPI

from app import classifier, db
from app.models import Ticket, TicketCreate

logger = logging.getLogger(__name__)

app = FastAPI(title="TriageBot")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", response_model=Ticket, status_code=201)
def create_ticket(payload: TicketCreate) -> Ticket:
    try:
        classification = classifier.classify_ticket(payload.title, payload.description)
    except Exception:
        logger.exception("classify_ticket failed, using fallback")
        classification = classifier.FALLBACK_CLASSIFICATION

    return db.insert_ticket(
        title=payload.title,
        description=payload.description,
        category=classification["category"],
        priority=classification["priority"],
        tags=classification["tags"],
    )


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - GET /tickets
# - PATCH /tickets/{ticket_id}
# - GET /
