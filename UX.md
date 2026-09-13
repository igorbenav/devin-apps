# UX: who uses this platform, and what they are trying to get done

Written for the sessions that build tools 3 through 50, and for the people who will ask for them.
It covers two audiences that are usually discussed separately and shouldn't be: the person doing
their job inside a tool, and the person (or Devin session) creating the tool.

Power Apps is the baseline we are compared against. Not its canvas editor — its *consistency*: every
app looks the same, logs in the same way, appears in the same launcher, and an ops lead can get one
built without a platform team. That consistency is a UX property, and on this platform it has to
come from the shared layer, because nobody is going to hand-police fifty tools.

Gaps below were read off the templates, not guessed — where this guesses about the customer's
actual working habits, it says so.

## 1. The four people

|                    | Who                                                               | How often they touch it                        | What "good" means to them                                                        |
| ------------------ | ----------------------------------------------------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------- |
| **Operator**       | KYC analyst, reviewer, ops agent. The person the tool exists for. | Many times a day, in bursts, as work arrives   | Get through the queue without thinking about the tool                            |
| **Requester**      | Ops lead / PM who owns the process and asks for the tool          | Once per tool, then occasional change requests | Describe the process and get something usable back, without writing a spec twice |
| **Platform admin** | Whoever owns access and answers "who did what"                    | Weekly; daily in the first month of a new tool | Grant the right access fast, prove a decision after the fact                     |
| **Builder**        | A Devin session, plus the engineer who reviews the PR             | Per tool and per change                        | Ship a tool that is consistent by default, without inventing UI decisions        |

The Builder is a real persona here, not a metaphor. Most of this document's leverage is in making the
Builder's defaults good, because the Builder is the one who will be repeating decisions fifty times.

## 2. Jobs to be done

Frequency is the ranking input: a job done forty times a day deserves keyboard-level polish; a job
done twice a year deserves to merely exist and be discoverable.

### Operator

| Job                                           | Trigger                                     | Frequency                              | Today                                                                                                                                          |
| --------------------------------------------- | ------------------------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Find the tool I need                          | Start of shift, or a colleague sends a link | Daily                                  | Launcher lists permitted tools. Works.                                                                                                         |
| See what needs *me* right now                 | Opening the tool                            | Many/day                               | KYC has a "mine" tab; nothing platform-wide. No cross-tool "my work" view                                                                      |
| Pick up the next item and work it             | Continuous                                  | 10–100/day                             | Claim/release in place via HTMX. Good, but no busy state — a slow click looks like a dead click                                                |
| Understand an item before deciding            | Per item                                    | 10–100/day                             | Case detail with documents and the case's own audit trail. Tool-specific, not inherited                                                        |
| Take an action and know it stuck              | Per item                                    | 10–100/day                             | Row swaps in. No confirmation message; errors render inline in KYC only                                                                        |
| Hand off / escalate to a human                | Exception path                              | Weekly                                 | Escalate state exists; no notification, so handoff happens in Slack. Out of scope, but the UI should say so rather than imply someone was told |
| Find something I did last week                | Question from a colleague or auditor        | Weekly                                 | No search, no filter by me, no date range. `/audit` shows the last 200 events for everyone                                                     |
| Get access to a tool I can see but can't open | New joiner, role change                     | Rare per person, constant in aggregate | Launcher says "ask an admin". Dead end                                                                                                         |
| Do it on a phone                              | On call, travelling                         | Rare but high-stakes                   | No responsive CSS at all. Unusable                                                                                                             |

### Requester

| Job                                          | Trigger                                       | Frequency                    | Today                                                                                                                               |
| -------------------------------------------- | --------------------------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Describe a process well enough to get a tool | New process, or a spreadsheet that grew teeth | ~10/yr initially, more later | No intake format. The quality of what Devin builds tracks the quality of the ask, and there is nothing telling them what to include |
| See a first version and react to it          | 1–2 days after asking                         | 2–3 rounds per tool          | Works (PR + a running demo), but requires someone to read a PR                                                                      |
| Ask for a change                             | After launch                                  | Monthly per tool             | Same path as a new tool. No in-app "report an issue" affordance, so requests arrive in Slack with no context                        |
| Know the tool is being used                  | Monthly                                       | Monthly                      | Nothing. No usage numbers anywhere                                                                                                  |

### Platform admin

| Job                            | Trigger                  | Frequency       | Today                                                                                                                 |
| ------------------------------ | ------------------------ | --------------- | --------------------------------------------------------------------------------------------------------------------- |
| Give a person access           | Joiner/mover             | Weekly          | SQLAdmin: roles and user-roles are editable, and those writes are audited                                             |
| Answer "who approved this?"    | Dispute, audit, incident | Monthly, urgent | `/audit`, last 200 events, filter by entity type only. No actor filter, no entity id filter, no date range, no export |
| Prove the control works at all | Compliance review        | Quarterly       | Maker/checker is enforced in the service layer and tested. There is no page that *shows* a non-engineer that          |
| Retire a tool or a permission  | Rare                     | Yearly          | Undefined — no lifecycle story for a tool nobody uses                                                                 |

### Builder

| Job                                            | Trigger       | Frequency   | Today                                                                                                                                                  |
| ---------------------------------------------- | ------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Understand the pattern before writing anything | Session start | Per session | `PLAYBOOK.md`, and it is the reason sessions 2 and 3 were cheap                                                                                        |
| Scaffold a tool                                | Session start | Per tool    | `bp new tool <slug>`; manifest-driven since #7, no shared files to edit                                                                                |
| Decide what the UI should look like            | Per page      | 5–10/tool   | **This is the gap.** There is no component vocabulary, so every tool re-invents tables, forms, errors and empty states, and they will drift by tool 10 |
| Wire permissions                               | Per action    | 5/tool      | `require_permission` + `current_permissions`. Clear                                                                                                    |
| Prove it works                                 | Before the PR | Per session | Unit tests, plus the browser-testing skill. Good                                                                                                       |

## 3. User stories worth implementing, in priority order

Priority = frequency × cost of the current workaround. Each story states the acceptance criterion I
would test against.

**P0 — every operator, every action**

1. *As an operator, when I click an action I can tell it is running,* so I don't double-click a slow
   approve. → Any `hx-post` button shows a busy state within 100ms and is disabled while in flight.
1. *As an operator, when an action fails I see why, in the page,* not a JSON body or a silent no-op.
   → A shared flash/inline-error region; every tool gets it without writing one. Today KYC renders
   errors inline and flags mostly does; a 403 from a page dependency is raw JSON.
1. *As an operator without permission, I get a page that tells me what to do next.* → Styled 403 with
   the missing permission named and a "request access" action, not `{"detail": "..."}`.

**P1 — every operator, every session**

4. *As an operator, I can find a specific record by its identifier.* → A shared list component with
   search, sort and paging that a tool opts into with a few lines, rather than hand-rolling a table.
1. *As an operator, the link in my address bar reproduces what I'm looking at.* → Filter and tab state
   lives in the query string (KYC tabs already do this; the audit filter does not).
1. *As an operator, I see the history of the thing I'm looking at, on the thing I'm looking at.* → A
   platform-provided entity audit partial any detail page can include, instead of KYC's bespoke one.

**P2 — admins and requesters**

7. *As an admin, I can filter the audit log by actor, entity id and date range, and page past 200.*
1. *As an admin, I can grant a role without SQLAdmin* — a small "people and roles" page, because
   SQLAdmin is a database editor and hands it the whole schema.
1. *As a requester, I can report a problem from the page I'm on,* with the tool, page and my username
   prefilled into a GitHub issue — that issue is then a ready-made Devin prompt. *Built.*
1. *As a requester, I can see whether anyone used this tool last month.* → Usage counts derived from
   the audit table; no new tracking infrastructure.

**P3 — situational but embarrassing when missing**

11. Responsive layout at one breakpoint, so an approval is possible from a phone.
01. Visible focus states and sane tab order; an operator doing 80 decisions a day will want the
    keyboard. Whether they actually will is a guess — worth asking their KYC team before building
    shortcuts.

## 4. What the shared layer should own

The rule that keeps fifty tools coherent: **if two tools would each make a UI decision, the platform
makes it once.** Concretely, the platform should own — and `platform_sdk` should expose — the
following, so a tool inherits them by existing:

- Page shell: nav, current user, roles, tool list, log out. *Exists.*
- Page header pattern: title, one-line purpose, owning team, "report an issue". *Missing owner and
  feedback.*
- Empty states, loading/busy states, flash messages, inline field errors. *Missing.*
- Permission-denied and not-found pages, in HTML. *Missing.*
- List/table: sort, paginate, search, per-row HTMX actions, "no results" state. *Every tool hand-rolls it.*
- Form controls and validation rendering. *Hand-rolled.*
- Destructive/irreversible action confirmation. *Missing; KYC decisions are irreversible today with no confirm step.*
- Entity audit trail partial. *Exists inside KYC only.*
- Formatting filters: timestamps in the viewer's timezone, money, risk scores, usernames from ids.
  *Ad hoc per template; `usernames_for_ids` exists in the SDK, the rest doesn't.*
- One breakpoint of responsive layout and focus styling. *Missing.*

A tool is then free to choose: its columns, its tabs, its detail layout, its action verbs and its
domain language. That is the right split — the tool owns the *work*, the platform owns the *frame*.

## 5. Development UX: how a request becomes a tool

The biggest single lever on quality is the intake, not the code: a paragraph in Slack makes the
Builder guess the rest. These are the ten questions `/tools/intake` asks, and the ones to ask
anywhere else a request arrives:

1. Who uses this, and what is their job title?
1. What decision or action does it let them take that they can't take now?
1. What do they do today instead (spreadsheet, email, Power Apps, nothing)?
1. What are the states a record moves through, and who can move it between them?
1. What must never happen? (e.g. same person approves their own case)
1. What has to be provable afterwards, to whom?
1. Where does the data come from, and where does it need to go?
1. How many records a day, and how many people?
1. What does success look like in a month — time saved, errors avoided, a number?
1. What is explicitly out of scope for v1?

Questions 4, 5 and 6 are the ones that decide whether the result is a real workflow tool or a CRUD
grid — they are exactly what made the KYC session produce something worth demoing. Question 9 is the
one that lets the VP kill a tool later.

The brief feeds `bp new tool` and the session that follows it. The UX bar a finished tool should
meet: every action has a busy state, every failure has a visible message, every list has an empty
state, and the page header names the tool's owner.

## 6. What the shared layer still doesn't own

Roughly in the order they compound, each about half a session to a session of work:

1. **Feedback and failure** — busy states, a flash region, HTML 403/404 pages, inline form errors,
   confirmation on irreversible actions.
1. **The list component** — a shared table partial with search, sort and paging, URL-state
   conventions, and formatting filters.
1. **Launcher and metadata** — tool owner and feedback link on the manifest, a request-access flow,
   a cross-tool "my work" view.
1. **Audit usability** — actor, entity and date filters, paging past 200, export, a shared
   entity-audit partial, per-tool usage counts.
1. **Access without SQLAdmin** — a people-and-roles page behind `platform.admin`.
1. **Polish** — one breakpoint, focus styles, tab order.

The first two are what stop tools 3–50 from each inventing their own table and their own error
handling; everything else is a convenience until the tool count grows.

## 7. Things I don't know and would ask the customer

- Do operators live in this tool all day, or drop into it a few times between other systems? It
  changes whether keyboard shortcuts and density matter more than guidance and labels.
- Is any of this used on a phone today in Power Apps? If yes, responsive moves from P3 to P1.
- Who actually grants access at this company, and are they willing to use SQLAdmin? If not, slice E
  is not optional.
- Does anything need to be visible to people *outside* the ops teams (finance, compliance, support)
  in read-only form? Read-only viewers are a different permission shape than the current roles.
- What is the real volume per tool? Everything above assumes hundreds of records, not millions;
  server-rendered tables with paging hold up fine at that size and would need rethinking well before
  a million rows.
