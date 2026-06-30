"""Spawn `woodpecker-mcp serve` over stdio (how HolmesGPT launches it), list the
tools, and call them. Targets whatever the WP_* config points at.

  woodpecker-mcp ingest examples/topology.example.json
  WP_AUTO_REFRESH=0 python tests/smoke_mcp.py   # static snapshot
  python tests/smoke_mcp.py                       # live infra
"""
import asyncio
import json
import os
import shutil

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CMD = shutil.which("woodpecker-mcp") or "woodpecker-mcp"
params = StdioServerParameters(command=CMD, args=["serve"], env={**os.environ})


def show(title, result):
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        text = json.dumps(json.loads(text), indent=2)
    except Exception:
        pass
    print(f"\n=== {title} ===\n{text}")


async def main():
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS EXPOSED:")
            for t in tools.tools:
                print(f"  - {t.name}: {t.description.splitlines()[0]}")

            show("get_topology", await session.call_tool("woodpecker_get_topology", {}))
            show("diagnose_root_cause", await session.call_tool("woodpecker_diagnose_root_cause", {}))
            show("blast_radius(db, upstream)",
                 await session.call_tool("woodpecker_get_blast_radius",
                                         {"service": "db", "direction": "upstream"}))
            show("detect_blind_spots", await session.call_tool("woodpecker_detect_blind_spots", {}))


if __name__ == "__main__":
    asyncio.run(main())
