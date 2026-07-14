# Example prompts — Splunk MCP

Copy any prompt below to an AI agent (Claude Code, Claude Desktop, …) with the
**`splunk`** MCP server connected. Describe the outcome — the agent picks the
tools. Names in `code` show which tools each prompt exercises.

**Always start with:** *"Check Splunk — is the management API and HEC reachable?"*
→ `splunk_check` (probes 8089 and 8088).

## One end-to-end scenario

> **"Set up ingest for a Cisco ISE lab: create an `ise` index, add a UDP 5515 syslog
> input feeding it (sourcetype `cisco:ise:syslog`), enable HEC and mint a token for it,
> then generate 300 realistic ISE auth events over the last 2 hours and show me the
> pass/fail split with a search."**

Exercises: `splunk_create_index` → `splunk_create_udp_input` → `splunk_enable_hec` +
`splunk_create_hec_token` → `splunk_generate_telemetry(profile="ise_auth", …)` →
`splunk_search` (`index=ise | stats count by action`).

## Focused tasks (one area each)

**Indexes**
> "Create a `network` index with a 90-day retention and show me its current size."
> *(`splunk_create_index` / `splunk_get_index`)*

**Syslog ingest**
> "Add a UDP 514 syslog input on sourcetype `cisco:ios` feeding the `cisco` index."
> *(`splunk_create_udp_input`)*

**HEC**
> "Enable HEC, mint a token called `lab-telemetry` for the `main` index, and send a
> test event through it."  *(`splunk_enable_hec` / `splunk_create_hec_token` /
> `splunk_send_hec_event`)*

**Search (SPL)**
> "Over the last 24 h, which source IPs had the most failed ISE authentications?"
> *(`splunk_search`, or `splunk_search_job` for big/slow searches)*

**Synthetic telemetry (demo data)**
> "List the telemetry profiles, then generate 500 IOS + 500 firewall events so the
> dashboards populate."  *(`splunk_list_telemetry_profiles` / `splunk_generate_telemetry`)*

**Apps / dashboards**
> "Install this Cisco ISE add-on tarball at /tmp/addon.tgz, enable it, and list its
> dashboards."  *(`splunk_install_app` / `splunk_enable_app` / `splunk_list_dashboards`)*

## Tips

- **`splunk_check` first** — HEC (8088) and the mgmt API (8089) are separate ports/auth.
- **Synthetic events are backfilled** across the last `span_minutes`, so time-range
  panels light up immediately; every host is prefixed `sim-`.
- **Scope searches with `index=<name>`** — the `cisco`/`ise`/`windows` indexes usually
  aren't in a role's default search set, so a bare search finds nothing.
- **Prefer Splunkbase add-ons + their prebuilt dashboards** (Cisco Security Cloud,
  Cisco ISE, Microsoft Windows) over hand-built panels.
- `splunk_rest_call` reaches any endpoint without a dedicated tool.
