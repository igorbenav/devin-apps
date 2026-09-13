"""Per-request id and client IP, available without threading ``Request`` around.

The audit log records who did what from where; service functions take a session
and an actor, not a ``Request``. A context variable set by
:class:`RequestContextMiddleware` keeps the transport details reachable from the
service layer without widening every service signature.
"""

import contextvars
import uuid
from dataclasses import dataclass

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"


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
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        client_host = request.client.host if request.client else None
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
