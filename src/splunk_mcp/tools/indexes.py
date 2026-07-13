"""Index tools: list/create/delete indexes and see their size/event counts."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps

_SLIM = ("name", "disabled", "totalEventCount", "currentDBSizeMB",
         "maxTotalDataSizeMB", "frozenTimePeriodInSecs", "homePath", "datatype")


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_list_indexes() -> str:
        """List indexes with event counts and sizes (name, events, DB size MB, retention)."""
        rows = await client.list_entries("/services/data/indexes")
        return dumps([{k: r.get(k) for k in _SLIM} for r in rows])

    @mcp.tool()
    async def splunk_get_index(name: str) -> str:
        """Full detail for one index."""
        rows = client.unwrap_entries(await client.get(f"/services/data/indexes/{name}"))
        return dumps(rows[0] if rows else {})

    @mcp.tool()
    async def splunk_create_index(
        name: str,
        max_total_size_mb: int | None = None,
        frozen_time_period_secs: int | None = None,
        datatype: str = "event",
    ) -> str:
        """Create an index (e.g. a dedicated 'cisco' or 'windows' index for lab telemetry).

        Args:
            name: index name (lowercase, no spaces).
            max_total_size_mb: max index size before rolling to frozen (optional).
            frozen_time_period_secs: retention in seconds before freezing/deleting (optional).
            datatype: 'event' (default) or 'metric'.
        """
        body: dict = {"name": name, "datatype": datatype}
        if max_total_size_mb is not None:
            body["maxTotalDataSizeMB"] = max_total_size_mb
        if frozen_time_period_secs is not None:
            body["frozenTimePeriodInSecs"] = frozen_time_period_secs
        return dumps(await client.post("/services/data/indexes", data=body))

    @mcp.tool()
    async def splunk_delete_index(name: str) -> str:
        """Delete an index (removes its data). Cannot be undone."""
        return dumps(await client.delete(f"/services/data/indexes/{name}"))
