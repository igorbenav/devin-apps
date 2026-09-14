"""Demo data for the Refunds tool.

Idempotent by ``order_ref``: re-running leaves existing refunds untouched, which matters because
the seed runs on every deploy in environments that seed.

The set is chosen so the rules are demonstrable rather than just described: two refunds are
above the high-value threshold, and ORD-90114 was raised by the seeded *reviewer*, so logging in
as that user and trying to approve it shows the self-approval refusal.

Referenced from ``tool.py`` as the tool's ``seed``; the platform calls it from ``run_tool_seeds``
so there is no per-tool seed script.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....infrastructure.logging import get_logger
from ....platform_sdk import audit, user_id_by_username
from .crud import crud_refund_requests
from .models import STATE_APPROVED, STATE_PROCESSED, STATE_REJECTED, STATE_REQUESTED
from .schemas import RefundRequestCreate, RefundRequestRead
from .service import ENTITY_TYPE

logger = get_logger()

ANALYST_USERNAME = "analyst"
REVIEWER_USERNAME = "reviewer"

# order_ref, customer_ref, amount, currency, requester's reason, state, requested by, days ago, decision reason
REFUNDS: list[tuple[str, str, str, str, str, str, str, int, str | None]] = [
    (
        "ORD-90110",
        "CUS-4801",
        "42.50",
        "EUR",
        "Customer charged for expedited shipping that was never applied",
        STATE_REQUESTED,
        ANALYST_USERNAME,
        1,
        None,
    ),
    (
        "ORD-90114",
        "CUS-4802",
        "180.00",
        "EUR",
        "Damaged item, photos received and accepted by the warehouse",
        STATE_REQUESTED,
        REVIEWER_USERNAME,
        1,
        None,
    ),
    (
        "ORD-90118",
        "CUS-4803",
        "1450.00",
        "EUR",
        "Bulk order cancelled inside the cooling-off window",
        STATE_REQUESTED,
        ANALYST_USERNAME,
        2,
        None,
    ),
    (
        "ORD-90121",
        "CUS-4804",
        "76.20",
        "GBP",
        "Duplicate charge on the same order, confirmed with the customer",
        STATE_REQUESTED,
        ANALYST_USERNAME,
        2,
        None,
    ),
    (
        "ORD-90126",
        "CUS-4805",
        "310.00",
        "USD",
        "Subscription renewed after the customer cancelled in writing",
        STATE_REQUESTED,
        ANALYST_USERNAME,
        3,
        None,
    ),
    (
        "ORD-90130",
        "CUS-4806",
        "24.99",
        "EUR",
        "Promised discount code failed at checkout",
        STATE_REQUESTED,
        ANALYST_USERNAME,
        3,
        None,
    ),
    (
        "ORD-90133",
        "CUS-4807",
        "2100.00",
        "USD",
        "Enterprise order fulfilled twice after an integration retry",
        STATE_APPROVED,
        ANALYST_USERNAME,
        4,
        "Duplicate fulfilment confirmed in the warehouse log; finance notified of the amount",
    ),
    (
        "ORD-90137",
        "CUS-4808",
        "129.00",
        "EUR",
        "Item arrived three weeks late and was refused on delivery",
        STATE_APPROVED,
        ANALYST_USERNAME,
        4,
        "Carrier confirmed the delay; refusal on delivery is refundable in full",
    ),
    (
        "ORD-90141",
        "CUS-4809",
        "58.40",
        "GBP",
        "Wrong size shipped and the replacement was out of stock",
        STATE_APPROVED,
        ANALYST_USERNAME,
        5,
        "Replacement unavailable, so a refund is the only remedy left",
    ),
    (
        "ORD-90145",
        "CUS-4810",
        "430.00",
        "EUR",
        "Service never activated after the customer paid the setup fee",
        STATE_APPROVED,
        ANALYST_USERNAME,
        5,
        "Activation never completed on our side; setup fee refunded in full",
    ),
    (
        "ORD-90149",
        "CUS-4811",
        "19.90",
        "EUR",
        "Customer says the download link never worked",
        STATE_REJECTED,
        ANALYST_USERNAME,
        6,
        "Access logs show four successful downloads, so nothing is owed",
    ),
    (
        "ORD-90152",
        "CUS-4812",
        "890.00",
        "USD",
        "Customer changed their mind two months after delivery",
        STATE_REJECTED,
        ANALYST_USERNAME,
        7,
        "Outside the 30-day returns window and the goods were used",
    ),
    (
        "ORD-90156",
        "CUS-4813",
        "64.00",
        "EUR",
        "Charged twice for the same monthly plan",
        STATE_PROCESSED,
        ANALYST_USERNAME,
        8,
        "Double charge confirmed in the payment provider dashboard",
    ),
    (
        "ORD-90160",
        "CUS-4814",
        "215.75",
        "GBP",
        "Order lost in transit and never recovered",
        STATE_PROCESSED,
        ANALYST_USERNAME,
        9,
        "Carrier declared the parcel lost; refunded rather than reshipped",
    ),
    (
        "ORD-90164",
        "CUS-4815",
        "1290.00",
        "EUR",
        "Annual plan billed after the customer downgraded",
        STATE_PROCESSED,
        ANALYST_USERNAME,
        12,
        "Downgrade was recorded before the renewal ran; full difference refunded",
    ),
]


async def _user_ids(db: AsyncSession) -> dict[str, int]:
    ids: dict[str, int] = {}
    for username in (ANALYST_USERNAME, REVIEWER_USERNAME):
        user_id = await user_id_by_username(db, username)
        if user_id is not None:
            ids[username] = user_id
    return ids


async def seed_demo_data(db: AsyncSession) -> None:
    """Create the demo refunds, their decisions, and a system audit entry each."""
    user_ids = await _user_ids(db)
    if not user_ids:
        logger.warning("Demo users not found; seed platform roles first so refunds can be attributed")

    now = datetime.now(UTC)
    created_count = 0
    for order_ref, customer_ref, amount, currency, reason, state, requester, days_ago, decision_reason in REFUNDS:
        if await crud_refund_requests.exists(db=db, order_ref=order_ref):
            continue

        refund = await crud_refund_requests.create(
            db=db,
            object=RefundRequestCreate(
                customer_ref=customer_ref,
                order_ref=order_ref,
                amount=Decimal(amount),
                currency=currency,
                reason=reason,
                requested_by=user_ids.get(requester),
                state=state,
            ),
            commit=False,
            schema_to_select=RefundRequestRead,
        )

        decided: dict[str, Any] = {}
        if state != STATE_REQUESTED:
            decided["decided_by"] = user_ids.get(REVIEWER_USERNAME)
            decided["decision_reason"] = decision_reason
            decided["decided_at"] = now - timedelta(days=days_ago - 1)
        if state == STATE_PROCESSED:
            decided["processed_by"] = user_ids.get(ANALYST_USERNAME)
            decided["processed_at"] = now - timedelta(days=days_ago - 2)
        if decided:
            await crud_refund_requests.update(db=db, object=decided, id=refund["id"], commit=False)

        await audit.record(
            db,
            None,
            "refunds.request.seeded",
            ENTITY_TYPE,
            refund["id"],
            after={"state": state, "amount": amount, "currency": currency, "order_ref": order_ref},
        )
        created_count += 1

    await db.commit()

    print(f"\nSeeded {created_count} refund requests ({len(REFUNDS) - created_count} already present).")
    print(f"  ORD-90114 was raised by '{REVIEWER_USERNAME}': approving it as that user demonstrates the self-approval block.")
    print("  ORD-90118 and ORD-90133 are above the high-value threshold.\n")
