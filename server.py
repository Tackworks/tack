"""
Tack — A self-hosted task board for AI agent teams.
Model-agnostic REST API. Any agent framework, any model, any scale.
Pin your tasks, track your agents.
"""

import sqlite3
import json
import uuid
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

DB_PATH = Path(os.environ.get("TACK_DB", str(Path(__file__).parent / "data" / "board.db")))
STATIC_DIR = Path(__file__).parent / "static"
HOST = os.environ.get("TACK_HOST", "127.0.0.1")
PORT = int(os.environ.get("TACK_PORT", "8795"))
API_KEY = os.environ.get("TACK_API_KEY", "")

app = FastAPI(title="Tack", version="1.1.0")


# --- Optional API Key Auth ---

OPEN_PATHS = {"/", "/health", "/static"}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}

class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not API_KEY:
            return await call_next(request)
        # Allow static files, health, and UI
        path = request.url.path
        if path == "/" or path.startswith("/static") or path == "/health":
            return await call_next(request)
        # Allow reads without auth (board viewing)
        if request.method in READ_METHODS:
            return await call_next(request)
        # Check API key for write operations
        key = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ")
        if key != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
        return await call_next(request)

app.add_middleware(ApiKeyMiddleware)


# --- Database ---

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                column_name TEXT NOT NULL DEFAULT 'inbox',
                assignee TEXT DEFAULT '',
                priority TEXT DEFAULT 'normal',
                position INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT DEFAULT '',
                tags TEXT DEFAULT '[]'
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT,
                action TEXT NOT NULL,
                actor TEXT DEFAULT '',
                details TEXT DEFAULT '',
                timestamp TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT NOT NULL,
                author TEXT DEFAULT '',
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        # Migrate: add columns to cards if missing (duplicate column errors are expected)
        for col in ["claimed_by", "claimed_at", "claim_expires_at", "decision", "approval", "defer_until", "follows_id"]:
            try:
                db.execute(f"ALTER TABLE cards ADD COLUMN {col} TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # Column already exists


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# --- Models ---

VALID_COLUMNS = ["inbox", "approved", "in_progress", "awaiting_decision", "awaiting_approval", "deferred", "done", "blocked"]
VALID_PRIORITIES = ["low", "normal", "high", "critical"]

class CardCreate(BaseModel):
    title: str
    description: str = ""
    column_name: str = "inbox"
    assignee: str = ""
    priority: str = "normal"
    created_by: str = ""
    tags: list[str] = []

class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column_name: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[list[str]] = None
    actor: Optional[str] = None

class CardMove(BaseModel):
    column_name: str
    position: Optional[int] = None
    actor: Optional[str] = None

class ClaimRequest(BaseModel):
    agent: str
    ttl_seconds: int = 300

class NoteCreate(BaseModel):
    author: str = ""
    content: str

class DecisionOption(BaseModel):
    key: str
    label: str
    description: str = ""

class DecisionRequest(BaseModel):
    question: str
    options: list[DecisionOption]
    context: str = ""
    deadline: Optional[str] = None
    actor: Optional[str] = None

class DecisionSubmit(BaseModel):
    choice: str
    actor: str = ""
    note: str = ""
    move_to: str = "in_progress"

class ApprovalRequest(BaseModel):
    plan: str
    context: str = ""
    actor: Optional[str] = None

class ApprovalSubmit(BaseModel):
    approved: bool
    comment: str = ""
    actor: str = ""
    move_to: Optional[str] = None

class CardComplete(BaseModel):
    note: str = ""
    actor: str = ""
    followup: bool = False
    followup_title: str = ""
    followup_description: str = ""


# --- Helpers ---

def filter_fields(card: dict, fields: Optional[str]) -> dict:
    """Filter card dict to only requested fields. Always includes 'id'."""
    if not fields:
        return card
    requested = {f.strip() for f in fields.split(",")}
    requested.add("id")
    return {k: v for k, v in card.items() if k in requested}


def clear_expired_claim(card: dict) -> dict:
    """Clear claim fields if the claim has expired."""
    if card.get("claim_expires_at") and card["claim_expires_at"] < now_iso():
        card["claimed_by"] = ""
        card["claimed_at"] = ""
        card["claim_expires_at"] = ""
    return card


def parse_card(row) -> dict:
    """Convert a DB row to a card dict with parsed JSON fields."""
    card = dict(row)
    card["tags"] = json.loads(card["tags"])
    for field in ("decision", "approval"):
        if card.get(field):
            try:
                card[field] = json.loads(card[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return clear_expired_claim(card)


# --- API Routes ---

DONE_ARCHIVE_DAYS = int(os.environ.get("TACK_DONE_ARCHIVE_DAYS", "7"))
DEFER_DAYS = int(os.environ.get("TACK_DEFER_DAYS", "7"))


def check_deferred_cards():
    """Move deferred cards back to awaiting_decision if their defer_until has passed."""
    now = now_iso()
    with get_db() as db:
        rows = db.execute(
            "SELECT id, title, defer_until FROM cards WHERE column_name = 'deferred' AND defer_until != '' AND defer_until <= ?",
            (now,)
        ).fetchall()
        for row in rows:
            db.execute(
                "UPDATE cards SET column_name = 'awaiting_decision', defer_until = '', updated_at = ? WHERE id = ?",
                (now, row["id"])
            )
            db.execute(
                "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
                (row["id"], "moved", "system", "deferred -> awaiting_decision (defer period expired)", now)
            )


@app.get("/api/board")
def get_board(fields: Optional[str] = None):
    """Get all cards organized by column. Done cards older than DONE_ARCHIVE_DAYS are hidden.
    Use ?fields=id,title,column_name to return only specific fields (saves tokens)."""
    check_deferred_cards()
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM cards ORDER BY position ASC, created_at ASC"
        ).fetchall()

    cutoff = datetime.now(timezone.utc) - timedelta(days=DONE_ARCHIVE_DAYS)
    cutoff_iso = cutoff.isoformat()

    board = {col: [] for col in VALID_COLUMNS}
    for row in rows:
        card = parse_card(row)
        col = card["column_name"]
        if col == "done" and card["updated_at"] < cutoff_iso:
            continue
        if col in board:
            board[col].append(filter_fields(card, fields))
        else:
            board["inbox"].append(filter_fields(card, fields))
    return board


@app.get("/api/cards")
def list_cards(column: Optional[str] = None, assignee: Optional[str] = None,
               q: Optional[str] = None, tag: Optional[str] = None,
               priority: Optional[str] = None, fields: Optional[str] = None):
    """List cards with optional filters.
    Use ?q=search+term to search title and description.
    Use ?tag=tagname to filter by tag.
    Use ?priority=high to filter by priority.
    Use ?fields=id,title,column_name to return only specific fields (saves tokens)."""
    query = "SELECT * FROM cards WHERE 1=1"
    params = []
    if column:
        query += " AND column_name = ?"
        params.append(column)
    if assignee:
        query += " AND assignee = ?"
        params.append(assignee)
    if q:
        query += " AND (title LIKE ? OR description LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    if tag:
        query += " AND tags LIKE ?"
        params.append(f'%"{tag}"%')
    if priority:
        query += " AND priority = ?"
        params.append(priority)
    query += " ORDER BY position ASC, created_at ASC"

    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    cards = []
    for row in rows:
        card = parse_card(row)
        cards.append(filter_fields(card, fields))
    return cards


@app.post("/api/cards", status_code=201)
def create_card(card: CardCreate):
    """Create a new card."""
    if card.column_name not in VALID_COLUMNS:
        raise HTTPException(400, f"Invalid column. Use one of: {VALID_COLUMNS}")
    if card.priority not in VALID_PRIORITIES:
        raise HTTPException(400, f"Invalid priority. Use one of: {VALID_PRIORITIES}")

    card_id = f"card-{uuid.uuid4().hex[:8]}"
    ts = now_iso()

    with get_db() as db:
        row = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 as next_pos FROM cards WHERE column_name = ?",
            (card.column_name,)
        ).fetchone()
        pos = row["next_pos"]

        db.execute(
            """INSERT INTO cards (id, title, description, column_name, assignee, priority,
               position, created_at, updated_at, created_by, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (card_id, card.title, card.description, card.column_name,
             card.assignee, card.priority, pos, ts, ts, card.created_by,
             json.dumps(card.tags))
        )
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "created", card.created_by, f"Created in {card.column_name}", ts)
        )

    return {"id": card_id, "status": "created"}


@app.get("/api/cards/{card_id}")
def get_card(card_id: str):
    """Get a single card by ID."""
    with get_db() as db:
        row = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Card not found")
    card = parse_card(row)
    return card


@app.patch("/api/cards/{card_id}")
def update_card(card_id: str, update: CardUpdate):
    """Update card fields."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        fields = {}
        if update.title is not None:
            fields["title"] = update.title
        if update.description is not None:
            fields["description"] = update.description
        if update.column_name is not None:
            if update.column_name not in VALID_COLUMNS:
                raise HTTPException(400, f"Invalid column. Use one of: {VALID_COLUMNS}")
            fields["column_name"] = update.column_name
        if update.assignee is not None:
            fields["assignee"] = update.assignee
        if update.priority is not None:
            if update.priority not in VALID_PRIORITIES:
                raise HTTPException(400, f"Invalid priority. Use one of: {VALID_PRIORITIES}")
            fields["priority"] = update.priority
        if update.tags is not None:
            fields["tags"] = json.dumps(update.tags)

        if not fields:
            return {"status": "no changes"}

        fields["updated_at"] = now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [card_id]
        db.execute(f"UPDATE cards SET {set_clause} WHERE id = ?", values)

        changes = ", ".join(f"{k}={v}" for k, v in fields.items() if k != "updated_at")
        actor = update.actor or ""
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "updated", actor, changes, now_iso())
        )

    return {"status": "updated"}


@app.post("/api/cards/{card_id}/move")
def move_card(card_id: str, move: CardMove):
    """Move a card to a different column."""
    if move.column_name not in VALID_COLUMNS:
        raise HTTPException(400, f"Invalid column. Use one of: {VALID_COLUMNS}")

    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        old_col = existing["column_name"]
        ts = now_iso()

        if move.position is not None:
            pos = move.position
        else:
            row = db.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 as next_pos FROM cards WHERE column_name = ?",
                (move.column_name,)
            ).fetchone()
            pos = row["next_pos"]

        # Auto-set defer_until when moving to deferred column
        if move.column_name == "deferred":
            defer_until = (datetime.now(timezone.utc) + timedelta(days=DEFER_DAYS)).isoformat()
            db.execute(
                "UPDATE cards SET column_name = ?, position = ?, updated_at = ?, defer_until = ? WHERE id = ?",
                (move.column_name, pos, ts, defer_until, card_id)
            )
        else:
            db.execute(
                "UPDATE cards SET column_name = ?, position = ?, updated_at = ?, defer_until = '' WHERE id = ?",
                (move.column_name, pos, ts, card_id)
            )
        actor = move.actor or ""
        details = f"{old_col} -> {move.column_name}"
        if move.column_name == "deferred":
            details += f" (returns in {DEFER_DAYS} days)"
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "moved", actor, details, ts)
        )

    return {"status": "moved", "from": old_col, "to": move.column_name}


@app.post("/api/cards/{card_id}/complete")
def complete_card(card_id: str, body: CardComplete):
    """Move card to done with a completion note. Optionally create a followup card.
    Use followup=true to spawn a new card in inbox that references this one."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        ts = now_iso()
        old_col = existing["column_name"]

        # Move to done
        row = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 as next_pos FROM cards WHERE column_name = 'done'"
        ).fetchone()
        db.execute(
            "UPDATE cards SET column_name = 'done', position = ?, updated_at = ?, defer_until = '' WHERE id = ?",
            (row["next_pos"], ts, card_id)
        )
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "completed", body.actor, f"{old_col} -> done", ts)
        )

        # Add completion note
        if body.note:
            db.execute(
                "INSERT INTO notes (card_id, author, content, timestamp) VALUES (?, ?, ?, ?)",
                (card_id, body.actor, f"[COMPLETED] {body.note}", ts)
            )

        # Create followup card if requested
        followup_id = None
        if body.followup:
            followup_id = f"card-{uuid.uuid4().hex[:8]}"
            followup_title = body.followup_title or f"Follow-up: {existing['title']}"
            followup_desc = body.followup_description or ""
            if body.note:
                followup_desc = f"Previous card completed with note: {body.note}\n\n{followup_desc}".strip()

            row2 = db.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 as next_pos FROM cards WHERE column_name = 'inbox'"
            ).fetchone()
            db.execute(
                """INSERT INTO cards (id, title, description, column_name, assignee, priority,
                   position, created_at, updated_at, created_by, tags, follows_id)
                   VALUES (?, ?, ?, 'inbox', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (followup_id, followup_title, followup_desc, existing["assignee"],
                 existing["priority"], row2["next_pos"], ts, ts,
                 body.actor, existing["tags"], card_id)
            )
            db.execute(
                "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
                (followup_id, "created", body.actor, f"Follow-up from {card_id}: {existing['title']}", ts)
            )

    result = {"status": "completed", "from": old_col}
    if followup_id:
        result["followup_id"] = followup_id
    return result


@app.post("/api/cards/{card_id}/claim")
def claim_card(card_id: str, claim: ClaimRequest):
    """Claim a card for an agent. Prevents other agents from working on it.
    Returns 409 if already claimed by another agent (and not expired)."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        if existing["claimed_by"] and existing["claim_expires_at"] > now_iso():
            if existing["claimed_by"] != claim.agent:
                raise HTTPException(409, {
                    "error": "Card already claimed",
                    "claimed_by": existing["claimed_by"],
                    "expires_at": existing["claim_expires_at"],
                    "hint": f"Try another card, or wait until {existing['claim_expires_at']}"
                })

        ts = now_iso()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=claim.ttl_seconds)).isoformat()

        db.execute(
            "UPDATE cards SET claimed_by = ?, claimed_at = ?, claim_expires_at = ?, updated_at = ? WHERE id = ?",
            (claim.agent, ts, expires, ts, card_id)
        )
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "claimed", claim.agent, f"TTL={claim.ttl_seconds}s, expires={expires}", ts)
        )

    return {"status": "claimed", "agent": claim.agent, "expires_at": expires}


@app.post("/api/cards/{card_id}/release")
def release_card(card_id: str, agent: Optional[str] = None):
    """Release a claim on a card."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        if agent and existing["claimed_by"] and existing["claimed_by"] != agent:
            raise HTTPException(403, f"Card claimed by {existing['claimed_by']}, not {agent}")

        ts = now_iso()
        db.execute(
            "UPDATE cards SET claimed_by = '', claimed_at = '', claim_expires_at = '', updated_at = ? WHERE id = ?",
            (ts, card_id)
        )
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "released", agent or existing["claimed_by"] or "", "Claim released", ts)
        )

    return {"status": "released"}


@app.post("/api/cards/{card_id}/notes", status_code=201)
def add_note(card_id: str, note: NoteCreate):
    """Add a note to a card's trace log. Append-only."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        ts = now_iso()
        db.execute(
            "INSERT INTO notes (card_id, author, content, timestamp) VALUES (?, ?, ?, ?)",
            (card_id, note.author, note.content, ts)
        )
        db.execute(
            "UPDATE cards SET updated_at = ? WHERE id = ?", (ts, card_id)
        )
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "note_added", note.author, note.content[:100], ts)
        )

    return {"status": "added"}


@app.get("/api/cards/{card_id}/notes")
def get_notes(card_id: str):
    """Get all notes for a card, oldest first."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        rows = db.execute(
            "SELECT * FROM notes WHERE card_id = ? ORDER BY timestamp ASC", (card_id,)
        ).fetchall()

    return [dict(r) for r in rows]


@app.post("/api/cards/{card_id}/decision")
def request_decision(card_id: str, decision: DecisionRequest):
    """Agent requests a human decision. Moves card to awaiting_decision with structured options."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        ts = now_iso()
        decision_data = {
            "question": decision.question,
            "options": [o.model_dump() for o in decision.options],
            "context": decision.context,
            "deadline": decision.deadline,
            "requested_by": decision.actor or "",
            "requested_at": ts,
            "decided": None,
            "decided_by": None,
            "decided_at": None,
        }

        db.execute(
            "UPDATE cards SET column_name = 'awaiting_decision', decision = ?, updated_at = ? WHERE id = ?",
            (json.dumps(decision_data), ts, card_id)
        )
        actor = decision.actor or ""
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "decision_requested", actor, decision.question[:100], ts)
        )

    return {"status": "awaiting_decision", "question": decision.question, "options": [o.key for o in decision.options]}


@app.post("/api/cards/{card_id}/decide")
def submit_decision(card_id: str, submit: DecisionSubmit):
    """Human submits a decision. Records the choice and moves card onward."""
    if submit.move_to not in VALID_COLUMNS:
        raise HTTPException(400, f"Invalid move_to column. Use one of: {VALID_COLUMNS}")

    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        decision_raw = existing["decision"]
        if not decision_raw:
            raise HTTPException(400, "No pending decision on this card")

        decision_data = json.loads(decision_raw)
        if decision_data.get("decided"):
            raise HTTPException(400, f"Already decided: {decision_data['decided']}")

        valid_keys = [o["key"] for o in decision_data["options"]]
        if submit.choice not in valid_keys:
            raise HTTPException(400, f"Invalid choice. Options: {valid_keys}")

        ts = now_iso()
        decision_data["decided"] = submit.choice
        decision_data["decided_by"] = submit.actor
        decision_data["decided_at"] = ts

        db.execute(
            "UPDATE cards SET decision = ?, column_name = ?, updated_at = ? WHERE id = ?",
            (json.dumps(decision_data), submit.move_to, ts, card_id)
        )
        chosen_label = next((o["label"] for o in decision_data["options"] if o["key"] == submit.choice), submit.choice)
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "decided", submit.actor, f"Chose: {chosen_label}", ts)
        )

        if submit.note:
            db.execute(
                "INSERT INTO notes (card_id, author, content, timestamp) VALUES (?, ?, ?, ?)",
                (card_id, submit.actor, submit.note, ts)
            )

    return {"status": "decided", "choice": submit.choice, "moved_to": submit.move_to}


@app.get("/api/decisions")
def list_pending_decisions():
    """List all cards awaiting a decision."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM cards WHERE column_name = 'awaiting_decision' AND decision != '' ORDER BY updated_at ASC"
        ).fetchall()

    return [parse_card(row) for row in rows]


@app.post("/api/cards/{card_id}/approval")
def request_approval(card_id: str, req: ApprovalRequest):
    """Agent proposes a plan and requests approval. Moves card to awaiting_approval.
    Simpler than a decision — human just approves or denies with an optional comment."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        ts = now_iso()
        approval_data = {
            "plan": req.plan,
            "context": req.context,
            "requested_by": req.actor or "",
            "requested_at": ts,
            "approved": None,
            "approved_by": None,
            "approved_at": None,
            "comment": None,
        }

        db.execute(
            "UPDATE cards SET column_name = 'awaiting_approval', approval = ?, updated_at = ? WHERE id = ?",
            (json.dumps(approval_data), ts, card_id)
        )
        actor = req.actor or ""
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "approval_requested", actor, req.plan[:100], ts)
        )

    return {"status": "awaiting_approval", "plan": req.plan}


@app.post("/api/cards/{card_id}/approve")
def submit_approval(card_id: str, submit: ApprovalSubmit):
    """Human approves or denies a plan. Moves card onward."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        approval_raw = existing["approval"]
        if not approval_raw:
            raise HTTPException(400, "No pending approval on this card")

        approval_data = json.loads(approval_raw)
        if approval_data.get("approved") is not None:
            raise HTTPException(400, f"Already decided: {'approved' if approval_data['approved'] else 'denied'}")

        ts = now_iso()
        approval_data["approved"] = submit.approved
        approval_data["approved_by"] = submit.actor
        approval_data["approved_at"] = ts
        approval_data["comment"] = submit.comment

        if submit.move_to:
            if submit.move_to not in VALID_COLUMNS:
                raise HTTPException(400, f"Invalid move_to column. Use one of: {VALID_COLUMNS}")
            move_to = submit.move_to
        else:
            move_to = "in_progress" if submit.approved else "blocked"

        db.execute(
            "UPDATE cards SET approval = ?, column_name = ?, updated_at = ? WHERE id = ?",
            (json.dumps(approval_data), move_to, ts, card_id)
        )
        status = "approved" if submit.approved else "denied"
        detail = f"{status}" + (f": {submit.comment}" if submit.comment else "")
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "approval_" + status, submit.actor, detail, ts)
        )

        if submit.comment:
            db.execute(
                "INSERT INTO notes (card_id, author, content, timestamp) VALUES (?, ?, ?, ?)",
                (card_id, submit.actor, f"[{status.upper()}] {submit.comment}", ts)
            )

    return {"status": status, "moved_to": move_to}


@app.get("/api/approvals")
def list_pending_approvals():
    """List all cards awaiting approval."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM cards WHERE column_name = 'awaiting_approval' AND approval != '' ORDER BY updated_at ASC"
        ).fetchall()

    return [parse_card(row) for row in rows]


@app.get("/api/cards/{card_id}/thread")
def get_card_thread(card_id: str):
    """Get the followup chain for a card. Walks both directions:
    ancestors (what this card follows) and descendants (what follows this card)."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")

        # Walk ancestors (follows_id chain backwards)
        ancestors = []
        current = dict(existing)
        while current.get("follows_id"):
            parent = db.execute("SELECT * FROM cards WHERE id = ?", (current["follows_id"],)).fetchone()
            if not parent:
                break
            ancestors.insert(0, parse_card(parent))
            current = dict(parent)

        # Walk descendants (cards whose follows_id points to this card, then recurse)
        descendants = []
        queue = [card_id]
        while queue:
            parent_id = queue.pop(0)
            children = db.execute("SELECT * FROM cards WHERE follows_id = ?", (parent_id,)).fetchall()
            for child in children:
                descendants.append(parse_card(child))
                queue.append(child["id"])

    return {
        "card": parse_card(existing),
        "ancestors": ancestors,
        "descendants": descendants,
        "thread_length": len(ancestors) + 1 + len(descendants)
    }


class CardDelete(BaseModel):
    reason: str
    actor: str = ""


@app.post("/api/cards/{card_id}/delete")
def delete_card_with_reason(card_id: str, body: CardDelete):
    """Delete a card. Requires a reason (consolidation, no longer relevant, etc.)."""
    with get_db() as db:
        existing = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Card not found")
        db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        db.execute(
            "INSERT INTO activity (card_id, action, actor, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (card_id, "deleted", body.actor, f"{existing['title']} — reason: {body.reason}", now_iso())
        )
    return {"status": "deleted", "reason": body.reason}


@app.delete("/api/cards/{card_id}")
def delete_card(card_id: str):
    """Delete a card (deprecated — use POST /api/cards/{card_id}/delete with reason)."""
    raise HTTPException(400, "Deletion reason is required. Use POST /api/cards/{card_id}/delete with {\"reason\": \"...\"}")


@app.post("/api/batch", status_code=200)
def batch_operations(ops: list[dict]):
    """Execute multiple operations in one call. Each op: {action, ...params}.
    Actions: create, move, update, claim, release, note, decide."""
    results = []
    for op in ops:
        action = op.pop("action", None)
        try:
            if action == "create":
                results.append(create_card(CardCreate(**op)))
            elif action == "move":
                card_id = op.pop("card_id")
                results.append(move_card(card_id, CardMove(**op)))
            elif action == "update":
                card_id = op.pop("card_id")
                results.append(update_card(card_id, CardUpdate(**op)))
            elif action == "claim":
                card_id = op.pop("card_id")
                results.append(claim_card(card_id, ClaimRequest(**op)))
            elif action == "release":
                card_id = op.pop("card_id")
                results.append(release_card(card_id, op.get("agent")))
            elif action == "note":
                card_id = op.pop("card_id")
                results.append(add_note(card_id, NoteCreate(**op)))
            else:
                results.append({"error": f"Unknown action: {action}"})
        except HTTPException as e:
            results.append({"error": str(e.detail), "status_code": e.status_code})
        except Exception as e:
            results.append({"error": str(e)})
    return {"results": results, "count": len(results)}


@app.get("/api/activity")
def get_activity(limit: int = 50):
    """Get recent activity log."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM activity ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/changes")
def get_changes(since: Optional[str] = None, limit: int = 20):
    """Get changes since a timestamp. Designed for agent polling.
    Returns activity entries + the affected card data."""
    with get_db() as db:
        if since:
            rows = db.execute(
                "SELECT * FROM activity WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
                (since, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM activity ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()

        changes = []
        for row in rows:
            entry = dict(row)
            card = db.execute("SELECT * FROM cards WHERE id = ?", (entry["card_id"],)).fetchone()
            if card:
                card_data = dict(card)
                card_data["tags"] = json.loads(card_data["tags"])
                entry["card"] = card_data
            changes.append(entry)

    return {"changes": changes, "checked_at": now_iso()}


@app.get("/health")
def health():
    return {"status": "ok", "service": "tack", "timestamp": now_iso()}


# --- Static files & SPA fallback ---

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# --- Startup ---

@app.on_event("startup")
def startup():
    init_db()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
