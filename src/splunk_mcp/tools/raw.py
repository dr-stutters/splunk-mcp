"""Generic escape hatch + REST endpoint discovery for the Splunk management API."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from ..client import SplunkAPIError, SplunkClient
from . import dumps


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_rest_call(
        method: Literal["GET", "POST", "PUT", "DELETE"],
        path: str,
        query_params: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
        raw_text: bool = False,
    ) -> str:
        """Call any Splunk management endpoint (port 8089) not covered by a tool.

        The management API takes *form-encoded* parameters (pass them as
        `form_body`, not JSON) and returns Atom XML; this adds output_mode=json and
        returns parsed JSON unless raw_text=True (e.g. to fetch a dashboard's XML).
        Use splunk_list_endpoints to discover paths.

        Example: method='POST', path='/services/data/indexes',
        form_body={'name': 'cisco', 'maxTotalDataSizeMB': 5000}.
        """
        return dumps(await client.request(
            method, path, params=query_params, data=form_body, raw_text=raw_text))

    @mcp.tool()
    async def splunk_list_endpoints(path: str = "/services/data") -> str:
        """List the REST endpoints available under a path (the Atom service catalog).

        Discovery aid for splunk_rest_call. The bare '/services' root is not listable
        on Splunk; drill into a namespace instead, e.g. '/services/data',
        '/services/data/inputs', '/services/server', '/services/authentication'.
        """
        try:
            rows = client.unwrap_entries(await client.get(path))
            names = sorted(r.get("name", "") for r in rows if r.get("name"))
            if names:
                return dumps(names)
        except SplunkAPIError as e:
            if e.status_code != 404:
                raise
        # Fall back to the common top-level namespaces (the root is not listable).
        return dumps({
            "note": f"{path!r} is not a listable catalog; drill into one of these:",
            "namespaces": [
                "/services/data", "/services/data/indexes", "/services/data/inputs",
                "/services/server", "/services/search/jobs", "/services/saved/searches",
                "/services/apps/local", "/services/authentication/users",
                "/services/authorization/roles", "/services/licenser",
                "/services/storage/collections", "/services/messages",
            ],
        })
