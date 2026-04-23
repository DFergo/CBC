# Prompt to paste into Claude Code inside the HRDDHelper repo

> Paste everything below into a fresh Claude Code session running against the
> HRDDHelper repository. Self-contained; the agent doesn't need prior context.
> The shape mirrors what landed in CBC (Collective Bargaining Copilot, the
> spin-off from HRDD) as Sprint 14 on 2026-04-24.

---

## Context

HRDD Helper and CBC share the same pull-inverse architecture: a FastAPI backend polls each frontend's sidecar over HTTP for queued messages, processes each through the LLM, streams tokens back via SSE. Historically the polling loop has been serial — one turn at a time across the entire deployment, regardless of how many users or frontends there are.

CBC closed Sprint 14 this week and refactored its polling loop to process chats in parallel, bounded by a user-configurable cap. You are porting the same changes to HRDD Helper. The pattern is a direct lift; the deltas are well-known.

## Goal

Let HRDD process up to N chat turns in parallel backend-wide, with N configurable from the admin panel. Default N = 4 to match the new `OLLAMA_NUM_PARALLEL=4` that Daniel set on the shared Mac Studio. Options exposed: **1, 2, 4, 6**.

## Files to modify

Work inside `HRDDHelper/` at the workspace root.

### 1. `src/backend/services/polling.py`

Replace the current serial tick pattern with parallel processing. The existing `_tick` likely has:

```python
async def _tick(client):
    for fe in registry.list_enabled():
        # health check
        # push thresholds/config
        # drain queue
        for msg in drained.get("messages") or []:
            await _process_message(client, fe, msg)
        # recovery / auth / uploads handlers (sequential is fine)
```

Change it to:

```python
async def _tick(client):
    _ensure_turn_semaphore()
    fes = list(registry.list_enabled())
    if not fes:
        return
    await asyncio.gather(
        *[_process_frontend(client, fe) for fe in fes],
        return_exceptions=True,
    )
```

Extract the per-frontend body into `_process_frontend(client, fe)` — health, push sync, drain, gather messages, recovery handlers, uploads. Inside, wrap the message processing in `asyncio.gather`:

```python
msg_tasks = [
    _process_message_safe(client, fe, msg, fid)
    for msg in drained.get("messages") or []
]
if msg_tasks:
    await asyncio.gather(*msg_tasks)
```

Add a `_process_message_safe` wrapper that acquires the global turn semaphore AND catches exceptions (so a crash in one task doesn't abort siblings):

```python
async def _process_message_safe(client, fe, msg, fid):
    sem = _turn_semaphore
    if sem is None:
        try:
            await _process_message(client, fe, msg)
        except Exception as e:
            logger.exception(f"Processing message from {fid} failed: {e}")
        return
    async with sem:
        try:
            await _process_message(client, fe, msg)
        except Exception as e:
            logger.exception(f"Processing message from {fid} failed: {e}")
```

Add module-level state + helper at the top of the file (near other module state):

```python
_turn_semaphore: asyncio.Semaphore | None = None
_turn_semaphore_cap: int = 0


def _ensure_turn_semaphore() -> None:
    """Called from `_tick`. Re-reads LLMConfig.max_concurrent_turns and
    resizes the semaphore if the cap changed. Tasks holding the old
    semaphore drain naturally into it; new tasks acquire the new one."""
    global _turn_semaphore, _turn_semaphore_cap
    # Adapt this import to wherever HRDD stores its LLM config pydantic model.
    # In CBC it's `src.services.llm_config_store.load_config()`. In HRDD it
    # may live in `src.core.config` or `src.services.llm_provider` — check.
    from src.services.llm_config_store import load_config  # ADAPT
    try:
        desired = int(load_config().max_concurrent_turns)
    except Exception:
        desired = 4
    if desired < 1:
        desired = 1
    if _turn_semaphore is None or desired != _turn_semaphore_cap:
        _turn_semaphore = asyncio.Semaphore(desired)
        _turn_semaphore_cap = desired
        logger.info(f"Turn semaphore (re)sized to {desired}")
```

### 2. Cancel watcher (depends on Sprint 13 cancel endpoint)

If HRDD **already has** a Sprint 13-style `POST /internal/chat/cancel/{token}` endpoint in its sidecar and some form of per-turn cancel polling in `polling.py`:

- Replace the per-turn polling with a module-level `_pending_cancellations: set[str]` plus a new `cancel_watcher_loop()` async function (sibling of `polling_loop`, same file) that polls each enabled frontend's `/internal/cancellations` every ~1 s and populates the set.
- Each `_process_turn` reads via `cancel_check=lambda: session_token in _pending_cancellations` and discards the token from the set in a `finally:` block on completion.
- Start `cancel_watcher_loop` from `main.py`'s lifespan alongside `polling_loop`.
- Reason: with parallel turns, per-turn drains race. First watcher to hit the sidecar clears the set for everyone. One central watcher + shared set is race-free.

If HRDD **does not have** Sprint 13 cancel/stop features yet: skip this block. The parallelism refactor still works without cancel. Flag it to Daniel as a known gap (Sprint 13 port owed to HRDD separately).

### 3. `src/backend/services/llm_config_store.py` (or wherever HRDD's `LLMConfig` pydantic model lives — CHECK)

Add a new field:

```python
max_concurrent_turns: Literal[1, 2, 4, 6] = 4
```

Next to existing top-level LLMConfig fields (compression, routing, etc.). Make sure `model_dump()` round-trips it — pydantic handles this automatically.

Existing configs without the field migrate transparently (default 4 on first load).

### 4. `src/backend/main.py`

If you added `cancel_watcher_loop` in step 2, start it in the lifespan alongside `polling_loop`:

```python
from src.services.polling import cancel_watcher_loop, polling_loop
...
poll_task = asyncio.create_task(polling_loop())
cancel_task = asyncio.create_task(cancel_watcher_loop())  # NEW
...
# on shutdown, cancel both
```

### 5. Admin TypeScript type — `src/admin/src/api.ts` (HRDD may call it something slightly different)

Add to the `LLMConfig` interface (or whatever HRDD's equivalent is called):

```typescript
max_concurrent_turns: 1 | 2 | 4 | 6
```

### 6. Admin i18n — wherever HRDD keeps its admin translations

Add two keys:

- `llm_max_concurrent_turns`: `"Max concurrent turns (backend-wide)"` (EN) / `"Máximo de turnos simultáneos (todo el backend)"` (ES)
- `llm_max_concurrent_turns_description`: a paragraph warning that the value MUST match `OLLAMA_NUM_PARALLEL` and LM Studio's Parallel, or excess turns queue invisibly inside the runtime.

Copy the full EN + ES strings from CBC's `CBCopilot/src/admin/src/i18n.ts` (search for `llm_max_concurrent_turns` in that file — the strings are ready to lift).

Other languages can fall back to EN via the project's existing partial-translations pattern.

### 7. Admin LLM UI — HRDD's `src/admin/src/LLMTab.tsx`

CBC has this inside `sections/LLMSection.tsx` (a section of GeneralTab); HRDD has it as its own top-level tab. The control itself is identical — a dropdown bound to the new field:

```tsx
<div className="mt-4 border border-gray-200 rounded-lg p-4">
  <div className="flex items-center justify-between mb-1">
    <h4 className="text-sm font-semibold text-gray-700">{t('llm_max_concurrent_turns')}</h4>
    <select
      value={cfg.max_concurrent_turns}
      onChange={e => setCfg(c => c ? { ...c, max_concurrent_turns: parseInt(e.target.value, 10) as 1 | 2 | 4 | 6 } : c)}
      className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
    >
      <option value={1}>1</option>
      <option value={2}>2</option>
      <option value={4}>4</option>
      <option value={6}>6</option>
    </select>
  </div>
  <p className="text-xs text-gray-500">
    {t('llm_max_concurrent_turns_description')}
  </p>
</div>
```

Place near whatever existing HRDD has for compression / summary routing / disable-thinking (if HRDD has those). If the `t()` function in HRDD's admin works differently from CBC's, adapt the call shape.

## Concurrency audit (same as CBC's)

Before calling this done, confirm these HRDD modules are safe for concurrent access across different sessions:

- `session_store` — per-session disk files + cache. Safe for different sessions running in parallel. Same session can't have two in-flight turns (UI locks input while streaming).
- Circuit breaker / `_fail_state` in `llm_provider.py` — module-level dict, simple add/clear ops are GIL-atomic. Benign miscounts under heavy contention, acceptable.
- `httpx.AsyncClient` — designed for concurrent use across tasks.

If HRDD has any module-level mutable state that isn't one of the above, evaluate whether two simultaneous turns could step on it. If in doubt, add an `asyncio.Lock` around the write path.

## Verification

After coding:

1. `python3 -m py_compile src/backend/services/polling.py src/backend/services/llm_config_store.py src/backend/main.py` — all clean.
2. Admin TypeScript compiles (the Docker build does this; don't run `docker compose build` locally unless Daniel asks — he deploys via Portainer).
3. Update HRDD's `docs/STATUS.md`, `docs/CHANGELOG.md`, and add an ADR describing the parallelism change (number it as the next free ADR in HRDD's series). Mirror the content structure from CBC's Sprint 14 entries if helpful — see `../W_LAIUNI_CBC/docs/STATUS.md` and `../W_LAIUNI_CBC/docs/architecture/decisions.md` in the sibling repo.
4. Offer `/git` at the end — Daniel commits + pushes, then re-pulls in Portainer to deploy.

## Constraints (same as always in HRDD)

- Do NOT modify `CLAUDE.md`, `.claude/`, or anything under `/.git`.
- Do NOT run `docker compose build` or `docker compose up` on the local Mac — Daniel deploys via Portainer. `py_compile` + admin tsc (via the Portainer build) is enough.
- Follow HRDD's commit message format (check `git log --oneline` for the convention — CBC uses `[sprint-N] <title>`).

## Sanity check if anything looks off

- If you can't find HRDD's `LLMConfig` pydantic model: grep for `class LLMConfig` or `max_tokens:` or `temperature:` — one of those will hit.
- If HRDD's polling loop structure looks very different from CBC's: adapt the spirit rather than the syntax. The key invariants are (a) `asyncio.gather` at the frontends level, (b) `asyncio.gather` at the messages-within-a-frontend level, (c) a single semaphore gating LLM-bound work, (d) semaphore resized from config per tick so admin changes land live.
- If HRDD doesn't have a separate `sidecar` main.py with `/internal/cancellations`: skip the cancel watcher entirely and note it as a follow-up.

## Live-test after deploy (Daniel's QA, not yours)

1. Two users on same frontend send simultaneously → both start streaming in ~1 s.
2. Five users → fifth queues with indicator if HRDD has one; otherwise queues silently in the semaphore.
3. Change admin dropdown 4 → 2 → next pair obeys new cap live.
4. (If cancel wired) Stop one of N parallel streams → only that cancels.

## Reference for reviewers

The CBC Sprint 14 commit + PR is the authoritative reference. Look at:

- `CBCopilot/src/backend/services/polling.py` for the full parallelism + semaphore + cancel-watcher pattern.
- `CBCopilot/src/backend/services/llm_config_store.py` for the `max_concurrent_turns` field.
- `CBCopilot/src/admin/src/sections/LLMSection.tsx` for the dropdown UI.
- `docs/architecture/decisions.md` ADR-008 for the rationale + concurrency audit.
- `docs/CHANGELOG.md` Sprint 14 entry for the full file list and verification steps.

Copy with understanding: HRDD is a sibling repo, not a subtree. Paths and module names differ.
