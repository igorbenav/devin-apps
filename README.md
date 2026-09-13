# Internal tools platform

An internal-tools platform you own: the things a low-code suite like Power Apps gives you once
for every app — login, roles and permissions, an audit trail, an admin back office, an app
launcher — live once here, and each tool is a small module that plugs into them.

**One repo, one deployable FastAPI app.** Tools are never separate repos or separate
deployments, because the whole point is that the tenth tool costs a fraction of the first:
shared auth, shared audit, one migration history, one compose file, one thing to operate.
The UI is server-rendered Jinja2 + HTMX — vendored locally, no CDN, no build step, no frontend
to deploy.

Three tools ship as worked examples:

| Tool                             | Permission to open | What it demonstrates                                                                                                        |
| -------------------------------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| KYC Review Queue (`/tools/kyc`)  | `kyc.review`       | A real workflow: claim → approve/reject/escalate with maker/checker separation, mandatory reasons, every transition audited |
| Feature Flags (`/tools/flags`)   | `flags.read`       | The cheap CRUD tool, plus an API-key-authenticated `GET /api/v1/flags/evaluate` for services                                |
| Request a tool (`/tools/intake`) | `tools.request`    | A requester describes a tool; the app starts a Devin session from the brief and a human merges the PR                       |

## Run it locally

```bash
uv sync --all-packages --all-extras
uv run bp deploy generate local
cp backend/.env.example backend/.env && uv run bp env gen-secret   # paste into SECRET_KEY
echo 'CREATE_TABLES_ON_STARTUP=false' >> backend/.env              # Alembic owns the schema
docker compose up -d --build

# migrate, then seed roles, demo users and demo data, from inside the running container
docker compose exec -w /app api sh -c "alembic upgrade head && python -m scripts.setup_initial_data"
```

Open <http://127.0.0.1:8000/> — the launcher (login required) shows only the tools you hold the
permission for. `/audit` is the audit log (`audit.read`), `/admin` is SQLAdmin
(`platform.admin` or superuser).

For a real deployment — production env file, migrations as a one-shot container, the preflight
check, upgrades and rollback — follow [DEPLOY.md](DEPLOY.md). It is written to be executable by
a Devin session, and everything it cannot invent (host, DNS, TLS, secrets) is called out.

### Seeded demo users

`scripts/setup_initial_data.py` creates the roles and one obvious user per role, printing the
credentials when it finishes. **Development demo credentials only — never seed these in a real
environment**; production role sync runs without them (`python -m scripts.sync_roles`). Override
the password with `DEMO_USER_PASSWORD`.

| User         | Role     | Password    | Permissions                                              |
| ------------ | -------- | ----------- | -------------------------------------------------------- |
| `analyst`    | analyst  | `Demo1234!` | `kyc.review`, `flags.read`                               |
| `reviewer`   | reviewer | `Demo1234!` | analyst + `kyc.approve`, `kyc.escalate`, `tools.request` |
| `toolsadmin` | admin    | `Demo1234!` | all, incl. `flags.write`, `audit.read`, `platform.admin` |

Permissions are flat dotted strings on a role, with no hierarchy and no implication: holding
`kyc.approve` does not grant `kyc.review`. Superusers pass every check.

## Adding a tool

```bash
uv run bp new tool refunds --label "Refunds" --permission refunds.read
```

That generates the whole module; then you write the domain. Follow
[PLAYBOOK.md](PLAYBOOK.md) — it is the step-by-step a Devin session (or a new engineer) works
from, including the tests and the definition of done.

A tool is one directory that owns everything it contributes:

```text
backend/src/modules/tools/<slug>/
  models.py schemas.py crud.py service.py   domain
  permissions.py                            the permission strings this tool owns
  router.py  templates/<slug>/*.html        pages
  api.py                                    optional JSON API under /api/v1
  admin.py                                  optional SQLAdmin views
  seed.py                                   optional demo data
  tests/                                    unit tests, next to the code
  tool.py                                   the manifest that registers all of the above
```

Registration is the manifest and nothing else: the platform collects pages, API routers, admin
views, permissions and seeds from each `ToolSpec` at startup, so adding a tool edits no shared
file except which seeded role gets the new permission. Tools reach the platform through one
façade, `src.platform_sdk`, and `lint-imports` enforces that — no tool imports another tool, and
the platform never imports a tool. The reasoning, and what this looks like at 50 tools, is in
[ARCHITECTURE.md](ARCHITECTURE.md).

## What the platform gives every tool

- **Login and sessions** — server-side sessions, CSRF, login lockout; Google OAuth wired
  (swapping in Entra ID/OIDC is a provider class plus config, see below)
- **Roles and permissions** — `require_permission` for routes, `current_permissions` for
  templates so a button is only rendered when the action is actually allowed
- **Audit trail** — append-only `audit.record` with actor, entity, before/after and reason,
  readable at `/audit`; admin writes are audited too
- **Launcher** — the home page, listing the tools the current user may open
- **Admin** — SQLAdmin, permission-gated, for the back-office cases a tool page shouldn't grow
- **Shared shell** — base templates, CSS, HTMX conventions, inline HTML errors, a
  "Report an issue" link on every page
- **Infrastructure** — Postgres + SQLAlchemy 2.0 async, Alembic, Redis cache/sessions, Taskiq
  workers, rate limiting, API keys, the `bp` CLI for compose/env/generators

## Using Devin to run it

The platform is designed to be operated by Devin sessions as much as by people:
[DEVIN-OPERATING-MODEL.md](DEVIN-OPERATING-MODEL.md) covers the playbooks, repo knowledge,
automations (issue-label intake, CI-failure fixes, dependency sweeps), Devin Review and code
scans, plus per-tool session tags and ACU caps so cost is attributable per tool. `/tools/intake`
is the in-app version of that: a ten-question brief becomes a `POST /v1/sessions` call against
the add-a-tool playbook. With no `DEVIN_API_KEY` configured it stores the brief and shows the
prompt to copy instead of pretending a session started. A human always reviews and merges.

## Security

[SECURITY.md](SECURITY.md) is the security model — the controls in place, what the operator has to
get right, and the residual risk that was accepted and why. Production startup refuses to run on an unsafe configuration (weak
`SECRET_KEY`, `CSRF_ENABLED=false`, insecure session cookies, a non-Redis session backend,
wildcard CORS with credentials), and `python -m scripts.preflight` checks the same rules plus the
database revision and Redis before you move traffic.

### Swapping Google OAuth for Entra ID / OIDC

Google OAuth is wired today (`backend/src/infrastructure/auth/`, authorization-code + PKCE with
state in session storage). Entra ID is the same OIDC flow with different endpoints, so a swap is
configuration plus one provider class, not an architecture change: add
`MICROSOFT_CLIENT_ID`/`MICROSOFT_CLIENT_SECRET`/`MICROSOFT_TENANT_ID` to the settings mixin,
point the provider at
`https://login.microsoftonline.com/<tenant>/oauth2/v2.0/{authorize,token}` with scopes
`openid profile email`, verify the ID token against that tenant's JWKS, and map the `oid` (not
`email`) claim to the local user — `oid` is the stable per-tenant user identifier. Everything
downstream (session creation, roles, audit) is provider-agnostic and needs no changes; group
claims could later be mapped onto platform roles in the same callback. Not implemented here.

## Repo layout

A [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with two members; one
venv at the root covers both.

```text
├── backend/                      # the deployable application
│   ├── src/
│   │   ├── interfaces/           # FastAPI app, HTTP routes, SQLAdmin wiring
│   │   ├── infrastructure/       # config, auth, db, cache, taskiq, deploy preflight
│   │   ├── modules/platform/     # roles, permissions, audit, registry, launcher
│   │   ├── modules/tools/<slug>/ # one directory per internal tool
│   │   └── platform_sdk/         # the only surface tools may import
│   ├── migrations/               # Alembic, one linear history for the whole app
│   ├── scripts/                  # setup_initial_data, sync_roles, preflight, superuser
│   └── Dockerfile                # multi-stage: dev / migrate / prod
└── cli/                          # `bp` - developer/operator tool, never ships in prod
```

## Common tasks

```bash
cd backend
uv run --no-sync pytest tests/unit src/modules -q   # unit tests, including the per-tool ones
uv run --no-sync mypy src
uv run --no-sync lint-imports                       # layering + tool independence contracts
uv run alembic revision --autogenerate -m "<msg>"

cd ..
uv run --no-sync ruff check backend cli
uv run bp env validate                              # audit .env against the production validator
uv run bp deploy generate prod --workers 8
```

## Documentation

| Document                                             | What it is for                                                            |
| ---------------------------------------------------- | ------------------------------------------------------------------------- |
| [PLAYBOOK.md](PLAYBOOK.md)                           | How to add a tool, step by step — the file a Devin session is pointed at  |
| [DEPLOY.md](DEPLOY.md)                               | The deployment runbook: env, migrations, preflight, upgrades, rollback    |
| [ARCHITECTURE.md](ARCHITECTURE.md)                   | How the repo is organised, the tool contract, and the invariants          |
| [UX.md](UX.md)                                       | Personas, jobs to be done, and the shared UX contract tools must follow   |
| [SECURITY.md](SECURITY.md)                           | The security model: controls, operator duties, accepted risk              |
| [DEVIN-OPERATING-MODEL.md](DEVIN-OPERATING-MODEL.md) | Playbooks, knowledge, automations and reviews for running this with Devin |

## Upstream

This is a fork of [Fastro](https://github.com/benavlabs/FastAPI-boilerplate), the Benav Labs
FastAPI boilerplate, which supplies the FastAPI/SQLAlchemy/Alembic foundation, the auth and
caching infrastructure and the `bp` CLI. Everything under `modules/platform/`, `modules/tools/`
and `platform_sdk/`, and the documents listed above, are this fork.

## License

[`MIT`](LICENSE.md)
