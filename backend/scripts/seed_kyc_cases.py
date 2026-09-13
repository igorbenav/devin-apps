"""Seed the KYC review queue with demo cases and their documents.

Idempotent by ``customer_ref``: re-running leaves existing cases untouched.
Two of the cases are already in review — one held by the seeded analyst, one by
the seeded reviewer — so the maker/checker refusal can be demonstrated by
logging in as the reviewer and trying to decide the case they hold.
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.infrastructure.database.initialize import close_database  # noqa: E402
from src.infrastructure.database.session import local_session  # noqa: E402
from src.infrastructure.logging import get_logger  # noqa: E402
from src.modules.platform import audit  # noqa: E402
from src.modules.tools.kyc.crud import crud_kyc_cases, crud_kyc_documents  # noqa: E402
from src.modules.tools.kyc.models import (  # noqa: E402
    DOC_STATUS_EXPIRED,
    DOC_STATUS_MISSING,
    DOC_STATUS_RECEIVED,
    STATE_APPROVED,
    STATE_ESCALATED,
    STATE_IN_REVIEW,
    STATE_PENDING,
    STATE_REJECTED,
)
from src.modules.tools.kyc.schemas import KycCaseCreate, KycCaseRead, KycDocumentCreate  # noqa: E402
from src.modules.tools.kyc.service import ENTITY_TYPE  # noqa: E402
from src.modules.user.service import UserService  # noqa: E402

logger = get_logger()

ANALYST_USERNAME = "analyst"
REVIEWER_USERNAME = "reviewer"

DOCUMENT_SETS: dict[str, list[tuple[str, str, str]]] = {
    "standard": [
        ("passport", "passport.pdf", DOC_STATUS_RECEIVED),
        ("proof_of_address", "utility-bill.pdf", DOC_STATUS_RECEIVED),
    ],
    "incomplete": [
        ("passport", "passport.pdf", DOC_STATUS_RECEIVED),
        ("proof_of_address", "lease.pdf", DOC_STATUS_MISSING),
        ("source_of_funds", "payslips.pdf", DOC_STATUS_RECEIVED),
    ],
    "stale": [
        ("passport", "passport-old.pdf", DOC_STATUS_EXPIRED),
        ("proof_of_address", "bank-statement.pdf", DOC_STATUS_RECEIVED),
        ("company_registry", "registry-extract.pdf", DOC_STATUS_RECEIVED),
    ],
}

# customer_ref, customer_name, risk_score, days_ago, state, assignee, reason, document set
CASES: list[tuple[str, str, int, int, str, str | None, str | None, str]] = [
    ("CUS-1001", "Aurora Freight Ltd", 91, 9, STATE_PENDING, None, None, "stale"),
    ("CUS-1002", "Priya Raman", 84, 7, STATE_PENDING, None, None, "incomplete"),
    ("CUS-1003", "Northwind Capital", 78, 6, STATE_IN_REVIEW, REVIEWER_USERNAME, None, "stale"),
    ("CUS-1004", "Tomas Eriksen", 73, 6, STATE_IN_REVIEW, ANALYST_USERNAME, None, "standard"),
    ("CUS-1005", "Bluefin Logistics", 66, 5, STATE_PENDING, None, None, "standard"),
    ("CUS-1006", "Hana Okabe", 58, 5, STATE_ESCALATED, None, "Sanctions screening hit needs compliance input", "incomplete"),
    ("CUS-1007", "Meridian Foods", 51, 4, STATE_PENDING, None, None, "standard"),
    ("CUS-1008", "Lucia Ferreira", 44, 3, STATE_IN_REVIEW, ANALYST_USERNAME, None, "standard"),
    (
        "CUS-1009",
        "Cobalt Studios",
        37,
        3,
        STATE_APPROVED,
        None,
        "Documents verified against registry, no adverse media",
        "standard",
    ),
    (
        "CUS-1010",
        "Samuel Adeyemi",
        29,
        2,
        STATE_REJECTED,
        None,
        "Proof of address expired and customer did not respond",
        "stale",
    ),
    ("CUS-1011", "Vertex Analytics", 22, 2, STATE_PENDING, None, None, "standard"),
    ("CUS-1012", "Mei Lin", 12, 1, STATE_PENDING, None, None, "standard"),
]


async def _user_ids(db: AsyncSession) -> dict[str, int]:
    user_service = UserService()
    ids: dict[str, int] = {}
    for username in (ANALYST_USERNAME, REVIEWER_USERNAME):
        user = await user_service.get_by_username(username, db)
        if user is not None:
            ids[username] = int(user["id"])
    return ids


async def seed_kyc_cases() -> None:
    """Create the demo cases, their documents, and a system audit entry each."""
    async with local_session() as db:
        user_ids = await _user_ids(db)
        if not user_ids:
            logger.warning("Demo users not found; seed platform roles first so cases can be assigned")

        created_count = 0
        for ref, name, risk, days_ago, state, assignee, reason, document_set in CASES:
            existing = await crud_kyc_cases.get(db=db, customer_ref=ref, schema_to_select=KycCaseRead)
            if existing is not None:
                continue

            case = await crud_kyc_cases.create(
                db=db,
                object=KycCaseCreate(
                    customer_ref=ref,
                    customer_name=name,
                    risk_score=risk,
                    submitted_at=datetime.now(UTC) - timedelta(days=days_ago),
                    state=state,
                    assigned_to=user_ids.get(assignee) if assignee else None,
                ),
                commit=False,
                schema_to_select=KycCaseRead,
            )
            if reason is not None:
                decided: dict[str, object] = {"decision_reason": reason}
                if state in (STATE_APPROVED, STATE_REJECTED):
                    decided["decided_by"] = user_ids.get(REVIEWER_USERNAME)
                await crud_kyc_cases.update(db=db, object=decided, id=case["id"], commit=False)

            for kind, filename, status in DOCUMENT_SETS[document_set]:
                await crud_kyc_documents.create(
                    db=db,
                    object=KycDocumentCreate(case_id=case["id"], kind=kind, filename=filename, status=status),
                    commit=False,
                )

            await audit.record(
                db,
                None,
                "kyc.case.seeded",
                ENTITY_TYPE,
                case["id"],
                after={"state": state, "risk_score": risk, "customer_ref": ref},
            )
            created_count += 1

        await db.commit()

    print(f"\nSeeded {created_count} KYC cases ({len(CASES) - created_count} already present).")
    print(f"  '{REVIEWER_USERNAME}' holds CUS-1003: deciding it as that user demonstrates the maker/checker block.")
    print(f"  '{ANALYST_USERNAME}' holds CUS-1004 and CUS-1008.\n")


async def main() -> None:
    try:
        await seed_kyc_cases()
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
