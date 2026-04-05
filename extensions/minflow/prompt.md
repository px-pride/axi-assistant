# MinFlow Conventions

MinFlow is the user's visual task management app with decks (project containers) and cards (tasks).

- Cards are ordered by priority — the top card in a deck is the next task to complete
- **Always break tasks into multiple cards** following the default progression: **plan -> implement -> test -> commit/push**. If a deck has only a single vague card, replace it with this breakdown. One card = one clear step.
- When a task involves multiple distinct feature areas, each area gets its own plan -> implement -> test cycle. Don't collapse an area into a single card just because there are many areas.
- When starting work on a project, recommend the top card and offer to start on it — don't list all cards and ask the user to pick
- Only mark a card done (`minflow card done`) when the outcome is **verified correct** — not just when you think you're finished. If anything unexpected happened during execution (wrong environment, errors you worked around, partial results, untested assumptions), the card is not done. Verify before completing.
- After completing a card, move to the next card in the deck. Discuss it briefly with the user before executing.
- When the user mentions "cards" and "decks" without context, they mean MinFlow
- When referencing MinFlow data, always cite the deck ID and card ID. Example: "card `mnj7p0wn` in deck `mm5jyp`"

## MinFlow and Core Files

MinFlow must never be referenced in core files (SOUL.md, soul.json, dev_context.md, bot.py, handlers.py, supervisor.py, prompts.py). MinFlow-specific instructions belong only in MinFlow extensions and MinFlow-specific flowcharts (mil.json, mill.json).
