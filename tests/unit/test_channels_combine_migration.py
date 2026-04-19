"""Regression tests for ensure_guild_infrastructure combined-mode discovery.

Covers BUG 1: when AXI_COMBINE_LIVE_CATEGORIES=1, the category discovery must
include pre-existing categories matching AXI_CATEGORY_NAME / ACTIVE_CATEGORY_NAME
so channels from a previous non-combined config are still visible to
ensure_agent_channel and reconstruct_agents_from_channels. Otherwise the bot
creates a duplicate #axi-master inside the new combined category while the
pre-existing #axi-master remains in the legacy Axi category.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_USER_IDS", "1")
os.environ.setdefault("DISCORD_GUILD_ID", "1")

from axi import channels


class FakeRole:
    """Hashable stand-in for discord.Role / discord.Member (dict-key compatible)."""
    def __init__(self, rid: int) -> None:
        self.id = rid


class FakeCategory:
    def __init__(self, cid: int, name: str, text_channels: list | None = None) -> None:
        self.id = cid
        self.name = name
        self.text_channels = text_channels or []
        self.channels = self.text_channels  # channel limit check uses .channels
        self.overwrites: dict = {}
        self.edit = AsyncMock()


class FakeGuild:
    def __init__(self, cats: list[FakeCategory]) -> None:
        self.id = 999
        self.categories = cats
        self.default_role = FakeRole(1)
        self.me = FakeRole(2)
        self.create_category = AsyncMock(side_effect=self._create_category)
        self._created: list[FakeCategory] = []

    async def _create_category(self, name: str, overwrites: dict | None = None) -> FakeCategory:
        cat = FakeCategory(cid=100000 + len(self._created), name=name)
        cat.overwrites = overwrites or {}
        self._created.append(cat)
        self.categories.append(cat)
        return cat


class FakeBot:
    def __init__(self, guild: FakeGuild) -> None:
        self._guild = guild

    def get_guild(self, _gid: int) -> FakeGuild:
        return self._guild


def _reset_channel_state() -> None:
    channels.target_guild = None
    channels.axi_categories = []
    channels.active_categories = []
    channels.killed_categories = []


@pytest.mark.asyncio
async def test_default_mode_unchanged() -> None:
    """No combine env vars — classic Axi/Active/Killed discovery still works."""
    _reset_channel_state()
    axi = FakeCategory(1, "Axi")
    active = FakeCategory(2, "Active")
    killed = FakeCategory(3, "Killed")
    guild = FakeGuild([axi, active, killed])

    with patch.object(channels, "_bot", FakeBot(guild)), \
         patch.object(channels.config, "DISCORD_GUILD_ID", 999), \
         patch.object(channels.config, "COMBINE_LIVE_CATEGORIES", False), \
         patch.object(channels.config, "AXI_CATEGORY_NAME", "Axi"), \
         patch.object(channels.config, "ACTIVE_CATEGORY_NAME", "Active"), \
         patch.object(channels.config, "KILLED_CATEGORY_NAME", "Killed"), \
         patch.object(channels.config, "COMBINED_CATEGORY_NAME", "Axi"), \
         patch.object(channels.config, "ALLOWED_USER_IDS", []):
        await channels.ensure_guild_infrastructure()

    assert [c.name for c in channels.axi_categories] == ["Axi"]
    assert [c.name for c in channels.active_categories] == ["Active"]
    assert [c.name for c in channels.killed_categories] == ["Killed"]
    guild.create_category.assert_not_called()


@pytest.mark.asyncio
async def test_combine_mode_discovers_legacy_axi_category() -> None:
    """Combined mode with pre-existing 'Axi' category — must discover it, not recreate."""
    _reset_channel_state()
    legacy_axi = FakeCategory(1, "Axi")
    legacy_active = FakeCategory(2, "Active")
    killed = FakeCategory(3, "Killed")
    guild = FakeGuild([legacy_axi, legacy_active, killed])

    with patch.object(channels, "_bot", FakeBot(guild)), \
         patch.object(channels.config, "DISCORD_GUILD_ID", 999), \
         patch.object(channels.config, "COMBINE_LIVE_CATEGORIES", True), \
         patch.object(channels.config, "AXI_CATEGORY_NAME", "Axi"), \
         patch.object(channels.config, "ACTIVE_CATEGORY_NAME", "Active"), \
         patch.object(channels.config, "KILLED_CATEGORY_NAME", "Killed"), \
         patch.object(channels.config, "COMBINED_CATEGORY_NAME", "Combined"), \
         patch.object(channels.config, "ALLOWED_USER_IDS", []):
        await channels.ensure_guild_infrastructure()

    # Combined category created; legacy Axi + Active are also in axi_categories.
    names = [c.name for c in channels.axi_categories]
    assert "Combined" in names, f"Expected 'Combined' in axi_categories, got {names}"
    assert "Axi" in names, f"Expected legacy 'Axi' in axi_categories, got {names}"
    assert "Active" in names, f"Expected legacy 'Active' in axi_categories, got {names}"

    # Combined must be FIRST so new channels go there (LEGACY_ORDER_BIAS).
    assert names[0] == "Combined", f"Combined must be first; got {names}"

    # Active should NOT have been created independently.
    assert channels.active_categories == []

    # Only Combined was created; legacy Axi/Active were discovered, not recreated.
    created_names = [call.args[0] for call in guild.create_category.call_args_list]
    assert "Combined" in created_names
    assert "Axi" not in created_names
    assert "Active" not in created_names


@pytest.mark.asyncio
async def test_combine_mode_alias_no_double_discovery() -> None:
    """When COMBINED_CATEGORY_NAME == AXI_CATEGORY_NAME, don't double-count."""
    _reset_channel_state()
    axi = FakeCategory(1, "Axi")
    killed = FakeCategory(2, "Killed")
    guild = FakeGuild([axi, killed])

    with patch.object(channels, "_bot", FakeBot(guild)), \
         patch.object(channels.config, "DISCORD_GUILD_ID", 999), \
         patch.object(channels.config, "COMBINE_LIVE_CATEGORIES", True), \
         patch.object(channels.config, "AXI_CATEGORY_NAME", "Axi"), \
         patch.object(channels.config, "ACTIVE_CATEGORY_NAME", "Active"), \
         patch.object(channels.config, "KILLED_CATEGORY_NAME", "Killed"), \
         patch.object(channels.config, "COMBINED_CATEGORY_NAME", "Axi"), \
         patch.object(channels.config, "ALLOWED_USER_IDS", []):
        await channels.ensure_guild_infrastructure()

    axi_ids = [c.id for c in channels.axi_categories]
    assert axi_ids.count(axi.id) == 1, f"Axi category listed more than once: {axi_ids}"
    assert len(channels.axi_categories) == 1, "Expected only one axi category when aliased"


@pytest.mark.asyncio
async def test_combine_mode_fresh_install_only_creates_combined() -> None:
    """Combined mode with no pre-existing categories — only Combined + Killed created."""
    _reset_channel_state()
    guild = FakeGuild([])

    with patch.object(channels, "_bot", FakeBot(guild)), \
         patch.object(channels.config, "DISCORD_GUILD_ID", 999), \
         patch.object(channels.config, "COMBINE_LIVE_CATEGORIES", True), \
         patch.object(channels.config, "AXI_CATEGORY_NAME", "Axi"), \
         patch.object(channels.config, "ACTIVE_CATEGORY_NAME", "Active"), \
         patch.object(channels.config, "KILLED_CATEGORY_NAME", "Killed"), \
         patch.object(channels.config, "COMBINED_CATEGORY_NAME", "Combined"), \
         patch.object(channels.config, "ALLOWED_USER_IDS", []):
        await channels.ensure_guild_infrastructure()

    created_names = [call.args[0] for call in guild.create_category.call_args_list]
    assert created_names == ["Combined", "Killed"]
    assert [c.name for c in channels.axi_categories] == ["Combined"]
    assert channels.active_categories == []


@pytest.mark.asyncio
async def test_combine_mode_legacy_active_only() -> None:
    """Combined mode with only legacy 'Active' (e.g. user never had 'Axi')."""
    _reset_channel_state()
    legacy_active = FakeCategory(1, "Active")
    killed = FakeCategory(2, "Killed")
    guild = FakeGuild([legacy_active, killed])

    with patch.object(channels, "_bot", FakeBot(guild)), \
         patch.object(channels.config, "DISCORD_GUILD_ID", 999), \
         patch.object(channels.config, "COMBINE_LIVE_CATEGORIES", True), \
         patch.object(channels.config, "AXI_CATEGORY_NAME", "Axi"), \
         patch.object(channels.config, "ACTIVE_CATEGORY_NAME", "Active"), \
         patch.object(channels.config, "KILLED_CATEGORY_NAME", "Killed"), \
         patch.object(channels.config, "COMBINED_CATEGORY_NAME", "Combined"), \
         patch.object(channels.config, "ALLOWED_USER_IDS", []):
        await channels.ensure_guild_infrastructure()

    names = [c.name for c in channels.axi_categories]
    assert names[0] == "Combined"
    assert "Active" in names
