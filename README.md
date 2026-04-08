# Tack

A self-hosted task board for AI agent teams. Model-agnostic REST API. Any agent framework, any model, any scale.

Pin your tasks, track your agents.

## What is this?

Tack is a lightweight Kanban board designed for human-AI collaboration. Your AI agents create, update, and move cards through a simple REST API. You see everything in a drag-and-drop web interface. Drag a card to "Approved" and your agents pick it up. Need a decision? Agents queue structured options with clickable buttons. You click, they resume.

No vendor lock-in. No cloud dependency. SQLite backend. Self-host in 30 seconds.

## Quick Start

```bash
pip install fastapi uvicorn
python server.py
```

Open `http://localhost:8795` in your browser.

### Docker

```bash
docker compose up -d
```

Or build manually:

```bash
docker build -t tack .
docker run -d -p 8795:8795 -v tack-data:/data tack
```

## For AI Agents

Give your agent the contents of [TOOL.md](TOOL.md) as context. It contains:

- REST API reference with all endpoints
- Column and priority definitions
- OpenAI function-calling tool definitions (works with any compatible framework)
- Usage guidelines (when to create cards, when to move them)

The tool spec is model-agnostic. It works with OpenAI, Anthropic, Ollama, llama.cpp, or any system that supports function calling or HTTP tool use.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/board` | Get all cards organized by column |
| `GET` | `/api/cards` | List cards (filter by `?column=`, `?assignee=`, `?fields=`) |
| `POST` | `/api/cards` | Create a card |
| `GET` | `/api/cards/{id}` | Get a single card |
| `PATCH` | `/api/cards/{id}` | Update card fields |
| `POST` | `/api/cards/{id}/move` | Move card to a column |
| `POST` | `/api/cards/{id}/claim` | Claim card (prevents other agents from grabbing it) |
| `POST` | `/api/cards/{id}/release` | Release a claim |
| `POST` | `/api/cards/{id}/notes` | Add a note to the card's trace log |
| `GET` | `/api/cards/{id}/notes` | Read card notes |
| `POST` | `/api/cards/{id}/decision` | Request a human decision (with structured options) |
| `POST` | `/api/cards/{id}/decide` | Submit a decision |
| `GET` | `/api/decisions` | List all pending decisions |
| `POST` | `/api/cards/{id}/approval` | Request approval for a plan (yes/no) |
| `POST` | `/api/cards/{id}/approve` | Submit an approval or denial |
| `GET` | `/api/approvals` | List all pending approvals |
| `POST` | `/api/batch` | Execute multiple operations in one call |
| `DELETE` | `/api/cards/{id}` | Delete a card |
| `GET` | `/api/activity` | Recent activity log |
| `GET` | `/api/changes` | Poll for changes since a timestamp |
| `GET` | `/health` | Health check |

## Agent-Native Features

- **Sparse-field reads** — `?fields=id,title,column_name` returns only the fields you ask for. Cuts response size ~5x, saves tokens on every poll.
- **Atomic claiming with TTL** — `POST /claim` locks a card so two agents don't work on the same task. Claims auto-expire after a configurable TTL. 409 conflict with recovery hint if already claimed.
- **Per-card trace log** — Append-only notes on each card. Agents document reasoning, findings, and handoff context. Makes agent-to-agent handoffs possible without losing context.
- **Human-in-the-loop decisions** — Agents post structured questions with options. Humans see clickable buttons in the UI. Click to decide, card moves forward. `GET /api/decisions` gives you the decision queue.
- **Plan approvals** — Agents propose a plan, humans approve or deny. Simpler than decisions — no options to choose from, just yes/no with optional comments. Denied cards move to blocked with the reason logged. `GET /api/approvals` gives you the approval queue.
- **Batch operations** — `POST /api/batch` with an array of actions. Create, move, update, claim, release, and note in a single call.
- **Webhook support** — Set `TACK_WEBHOOKS` to a comma-separated list of URLs. Tack fires POST requests on card_created, card_moved, and decision_made events.

## Columns

| Column | Purpose |
|--------|---------|
| **Inbox** | New tasks, not yet reviewed |
| **Approved** | Human approved — agents pick these up |
| **In Progress** | Actively being worked on |
| **Awaiting Decision** | Needs human input (with structured options) |
| **Awaiting Approval** | Agent proposed a plan, needs yes/no |
| **Blocked** | Cannot proceed |
| **Done** | Completed |

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `TACK_HOST` | `127.0.0.1` | Bind address |
| `TACK_PORT` | `8795` | Port number |
| `TACK_DB` | `./data/board.db` | SQLite database path |
| `TACK_WEBHOOKS` | (none) | Comma-separated webhook URLs |
| `TACK_DONE_ARCHIVE_DAYS` | `7` | Auto-hide done cards older than N days from board view |
| `TACK_DEFER_DAYS` | `7` | Days before deferred cards auto-return to Awaiting Decision |
| `TACK_API_KEY` | (none) | Optional API key for write operations (reads remain open) |

## Keyboard Shortcuts

- `n` — New card
- `/` — Focus search
- `Esc` — Close modal / clear search
- Double-click card to edit

## Dependencies

- Python 3.10+
- FastAPI
- Uvicorn
- SortableJS (loaded from CDN in the frontend)

## License

MIT
