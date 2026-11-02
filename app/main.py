import logging

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from app import classifier, db
from app.models import Category, Priority, Status, Ticket, TicketCreate, TicketUpdate

load_dotenv()

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


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(
    category: Category | None = None,
    priority: Priority | None = None,
    status: Status | None = None,
) -> list[Ticket]:
    return db.list_tickets(category=category, priority=priority, status=status)


@app.get("/tickets/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: int) -> Ticket:
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(ticket_id: int, payload: TicketUpdate) -> Ticket:
    ticket = db.update_ticket(ticket_id, status=payload.status, priority=payload.priority)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - GET /
