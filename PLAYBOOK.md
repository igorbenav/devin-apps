# How to add a new internal tool

Read this if you have never seen this repo: it takes you from nothing to a working internal
tool behind login, roles, and the audit log. Expect 30–90 minutes for a simple tool.

You are building for four people at once: the **operator** who works the queue many times a day
and wants to stop noticing the tool; the **requester** who owns the process and asked for it; the
**platform admin** who grants access and has to answer "who approved this?"; and the next
**builder** — usually another Devin session — who should recognise this tool's shape instantly.
What the operator does most often is what deserves the polish.

One repo, one deployable FastAPI app. Every internal tool is a vertical-slice module under
`backend/src/modules/tools/<slug>/` that plugs into the shared platform in
`backend/src/modules/platform/` (login, roles/permissions, audit log, launcher, admin). UI is
server-rendered Jinja2 + HTMX; no JS framework, no build step.

A tool is one directory, and it owns everything it contributes:

```text
backend/src/modules/tools/<slug>/
  models.py schemas.py crud.py service.py        domain
  permissions.py                                 the permission strings this tool owns
  router.py  templates/<slug>/*.html             pages
  api.py                                         optional JSON API under /api/v1
  admin.py                                       optional SQLAdmin views
  seed.py                                        optional demo data
  tests/                                         unit tests, next to the code
  tool.py                                        the manifest tying all of it together
```

Tools import the platform through one façade, `src.platform_sdk`, and nothing else of the
platform: `uv run --no-sync lint-imports` (backend/) enforces the layering, that no tool
imports another tool, and that the platform never imports a tool.
[ARCHITECTURE.md](ARCHITECTURE.md) explains why the repo is shaped this way and lists the
invariants a tool must not break.

## 1. Generate the module

```bash
uv run bp new tool kyc_review --label "KYC Review" --permission kyc.review \
  --description "Review and approve pending KYC cases."
```

The generated `tool.py` is the manifest, and it is the only registration there is:

```python
SPEC = register(
    ToolSpec(
        name="KYC Review",
        slug="kyc_review",
        description="...",
        route_prefix="/tools/kyc_review",
        required_permission=REQUIRED_PERMISSION,
        nav_label="KYC Review",
        pages=router,  # mounted at route_prefix
        api=api_router,
        api_prefix="/kyc",  # optional, mounted under /api/v1
        admin_views=(KycCaseAdmin,),  # optional SQLAdmin views
        permissions=PERMISSIONS,  # collected into the app-wide catalog
        seed=seed_demo_data,  # run by scripts/seed_tools.py
    )
)
```

The platform discovers the module on import and collects each field, so you never edit
`interfaces/api/v1/__init__.py`, `interfaces/admin/views/__init__.py`, or add a seed script.
Drop any field the tool does not need; delete the example domain once yours replaces it.

## 2. Model the domain

Edit `models.py`: SQLAlchemy 2 `Mapped`/`mapped_column`, inherit `Base` from `src.platform_sdk`,
table name prefixed with the tool slug (`kyc_review_case`), timestamps as
`DateTime(timezone=True)` with UTC defaults, status fields as plain strings with a small set of
documented values. `schemas.py` holds the Pydantic v2 schemas; `crud.py` one `FastCRUD(...)` per
model.

## 3. Define permissions

Permissions are flat dotted strings — no hierarchy, no implication — and the tool owns them, in
its own `permissions.py`:

```python
REQUIRED_PERMISSION: Final = "kyc.review"
PERMISSIONS: Final[tuple[Permission, ...]] = (Permission(REQUIRED_PERMISSION, "Open the queue"),)
```

Listing them in the manifest puts them in `permission_catalog()`, which is what `admin` and
superusers get. Which *other* seeded role holds one stays a shared decision: edit `ROLE_GRANTS`
in `backend/src/modules/platform/constants.py` and re-run
`uv run python -m scripts.create_platform_roles` from `backend/`. A permission no role holds is
a permission nobody has.

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
write cannot leave an audit entry behind (and vice versa); `request_id` and `ip` come from the
request context middleware. The audit table is append-only, in the CRUD layer and in SQLAdmin.
Do not add an update or delete path.

## 5. Routes, templates, HTMX, API, admin

`router.py` gates pages with `require_page_permission(REQUIRED_PERMISSION)` (a 403 renders an
error page) and JSON routes in `api.py` with `require_permission("...")`. Render with
`render(request, "kyc_review/list.html", viewer=viewer, context=...)`; the loader sees the
platform templates and every tool's `templates/<slug>/`, so names are namespaced by slug.

Pages extend `platform/base.html` (nav, current user, roles, tool list, logout). HTMX is
vendored at `backend/src/static/js/htmx.min.js` — never a CDN. The convention for an action:
`hx-post` to a route that calls the service and returns one rendered partial (`_row.html`) with
`hx-target`/`hx-swap="outerHTML"`. CSS is one hand-written file at
`backend/src/static/css/platform.css`. `admin.py` views subclass `PermissionGatedView` +
`AuditedAdminView` so back-office writes are gated and audited like service writes.

### The UX split: the platform owns the frame, the tool owns the work

The rule that keeps fifty tools coherent is that **if two tools would each make the same UI
decision, the platform makes it once.** The platform owns (and `platform_sdk` exposes) the page
shell, nav, current user and roles, the page-header pattern, permission-denied and not-found
pages, and the formatting filters. Do not re-implement any of those, and if you need one that
doesn't exist yet, add it to the platform rather than to your tool.

The tool owns its columns, its tabs, its detail layout, its action verbs and its domain language
— the things that are actually about the work. Within that:

- An action is `hx-post` → service → one re-rendered partial. Refusals render inline, in the page,
  saying *why* (the maker/checker 403 is the example to copy); never a raw JSON body.
- Buttons are rendered only when `current_permissions` **and** the domain rule both allow the
  action — and the service re-checks anyway, because hiding a button is not a control.
- Filter and tab state lives in the query string, so a pasted link reproduces the screen.
- Every list has an empty state; every irreversible action asks first.

What the platform *should* own and doesn't yet is tracked under the
[`shared-layer`](https://github.com/igorbenav/devin-apps/labels/shared-layer) label. If you find
yourself building one of those, build it in the platform and close the issue.

## 6. Migration and seed

Autogenerate, then read it before applying it:

```bash
cd backend
uv run alembic revision --autogenerate -m "add kyc_review tables"
uv run alembic upgrade head
uv run python -m scripts.seed_tools     # runs every tool's seed(), yours included
```

Check it for accidental drops, missing indexes on filtered columns, and correct `ondelete`
behaviour. Migrations are one shared linear chain: rebase yours if `head` moved.

## 7. Tests

```bash
cd backend && uv run pytest tests/unit src/modules/tools
```

Tests live in `modules/tools/<slug>/tests/` next to the code; fixtures (`db_session`,
`test_user`, `client`) come from `backend/conftest.py`. Keep the generated shape: a permission
test, a state-transition test asserting both the new state and the audit event it wrote, and a
rejected invalid transition. Unit tests only — do not spend time on integration tests.

## 8. Shipping it

Nothing tool-specific to do: one repo, one deployable app. The deploy rebuilds the image and the `migrate` service
runs `alembic upgrade head` then `scripts.sync_roles`, which picks up the permission strings your manifest declares
and applies your `ROLE_GRANTS` decision to the existing roles. Grants to *other* roles are a human choice in
`/admin` → Roles after the rollout. The full runbook — env file, preflight, upgrade, rollback — is [DEPLOY.md](DEPLOY.md).

What can still break a deploy, so check it before merging: a migration that is not rebased onto the current `head`
(the chain is linear), a seed that is not idempotent (it runs on every deploy in environments that seed), and a
permission string renamed without a migration for the rows already holding the old one.

## Definition of done

- `bp new tool` module replaced with your domain; no leftover example code.
- Everything the tool contributes is in its manifest; no shared registry file was edited.
- Permission declared in the tool, and the seeded-role decision made in `ROLE_GRANTS`.
- Every state change goes through a service function that records an audit event in the same
  transaction; no writes in route handlers.
- Migration generated, reviewed, applied; seed runs through `scripts/seed_tools.py`.
- Pages and at least one HTMX action work for a user holding the permission — and the tool is
  invisible on the launcher for a user who does not.
- The UX split above is respected: shared shell reused, failures visible in the page, lists have
  an empty state, and tab/filter state is in the URL.
- `uv run pytest tests/unit src/modules/tools`, `uv run --no-sync lint-imports` and
  `pre-commit run --all-files` pass.
- Anything you guessed at, decided alone, or would flag to a security reviewer is called out in the
  PR description — that is where a reviewer will look for it.
