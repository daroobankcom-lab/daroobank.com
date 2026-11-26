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


def require_nondebug_hosts(value):
    """Require explicit DNS/IP patterns, not an unrestricted wildcard or URL."""
    if (not isinstance(value, str) or not value or len(value) > 8192
            or any(not 32 <= ord(char) <= 126 for char in value)):
        raise ImproperlyConfigured('DAROOBANK_ALLOWED_HOSTS must explicitly list valid non-debug hosts.')
    hosts = [host.strip() for host in value.split(',')]
    if not hosts or any(not _valid_host_pattern(host) for host in hosts):
        raise ImproperlyConfigured('DAROOBANK_ALLOWED_HOSTS must explicitly list valid non-debug hosts.')
    return hosts
