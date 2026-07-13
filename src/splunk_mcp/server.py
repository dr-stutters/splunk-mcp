"""Splunk Enterprise MCP server entry point."""

from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

from .client import SplunkClient
from .config import load_settings
from .tools import register_all


def build_server() -> FastMCP:
    settings = load_settings()
    client = SplunkClient(settings)
    mcp = FastMCP(
        "splunk",
        instructions=(
            "Tools for Splunk Enterprise over its REST API (management port 8089, "
            "HTTP Basic auth) plus the HTTP Event Collector (port 8088, token auth). "
            "Start with splunk_server_info / splunk_health to confirm the box is up. "
            "Core workflows: run SPL with splunk_search (one-shot) or splunk_search_job "
            "(async, for big/slow searches); manage indexes (splunk_list_indexes / "
            "splunk_create_index); wire up ingest with data inputs (splunk_list_inputs / "
            "splunk_create_tcp_input / splunk_create_udp_input for syslog) and HEC "
            "(splunk_list_hec_tokens / splunk_create_hec_token / splunk_send_hec_event); "
            "install and enable add-ons/apps (splunk_list_apps / splunk_install_app) and "
            "dashboards (splunk_list_dashboards / splunk_create_dashboard). Use "
            "splunk_rest_call for any endpoint without a dedicated tool - the management "
            "API takes form-encoded params and returns Atom entries (unwrapped to JSON "
            "here). This server pairs with the CML/ISE/FMC/Windows MCPs: point the lab "
            "devices' syslog/HEC at this Splunk to centralize telemetry."
        ),
    )
    register_all(mcp, client)
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Splunk Enterprise MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    args = parser.parse_args()
    build_server().run(transport=args.transport)


if __name__ == "__main__":
    main()
