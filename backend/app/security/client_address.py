"""The caller's address, for the per-address login limit.

X-Forwarded-For is a header the caller can write. It is believed only when the connection comes from
a proxy listed in TRUSTED_PROXIES (empty by default, so by default the real peer address is used).
Behind a trusted proxy the right-most entry that is not itself a trusted proxy is the caller: each
proxy appends the address it saw, so anything the caller put at the front is never reached.
Run uvicorn with --no-proxy-headers so this is the only place that decision is made.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_trusted(value: str) -> tuple[Network, ...]:
    """'127.0.0.1, ::1, 10.0.0.0/8' -> networks. A bad entry is an error, not silently ignored."""
    return tuple(
        ipaddress.ip_network(part.strip(), strict=False)
        for part in value.split(",")
        if part.strip()
    )  # noqa: E501


def _ip(text: str):
    try:
        return ipaddress.ip_address(text.strip())
    except ValueError:
        return None


def _trusted(address, networks: tuple[Network, ...]) -> bool:
    return address is not None and any(address in network for network in networks)


def client_address(request: Request, trusted: tuple[Network, ...]) -> str:
    peer = request.client.host if request.client else None
    if peer is None:
        return "unknown"
    if not _trusted(_ip(peer), trusted):
        return peer
    chain = [_ip(part) for part in request.headers.get("x-forwarded-for", "").split(",")]
    for address in reversed([a for a in chain if a is not None]):
        if not _trusted(address, trusted):
            return str(address)
    return peer
