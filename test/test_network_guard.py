"""No test reaches the network: a connection fails the test and names the test, the host and the remedy."""
import socket
from types import SimpleNamespace

import pytest

import network_guard


@pytest.mark.unit
def test_a_connection_to_a_host_fails_naming_the_test_the_host_and_the_remedy(request) -> None:
    with pytest.raises(network_guard.NetworkGuardError) as raised:
        socket.create_connection(("example.invalid", 443), timeout=1)

    assert network_guard.take() == [str(raised.value)]
    message = str(raised.value)
    assert message.startswith(f"{network_guard.OWNER}: test {request.node.nodeid} ")
    assert "example.invalid:443" in message
    assert "remote_images fixture in test/conftest.py" in message


@pytest.mark.unit
def test_a_connection_by_address_fails_too() -> None:
    with socket.socket() as connection, pytest.raises(network_guard.NetworkGuardError) as raised:
        connection.connect(("192.0.2.1", 80))

    assert network_guard.take() == [str(raised.value)]
    assert "192.0.2.1:80" in str(raised.value)


@pytest.mark.unit
def test_an_attempt_the_code_caught_still_fails_the_test_phase() -> None:
    with pytest.raises(OSError):
        socket.getaddrinfo("example.invalid", 80)
    report = SimpleNamespace(outcome="passed", longrepr=None)

    network_guard.fail(report)

    assert report.outcome == "failed"
    assert "example.invalid:80" in report.longrepr


@pytest.mark.unit
def test_a_loopback_server_stays_reachable() -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        with socket.create_connection(server.getsockname(), timeout=1):
            pass

    assert network_guard.take() == []
