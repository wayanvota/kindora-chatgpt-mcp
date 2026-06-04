"""Offline tests for the Kindora ChatGPT MCP wrapper.

These run without network access: tool registration is introspected, and the
upstream proxy is exercised through a stubbed client. A live round-trip against
Kindora is intentionally not tested here (it needs outbound network and would be
flaky in CI).

Run:  pytest
"""

import asyncio

import pytest
from fastmcp import Client

import server

EXPECTED_TOOLS = {
    "search_funders",
    "search_open_grants",
    "search_funder_jobs",
    "get_funder_profile",
    "get_990_summary",
    "get_foundation_grants",
    "get_funder_stats",
    "get_ntee_codes",
    "health_check",
}


async def _tool_objects():
    # Introspect via the public in-memory Client (stable across FastMCP 2.x/3.x).
    # Returns MCP Tool objects with .name and .annotations.
    async with Client(server.mcp) as client:
        return await client.list_tools()


def test_all_tools_registered():
    tools = asyncio.run(_tool_objects())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS


def test_every_tool_is_read_only():
    tools = asyncio.run(_tool_objects())
    for t in tools:
        ann = getattr(t, "annotations", None)
        assert ann is not None and ann.readOnlyHint is True, f"{t.name} not read-only"


# --- _call() normalization, with a stubbed upstream client -------------------

class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Result:
    def __init__(self, data=None, structured=None, content=None):
        self.data = data
        self.structured_content = structured
        self.content = content or []


class _FakeClient:
    last_args = None

    def __init__(self, result):
        self._result = result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, arguments):
        type(self).last_args = arguments
        return self._result


def _patch(monkeypatch, result):
    monkeypatch.setattr(server, "Client", lambda *a, **k: _FakeClient(result))


def test_call_prefers_structured_data(monkeypatch):
    _patch(monkeypatch, _Result(data={"ok": 1}))
    assert asyncio.run(server._call("x", {})) == {"ok": 1}


def test_call_falls_back_to_structured_content(monkeypatch):
    _patch(monkeypatch, _Result(structured={"s": 2}))
    assert asyncio.run(server._call("x", {})) == {"s": 2}


def test_call_parses_text_json(monkeypatch):
    _patch(monkeypatch, _Result(content=[_Block('{"j": 3}')]))
    assert asyncio.run(server._call("x", {})) == {"j": 3}


def test_call_wraps_plain_text(monkeypatch):
    _patch(monkeypatch, _Result(content=[_Block("hello")]))
    assert asyncio.run(server._call("x", {})) == {"result": "hello"}


def test_call_strips_null_arguments(monkeypatch):
    _patch(monkeypatch, _Result(data={"ok": 1}))
    asyncio.run(server._call("x", {"keep": 5, "drop": None}))
    assert _FakeClient.last_args == {"keep": 5}
