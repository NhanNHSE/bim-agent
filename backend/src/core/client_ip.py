"""Resolve real client IP when behind a trusted reverse proxy."""

from ipaddress import ip_address, ip_network

from starlette.requests import Request

from src.core.config import get_settings


def _is_trusted_proxy(peer_ip) -> bool:
    """Check whether peer_ip belongs to any CIDR in settings.trusted_proxies."""
    raw = get_settings().trusted_proxies
    for part in raw.split(","):
        cidr = part.strip()
        if not cidr:
            continue
        try:
            net = ip_network(cidr, strict=False)
        except ValueError:
            continue
        if peer_ip in net:
            return True
    return False


def get_client_ip(request: Request) -> str:
    """Extract client IP, trusting X-Real-IP only from configured trusted proxies."""
    if request.client is None:
        return "unknown"

    peer = request.client.host
    try:
        peer_ip = ip_address(peer)
    except ValueError:
        return peer

    if _is_trusted_proxy(peer_ip):
        header = request.headers.get("x-real-ip")
        if header:
            try:
                return str(ip_address(header.strip()))
            except ValueError:
                pass

    return peer
