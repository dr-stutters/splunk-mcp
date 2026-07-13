"""Search tools: one-shot SPL, async search jobs, and saved searches."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_search(
        query: str,
        earliest: str = "-24h",
        latest: str = "now",
        count: int = 100,
    ) -> str:
        """Run a one-shot (blocking) SPL search and return the results as JSON.

        Best for quick, bounded lookups. For big/slow searches use
        splunk_search_job. A bare filter is auto-prefixed with 'search '.

        Args:
            query: SPL, e.g. 'index=_internal | stats count by sourcetype' or
                'index=main sourcetype=cisco:asa | head 20'.
            earliest: earliest time modifier (e.g. '-24h', '-7d@d', '0' for all-time).
            latest: latest time modifier (e.g. 'now').
            count: max rows to return (0 = no limit).
        """
        data = await client.search_oneshot(query, earliest=earliest, latest=latest, count=count)
        if isinstance(data, dict):
            return dumps({"results": data.get("results", data), "fields": data.get("fields")})
        return dumps(data)

    @mcp.tool()
    async def splunk_search_job(
        query: str,
        earliest: str = "-24h",
        latest: str = "now",
    ) -> str:
        """Create an async search job (returns its sid). Use for long/large searches,
        then poll with splunk_search_job_status and fetch splunk_search_job_results."""
        from ..client import normalize_search
        body = {"search": normalize_search(query), "earliest_time": earliest,
                "latest_time": latest, "output_mode": "json"}
        data = await client.post("/services/search/jobs", data=body)
        sid = data.get("sid") if isinstance(data, dict) else None
        return dumps({"sid": sid, "raw": data})

    @mcp.tool()
    async def splunk_search_job_status(sid: str) -> str:
        """Get an async search job's dispatch state (QUEUED/PARSING/RUNNING/DONE),
        progress, event/result counts."""
        rows = client.unwrap_entries(await client.get(f"/services/search/jobs/{sid}"))
        c = rows[0] if rows else {}
        keep = {k: c.get(k) for k in (
            "dispatchState", "isDone", "doneProgress", "eventCount", "resultCount",
            "scanCount", "runDuration", "messages")}
        return dumps(keep)

    @mcp.tool()
    async def splunk_search_job_results(sid: str, count: int = 100, offset: int = 0) -> str:
        """Fetch results from a completed (or running) async search job."""
        return dumps(await client.get(
            f"/services/search/jobs/{sid}/results",
            params={"count": count, "offset": offset, "output_mode": "json"}))

    @mcp.tool()
    async def splunk_list_saved_searches(app: str | None = None) -> str:
        """List saved searches / reports / alerts (name, search, schedule, app)."""
        path = f"/servicesNS/-/{app}/saved/searches" if app else "/services/saved/searches"
        rows = client.unwrap_entries(await client.list_entries(path))
        slim = [{k: r.get(k) for k in ("name", "app", "search", "cron_schedule",
                "is_scheduled", "disabled", "actions")} for r in rows]
        return dumps(slim)

    @mcp.tool()
    async def splunk_create_saved_search(
        name: str,
        search: str,
        app: str = "search",
        cron_schedule: str | None = None,
        is_scheduled: bool = False,
    ) -> str:
        """Create a saved search (optionally scheduled). `search` is the SPL body."""
        body: dict = {"name": name, "search": search}
        if cron_schedule:
            body["cron_schedule"] = cron_schedule
        if is_scheduled:
            body["is_scheduled"] = 1
        path = f"/servicesNS/nobody/{app}/saved/searches"
        return dumps(await client.post(path, data=body))
