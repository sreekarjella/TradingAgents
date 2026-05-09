"""Network auto-detection — Walmart proxy vs home direct connection.

Call ``configure_network()`` once at startup. It detects which network
you're on and sets proxy environment variables accordingly.

Walmart network → proxy for yfinance, clear proxy for Angel One
Home network    → direct connection for everything
"""

from __future__ import annotations

import logging
import os
import socket

logger = logging.getLogger(__name__)

_WALMART_PROXY = "http://sysproxy.wal-mart.com:8080"
_WALMART_PROXY_HOST = "sysproxy.wal-mart.com"
_LOCAL_HOSTS = "localhost,127.0.0.1,0.0.0.0"


def is_walmart_network() -> bool:
    """Check if we're on the Walmart network by resolving the proxy hostname."""
    try:
        socket.getaddrinfo(_WALMART_PROXY_HOST, 8080, socket.AF_INET, socket.SOCK_STREAM)
        return True
    except socket.gaierror:
        return False


def configure_network() -> str:
    """Auto-detect network and configure proxy environment variables.

    Returns:
        ``"walmart"`` or ``"home"`` indicating detected network.
    """
    if is_walmart_network():
        os.environ["HTTP_PROXY"] = _WALMART_PROXY
        os.environ["HTTPS_PROXY"] = _WALMART_PROXY
        os.environ["NO_PROXY"] = _LOCAL_HOSTS
        os.environ["no_proxy"] = _LOCAL_HOSTS
        logger.info("Walmart network detected — proxy configured for external APIs")
        return "walmart"

    # Home network — clear any proxy that might have leaked from .env
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(key, None)
    os.environ.pop("NO_PROXY", None)
    os.environ.pop("no_proxy", None)
    logger.info("Home network detected — direct connection, no proxy")
    return "home"


def clear_proxy_for_angel_one() -> None:
    """Temporarily clear proxy for Angel One SmartAPI calls.

    Angel One's API is blocked by Walmart proxy (407), so we must
    clear proxy vars before making SmartAPI calls. Only works on
    home network — on Walmart network, Angel One won't work regardless.
    """
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(key, None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    network = configure_network()
    print(f"Detected network: {network}")
    print(f"HTTP_PROXY: {os.environ.get('HTTP_PROXY', '(not set)')}")
    print(f"HTTPS_PROXY: {os.environ.get('HTTPS_PROXY', '(not set)')}")
