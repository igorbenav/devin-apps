# How to add a new internal tool

Read this if you have never seen this repo. It takes you from nothing to a working internal
tool behind login, roles, and the audit log. Expect 30–90 minutes for a simple tool.

## What this repo is

One repo, one deployable FastAPI app. Every internal tool is a vertical-slice module under
`backend/src/modules/tools/<slug>/` that plugs into the shared platform in
`backend/src/modules/platform/` (login, roles/permissions, audit log, launcher, admin). Tools
are never separate repos or separate deployments. UI is server-rendered Jinja2 + HTMX; there
is no JS framework and no build step.

## 1. Generate the module

```bash
uv run bp new tool kyc_review --label "KYC Review" --permission kyc.review \
  --description "Review and approve pending KYC cases."
```

This writes `backend/src/modules/tools/kyc_review/` (`models.py`, `schemas.py`, `crud.py`,
`service.py`, `router.py`, `admin.py`, `tool.py`, `templates/kyc_review/{list,detail,_row}.html`)
and `backend/tests/unit/tools/test_kyc_review.py`. The module registers itself on import —
`setup_platform()` discovers it and mounts its router — so you never edit a shared file to add
a tool. Delete the example model/service/route the generator gives you once yours replaces it.

## 2. Model the domain

Edit `models.py`. Follow the existing modules: SQLAlchemy 2 `Mapped`/`mapped_column`, inherit
`Base` from `src.infrastructure.database.session`, table name prefixed with the tool slug
(`kyc_review_case`), timestamps as `DateTime(timezone=True)` with UTC defaults. Keep status
fields as plain strings with a small set of documented values. `schemas.py` holds the Pydantic
v2 create/update/read schemas; `crud.py` holds one `FastCRUD(...)` object per model.

## 3. Define permissions

Permissions are flat dotted strings — no hierarchy, no implication. Add yours to
`backend/src/modules/platform/constants.py`:

```python
PERM_KYC_REVIEW: Final = "kyc.review"
ALL_PERMISSIONS: Final[tuple[str, ...]] = (..., PERM_KYC_REVIEW)
```

Then add it to the seeded roles in the same file (`ANALYST_PERMISSIONS`,
`REVIEWER_PERMISSIONS`; `admin` gets everything automatically) and re-run
`uv run python -m scripts.create_platform_roles` from `backend/`. Superusers pass every check
without any role. A permission that no role holds is a permission nobody has.

## 4. Services do the writing, and audit it

Route handlers never write. Every state change goes through a function in `service.py` that
validates, writes, records an audit event, and commits — one transaction:

```python
async def approve_case(db: AsyncSession, actor: dict[str, Any], case_id: int) -> dict[str, Any]:
    case = await get_case(db, case_id)
    if case["status"] != "pending":
        raise InvalidStateError(f"Case {case_id} is {case['status']}, not pending")

    before = {"status": case["status"]}
    await crud_cases.update(db=db, object=CaseUpdate(status="approved"), id=case_id, commit=False)
    await audit.record(db, actor, "kyc.case.approved", "kyc_case", case_id, before=before, after={"status": "approved"})
    await db.commit()
```

`audit.record` never commits on its own — it flushes into the caller's transaction, so a failed
write cannot leave an audit entry behind (and vice versa). `request_id` and `ip` are picked up
from the request context middleware. The audit table is append-only: there is no update or
delete path, in the CRUD layer or in SQLAdmin. Do not add one.

## 5. Routes, templates, HTMX

`router.py` gates pages with `require_page_permission(SPEC.required_permission)` (HTML: a 403
renders an error page) and JSON/API routes with `require_permission("...")`. Render with
`render(request, viewer, "kyc_review/list.html", ...)` from
`src.modules.platform.templating`; the loader already sees both the platform templates and
every tool's `templates/<slug>/` directory, so template names are namespaced by slug.

Pages extend `platform/base.html` (nav, current user, roles, tool list, logout). HTMX is
vendored at `backend/src/static/js/htmx.min.js` — never a CDN. The convention for an action:
`hx-post` to a route that performs the service call and returns a single rendered partial
(`_row.html`) with `hx-target`/`hx-swap="outerHTML"`. Full-page reload after a mutation is a
fallback, not the default. CSS is one hand-written file at `backend/src/static/css/platform.css`;
add classes there rather than inline styles. No JS framework, no build step.

`admin.py` registers a SQLAdmin view for the tool's tables; `tool.py` holds the `ToolSpec`
(name, slug, description, route prefix, required permission, nav label) that the launcher uses
to decide whether to show your tool to a given user.

## 6. Migration

Autogenerate, then read it before applying it:

```bash
cd backend
uv run alembic revision --autogenerate -m "add kyc_review tables"
uv run alembic upgrade head
```

Check the generated file for accidental drops, missing indexes on filtered columns, and correct
`ondelete` behaviour. Strip Alembic's boilerplate comments. One migration per tool is fine.

## 7. Tests

```bash
cd backend && uv run pytest tests/unit
```

The generated test file is the shape to keep: a permission test (holder allowed, non-holder gets
403 with a clear message), a state-transition test asserting both the new state and the audit
event it wrote, and a test that the invalid transition is rejected. Unit tests only — do not
spend time on integration tests.

## Definition of done

- `bp new tool` module replaced with your domain; no leftover example code.
- Permission added to `constants.py` **and** to the seeded roles, seed script re-run.
- Every state change goes through a service function that records an audit event in the same
  transaction; no writes in route handlers.
- Migration generated, reviewed, applied.
- List page, detail page, and at least one HTMX action work while logged in as a user holding
  the permission — and the tool is invisible on the launcher for a user who does not.
- `uv run pytest tests/unit` passes; lint/format clean (`pre-commit run --all-files`).
- Anything you guessed at, decided alone, or would flag to a security reviewer is appended to
  `NOTES.md`.
