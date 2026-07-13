"""Live read-mostly smoke test against a real Splunk box (reads .env).

Run directly:  uv run python tests/smoke_test.py
Exercises the SplunkClient the tools wrap: server info, health, indexes, apps,
a one-shot search, endpoint discovery, plus an index create -> delete round-trip.
"""

from __future__ import annotations

import asyncio

from splunk_mcp.client import SplunkClient
from splunk_mcp.config import load_settings


async def main() -> None:
    client = SplunkClient(load_settings())
    try:
        info = client.unwrap_entries(await client.get("/services/server/info"))[0]
        print(f"[ok] server: Splunk {info.get('version')} "
              f"({info.get('serverName')}), {info.get('numberOfCores')} cores, "
              f"{info.get('physicalMemoryMB')} MB")

        health = client.unwrap_entries(await client.get("/services/server/health/splunkd"))
        print(f"[ok] health: {health[0].get('health') if health else '?'}")

        idx = await client.list_entries("/services/data/indexes")
        print(f"[ok] indexes: {len(idx)} (e.g. {[i['name'] for i in idx[:5]]})")

        apps = await client.list_entries("/services/apps/local")
        print(f"[ok] apps: {len(apps)} installed")

        res = await client.search_oneshot(
            "| makeresults | eval probe=\"splunk-mcp\"", earliest="-1m", count=1)
        print(f"[ok] search: {len(res.get('results', []))} row(s) from makeresults")

        eps = client.unwrap_entries(await client.get("/services/data"))
        print(f"[ok] endpoints: {len(eps)} under /services/data")

        # create -> delete round-trip
        name = "smoketest_idx"
        await client.post("/services/data/indexes", data={"name": name})
        print(f"[ok] created index {name!r}")
        await client.delete(f"/services/data/indexes/{name}")
        print(f"[ok] deleted index {name!r}")

        print("\nSMOKE TEST PASSED")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
