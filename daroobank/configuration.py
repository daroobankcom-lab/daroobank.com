"""Small fail-closed checks for non-debug environment settings."""
import ipaddress
import re

from django.core.exceptions import ImproperlyConfigured

_DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z', re.IGNORECASE | re.ASCII)


def require_nondebug_secret(value):
    """Reject obvious unsafe shapes; this cannot determine randomness or secrecy."""
    if (not isinstance(value, str) or not 50 <= len(value) <= 512 or len(set(value)) < 5
            or value.lower().startswith('django-insecure-')
            or any(not 33 <= ord(char) <= 126 for char in value)):
        raise ImproperlyConfigured('DAROOBANK_SECRET_KEY must be a non-debug secret with a supported shape.')
    return value


def _valid_host_pattern(pattern):
    if pattern.startswith('[') and pattern.endswith(']'):
        try:
            return '%' not in pattern and ipaddress.ip_address(pattern[1:-1]).version == 6
        except ValueError:
            return False
    domain = pattern[1:] if pattern.startswith('.') else pattern
    if not domain or len(domain) > 253 or domain.startswith('.') or domain.endswith('.'):
        return False
    return all(_DNS_LABEL.fullmatch(label) is not None for label in domain.split('.'))


def parse_hsts_seconds(value):
    """Accept a bounded ASCII duration; enablement needs independent TLS review."""
    if value is None:
        return 0
    if (not isinstance(value, str) or not 1 <= len(value) <= 8
            or not value.isascii() or not value.isdecimal()):
        raise ImproperlyConfigured('DAROOBANK_HSTS_SECONDS must be an integer from 0 to 31536000.')
    seconds = int(value)
    if seconds > 31_536_000:
        raise ImproperlyConfigured('DAROOBANK_HSTS_SECONDS must be an integer from 0 to 31536000.')
    return seconds


def require_trusted_proxy_networks(value):
    """Parse a small explicit network list; this cannot prove proxy ownership."""
    message = 'DAROOBANK_TRUSTED_PROXY_CIDRS must list explicit, non-universal networks.'
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(not 32 <= ord(char) <= 126 for char in value)):
        raise ImproperlyConfigured(message)
    entries = [item.strip() for item in value.split(',')]
    if not 1 <= len(entries) <= 32 or any(not entry or '%' in entry for entry in entries):
        raise ImproperlyConfigured(message)
    try:
        networks = tuple(ipaddress.ip_network(entry, strict=True) for entry in entries)
    except ValueError:
        raise ImproperlyConfigured(message) from None
    # Reject lists that collectively cover all IPv4 or all IPv6 addresses,
    # including two complementary /1 networks. Smaller broad networks can
    # still be unsafe; their ownership cannot be checked here.
    for version in (4, 6):
        collapsed = ipaddress.collapse_addresses(network for network in networks if network.version == version)
        if any(network.prefixlen == 0 for network in collapsed):
            raise ImproperlyConfigured(message)
    return networks


def require_nondebug_hosts(value):
    """Require explicit DNS/IP patterns, not an unrestricted wildcard or URL."""
    if (not isinstance(value, str) or not value or len(value) > 8192
            or any(not 32 <= ord(char) <= 126 for char in value)):
        raise ImproperlyConfigured('DAROOBANK_ALLOWED_HOSTS must explicitly list valid non-debug hosts.')
    hosts = [host.strip() for host in value.split(',')]
    if not hosts or any(not _valid_host_pattern(host) for host in hosts):
        raise ImproperlyConfigured('DAROOBANK_ALLOWED_HOSTS must explicitly list valid non-debug hosts.')
    return hosts
