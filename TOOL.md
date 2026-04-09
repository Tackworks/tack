# Tack — Agent Tool Reference

You have access to a task board. Use it to track work, report progress, and flag blockers. These instructions work with any model or agent framework.

## Quick Reference

All endpoints accept and return JSON. Base URL is configurable (default: `http://127.0.0.1:8795`).

### Create a card
```
POST /api/cards
{"title": "Research compression options", "assignee": "researcher", "priority": "high", "column_name": "in_progress"}
```

### Move a card
```
POST /api/cards/{card_id}/move
{"column_name": "done", "actor": "my-agent"}
```

### Update a card
```
PATCH /api/cards/{card_id}
{"description": "Updated findings...", "priority": "normal", "actor": "my-agent"}
```

### List cards
```
GET /api/cards
GET /api/cards?assignee=researcher
GET /api/cards?column=blocked
GET /api/cards?fields=id,title,column_name    # sparse fields — saves tokens
```

### Get the full board
```
GET /api/board
GET /api/board?fields=id,title,assignee,column_name   # sparse fields
```

### Claim a card (prevents other agents from grabbing it)
```
POST /api/cards/{card_id}/claim
{"agent": "my-agent", "ttl_seconds": 300}
```
Returns 409 if already claimed by another agent. Same agent can reclaim. Claims auto-expire after TTL.

### Release a claim
```
POST /api/cards/{card_id}/release?agent=my-agent
```

### Add a note to a card's trace log
```
POST /api/cards/{card_id}/notes
{"author": "my-agent", "content": "Checked compression ratios — 3.2x on average"}
```

### Read a card's notes
```
GET /api/cards/{card_id}/notes
```

### Request a human decision
```
POST /api/cards/{card_id}/decision
{
  "question": "Which auth method should we use?",
  "options": [
    {"key": "jwt", "label": "JWT tokens", "description": "Stateless, scalable"},
    {"key": "sessions", "label": "Server sessions", "description": "Simple, revocable"}
  ],
  "context": "Building auth for the API. Need to decide before implementing.",
  "actor": "my-agent"
}
```
Moves card to `awaiting_decision`. Human sees clickable buttons in the UI.

### Check pending decisions
```
GET /api/decisions
```

### Request an approval
```
POST /api/cards/{card_id}/approval
{
  "plan": "Migrate the database to PostgreSQL. Steps: 1) Export current data, 2) Set up PG schema, 3) Import data, 4) Update connection strings.",
  "context": "Current SQLite DB is hitting concurrency limits under load.",
  "actor": "my-agent"
}
```
Moves card to `awaiting_approval`. Human sees the plan with Approve/Deny buttons.

### Submit an approval
```
POST /api/cards/{card_id}/approve
{"approved": true, "comment": "Looks good, go ahead.", "actor": "reviewer"}
```
Approved cards move to `in_progress`. Denied cards move to `blocked` (override with `move_to`). Comments are logged as notes.

### Check pending approvals
```
GET /api/approvals
```

### Batch operations
```
POST /api/batch
[
  {"action": "create", "title": "Task A", "assignee": "agent-1"},
  {"action": "move", "card_id": "card-abc123", "column_name": "done", "actor": "agent-1"},
  {"action": "note", "card_id": "card-abc123", "author": "agent-1", "content": "Completed."}
]
```

### Poll for changes (since last check)
```
GET /api/changes?since=2026-04-07T12:00:00+00:00
```

## Columns

| Column | Meaning | Who moves cards here |
|--------|---------|---------------------|
| `inbox` | New tasks, not yet reviewed | Anyone |
| `approved` | Human approved — pick these up | Human approver |
| `in_progress` | Actively being worked on | The assigned agent |
| `awaiting_decision` | Needs human input | Agent who hit a decision point |
| `awaiting_approval` | Agent proposed a plan, needs yes/no | Agent requesting approval |
| `deferred` | Postponed — auto-returns to awaiting_decision after TACK_DEFER_DAYS | Human or agent deferring |
| `done` | Completed | Agent who finished the work |
| `blocked` | Cannot proceed | Agent who found the blocker |

## Priorities

| Priority | When to use |
|----------|-------------|
| `critical` | Production down, security issue, data loss risk |
| `high` | Blocks other work, time-sensitive |
| `normal` | Standard work item |
| `low` | Nice to have, no urgency |

## When to Create Cards

- When you receive a new task that will take more than one step
- When you discover a blocker or dependency
- When you need a human decision before proceeding

## When to Move Cards

- `inbox` -> `in_progress`: When you start working on it (or wait for human to move to `approved`)
- `approved` -> `in_progress`: When you pick up an approved card
- `in_progress` -> `awaiting_decision`: When you need human input (use `/decision` endpoint)
- `in_progress` -> `awaiting_approval`: When you have a plan that needs sign-off (use `/approval` endpoint)
- `in_progress` -> `blocked`: When something external prevents progress
- `in_progress` -> `done`: When the work is complete
- `blocked` -> `in_progress`: When the blocker is resolved

## When NOT to Use the Board

- Simple greetings or status questions
- One-shot tasks that complete immediately
- Internal routing decisions

## OpenAI Function-Calling Tool Definitions

For agent frameworks that use OpenAI-format tool definitions:

```json
[
  {
    "type": "function",
    "function": {
      "name": "tack_create",
      "description": "Create a new task card on the board",
      "parameters": {
        "type": "object",
        "properties": {
          "title": {"type": "string", "description": "Short task title"},
          "description": {"type": "string", "description": "Details and context"},
          "column_name": {"type": "string", "enum": ["inbox","approved","in_progress","awaiting_decision","awaiting_approval","deferred","done","blocked"]},
          "assignee": {"type": "string", "description": "Agent or person responsible"},
          "priority": {"type": "string", "enum": ["low","normal","high","critical"]},
          "tags": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["title"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tack_move",
      "description": "Move a card to a different column",
      "parameters": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "column_name": {"type": "string", "enum": ["inbox","approved","in_progress","awaiting_decision","awaiting_approval","deferred","done","blocked"]},
          "actor": {"type": "string", "description": "Your agent name"}
        },
        "required": ["card_id", "column_name"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tack_update",
      "description": "Update a card's fields",
      "parameters": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "title": {"type": "string"},
          "description": {"type": "string"},
          "assignee": {"type": "string"},
          "priority": {"type": "string", "enum": ["low","normal","high","critical"]},
          "tags": {"type": "array", "items": {"type": "string"}},
          "actor": {"type": "string"}
        },
        "required": ["card_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tack_list",
      "description": "List cards, optionally filtered by column or assignee. Use fields param to save tokens.",
      "parameters": {
        "type": "object",
        "properties": {
          "column": {"type": "string", "enum": ["inbox","approved","in_progress","awaiting_decision","awaiting_approval","deferred","done","blocked"]},
          "assignee": {"type": "string"},
          "fields": {"type": "string", "description": "Comma-separated field names to return, e.g. 'id,title,column_name'"}
        }
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tack_claim",
      "description": "Claim a card so no other agent works on it. Returns 409 if already claimed.",
      "parameters": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "agent": {"type": "string", "description": "Your agent name"},
          "ttl_seconds": {"type": "integer", "description": "Claim duration in seconds (default 300)"}
        },
        "required": ["card_id", "agent"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tack_release",
      "description": "Release your claim on a card",
      "parameters": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "agent": {"type": "string"}
        },
        "required": ["card_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tack_note",
      "description": "Add a note to a card's trace log. Use to document reasoning, findings, or handoff context.",
      "parameters": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "author": {"type": "string"},
          "content": {"type": "string", "description": "The note content"}
        },
        "required": ["card_id", "content"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tack_decision",
      "description": "Request a human decision. Moves card to awaiting_decision with structured options.",
      "parameters": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "question": {"type": "string", "description": "The decision question"},
          "options": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "key": {"type": "string"},
                "label": {"type": "string"},
                "description": {"type": "string"}
              },
              "required": ["key", "label"]
            }
          },
          "context": {"type": "string", "description": "Background info for the decision maker"},
          "actor": {"type": "string"}
        },
        "required": ["card_id", "question", "options"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tack_approval",
      "description": "Request human approval for a plan. Moves card to awaiting_approval. Human sees Approve/Deny buttons.",
      "parameters": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "plan": {"type": "string", "description": "The plan to be approved or denied"},
          "context": {"type": "string", "description": "Background info for the approver"},
          "actor": {"type": "string"}
        },
        "required": ["card_id", "plan"]
      }
    }
  }
]
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TACK_HOST` | `127.0.0.1` | Bind address |
| `TACK_PORT` | `8795` | Port number |
| `TACK_DB` | `./data/board.db` | SQLite database path |
| `TACK_DONE_ARCHIVE_DAYS` | `7` | Auto-hide done cards older than this many days from `/api/board` |
| `TACK_DEFER_DAYS` | `7` | Days before deferred cards auto-return to Awaiting Decision |
| `TACK_API_KEY` | (none) | Optional API key for write operations (reads remain open) |
