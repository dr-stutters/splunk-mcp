"""Synthetic telemetry generator: fabricate realistic Cisco/ISE/ASA/Windows log
events and ship them into Splunk (HEC or UDP syslog) so the installed add-ons'
dashboards populate with demo/test data.

The event text is modelled on the real sourcetypes the lab's add-ons parse:
`cisco:ios` (IOS-XE syslog), `cisco:ise:syslog` (Splunk_TA_cisco-ise
CISE_* messages), `cisco:asa`, and `WinEventLog:Security`. Every synthetic host
is prefixed `sim-` so generated data is trivially identifiable and separable
from real telemetry (`host=sim-*`).

The generation core (`_generate`) is pure and seedable, so a given
(profile, count, seed, now) always yields byte-identical events - handy for
reproducible demos and unit tests.
"""

from __future__ import annotations

import asyncio
import random
import socket
import time as _time
from datetime import datetime, timezone
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from ..client import SplunkClient
from . import dumps

# --------------------------------------------------------------------------
# data pools (module constants) - all hosts prefixed sim-
# --------------------------------------------------------------------------
_SIM_SWITCHES = [f"sim-sw{n:02d}" for n in range(1, 6)]
_SIM_ISE = ["sim-ise01", "sim-ise02"]
_SIM_ASA = ["sim-asa01", "sim-asa02"]
_SIM_WIN = ["sim-win-dc01", "sim-win-fs01", "sim-win-app01"]
_SIM_USERS = ["alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi"]
_SIM_IFACES = ["GigabitEthernet1/0/1", "GigabitEthernet1/0/2", "GigabitEthernet1/0/12",
               "TenGigabitEthernet1/1/1", "GigabitEthernet0/0", "Vlan100"]
_SIM_NADS = ["sim-sw01", "sim-sw02", "sim-c9800", "sim-asa01"]
_SIM_POLICY_SETS = ["Wired_MAB", "Wired_802.1X", "Wireless_802.1X", "Default"]
_SIM_AUTHZ_RULES = ["Employee_Full", "Contractor_Limited", "IoT_Restricted",
                    "BYOD_Provision", "PermitAccess"]
_SIM_EAP = ["EAP-TLS", "PEAP-MSCHAPv2", "EAP-FAST", "Lookup (MAB)"]
_SIM_FAIL_REASONS = [
    "22056 Subject not found in the applicable identity store(s)",
    "24408 User authentication against Active Directory failed",
    "11036 The Message-Authenticator RADIUS attribute is invalid",
    "15039 Rejected per authorization profile",
    "22040 Wrong password or invalid shared secret",
]


def _mac(rng: random.Random) -> str:
    return ":".join(f"{rng.randint(0, 255):02X}" for _ in range(6))


def _ip(rng: random.Random, net: str = "10.10") -> str:
    return f"{net}.{rng.randint(0, 254)}.{rng.randint(1, 254)}"


def _syslog_ts(dt: datetime) -> str:
    """'Jul 13 22:41:07' - classic BSD syslog timestamp (no year)."""
    return f"{dt.strftime('%b')} {dt.day:2d} {dt.strftime('%H:%M:%S')}"


def _iso_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# per-profile generators: (rng, dt) -> (host, event_text)
# --------------------------------------------------------------------------
def _gen_ios(rng: random.Random, dt: datetime) -> tuple[str, str]:
    host = rng.choice(_SIM_SWITCHES)
    seq = rng.randint(100000, 999999)
    ts = _syslog_ts(dt)
    iface = rng.choice(_SIM_IFACES)
    user = rng.choice(_SIM_USERS)
    ip = _ip(rng, "198.18.128")
    kind = rng.choices(
        ["lineproto_up", "lineproto_down", "link_down", "config", "login_ok",
         "login_fail", "dot1x_ok", "dot1x_fail", "authmgr"],
        weights=[16, 8, 6, 14, 12, 6, 16, 6, 10])[0]
    body = {
        "lineproto_up": f"%LINEPROTO-5-UPDOWN: Line protocol on Interface {iface}, "
                        "changed state to up",
        "lineproto_down": f"%LINEPROTO-5-UPDOWN: Line protocol on Interface {iface}, "
                          "changed state to down",
        "link_down": f"%LINK-3-UPDOWN: Interface {iface}, changed state to down",
        "config": f"%SYS-5-CONFIG_I: Configured from console by {user} on vty0 ({ip})",
        "login_ok": f"%SEC_LOGIN-5-LOGIN_SUCCESS: Login Success [user: {user}] "
                    f"[Source: {ip}] [localport: 22] at {ts}",
        "login_fail": f"%SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: {user}] "
                      f"[Source: {ip}] [localport: 22] [Reason: Login Authentication Failed]",
        "dot1x_ok": f"%DOT1X-5-SUCCESS: Authentication successful for client "
                    f"({_mac(rng)}) on Interface {iface} AuditSessionID {rng.getrandbits(64):016X}",
        "dot1x_fail": f"%DOT1X-5-FAIL: Authentication failed for client ({_mac(rng)}) "
                      f"on Interface {iface}",
        "authmgr": f"%AUTHMGR-5-START: Starting 'dot1x' for client ({_mac(rng)}) "
                   f"on Interface {iface}",
    }[kind]
    # Syslog-server form: "<pri>Mon DD HH:MM:SS host: seq: *timestamp: %FACILITY-..."
    return host, f"{ts} {host}: {seq}: *{ts}.{rng.randint(0,999):03d}: {body}"


def _ise_header(rng: random.Random, dt: datetime, host: str, cat: str, msgid: int,
                sev: str) -> str:
    seq = rng.randint(1000000000, 9999999999)
    return (f"<181>{_syslog_ts(dt)} {host} {cat} {seq:010d} 1 0 "
            f"{_iso_ts(dt)} +00:00 {seq} {msgid} {sev} {cat}:")


def _gen_ise_auth(rng: random.Random, dt: datetime) -> tuple[str, str]:
    host = rng.choice(_SIM_ISE)
    user = rng.choice(_SIM_USERS)
    mac = _mac(rng)
    nad = rng.choice(_SIM_NADS)
    passed = rng.random() > 0.2
    common = (f"NetworkDeviceName={nad}, User-Name={user}, UserName={user}, "
              f"Calling-Station-ID={mac}, EndPointMACAddress={mac}, "
              f"NAS-IP-Address={_ip(rng, '198.18.128')}, NAS-Port-Id={rng.choice(_SIM_IFACES)}, "
              f"EapAuthentication={rng.choice(_SIM_EAP)}, "
              f"ISEPolicySetName={rng.choice(_SIM_POLICY_SETS)}, "
              f"IdentityGroup=Endpoint Identity Groups:{rng.choice(['Employees','BYOD','IoT'])}")
    if passed:
        hdr = _ise_header(rng, dt, host, "CISE_Passed_Authentications", 5200, "NOTICE")
        body = (f" Passed-Authentication: Authentication succeeded, {common}, "
                f"AuthenticationMethod={rng.choice(['MSCHAPV2','x509_PKI','Lookup'])}, "
                f"SelectedAuthorizationProfiles={rng.choice(_SIM_AUTHZ_RULES)}, "
                f"AuthorizationPolicyMatchedRule={rng.choice(_SIM_AUTHZ_RULES)}, "
                f"Response={{RadiusPacketType=Accept}}")
    else:
        hdr = _ise_header(rng, dt, host, "CISE_Failed_Attempts", 5400, "NOTICE")
        body = (f" Failed-Attempt: Authentication failed, {common}, "
                f"FailureReason={rng.choice(_SIM_FAIL_REASONS)}, "
                f"FailedAttempts={rng.randint(1, 5)}, "
                f"Response={{RadiusPacketType=Reject}}")
    return host, hdr + body


def _gen_ise_acct(rng: random.Random, dt: datetime) -> tuple[str, str]:
    host = rng.choice(_SIM_ISE)
    user = rng.choice(_SIM_USERS)
    mac = _mac(rng)
    status = rng.choices(["Start", "Interim-Update", "Stop"], weights=[3, 5, 3])[0]
    hdr = _ise_header(rng, dt, host, "CISE_RADIUS_Accounting", 3000, "NOTICE")
    fields = (f" RADIUS-Accounting: RADIUS Accounting watchdog update, "
              f"NetworkDeviceName={rng.choice(_SIM_NADS)}, User-Name={user}, UserName={user}, "
              f"Calling-Station-ID={mac}, Acct-Status-Type={status}, "
              f"Acct-Session-Id={rng.getrandbits(32):08X}, "
              f"Framed-IP-Address={_ip(rng)}, "
              f"Acct-Input-Octets={rng.randint(1000, 9000000)}, "
              f"Acct-Output-Octets={rng.randint(1000, 9000000)}, "
              f"Acct-Session-Time={rng.randint(1, 86400)}")
    return host, hdr + fields


def _gen_asa(rng: random.Random, dt: datetime) -> tuple[str, str]:
    host = rng.choice(_SIM_ASA)
    ts = _syslog_ts(dt)
    src, dst = _ip(rng, "10.20"), _ip(rng, "203.0")
    sport, dport = rng.randint(1024, 65535), rng.choice([80, 443, 22, 53, 3389, 8080])
    kind = rng.choices(["built", "teardown", "deny", "vpn"], weights=[10, 10, 6, 3])[0]
    conn = rng.randint(1000, 9999999)
    body = {
        "built": f"%ASA-6-302013: Built outbound TCP connection {conn} for "
                 f"outside:{dst}/{dport} ({dst}/{dport}) to inside:{src}/{sport} ({src}/{sport})",
        "teardown": f"%ASA-6-302014: Teardown TCP connection {conn} for outside:{dst}/{dport} "
                    f"to inside:{src}/{sport} duration 0:0{rng.randint(1,9)}:0{rng.randint(1,9)} "
                    f"bytes {rng.randint(100, 900000)} TCP FINs",
        "deny": f"%ASA-4-106023: Deny tcp src outside:{dst}/{sport} dst inside:{src}/{dport} "
                'by access-group "outside_access_in"',
        "vpn": f"%ASA-6-113019: Group = VPN-USERS, Username = {rng.choice(_SIM_USERS)}, "
               f"IP = {dst}, Session disconnected. Session Type: AnyConnect, "
               f"Duration: 0h:{rng.randint(1,59):02d}m:{rng.randint(1,59):02d}s, "
               f"Bytes xmt: {rng.randint(1000,900000)}, Bytes rcv: {rng.randint(1000,900000)}, "
               "Reason: User Requested",
    }[kind]
    return host, f"{ts} {host} : {body}"


def _gen_windows(rng: random.Random, dt: datetime) -> tuple[str, str]:
    host = rng.choice(_SIM_WIN)
    user = rng.choice(_SIM_USERS)
    ok = rng.random() > 0.25
    code = "4624" if ok else "4625"
    logon_type = rng.choice([2, 3, 10])
    ts = dt.strftime("%m/%d/%Y %I:%M:%S %p")
    lines = [
        f"{ts}",
        "LogName=Security",
        f"EventCode={code}",
        f"EventType={0 if ok else 0}",
        f"ComputerName={host}.mitchcloud.lab",
        "SourceName=Microsoft Windows security auditing.",
        "Type=Information",
        "TaskCategory=Logon",
        f"Keywords=Audit {'Success' if ok else 'Failure'}",
        f"Message={'An account was successfully logged on.' if ok else 'An account failed to log on.'}",
        "",
        "Subject:",
        f"\tSecurity ID:\t\tS-1-5-21-{rng.randint(1000000000,9999999999)}-{rng.randint(1000,9999)}",
        f"\tAccount Name:\t\t{host}$",
        "\tAccount Domain:\t\tMITCHCLOUD",
        "",
        "Logon Type:\t\t" + str(logon_type),
        "",
        "New Logon:" if ok else "Account For Which Logon Failed:",
        f"\tSecurity ID:\t\tS-1-5-21-{rng.randint(1000000000,9999999999)}-{rng.randint(1000,9999)}",
        f"\tAccount Name:\t\t{user}",
        "\tAccount Domain:\t\tMITCHCLOUD",
        "",
        "Network Information:",
        f"\tWorkstation Name:\t{rng.choice(_SIM_WIN)}",
        f"\tSource Network Address:\t{_ip(rng, '198.18.130')}",
        f"\tSource Port:\t\t{rng.randint(1024, 65535)}",
    ]
    if not ok:
        lines += ["", "Failure Information:", "\tFailure Reason:\t\tUnknown user name or bad password.",
                  "\tStatus:\t\t\t0xC000006D", "\tSub Status:\t\t0xC000006A"]
    return host, "\n".join(lines)


_PROFILES: dict[str, dict[str, Any]] = {
    "ios": {"sourcetype": "cisco:ios", "index": "cisco", "udp_port": 5514, "gen": _gen_ios,
            "desc": "IOS-XE switch/router syslog (link, config, login, dot1x)"},
    "ise_auth": {"sourcetype": "cisco:ise:syslog", "index": "ise", "udp_port": 5515,
                 "gen": _gen_ise_auth,
                 "desc": "ISE RADIUS auth (CISE_Passed_Authentications / Failed_Attempts, ~80/20)"},
    "ise_acct": {"sourcetype": "cisco:ise:syslog", "index": "ise", "udp_port": 5515,
                 "gen": _gen_ise_acct, "desc": "ISE RADIUS accounting (CISE_RADIUS_Accounting)"},
    "asa": {"sourcetype": "cisco:asa", "index": "cisco", "udp_port": None, "gen": _gen_asa,
            "desc": "ASA firewall (built/teardown/deny/VPN) - HEC only (no ASA UDP input)"},
    "windows": {"sourcetype": "WinEventLog:Security", "index": "windows", "udp_port": None,
                "gen": _gen_windows,
                "desc": "Windows Security log (4624/4625) - HEC only (no Windows UDP input)"},
}

_HEC_BATCH = 500


def _generate(profile: str, count: int, span_minutes: int, seed: int | None,
              now: float | None = None) -> list[tuple[float, str, str]]:
    """Pure: return [(epoch_ts, host, event_text)] spread oldest->newest over the span.

    Deterministic for a given (profile, count, span_minutes, seed, now).
    """
    if profile not in _PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose from {sorted(_PROFILES)}")
    if count < 1:
        raise ValueError("count must be >= 1")
    gen: Callable[[random.Random, datetime], tuple[str, str]] = _PROFILES[profile]["gen"]
    rng = random.Random(seed)
    end = now if now is not None else _time.time()
    start = end - span_minutes * 60
    step = (end - start) / count if count else 0
    out: list[tuple[float, str, str]] = []
    for i in range(count):
        ts = start + step * i
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        host, text = gen(rng, dt)
        out.append((ts, host, text))
    return out


def register(mcp: FastMCP, client: SplunkClient) -> None:
    @mcp.tool()
    async def splunk_list_telemetry_profiles() -> str:
        """List synthetic-telemetry profiles (sourcetype, target index, UDP port, sample line).

        Each profile fabricates realistic events for one source type; use
        splunk_generate_telemetry to send them. All synthetic hosts are prefixed
        `sim-` so the data is identifiable (search host=sim-*).
        """
        rows = []
        for name, p in _PROFILES.items():
            sample = _generate(name, 1, 1, seed=0)[0][2].split("\n")[0][:160]
            rows.append({"profile": name, "sourcetype": p["sourcetype"], "index": p["index"],
                         "udp_port": p["udp_port"], "description": p["desc"], "sample": sample})
        return dumps(rows)

    @mcp.tool()
    async def splunk_generate_telemetry(
        profile: str,
        count: int = 100,
        span_minutes: int = 60,
        transport: str = "hec",
        index: str | None = None,
        sourcetype: str | None = None,
        host: str | None = None,
        token: str | None = None,
        udp_port: int | None = None,
        seed: int | None = None,
    ) -> str:
        """Generate `count` synthetic events for `profile` and ship them to Splunk.

        Fills dashboards/add-ons with realistic demo data. Events are backfilled
        with timestamps spread evenly over the last `span_minutes`. All hosts are
        `sim-*` (override with `host`). Set `seed` for reproducible output.

        Profiles: ios, ise_auth, ise_acct, asa, windows (see
        splunk_list_telemetry_profiles). Transport:
        - "hec" (default): structured send to HEC :8088 with per-event time/host/
          index/sourcetype. Needs a HEC token (SPLUNK_HEC_TOKEN or `token=`).
        - "udp": raw syslog packets to a UDP data input (ios->5514, ise_*->5515).
          Only profiles with a UDP input support this; the input's connection_host
          setting decides the host (event text only). asa/windows are HEC-only.
        """
        if profile not in _PROFILES:
            raise ValueError(f"unknown profile {profile!r}; choose from {sorted(_PROFILES)}")
        p = _PROFILES[profile]
        idx = index or p["index"]
        st = sourcetype or p["sourcetype"]
        events = _generate(profile, count, span_minutes, seed)
        if host:
            events = [(ts, host, text) for ts, _h, text in events]
        span = {"earliest": datetime.fromtimestamp(events[0][0], tz=timezone.utc).isoformat(),
                "latest": datetime.fromtimestamp(events[-1][0], tz=timezone.utc).isoformat()}
        hosts_used = sorted({h for _t, h, _x in events})

        if transport == "hec":
            sent = 0
            acks = []
            for start in range(0, len(events), _HEC_BATCH):
                batch = events[start:start + _HEC_BATCH]
                envelopes = [{"event": text, "time": round(ts, 3), "host": h,
                              "index": idx, "sourcetype": st, "source": f"telemetry:{profile}"}
                             for ts, h, text in batch]
                acks.append(await client.hec_send(envelopes, token=token))
                sent += len(envelopes)
            return dumps({"profile": profile, "transport": "hec", "sent": sent,
                          "index": idx, "sourcetype": st, "hosts": hosts_used,
                          "time_range": span, "hec_ack": acks[-1] if acks else None})

        if transport == "udp":
            port = udp_port or p["udp_port"]
            if port is None:
                raise ValueError(
                    f"profile {profile!r} has no UDP input (index {p['index']}); "
                    "use transport='hec' or pass udp_port=")
            # Derive the Splunk host from the mgmt base_url.
            target = client.base_url.split("://", 1)[-1].split(":")[0].split("/")[0]
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sent = 0
            try:
                for i, (_ts, _h, text) in enumerate(events):
                    # UDP syslog is single-line; collapse any newlines defensively.
                    sock.sendto(text.replace("\n", " ").encode("utf-8", "replace"), (target, port))
                    sent += 1
                    if i % 50 == 49:
                        await asyncio.sleep(0)
            finally:
                sock.close()
            return dumps({"profile": profile, "transport": "udp", "sent": sent,
                          "udp_target": f"{target}:{port}", "sourcetype_of_input": st,
                          "hosts": hosts_used, "time_range": span,
                          "note": "UDP host is set by the input's connection_host; event text only"})

        raise ValueError("transport must be 'hec' or 'udp'")
