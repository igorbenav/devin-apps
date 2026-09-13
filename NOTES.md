# NOTES

Append-only. Newest session at the bottom.

## Session 1 — shared platform layer, tool generator, playbook (branch `platform`)

### Decisions made without being told

- **Platform lives in `backend/src/modules/platform/`**, not a top-level `src/platform/`. It is a
  vertical slice like `user` and `tier`, so it follows the same module layout
  (`models/schemas/crud/service/dependencies/routes`). Only the request-context middleware went to
  `infrastructure/` (`request_context.py`), because it is plumbing, not a domain.
- **Browser login is a new HTML route (`GET/POST /login`), not a change to `/api/v1/auth/login`.**
  The JSON API is unchanged; the HTML form calls the same crudauth session machinery. Internal
  users need somewhere to log in with a browser, and I did not want to touch the existing API
  contract or its tests.
- **Permissions are resolved per request from the database**, not cached in the session. Roles
  change rarely but a stale session granting a revoked permission is the failure mode I did not
  want. It is one indexed join per request on a page-render path; revisit if it shows up in a
  profile.
- **Superusers bypass every permission check** (`get_permissions_for_user(..., is_superuser=True)`
  returns the whole catalog) so the platform is operable before any role exists.
- **`audit.record` never commits.** It writes and flushes into the caller's transaction; the
  service function commits. That is the only way to guarantee "state change and audit entry land
  together or not at all", which was the actual requirement. The cost is that a caller who forgets
  to commit silently loses the audit entry — services are the only callers, and each one commits.
- **Audit `entity_id` is stored as a string.** Tools will have int PKs, UUIDs, and composite-ish
  keys; one column type avoids a second audit table per key type.
- **Role seeding is audited.** `upsert_role`/`assign_role` go through the same service path as
  everything else, so a fresh seed leaves ~10 `platform.role.*` events with a null actor (system).
  I preferred that over a silent write path.
- **Seed script is a sibling (`scripts/create_platform_roles.py`) called from
  `setup_initial_data.py`**, matching how `create_first_tier` / `create_first_superuser` are
  already composed.
- **SQLAdmin now accepts platform users, not only the configured `ADMIN_USERNAME` pair.** A user
  with `platform.admin` (or a superuser) can log into `/admin`; the audit view additionally needs
  `audit.read`. The configured break-glass pair still works and still writes exactly
  `{"admin_authenticated": True}` into the session — the views treat a session with no `user_id` as
  the break-glass superuser, which is how I kept the existing admin-auth tests untouched.
- **The single migration is a baseline "initial schema", not a platform-tables-only migration.**
  The boilerplate ships zero migrations and creates tables from the models at startup
  (`CREATE_TABLES_ON_STARTUP=true`), so a platform-only migration cannot apply to a fresh database
  — its foreign keys point at a `user` table Alembic has never created. I wrote the platform-only
  version first, found it fails on a genuinely empty database, and regenerated it as the baseline
  the repo's own migration docs tell you to create. The documented run flow therefore sets
  `CREATE_TABLES_ON_STARTUP=false`, so Alembic owns the schema and does not race `create_all`.
- **`ClientCacheMiddleware` was publicly caching every non-`/api/` response — flag for the security
  reviewer.** It assumed "not an API path" meant "static asset" and set `public, max-age=60`. That
  predates this PR but only became dangerous once the platform served authenticated HTML: browser
  testing hit a cached `/login?next=/audit` after logging in, and the same header would let a shared
  cache serve one user's launcher or audit page to another. Inverted it — only `/static/` is public,
  everything else is `private, no-cache, no-store, must-revalidate` — with a test.
- **`CREATE_TABLES_ON_STARTUP` was silently ignored (upstream bug, fixed here).** `main.py` supplies
  its own `lifespan_with_security`, which called `lifespan_factory(settings)` and therefore took the
  factory's `create_tables_on_startup=True` default — the setting is only honoured on the lifespan
  `create_application` builds for you. So the app ran `create_all` regardless and the subsequent
  `alembic upgrade head` died with `DuplicateTableError`. Caught during browser testing; `main.py`
  now passes `settings.CREATE_TABLES_ON_STARTUP` through. Worth reporting upstream.
- **Migrate and seed run from the host, not `docker compose exec api`.** The dev image copies only
  `backend/src` and `backend/tests`, so `alembic.ini`, `migrations/` and `scripts/` are not in the
  container (there is a separate `migrate` build target for the migrations alone, and nothing that
  ships the seed script). My first README draft used `compose exec api` and failed with
  `No 'script_location' key found in configuration.` — caught during browser testing. Packaging
  the migrations and scripts into the dev image would be the real fix; out of scope here.
- **The launcher renders a "no tools yet" empty state** rather than 404ing, since Session 1 ships
  zero tools by design.
- **Generator Jinja uses `<< >>` / `<% %>` delimiters.** The templates emit Jinja *and* Python, so
  the default `{{ }}` collided with the templates' own HTMX/Jinja output (and `[[ ]]`, my first
  attempt, collided with Python list literals — see "took longer" below).

### Places I guessed at repo conventions

- Table naming: `platform_role`, `platform_user_role`, `platform_audit_event`. Existing tables are
  unprefixed singular (`user`, `tier`); I prefixed the platform ones so tool tables can own the
  short names. The generator prefixes tool tables with the tool slug for the same reason.
- Tool route prefix is `/tools/<slug>`. Nothing in the repo dictated it.
- HTML routes are `include_in_schema=False` so they stay out of the OpenAPI doc, which is otherwise
  the API surface.
- Templates are addressed as `<slug>/list.html` through a `ChoiceLoader` over the platform
  templates plus every tool's `templates/` dir. That is the mechanism that lets templates live
  inside the module and still resolve by a short name.
- `ForbiddenException` from crudauth is reused for 403s rather than a new exception type.

### For a security reviewer

- **Seeded demo users (`analyst` / `reviewer` / `toolsadmin`, password `Demo1234!`) are a demo
  affordance and a liability.** They are created by the normal seed script. If this ever runs
  outside a demo, the seeding must be gated on environment or removed. `DEMO_USER_PASSWORD`
  overrides the password but the default is weak on purpose.
- **`/admin` access is now permission-driven.** Anyone holding `platform.admin` can edit roles and
  role assignments through SQLAdmin — i.e. `platform.admin` is effectively privilege-escalation to
  everything. That is intentional (it is the admin role) but should be granted like root.
- **The audit log is append-only by construction, not by database grant.** The CRUD wrapper raises
  on `update`/`upsert`/`delete`, and the SQLAdmin view refuses writes, but anything holding a raw
  session can still `UPDATE platform_audit_event`. If audit integrity matters legally, add a
  database role without UPDATE/DELETE on that table, or ship to an append-only store.
- **Audit `before`/`after` payloads are whatever the service passes.** Nothing redacts them. A tool
  that dumps a full row into `after` will put PII (and, if someone is careless, secrets) into the
  audit log, which is readable by anyone with `audit.read`. The playbook says to pass the changed
  fields only; it is a convention, not an enforcement.
- **Client IP comes from the socket, not `X-Forwarded-For`.** Behind the nginx compose profile the
  recorded IP will be the proxy's unless a trusted-proxy middleware is added. Better wrong-and-
  honest than spoofable.
- Login errors are deliberately generic ("Invalid username or password") and the `?next=` parameter
  is restricted to same-origin relative paths (no `//host`, no backslashes, no control characters).
- No rate limiting on the login form — per the brief, internal tools do not get rate limiting. For
  a public-internet deployment, the login route is the one place I would reconsider. crudauth's
  escalating lockout still applies.
- HTMX is vendored, not CDN-loaded: `backend/src/static/js/htmx.min.js` is htmx 2.0.4 fetched from
  unpkg. No SRI is needed since it is served same-origin, but the version is pinned by the file and
  needs manual bumping.

### Time / what took longer than expected

- **Generator proof (`bp new tool example` → migration → tests → delete): ~25 minutes**, of which
  maybe 2 were the generator actually running. The rest was two real bugs the proof caught, which
  is exactly why it was worth doing:
  1. Jinja delimiter collision — the generator's `[[ ]]` delimiters broke on the Python list
     literals in the SQLAdmin template. Moved the generator to `<< >>` / `<% %>` / `<# #>`.
  1. FastCRUD's `create()` returns `None` unless you pass `schema_to_select`, so the generated
     service's `created.title` blew up under test. The template now passes `schema_to_select` and
     works with the returned dict. Worth knowing before writing any tool service.
- Wiring SQLAdmin auth to platform permissions without breaking the existing admin-auth tests took
  two attempts; the first stored extra keys in the session and the tests assert the exact session
  payload.
- Everything else was roughly on time. Nothing was cut.

### Not done / deliberately out of scope

- No real tool ships in this PR: the only tool built was the throwaway `example`, deleted with its
  migration before committing (per the brief).
- No integration tests. Unit tests cover permission resolution, the dependencies, role state
  transitions, audit writes and append-only enforcement, registry filtering, and the platform
  pages.
- Entra/OIDC is a README paragraph only.

## Session 2 — KYC review queue (`tool/kyc`)

### Generator output: kept vs rewritten

Kept, unchanged or nearly so: the module skeleton and file layout, `crud.py` (two `FastCRUD`
objects instead of one), `tool.py`'s `ToolSpec` and its auto-registration, `admin.py`'s
read-only SQLAdmin view (duplicated for the second model), the `templates/kyc/` directory
convention and the `{% extends "platform/base.html" %}` header block, the router's
`require_page_permission` dependency alias, and the test file's location and fixtures.

Rewritten: everything with domain content. `models.py`, `schemas.py`, `service.py`, `router.py`
and all three templates were replaced — the generated example is a single-model
open/done toggle, and KYC is two models, five states, four actors' worth of rules and
eight routes. Roughly 20% of the generated lines survived, but the 20% is the part that is
tedious to get right (registration, loader paths, admin wiring, permission dependency), which
is the point: the generator removes the boilerplate, not the thinking.

### Decisions made without being told

- `escalated → in_review` ("resume") requires `kyc.approve`, not `kyc.review`. The brief says
  "by a reviewer"; an analyst who could pull a case back out of escalation would defeat the
  escalation. Resuming also assigns the case to the actor.
- Maker/checker is enforced against `assigned_to` at decision time, so the block is escapable by
  releasing the case and having someone else claim it — that is intended (release is itself
  audited), but it means the control is "two humans touched this", not "the maker can never
  decide". Worth saying out loud to the VP.
- Superusers bypass permission checks (platform behaviour) but **not** maker/checker: the
  assignee rule is a domain rule in the service, not a permission. A superuser assigned to a case
  still cannot decide it.
- Decision reason minimum is 10 characters, per the brief; whitespace is stripped first so
  `"          "` is rejected.
- `/audit` gained an optional `entity_id` filter (`list_audit_events`) so the case detail page can
  show only that case's chain without a second query path.
- Seeded decided cases record `decided_by` as the seeded reviewer, so the detail page of an
  already-approved case is not missing its decider.

### For a security reviewer

- Every transition writes the audit row in the same transaction as the state change
  (`commit=False` on the CRUD write, then `audit.record`, then one `db.commit()`), so there is no
  window where a case moves without an audit entry.
- Action buttons are rendered from `service.allowed_actions()`, the same function the service
  checks against — but the service re-validates on POST, so a hand-crafted POST cannot bypass
  permission, state or maker/checker rules. The tests assert the service, not the template.
- `assigned_to`/`decided_by` are `ON DELETE SET NULL`: deleting a user blanks the attribution on
  their cases. The audit trail keeps `actor_user_id`, so history survives, but the case row alone
  will no longer say who decided it.

### Time / what took longer than expected

- About 90 minutes end to end. The only real surprise: `KycCaseCreate.submitted_at` defaulted to
  `None` and FastCRUD passes the whole dict through, so the model-level `default_factory` never
  fired and every insert hit a NOT NULL violation. Defaulting in the schema, not the model, is the
  rule here.

## Session 3 — feature flags (branch `tool/flags`)

### Elapsed time

Being blunt, because the brief says this number matters: the only clock I can measure honestly is
the VM's, and it pauses between turns, so it undercounts. Machine-awake time from the
`bp new tool flags` run to opening the PR was **~7 minutes** (worktree file timestamps 20:08–20:15)
— that is compute time, not the user-visible wall time, which was longer and dominated by waiting
on me between turns rather than by the work. What I can say without hedging: the flags tool was
one uninterrupted work stretch with no rework and no design decisions of consequence, versus the
KYC tool's several. Roughly: generator + domain, then service/UI, then the API-key dependency and
evaluate endpoint, then migration + seed + a manual end-to-end run, then tests and lint.

### Generator retention

Kept the generated `tool.py`, `crud.py`, `admin.py`, the router's permission wiring and template
scaffolding, and the test file's fixtures. Rewrote `models.py`, `schemas.py`, `service.py` and the
templates for the real domain, and deleted the generated `detail.html`/`_row.html` — flags have no
detail page; the table is the whole UI.

### API-key request authentication (closes a pre-existing gap)

The boilerplate shipped `APIKeyService.validate_api_key` but nothing that authenticates a request
with an `fai_…` key: API keys were management-only. `require_api_key(resource, action)` in
`backend/src/modules/api_keys/dependencies.py` closes that, reading the `X-API-Key` header via
`APIKeyHeader(auto_error=False)` so the 401 body is ours. It is applied to exactly one route,
`GET /api/v1/flags/evaluate`, per the brief.

For a security reviewer:

- The evaluate endpoint requires a `*`/`read` key. There is no per-flag or per-tool scoping; any
  valid read key can evaluate any flag. Flag keys and rollout percentages are not secret, but that
  is an assumption, not an enforced boundary.
- `validate_api_key` updates `last_used_at` on every call, so each evaluation is a write. Fine at
  internal-tool volume; it would need batching if services poll this endpoint hot.
- The dependency does not rate-limit. Per the brief internal routes do not get rate limiting, but
  this one is reachable by anything holding a key, not just a logged-in human — it is the one route
  in the repo where I would add a limit before exposing it outside the VPC.
- No API-key auth is applied anywhere else, deliberately. Session auth still guards the UI routes.

### Decisions made without being told

- Rollout bucketing is `sha256(f"{key}:{subject}")`, first 4 bytes mod 100. Including the key means
  a subject is not in the same bucket for every flag (otherwise the same unlucky 10% of users get
  every partial rollout). Deterministic and stable across processes — no `hash()`, which is salted.
- `rollout_percent` is validated 0–100 in the Pydantic schemas and by a DB CHECK constraint
  (`ck_feature_flag_rollout_percent`). The schema check is the friendly error; the constraint is
  there because SQLAdmin and psql write to this table without going through the schemas.
- Unknown flag keys return the repo's generic 404 error envelope rather than an
  `{enabled: false}` body. A typo'd key should be loud, not silently false.
- The SQLAdmin view for flags has `can_create = False`: creating a flag without going through the
  service would skip the audit entry. Editing and deleting are still possible there and are *not*
  audited — same hole the platform's admin surface has generally, noted in session 1.
- The seed prints the plaintext API key once and nowhere else; it is not committed and not stored
  in recoverable form.

### Review follow-ups (same session)

- `update_flag` and `toggle_flag` now read the row with `SELECT ... FOR UPDATE` before deciding what
  to write. A toggle is a read-modify-write; two concurrent toggles both read the old value and
  write the same inverse, so one is silently lost.
- `create_flag` keeps the `exists` pre-check for the friendly message but also catches the unique
  violation, so a race returns "already exists" instead of a 500.
- `updated_at` is set by the model (`onupdate`), which covers SQLAdmin edits too, rather than by
  each service function.
- The permission gate for SQLAdmin views moved from `interfaces/admin/views/platform.py` to
  `modules/platform/admin.py` so tool modules can mix it in without importing an interface layer.
  `FlagAdmin` declared `required_permission` but did not inherit the gate, so it was inert; the
  generator template had the same hole and now emits the mixin.
- The seeded API key prints to stdout rather than through the logger, so a live credential does not
  end up in aggregated application logs.

## Session 4 — security review and hardening

Full write-up in `SECURITY-REVIEW.md`; this records the decisions I made without being told.

- **Login CSRF.** crudauth's synchronizer token only covers requests that already have a session, so
  the two login forms were unprotected. I added a small `SameOriginMiddleware` rather than adding a
  pre-session token to both forms: it is ~20 lines, it covers the SQLAdmin login form (which I do not
  own), and requests with no `Origin` (curl, service callers) are left to route authentication. If
  you later front this with something that rewrites `Host`, that middleware's same-origin comparison
  depends on `Host` being trustworthy.
- **CSP and `/admin`.** SQLAdmin's own templates carry inline script and style, so a single strict
  policy would break the admin UI. Rather than weaken the whole app I select a looser policy on the
  `/admin` prefix only. If SQLAdmin ever moves behind a different prefix, that check moves with it.
- **Production validator now blocks startup** for `CSRF_ENABLED=false`, `SESSION_SECURE_COOKIES=false`
  and a non-Redis session backend. This is a behaviour change: a production deployment that was
  running with those settings will now refuse to boot. That is the point, but it will be a surprise.
  I rewrote the existing test that asserted these were warnings.
- **Login/logout are now audited.** Not asked for, but a KYC trail that cannot answer "who was logged
  in" is half a trail. Failed logins are recorded with a digest of the submitted identifier, never
  the identifier itself — people type passwords into username fields.
- **API keys die with their owner.** `validate_api_key` now rejects keys whose owner is soft-deleted.
  Offboarding previously left the only non-session auth path alive.
- **Not fixed, deliberately** (all in the report with reasoning): SQLAdmin's permission snapshot is
  stale for up to the session timeout; SQLAdmin writes bypass the audit trail; the evaluate endpoint
  has no rate limit; API key scope is wildcard/read rather than per-endpoint. Each is a design
  boundary rather than a bug, and fixing them properly is bigger than this pass.
- **Took longer than expected:** working out which CSRF defences crudauth already provides versus what
  the browser-facing routes added in session 1 needed on top. Most of the review time went into
  reading, not writing; the code changes are small on purpose.
