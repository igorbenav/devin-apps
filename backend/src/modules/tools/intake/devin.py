"""The one place this app talks to the Devin API.

Deliberately small: create a session, return its id and url. The API key is read from settings and never leaves the
server, and a missing key is a distinct error so the UI can say "not configured" rather than "failed".
"""

from typing import Any

import httpx

from ....infrastructure.config.settings import settings

CREATE_SESSION_PATH = "/v1/sessions"


class DevinNotConfigured(Exception):
    """No API key is set, so this deployment cannot start sessions itself."""


class DevinDispatchError(Exception):
    """The API rejected the request or could not be reached.

    ``ambiguous`` means the session may exist anyway: a timeout, a 5xx, or a 2xx this client could not read. Retrying
    those automatically would pay for a second session, so the caller has to leave them to a human.
    """

    def __init__(self, message: str, ambiguous: bool = False) -> None:
        super().__init__(message)
        self.ambiguous = ambiguous


def is_configured() -> bool:
    return bool(settings.DEVIN_API_KEY)


async def create_session(prompt: str, tags: list[str], title: str) -> dict[str, Any]:
    """Start a Devin session from ``prompt``; returns ``{"session_id", "url"}``.

    ``tags`` carry the tool slug so usage is attributable per tool from the first session, and ``max_acu_limit`` caps
    what a single form submission can spend.
    """
    if not is_configured():
        raise DevinNotConfigured("DEVIN_API_KEY is not set")

    payload: dict[str, Any] = {
        "prompt": prompt,
        "tags": tags,
        "title": title,
        "max_acu_limit": settings.DEVIN_MAX_ACU_LIMIT,
    }
    if settings.DEVIN_TOOL_PLAYBOOK_ID:
        payload["playbook_id"] = settings.DEVIN_TOOL_PLAYBOOK_ID

    try:
        async with httpx.AsyncClient(
            base_url=settings.DEVIN_API_BASE_URL, timeout=settings.DEVIN_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(
                CREATE_SESSION_PATH, json=payload, headers={"Authorization": f"Bearer {settings.DEVIN_API_KEY}"}
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:  # the response body can echo the prompt; only the status is safe to surface
        status_code = exc.response.status_code
        raise DevinDispatchError(f"Devin API returned {status_code}", ambiguous=status_code >= 500) from exc
    except httpx.HTTPError as exc:
        raise DevinDispatchError(f"Could not reach the Devin API: {type(exc).__name__}", ambiguous=True) from exc
    except ValueError as exc:  # a 2xx that is not JSON, e.g. a gateway's maintenance page
        raise DevinDispatchError("Devin API returned a response that was not JSON", ambiguous=True) from exc

    if not isinstance(body, dict):
        raise DevinDispatchError("Devin API returned an unexpected response shape", ambiguous=True)

    session_id = body.get("session_id")
    if not session_id:
        raise DevinDispatchError("Devin API response contained no session_id", ambiguous=True)

    return {"session_id": str(session_id), "url": str(body.get("url") or "")}
