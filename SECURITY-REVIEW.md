# Security review — internal tools platform

Scope: the whole repo as deployed (`backend/` FastAPI app, SQLAdmin surface, the KYC and feature-flag tools, the
`bp deploy` compose templates). Reviewed by reading every route, dependency, service and template, plus the
configuration and deployment path. Findings are split into what was actually wrong, what depends on how you deploy it,
what is hardening rather than a hole, and what does not apply to this app.

Everything under "fixed in this PR" is implemented and covered by unit tests where behaviour is testable.

## 1. Confirmed issues, fixed in this PR

| #   | Issue                                                                                                                 | Why it mattered                                                                                                                                                                                                                                                 | Fix                                                                                                                                                                                                                                                                                                          |
| --- | --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | CORS fell back to `allow_origins=["*"]` when nothing was configured                                                   | With `allow_credentials=true`, any origin could make authenticated cross-origin calls. A deployment that simply never sets `CORS_ORIGINS` got the worst setting.                                                                                                | Default is now the empty list: unconfigured means no cross-origin access.                                                                                                                                                                                                                                    |
| 2   | No CSRF defence on the two login forms                                                                                | crudauth's synchronizer token protects requests made *with* a session; the browser login form and the SQLAdmin login form have no session yet and are plain form posts. A third-party page could log a victim into an attacker-controlled account (login CSRF). | `SameOriginMiddleware` rejects state-changing requests whose `Origin` is neither this deployment's own host nor a configured origin.                                                                                                                                                                         |
| 3   | SQLAdmin's Starlette session cookie used framework defaults                                                           | 14-day lifetime, no `Secure`, no explicit `SameSite` — admin login state outlived and out-scoped the app session cookie.                                                                                                                                        | Named `admin_session`, `https_only` tied to `SESSION_SECURE_COOKIES`, `SameSite=Lax`, lifetime tied to `SESSION_TIMEOUT_MINUTES`.                                                                                                                                                                            |
| 4   | No Content-Security-Policy                                                                                            | Any future template mistake became script execution.                                                                                                                                                                                                            | Strict policy (`script-src 'self'`, `frame-ancestors 'none'`, `base-uri 'none'`, `object-src 'none'`). The platform's inline CSRF script moved to `static/js/platform.js` so nothing inline is needed. `/admin` gets a narrower exception (`unsafe-inline`) because SQLAdmin's bundled templates are inline. |
| 5   | `X-Request-ID` was echoed and stored verbatim; client IP was the socket address regardless of proxies                 | The request id lands in an audit row and a response header — an unbounded arbitrary-byte header. Behind a proxy the recorded IP was the proxy's, so audit rows carried a useless address.                                                                       | Request ids must match `[A-Za-z0-9._-]{1,64}` or a fresh UUID is used; `X-Forwarded-For` is read only as far back as `TRUSTED_PROXY_HOPS` allows, never when it is 0.                                                                                                                                        |
| 6   | Failed logins logged the submitted username                                                                           | People type their password into the username field; those logs are then a credential store.                                                                                                                                                                     | Logged (and audited) as a SHA-256 digest tag instead, so repeated attempts are still correlatable.                                                                                                                                                                                                           |
| 7   | API keys kept working after their owner was soft-deleted                                                              | Offboarding a user did not revoke their keys — the only non-session authentication path in the app.                                                                                                                                                             | `validate_api_key` now rejects keys whose owner is missing or `is_deleted`.                                                                                                                                                                                                                                  |
| 8   | Demo users could be seeded into production                                                                            | Three accounts with a published password, one holding every permission.                                                                                                                                                                                         | `create_platform_roles` refuses when `ENVIRONMENT=production` unless `SEED_DEMO_USERS_IN_PRODUCTION=true` is set deliberately.                                                                                                                                                                               |
| 9   | `CSRF_ENABLED=false`, `SESSION_SECURE_COOKIES=false` and a non-Redis session backend were only warnings in production | Each silently disables an authentication control; a warning in a boot log is not a control.                                                                                                                                                                     | They now fail production startup. `CREATE_TABLES_ON_STARTUP=true` in production warns (schema should come from reviewed migrations).                                                                                                                                                                         |
| 10  | Sign-in and sign-out were not in the audit trail                                                                      | The trail showed who approved a KYC case but not who logged in. For a fintech audit that is the first question.                                                                                                                                                 | `platform.session.login`, `platform.session.logout` and `platform.session.login_failed` are recorded.                                                                                                                                                                                                        |
| 11  | Unbounded free text reached audit payloads                                                                            | KYC decision reasons had a minimum but no maximum; the `/audit` `entity_type` filter was unbounded.                                                                                                                                                             | Reasons capped at 2000 characters, filter at 100.                                                                                                                                                                                                                                                            |
| 12  | Dev compose published Postgres and Redis on all interfaces                                                            | The dev database ships with the password `postgres`.                                                                                                                                                                                                            | Bound to `127.0.0.1` in the local template. Prod template already keeps them off the host.                                                                                                                                                                                                                   |

## 2. Configuration-dependent risks (deployment must get these right)

These are not code defects; they are the settings that decide whether the deployment is safe. The production validator
now blocks the worst of them at startup, but the rest are on the operator.

- `SECRET_KEY` — signs sessions and the admin cookie. The default is a known string; the validator rejects weak keys in
  production. Rotating it invalidates all sessions.
- TLS — the app sets HSTS in production but does not terminate TLS. Put it behind a proxy that does, and set
  `TRUSTED_PROXY_HOPS` to the number of proxies in front, otherwise audit rows record the proxy's IP.
- `SESSION_BACKEND=redis` — required, and now enforced in production: the memory backend means sessions are per-worker,
  so a multi-worker deployment logs people out at random and cannot revoke a session globally. Login lockout also only
  exists when Redis is configured.
- `ADMIN_USERNAME`/`ADMIN_PASSWORD` — the break-glass admin bypasses the platform's roles entirely and is not tied to a
  user row, so its actions have no `actor_user_id` in the audit trail. Set strong credentials or set `ADMIN_ENABLED=false`
  and rely on `platform.admin` accounts.
- Docs — `/docs` and `/openapi.json` are hidden in production unless `ENABLE_DOCS_IN_PRODUCTION`, in which case they are
  superuser-only. Leave them off.
- `CORS_ORIGINS` — leave empty unless a browser app on another origin genuinely calls this API. Wildcard is rejected in
  production.

## 3. Defence in depth / accepted residual risk (not fixed, deliberately)

- **SQLAdmin permission snapshot.** Permissions are read into the admin session at login, so revoking `platform.admin`
  takes effect on the next admin login or when the session expires (30 minutes by default), not instantly. Re-resolving
  per request would need a DB call inside SQLAdmin's sync `is_accessible`. Bounded, documented, acceptable for an
  internal tool; revoke the user's password/session if it needs to be immediate.
- **SQLAdmin writes bypass the service layer.** Editing a `Role` or a `Flag` in `/admin` does not write an audit event —
  only the audit table itself is hard-blocked from writes. Anyone with `platform.admin` is trusted; if you want every
  change audited, remove the write views and drive changes through the tools.
- **Privilege escalation inside `/admin`.** A `platform.admin` user can edit user rows, including `is_superuser`. That is
  what the permission means here; treat it as equivalent to superuser when granting it.
- **No rate limit on `/api/v1/flags/evaluate`.** It is the one API-key-authenticated route and the only surface a service
  (not a browser) reaches. The repo's rate limiting is opt-in per route; add `check_rate_limit` there before exposing it
  outside the cluster. Each evaluation also writes `last_used_at`, so a hot caller writes on every request.
- **API key scope is coarse.** The seeded key holds wildcard/read, not "may evaluate flags". Fine for one endpoint,
  wrong the moment a second API-key route exists.
- **Error responses are JSON everywhere.** An unexpected 500 or a 403 on an HTML page renders as JSON with a support id
  (no stack trace, no SQL). Expected domain errors already render inline in the tools. This is a UX gap more than a
  security one — flagging it for the UX phase.
- **Audit content is PII by design.** Customer names and decision reasons are stored in `after` payloads. That is the
  point of the trail, but it means the audit table inherits the retention and access rules of customer data;
  `audit.read` should be a small group.

## 4. Verified as sound (no change needed)

- **Authorization is enforced in services, not templates.** Hiding a button is never the control: every KYC transition
  re-checks the permission and the maker/checker rule inside the service, and forged POSTs were verified during browser
  testing to be refused without mutating state.
- **No IDOR found.** Every id-bearing route resolves the object and then authorizes the action; KYC claim/release check
  assignment, not just authentication.
- **Audit log is append-only.** No update or delete path exists in the CRUD layer, the SQLAdmin view is read-only and
  raises on insert/update/delete, and `audit.record` flushes into the caller's transaction so a rolled-back change takes
  its audit row with it.
- **SQL injection.** All queries go through SQLAlchemy/FastCRUD with bound parameters; no string-built SQL anywhere.
- **XSS.** Jinja autoescaping is on, no `|safe`, no `Markup`, no HTML built in Python. HTMX swaps server-rendered
  partials only. HTMX is vendored, not loaded from a CDN.
- **Password and API key storage.** Passwords are crudauth's; API keys are scrypt-hashed with a per-row salt, looked up
  by indexed prefix and compared with `hmac.compare_digest`. The plaintext key is shown once and never logged.
- **Open redirect.** `safe_next_path` rejects absolute, protocol-relative and control-character `next` values.
- **Dependencies.** No unexpected or unused packages in `pyproject.toml`; `uv.lock` pins the full graph, all packages are
  well-known and resolve to the real upstream projects. Nothing was added for this review.

## 5. Not applicable to this app

- SSRF — the app never fetches a caller-supplied URL.
- File upload — KYC documents are filenames only; no bytes are accepted or served.
- Payments, webhooks, email/notifications — none exist.
- Multi-tenant row isolation / RLS — one organisation, one database, permissions are the boundary.

## 6. Known gap, unrelated to security

The dev compose worker runs `taskiq worker --reload`, which needs the `taskiq[reload]` extra that is not installed, so
that container fails to start. Nothing in the platform or the tools uses background jobs; it is a deployment-phase fix.
