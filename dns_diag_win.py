#!/usr/bin/env python3
"""
dns_diag_win.py — Windows 11 DNS diagnostics for "why browser resolves but Python/nslookup fails".
No admin required. Uses only stdlib; optionally uses dnspython if available for direct DNS queries.
Tested with Python 3.11+ on Windows.

Usage:
    python dns_diag_win.py mastodon.social --nameservers 8.8.8.8 1.1.1.1
    python dns_diag_win.py example.com

What it checks:
1) OS resolver via socket.getaddrinfo() for A/AAAA.
2) IPv4 and IPv6 separately (to catch AAAA-timeout cases).
3) TCP connect to host:80/443 to reveal which address family succeeds.
4) Optional: dnspython direct queries (system default, 8.8.8.8, 1.1.1.1) if installed.
5) Optional: DNS-over-HTTPS (DoH) to Cloudflare and Google if httpx or requests are installed.
6) Prints concise verdicts + remediation tips.

Exit code is nonzero if all resolution/connect attempts fail.
"""
from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
from typing import Iterable, Optional

# Optional deps
try:
    import dns.resolver  # type: ignore
    HAVE_DNSPYTHON = True
    print("have dns python")
except Exception:
    HAVE_DNSPYTHON = False

# Optional HTTP client for DoH
HAVE_HTTPX = False
HAVE_REQUESTS = False
try:
    import httpx  # type: ignore
    HAVE_HTTPX = True
except Exception:
    try:
        import requests  # type: ignore
        HAVE_REQUESTS = True
    except Exception:
        pass


def pretty_exception(e: BaseException) -> str:
    root = e.__cause__ or e.__context__ or e
    return f"{type(root).__name__}: {root}"


def getaddrinfo_all(host: str, family: int = socket.AF_UNSPEC, port: int = 443) -> list[tuple]:
    # flags=AI_ADDRCONFIG helps avoid IPv6 on systems without IPv6 routes
    hints = {
        "family": family,
        "type": socket.SOCK_STREAM,
        "proto": 0,
        "flags": getattr(socket, "AI_ADDRCONFIG", 0),
    }
    return socket.getaddrinfo(host, port, **hints)


def resolve_os(host: str) -> dict:
    out: dict[str, list[str]] = {"AF_INET": [], "AF_INET6": []}
    errors: dict[str, str] = {}
    for fam_name, fam in (("AF_UNSPEC", socket.AF_UNSPEC), ("AF_INET", socket.AF_INET), ("AF_INET6", socket.AF_INET6)):
        try:
            infos = getaddrinfo_all(host, fam)
            addrs = []
            for fam_i, socktype, proto, canonname, sockaddr in infos:
                ip = sockaddr[0]
                addrs.append(ip)
                if fam_i == socket.AF_INET:
                    out["AF_INET"].append(ip)
                elif fam_i == socket.AF_INET6:
                    out["AF_INET6"].append(ip)
            print(f"[OS] getaddrinfo({host}, {fam_name}) -> {sorted(set(addrs)) or '[]'}")
        except Exception as e:
            errors[fam_name] = pretty_exception(e)
            print(f"[OS] getaddrinfo({host}, {fam_name}) ERROR: {errors[fam_name]}")
    return {"addresses": out, "errors": errors}


def tcp_connect(host: str, port: int, family: int, timeout: float = 5.0) -> tuple[bool, str]:
    af_name = "IPv4" if family == socket.AF_INET else "IPv6"
    try:
        # create_connection picks first resolved addr for us when family=AF_UNSPEC, but we want forced family
        infos = getaddrinfo_all(host, family=family, port=port)
        last_err = None
        for af, socktype, proto, canonname, sockaddr in infos:
            s = socket.socket(af, socktype, proto)
            s.settimeout(timeout)
            try:
                s.connect(sockaddr)
                peer = s.getpeername()
                s.close()
                return True, f"connected to {peer}"
            except Exception as e:
                last_err = e
                s.close()
                continue
        if last_err:
            return False, pretty_exception(last_err)
        return False, "no addresses"
    except Exception as e:
        return False, pretty_exception(e)


def tls_handshake(host: str, port: int, family: int, timeout: float = 7.0) -> tuple[bool, str]:
    try:
        infos = getaddrinfo_all(host, family=family, port=port)
        last_err = None
        for af, socktype, proto, canonname, sockaddr in infos:
            s = socket.socket(af, socktype, proto)
            s.settimeout(timeout)
            try:
                s.connect(sockaddr)
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(s, server_hostname=host) as tls_sock:
                    tls_sock.settimeout(timeout)
                    # A single read to confirm it didn't immediately die
                    try:
                        tls_sock.recv(1, socket.MSG_PEEK)
                    except Exception:
                        pass
                    peer = tls_sock.getpeername()
                    return True, f"TLS OK to {peer}"
            except Exception as e:
                last_err = e
            finally:
                try:
                    s.close()
                except Exception:
                    pass
        if last_err:
            return False, pretty_exception(last_err)
        return False, "no addresses"
    except Exception as e:
        return False, pretty_exception(e)


def resolve_with_dnspython(host: str, nameservers: Optional[Iterable[str]] = None) -> dict:
    if not HAVE_DNSPYTHON:
        return {"available": False, "note": "dnspython not installed"}
    res = dns.resolver.Resolver(configure=True)
    if nameservers:
        res.nameservers = list(nameservers)
    results = {}
    for rtype in ("A", "AAAA"):
        try:
            ans = res.resolve(host, rtype, lifetime=4.0)
            results[rtype] = sorted({rdata.address for rdata in ans})
            print(f"[dns.resolver {res.nameservers}] {host} {rtype} -> {results[rtype]}")
        except Exception as e:
            results[f"{rtype}_error"] = pretty_exception(e)
            print(f"[dns.resolver {res.nameservers}] {host} {rtype} ERROR: {results[f'{rtype}_error']}")
    return {"available": True, "nameservers": res.nameservers, "results": results}


def doh_query(host: str, provider: str) -> dict:
    """
    Simple DoH query using GET (JSON), provider in {'cloudflare','google'}.
    """
    if not (HAVE_HTTPX or HAVE_REQUESTS):
        return {"available": False, "note": "httpx/requests not installed"}

    def fetch(url: str, params: dict, headers: dict) -> tuple[bool, dict | str]:
        try:
            if HAVE_HTTPX:
                with httpx.Client(timeout=5.0) as client:
                    r = client.get(url, params=params, headers=headers)
                    r.raise_for_status()
                    return True, r.json()
            else:
                r = requests.get(url, params=params, headers=headers, timeout=5.0)
                r.raise_for_status()
                return True, r.json()
        except Exception as e:
            return False, pretty_exception(e)

    if provider == "cloudflare":
        url = "https://cloudflare-dns.com/dns-query"
    elif provider == "google":
        url = "https://dns.google/resolve"
    else:
        raise ValueError("unknown provider")

    params = {"name": host, "type": "A"}
    headers = {"accept": "application/dns-json"}
    ok_a, data_a = fetch(url, params, headers)

    params6 = {"name": host, "type": "AAAA"}
    ok_aaaa, data_aaaa = fetch(url, params6, headers)

    return {
        "available": True,
        "provider": provider,
        "A": data_a if ok_a else {"error": data_a},
        "AAAA": data_aaaa if ok_aaaa else {"error": data_aaaa},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host", help="Hostname to test (e.g., mastodon.social)")
    ap.add_argument("--nameservers", nargs="*", default=[], help="Optional list of DNS servers (e.g., 8.8.8.8 1.1.1.1) for dnspython tests")
    ap.add_argument("--no-doh", action="store_true", help="Skip DNS-over-HTTPS probes")
    args = ap.parse_args()

    host = args.host.strip()

    print(f"=== DNS Diagnostics for {host} ===")
    print(f"Python: {sys.version.split()[0]}  Platform: {sys.platform}")
    print()

    # 1) OS resolver
    os_res = resolve_os(host)
    print()

    # 2) Connectivity probes
    for fam, label in ((socket.AF_INET, "IPv4"), (socket.AF_INET6, "IPv6")):
        ok_tcp_443, msg_tcp_443 = tcp_connect(host, 443, fam)
        print(f"[TCP {label}] 443 -> {msg_tcp_443 if ok_tcp_443 else 'FAIL: ' + msg_tcp_443}")
        ok_tls_443, msg_tls_443 = tls_handshake(host, 443, fam)
        print(f"[TLS {label}] 443 -> {msg_tls_443 if ok_tls_443 else 'FAIL: ' + msg_tls_443}")
        ok_tcp_80, msg_tcp_80 = tcp_connect(host, 80, fam)
        print(f"[TCP {label}] 80  -> {msg_tcp_80 if ok_tcp_80 else 'FAIL: ' + msg_tcp_80}")
        print()

    # 3) dnspython with system + specific nameservers
    resolve_with_dnspython(host, None)
    if args.nameservers:
        for ns in args.nameservers:
            resolve_with_dnspython(host, [ns])
            # spacing
    print()

    # 4) DoH probes (compare with what browsers might use)
    if not args.no_doh:
        for prov in ("cloudflare", "google"):
            doh = doh_query(host, prov)
            if doh.get("available"):
                print(f"[DoH {prov}] A: {json.dumps(doh.get('A'), indent=2)[:400]}")
                print(f"[DoH {prov}] AAAA: {json.dumps(doh.get('AAAA'), indent=2)[:400]}")
            else:
                print(f"[DoH {prov}] skipped ({doh.get('note')})")
            print()

    # Verdict heuristic
    v4 = bool(os_res["addresses"]["AF_INET"])
    v6 = bool(os_res["addresses"]["AF_INET6"])
    exit_bad = 0

    if not v4 and not v6:
        print("VERDICT: OS resolver could not resolve the host at all. This points to DNS issues on your system/network.")
        exit_bad = 2
    elif v6 and not v4:
        print("VERDICT: Only IPv6 resolves. If connections fail above, you may have IPv6 routing/firewall issues.")
    elif v4 and not v6:
        print("VERDICT: Only IPv4 resolves. That's usually fine. If browser works but Python fails, check local firewall for Python.")
    else:
        print("VERDICT: Both IPv4 and IPv6 resolve via OS. If Python fetch still fails, investigate firewall/AV, SNI/TLS interception, or HTTP proxy settings.")

    return exit_bad


if __name__ == "__main__":
    raise SystemExit(main())
