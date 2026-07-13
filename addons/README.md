# Splunk add-ons (drop zone)

Drop Splunkbase add-on packages (`.tgz` / `.spl`) here. The splunk-engineer agent
(or the `splunk_install_app` tool) installs them onto the lab Splunk box from this
folder, then wires the matching sourcetype/index and enables the add-on's
dashboards.

> **The packages themselves are gitignored — local only.** Splunkbase add-ons are
> licensed by Splunk/Cisco and their terms restrict redistribution, so we don't
> commit the binaries to GitHub. This mirrors the
> [Cisco Validated Designs](https://github.com/dr-stutters/cml-mcp) convention
> (source PDFs gitignored, the distilled briefs committed): here the **packages are
> local, this manifest is committed**. Download each from Splunkbase yourself.

## Install workflow

1. Download the add-on `.tgz` from [splunkbase.splunk.com](https://splunkbase.splunk.com)
   (requires a splunk.com login) and drop it in this folder.
2. splunk-engineer copies it to the Splunk host and installs it:
   `scp addons/<pkg>.tgz cisco@198.18.128.51:/tmp/` →
   `splunk_install_app('/tmp/<pkg>.tgz')` → `splunk_enable_app(<name>)` →
   restart Splunk if prompted (`sudo systemctl restart Splunkd`).
3. Point the source's data input at the add-on's expected **sourcetype** (the port
   is just transport; the sourcetype drives the add-on's field extraction), then
   verify parsing: `splunk_search('index=<idx> sourcetype=<st> | head', ...)` and
   open the add-on's dashboards.

## Manifest — dropped packages + install status (as of 2026-07-13)

| Package (app id) | Ver | Role | Status |
|---|---|---|---|
| **Cisco Catalyst Add-on** (`TA_cisco_catalyst`) | 3.2.37 | Collects ISE/DNAC/SD-WAN via **OpenAPI Basic-auth** (or pxGrid) | ✅ **installed + working** — ISE account `ise35` (`https://198.18.134.35`, admin Basic-auth) validated; 4 inputs (SGTs, policy sets, authz profiles, nodes) → **`index=ise`, 28 events** (`cisco:ise:custom:*`). No ISE GUI/cert needed. |
| **Cisco Enterprise Networking app** (`cisco-catalyst-app`) | 3.2.0 | Dashboards for the Catalyst Add-on data | ✅ installed — renders the ISE data (`cisco_ise_dashboard`) |
| **Splunk Add-on for Cisco ISE** (`Splunk_TA_cisco-ise`) | 5.0.0 | Parses ISE **syslog** (`cisco:ise:syslog`) — live auth stream | ✅ **working** — ISE Remote Logging Target (`198.18.128.51:5515`, LOCAL6) + Passed Auth / Failed / RADIUS Accounting categories mapped (ISE GUI). Live MAB re-auth confirmed in `index=ise`: `CISE_Passed_Authentications` + `CISE_RADIUS_Accounting`, add-on parsing (e.g. `AuthenticationMethod=Lookup`) |
| Cisco Secure Firewall (`ciscosecurefirewall`) | — | FTD/ASA dashboards (+ companion TA) | ⏸ deferred — SD-WAN firewall lab is stopped |
| Cisco Security Cloud (`CiscoSecurityCloud`) | 3.6.7 | Umbrella; its own props target Secure Client **NVM**/**Endpoint** (`cisco:nvm:*`,`cisco:evm:*`) | ⏸ deferred — lab doesn't emit NVM/endpoint telemetry |
| Cisco Catalyst Enhanced NetFlow (`splunk_app_stream_ipfix_cisco_hsl`) | 2.1.0 | NetFlow/IPFIX element mapping | ⏸ N/A — no NetFlow source |
| ~~App for Cisco Network Data~~ (`cisco_ios`) | 2.8.0 | IOS syslog dashboards | ❌ removed — unmaintained (since 2024) + needs the equally-dated TA-cisco_ios for base extraction |

**Two ISE→Splunk paths (complementary):** the **Catalyst Add-on** pulls ISE
config/inventory over the OpenAPI (working now, no GUI); the **ISE syslog add-on**
captures the live RADIUS auth stream (needs the ISE GUI remote-logging step). The
lone cat9000v syslog (`cisco:ios`) has no maintained Cisco app, so it uses the
custom **Cisco Syslog Overview** dashboard built via the Splunk MCP.

Record the exact version/build of each package you drop here in the Status column
when you add it, so the install is reproducible.
