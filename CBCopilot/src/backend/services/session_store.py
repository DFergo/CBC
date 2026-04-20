"""Disk-backed session store with in-memory cache.

Adapted from HRDDHelper/src/backend/services/session_store.py (Sprint 8a
revision). CBC differences:
- Single user profile: no role/mode fields in session metadata.
- Survey fields are CBC's: company_slug, country, region, initial_query,
  comparison_scope (only set for Compare All).
- `destroyed` state: when privacy mode auto-destroy fires, the entire
  `/app/data/sessions/{token}/` tree is rm -rf'd (uploads + session RAG
  index + conversation log all gone). ADR-005.

Disk layout (SPEC §4.5):
    /app/data/sessions/{token}/
    ├── session.json        ← metadata (survey, status, timestamps, counters)
    ├── conversation.jsonl  ← one JSON line per message {role, content, timestamp}
    ├── uploads/            ← managed by session_rag.py
    └── rag_index/          ← managed by session_rag.py
"""
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.services._paths import SESSIONS_DIR, atomic_write_json

logger = logging.getLogger("session_store")


def _session_dir(token: str) -> Path:
    return SESSIONS_DIR / token


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """Disk-backed session store with in-memory cache of active sessions."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._loaded = False

    # --- Loading / persistence ---

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        count = 0
        for d in SESSIONS_DIR.iterdir():
            if not (d.is_dir() and (d / "session.json").exists()):
                continue
            try:
                meta = json.loads((d / "session.json").read_text())
                if meta.get("archived") or meta.get("status") == "destroyed":
                    continue
                self._cache[d.name] = {
                    "system_prompt": meta.get("system_prompt", ""),
                    "messages": self._load_conversation(d.name),
                    "survey": meta.get("survey", {}),
                    "language": meta.get("language", "en"),
                    "frontend_id": meta.get("frontend_id", ""),
                    "frontend_name": meta.get("frontend_name", ""),
                    "status": meta.get("status", "active"),
                    "flagged": meta.get("flagged", False),
                    "created_at": meta.get("created_at"),
                    "last_activity": meta.get("last_activity"),
                    "guardrail_violations": meta.get("guardrail_violations", 0),
                    "initial_query_injected": meta.get("initial_query_injected", False),
                }
                count += 1
            except Exception as e:
                logger.warning(f"Failed to load session {d.name}: {e}")
        if count:
            logger.info(f"Loaded {count} active sessions from disk")

    def _load_conversation(self, token: str) -> list[dict[str, Any]]:
        path = _session_dir(token) / "conversation.jsonl"
        if not path.exists():
            return []
        messages: list[dict[str, Any]] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning(f"Bad JSONL line in {token}")
        return messages

    def _save_meta(self, token: str) -> None:
        session = self._cache.get(token)
        if not session:
            return
        d = _session_dir(token)
        d.mkdir(parents=True, exist_ok=True)
        meta = {
            "survey": session.get("survey", {}),
            "language": session.get("language", "en"),
            "status": session.get("status", "active"),
            "flagged": session.get("flagged", False),
            "system_prompt": session.get("system_prompt", ""),
            "created_at": session.get("created_at"),
            "last_activity": session.get("last_activity"),
            "frontend_id": session.get("frontend_id", ""),
            "frontend_name": session.get("frontend_name", ""),
            "guardrail_violations": session.get("guardrail_violations", 0),
            "initial_query_injected": session.get("initial_query_injected", False),
        }
        atomic_write_json(d / "session.json", meta)

    def _append_message(
        self,
        token: str,
        role: str,
        content: str,
        timestamp: str,
        attachments: list[str] | None = None,
    ) -> None:
        d = _session_dir(token)
        d.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {"role": role, "content": content, "timestamp": timestamp}
        if attachments:
            entry["attachments"] = list(attachments)
        line = json.dumps(entry, ensure_ascii=False)
        with open(d / "conversation.jsonl", "a") as f:
            f.write(line + "\n")

    # --- Public API ---

    def init_session(
        self,
        token: str,
        system_prompt: str = "",
        survey: dict[str, Any] | None = None,
        language: str = "en",
        frontend_id: str = "",
        frontend_name: str = "",
    ) -> None:
        """Create a session or refresh its prompt + survey if it already exists."""
        self._ensure_loaded()
        now = _now()
        if token not in self._cache:
            self._cache[token] = {
                "system_prompt": system_prompt,
                "messages": [],
                "survey": survey or {},
                "language": language,
                "frontend_id": frontend_id,
                "frontend_name": frontend_name,
                "status": "active",
                "flagged": False,
                "created_at": now,
                "last_activity": now,
                "guardrail_violations": 0,
                "initial_query_injected": False,
            }
            logger.info(f"Session initialized: {token} (frontend={frontend_id!r}, company={(survey or {}).get('company_slug')!r})")
        else:
            self._cache[token]["system_prompt"] = system_prompt
            if survey:
                self._cache[token]["survey"] = survey
            if language:
                self._cache[token]["language"] = language
            if frontend_id:
                self._cache[token]["frontend_id"] = frontend_id
        self._save_meta(token)

    def exists(self, token: str) -> bool:
        self._ensure_loaded()
        return token in self._cache

    def add_message(
        self,
        token: str,
        role: str,
        content: str,
        attachments: list[str] | None = None,
    ) -> None:
        """Append a message to the session (memory + disk).

        When `attachments` is set, the raw filenames are stored alongside the
        message so the UI can render chips on the user bubble AND the LLM
        message-builder can decorate the content with an "attached this turn"
        signal (see `get_llm_messages`).
        """
        self._ensure_loaded()
        self._ensure_session(token)
        now = _now()
        entry: dict[str, Any] = {"role": role, "content": content, "timestamp": now}
        if attachments:
            entry["attachments"] = list(attachments)
        self._cache[token]["messages"].append(entry)
        self._cache[token]["last_activity"] = now
        self._append_message(token, role, content, now, attachments=attachments)
        self._save_meta(token)

    def _ensure_session(self, token: str) -> None:
        if token not in self._cache:
            now = _now()
            self._cache[token] = {
                "system_prompt": "",
                "messages": [],
                "survey": {},
                "language": "en",
                "frontend_id": "",
                "frontend_name": "",
                "status": "active",
                "flagged": False,
                "created_at": now,
                "last_activity": now,
                "guardrail_violations": 0,
                "initial_query_injected": False,
            }

    def get_llm_messages(self, token: str) -> list[dict[str, str]]:
        """Messages formatted for LLM input: system prompt first, then history
        (role + content only — timestamps stripped).

        When a user turn carries `attachments`, the content is decorated with
        a short "User attached this turn: …" prefix so the model knows a new
        file arrived with this message. The raw content on disk stays clean.
        `assistant_summary` is coerced to `assistant` so the LLM sees a normal
        conversation history.
        """
        self._ensure_loaded()
        self._ensure_session(token)
        session = self._cache[token]
        out: list[dict[str, str]] = []
        if session["system_prompt"]:
            out.append({"role": "system", "content": session["system_prompt"]})
        for msg in session["messages"]:
            content = msg["content"]
            role = msg["role"]
            if role == "user" and msg.get("attachments"):
                files = ", ".join(msg["attachments"])
                content = f"[The user attached this turn: {files}]\n\n{content}"
            out.append({"role": "assistant" if role == "assistant_summary" else role, "content": content})
        return out

    def get_session(self, token: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return self._cache.get(token)

    def list_sessions(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        out: list[dict[str, Any]] = []
        for token, data in self._cache.items():
            survey = data.get("survey", {})
            out.append({
                "token": token,
                "frontend_id": data.get("frontend_id", ""),
                "frontend_name": data.get("frontend_name", ""),
                "company_slug": survey.get("company_slug", ""),
                "company_display_name": survey.get("company_display_name", ""),
                "is_compare_all": bool(survey.get("is_compare_all")),
                "country": survey.get("country", ""),
                "message_count": len(data.get("messages", [])),
                "status": data.get("status", "active"),
                "flagged": data.get("flagged", False),
                "guardrail_violations": data.get("guardrail_violations", 0),
                "created_at": data.get("created_at"),
                "last_activity": data.get("last_activity"),
            })
        return out

    # --- Flags / counters ---

    def toggle_flag(self, token: str) -> bool:
        self._ensure_loaded()
        session = self._cache.get(token)
        if not session:
            return False
        session["flagged"] = not session.get("flagged", False)
        self._save_meta(token)
        return session["flagged"]

    def increment_guardrail_violations(self, token: str) -> int:
        self._ensure_loaded()
        session = self._cache.get(token)
        if not session:
            return 0
        count = int(session.get("guardrail_violations", 0)) + 1
        session["guardrail_violations"] = count
        self._save_meta(token)
        return count

    def set_status(self, token: str, status: str) -> None:
        self._ensure_loaded()
        session = self._cache.get(token)
        if session:
            session["status"] = status
            self._save_meta(token)

    def mark_initial_query_injected(self, token: str) -> None:
        """Flip the `initial_query_injected` bit so the polling loop doesn't
        re-inject the same survey query on every poll."""
        self._ensure_loaded()
        session = self._cache.get(token)
        if session and not session.get("initial_query_injected"):
            session["initial_query_injected"] = True
            self._save_meta(token)

    # --- Archive / destroy ---

    def archive_session(self, token: str) -> None:
        """Mark as archived in session.json; files stay on disk for audit.
        Drops from in-memory cache (next load skips archived sessions).
        """
        session = self._cache.get(token)
        if session:
            session["archived"] = True
            session["archived_at"] = _now()
            self._save_meta(token)
        else:
            p = _session_dir(token) / "session.json"
            if p.exists():
                try:
                    meta = json.loads(p.read_text())
                    meta["archived"] = True
                    meta["archived_at"] = _now()
                    atomic_write_json(p, meta)
                except Exception as e:
                    logger.warning(f"Failed to archive {token} on disk: {e}")
        self._cache.pop(token, None)
        logger.info(f"Session archived: {token}")

    def destroy_session(self, token: str) -> bool:
        """ADR-005 privacy wipe: rm -rf `/app/data/sessions/{token}/`. Also
        drops the session_rag + context_compressor caches. Returns True if
        anything existed."""
        self._cache.pop(token, None)
        # session_rag stores under the same tree — single rmtree covers both
        d = _session_dir(token)
        existed = d.exists()
        if existed:
            shutil.rmtree(d, ignore_errors=True)
        # Belt-and-suspenders: clear in-memory caches held by other services
        try:
            from src.services import session_rag
            session_rag.destroy_session(token)
        except Exception:
            pass
        try:
            from src.services import context_compressor
            context_compressor.forget_session(token)
        except Exception:
            pass
        if existed:
            logger.info(f"Session destroyed (full wipe): {token}")
        return existed


# Singleton
store = SessionStore()
