# Architecture: one app, many tools

How this repo is organised and why, written for whoever adds tool number 4 — or tool number 50.
[PLAYBOOK.md](PLAYBOOK.md) is the procedure; this is the reasoning behind it.

## The shape

One repo, one deployable FastAPI app. Two layers that must not blur:

- **The platform** (`backend/src/modules/platform/`) owns everything every tool needs and nobody
  should re-implement: login, roles and permissions, the audit log, the launcher, the admin
  surface, templating and the page shell.
- **A tool** (`backend/src/modules/tools/<slug>/`) owns one business workflow, entirely inside its
  own directory.

Between them sits `backend/src/platform_sdk/` — the only thing a tool is allowed to import from
outside itself. Tools never import `interfaces/`, and the platform never imports a tool.

```text
backend/src/
  interfaces/       FastAPI app, HTTP wiring, SQLAdmin registration
  infrastructure/   config, database, auth, cache, taskiq, deploy preflight
  platform_sdk/     the tool-facing façade (ToolSpec, register, audit, render, deps)
  modules/
    platform/       registry · dependencies · audit · templating · admin · routes · constants
    tools/<slug>/   one directory per tool, self-contained
  static/           platform.css · vendored htmx
```

## Registration is a manifest, not a list

Every tool declares what it contributes in `tool.py`, and the platform *collects* it at startup:

```python
SPEC = register(
    ToolSpec(
        slug="kyc",
        name="KYC Review Queue",
        route_prefix="/tools/kyc",
        required_permission=PERM_KYC_REVIEW,
        pages=router,  # mounted at route_prefix
        api=api_router,
        api_prefix="/kyc",  # mounted under /api/v1
        admin_views=(KycCaseAdmin,),  # registered with SQLAdmin
        permissions=PERMISSIONS,  # merged into permission_catalog()
        seed=seed_demo_data,  # run by scripts/seed_tools.py
    )
)
```

`registry.discover_tools()` walks `modules/tools/*` and imports each `tool.py`; then
`include_tool_routers`, `include_tool_api_routers`, `register_tool_admin_views`,
`permission_catalog` and `run_tool_seeds` are loops over the registered specs. So the dependency
arrow is `interfaces → platform ← tools`: the platform never names a tool, and adding one edits no
shared file.

The one deliberate exception: **declaring a permission does not grant it.** Which seeded role holds
a new permission is a human decision in `ROLE_GRANTS` (`modules/platform/constants.py`) — `admin`
takes the whole catalog, anything else is an explicit edit. Silently widening a role from inside a
tool directory is the failure mode worth one shared edit per tool.

Rule for growing the manifest: a field exists only when the platform *collects* it. Anything a tool
merely configures for itself stays in the tool, or `ToolSpec` becomes a god object.

## Enforcement

The layering is checked, not trusted: `uv run --no-sync lint-imports` (in pre-commit and CI) asserts
the layer order, that no tool imports another tool, that the platform imports no tool, and that
tools reach shared code only through `platform_sdk`. Without it every rule here is a convention that
decays. There is one recorded `ignore_imports`
(`infrastructure.auth.routes -> modules.platform.service`) because CRUDAuth owns the login route
while login auditing lives in the platform; fixing that properly needs an event hook in the auth
layer.

`platform_sdk` is a promise: once fifty tools import it, changing it is a migration. Keep it small,
and refuse to re-export things a tool should not touch (sessions, the app factory, other tools).

## Invariants a tool must not break

- **Services write, routes don't.** Every state change goes through a service function that
  validates, writes, records an audit event and commits.
- **`audit.record` never commits.** It flushes into the caller's transaction, so a state change and
  its audit row land together or not at all. The cost: a caller who forgets to commit loses the
  audit entry — services are the only callers.
- **Permissions are resolved per request from the database**, not cached in the session, so a
  revoked permission takes effect immediately. It is one indexed join on a page render.
- **Superusers bypass permission checks, not domain rules.** KYC maker/checker is a service rule, so
  a superuser assigned to a case still cannot decide it.
- **Authorization is never the template.** Hiding a button is presentation; the service re-checks on
  every POST.
- **The audit log is append-only by construction** — no update or delete path in the CRUD layer, and
  the SQLAdmin view refuses writes. Not enforced by database grant; see [SECURITY.md](SECURITY.md).
- **Audit `before`/`after` carry the changed fields**, not whole rows: the payload is readable by
  anyone with `audit.read` and is not redacted.

## Conventions that are choices, not laws

- Platform tables are prefixed `platform_`, tool tables with the tool slug, so tools can own short
  names. Upstream tables (`user`, `tier`) are unprefixed.
- Tool routes live at `/tools/<slug>`; HTML routes are `include_in_schema=False` so the OpenAPI
  document stays the API surface.
- Templates resolve through a `ChoiceLoader` over the platform templates plus every tool's
  `templates/<slug>/`, which is what lets a tool ship HTML inside its module and still
  `{% extends "platform/base.html" %}`.
- Audit `entity_id` is a string column, because tools will have int PKs, UUIDs and composite-ish
  keys and one audit table is worth more than exact typing.
- Schema defaults belong in the Pydantic schema, not only the model: FastCRUD passes the whole dict
  through, so a model-level `default_factory` never fires for a field the schema defaulted to
  `None`.

## What 50 tools costs

- **Adding one**: `bp new tool <slug>` plus the domain. No shared-file edits, so no merge conflicts
  with the other 49 teams, except the role-grant decision above.
- **Startup**: 50 package imports and 50 routers — tens of milliseconds, once.
- **Launcher and admin**: already permission-filtered; they need grouping (`spec.category`) before
  they need anything structural.
- **Dependencies**: a tool that needs a library the platform does not have is the trigger to move
  *that* tool out, not to restructure everything.
- **Background jobs and integrations** slot into the manifest the same way (`tasks=(...)` collected
  into the taskiq broker) — that is the point of making the manifest the contract.

## Deliberate non-goals

- **Per-tool Alembic branches.** Migrations are one linear chain, so a tool rebases if `head` moved.
  Branches (`version_locations` per tool, `branch_label`, `alembic upgrade heads`) would remove that
  conflict and put a plural `heads` in the deploy runbook. Worth doing when merge conflicts on
  `down_revision` actually hurt; not before.
- **One installed package per tool** (uv workspace member per tool, discovered through entry
  points). That is real decoupling — per-tool dependencies and CI — at the price of 50
  `pyproject.toml` files and a versioned, released `platform_sdk`. The seam is left open: discovery
  can grow an entry-point scan alongside the directory walk, so moving one tool to a package later
  is a one-tool change rather than a rewrite.
- **Separate repos or separate deployments per tool.** The whole economic argument is that the tenth
  tool inherits auth, audit, migrations and operations from the first.
