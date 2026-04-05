# Timeouts

Every timeout you add to any code — no matter how obvious, reasonable, or defensive it seems — must be explicitly approved by the user before implementation. State the timeout value, where it applies, and what happens when it fires. Do not add timeouts silently as part of a larger change.

Timeouts interact with queues, concurrency, and retry logic in non-obvious ways. A "safe" timeout can cause cascading failures when multiple callers are waiting in line.
