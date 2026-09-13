# Operating this platform with Devin

`UX.md` argues about what the screens should do. This is the other half: which **Devin features** to
actually turn on so that "ask for an internal tool and get one" works for a non-engineer, the way
Power Apps does — and where that comparison breaks.

v1 scope: desktop only, ten-ish tools, one repo, one deployment.

The thing Power Apps really sells is not the canvas editor. It is that **an ops lead can get an app
without asking the platform team, and the platform team still keeps control of identity, data
access and audit.** Everything below exists to reproduce that loop with Devin holding the pen.

## 1. The loop we need

```
requester describes a need  ->  a Devin session builds it  ->  a human merges  ->  it is live in the launcher
     ^                                                                                    |
     +----------------------- they report a problem from inside the tool -----------------+
```

Four handoffs, each with a Devin feature behind it:

| Step                              | Feature to use                                                                                     | Why this one                                                                                                                                          |
| --------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Capture the request               | **Automations** with a GitHub *Issue* trigger, or a Slack trigger on `@Devin` in `#internal-tools` | The requester already lives in Slack/Jira; an automation fires a session with a fixed prompt and no engineer in the middle                            |
| Build it consistently             | **Playbooks** (one per task type) + **Knowledge** pinned to this repo                              | The playbook is the procedure, Knowledge is the standing law. Without them each session re-derives conventions and the fifty tools drift              |
| Start ready to work               | **Environment blueprint / snapshot** (already configured for this repo)                            | Sessions that spend ten minutes installing `uv` cost real money at fifty tools                                                                        |
| Keep quality without a bottleneck | **Devin Review** on every PR, with **Auto-Fix**, plus CI                                           | One engineer cannot meaningfully review fifty small apps a quarter. A first-pass reviewer that knows the repo's standards is the only way this scales |

## 2. What to configure, concretely

### Playbooks (three, not thirty)

1. **`Add an internal tool`** — takes a filled-in brief (the ten questions in `UX.md` §5) and runs the
   `PLAYBOOK.md` procedure: `bp new tool <slug>`, model the domain, services with audit, permissions
   on the manifest, HTMX pages, migration, tests, PR. Definition of done included, so the session
   stops at the right place.
1. **`Change an existing tool`** — scoped edit: find the tool module, change it inside that module
   only, no shared-layer edits without saying so in the PR.
1. **`Fix a reported bug`** — starts from an issue created by the in-app report button, reproduces
   first, then fixes.

Keep the number small. Playbooks that nobody maintains are worse than no playbook.

### Knowledge pinned to this repo

Standing rules that must hold in *every* session, which is exactly what Knowledge is for (pin to the
repo so it always loads):

- The one-repo/one-deploy rule, and that tools live under `backend/src/modules/tools/<slug>/`.
- Tools import `src.platform_sdk` and nothing else from the platform; import-linter enforces it.
- Every state change goes through a service function that records an audit event. No writes in routes.
- Adding a permission does not grant it — role assignment is deliberate.
- The UX contract from `UX.md` §4: use the shared components, don't invent a table.
- The invariants in `ARCHITECTURE.md`: audit in the same transaction, no writes in routes,
  permissions resolved per request.

This repo already has an auto-generated index note; these are the opinionated ones worth writing by hand.

### Automations

- **GitHub issue labeled `tool-request`** → session with the *Add an internal tool* playbook.
- **GitHub issue labeled `tool-bug`** → session with the *Fix a reported bug* playbook.
- **Issue comment starting with `/devin`** → follow-up session, so a requester can iterate by commenting.
- **CI check run `conclusion = failure`** on this repo → session that fixes the build.
- **Schedule, weekly** → dependency and security sweep on this repo, opening a PR when something
  needs bumping. This is the maintenance work that "we'll own it ourselves" quietly signs you up for.

Conditions should be narrow (specific repo, specific label). An automation that fires on every issue
is a way to burn ACUs.

### Devin Review + code scans

- Devin Review on all PRs to this repo, Auto-Fix on. It has caught real bugs the test suite did not
  — test packages breaking Alembic's model discovery, a fresh database missing tool tables,
  concurrent writes that needed row locks.
- A periodic **code scan** (security profile) over the repo — the same class of work as the manual
  review behind `SECURITY.md`, minus the person.

### Ask Devin / the repo index

Non-engineers asking "who is allowed to approve a KYC case?" should get an answer from the indexed
repo instead of an engineer reading `service.py` aloud in a meeting. This is the closest thing to
Power Apps' "the app is self-documenting" property, and it costs nothing to enable.

### Session hygiene that matters at fifty tools

- **Tag every session** with the tool slug (`tags: ["tool:kyc"]`) so usage can be attributed per tool
  later. Cost per tool is the number the VP will ask for in month three, and it cannot be
  reconstructed after the fact.
- **`max_acu_limit`** on automation-started sessions, so a malformed request cannot run away.
- Sessions synced to a Slack thread, so the requester watches progress where they already are.

## 3. The piece that lives in the app itself

Everything above is configuration. The part that makes this a product rather than a GitHub
workflow is the **in-app intake**, and it is built:

- **`/tools/intake`**, behind the `tools.request` permission: the ten brief questions as a form. On
  submit the platform calls `POST /v1/sessions` with the brief rendered into the *Add an internal
  tool* playbook, tagged `tool:<slug>`, capped with `max_acu_limit`, and stores the session URL.
  The list below the form shows each brief's status and session link.
- **"Report an issue"** in the shared page header: a prefilled GitHub issue (tool, page, user, what
  happened) that the `tool-bug` automation turns into a session.

Why the API and not just a link to Slack: the brief is the thing that determines output quality, and
a form gets a complete brief where a Slack message gets three sentences. It is also the demo that
answers the VP's real question — *can my ops lead get a tool without filing a ticket with my team?*

Operating it: `DEVIN_API_KEY` is held server-side (never rendered into the page); without it the
brief is still stored and the prompt shown to copy, rather than pretending a session started. Each
requester is capped per day and dispatch is claimed in the database before the API call, so a
double click cannot buy two sessions. The brief is requester-typed text going into an agent prompt
— prompt injection is mitigated by the ACU cap, the tag, and the human merge, not solved.

## 4. Where this does not match Power Apps, and you should say so out loud

- **Latency.** Power Apps: minutes, in a WYSIWYG editor, by the person who wants it. Here: a session
  plus a human merge, so hours. Fine for "we need a review queue", wrong for "I want this column
  moved right now". The in-app request form makes the ask cheap; it does not make the wait short.
- **No end-user editing.** Nobody without repo access changes a screen. That is a real loss of
  agency for the requester, and the honest trade is that it buys you review, tests, audit and a
  rollback story — the four things spreadsheets-turned-apps never have.
- **Connectors.** Power Apps ships hundreds (365, Dataverse, SharePoint, Teams). Here every
  integration is code someone writes once. Cheap for internal Postgres, expensive if these tools
  really need to read SharePoint lists.
- **A human is still in the loop, by design.** Devin Review plus CI plus a merge. Do not sell
  "no engineers involved"; sell "engineers spend an hour per tool instead of a week".
- **Cost is variable, not a license.** ACUs per tool built and per bug fixed, versus a flat $250K.
  That is an advantage only if the tool count grows faster than the session count — which is why
  tagging sessions per tool from day one matters.
- **The platform layer is your liability now.** Microsoft patches Power Apps. Here, the weekly
  dependency automation and the periodic code scan *are* the patching story; if nobody owns them,
  the savings quietly become risk.

## 5. Suggested order

1. Knowledge notes + the three playbooks. Costs an hour, improves every session after it.
1. Devin Review with Auto-Fix, and the CI-failure automation. This is what makes fifty tools
   reviewable.
1. `TOOL_BRIEF.md` + the issue-label automations. The requester loop, with zero app code.
1. In-app request form and report button (§3). The demo-able version of the same loop.
1. Weekly maintenance automation and the periodic code scan. The part everyone forgets until an
   audit.
