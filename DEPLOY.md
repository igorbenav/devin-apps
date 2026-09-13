# Deploying the platform

One repo, one deployable app: every tool ships in the same image and the same rollout. Adding a tool does not add a
service, a pipeline or a hostname — it adds a migration and a permission string, both handled by the steps below.

This runbook is written to be executed literally, by a person or by a Devin session, on a single Linux host with Docker
installed. Everything after "First deploy" is copy-pasteable.

## What you need before you start

| Thing                                           | Why                                                                                           | Who provides it     |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------- |
| A host with Docker + compose plugin             | Runs the stack                                                                                | you                 |
| A DNS name and TLS certificate                  | Session cookies are `Secure`; browsers will not send them over plain HTTP                     | you                 |
| `SECRET_KEY`                                    | Signs sessions and CSRF tokens                                                                | generate, see below |
| Postgres password (or a managed `DATABASE_URL`) | Data                                                                                          | you                 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD`             | The first login, before any role exists                                                       | you                 |
| `DEVIN_API_KEY` (optional)                      | Lets `/tools/intake` actually start a session; without it briefs are stored and shown to copy | you                 |

A Devin session does not have these. If you are a Devin session reading this: ask for the secrets, do not invent them,
and never write a filled-in `backend/.env` into git — it is `.gitignore`d for that reason.

## Configure

```bash
cp backend/.env.example backend/.env
uv run bp env gen-secret          # paste into SECRET_KEY
```

Then set, in `backend/.env`:

```env
ENVIRONMENT=production            # turns on startup security validation
CREATE_TABLES_ON_STARTUP=false    # Alembic owns the schema
SECRET_KEY=<the generated value>
POSTGRES_PASSWORD=<not "postgres">
POSTGRES_SERVER=postgres          # the compose service; or drop it and set DATABASE_URL
SESSION_BACKEND=redis
SESSION_SECURE_COOKIES=true
CSRF_ENABLED=true
CORS_ORIGINS=https://tools.example.com    # explicit, never *
ADMIN_USERNAME=<real admin>
ADMIN_PASSWORD=<strong password>
ADMIN_EMAIL=<real address>
ISSUE_TRACKER_NEW_ISSUE_URL=https://github.com/<org>/<repo>/issues/new
```

Managed Postgres instead of the compose one: set `DATABASE_URL` and it overrides every `POSTGRES_*` value. The async
driver spelling matters — `postgresql+asyncpg://…?ssl=require`, *not* libpq's `sslmode=require`.

`ENVIRONMENT=production` is not cosmetic. It makes the app refuse to start on a default secret key, a default database
password, `CSRF_ENABLED=false`, insecure cookies, a non-Redis session backend or wildcard CORS
(`backend/src/infrastructure/security/production_validator.py`), and it makes `create_platform_roles` refuse to seed
the demo users.

## First deploy

```bash
uv sync --all-packages --all-extras
uv run bp deploy generate prod          # or: nginx, if you want the bundled reverse proxy
docker compose build

# 1. Check the config before anything starts. Reads only; exits non-zero with a list of problems.
docker compose run --rm -w /app --no-deps api python -m scripts.preflight --config-only

# 2. Start. The `migrate` service runs `alembic upgrade head` and then `scripts.sync_roles`,
#    and the API only starts once it has exited successfully.
docker compose up -d

# 3. The first human. Uses ADMIN_USERNAME / ADMIN_PASSWORD from the env file.
docker compose run --rm -w /app api python -m scripts.create_first_superuser

# 4. Smoke test.
curl -fsS http://127.0.0.1:8000/health        # nginx mode: http://localhost/health
docker compose run --rm -w /app api python -m scripts.preflight   # config + revision + Redis
```

`prod` mode publishes the API on `127.0.0.1:8000` only — put a TLS-terminating proxy in front of it, or use
`bp deploy generate nginx` and add the certificate to `nginx/default.conf`.

Then log in as the admin, and give real people roles: `/admin` → Role assignments. The three seeded roles (`analyst`,
`reviewer`, `toolsadmin`) exist in every deployment; the demo *users* do not exist in production.

## What runs

| Service    | Image stage  | Role                                                                                   |
| ---------- | ------------ | -------------------------------------------------------------------------------------- |
| `migrate`  | `migrate`    | one-shot: `alembic upgrade head`, then `scripts.sync_roles`; both idempotent           |
| `api`      | `prod`       | the whole platform, every tool, `WORKERS` uvicorn workers                              |
| `worker`   | `base`       | Taskiq background jobs; nothing in the current tools needs it, keep it for future ones |
| `postgres` | `postgres:*` | data; volume `postgres-data`                                                           |
| `redis`    | `redis:*`    | sessions, CSRF tokens, login lockout, cache, rate limits; volume `redis-data`          |

Sessions live in Redis, so losing the Redis volume logs everyone out, and nothing else.

## Upgrading (including "a new tool was merged")

```bash
git pull
docker compose build
docker compose run --rm -w /app --no-deps api python -m scripts.preflight --config-only
docker compose up -d            # migrate runs first: new migration + new permission strings
curl -fsS http://127.0.0.1:8000/health
```

A new tool needs nothing else: its pages, API routes, admin views, permissions and seeds all come from its manifest.
The one human decision left is which role gets the new permission — `scripts.sync_roles` applies what the tool declares
in `permissions.py`, and anything beyond that is `/admin` → Roles.

## Rolling back

Code rolls back by checking out the previous tag and repeating the upgrade steps. Migrations do not: `alembic downgrade` is not exercised here, so treat a merged migration as forward-only and restore from a dump if one goes
wrong.

```bash
docker compose exec postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup-$(date +%F).sql   # before upgrading
```

Take that dump before every upgrade that carries a migration. Nothing in this repo schedules backups for you.

## Troubleshooting

| Symptom                                                                               | Cause                                                                                                                                 |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| API container exits immediately with "Critical security issues detected"              | The production validator; the log lists each issue. Run `scripts.preflight --config-only` to see the same list without a restart loop |
| `migrate` exits with "Production migration requires CONFIRM_PRODUCTION_MIGRATION=yes" | Running Alembic by hand with `ENVIRONMENT=production`; the compose service sets it, your shell has to too                             |
| Login redirects back to the login page                                                | Cookies are `Secure` and you are on plain HTTP, or Redis is unreachable (`scripts.preflight` checks the second)                       |
| `preflight` says the revision does not match                                          | The image is newer than the database: `docker compose up -d migrate`                                                                  |
| Intake shows "copy this prompt" instead of starting a session                         | No `DEVIN_API_KEY`; intentional, the brief is still stored                                                                            |

## Deliberately not here

No Kubernetes manifests, no Terraform, no CI-driven deploy, no blue/green. This is a single-host runbook because that
is what the prototype has been verified against; anything more is a real infrastructure decision, not a doc.
