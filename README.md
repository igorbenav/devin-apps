<h1 align="center">Fastro · The Benav Labs FastAPI Boilerplate</h1>
<p align="center" markdown=1>
  <i><b>Batteries-included FastAPI starter</b> - vertical-slice modules, swappable infrastructure, plugin-ready CLI.</i>
</p>

<p align="center">
  <a href="https://benavlabs.github.io/FastAPI-boilerplate">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/assets/fastro-cover-dark.png">
      <img src="docs/assets/fastro-cover-light.png" alt="Fastro - open-source FastAPI boilerplate with auth, CRUD, jobs, caching and rate-limits" width="100%">
    </picture>
  </a>
</p>

<p align="center">
<a href="https://benavlabs.github.io/FastAPI-boilerplate/">Docs</a> · <a href="https://deepwiki.com/benavlabs/FastAPI-boilerplate">DeepWiki</a> · <a href="https://discord.com/invite/TEmPs22gqB">Discord</a>
</p>

<p align="center">
  <a href="https://fastapi.tiangolo.com">
      <img src="https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi" alt="FastAPI">
  </a>
  <a href="https://www.postgresql.org">
      <img src="https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  </a>
  <a href="https://redis.io">
      <img src="https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=fff&style=for-the-badge" alt="Redis">
  </a>
  <a href="https://deepwiki.com/benavlabs/FastAPI-boilerplate">
      <img src="https://img.shields.io/badge/DeepWiki-1F2937?style=for-the-badge&logoColor=white" alt="DeepWiki">
  </a>
</p>

<p align="center" markdown=1>
  <i>The free, open-source FastAPI foundation. Building a <b>SaaS</b> - AI or not? <a href="https://fastro.ai">FastroAI</a> adds payments, entitlements, email &amp; a frontend (plus AI) on top - <a href="#fastro-vs-fastroai">compare&nbsp;↓</a></i>
</p>

## Internal tools platform

This fork is an **internal tools platform**: the things a low-code suite like Power Apps gives
you once for every app — login, roles and permissions, an audit trail, an admin surface, an app
launcher — live once in `backend/src/modules/platform/`, and each internal tool is a
vertical-slice module under `backend/src/modules/tools/<slug>/` that plugs into it. **One repo,
one deployable app**: tools are never separate repos or separate deployments, because the whole
value proposition is that the tenth tool costs a fraction of the first — shared auth, shared
audit, one migration history, one compose file, one thing to operate. UI is server-rendered
Jinja2 + HTMX (vendored locally, no CDN, no build step). To add a tool, run
`uv run bp new tool <slug> --label "<Label>" --permission <perm>` and follow
[PLAYBOOK.md](PLAYBOOK.md).

### Run it

```bash
uv sync --all-packages --all-extras
uv run bp deploy generate local
cp backend/.env.example backend/.env && uv run bp env gen-secret   # paste into SECRET_KEY
echo 'CREATE_TABLES_ON_STARTUP=false' >> backend/.env                # Alembic owns the schema
docker compose up --build

# in another terminal: migrate, then seed roles + demo users
docker compose exec api sh -c "alembic upgrade head && python -m scripts.setup_initial_data"
```

The single migration in `backend/migrations/versions/` is the baseline schema (the boilerplate
ships none, creating tables from the models at startup instead), so it must run against an empty
database with `CREATE_TABLES_ON_STARTUP=false`.

Then open <http://127.0.0.1:8000/> — the launcher (login required), `/audit` for the audit log
(needs `audit.read`), `/admin` for SQLAdmin (needs `platform.admin` or superuser).

### Seeded demo users

`scripts/setup_initial_data.py` creates the three roles and one obvious user per role, printing
the credentials when it finishes. **Development demo credentials only — never seed these in a
real environment.** Override the password with `DEMO_USER_PASSWORD`.

| User         | Role     | Password    | Permissions                                              |
| ------------ | -------- | ----------- | -------------------------------------------------------- |
| `analyst`    | analyst  | `Demo1234!` | `kyc.review`, `flags.read`                               |
| `reviewer`   | reviewer | `Demo1234!` | analyst + `kyc.approve`, `kyc.escalate`                  |
| `toolsadmin` | admin    | `Demo1234!` | all, incl. `flags.write`, `audit.read`, `platform.admin` |

Permissions are flat dotted strings on a role, with no hierarchy. Superusers pass every check.

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

## Features

- Fully async FastAPI + SQLAlchemy 2.0
- Pydantic v2 models & validation
- Server-side sessions + CSRF via [crudauth](https://pypi.org/project/crudauth/); OAuth (Google wired); API keys
- Annotated type aliases for all FastAPI dependencies
- Rate limiter with per-tier, per-path rules
- FastCRUD for efficient CRUD & pagination
- **SQLAdmin**-based admin panel (optional, env-toggled)
- [Taskiq](https://taskiq-python.github.io/) workers (Redis or RabbitMQ broker)
- Redis or Memcached caching (`@cache` decorator + provider API)
- **Plugin-ready `bp` CLI** - generate compose files, audit env, mount third-party command/feature plugins
- Docker Compose for local / prod / nginx-fronted (generated by the CLI)
- Runs on any Postgres - the bundled container, or serverless via [Neon](https://neon.com) ([guide](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/database/neon/))

## Why and When to use it

**Perfect if you want:**

- A pragmatic starter with auth, CRUD, jobs, caching and rate-limits
- **Sensible defaults** with the freedom to opt-out of modules
- **A foundation that grows** - vertical-slice modules + a plugin-aware CLI for code generators
- **Docs over boilerplate** in this README - depth lives on the [docs site](https://benavlabs.github.io/FastAPI-boilerplate/)

> **Not a fit** if you need a monorepo microservices scaffold - [see the docs](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/project-structure/) for pointers.

**What you get:**

- **App**: FastAPI [app factory](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/project-structure/), env-aware docs exposure
- **Auth**: [server-side sessions](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/authentication/sessions/), CSRF, [OAuth](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/authentication/), [API keys](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/authentication/permissions/)
- **DB**: Postgres + SQLAlchemy 2.0, [Alembic migrations](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/database/migrations/) with prod-confirm gate - local container or serverless ([Neon](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/database/neon/))
- **CRUD**: [FastCRUD generics](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/database/crud/)
- **Caching**: [decorator + provider API](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/caching/) (Redis or Memcached)
- **Queues**: [Taskiq workers](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/background-tasks/) (Redis or RabbitMQ)
- **Rate limits**: [per-tier + per-path rules](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/rate-limiting/)
- **Admin**: [SQLAdmin views](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/admin-panel/) (optional, env-toggled)
- **CLI**: [`bp` tool](https://benavlabs.github.io/FastAPI-boilerplate/cli/) for compose scaffolding, env audits, and plugin extensions

## Fastro vs FastroAI

This boilerplate - **Fastro** - is the free, open-source **foundation**: everything you need for a production FastAPI backend. **[FastroAI](https://fastro.ai)** is the paid template built on the same foundation for shipping a **complete SaaS** - Stripe billing (subscriptions, credits, discounts), entitlements, transactional email, and a frontend, all wired together. Building an **AI** product? The PydanticAI agent layer is included too - but every paid feature fits a regular SaaS just as well.

|                                                                    | **Fastro** (this repo · free) |     **FastroAI** (paid)     |
| ------------------------------------------------------------------ | :---------------------------: | :-------------------------: |
| FastAPI + SQLAlchemy 2.0, Pydantic v2                              |               ✓               |              ✓              |
| Auth - sessions, OAuth, API keys                                   |               ✓               |         ✓ **+ JWT**         |
| FastCRUD · SQLAdmin · Alembic                                      |               ✓               |              ✓              |
| Caching · rate limiting · Taskiq jobs                              |               ✓               |              ✓              |
| Docker (local / prod / nginx)                                      |               ✓               |              ✓              |
| `bp` CLI - scaffolding, env audit, plugins                         |               ✓               |                             |
| **Payments** - Stripe: subscriptions, credits, discounts, webhooks |                               |              ✓              |
| **Entitlements** - feature gating by plan/tier                     |                               |              ✓              |
| **Transactional email** & notifications                            |                               |              ✓              |
| **Frontend** - Astro landing / marketing site                      |                               |              ✓              |
| **Observability** - Logfire tracing & metrics                      |                               |              ✓              |
| **AI agents** - PydanticAI: memory, tools, usage tracking          |                               |              ✓              |
| Support                                                            |      Community · Discord      | Priority · lifetime updates |

<p align="center">
  <a href="https://fastro.ai">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/assets/fastroai-card-dark.png">
      <img src="docs/assets/fastroai-card-light.png" alt="FastroAI - the complete SaaS template: payments, entitlements, email, frontend and AI on top of Fastro" width="100%">
    </picture>
  </a>
</p>

**Stick with Fastro** if you want a clean, hackable FastAPI backend to build on.
**[Get FastroAI →](https://fastro.ai)** if you're shipping a SaaS - AI or not - and want billing, entitlements, email, auth, and a frontend ready out of the box.

## Repo Layout

This is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with two members. One venv at the root covers both.

```text
fastapi-boilerplate/
├── pyproject.toml          # workspace root (uv workspace metadata)
├── backend/                # the deployable application
│   ├── src/                # interfaces/, infrastructure/, modules/
│   ├── pyproject.toml
│   └── Dockerfile          # multi-stage: dev / migrate / prod
└── cli/                    # `bp` - developer/operator tool (never ships in prod)
    └── src/cli/
```

## Quickstart

```bash
git clone https://github.com/<you>/FastAPI-boilerplate
cd FastAPI-boilerplate
uv sync --all-packages --all-extras           # one venv at the root, both members installed
```

Generate a compose file for the deployment shape you want:

```bash
uv run bp deploy generate local               # hot-reload dev stack
# or: uv run bp deploy generate prod          # production single-host
# or: uv run bp deploy generate nginx         # production behind nginx
```

Configure your env (the CLI helps with secrets and validation):

```bash
cp backend/.env.example backend/.env
uv run bp env gen-secret                      # print a fresh SECRET_KEY
uv run bp env validate                        # audit .env against the production validator
```

Bring it up:

```bash
docker compose up --build
# → http://127.0.0.1:8000  (Swagger at /docs)
```

**Without Docker** (Postgres + Redis required locally - or skip local Postgres with [Neon](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/database/neon/)):

```bash
cd backend
uv run alembic upgrade head
uv run python -m scripts.setup_initial_data   # creates the first admin user + default tier
uv run fastapi dev src/interfaces/main.py     # API
uv run taskiq worker infrastructure.taskiq.worker:default_broker  # in a second terminal
```

> Full setup, env-var reference, and per-environment deployment guides live in the [docs](https://benavlabs.github.io/FastAPI-boilerplate/getting-started/installation/).

## Common tasks

```bash
# generate a fresh production-ready compose file
uv run bp deploy generate prod --workers 8

# audit your .env against the production security validator
uv run bp env validate

# run Alembic migrations
cd backend && uv run alembic revision --autogenerate -m "<msg>" && uv run alembic upgrade head

# run tests
cd backend && uv run pytest

# install bp as a global tool (optional)
uv tool install --editable ./cli
```

More examples (superuser creation, tiers, rate limits, admin usage, plugin authoring) in the [docs](https://benavlabs.github.io/FastAPI-boilerplate/).

## Sponsors

<a href="https://neon.com"><img src="https://img.shields.io/badge/Neon-00E599?style=for-the-badge&logo=postgresql&logoColor=black" alt="Neon"></a>

**[Neon](https://neon.com)** supports this project with database credits for our open-source infrastructure - thank you. Neon is serverless Postgres: compute scales to zero when idle, and you can branch a database like you branch code (handy for per-PR preview environments).

It's also a drop-in option for your own build, and **free to start** - the free plan is permanent rather than a trial (no credit card), with enough storage and compute for dev, staging, and small production workloads. Point `DATABASE_URL` at a Neon project and the local Postgres container becomes optional - no code changes:

```env
DATABASE_URL=postgresql+asyncpg://user:password@ep-xxx-pooler.region.aws.neon.tech/neondb?ssl=require
```

→ [Full Neon guide](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/database/neon/) (connection-string conversion, pooled vs. direct endpoints, scale-to-zero pool settings). Any other managed Postgres works the same way.

## Contributing

Read [contributing](CONTRIBUTING.md).

## References

This project was inspired by a few projects, it's based on them with things changed to the way I like (and pydantic, sqlalchemy updated)

- [`Full Stack FastAPI and PostgreSQL`](https://github.com/tiangolo/full-stack-fastapi-postgresql) by @tiangolo himself
- [`FastAPI Microservices`](https://github.com/Kludex/fastapi-microservices) by @kludex which heavily inspired this boilerplate
- [`Async Web API with FastAPI + SQLAlchemy 2.0`](https://github.com/rhoboro/async-fastapi-sqlalchemy) for sqlalchemy 2.0 ORM examples
- [`FastaAPI Rocket Boilerplate`](https://github.com/asacristani/fastapi-rocket-boilerplate/tree/main) for docker compose

## License

[`MIT`](LICENSE.md)

## Contact

Benav Labs – [benav.io](https://benav.io), [discord server](https://discord.com/invite/TEmPs22gqB)

<hr>
<a href="https://benav.io">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/benav-labs-banner-dark.png">
    <img src="docs/assets/benav-labs-banner-light.png" alt="Benav Labs - benav.io" width="100%"/>
  </picture>
</a>
