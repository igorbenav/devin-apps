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

## Session 4b — closing the four deferred security items

All four of the "not fixed, deliberately" items above are now closed; `SECURITY-REVIEW.md` §1 rows
13–18 have the detail. Decisions I made without being told:

- **Admin permission freshness** is re-resolved in `AdminAuth.authenticate`, which runs on every
  admin request, rather than in `is_accessible` (sync, cannot query). That is one DB round trip per
  admin page load, which is fine for an internal admin surface and is the only place SQLAdmin gives
  an async hook. A session with no `user_id` is the break-glass admin and is left alone.
- **Admin auditing is best-effort, not atomic.** SQLAdmin commits and then calls the `after_*` hooks,
  so the audit row is a second transaction. I did not fight SQLAdmin's session handling for this;
  the mixin's docstring and the report say so plainly rather than implying admin writes are as
  trustworthy as service-layer writes.
- **The rate limiter buckets by API key id**, not by the shipped `check_rate_limit` (session user or
  client IP, plus tier lookup): every service caller behind a cluster egress shares one IP, so the
  shipped limiter would throttle all of them together. 600/min is a guess sized for polling clients;
  no requirement was given.
- **Wildcard API keys still reach the evaluate route** because `validate_api_key` falls back to
  `*:read`. I did not remove that fallback — it is repo behaviour that other (future) keys rely on —
  but the seeded key is now `feature_flags:read` and the report says wildcard keys should be revoked.
- **Adding the enum value needed a migration** (`c41ab0d7e5f2`); its downgrade is empty because
  Postgres cannot drop an enum value safely.
- **Devin Review findings from the first security PR are also fixed here**: the strict CSP blanked
  `/docs` (own policy for the docs paths), configured CORS origins could post the login forms (now
  `/api/` only), API/OAuth/admin sign-ins were unaudited (`record_login` takes a `method`), and an
  oversized or malformed `X-Forwarded-For` hop went into the audit row (truncated and parsed as an
  IP, else the socket address).

## Session 5 — modularity investigation (no code changes)

`MODULARITY.md` is the deliverable: what a tool has to touch outside its own directory today, four
options, a recommended target (manifest-driven `ToolSpec`, a `platform_sdk` façade, import-linter
contracts, per-tool Alembic branches, tests inside the module) and a six-step migration path.

Written up rather than implemented on purpose — it changes shared wiring in `interfaces/` and the
migration layout, and I want it confirmed before 50 tools depend on it. Two calls I would push back
on if challenged: per-tool Alembic branches are the one step I would drop first (multiple heads is a
real operational change for whoever runs deploys), and `import-linter` is a new dev dependency —
without it every layering rule in the document is a convention that decays.

## Session 6 — implementing the modular tool contract

Steps 1–5 of `MODULARITY.md` plus tests-in-modules and the generator. The shape: `ToolSpec` now
carries `pages`, `api`/`api_prefix`, `admin_views`, `permissions` and `seed`, and the platform
collects them (`include_tool_api_routers`, `register_tool_admin_views`, `permission_catalog`,
`run_tool_seeds`). `interfaces/api/v1/__init__.py` and `interfaces/admin/views/__init__.py` no
longer name a tool; `src/platform_sdk/` is the one import surface a tool is allowed to use, and
`import-linter` enforces layering, tool independence and "tools never import `interfaces`".

Decisions I made without being told:

- **Declaring a permission does not grant it.** A tool owns its permission strings, and the
  catalog is collected from the manifests, but which seeded role holds a new permission stays in
  `ROLE_GRANTS`. `admin` gets the whole catalog; analyst/reviewer are an explicit edit. Silently
  widening a role from a tool directory is the failure mode I did not want at 50 tools.
- **`platform_sdk` re-exports six things no tool uses yet** (`require_permission`,
  `CurrentPermissionsDep`, `PermissionDeniedError`, `actor_id`, `jsonable`, `snapshot`). They are
  the contract for cases the two current tools happen not to hit; the alternative is a tool author
  reaching into `modules.platform` the first time they need one, which is what the façade exists
  to prevent.
- **Routers read their slug from `permissions.py`, not from `SPEC`.** `tool.py` imports the router,
  so a router that imports `SPEC` is a cycle; page handlers call `get_tool(SLUG)` at request time.
  The generator templates do the same, so nobody rediscovers this.
- **One `ignore_imports` in the layering contract**: `infrastructure.auth.routes -> modules.platform.service`, because CRUDAuth owns the login route and login auditing lives in the
  platform. Fixing it properly means an event hook in the auth layer — worth doing, out of scope
  here, and now visible in config instead of invisible in the import graph.
- **Per-tool Alembic branches are deliberately not in this PR.** They put `alembic upgrade heads`
  in the deploy runbook and nobody confirmed that trade; migrations stay one linear chain.
- **`run_tool_seeds` runs seeds serially on one session** and each existing seed commits its own
  work, so a later failure does not roll back an earlier tool's demo data. Fine for demo seeding.

New dev dependency: `import-linter` (wired into pre-commit and the lint workflow). Without it
every rule above is a convention that decays; that is the whole justification.

Found while verifying, unrelated to this refactor: migration `c41ab0d7e5f2` added the *value*
`feature_flags` to the `keypermissionresource` enum, but the column stores member *names*, so
seeding the flag-evaluation key against a migrated database failed with `invalid input value for enum`. Fixed in `d2f0c31a77b4`. It never showed up before because the seeded key was created
against a database built by `CREATE_TABLES_ON_STARTUP`.

Proof the generator still works end to end: `bp new tool example --label Example --permission example.use` → migration autogenerated and applied → its four generated tests pass → module and
migration deleted. Roughly four hours of work; most of it went into the circular-import fallout
from moving permissions and seeds into the modules, not into the collection loops.

## UX pass: personas, jobs to be done, and what the shared layer should own

`UX.md` is analysis, not code. Decisions and guesses worth flagging:

- **The Devin session is treated as a persona**, alongside operator, requester and admin. That is a
  deliberate framing choice: at fifty tools, most UI decisions are made by a builder repeating a
  default, so the defaults are the product.
- **The gap list is grounded in the templates at `eaf283c`**, not imagined. No responsive CSS (zero
  media queries in `platform.css`), no busy/loading state on any `hx-post`, page-level 403s render
  as JSON, `/audit` caps at 200 events with an entity-type filter that is not in the URL, and every
  table is hand-rolled per tool.
- **Priorities are frequency-weighted**, so "an action shows it is running" outranks anything on the
  admin side. I have no telemetry — frequencies are estimates from the domain (a KYC analyst
  clearing a queue) and should be checked with the customer's ops team before slice B is built.
- **Guesses I could not resolve**: whether operators live in the tool all day (decides keyboard vs
  guidance), whether phones matter, whether whoever grants access will tolerate SQLAdmin, and
  whether read-only viewers outside ops are needed. All listed as open questions rather than
  answered silently.
- **Sizing is in Devin sessions, not calendar time**, and slices A/B/G are called out as the
  compounding ones. Nothing here was implemented; the next session should pick slices, not the
  whole list.

## Devin operating model (which product features to actually turn on)

`DEVIN-OPERATING-MODEL.md` is the other half of the UX work: configuration and one buildable
feature, not screens. Notes on it:

- **Feature claims were checked against the Devin docs, not recalled.** Automations (GitHub issue /
  issue-comment / check-run / schedule triggers, with narrow conditions), playbooks, repo-pinned
  knowledge, Devin Review + Auto-Fix, code scans, session tags and `max_acu_limit`, and
  `POST /v1/sessions` with `playbook_id`/`tags` all exist as described. Anything I could not verify
  is not in the document.
- **Mobile dropped from v1** at the customer's instruction; `UX.md` still lists it as P3 so the
  decision is visible rather than lost.
- **The one thing worth building is the in-app intake** (tool-request form → Devin API session,
  report-issue button → labelled GitHub issue → automation). It is the only piece that answers
  "can an ops lead get a tool without filing a ticket with the platform team", which is the actual
  Power Apps value proposition. Flagged as needing a server-side API key, a `tools.request`
  permission and a rate limit — it is the one endpoint in the app that spends money.
- **Per-tool session tagging is called out as a day-one decision** because cost per tool cannot be
  reconstructed retroactively, and it is the number that decides whether this was worth it.
- **The honest-limits section is deliberately blunt**: latency versus a WYSIWYG editor, no end-user
  editing, no connector ecosystem, a human still merges, variable cost instead of a licence, and
  the fact that maintenance of the shared layer becomes the customer's liability.

## In-app tool intake and report-an-issue

The one buildable piece from `DEVIN-OPERATING-MODEL.md`, now implemented as the `intake` tool
(`backend/src/modules/tools/intake/`, permission `tools.request`) plus a shared header link.
Decisions I made without being told:

- **The slug is `intake`, not `requests`.** `requests` as a module name next to the library of the
  same name is a trap for a future session reading an import out of context.
- **The brief is persisted before the API call, always.** A failed dispatch leaves a `failed`
  request with a retry button and the answers intact; nobody retypes ten questions because the API
  was down. A deployment with no `DEVIN_API_KEY` leaves the request `queued` and shows the prompt
  to copy rather than claiming a session started — the demo should not lie about what happened.
- **Five submissions per requester per rolling 24 hours** (`service.MAX_REQUESTS_PER_DAY`). This is
  the only endpoint in the app that spends money, and the limit is a business rule, so it lives in
  the service, not in the rate limiter the rest of the app deliberately does not use. Deliberately
  generous for a demo; tighten before it is real.
- **Only the status line and the HTTP status code ever reach the user on a failure.** The Devin API
  response body can echo the prompt back, and the prompt contains whatever the requester typed, so
  `devin.py` raises `DevinDispatchError("Devin API returned <status>")` and nothing else. The API
  key is read from settings at call time and is never rendered, logged or stored.
- **`tools.request.admin` exists but is granted to nobody but `admin`** (which takes the whole
  catalog). It is what lets someone see and retry another person's request; the requester
  otherwise sees only their own, enforced in the router and covered by a test.
- **`tools.request` went to the seeded `reviewer` role**, so the demo has a non-admin requester.
  Which role really owns this is a customer decision.
- **Session `title` is sent as well as `tags` and `max_acu_limit`.** Verified against the API
  reference for `POST /v1/sessions` (response is `{session_id, url, is_new_session}`), not recalled.

Flags for a security reviewer:

- The brief is attacker-controlled text that ends up inside a prompt for an agent with repo access.
  The prompt frames it as requirements from a requester, but prompt injection is not *solved* here:
  the mitigations that matter are the ACU cap, the tag, the playbook, and the fact that a human
  reviews and merges the PR. Do not remove the human merge step.
- `ISSUE_TRACKER_NEW_ISSUE_URL` defaults to this repository's issue tracker. It is a link target
  built into HTML, so point it at the customer's tracker before deploying; a wrong value leaks
  page paths and usernames to whoever owns that URL.
- Requests are readable by their requester and by `tools.request.admin`. They are business
  requirements, not secrets, but they are not scrubbed either.

Time: the module itself was quick (the generator plus the manifest contract from PR #7 meant no
shared file needed editing except the one role grant). The two things that took longest were
deciding the failure semantics above and confirming the API response shape.

### Intake, second pass (review + browser findings)

- **Two paid-session races were real.** Both are now closed in the database, not in Python:
  `submit_request` takes a transaction-scoped `pg_advisory_xact_lock` keyed by requester before it
  counts today's requests, and `dispatch_request` takes `SELECT ... FOR UPDATE` on the row before it
  reads the status. Without those, concurrent submits all read `count - 1` and two clicks on
  "Start the session" both reach the API and both spend ACUs. Postgres-specific on purpose; the app
  is Postgres-only already.
- **Slug validation now matches `bp new tool` exactly** (`^[a-z][a-z0-9_]{1,48}[a-z0-9]$`). The old
  pattern accepted hyphens the generator rejects, so the failure landed inside a paid session.
  `ToolRequestRead` relaxes the pattern so tightening it cannot make an older row unreadable.
  `submit_request` also refuses a slug an installed tool already uses, since the generator will not
  overwrite an existing module.
- **Ownership is enforced in the service, not the route.** A denied dispatch now raises
  `PermissionDeniedError` and returns no markup at all; before, the refusal rendered the foreign
  request's id and status.
- **A 2xx that is not JSON is a failed dispatch, not a 500.** Also rejects a non-object body.

### Intake, third pass: ambiguous dispatch

- **A timeout is not a failure.** The row lock stops two clicks racing, but it says nothing about a call that timed
  out after Devin accepted it: the waiter would see `failed`, retry, and pay twice. Dispatch now commits a
  `dispatching` claim *before* the HTTP call, and only `queued`/`failed` may be dispatched at all.
- **Ambiguous outcomes stay claimed.** A transport error, a 5xx, or a 2xx this client cannot parse leaves the request
  in `dispatching` with "a session may have been created; check Devin before starting another". There is no
  idempotency key on `POST /v1/sessions`, so the only honest recovery is a human looking for the `tool:<slug>` tag;
  the UI hides the retry button in that state rather than offering a second charge.
- A 4xx (bad payload, bad key) is definitive, so it stays `failed` and retryable.
