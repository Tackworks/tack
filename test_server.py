"""
Comprehensive test suite for Tack task board API.

Uses FastAPI TestClient with a fresh temporary database per test.
Run: pytest test_server.py -v
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Give every test its own empty database by overriding DB_PATH."""
    db_file = tmp_path / "test_board.db"
    # Patch DB_PATH *before* the app processes any request (init_db runs on
    # startup, but TestClient triggers startup for us).
    import server
    original = server.DB_PATH
    server.DB_PATH = db_file
    server.init_db()
    yield db_file
    server.DB_PATH = original


@pytest.fixture
def client():
    """FastAPI TestClient wired to the Tack app."""
    from server import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _create_card(client, **overrides):
    """Helper: create a card and return the response JSON."""
    payload = {
        "title": "Test card",
        "description": "A test card",
        "priority": "normal",
        "tags": [],
    }
    payload.update(overrides)
    resp = client.post("/api/cards", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1. Health endpoint
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "tack"
        assert "timestamp" in data


# ---------------------------------------------------------------------------
# 2. Card CRUD
# ---------------------------------------------------------------------------

class TestCardCRUD:
    def test_create_card_minimal(self, client):
        resp = client.post("/api/cards", json={"title": "Do the thing"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "created"
        assert data["id"].startswith("card-")

    def test_create_card_full(self, client):
        payload = {
            "title": "Full card",
            "description": "Detailed description",
            "column_name": "approved",
            "assignee": "jim",
            "priority": "high",
            "created_by": "pam",
            "tags": ["urgent", "backend"],
        }
        resp = client.post("/api/cards", json=payload)
        assert resp.status_code == 201
        card_id = resp.json()["id"]

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["title"] == "Full card"
        assert card["description"] == "Detailed description"
        assert card["column_name"] == "approved"
        assert card["assignee"] == "jim"
        assert card["priority"] == "high"
        assert card["created_by"] == "pam"
        assert card["tags"] == ["urgent", "backend"]

    def test_get_card(self, client):
        card_id = _create_card(client)["id"]
        resp = client.get(f"/api/cards/{card_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == card_id

    def test_get_card_not_found(self, client):
        resp = client.get("/api/cards/nonexistent")
        assert resp.status_code == 404

    def test_update_card_title(self, client):
        card_id = _create_card(client)["id"]
        resp = client.patch(f"/api/cards/{card_id}", json={"title": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["title"] == "Updated"

    def test_update_card_multiple_fields(self, client):
        card_id = _create_card(client)["id"]
        resp = client.patch(f"/api/cards/{card_id}", json={
            "description": "New desc",
            "assignee": "dwight",
            "priority": "critical",
            "tags": ["fire"],
            "actor": "michael",
        })
        assert resp.status_code == 200
        card = client.get(f"/api/cards/{card_id}").json()
        assert card["description"] == "New desc"
        assert card["assignee"] == "dwight"
        assert card["priority"] == "critical"
        assert card["tags"] == ["fire"]

    def test_update_card_no_changes(self, client):
        card_id = _create_card(client)["id"]
        resp = client.patch(f"/api/cards/{card_id}", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "no changes"

    def test_update_card_not_found(self, client):
        resp = client.patch("/api/cards/nonexistent", json={"title": "X"})
        assert resp.status_code == 404

    def test_delete_card_with_reason(self, client):
        card_id = _create_card(client)["id"]
        resp = client.post(f"/api/cards/{card_id}/delete", json={
            "reason": "No longer relevant",
            "actor": "pam",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert resp.json()["reason"] == "No longer relevant"

        # Card should be gone
        resp = client.get(f"/api/cards/{card_id}")
        assert resp.status_code == 404

    def test_delete_card_not_found(self, client):
        resp = client.post("/api/cards/nonexistent/delete", json={
            "reason": "Cleanup",
        })
        assert resp.status_code == 404

    def test_delete_card_deprecated_endpoint(self, client):
        card_id = _create_card(client)["id"]
        resp = client.delete(f"/api/cards/{card_id}")
        assert resp.status_code == 400
        assert "reason" in resp.json()["detail"].lower()

    def test_list_cards_empty(self, client):
        resp = client.get("/api/cards")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_cards_returns_all(self, client):
        _create_card(client, title="Card A")
        _create_card(client, title="Card B")
        resp = client.get("/api/cards")
        assert len(resp.json()) == 2


# ---------------------------------------------------------------------------
# 3. Invalid column / priority validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_create_invalid_column(self, client):
        resp = client.post("/api/cards", json={
            "title": "Bad column",
            "column_name": "nonexistent_column",
        })
        assert resp.status_code == 400
        assert "Invalid column" in resp.json()["detail"]

    def test_create_invalid_priority(self, client):
        resp = client.post("/api/cards", json={
            "title": "Bad priority",
            "priority": "ultra",
        })
        assert resp.status_code == 400
        assert "Invalid priority" in resp.json()["detail"]

    def test_update_invalid_column(self, client):
        card_id = _create_card(client)["id"]
        resp = client.patch(f"/api/cards/{card_id}", json={
            "column_name": "garbage",
        })
        assert resp.status_code == 400

    def test_update_invalid_priority(self, client):
        card_id = _create_card(client)["id"]
        resp = client.patch(f"/api/cards/{card_id}", json={
            "priority": "mega",
        })
        assert resp.status_code == 400

    def test_move_invalid_column(self, client):
        card_id = _create_card(client)["id"]
        resp = client.post(f"/api/cards/{card_id}/move", json={
            "column_name": "limbo",
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 4. Card move between columns
# ---------------------------------------------------------------------------

class TestCardMove:
    def test_move_card(self, client):
        card_id = _create_card(client, column_name="inbox")["id"]
        resp = client.post(f"/api/cards/{card_id}/move", json={
            "column_name": "in_progress",
            "actor": "jim",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "moved"
        assert data["from"] == "inbox"
        assert data["to"] == "in_progress"

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["column_name"] == "in_progress"

    def test_move_card_with_position(self, client):
        card_id = _create_card(client, column_name="inbox")["id"]
        resp = client.post(f"/api/cards/{card_id}/move", json={
            "column_name": "approved",
            "position": 5,
        })
        assert resp.status_code == 200
        card = client.get(f"/api/cards/{card_id}").json()
        assert card["position"] == 5

    def test_move_card_not_found(self, client):
        resp = client.post("/api/cards/nonexistent/move", json={
            "column_name": "done",
        })
        assert resp.status_code == 404

    def test_move_to_deferred_sets_defer_until(self, client):
        card_id = _create_card(client)["id"]
        resp = client.post(f"/api/cards/{card_id}/move", json={
            "column_name": "deferred",
        })
        assert resp.status_code == 200

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["column_name"] == "deferred"
        assert card["defer_until"] != ""
        # defer_until should be roughly DEFER_DAYS in the future
        defer_dt = datetime.fromisoformat(card["defer_until"])
        now = datetime.now(timezone.utc)
        assert defer_dt > now

    def test_move_from_deferred_clears_defer_until(self, client):
        card_id = _create_card(client)["id"]
        # Move to deferred first
        client.post(f"/api/cards/{card_id}/move", json={"column_name": "deferred"})
        card = client.get(f"/api/cards/{card_id}").json()
        assert card["defer_until"] != ""

        # Move back to inbox
        client.post(f"/api/cards/{card_id}/move", json={"column_name": "inbox"})
        card = client.get(f"/api/cards/{card_id}").json()
        assert card["defer_until"] == ""


# ---------------------------------------------------------------------------
# 5. Card claiming and conflict (409)
# ---------------------------------------------------------------------------

class TestClaiming:
    def test_claim_card(self, client):
        card_id = _create_card(client)["id"]
        resp = client.post(f"/api/cards/{card_id}/claim", json={
            "agent": "dwight",
            "ttl_seconds": 600,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "claimed"
        assert data["agent"] == "dwight"
        assert "expires_at" in data

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["claimed_by"] == "dwight"

    def test_claim_conflict_409(self, client):
        card_id = _create_card(client)["id"]
        # Agent A claims
        resp = client.post(f"/api/cards/{card_id}/claim", json={
            "agent": "dwight",
            "ttl_seconds": 600,
        })
        assert resp.status_code == 200

        # Agent B tries to claim -- should get 409
        resp = client.post(f"/api/cards/{card_id}/claim", json={
            "agent": "jim",
            "ttl_seconds": 600,
        })
        assert resp.status_code == 409

    def test_same_agent_can_reclaim(self, client):
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/claim", json={
            "agent": "dwight",
            "ttl_seconds": 600,
        })
        # Same agent reclaims -- should succeed (extends)
        resp = client.post(f"/api/cards/{card_id}/claim", json={
            "agent": "dwight",
            "ttl_seconds": 300,
        })
        assert resp.status_code == 200

    def test_claim_not_found(self, client):
        resp = client.post("/api/cards/nonexistent/claim", json={
            "agent": "dwight",
        })
        assert resp.status_code == 404

    def test_release_card(self, client):
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/claim", json={"agent": "dwight"})

        resp = client.post(f"/api/cards/{card_id}/release")
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["claimed_by"] == ""

    def test_release_wrong_agent_403(self, client):
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/claim", json={"agent": "dwight"})

        resp = client.post(f"/api/cards/{card_id}/release", params={"agent": "jim"})
        assert resp.status_code == 403

    def test_release_not_found(self, client):
        resp = client.post("/api/cards/nonexistent/release")
        assert resp.status_code == 404

    def test_expired_claim_allows_new_claim(self, client):
        """After a claim expires, another agent should be able to claim."""
        card_id = _create_card(client)["id"]
        # Claim with 1-second TTL
        client.post(f"/api/cards/{card_id}/claim", json={
            "agent": "dwight",
            "ttl_seconds": 1,
        })
        # Wait for expiry
        time.sleep(1.5)

        # Different agent should succeed
        resp = client.post(f"/api/cards/{card_id}/claim", json={
            "agent": "jim",
            "ttl_seconds": 600,
        })
        assert resp.status_code == 200
        assert resp.json()["agent"] == "jim"


# ---------------------------------------------------------------------------
# 6. Notes (add, list)
# ---------------------------------------------------------------------------

class TestNotes:
    def test_add_note(self, client):
        card_id = _create_card(client)["id"]
        resp = client.post(f"/api/cards/{card_id}/notes", json={
            "author": "michael",
            "content": "That's what she said",
        })
        assert resp.status_code == 201
        assert resp.json()["status"] == "added"

    def test_list_notes(self, client):
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/notes", json={
            "author": "pam",
            "content": "First note",
        })
        client.post(f"/api/cards/{card_id}/notes", json={
            "author": "jim",
            "content": "Second note",
        })

        resp = client.get(f"/api/cards/{card_id}/notes")
        assert resp.status_code == 200
        notes = resp.json()
        assert len(notes) == 2
        assert notes[0]["content"] == "First note"
        assert notes[1]["content"] == "Second note"
        assert notes[0]["author"] == "pam"
        assert notes[1]["author"] == "jim"

    def test_add_note_card_not_found(self, client):
        resp = client.post("/api/cards/nonexistent/notes", json={
            "content": "Orphan note",
        })
        assert resp.status_code == 404

    def test_list_notes_card_not_found(self, client):
        resp = client.get("/api/cards/nonexistent/notes")
        assert resp.status_code == 404

    def test_notes_ordered_by_timestamp(self, client):
        card_id = _create_card(client)["id"]
        for i in range(5):
            client.post(f"/api/cards/{card_id}/notes", json={
                "author": "bot",
                "content": f"Note {i}",
            })
        notes = client.get(f"/api/cards/{card_id}/notes").json()
        timestamps = [n["timestamp"] for n in notes]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# 7. Decision workflow
# ---------------------------------------------------------------------------

class TestDecisionWorkflow:
    def _request_decision(self, client, card_id):
        return client.post(f"/api/cards/{card_id}/decision", json={
            "question": "Which framework?",
            "options": [
                {"key": "flask", "label": "Flask", "description": "Lightweight"},
                {"key": "fastapi", "label": "FastAPI", "description": "Modern async"},
            ],
            "context": "Starting a new microservice",
            "actor": "jim",
        })

    def test_request_decision(self, client):
        card_id = _create_card(client)["id"]
        resp = self._request_decision(client, card_id)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_decision"
        assert data["question"] == "Which framework?"
        assert "flask" in data["options"]
        assert "fastapi" in data["options"]

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["column_name"] == "awaiting_decision"
        assert card["decision"]["question"] == "Which framework?"
        assert card["decision"]["decided"] is None

    def test_submit_decision(self, client):
        card_id = _create_card(client)["id"]
        self._request_decision(client, card_id)

        resp = client.post(f"/api/cards/{card_id}/decide", json={
            "choice": "fastapi",
            "actor": "jon",
            "note": "Obviously the right choice",
            "move_to": "in_progress",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "decided"
        assert data["choice"] == "fastapi"
        assert data["moved_to"] == "in_progress"

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["column_name"] == "in_progress"
        assert card["decision"]["decided"] == "fastapi"
        assert card["decision"]["decided_by"] == "jon"

    def test_submit_decision_invalid_choice(self, client):
        card_id = _create_card(client)["id"]
        self._request_decision(client, card_id)

        resp = client.post(f"/api/cards/{card_id}/decide", json={
            "choice": "django",
            "actor": "jon",
        })
        assert resp.status_code == 400
        assert "Invalid choice" in resp.json()["detail"]

    def test_submit_decision_already_decided(self, client):
        card_id = _create_card(client)["id"]
        self._request_decision(client, card_id)

        client.post(f"/api/cards/{card_id}/decide", json={
            "choice": "fastapi",
            "actor": "jon",
        })
        # Try to decide again
        resp = client.post(f"/api/cards/{card_id}/decide", json={
            "choice": "flask",
            "actor": "jon",
        })
        assert resp.status_code == 400
        assert "Already decided" in resp.json()["detail"]

    def test_submit_decision_no_pending(self, client):
        card_id = _create_card(client)["id"]
        resp = client.post(f"/api/cards/{card_id}/decide", json={
            "choice": "whatever",
            "actor": "jon",
        })
        assert resp.status_code == 400
        assert "No pending decision" in resp.json()["detail"]

    def test_submit_decision_invalid_move_to(self, client):
        card_id = _create_card(client)["id"]
        self._request_decision(client, card_id)

        resp = client.post(f"/api/cards/{card_id}/decide", json={
            "choice": "fastapi",
            "actor": "jon",
            "move_to": "nonexistent_column",
        })
        assert resp.status_code == 400

    def test_submit_decision_card_not_found(self, client):
        resp = client.post("/api/cards/nonexistent/decide", json={
            "choice": "x",
            "actor": "jon",
        })
        assert resp.status_code == 404

    def test_request_decision_card_not_found(self, client):
        resp = client.post("/api/cards/nonexistent/decision", json={
            "question": "?",
            "options": [{"key": "a", "label": "A"}],
        })
        assert resp.status_code == 404

    def test_list_pending_decisions(self, client):
        card_id = _create_card(client)["id"]
        self._request_decision(client, card_id)

        resp = client.get("/api/decisions")
        assert resp.status_code == 200
        decisions = resp.json()
        assert len(decisions) == 1
        assert decisions[0]["id"] == card_id

    def test_decision_note_attached(self, client):
        """When a decision includes a note, it should appear in the card's notes."""
        card_id = _create_card(client)["id"]
        self._request_decision(client, card_id)
        client.post(f"/api/cards/{card_id}/decide", json={
            "choice": "fastapi",
            "actor": "jon",
            "note": "Good framework",
        })
        notes = client.get(f"/api/cards/{card_id}/notes").json()
        assert any("Good framework" in n["content"] for n in notes)


# ---------------------------------------------------------------------------
# 8. Approval workflow
# ---------------------------------------------------------------------------

class TestApprovalWorkflow:
    def _request_approval(self, client, card_id):
        return client.post(f"/api/cards/{card_id}/approval", json={
            "plan": "Migrate database to PostgreSQL",
            "context": "Current SQLite won't scale",
            "actor": "oscar",
        })

    def test_request_approval(self, client):
        card_id = _create_card(client)["id"]
        resp = self._request_approval(client, card_id)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_approval"
        assert data["plan"] == "Migrate database to PostgreSQL"

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["column_name"] == "awaiting_approval"
        assert card["approval"]["plan"] == "Migrate database to PostgreSQL"
        assert card["approval"]["approved"] is None

    def test_approve(self, client):
        card_id = _create_card(client)["id"]
        self._request_approval(client, card_id)

        resp = client.post(f"/api/cards/{card_id}/approve", json={
            "approved": True,
            "comment": "Looks good, ship it",
            "actor": "jon",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["moved_to"] == "in_progress"

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["column_name"] == "in_progress"
        assert card["approval"]["approved"] is True
        assert card["approval"]["approved_by"] == "jon"

    def test_deny(self, client):
        card_id = _create_card(client)["id"]
        self._request_approval(client, card_id)

        resp = client.post(f"/api/cards/{card_id}/approve", json={
            "approved": False,
            "comment": "Too risky right now",
            "actor": "jon",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "denied"
        assert data["moved_to"] == "blocked"

        card = client.get(f"/api/cards/{card_id}").json()
        assert card["column_name"] == "blocked"
        assert card["approval"]["approved"] is False

    def test_approve_with_custom_move_to(self, client):
        card_id = _create_card(client)["id"]
        self._request_approval(client, card_id)

        resp = client.post(f"/api/cards/{card_id}/approve", json={
            "approved": True,
            "actor": "jon",
            "move_to": "done",
        })
        assert resp.status_code == 200
        assert resp.json()["moved_to"] == "done"

    def test_approve_invalid_move_to(self, client):
        card_id = _create_card(client)["id"]
        self._request_approval(client, card_id)

        resp = client.post(f"/api/cards/{card_id}/approve", json={
            "approved": True,
            "actor": "jon",
            "move_to": "narnia",
        })
        assert resp.status_code == 400

    def test_approve_no_pending(self, client):
        card_id = _create_card(client)["id"]
        resp = client.post(f"/api/cards/{card_id}/approve", json={
            "approved": True,
            "actor": "jon",
        })
        assert resp.status_code == 400
        assert "No pending approval" in resp.json()["detail"]

    def test_approve_already_decided(self, client):
        card_id = _create_card(client)["id"]
        self._request_approval(client, card_id)
        client.post(f"/api/cards/{card_id}/approve", json={
            "approved": True,
            "actor": "jon",
        })
        # Try again
        resp = client.post(f"/api/cards/{card_id}/approve", json={
            "approved": False,
            "actor": "jon",
        })
        assert resp.status_code == 400
        assert "Already decided" in resp.json()["detail"]

    def test_approve_card_not_found(self, client):
        resp = client.post("/api/cards/nonexistent/approve", json={
            "approved": True,
            "actor": "jon",
        })
        assert resp.status_code == 404

    def test_request_approval_card_not_found(self, client):
        resp = client.post("/api/cards/nonexistent/approval", json={
            "plan": "Does not matter",
        })
        assert resp.status_code == 404

    def test_list_pending_approvals(self, client):
        card_id = _create_card(client)["id"]
        self._request_approval(client, card_id)

        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        approvals = resp.json()
        assert len(approvals) == 1
        assert approvals[0]["id"] == card_id

    def test_approval_comment_creates_note(self, client):
        card_id = _create_card(client)["id"]
        self._request_approval(client, card_id)
        client.post(f"/api/cards/{card_id}/approve", json={
            "approved": True,
            "comment": "Great plan",
            "actor": "jon",
        })
        notes = client.get(f"/api/cards/{card_id}/notes").json()
        assert any("Great plan" in n["content"] for n in notes)


# ---------------------------------------------------------------------------
# 9. Board endpoint with field filtering
# ---------------------------------------------------------------------------

class TestBoard:
    def test_board_returns_all_columns(self, client):
        from server import VALID_COLUMNS
        resp = client.get("/api/board")
        assert resp.status_code == 200
        board = resp.json()
        for col in VALID_COLUMNS:
            assert col in board

    def test_board_cards_in_correct_columns(self, client):
        _create_card(client, title="Inbox card", column_name="inbox")
        _create_card(client, title="Done card", column_name="done")
        board = client.get("/api/board").json()
        inbox_titles = [c["title"] for c in board["inbox"]]
        done_titles = [c["title"] for c in board["done"]]
        assert "Inbox card" in inbox_titles
        assert "Done card" in done_titles

    def test_board_field_filtering(self, client):
        _create_card(client, title="Filtered card")
        board = client.get("/api/board", params={"fields": "title,column_name"}).json()
        for col, cards in board.items():
            for card in cards:
                # 'id' is always included
                assert "id" in card
                assert "title" in card
                assert "column_name" in card
                # Other fields should be absent
                assert "description" not in card
                assert "assignee" not in card

    def test_board_hides_old_done_cards(self, client):
        """Done cards older than DONE_ARCHIVE_DAYS should be hidden from the board."""
        card_id = _create_card(client, title="Old done", column_name="done")["id"]

        # Manually backdate updated_at to 30 days ago
        import server
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with server.get_db() as db:
            db.execute("UPDATE cards SET updated_at = ? WHERE id = ?", (old_ts, card_id))

        board = client.get("/api/board").json()
        done_ids = [c["id"] for c in board["done"]]
        assert card_id not in done_ids

    def test_board_shows_recent_done_cards(self, client):
        result = _create_card(client, title="Recent done", column_name="done")
        board = client.get("/api/board").json()
        done_ids = [c["id"] for c in board["done"]]
        assert result["id"] in done_ids


# ---------------------------------------------------------------------------
# 10. Search parameters (q, tag, priority)
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_by_text(self, client):
        _create_card(client, title="Deploy to production")
        _create_card(client, title="Fix login bug")
        cards = client.get("/api/cards", params={"q": "deploy"}).json()
        assert len(cards) == 1
        assert cards[0]["title"] == "Deploy to production"

    def test_search_by_description(self, client):
        _create_card(client, title="Card", description="needs database migration")
        _create_card(client, title="Other card", description="simple fix")
        cards = client.get("/api/cards", params={"q": "migration"}).json()
        assert len(cards) == 1

    def test_filter_by_tag(self, client):
        _create_card(client, title="Tagged", tags=["backend", "urgent"])
        _create_card(client, title="Untagged", tags=[])
        cards = client.get("/api/cards", params={"tag": "backend"}).json()
        assert len(cards) == 1
        assert cards[0]["title"] == "Tagged"

    def test_filter_by_priority(self, client):
        _create_card(client, title="Normal card", priority="normal")
        _create_card(client, title="Critical card", priority="critical")
        cards = client.get("/api/cards", params={"priority": "critical"}).json()
        assert len(cards) == 1
        assert cards[0]["title"] == "Critical card"

    def test_filter_by_column(self, client):
        _create_card(client, title="Inbox card", column_name="inbox")
        _create_card(client, title="In progress card", column_name="in_progress")
        cards = client.get("/api/cards", params={"column": "in_progress"}).json()
        assert len(cards) == 1
        assert cards[0]["title"] == "In progress card"

    def test_filter_by_assignee(self, client):
        _create_card(client, title="Jim's card", assignee="jim")
        _create_card(client, title="Dwight's card", assignee="dwight")
        cards = client.get("/api/cards", params={"assignee": "jim"}).json()
        assert len(cards) == 1
        assert cards[0]["title"] == "Jim's card"

    def test_combined_filters(self, client):
        _create_card(client, title="Target", priority="high", column_name="inbox")
        _create_card(client, title="Decoy 1", priority="high", column_name="done")
        _create_card(client, title="Decoy 2", priority="low", column_name="inbox")
        cards = client.get("/api/cards", params={
            "priority": "high",
            "column": "inbox",
        }).json()
        assert len(cards) == 1
        assert cards[0]["title"] == "Target"

    def test_cards_field_filtering(self, client):
        _create_card(client, title="Filtered")
        cards = client.get("/api/cards", params={"fields": "title"}).json()
        assert len(cards) == 1
        assert "id" in cards[0]
        assert "title" in cards[0]
        assert "description" not in cards[0]


# ---------------------------------------------------------------------------
# 11. Batch operations
# ---------------------------------------------------------------------------

class TestBatch:
    def test_batch_create(self, client):
        ops = [
            {"action": "create", "title": "Batch card 1"},
            {"action": "create", "title": "Batch card 2"},
        ]
        resp = client.post("/api/batch", json=ops)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert all(r.get("status") == "created" for r in data["results"])

    def test_batch_mixed_operations(self, client):
        # Create a card first
        card_id = _create_card(client)["id"]

        ops = [
            {"action": "create", "title": "New batch card"},
            {"action": "move", "card_id": card_id, "column_name": "in_progress"},
            {"action": "note", "card_id": card_id, "content": "Batch note", "author": "bot"},
        ]
        resp = client.post("/api/batch", json=ops)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert data["results"][0].get("status") == "created"
        assert data["results"][1].get("status") == "moved"
        assert data["results"][2].get("status") == "added"

    def test_batch_unknown_action(self, client):
        ops = [{"action": "explode"}]
        resp = client.post("/api/batch", json=ops)
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data["results"][0]

    def test_batch_partial_failure(self, client):
        """If one op fails, others should still succeed."""
        card_id = _create_card(client)["id"]
        ops = [
            {"action": "move", "card_id": "nonexistent", "column_name": "done"},
            {"action": "note", "card_id": card_id, "content": "Still works"},
        ]
        resp = client.post("/api/batch", json=ops)
        data = resp.json()
        assert "error" in data["results"][0]
        assert data["results"][1].get("status") == "added"

    def test_batch_claim_and_release(self, client):
        card_id = _create_card(client)["id"]
        ops = [
            {"action": "claim", "card_id": card_id, "agent": "dwight", "ttl_seconds": 600},
        ]
        resp = client.post("/api/batch", json=ops)
        assert resp.json()["results"][0]["status"] == "claimed"

        ops = [
            {"action": "release", "card_id": card_id, "agent": "dwight"},
        ]
        resp = client.post("/api/batch", json=ops)
        assert resp.json()["results"][0]["status"] == "released"

    def test_batch_update(self, client):
        card_id = _create_card(client)["id"]
        ops = [
            {"action": "update", "card_id": card_id, "title": "Batch updated title"},
        ]
        resp = client.post("/api/batch", json=ops)
        assert resp.json()["results"][0]["status"] == "updated"
        card = client.get(f"/api/cards/{card_id}").json()
        assert card["title"] == "Batch updated title"


# ---------------------------------------------------------------------------
# 12. Activity log
# ---------------------------------------------------------------------------

class TestActivity:
    def test_activity_logged_on_create(self, client):
        _create_card(client, title="Logged card", created_by="pam")
        activity = client.get("/api/activity").json()
        assert len(activity) >= 1
        assert activity[0]["action"] == "created"
        assert activity[0]["actor"] == "pam"

    def test_activity_logged_on_move(self, client):
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/move", json={
            "column_name": "done",
            "actor": "jim",
        })
        activity = client.get("/api/activity").json()
        move_entries = [a for a in activity if a["action"] == "moved"]
        assert len(move_entries) >= 1
        assert "inbox -> done" in move_entries[0]["details"]

    def test_activity_logged_on_delete(self, client):
        card_id = _create_card(client, title="Deleted card")["id"]
        client.post(f"/api/cards/{card_id}/delete", json={
            "reason": "Cleanup",
            "actor": "toby",
        })
        activity = client.get("/api/activity").json()
        delete_entries = [a for a in activity if a["action"] == "deleted"]
        assert len(delete_entries) >= 1
        assert "toby" in delete_entries[0]["actor"]
        assert "Cleanup" in delete_entries[0]["details"]

    def test_activity_limit(self, client):
        for i in range(10):
            _create_card(client, title=f"Card {i}")
        activity = client.get("/api/activity", params={"limit": 3}).json()
        assert len(activity) == 3

    def test_activity_default_limit(self, client):
        # Default limit is 50; creating fewer cards should return all
        for i in range(5):
            _create_card(client, title=f"Card {i}")
        activity = client.get("/api/activity").json()
        assert len(activity) == 5

    def test_activity_ordered_desc(self, client):
        _create_card(client, title="First")
        _create_card(client, title="Second")
        activity = client.get("/api/activity").json()
        timestamps = [a["timestamp"] for a in activity]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# 13. Changes polling with since parameter
# ---------------------------------------------------------------------------

class TestChanges:
    def test_changes_returns_recent(self, client):
        _create_card(client, title="Changed card")
        resp = client.get("/api/changes")
        assert resp.status_code == 200
        data = resp.json()
        assert "changes" in data
        assert "checked_at" in data
        assert len(data["changes"]) >= 1

    def test_changes_since_filters(self, client):
        _create_card(client, title="Before card")
        # Capture the timestamp after the first card
        checked_at = client.get("/api/changes").json()["checked_at"]

        # Tiny sleep to ensure timestamp separation
        time.sleep(0.05)
        _create_card(client, title="After card")

        resp = client.get("/api/changes", params={"since": checked_at})
        data = resp.json()
        # Should only see the second card's creation
        assert len(data["changes"]) >= 1
        details = [c.get("card", {}).get("title") for c in data["changes"]]
        assert "After card" in details

    def test_changes_include_card_data(self, client):
        _create_card(client, title="Card with data")
        data = client.get("/api/changes").json()
        entry = data["changes"][0]
        assert "card" in entry
        assert entry["card"]["title"] == "Card with data"

    def test_changes_limit(self, client):
        for i in range(10):
            _create_card(client, title=f"Card {i}")
        data = client.get("/api/changes", params={"limit": 3}).json()
        assert len(data["changes"]) == 3

    def test_changes_deleted_card_no_card_data(self, client):
        """After deletion, the card row is gone, so 'card' key should be absent."""
        card_id = _create_card(client, title="Will be deleted")["id"]
        client.post(f"/api/cards/{card_id}/delete", json={
            "reason": "testing",
            "actor": "tester",
        })
        data = client.get("/api/changes").json()
        delete_entries = [c for c in data["changes"] if c["action"] == "deleted"]
        assert len(delete_entries) >= 1
        # Card was deleted, so the card data should not be present
        assert "card" not in delete_entries[0]


# ---------------------------------------------------------------------------
# 14. Deferred column auto-return
# ---------------------------------------------------------------------------

class TestDeferredAutoReturn:
    def test_deferred_card_returns_when_expired(self, client):
        """Cards in 'deferred' with a past defer_until should auto-return
        to awaiting_decision when the board is loaded."""
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/move", json={"column_name": "deferred"})

        # Manually set defer_until to the past
        import server
        past_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with server.get_db() as db:
            db.execute(
                "UPDATE cards SET defer_until = ? WHERE id = ?",
                (past_ts, card_id)
            )

        # Loading the board triggers check_deferred_cards()
        board = client.get("/api/board").json()

        # Card should have moved to awaiting_decision
        awaiting_ids = [c["id"] for c in board["awaiting_decision"]]
        deferred_ids = [c["id"] for c in board["deferred"]]
        assert card_id in awaiting_ids
        assert card_id not in deferred_ids

    def test_deferred_card_stays_if_not_expired(self, client):
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/move", json={"column_name": "deferred"})

        board = client.get("/api/board").json()
        deferred_ids = [c["id"] for c in board["deferred"]]
        assert card_id in deferred_ids

    def test_deferred_auto_return_creates_activity(self, client):
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/move", json={"column_name": "deferred"})

        import server
        past_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with server.get_db() as db:
            db.execute(
                "UPDATE cards SET defer_until = ? WHERE id = ?",
                (past_ts, card_id)
            )

        # Trigger the check
        client.get("/api/board")

        activity = client.get("/api/activity").json()
        auto_return = [a for a in activity
                       if a["action"] == "moved"
                       and a["card_id"] == card_id
                       and "defer period expired" in a.get("details", "")]
        assert len(auto_return) >= 1
        assert auto_return[0]["actor"] == "system"


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_position_auto_increment(self, client):
        """Cards created in the same column get incrementing positions."""
        id1 = _create_card(client, column_name="inbox")["id"]
        id2 = _create_card(client, column_name="inbox")["id"]
        card1 = client.get(f"/api/cards/{id1}").json()
        card2 = client.get(f"/api/cards/{id2}").json()
        assert card2["position"] > card1["position"]

    def test_card_id_format(self, client):
        result = _create_card(client)
        assert result["id"].startswith("card-")
        # 8 hex chars after the prefix
        suffix = result["id"][len("card-"):]
        assert len(suffix) == 8
        int(suffix, 16)  # should not raise

    def test_created_at_and_updated_at_set(self, client):
        card_id = _create_card(client)["id"]
        card = client.get(f"/api/cards/{card_id}").json()
        assert card["created_at"]
        assert card["updated_at"]
        # Both should be valid ISO timestamps
        datetime.fromisoformat(card["created_at"])
        datetime.fromisoformat(card["updated_at"])

    def test_tags_round_trip(self, client):
        card_id = _create_card(client, tags=["alpha", "beta", "gamma"])["id"]
        card = client.get(f"/api/cards/{card_id}").json()
        assert card["tags"] == ["alpha", "beta", "gamma"]

    def test_empty_board(self, client):
        board = client.get("/api/board").json()
        for col, cards in board.items():
            assert cards == []

    def test_claim_fields_cleared_on_expired(self, client):
        """When a claim expires, get_card should show empty claim fields."""
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/claim", json={
            "agent": "dwight",
            "ttl_seconds": 1,
        })
        time.sleep(1.5)
        card = client.get(f"/api/cards/{card_id}").json()
        assert card["claimed_by"] == ""
        assert card["claimed_at"] == ""
        assert card["claim_expires_at"] == ""


class TestComplete:
    def test_complete_moves_to_done(self, client):
        card_id = _create_card(client, column_name="in_progress")["id"]
        resp = client.post(f"/api/cards/{card_id}/complete", json={"note": "All done", "actor": "jim"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["from"] == "in_progress"
        card = client.get(f"/api/cards/{card_id}").json()
        assert card["column_name"] == "done"

    def test_complete_adds_note(self, client):
        card_id = _create_card(client, column_name="in_progress")["id"]
        client.post(f"/api/cards/{card_id}/complete", json={"note": "Finished the thing", "actor": "pam"})
        notes = client.get(f"/api/cards/{card_id}/notes").json()
        assert len(notes) == 1
        assert "[COMPLETED]" in notes[0]["content"]
        assert "Finished the thing" in notes[0]["content"]

    def test_complete_without_note(self, client):
        card_id = _create_card(client, column_name="inbox")["id"]
        resp = client.post(f"/api/cards/{card_id}/complete", json={})
        assert resp.status_code == 200
        notes = client.get(f"/api/cards/{card_id}/notes").json()
        assert len(notes) == 0

    def test_complete_with_followup(self, client):
        card_id = _create_card(client, title="Original Task", column_name="in_progress")["id"]
        resp = client.post(f"/api/cards/{card_id}/complete", json={
            "note": "Phase 1 done",
            "actor": "jim",
            "followup": True,
            "followup_title": "Phase 2",
            "followup_description": "Continue the work"
        })
        body = resp.json()
        assert body["status"] == "completed"
        assert "followup_id" in body

        followup = client.get(f"/api/cards/{body['followup_id']}").json()
        assert followup["column_name"] == "inbox"
        assert followup["title"] == "Phase 2"
        assert followup["follows_id"] == card_id
        assert "Phase 1 done" in followup["description"]

    def test_complete_followup_auto_title(self, client):
        card_id = _create_card(client, title="Fix Login Bug", column_name="in_progress")["id"]
        resp = client.post(f"/api/cards/{card_id}/complete", json={"followup": True, "actor": "pam"})
        body = resp.json()
        followup = client.get(f"/api/cards/{body['followup_id']}").json()
        assert followup["title"] == "Follow-up: Fix Login Bug"

    def test_complete_followup_inherits_fields(self, client):
        card_id = _create_card(client, title="Deploy", assignee="jim", priority="high", tags=["ops"])["id"]
        resp = client.post(f"/api/cards/{card_id}/complete", json={"followup": True})
        followup = client.get(f"/api/cards/{resp.json()['followup_id']}").json()
        assert followup["assignee"] == "jim"
        assert followup["priority"] == "high"
        assert followup["tags"] == ["ops"]

    def test_complete_404(self, client):
        resp = client.post("/api/cards/card-nonexist/complete", json={})
        assert resp.status_code == 404

    def test_complete_creates_activity(self, client):
        card_id = _create_card(client)["id"]
        client.post(f"/api/cards/{card_id}/complete", json={"actor": "dwight"})
        activity = client.get("/api/activity").json()
        completed = [a for a in activity if a["action"] == "completed"]
        assert len(completed) == 1
        assert completed[0]["actor"] == "dwight"


class TestThread:
    def test_thread_with_followup(self, client):
        id1 = _create_card(client, title="Task 1")["id"]
        resp = client.post(f"/api/cards/{id1}/complete", json={"followup": True})
        id2 = resp.json()["followup_id"]
        resp2 = client.post(f"/api/cards/{id2}/complete", json={"followup": True})
        id3 = resp2.json()["followup_id"]

        thread = client.get(f"/api/cards/{id2}/thread").json()
        assert thread["thread_length"] == 3
        assert len(thread["ancestors"]) == 1
        assert thread["ancestors"][0]["id"] == id1
        assert len(thread["descendants"]) == 1
        assert thread["descendants"][0]["id"] == id3

    def test_thread_no_chain(self, client):
        card_id = _create_card(client)["id"]
        thread = client.get(f"/api/cards/{card_id}/thread").json()
        assert thread["thread_length"] == 1
        assert thread["ancestors"] == []
        assert thread["descendants"] == []

    def test_thread_404(self, client):
        resp = client.get("/api/cards/card-nonexist/thread")
        assert resp.status_code == 404
