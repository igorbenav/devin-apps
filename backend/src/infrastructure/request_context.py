"""Per-request id and client IP, available without threading ``Request`` around.

The audit log records who did what from where; service functions take a session
and an actor, not a ``Request``. A context variable set by
:class:`RequestContextMiddleware` keeps the transport details reachable from the
service layer without widening every service signature.
"""

import contextvars
import ipaddress
import re
import uuid
from dataclasses import dataclass

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config.settings import get_settings

REQUEST_ID_HEADER = "X-Request-ID"
FORWARDED_FOR_HEADER = "X-Forwarded-For"
REQUEST_ID_MAX_LENGTH = 64
# The header is proxy-written but still attacker-influenced; the value goes in a varchar audit column, so it is both
# truncated before parsing and required to be a real address.
FORWARDED_FOR_MAX_LENGTH = 1024
_SAFE_REQUEST_ID = re.compile(rf"^[A-Za-z0-9._-]{{1,{REQUEST_ID_MAX_LENGTH}}}$")


def _request_id_from(request: Request) -> str:
    """The caller's request id when it is safe to store and echo back, else a fresh one.

    The value lands in audit rows and in a response header, so an unbounded header of arbitrary bytes is not taken at
    face value.
    """
    supplied = request.headers.get(REQUEST_ID_HEADER)
    if supplied and _SAFE_REQUEST_ID.match(supplied):
        return supplied
    return str(uuid.uuid4())


def _client_ip(request: Request, trusted_proxy_hops: int) -> str | None:
    """The client address, trusting ``X-Forwarded-For`` only as far as the configured number of proxies.

    With no trusted proxy in front, the socket address is the only value worth recording: the header is caller-
    controlled and would let anyone write a false IP into the audit trail.
    """
    peer = request.client.host if request.client else None
    if trusted_proxy_hops < 1:
        return peer

    forwarded = request.headers.get(FORWARDED_FOR_HEADER)
    if not forwarded:
        return peer

    hops = [value.strip() for value in forwarded[:FORWARDED_FOR_MAX_LENGTH].split(",") if value.strip()]
    if len(hops) < trusted_proxy_hops:
        return peer

    candidate = hops[-trusted_proxy_hops]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return peer
    return candidate


@dataclass(frozen=True)
class RequestContext:
    """Transport metadata for the request currently being handled."""

    request_id: str
    ip: str | None


_request_context: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "platform_request_context", default=None
)


def get_request_context() -> RequestContext | None:
    """The current request's context, or ``None`` outside a request."""
    return _request_context.get()


def set_request_context(context: RequestContext | None) -> None:
    """Set the current request context (used by the middleware and by tests)."""
    _request_context.set(context)


class RequestContextMiddleware:
    """Populate :func:`get_request_context` and echo the request id back.

    Pure ASGI rather than ``BaseHTTPMiddleware`` so the context variable is set
    in the same task that runs the endpoint.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = _request_id_from(request)
        client_host = _client_ip(request, get_settings().TRUSTED_PROXY_HOPS)
        set_request_context(RequestContext(request_id=request_id, ip=client_host))

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            set_request_context(None)
