from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport


ROOT = Path(__file__).parents[1]
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


@pytest_asyncio.fixture
async def protocol_client():
    transport = PythonStdioTransport(
        ROOT / "tests" / "fixture_server.py",
        cwd=str(ROOT),
        env={
            "KINDORA_API_KEY": "fixture-api-key-must-not-escape",
            "FASTMCP_SHOW_SERVER_BANNER": "false",
            "FASTMCP_CHECK_FOR_UPDATES": "off",
        },
        keep_alive=False,
    )
    # FastMCP 4 defaults to probing the experimental 2026 protocol first.
    # This server intentionally supports the stable MCP handshake used by
    # ChatGPT and desktop clients, so pin the public legacy negotiation path.
    async with Client(transport, timeout=5, mode="legacy") as client:
        yield client


async def call_data(client: Client, name: str, arguments: dict | None = None):
    result = await client.call_tool(name, arguments or {})
    return result.data


@pytest.mark.asyncio
async def test_u01_stdio_process_starts_and_discovers_complete_toolset(protocol_client):
    tools = await protocol_client.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_u02_discovery_explains_tool_selection_and_read_only_boundary(protocol_client):
    tools = await protocol_client.list_tools()
    assert all(tool.annotations and tool.annotations.read_only_hint is True for tool in tools)
    assert all(tool.description for tool in tools)


@pytest.mark.asyncio
async def test_u03_search_funders_round_trips_through_protocol(protocol_client):
    data = await call_data(protocol_client, "search_funders", {"query": "community health", "state": "NC"})
    assert data == {"fixture": True, "tool": "search_funders", "arguments": {"query": "community health", "state": "NC", "limit": 20}}


@pytest.mark.asyncio
async def test_u04_optional_nulls_are_omitted_before_upstream_call(protocol_client):
    data = await call_data(protocol_client, "search_funders", {"query": "education", "city": None})
    assert "city" not in data["arguments"]


@pytest.mark.asyncio
async def test_u05_unicode_and_punctuation_survive_round_trip(protocol_client):
    query = "Niñas' health access 🌍"
    data = await call_data(protocol_client, "search_funders", {"query": query})
    assert data["arguments"]["query"] == query


@pytest.mark.asyncio
async def test_u06_open_grant_defaults_are_applied(protocol_client):
    data = await call_data(protocol_client, "search_open_grants", {"query": "rural health"})
    assert data["arguments"]["deadline_days"] == 90
    assert data["arguments"]["nonprofit_only"] is True
    assert data["arguments"]["limit"] == 20


@pytest.mark.asyncio
async def test_u07_ein_drilldown_tools_route_to_matching_upstream_names(protocol_client):
    for name in ("get_funder_profile", "get_990_summary", "get_foundation_grants", "get_funder_stats"):
        data = await call_data(protocol_client, name, {"ein": "94-3136777"})
        assert data["tool"] == name
        assert data["arguments"]["ein"] == "94-3136777"


@pytest.mark.asyncio
async def test_u08_ntee_reference_call_supports_empty_arguments(protocol_client):
    data = await call_data(protocol_client, "get_ntee_codes")
    assert data["tool"] == "get_ntee_codes"
    assert data["arguments"] == {}


@pytest.mark.asyncio
async def test_u09_health_check_completes_through_stdio(protocol_client):
    data = await call_data(protocol_client, "health_check")
    assert data == {"fixture": True, "tool": "health_check", "arguments": {}}


@pytest.mark.asyncio
async def test_u10_repeated_calls_remain_independent_in_one_session(protocol_client):
    first = await call_data(protocol_client, "search_funders", {"query": "first"})
    second = await call_data(protocol_client, "search_funders", {"query": "second"})
    assert first["arguments"]["query"] == "first"
    assert second["arguments"]["query"] == "second"


@pytest.mark.asyncio
async def test_a01_unknown_tool_is_rejected(protocol_client):
    result = await protocol_client.call_tool("delete_everything", {}, raise_on_error=False)
    assert result.is_error


@pytest.mark.asyncio
async def test_a02_missing_required_ein_is_rejected(protocol_client):
    result = await protocol_client.call_tool("get_funder_profile", {}, raise_on_error=False)
    assert result.is_error


@pytest.mark.asyncio
async def test_a03_type_confused_limit_is_rejected(protocol_client):
    result = await protocol_client.call_tool("search_funders", {"limit": {"value": 20}}, raise_on_error=False)
    assert result.is_error


@pytest.mark.asyncio
async def test_a04_out_of_range_limit_is_rejected(protocol_client):
    result = await protocol_client.call_tool("search_funders", {"limit": 5000}, raise_on_error=False)
    assert result.is_error


@pytest.mark.asyncio
async def test_a05_markup_payload_remains_inert_structured_data(protocol_client):
    query = '<img src=x onerror="alert(1)">'
    data = await call_data(protocol_client, "search_funders", {"query": query})
    assert data["arguments"]["query"] == query


@pytest.mark.asyncio
async def test_a06_interpreter_payload_remains_inert_structured_data(protocol_client):
    query = "'; DROP TABLE foundations; --"
    data = await call_data(protocol_client, "search_funders", {"query": query})
    assert data["arguments"]["query"] == query


@pytest.mark.asyncio
async def test_a07_oversized_query_is_rejected(protocol_client):
    result = await protocol_client.call_tool("search_funders", {"query": "x" * 501}, raise_on_error=False)
    assert result.is_error


@pytest.mark.asyncio
async def test_a08_oversized_ein_list_is_rejected(protocol_client):
    result = await protocol_client.call_tool(
        "search_funder_jobs",
        {"funder_eins": ["94-3136777"] * 101},
        raise_on_error=False,
    )
    assert result.is_error


@pytest.mark.asyncio
async def test_a09_upstream_exception_is_generic_and_secret_safe(protocol_client):
    result = await protocol_client.call_tool(
        "search_funders", {"query": "__ERROR__"}, raise_on_error=False
    )
    assert result.is_error
    text = str(result)
    assert "Try again later" in text
    assert "fixture-upstream-secret" not in text


@pytest.mark.asyncio
async def test_a10_discovery_and_errors_never_expose_configured_key(protocol_client):
    tools = await protocol_client.list_tools()
    result = await protocol_client.call_tool(
        "search_funders", {"query": "__ERROR__"}, raise_on_error=False
    )
    combined = str(tools) + str(result)
    assert "fixture-api-key-must-not-escape" not in combined
    assert len(tools) == 9
