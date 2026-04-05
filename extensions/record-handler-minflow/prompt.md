Use the `minflow` CLI to look up relevant tasks and context. **NEVER read or write the workspace JSON file directly.**

Key lookup commands:
- `minflow deck list` — list all decks (projects)
- `minflow deck get <id>` — get a deck with its cards and text fields
- `minflow card list <deck-id>` — list cards in a deck

**Decks** are project containers on a visual canvas. Each has a title, cards (tasks), and text fields:
- `description` — one-liner project overview
- `status` — lifecycle status (idea, planning, active, prototype, stable, paused, blocked, done)
- `done` — completed milestones narrative
- `notes` — open questions, references, misc context

Read deck text fields (via `minflow deck get`) to understand project context before making changes.

**Cards** are tasks inside a deck, ordered by priority — the top card is the next task to complete.

When starting work on a project, recommend the top card and offer to start on it — don't list all cards and ask the user to pick.

If the `minflow` CLI is not available, fall back to a RECORDS.md file in your working directory.
