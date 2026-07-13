# splunk-mcp

An MCP server for **Splunk Enterprise**, exposing its REST management API
(port `8089`, HTTP Basic auth) and the **HTTP Event Collector** (HEC, port `8088`,
token auth) as tools. Built with FastMCP + async httpx.

It's a companion to [cml-mcp](https://github.com/dr-stutters/cml-mcp) (and the
[Firepower](https://github.com/dr-stutters/firepower-mcp),
[ISE](https://github.com/dr-stutters/ise-mcp), and
[Windows](https://github.com/dr-stutters/windows-mcp) MCPs): Splunk is the
observability/SIEM sink that the Cisco/Windows lab stacks forward telemetry to.
Usable standalone against any Splunk box.

## What it does

Splunk's management API takes **form-encoded** parameters and returns Atom
`entry[]` documents; this server adds `output_mode=json`, unwraps the entries to
plain JSON, and wraps the common workflows as typed tools (45 of them):

| Area | Tools |
|---|---|
| **System** | `splunk_check`, `splunk_server_info`, `splunk_server_settings`, `splunk_health`, `splunk_messages`, `splunk_licensing` |
| **Search** | `splunk_search` (one-shot SPL), `splunk_search_job` / `_status` / `_results` (async), `splunk_list_saved_searches`, `splunk_create_saved_search` |
| **Indexes** | `splunk_list_indexes`, `splunk_get_index`, `splunk_create_index`, `splunk_delete_index` |
| **Ingest - inputs** | `splunk_list_inputs`, `splunk_create_udp_input` / `_tcp_input` (syslog), `splunk_create_monitor_input`, `splunk_delete_input` |
| **Ingest - HEC** | `splunk_hec_settings`, `splunk_enable_hec`, `splunk_list_hec_tokens`, `splunk_create_hec_token`, `splunk_delete_hec_token`, `splunk_send_hec_event` |
| **Apps / add-ons** | `splunk_list_apps`, `splunk_get_app`, `splunk_install_app`, `splunk_enable_app`, `splunk_disable_app`, `splunk_delete_app` |
| **Dashboards** | `splunk_list_dashboards`, `splunk_get_dashboard`, `splunk_create_dashboard`, `splunk_delete_dashboard` |
| **KV Store** | `splunk_list_kvstore_collections`, `splunk_kvstore_records` |
| **Access control** | `splunk_list_users`, `splunk_list_roles`, `splunk_create_user`, `splunk_delete_user` |
| **Escape hatch** | `splunk_rest_call` (any endpoint; pass `form_body`), `splunk_list_endpoints` |

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/dr-stutters/splunk-mcp
cd splunk-mcp
uv sync
```

## Configure

Copy `.env.example` to `.env` and fill in your Splunk box:

```ini
SPLUNK_URL=https://192.0.2.51:8089      # mgmt/REST API; :8089 assumed if omitted
SPLUNK_USERNAME=admin
SPLUNK_PASSWORD=changeme
SPLUNK_VERIFY_SSL=false                 # labs use self-signed certs
# HEC (optional) - derived from SPLUNK_URL host with :8088 unless set:
# SPLUNK_HEC_URL=https://192.0.2.51:8088
# SPLUNK_HEC_TOKEN=00000000-0000-0000-0000-000000000000
```

## How to use this

Run standalone (stdio): `uv run splunk-mcp` — or register it in any MCP client:

```json
{ "mcpServers": { "splunk": { "command": "uv",
    "args": ["run", "--directory", "/path/to/splunk-mcp", "splunk-mcp"] } } }
```

It's built to be driven by an AI agent. In the
[cml-mcp](https://github.com/dr-stutters/cml-mcp) lab suite it's wired in as the
`splunk` server, owned by the **splunk-engineer** agent (tool prefix
`mcp__splunk__*`) — it owns the receiving side (indexes, inputs, HEC, add-ons,
verification searches) while the device agents configure log forwarding.
Standalone, just describe what you want:

> "Create a 'network' index and a UDP 514 syslog input feeding it."

> "Enable HEC, mint a token for the firewall lab, and send a test event."

> "Install this Cisco ISE add-on tarball and show me its dashboards."

Call **`splunk_check`** first — it probes both the management API (8089) and
HEC (8088) and reports what's reachable.

## Notes

- **HEC uses `Authorization: Splunk <token>`** on `:8088` - the client bypasses its
  Basic-auth for HEC calls so the header isn't clobbered. Enable HEC once
  (`splunk_enable_hec`), create a token, then send/verify.
- **Discovery:** the bare `/services` root isn't listable (404) - drill into a
  namespace (`/services/data`, `/services/server`, ...) with `splunk_list_endpoints`.
- **Prefer Splunkbase add-ons + their dashboards** (Cisco Security Cloud, Cisco ISE,
  Microsoft Windows) over hand-built panels: download the `.tgz`, place it on the
  Splunk host, `splunk_install_app('/path/to/addon.tgz')`, then enable it.

## Test

```bash
uv run pytest                         # unit tests - no Splunk needed (run in CI)
uv run python tests/smoke_test.py     # live pass against the box in .env
```

The unit tests mock the HTTP layer (form-encoded POSTs, Atom-entry unwrapping,
the HEC `Authorization: Splunk` header). The smoke test runs a live read-mostly
pass (server info, health, indexes, apps, a one-shot search, endpoint discovery,
and an index create→delete round-trip).

## Security notes

`.env` is gitignored — never commit credentials or HEC tokens. Use a
least-privilege role for routine search/ingest work. TLS verification is off by
default for lab self-signed certs; set `SPLUNK_VERIFY_SSL=true` against a
trusted CA.
