"""Demo data for the Tool Requests tool.

One already-submitted brief so the page has something on it, idempotent by title. It is left ``queued`` — seeding must
not call the Devin API and spend money.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ....platform_sdk import user_id_by_username
from .crud import crud_tool_requests
from .schemas import ToolRequestCreate

REQUESTER_USERNAME = "reviewer"

DEMO_REQUEST = {
    "title": "Chargeback review queue",
    "slug_hint": "chargebacks",
    "users": "Payment operations analysts, and the ops lead who signs off disputes.",
    "decision": "Decide whether to contest or accept a chargeback before the network deadline.",
    "today": "A shared spreadsheet plus a Slack thread per dispute; deadlines get missed.",
    "states": "new -> investigating -> contested | accepted. Analysts investigate, the ops lead decides.",
    "must_never_happen": "The analyst who gathered the evidence must not be the one who accepts the loss.",
    "provable": "Which evidence was attached and who decided, for the card networks and for the auditors.",
    "data_sources": "Disputes arrive from the PSP webhook export; decisions go back as a CSV for now.",
    "volume": "Around 40 disputes a day, 6 analysts.",
    "success": "No dispute misses its deadline in a month, and evidence is attached to every contested case.",
    "out_of_scope": "Automatic evidence gathering, and writing decisions back to the PSP.",
}


async def seed_demo_data(db: AsyncSession) -> None:
    """Insert the demo request this tool needs for a walkthrough."""
    if await crud_tool_requests.exists(db=db, title=DEMO_REQUEST["title"]):
        return

    requester_id = await user_id_by_username(db, REQUESTER_USERNAME)
    if requester_id is None:
        return

    await crud_tool_requests.create(
        db=db, object=ToolRequestCreate(**DEMO_REQUEST, requester_user_id=requester_id), commit=False
    )
    await db.commit()
