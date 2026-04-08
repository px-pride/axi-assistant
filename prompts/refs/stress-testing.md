# Stress Testing Reference

Instructions for stress testing the Axi test infrastructure. Read this when asked to stress test, verify test infra health, or after making changes to test infrastructure code.

## What to Test

Stress testing should cover ALL major subsystems, not just the one you're currently debugging:

1. **Message processing** — rapid-fire messages, queued message handling, flowchart completion
2. **Agent spawning** — spawn multiple agents, verify they wake and get their own channels
3. **Agent lifecycle** — send tasks to agents, verify responses, kill agents, confirm channel cleanup
4. **Concurrent agents** — multiple agents running simultaneously, no cross-talk or resource conflicts
5. **Edge cases** — spawn with same name as killed agent, spawn during active message processing, messages to sleeping agents

## Procedure

1. **Set up**: `uv run python axi_test.py up <name> --wait` to create a test instance
2. **Start**: `uv run python axi_test.py restart <name>` (or `systemctl --user start axi-test@<name>`)
3. **Verify startup**: Check journal logs for successful startup notification
4. **Run test rounds** for each subsystem above:
   - Use `discord_send_message` to send test messages to the instance's master channel
   - Use `discord_wait_for_message` to verify responses
   - Use `discord_list_channels` to verify agent channels are created/cleaned up
   - Check journal logs for errors between rounds
5. **Record results**: Log which subsystems passed/failed and any error details
6. **Tear down**: `uv run python axi_test.py down <name>`

## Message Processing Tests

- Send a single message, verify response completes (STREAM_END result=ok)
- Send two messages rapidly so the second queues, verify both complete
- Send 3+ messages rapidly, verify all process in order
- Verify flowchart blocks execute (CLASSIFY, RESPOND, GATHER_NEXT_ACTION, SET_STATUS)

## Agent Spawning Tests

- Spawn an agent via the test instance's master channel (ask the bot to spawn one)
- Verify a new Discord channel appears for the agent
- Send a message in the agent's channel, verify it responds
- Kill the agent, verify the channel is cleaned up or marked inactive
- Spawn another agent with the same name, verify no conflicts

## Success Criteria

All subsystems should pass. If any fail, investigate before declaring the infra healthy. A partial test (e.g., only testing message processing) is not a complete stress test.
