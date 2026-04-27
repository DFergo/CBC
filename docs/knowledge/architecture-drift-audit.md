# Architecture drift audit — deferred

**Decision date:** 2026-04-24 (Sprint 17 close)
**Status:** deferred. Re-evaluate after ~5 sprints OR if drift surfaces in Claude sessions.

## What we considered

A dedicated drift-detection sub-agent that:

1. Walks the current source tree (services, admin routers, admin UI sections, config files, storage paths).
2. Diffs that against `docs/architecture/ARCHITECTURE.md`.
3. Reports gaps: services in source not in the doc, UI controls in source not in §5 / §9, files in `/app/data/` layout that drifted, runtime keys with stale defaults.

Can be invoked manually (`/check-arch`) or wired into the `/sprint` Finalizing step as a hard gate before close.

## Why we're not building it now

- **Single-developer, high-Claude involvement.** Daniel + Claude are the only people writing into this repo. Every sprint already runs through the `/sprint` skill, which now requires touching ARCHITECTURE.md or explicitly noting "no architecture changes this sprint" in the CHANGELOG (Sprint 17). That discipline is the cheapest way to keep the doc accurate without introducing automated drift detection.
- **The doc is read every session.** `CLAUDE.md` puts ARCHITECTURE.md first in the READ ORDER. Stale claims will bite Claude in the next sprint and get fixed reactively, before they accumulate.
- **Building the audit is not free.** Writing a code walker that distinguishes "missing because the doc is wrong" from "missing because the implementation is in flux during the sprint" needs careful heuristics. The labour cost in Sprint 17 buys little if the workflow already keeps the doc honest.

## When to revisit

Build the audit if any of the following becomes true:

1. **A Claude session quotes ARCHITECTURE.md and acts on stale info.** This is the most concrete signal — the doc has degraded enough to misroute work.
2. **Multiple developers start contributing.** Discipline breaks under team scale; tooling has to take over.
3. **A sprint ships and the post-mortem reveals the doc didn't get touched** despite touching services, data flows, or storage. One incident is fine; a pattern is the trigger.
4. **`/sprint` Finalizing's "no architecture changes this sprint" note appears in 5 consecutive sprints**, but reality is that something did change. That's evidence the workflow alone isn't enough.

## What the audit would look like (sketch, for future Claude or developer)

- A subagent (`drift-audit` agent type, or a `/check-arch` skill) with read-only access to the working tree.
- Inputs: `docs/architecture/ARCHITECTURE.md`, `CBCopilot/src/backend/services/`, `CBCopilot/src/backend/api/v1/admin/`, `CBCopilot/src/admin/src/sections/` + `panels/`, `CBCopilot/config/deployment_backend.json`, `CBCopilot/src/backend/core/config.py`.
- Output: a markdown delta — three sections (services, runtime controls, storage) with `MISSING IN DOC`, `MISSING IN CODE`, `DRIFTED` rows.
- Optional: a "warm" mode that re-emits the §5 runtime control table from source, so the developer can paste-replace.

Keep this file updated when the decision changes. Don't delete on revisit — turn it into a "shipped: see X" record.
