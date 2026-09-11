"""
Kindora-for-ChatGPT MCP server.

A thin FastMCP server that re-exposes the public Kindora funder/grant tools so they
can be added to ChatGPT as a custom MCP connector ("Developer mode" / Apps).

Why a wrapper instead of pointing ChatGPT straight at Kindora?
  * Curated, ChatGPT-friendly tool descriptions and argument docs.
  * read-only annotations so ChatGPT will run the tools without write-confirmation prompts.
  * A single endpoint you control (auth, rate limiting, logging, header injection)
    sitting in front of Kindora's live API.

It works as an MCP -> MCP proxy: every tool below forwards the call to the live
Kindora MCP endpoint (default: https://kindora-mcp.azurewebsites.net/mcp/) and returns the result
unchanged. All tools are read-only and hit public IRS 990 / Grants.gov data.

Transports
  * stdio (default)            -> local testing, Claude Desktop, etc.
  * http  (streamable-http)    -> required for ChatGPT, which connects to a public URL.

Run:
  pip install -r requirements.txt
  # local stdio:
  python server.py
  # public HTTP endpoint for ChatGPT:
  TRANSPORT=http HOST=0.0.0.0 PORT=8000 python server.py
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Any, Optional

# An MCP stdio server must not make an unrelated network request or print a
# banner while establishing its protocol connection.
os.environ.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")
os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from pydantic import Field

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# The live upstream Kindora MCP endpoint that we proxy to.
KINDORA_MCP_URL = os.environ.get("KINDORA_MCP_URL", "https://kindora-mcp.azurewebsites.net/mcp/")

# Optional bearer token forwarded to Kindora (the public/free tier needs none;
# set this if you have been issued a key).
KINDORA_API_KEY = os.environ.get("KINDORA_API_KEY")

# How long (seconds) to wait on an upstream call before giving up.
UPSTREAM_TIMEOUT = float(os.environ.get("KINDORA_TIMEOUT", "60"))

READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}
Limit = Annotated[int, Field(ge=1, le=50)]
GrantWindow = Annotated[int, Field(ge=1, le=365)]
JobWindow = Annotated[int, Field(ge=0, le=730)]
FilingYears = Annotated[int, Field(ge=1, le=10)]
ShortText = Annotated[str, Field(max_length=500)]
Ein = Annotated[str, Field(pattern=r"^\d{2}-?\d{7}$")]
EinList = Annotated[list[Ein], Field(max_length=100)]

mcp = FastMCP(
    name="kindora-chatgpt",
    instructions=(
        "Access to Kindora's philanthropy data: 174K+ US foundations, 32K+ European "
        "funders, and 43K+ open grant opportunities sourced from IRS 990 filings and "
        "Grants.gov.\n\n"
        "Choosing a tool:\n"
        " - User describes a cause/topic and wants live opportunities or RFPs -> search_open_grants.\n"
        " - User wants funder ORGANIZATIONS aligned to a cause, or names a specific funder -> search_funders.\n"
        " - User wants philanthropy JOBS (program officers, grants managers, foundation CEOs) -> search_funder_jobs.\n"
        " - Once you have an EIN, drill in with get_funder_profile, get_990_summary, "
        "get_foundation_grants, or get_funder_stats.\n"
        " - get_ntee_codes resolves cause areas to NTEE classification codes.\n"
        "All tools are read-only and return public data."
    ),
)


# --------------------------------------------------------------------------- #
# Upstream proxy helper
# --------------------------------------------------------------------------- #

def _build_transport() -> StreamableHttpTransport:
    headers = {}
    if KINDORA_API_KEY:
        headers["Authorization"] = f"Bearer {KINDORA_API_KEY}"
    return StreamableHttpTransport(url=KINDORA_MCP_URL, headers=headers or None)


async def _call(tool: str, arguments: dict[str, Any]) -> Any:
    """Forward a tool call to the live Kindora MCP server and return its payload.

    Drops null arguments (Kindora expects omitted optionals, not explicit nulls),
    opens a short-lived streamable-HTTP session, and normalizes the result into a
    plain JSON-serializable object.
    """
    arguments = {k: v for k, v in arguments.items() if v is not None}

    try:
        async with Client(_build_transport(), timeout=UPSTREAM_TIMEOUT) as client:
            result = await client.call_tool(tool, arguments)
    except Exception as exc:  # noqa: BLE001
        raise ToolError("Kindora could not complete the request. Try again later.") from exc

    # fastmcp >=2 exposes deserialized structured output on .data, falling back
    # to .structured_content, then raw text content blocks.
    data = getattr(result, "data", None)
    if data is not None:
        return data

    structured = getattr(result, "structured_content", None)
    if structured:
        return structured

    texts = [
        getattr(block, "text", "")
        for block in (getattr(result, "content", None) or [])
        if getattr(block, "type", None) == "text"
    ]
    joined = "\n".join(t for t in texts if t)
    try:
        return json.loads(joined)
    except (json.JSONDecodeError, ValueError):
        return {"result": joined}


# --------------------------------------------------------------------------- #
# Discovery tools
# --------------------------------------------------------------------------- #

@mcp.tool(annotations=READ_ONLY)
async def search_funders(
    query: Optional[ShortText] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    ntee_code: Optional[str] = None,
    min_assets: Optional[int] = None,
    max_assets: Optional[int] = None,
    has_er_grants: Optional[bool] = None,
    funder_type: Optional[str] = None,
    exclude_funder_types: Optional[list[str]] = None,
    country: Optional[list[str]] = None,
    grantee_country_codes: Optional[list[str]] = None,
    limit: Limit = 20,
) -> Any:
    """Find grantmaking organizations by name, cause area, or location.

    Searches 174K+ US foundations plus 32K+ European funders from IRS 990 data.
    Use this to find aligned funders (including ones that fund by relationship, LOI,
    or annual cycle rather than a live RFP), or when the user names a specific funder.
    For active/open opportunities use search_open_grants instead.

    Args:
        query: Funder name or cause-area phrase. Topic searches work best with 2+ words
            (e.g. "Ford Foundation", "global health", "community foundation").
        state: Two-letter US state code for funder HQ (e.g. "CA", "NY").
        city: City name for funder HQ (case-insensitive).
        ntee_code: NTEE classification code to filter by (e.g. "E" Health, "B" Education).
        min_assets: Minimum total assets in dollars (e.g. 10000000).
        max_assets: Maximum total assets in dollars.
        has_er_grants: If true, only funders that make expenditure-responsibility grants
            (to non-501(c)(3) entities like PBCs, for-profits, foreign orgs).
        funder_type: Narrow to one type, e.g. "community_foundation", "family_foundation",
            "corporate_foundation", "private_operating", "independent_foundation".
        exclude_funder_types: Types to hide, e.g. ["operating_nonprofit"] to drop orgs that
            surface with large annual_grants but are not really grantmakers.
        country: One or more funder HQ countries for non-US funders
            (e.g. ["Germany", "Spain", "Netherlands"]).
        grantee_country_codes: ISO 3166-1 alpha-2 codes for where the funder's grantees are
            based (e.g. ["IN"], ["KE", "SF"]).
        limit: Max results, 1-50 (default 20).
    """
    return await _call("search_funders", {
        "query": query, "state": state, "city": city, "ntee_code": ntee_code,
        "min_assets": min_assets, "max_assets": max_assets, "has_er_grants": has_er_grants,
        "funder_type": funder_type, "exclude_funder_types": exclude_funder_types,
        "country": country, "grantee_country_codes": grantee_country_codes, "limit": limit,
    })


@mcp.tool(annotations=READ_ONLY)
async def search_open_grants(
    query: Optional[ShortText] = None,
    focus_area: Optional[str] = None,
    agency: Optional[str] = None,
    state: Optional[str] = None,
    country: Optional[str] = None,
    deadline_days: GrantWindow = 90,
    min_award: Optional[int] = None,
    max_award: Optional[int] = None,
    nonprofit_only: bool = True,
    source: Optional[str] = None,
    limit: Limit = 20,
) -> Any:
    """Find OPEN grant opportunities and RFPs by topic or cause area.

    The primary tool for finding grants. Searches 172K+ foundation programs and federal
    Grants.gov opportunities across program names, descriptions, focus areas, and
    beneficiary types, with stemming and natural-language matching.

    Query syntax: natural language ("affordable housing for seniors"), quoted phrases
    ('"after school"'), and exclusion ("education -higher"). Omit query to browse broadly
    open programs sorted by upcoming deadline.

    Args:
        query: Natural-language search (e.g. "STEM education for girls", "food bank hunger").
        focus_area: Filter foundation programs by focus area (e.g. "Education", "Health").
        agency: Filter government grants by agency (e.g. "Department of Education", "NSF").
        state: Two-letter US state code; returns state-focused plus nationally available programs.
        country: Country name for non-US targeting (e.g. "India", "Kenya", "Global").
        deadline_days: Deadline lookahead window in days, 1-365 (default 90).
        min_award: Minimum award amount in dollars.
        max_award: Maximum award amount in dollars.
        nonprofit_only: Restrict to nonprofit-eligible opportunities (default true).
        source: Limit to one source: "foundation" or "government".
        limit: Max results, 1-50 (default 20).
    """
    return await _call("search_open_grants", {
        "query": query, "focus_area": focus_area, "agency": agency, "state": state,
        "country": country, "deadline_days": deadline_days, "min_award": min_award,
        "max_award": max_award, "nonprofit_only": nonprofit_only, "source": source,
        "limit": limit,
    })


@mcp.tool(annotations=READ_ONLY)
async def search_funder_jobs(
    query: Optional[ShortText] = None,
    category: Optional[str] = None,
    state: Optional[str] = None,
    country: Optional[str] = None,
    funder_ein: Optional[Ein] = None,
    funder_eins: Optional[EinList] = None,
    employment_type: Optional[str] = None,
    exclude_categories: Optional[list[str]] = None,
    remote: Optional[str] = None,
    posted_within_days: JobWindow = 365,
    sort_by: str = "funder_giving",
    limit: Limit = 20,
) -> Any:
    """Find OPEN philanthropy jobs at grantmaking foundations.

    Roles involved in giving money away, running philanthropic programs, or executive
    leadership of philanthropic work. Backed by a weekly scrape of ~50K funder career
    pages plus LLM classification. Use this for jobs/careers/hiring questions, NOT for
    grant opportunities (use search_open_grants for those).

    For a cause area not covered by the categories below, first call search_funders to
    get matching funder EINs, then pass them here via funder_eins.

    Args:
        query: Keyword search on job title (e.g. "program officer", "grants manager", "CEO").
        category: One of grantmaking, program_leadership, executive_leadership,
            philanthropy_operations, program_support, development_for_grantmaking,
            philanthropy_communications, philanthropy_strategy.
        state: Two-letter US state code.
        country: Funder HQ country as ISO alpha-2 ("US", "GB", "DE") or name ("Germany").
        funder_ein: Restrict to a single funder by EIN.
        funder_eins: Restrict to a list of funder EINs (up to 100).
        employment_type: e.g. "full_time", "fellowship".
        exclude_categories: Categories to hide. Defaults to hiding philanthropy_operations;
            pass [] to include every category.
        remote: Remote filter, e.g. "remote", "hybrid", "onsite".
        posted_within_days: Recency window in days, 0-730 (0 disables; default 365).
        sort_by: "funder_giving" (biggest funders first, default) or "recent".
        limit: Max results, 1-50 (default 20).
    """
    return await _call("search_funder_jobs", {
        "query": query, "category": category, "state": state, "country": country,
        "funder_ein": funder_ein, "funder_eins": funder_eins,
        "employment_type": employment_type, "exclude_categories": exclude_categories,
        "remote": remote, "posted_within_days": posted_within_days, "sort_by": sort_by,
        "limit": limit,
    })


# --------------------------------------------------------------------------- #
# Profile & financials tools (require an EIN)
# --------------------------------------------------------------------------- #

@mcp.tool(annotations=READ_ONLY)
async def get_funder_profile(ein: Ein) -> Any:
    """Get a detailed profile for one foundation by EIN.

    Returns legal name, location, financials (total assets, annual grants), leadership,
    classification (foundation type, NTEE), and website. Use search_funders first to find
    the EIN.

    Args:
        ein: Foundation EIN, 9 digits, with or without hyphen ("94-3136777" or "943136777").
    """
    return await _call("get_funder_profile", {"ein": ein})


@mcp.tool(annotations=READ_ONLY)
async def get_990_summary(ein: Ein, years: FilingYears = 5) -> Any:
    """Get an IRS 990 / 990-PF financial summary and year-over-year trends for a foundation.

    Returns per-year revenue, end-of-year assets, grants paid, mission text, and computed
    trends for assets, grants, and revenue.

    Args:
        ein: Foundation EIN, 9 digits, with or without hyphen.
        years: Number of years of filings to return, 1-10 (default 5).
    """
    return await _call("get_990_summary", {"ein": ein, "years": years})


@mcp.tool(annotations=READ_ONLY)
async def get_foundation_grants(
    ein: Ein,
    year: Optional[int] = None,
    ntee_code: Optional[str] = None,
    recipient_country: Optional[str] = None,
    recipient_state: Optional[str] = None,
    purpose_keyword: Optional[str] = None,
    limit: Limit = 20,
) -> Any:
    """List individual grants a foundation has made, from its 990-PF filings.

    Ordered largest-first with aggregate stats. Each grant reports recipient HQ country
    and US state when known. Note: recipient_country is where the grantee is registered,
    not necessarily where program work happens.

    Args:
        ein: Foundation EIN, 9 digits, with or without hyphen.
        year: Optional filing year filter (e.g. 2023).
        ntee_code: Optional NTEE code to filter recipients (e.g. "B41", "E").
        recipient_country: ISO 3166-1 alpha-2 recipient HQ country (e.g. "IN", "CH", "ZA").
        recipient_state: Two-letter US state code for recipient HQ.
        purpose_keyword: Case-insensitive substring matched against grant purpose
            (e.g. "vaccine", "digital health").
        limit: Max grants, 1-50 (default 20).
    """
    return await _call("get_foundation_grants", {
        "ein": ein, "year": year, "ntee_code": ntee_code,
        "recipient_country": recipient_country, "recipient_state": recipient_state,
        "purpose_keyword": purpose_keyword, "limit": limit,
    })


@mcp.tool(annotations=READ_ONLY)
async def get_funder_stats(ein: Ein) -> Any:
    """Get aggregate giving statistics for a foundation.

    Lifetime totals, average/median/min/max grant size, top NTEE focus areas, US-state and
    recipient-HQ-country distribution (each with avg grant size), a non_us_recipient_pct
    headline, and a year-by-year breakdown. Useful for prospect targeting.

    Args:
        ein: Foundation EIN, 9 digits, with or without hyphen.
    """
    return await _call("get_funder_stats", {"ein": ein})


# --------------------------------------------------------------------------- #
# Reference & system tools
# --------------------------------------------------------------------------- #

@mcp.tool(annotations=READ_ONLY)
async def get_ntee_codes(
    category: Optional[str] = None,
    query: Optional[ShortText] = None,
) -> Any:
    """Browse or search NTEE classification codes for cause areas.

    Call with no arguments to list all 26 major categories. Filter by category letter or
    search by description to find codes for use with search_funders / get_foundation_grants.

    Args:
        category: Single letter A-Z (e.g. "E" Health Care, "B" Education, "P" Human Services).
        query: Search term against code descriptions (e.g. "education", "youth development").
    """
    return await _call("get_ntee_codes", {"category": category, "query": query})


@mcp.tool(annotations=READ_ONLY)
async def health_check() -> Any:
    """Check that the upstream Kindora service is reachable and healthy."""
    return await _call("health_check", {})


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> None:
    transport = os.environ.get("TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        mcp.run(
            transport="http",
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8000")),
            path=os.environ.get("MCP_PATH", "/mcp"),
        )
    else:
        mcp.run()  # stdio


if __name__ == "__main__":
    main()
