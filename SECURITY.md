# Security model

What protects this platform, what the operator has to get right, and what is knowingly left open.
Scope is the whole deployable: the FastAPI app, the SQLAdmin surface, the tools, and the `bp deploy`
compose templates. Every claim here was verified by reading the route, dependency, service or
template that implements it, and the behaviour is covered by unit tests where it is testable.

## 1. Controls in place

| Area              | Control                                                                                                                                                                                                                                         |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Authentication    | Server-side sessions in Redis (crudauth), escalating login lockout, generic login errors, `next` restricted to same-origin relative paths                                                                                                       |
| CSRF              | crudauth's synchronizer token for requests that have a session, plus `SameOriginMiddleware` for the two login forms that do not. Configured CORS origins are accepted on `/api/` only, so pages and `/admin` require same-origin                |
| Authorization     | Flat permissions resolved per request from the database and enforced in services, never in templates; forged POSTs are refused without mutating state                                                                                           |
| Audit             | Append-only by construction (no update/delete path in CRUD, read-only SQLAdmin view); service writes are atomic with their audit row; sign-in, sign-out and failed sign-in are recorded, including API, OAuth and `/admin`                      |
| Admin surface     | `/admin` requires `platform.admin` or superuser, re-resolved on every admin request so a revoked grant takes effect at once; writable views record create/update/delete with before/after snapshots                                             |
| API keys          | scrypt-hashed with a per-row salt, looked up by indexed prefix, compared with `hmac.compare_digest`, shown once and never logged; rejected when the owner is missing or soft-deleted; scoped (`feature_flags:read`) and rate-limited per key id |
| Browser hardening | Strict CSP (`script-src 'self'`, `frame-ancestors 'none'`, `base-uri 'none'`, `object-src 'none'`), with narrower policies for `/admin` and the docs paths; no inline script in platform templates; HSTS in production                          |
| Cookies           | App session and the separate `admin_session` cookie both `Secure` (tied to `SESSION_SECURE_COOKIES`), `SameSite=Lax`, lifetime tied to `SESSION_TIMEOUT_MINUTES`                                                                                |
| Input and logging | Request ids must match `[A-Za-z0-9._-]{1,64}`; `X-Forwarded-For` honoured only as far as `TRUSTED_PROXY_HOPS` and only if it parses as an IP; failed logins record a digest of the submitted identifier, never the identifier                   |
| Injection         | SQLAlchemy/FastCRUD with bound parameters everywhere; Jinja autoescaping on with no `safe` filter, no `Markup`, no HTML built in Python; HTMX vendored, never a CDN                                                                             |
| Startup           | The production validator refuses to boot on a weak `SECRET_KEY`, `CSRF_ENABLED=false`, insecure session cookies, a non-Redis session backend, or wildcard CORS with credentials. Unconfigured CORS means no cross-origin access                 |
| Seeding           | Demo users refuse to be created when `ENVIRONMENT=production` unless `SEED_DEMO_USERS_IN_PRODUCTION=true`; production role sync (`scripts.sync_roles`) creates no users at all                                                                  |

## 2. What the operator has to get right

Not code defects — the settings that decide whether a deployment is safe.
`python -m scripts.preflight` checks the mechanical ones before traffic moves; the rest are
judgement. [DEPLOY.md](DEPLOY.md) is the runbook.

- **`SECRET_KEY`** signs sessions and the admin cookie. Rotating it invalidates every session.
- **TLS** is not terminated by the app. Put it behind a proxy that does, and set
  `TRUSTED_PROXY_HOPS` to the number of proxies in front — otherwise audit rows record the proxy's
  address.
- **`SESSION_BACKEND=redis`** is required: the memory backend is per-worker, so sessions cannot be
  revoked globally and a multi-worker deployment logs people out at random. Login lockout also
  lives in Redis.
- **`ADMIN_USERNAME`/`ADMIN_PASSWORD`** is a break-glass login that bypasses roles and has no user
  row, so its actions audit with a null actor. Use strong credentials or set `ADMIN_ENABLED=false`
  and rely on `platform.admin` accounts.
- **`CORS_ORIGINS`** stays empty unless a browser app on another origin genuinely calls this API.
- **Docs** (`/docs`, `/openapi.json`) are hidden in production unless `ENABLE_DOCS_IN_PRODUCTION`,
  in which case they are superuser-only. Leave them off.
- **Demo users** (`analyst`/`reviewer`/`toolsadmin`) are a development affordance with a published
  password. They must never exist in a real environment.

## 3. Accepted residual risk

Known, reasoned about, and not fixed. Revisit these if the threat model changes.

- **`platform.admin` is effectively superuser.** It can edit user rows through `/admin`, including
  `is_superuser`. That is what the permission means here; grant it like root.
- **Admin audit rows are post-commit, not atomic.** SQLAdmin commits its own session and then calls
  the `after_*` hooks, so an admin write can land while its audit insert fails. Service-layer writes
  remain atomic. Making `/admin` atomic means replacing SQLAdmin's session handling.
- **The audit log is append-only by construction, not by grant.** Anything holding a raw database
  session can still `UPDATE platform_audit_event`. If audit integrity matters legally, add a
  database role without UPDATE/DELETE on that table, or ship to an append-only store.
- **Audit content is PII by design.** Customer names and decision reasons live in `after` payloads,
  so the audit table inherits the retention and access rules of customer data. `audit.read` should
  be a small group, and payloads should carry changed fields, not whole rows.
- **Legacy wildcard API keys still reach the evaluate route**, because validation falls back to
  `*:read` / `*:*`. New keys get narrow scope; revoke wildcard keys if you want the endpoint
  reachable only by `feature_flags:read`.
- **Rate limiting is opt-in.** With `RATE_LIMITER_ENABLED=false` the evaluate route is unlimited,
  and with it on the limiter inherits `RATE_LIMITER_FAIL_OPEN`. Each evaluation also writes
  `last_used_at`. There is no rate limit on the login form (crudauth's lockout applies instead);
  for an internet-facing deployment that is the first thing to reconsider.
- **Tool briefs are attacker-controlled text inside an agent prompt.** `/tools/intake` renders what
  a requester typed into a prompt for a session with repo access. Prompt injection is not solved:
  the mitigations are the ACU cap, the per-tool tag, the playbook, and the fact that a human reviews
  and merges the PR. Do not remove the human merge step.
- **`ISSUE_TRACKER_NEW_ISSUE_URL`** is a link target rendered into every page. Point it at your own
  tracker before deploying; a wrong value leaks page paths and usernames to whoever owns that URL.
- **Unexpected errors render as JSON**, including a 403 on an HTML page. Expected domain errors
  render inline in the tools. This is a UX gap more than a security one — see [UX.md](UX.md).

## 4. Out of scope for this app

SSRF (the app never fetches a caller-supplied URL), file upload (KYC documents are filenames only,
no bytes accepted or served), payments and webhooks (none exist), and multi-tenant row isolation
(one organisation, one database — permissions are the boundary).
