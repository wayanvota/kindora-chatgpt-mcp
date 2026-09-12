from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import server


@dataclass
class FixtureResult:
    data: Any
    structured_content: Any = None
    content: list[Any] | None = None


class FixtureClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        values = list(arguments.values())
        if "__ERROR__" in values:
            raise RuntimeError("fixture-upstream-secret-must-not-escape")
        if "__SLOW__" in values:
            await asyncio.sleep(0.05)
        return FixtureResult(data={"fixture": True, "tool": name, "arguments": arguments})


server.Client = lambda *_args, **_kwargs: FixtureClient()


if __name__ == "__main__":
    server.main()
