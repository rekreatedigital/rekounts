"""TLS still verifies the server when the host Python has no root certificates."""
import ssl
from unittest.mock import Mock

from rekounts import network


def test_bundled_roots_are_added_to_the_system_context(monkeypatch):
    context = Mock()
    create = Mock(return_value=context)
    monkeypatch.setattr(network.ssl, "create_default_context", create)
    monkeypatch.setattr(network.certifi, "where", lambda: "/bundle/cacert.pem")
    network.tls_context.cache_clear()
    try:
        assert network.tls_context() is context
        context.load_verify_locations.assert_called_once_with(cafile="/bundle/cacert.pem")
        create.assert_called_once_with()
        assert network.tls_context() is context
        create.assert_called_once()
    finally:
        network.tls_context.cache_clear()


def test_bundled_context_requires_a_trusted_hostname():
    context = network.tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
