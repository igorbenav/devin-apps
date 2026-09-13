---
name: platform-browser-testing
description: Run the Fastro internal-tools launcher, KYC queue, role permissions, audit HTMX, and SQLAdmin browser checks locally.
---

# Local platform browser testing

## Environment
- At repo root, run `uv sync --all-packages --all-extras` and `uv run bp deploy generate local`.
- Create `backend/.env` from its example if absent, generate a local SECRET_KEY, and set `CREATE_TABLES_ON_STARTUP=false`.
- Start Docker and `docker compose up -d --build api`; its Postgres/Redis dependencies are needed. A generated worker may require the `taskiq[reload]` extra; inspect its logs separately rather than treating worker failure as proof that browser routes cannot run.
- Run migrations and seed from the host because the dev API image may omit Alembic configuration and seed scripts:
  `POSTGRES_SERVER=127.0.0.1 uv run --directory backend alembic upgrade head`
  `POSTGRES_SERVER=127.0.0.1 uv run --directory backend python -m scripts.setup_initial_data`
- For host-side commands, also override Redis host settings to localhost if an invoked path needs Redis.
- After machine restart, restart API/dependencies and inspect preserved migration/seed state before resetting anything. Do not delete volumes merely to resume a run.

## Browser flow
- Open `http://127.0.0.1:8000/login`. Seeded analyst/reviewer/toolsadmin accounts use DEMO_USER_PASSWORD (demo default documented by the seed).
- Empty launcher is intentional when registry has no tools. Check current username, role chips, role-gated Audit/Admin links, and Log out.
- toolsadmin opens Audit log; entity selector should replace `#audit-rows` through `/audit/rows`, without document navigation. Compare performance.timeOrigin before/after and observe XHR responses.
- HTMX should load only from `/static/js/htmx.min.js`. Dynamic documents/partials should be private no-store; static assets may be public-cacheable.
- SQLAdmin `/admin/login` has an independent login/logout session. Use toolsadmin there; `/admin/role/list`, `/admin/user-role/list`, and `/admin/audit-event/list` expose platform views.
- Audit list/details have no write controls. Direct `/admin/audit-event/create` and `/admin/audit-event/edit/<existing-id>` must deny rather than render forms.
- Explicitly sign out of SQLAdmin before testing another user's SQLAdmin permissions; platform logout alone does not represent SQLAdmin logout.
- For cache checks, keep caching enabled: anonymous audit -> toolsadmin launcher -> click Audit -> logout -> analyst login -> Back/Forward and direct audit. Prior protected rows must not reappear.
- Analyst/reviewer audit denial is a JSON 403 with an audit.read permission message, not an HTML error page.

## Devin Secrets Needed
- Local seeded checks require no external secrets; use the local demo password configuration.
- Optional break-glass verification requires the locally configured ADMIN_USERNAME and ADMIN_PASSWORD.
- Production/staging must use explicitly granted credentials instead of local demo accounts.

## KYC queue extension
- Verify the KYC migration revision and tables before assuming startup/seed ran. If needed, from backend run `POSTGRES_SERVER=127.0.0.1 uv run alembic upgrade head` and `POSTGRES_SERVER=127.0.0.1 uv run python -m scripts.seed_kyc_cases`.
- Seed is idempotent by customer_ref and does not restore changed cases. Query or inspect actual IDs: customer suffixes need not equal database IDs after prior testing.
- `/tools/kyc` lists Pending, In review, Mine, Decided. Sorting is risk descending, then oldest submission. Mine filters assignee regardless of state; approved cases can remain assigned.
- Pick an untouched pending case for analyst Claim → reviewer Approve → toolsadmin `/audit` filtered to `kyc_case`. Keep an exact distinctive reason to correlate the before/after chain.
- Compare performance.timeOrigin before/after Claim/Release and inspect XHR resource entries to prove row swaps rather than reloads.
- Analyst approval fails the kyc.approve permission check before maker/checker. To isolate maker/checker, use a case assigned to a user who does hold approve permission (the seed assigns CUS-1003 to reviewer).
- Disallowed actions are hidden. For explicitly requested forged-request tests, use the page's actual `htmx.ajax('POST', path, {target:'#kyc-case-detail', swap:'outerHTML', values:{view:'detail', reason:'sufficient test reason'}})` and screenshot the resulting server-rendered inline error. Do not invent a fake error banner or extract cookies for external API calls.
- Action refusals intentionally return HTML 200 for HTMX swapping. A 200 alone proves nothing: verify the visible refusal, unchanged state, and absence of a new mutation audit event.
- Test a 9-character reason followed by a sufficient reason. Check assignee Release separately from non-assignee analyst Release.
- Record test start UTC and inspect `docker compose logs --since <start> api` for tracebacks/5xx. Read-only database checks can confirm denied actions wrote nothing.
