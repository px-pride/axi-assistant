# Discord Message Query Reference

You can query Discord server message history on demand using discord_query.py in your working directory.
Run it via bash to look up messages, browse channel history, or search for content.

## List servers the bot is in
```
python discord_query.py guilds
```
Returns JSONL with guild id and name. Use this to discover guild IDs.

## List channels in a server
```
python discord_query.py channels <guild_id>
```
Returns JSONL with channel id, name, type, and category.

## Fetch message history from a channel
```
python discord_query.py history <channel_id> [--limit 50] [--before DATETIME_OR_ID] [--after DATETIME_OR_ID] [--format text]
```
You can use guild_id:channel_name instead of a raw channel ID (e.g. `123456789:general`).
Default format is JSONL. Use --format text for human-readable output.
Accepts ISO datetimes (e.g. 2026-02-21T10:00:00+00:00) or Discord snowflake IDs for --before/--after.
Max 500 messages per query.

## Search messages in a server
```
python discord_query.py search <guild_id> "search term" [--channel CHANNEL] [--author USERNAME] [--limit 50] [--format text]
```
Case-insensitive substring search over recent message history.
Use --channel to limit to a specific channel, --author to filter by username.
This scans recent history (not a full-text index), so results are limited to the last ~500 messages per channel.
