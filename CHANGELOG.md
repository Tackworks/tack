# Changelog

## [1.3.0] - 2026-04-08

### Added
- **Card completion workflow** — `POST /api/cards/{id}/complete` moves to Done with a structured completion note. Agents decide whether a followup is needed.
- **Follow-up cards** — Complete with `followup: true` to auto-create a linked card in Inbox. Inherits assignee, priority, and tags from the parent. Shows "follows" badge on the card.
- **Thread view** — `GET /api/cards/{id}/thread` walks the follow-up chain (ancestors and descendants) to show the full workflow history.
- **Completion dialog in UI** — Dragging to Done shows a completion form with optional follow-up checkbox. Ctrl+Enter to submit.
- **Optional API key auth** — Set `TACK_API_KEY` to require authentication on write operations.
- **108-test suite** — pytest tests covering all API endpoints including the new completion/followup workflow.

### Fixed
- Narrowed exception handling in migration code (catches `sqlite3.OperationalError` only)
- CI now runs the full test suite

## [1.2.0] - 2026-04-08

### Added
- Optional API key auth, 97-test suite, CI improvements

## [1.1.0] - 2026-04-08

### Added
- **Dark/Light theme toggle** (Issue #1) — Click the moon/sun icon in the header or use localStorage to persist preference. Light theme designed for daylight readability.
- **Card search/filter** (Issue #2) — Real-time search across title, description, assignee, and tags. Press `/` to focus search, `Escape` to clear. Column counts show `matches/total` while filtering.
- **Deferred column** — Cards auto-return to Awaiting Decision after configurable period (`TACK_DEFER_DAYS`, default 7 days).
- **Note on move** — Optional note popup when dragging cards between columns.
- **Notes in card modal** — View and add notes directly from the card edit dialog.
- **Delete with reason** — Card deletion requires a reason (via `POST /api/cards/{id}/delete`).
- **Server-side search** — `GET /api/cards?q=term&tag=name&priority=high` for API consumers.

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
- Webhook support (planned, not yet implemented — use [Spur](https://github.com/Tackworks/spur) for event relay)
- Activity log and change polling
- Drag-and-drop web UI with keyboard shortcuts
- SQLite backend, single-file server
- Docker support
