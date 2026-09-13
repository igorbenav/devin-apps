# Modularity at 50 tools — where this repo stands and what to change

Question being answered: *is `backend/src/modules/tools/<slug>/` modular enough, and what does this look like
with 50 internal tools?* This is a proposal, not a change. Nothing in it is implemented yet.

## 1. What is already right

Three things the platform got right, and they are the expensive ones to retrofit, so keep them:

- **Discovery, not registration lists.** `registry.discover_tools()` walks `src/modules/tools/*` with `pkgutil`
  and imports each `tool.py`; `include_tool_routers()` mounts each `router` at `spec.route_prefix`. Adding a page
  route to a new tool requires no edit to shared wiring.
- **Templates travel with the module.** `templating.build_templates()` builds a `ChoiceLoader` over
  `tools/*/templates`, so a tool ships its own HTML and still does `{% extends "platform/base.html" %}`.
- **Dependency direction is already correct in the tools.** `modules/tools/kyc/*` imports
  `modules/platform/*`, `modules/common/*` and `infrastructure/dependencies`; no tool imports `interfaces/`.
  Business code sits above infrastructure and below the app wiring, as intended.

## 2. Where it leaks today

Everything below is a file **outside** the tool's directory that must be edited to add a tool. With two tools it
is invisible; with 50 it is the whole problem. Each one is also a merge-conflict point between teams.

| Leak                                               | File                                                                                      | What goes wrong at 50 tools                                                                                                                                                                                                                     |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Admin views are statically imported and registered | `interfaces/admin/views/__init__.py` imports `...tools.flags.admin`, `...tools.kyc.admin` | `interfaces` imports tools — the dependency arrow points the wrong way. A 100-line import block, conflicted constantly.                                                                                                                         |
| JSON API routers are statically imported           | `interfaces/api/v1/__init__.py` imports `...tools.flags.api`                              | Same arrow, same conflicts. Two mounting mechanisms (pages discovered, APIs hand-wired) for no reason.                                                                                                                                          |
| The permission catalog lives in the platform       | `modules/platform/constants.py` holds `kyc.review`, `flags.write`, …                      | The platform knows every tool's vocabulary. Adding a tool means editing shared constants **and** the seeded roles.                                                                                                                              |
| Seeds are top-level scripts                        | `scripts/seed_kyc_cases.py`, `scripts/seed_feature_flags.py`, `setup_initial_data.py`     | 50 scripts in one directory, orchestrated by hand.                                                                                                                                                                                              |
| Migrations are one linear chain                    | `backend/migrations/versions/`                                                            | Every tool's migration takes `down_revision` from whatever landed last, so two teams merging the same day collide; `autogenerate` diffs all 50 tools' tables at once.                                                                           |
| Tests live outside the module                      | `backend/tests/unit/tools/test_<slug>.py`                                                 | The module is not self-contained; you cannot hand one directory to a team and say "this is yours".                                                                                                                                              |
| `ToolSpec` under-describes a tool                  | `modules/platform/registry.py`                                                            | It carries name/slug/prefix/one permission/nav label. Everything else a tool contributes (admin views, API router, permissions, seed, later: background jobs) has no declared home, which is exactly why those things leaked into shared files. |
| Tools import platform internals                    | `from ...platform.templating import render`, `from ...platform.dependencies import ...`   | 50 tools pinned to internal module paths: the platform can never refactor without touching every tool.                                                                                                                                          |

There is also no mechanical enforcement of any of this — the layering holds because it was written carefully, not
because anything fails when it is broken.

## 3. Options considered

**A. Leave it.** Honest assessment: fine to ~5 tools. The leaks are each one line per tool. It fails on
merge-conflict rate and on "one directory = one team" ownership long before it fails technically.

**B. Manifest-driven modules, same package tree** (recommended). `ToolSpec` grows into the full contract:
everything a tool contributes is declared in its `tool.py` and *collected* by the platform. Deletes every row in
the table above except migrations and layering enforcement, which are handled separately. No packaging change,
no new deployment story, and it is the prerequisite for C and D — the collection points are the same.

**C. Top-level `backend/src/apps/<slug>/`** instead of `modules/tools/<slug>/`. Purely cosmetic: it renames the
directory and says "these are applications, not library modules". Worth doing only as part of B, and honestly
`modules/tools/` already reads fine. Not recommended on its own.

**D. One installed package per tool** (`tools/kyc/pyproject.toml` as a uv workspace member, discovered through
`[project.entry-points."platform.tools"]`). This is real decoupling: per-tool dependencies, per-tool CI, a tool
cannot import another tool's internals because it is not on its path unless declared. Costs: 50 `pyproject.toml`
files, 50 editable installs, slower `uv sync`, a `platform-sdk` package that must be released and versioned, and
migrations that must live in packages. **Not now** — but B should leave the seam: if discovery reads both the
directory scan *and* entry points, moving a tool to a package later is a mechanical change of one tool at a time.

## 4. Recommended target

### 4.1 The module contract

`tool.py` becomes the single declaration of everything the tool contributes. Sketch:

```python
# modules/tools/kyc/tool.py
from platform_sdk import Permission, ToolSpec, register
from . import admin, api, router, seed

SPEC = register(
    ToolSpec(
        slug="kyc",
        name="KYC Review Queue",
        description="Review and decide customer KYC cases.",
        nav_label="KYC",
        owner="risk-eng",  # CODEOWNERS / who to page
        route_prefix="/tools/kyc",  # pages, mounted by the platform
        api_prefix="/kyc",  # /api/v1/kyc, mounted by the platform
        pages=router.router,
        api=api.router,
        admin_views=(admin.KycCaseAdmin, admin.KycDocumentAdmin),
        permissions=(  # the tool owns its vocabulary
            Permission("kyc.review", "See the queue and claim cases"),
            Permission("kyc.approve", "Approve or reject a claimed case"),
            Permission("kyc.escalate", "Escalate a case"),
        ),
        required_permission="kyc.review",  # gates the launcher card
        seed=seed.seed_demo_data,  # async (db) -> None, dev/demo only
    )
)
```

Collection points on the platform side, all of them loops over `registered_tools()`:

```python
include_tool_routers(pages_router)  # exists
include_tool_api_routers(api_v1_router)  # new — replaces the import block in interfaces/api/v1
register_tool_admin_views(admin)  # new — replaces the import block in interfaces/admin/views
permission_catalog()  # new — platform perms + every tool's declared perms
run_tool_seeds(db)  # new — replaces scripts/seed_*.py
```

`interfaces/` then imports the platform only, and the arrow `interfaces → platform → tools` becomes
`interfaces → platform ← tools`. The platform never names a tool; tools never name the app.

### 4.2 `platform_sdk`: the stable façade

Add `backend/src/platform_sdk/__init__.py` re-exporting exactly what a tool is allowed to use — `ToolSpec`,
`register`, `Permission`, `audit.record`, `require_permission`, `require_page_permission`, `ViewerContext`,
`render`, `AsyncSessionDep`, `DomainError`, the audited admin base classes. Tools import `platform_sdk` and
nothing else from outside their own package. That is what makes the platform refactorable at 50 tools: the
façade is the compatibility surface, and anything not in it is internal. Deprecations get a release note in
`PLAYBOOK.md` and a `DeprecationWarning`, not a 50-directory sed.

### 4.3 Enforcement (this is the part that makes it stick)

Add `import-linter` to the dev dependencies and run it in CI and pre-commit, with contracts:

- layers: `interfaces` → `platform` → `modules/*` → `infrastructure` (no upward imports);
- `platform` must not import `modules.tools.*`;
- each `modules.tools.<slug>` is independent of every other `modules.tools.<slug>` (import-linter's
  "independence" contract, one line, covers all 50 pairs);
- tools may import `platform_sdk`, `common`, and `infrastructure.dependencies` — nothing else shared.

One new dev dependency, no runtime dependency. Without this, every rule above is a convention that decays.

### 4.4 Migrations

Give each tool its own Alembic branch: `version_locations = migrations/versions, src/modules/tools/*/migrations`
with a `branch_label` per tool (`kyc`, `flags`, …) and `depends_on` the platform baseline. Then
`alembic upgrade heads` applies all branches, two teams never fight over `down_revision`, and a tool's schema
history lives in the tool's directory. `bp new tool` generates the branch base. Cost: `heads` (plural) in the
runbooks and slightly more care with autogenerate (`--branch-label`, review as always).

### 4.5 Tests, ownership, layout

Tests move next to the module: `modules/tools/<slug>/tests/`, collected by adding the glob to `pytest` config.
Then the directory really is the unit of ownership: `CODEOWNERS` gets one line per tool derived from
`spec.owner`, and `pytest src/modules/tools/kyc` is the tool's whole suite.

Resulting shape of one tool — nothing outside it:

```
modules/tools/kyc/
  tool.py          # the manifest: everything the platform collects
  models.py schemas.py crud.py service.py     # domain; service functions audit
  router.py        # HTMX pages          api.py  # JSON, if any
  admin.py         # SQLAdmin views      seed.py # demo data
  migrations/      # this tool's Alembic branch
  templates/kyc/   # HTML
  tests/           # unit tests
```

### 4.6 What 50 tools then costs

- **Adding one**: `bp new tool <slug>` + write the domain. Zero shared-file edits, so zero merge conflicts with
  the other 49 teams. Roles still need a human decision (which role gets the new permission) — that stays a
  deliberate edit to the seeded roles, now the only one.
- **Startup**: 50 package imports plus 50 routers; tens of milliseconds, and it happens once. Non-issue.
- **Launcher/admin/nav**: already permission-filtered; add grouping by `spec.category` when the launcher gets
  long and the admin sidebar needs sections.
- **Dependencies**: a tool needing a library the platform does not have becomes the trigger to move *that* tool
  to option D, not to change everything.
- **Background jobs / integrations** (out of scope today): they slot into the manifest the same way —
  `tasks=(...)` collected into the taskiq broker — which is the point of making the manifest the contract.

## 5. Migration path

Incremental, each step a small PR, the app working after every one:

1. `platform_sdk` façade + rewrite the two existing tools' imports to use it. Pure re-export, no behaviour.
1. `import-linter` contracts in CI, capturing today's layering as the baseline.
1. Manifest fields `api` and `admin_views` + their collection loops; delete the import blocks in
   `interfaces/api/v1/__init__.py` and `interfaces/admin/views/__init__.py`.
1. Manifest `permissions` + `permission_catalog()`; `constants.py` keeps only platform permissions; seeded
   roles reference the catalog.
1. Manifest `seed`; fold `scripts/seed_*.py` into `modules/tools/*/seed.py` behind one `run_tool_seeds`.
1. Per-tool Alembic branches; move tests into the modules; update `bp new tool` and `PLAYBOOK.md` last, once the
   target exists.

Steps 1–3 are most of the value. Steps 4–6 are cheap once the manifest exists. Option D stays available and is
then a per-tool decision rather than a rewrite.

## 6. Risks and honest caveats

- **Alembic branches are the only genuinely risky step.** Multiple heads are a real operational change; if the
  team is not comfortable with `upgrade heads`, keep the single chain and accept the conflicts — it is the one
  item here that can be dropped without unravelling the rest.
- **The manifest can turn into a god object** if every future platform feature adds a field. The rule should be:
  a field exists only when the platform *collects* it; anything a tool merely configures for itself stays in the
  tool.
- **`platform_sdk` is a promise.** Once 50 tools import it, changing it is a migration. Keep it small and refuse
  to re-export anything a tool should not touch (sessions, the app factory, other tools).
- This proposal adds one dev dependency (`import-linter`) and no runtime dependency.
