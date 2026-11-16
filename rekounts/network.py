"""TLS trust for the model download and optional release check."""
import ssl
from functools import lru_cache

import certifi


@lru_cache(maxsize=1)
def tls_context() -> ssl.SSLContext:
    """Keep system trust and add bundled roots for python.org/frozen Macs.

    Never disable certificate or hostname verification. Adding certifi to the
    default context also keeps locally installed enterprise CA certificates.
    """
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context
