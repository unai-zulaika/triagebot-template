import logging
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app import classifier, db
from app.models import (
    ALLOWED_CATEGORIES,
    ALLOWED_PRIORITIES,
    Category,
    Priority,
    Status,
    Ticket,
    TicketCreate,
    TicketUpdate,
)

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(title="TriageBot")
templates = Jinja2Templates(directory="templates")


def _classify_with_fallback(title: str, description: str) -> dict:
    try:
        classification = classifier.classify_ticket(title, description)
    except Exception:
        logger.exception("classify_ticket failed, using fallback")
        return classifier._fallback()

    if (
        classification["category"] not in ALLOWED_CATEGORIES
        or classification["priority"] not in ALLOWED_PRIORITIES
    ):
        logger.error("classify_ticket returned an invalid classification, using fallback")
        return classifier._fallback()
    return classification


def _create_ticket_from_payload(title: str, description: str) -> Ticket:
    classification = _classify_with_fallback(title, description)
    return db.insert_ticket(
        title=title,
        description=description,
        category=classification["category"],
        priority=classification["priority"],
        tags=classification["tags"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", response_model=Ticket, status_code=201)
def create_ticket(payload: TicketCreate) -> Ticket:
    return _create_ticket_from_payload(payload.title, payload.description)


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


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    tickets = db.list_tickets()
    return templates.TemplateResponse(request, "index.html", {"tickets": tickets, "error": None})


@app.get("/ui/tickets", response_class=HTMLResponse)
def ui_list_tickets(
    request: Request,
    category: Category | Literal[""] | None = None,
    priority: Priority | Literal[""] | None = None,
    status: Status | Literal[""] | None = None,
) -> HTMLResponse:
    tickets = db.list_tickets(
        category=category or None, priority=priority or None, status=status or None
    )
    return templates.TemplateResponse(
        request, "_tickets_table.html", {"tickets": tickets, "error": None}
    )


@app.post("/ui/tickets", response_class=HTMLResponse)
def ui_create_ticket(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
) -> HTMLResponse:
    error: str | None = None
    try:
        payload = TicketCreate(title=title, description=description)
    except ValidationError:
        error = (
            "Título y descripción son obligatorios "
            "(título: máx. 200 caracteres, descripción: máx. 5000)."
        )
    else:
        _create_ticket_from_payload(payload.title, payload.description)

    tickets = db.list_tickets()
    return templates.TemplateResponse(
        request, "_tickets_table.html", {"tickets": tickets, "error": error}
    )


@app.patch("/ui/tickets/{ticket_id}", response_class=HTMLResponse)
def ui_update_ticket(
    ticket_id: int,
    status: str | None = Form(None),
    priority: str | None = Form(None),
) -> HTMLResponse:
    try:
        payload = TicketUpdate(status=status, priority=priority)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ticket = db.update_ticket(ticket_id, status=payload.status, priority=payload.priority)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    row_template = templates.get_template("_tickets_table.html")
    return HTMLResponse(row_template.module.ticket_row(ticket))
