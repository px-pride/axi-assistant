<!-- test: tests/test_agent_tool_visibility_generated.py -->

# Agent Tool Visibility in Discord

## Application Overview

When an Axi agent uses Claude Code's `Agent` tool, Discord should expose the top-level tool call and the subagent lifecycle in the parent channel. This flow verifies that users can see the Agent tool invocation, identify it by `tool_use_id`, and observe task lifecycle updates without needing direct access to Claude's raw stream.

## Scenarios

### 1. Top-level Agent tool call is announced in the parent channel

**Steps:**
1. In `#axi-master`, spawn a fresh throwaway agent in the test instance.
2. Wait for the spawned agent channel to appear.
3. Send the spawned agent a prompt that explicitly requires using the `Agent` tool exactly once.
4. Poll the spawned agent channel history for new bot messages.

**Expected Results:**
- A bot message appears with a prefix like `` `🔧 Agent ... (<tool_use_id>)` ``.
- The message includes the `tool_use_id` of the top-level Agent call.
- If the runtime provides tool input parameters for that path, the message also includes a JSON code block with the parameters.
- The announcement is only for the top-level Agent tool call, not nested child tool uses.

### 2. Subagent lifecycle is surfaced in the parent channel

**Steps:**
1. Continue polling the spawned agent channel after the Agent tool announcement.
2. Observe task lifecycle updates tied to the same Agent action.

**Expected Results:**
- A lifecycle message appears for the subagent task.
- At minimum, completion is visible as a message like `` `🔧 task completed (<task_id>)` ``.
- If the runtime emits start/progress events on that code path, they should appear as task start/progress messages instead of remaining opaque.
- Lifecycle messages should be updated in place per `task_id` when possible, rather than spamming duplicate progress lines.

### 3. Final user-visible response still completes normally

**Steps:**
1. Wait for the spawned agent to finish the requested task.
2. Inspect the final natural-language response in the spawned agent channel.

**Expected Results:**
- The agent still produces its final response after the visibility messages.
- The visibility messages do not prevent or replace the normal final response.
- Cleanup kills the throwaway agent in a `finally` block.
