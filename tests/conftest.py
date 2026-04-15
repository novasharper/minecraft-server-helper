import socket

import pytest


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Block all real network connections in every test.

    Patches the two socket-level entry points that urllib3 uses for TCP
    connections and DNS resolution.  The ``responses`` library intercepts
    HTTP calls at the ``requests`` adapter level (above sockets), so tests
    decorated with ``@responses.activate`` are completely unaffected.
    """

    def _block(*args, **kwargs):
        raise OSError(
            "Real network calls are not allowed in tests. "
            "Use @responses.activate to mock HTTP requests."
        )

    monkeypatch.setattr(socket, "create_connection", _block)
    monkeypatch.setattr(socket, "getaddrinfo", _block)
