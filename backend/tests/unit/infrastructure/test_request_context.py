"""Tests for the per-request id and client IP recorded on audit events."""

from starlette.requests import Request

from src.infrastructure.request_context import REQUEST_ID_MAX_LENGTH, _client_ip, _request_id_from


def _request(headers: dict[str, str], client: tuple[str, int] | None = ("10.0.0.9", 1234)) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_caller_request_id_is_kept_when_plain():
    assert _request_id_from(_request({"X-Request-ID": "abc-123_ok.1"})) == "abc-123_ok.1"


def test_oversized_request_id_is_replaced():
    supplied = "a" * (REQUEST_ID_MAX_LENGTH + 1)
    assert _request_id_from(_request({"X-Request-ID": supplied})) != supplied


def test_request_id_with_control_characters_is_replaced():
    supplied = "abc\r\nX-Injected: 1"
    assert _request_id_from(_request({"X-Request-ID": supplied})) != supplied


def test_forwarded_for_is_ignored_without_trusted_proxies():
    request = _request({"X-Forwarded-For": "1.2.3.4"})
    assert _client_ip(request, trusted_proxy_hops=0) == "10.0.0.9"


def test_forwarded_for_is_read_one_hop_back():
    request = _request({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    assert _client_ip(request, trusted_proxy_hops=1) == "203.0.113.7"


def test_short_forwarded_chain_falls_back_to_the_socket():
    request = _request({"X-Forwarded-For": "1.2.3.4"})
    assert _client_ip(request, trusted_proxy_hops=2) == "10.0.0.9"


def test_forwarded_value_that_is_not_an_address_falls_back_to_the_socket():
    """The header reaches a varchar audit column; a junk hop must not be written or break the insert."""
    request = _request({"X-Forwarded-For": "1.2.3.4, not-an-ip"})
    assert _client_ip(request, trusted_proxy_hops=1) == "10.0.0.9"


def test_oversized_forwarded_header_falls_back_to_the_socket():
    request = _request({"X-Forwarded-For": "9." * 5000 + "203.0.113.7"})
    assert _client_ip(request, trusted_proxy_hops=1) == "10.0.0.9"
