"""Sprint 8 auto-translate for branding disclaimer / instructions text.

Fills in `disclaimer_text_translations` and `instructions_text_translations`
for every language in LANGUAGE_CODES that is not already populated, running
the summariser LLM slot (with the standard fallback chain in llm_provider).

Called from admin endpoints, synchronously — translating 30 targets × 2
blocks × one round-trip each takes ~30-60 s on a typical local model, which
is acceptable for an admin action. The UI shows a spinner.

The translation prompt lives in src/backend/prompts/translate.md so admins
can tune it via the file watcher without redeploying.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

from src.services.branding_store import Branding
from src.services.llm_provider import chat as llm_chat

logger = logging.getLogger("branding_translator")

# Must match the frontend's i18n.ts LANGUAGES list. Exported so the admin API
# can show coverage without duplicating the list.
LANGUAGE_CODES: tuple[str, ...] = (
    "en", "es", "fr", "de", "pt", "it", "nl", "pl", "sv", "hu", "el", "ro",
    "hr", "uk", "ru", "tr", "ar", "ur", "zh", "ja", "ko", "vi", "th", "id",
    "hi", "bn", "mr", "te", "ta", "xh", "sw",
)

# Human-readable names used inside the translate.md prompt (so the LLM knows
# *into* which language it's translating — plain ISO codes alone are too terse).
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "pl": "Polish",
    "sv": "Swedish", "hu": "Hungarian", "el": "Greek", "ro": "Romanian",
    "hr": "Croatian", "uk": "Ukrainian", "ru": "Russian", "tr": "Turkish",
    "ar": "Arabic", "ur": "Urdu", "zh": "Simplified Chinese", "ja": "Japanese",
    "ko": "Korean", "vi": "Vietnamese", "th": "Thai", "id": "Indonesian",
    "hi": "Hindi", "bn": "Bengali", "mr": "Marathi", "te": "Telugu",
    "ta": "Tamil", "xh": "Xhosa", "sw": "Swahili",
}

TextKind = Literal["disclaimer", "instructions"]

_PROMPT_NAMES: tuple[Path, ...] = (
    Path("/app/data/prompts/translate.md"),
    Path(__file__).parent.parent / "prompts" / "translate.md",
)


def _load_prompt_template() -> str:
    """Load translate.md — prefer the admin-editable copy on disk, fall back
    to the image-shipped default. Same pattern as other CBC prompts."""
    for p in _PROMPT_NAMES:
        try:
            if p.exists():
                return p.read_text()
        except OSError as e:
            logger.warning(f"Cannot read {p}: {e}")
    raise RuntimeError("translate.md not found in /app/data/prompts or backend prompts/")


def _build_messages(source_text: str, source_lang: str, target_lang: str) -> list[dict[str, str]]:
    template = _load_prompt_template()
    source_name = LANGUAGE_NAMES.get(source_lang, source_lang)
    target_name = LANGUAGE_NAMES.get(target_lang, target_lang)
    system = (
        template
        .replace("{source_language}", source_name)
        .replace("{target_language}", target_name)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": source_text},
    ]


async def _translate_one(
    source_text: str,
    source_lang: str,
    target_lang: str,
    frontend_id: str | None,
) -> str:
    """One round-trip through the summariser slot. Returns the translation,
    stripped of surrounding whitespace. Raises on LLM failure — caller decides
    whether to swallow per-language or fail the whole job."""
    messages = _build_messages(source_text, source_lang, target_lang)
    out = await llm_chat(messages, slot="summariser", frontend_id=frontend_id)
    return out.strip()


async def auto_translate_branding(
    branding: Branding,
    frontend_id: str | None = None,
    overwrite: bool = False,
) -> tuple[Branding, dict[str, int]]:
    """Fill missing `*_text_translations` keys for the 31 i18n languages.

    - Source language comes from `branding.source_language` (default "en").
    - For each of {disclaimer_text, instructions_text} that is non-empty:
      for every target language ≠ source, if the slot is empty (or
      `overwrite=True`), call the LLM. Existing non-empty translations are
      preserved unless `overwrite=True`.
    - Failures per language are logged and skipped — the job returns whatever
      it managed to fill. The stats dict reports per-block success counts.

    Returns (updated_branding, {"disclaimer_filled": N, "instructions_filled": M,
    "disclaimer_failed": X, "instructions_failed": Y}).
    """
    source_lang = (branding.source_language or "en").strip() or "en"
    targets = [c for c in LANGUAGE_CODES if c != source_lang]

    stats = {
        "disclaimer_filled": 0,
        "disclaimer_failed": 0,
        "instructions_filled": 0,
        "instructions_failed": 0,
    }

    async def _fill(kind: TextKind, source_text: str, existing: dict[str, str]) -> dict[str, str]:
        out = dict(existing)
        if not source_text.strip():
            return out
        for tgt in targets:
            if not overwrite and out.get(tgt, "").strip():
                continue
            try:
                translated = await _translate_one(source_text, source_lang, tgt, frontend_id)
                if translated:
                    out[tgt] = translated
                    stats[f"{kind}_filled"] += 1
                else:
                    stats[f"{kind}_failed"] += 1
                    logger.warning(f"auto-translate {kind} → {tgt}: empty LLM output")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                stats[f"{kind}_failed"] += 1
                logger.warning(f"auto-translate {kind} → {tgt}: {e}")
        return out

    # Run sequentially — the summariser slot is typically a single-threaded
    # local model; parallel calls would just queue inside LM Studio / Ollama
    # and give no speedup while making failure logs messier.
    disc = await _fill("disclaimer", branding.disclaimer_text, branding.disclaimer_text_translations)
    instr = await _fill("instructions", branding.instructions_text, branding.instructions_text_translations)

    updated = Branding(**{
        **branding.model_dump(),
        "disclaimer_text_translations": disc,
        "instructions_text_translations": instr,
    })
    return updated, stats
