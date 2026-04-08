# Changelog

## [1.0.0] - 2026-04-08

Initial public release.

- Kanban board with 7 columns (Inbox, Approved, In Progress, Awaiting Decision, Awaiting Approval, Blocked, Done)
- Full REST API for card CRUD, moves, claims, notes, decisions, approvals
- Sparse-field reads (`?fields=id,title,column_name`) to save tokens
- Atomic card claiming with configurable TTL and 409 conflict handling
- Per-card trace log (append-only notes for agent reasoning)
- Human-in-the-loop decisions with structured options
- Plan approvals (yes/no with comments)
- Batch operations (`POST /api/batch`)
- Webhook support (`TACK_WEBHOOKS` env var)
- Activity log and change polling
- Drag-and-drop web UI with keyboard shortcuts
- SQLite backend, single-file server
- Docker support
