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

## Manifest — add-ons that match our lab sources

| Add-on (Splunkbase) | Source | Sourcetype | Index | Status |
|---|---|---|---|---|
| Splunk Add-on for Cisco IOS | CML switches/routers (IOS/IOS-XE) | `cisco:ios` | `cisco` | live `cisco:ios` data flowing; add-on not yet installed |
| Splunk Add-on for Cisco Identity Services Engine (ISE) | Cisco ISE (NAC) | `cisco:ise` | `ise` | pending |
| Cisco Secure Firewall App/Add-on for Splunk | FTD / ASA | `cisco:ftd` / `cisco:asa` | `cisco` | pending |
| Splunk Add-on for Microsoft Windows | Windows Server | `WinEventLog:*` | `windows` | pending |

_(Skip "Cisco Security Cloud Control" — it targets Cisco's cloud SCC/CDO telemetry,
which this lab doesn't emit.)_

Record the exact version/build of each package you drop here in the Status column
when you add it, so the install is reproducible.
