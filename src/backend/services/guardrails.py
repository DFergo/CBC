"""Pre-LLM content filter — runtime guardrails layer.

Adapted from HRDDHelper/src/backend/services/guardrails.py. The tables are
HRDD's generic safety rules (hate speech + prompt injection) with one CBC
tweak — the "workers from X are fired" pattern was too prone to false
positives for legitimate CBA discussions; the `fired` verb has been dropped
from that clause's verb list (deported / removed / eliminated remain, as
the intent signal there is unambiguous).

Sprint 7.5 decision (D1=B): NO separate `fabrication` category. CBC's user
population is trade-union delegates authenticated through the Contacts
allowlist — the `guardrails.md` prompt layer already tells the LLM to
refuse fabrication; if a delegate tries to jailbreak their way through,
that's on them.

On a triggered message, the polling loop:
1. Records the match (counter + log)
2. Skips the LLM entirely — the user's turn is persisted but the model
   does not see it. A fixed response is pushed as the assistant message.
3. When `violations >= guardrail_max_triggers`, the session is flagged
   and marked `completed`; the user sees the localised session-ended
   message. This matches HRDD's Sprint 16 enforcement (D3=A).

See SPEC §4.10 + lessons-learned §5.
"""
import logging
import re
from typing import NamedTuple

from src.core.config import config as backend_config

logger = logging.getLogger("guardrails")


class GuardrailResult(NamedTuple):
    triggered: bool
    response: str   # Fixed response in session language (empty if not triggered)
    category: str   # "hate_speech" | "prompt_injection" | "" (empty if not triggered)


# --- Pattern definitions (HRDD base, one CBC tweak) ---

_HATE_PATTERNS: list[re.Pattern] = [
    # Dehumanising slurs (multi-lingual core vocabulary)
    re.compile(r"\b(subhuman|untermenschen?|cockroach(?:es)?|vermin|parasit(?:e|es|en))\b", re.IGNORECASE),
    # Explicit calls for violence against a group
    re.compile(r"\b(kill\s+(?:all|every|the)\s+\w+|exterminate|ethnic\s+cleansing|genocide)\b", re.IGNORECASE),
    # Racial / ethnic supremacy framing
    re.compile(r"\b(\w+\s+(?:supremacy|are\s+(?:inferior|subhuman|animals)))\b", re.IGNORECASE),
    # Discriminatory "workers from {group} should be [removed]" framing. CBC
    # tweak: `fired` is common in legitimate CBA contract discussions so we
    # drop it; `deported|removed|eliminated` keep the intent signal clear.
    re.compile(r"\b(workers?\s+from\s+\w+\s+(?:are|should\s+be)\s+(?:deported|removed|eliminated))\b", re.IGNORECASE),
]

_INJECTION_PATTERNS: list[re.Pattern] = [
    # Direct override attempts
    re.compile(r"ignore\s+(?:all\s+)?(?:your|previous|prior|above)\s+(?:instructions?|rules?|prompt)", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?(?:your|previous|prior|above)\s+(?:instructions?|rules?|prompt)", re.IGNORECASE),
    re.compile(r"forget\s+(?:all\s+)?(?:your|previous|prior|above)\s+(?:instructions?|rules?|prompt)", re.IGNORECASE),
    # Identity override
    re.compile(r"you\s+are\s+now\s+(?:a\s+)?(?:different|new|my)\s+", re.IGNORECASE),
    re.compile(r"(?:act|behave|pretend|respond)\s+as\s+(?:if\s+you\s+(?:are|were)\s+)?(?:a\s+)?(?:different|evil|unfiltered|unrestricted|jailbroken)", re.IGNORECASE),
    # System-prompt extraction
    re.compile(r"(?:show|reveal|print|output|repeat|display)\s+(?:me\s+)?(?:your|the)\s+(?:system\s+)?(?:prompt|instructions?|rules?)", re.IGNORECASE),
    re.compile(r"what\s+(?:are|is)\s+your\s+(?:system\s+)?(?:prompt|instructions?|initial\s+prompt)", re.IGNORECASE),
    # DAN-style jailbreaks + debug-mode traps
    re.compile(r"\bDAN\b.*(?:do\s+anything\s+now|no\s+restrictions)", re.IGNORECASE),
    re.compile(r"(?:developer|debug|admin|sudo|root)\s+mode", re.IGNORECASE),
]


# --- Fixed responses (CBC-themed; English / Spanish / French / German / Portuguese) ---

_FIXED_RESPONSES: dict[str, str] = {
    "en": "Your message contains content that conflicts with this system's ethical principles. I'm here to help with collective bargaining research and CBA comparison. If you'd like to continue on that basis, I'm ready to help.",
    "es": "Tu mensaje contiene contenido que entra en conflicto con los principios éticos de este sistema. Estoy aquí para ayudar con investigación de negociación colectiva y comparación de convenios. Si deseas continuar sobre esa base, estoy listo para ayudar.",
    "fr": "Votre message contient du contenu qui entre en conflit avec les principes éthiques de ce système. Je suis ici pour aider à la recherche sur la négociation collective et la comparaison de conventions. Si vous souhaitez continuer sur cette base, je suis prêt à vous aider.",
    "de": "Ihre Nachricht enthält Inhalte, die den ethischen Grundsätzen dieses Systems widersprechen. Ich bin hier, um bei der Recherche zu Tarifverhandlungen und beim Vergleich von Tarifverträgen zu helfen. Wenn Sie auf dieser Grundlage fortfahren möchten, bin ich bereit zu helfen.",
    "pt": "Sua mensagem contém conteúdo que conflita com os princípios éticos deste sistema. Estou aqui para ajudar com pesquisa sobre negociação coletiva e comparação de acordos. Se deseja continuar nessa base, estou pronto para ajudar.",
}

_SESSION_ENDED_RESPONSES: dict[str, str] = {
    "en": "This session has been ended due to repeated policy violations. If you need help with CBA research, please start a new session.",
    "es": "Esta sesión ha sido finalizada debido a violaciones repetidas de la política de uso. Si necesitas ayuda con investigación de convenios, por favor inicia una nueva sesión.",
    "fr": "Cette session a été terminée en raison de violations répétées de la politique d'utilisation. Si vous avez besoin d'aide pour la recherche sur les conventions collectives, veuillez démarrer une nouvelle session.",
    "de": "Diese Sitzung wurde aufgrund wiederholter Richtlinienverstöße beendet. Wenn Sie Hilfe bei der Recherche zu Tarifverträgen benötigen, starten Sie bitte eine neue Sitzung.",
    "pt": "Esta sessão foi encerrada devido a violações repetidas da política de uso. Se precisar de ajuda com pesquisa sobre acordos coletivos, por favor inicie uma nova sessão.",
}


def _localised(lang: str, ended: bool = False) -> str:
    table = _SESSION_ENDED_RESPONSES if ended else _FIXED_RESPONSES
    return table.get(lang) or table["en"]


# --- Public API ---

def check(content: str, language: str = "en") -> GuardrailResult:
    """Inspect a user message against the pattern tables.

    Non-triggering messages return `(False, "", "")`. Triggering messages
    return a fixed response the caller can surface AND the category for
    logging. The polling loop logs violations and increments the session's
    counter but continues processing normally in Sprint 6A.
    """
    for pattern in _HATE_PATTERNS:
        match = pattern.search(content)
        if match:
            logger.warning(f"Guardrail triggered (hate_speech): matched '{match.group()}'")
            return GuardrailResult(triggered=True, response=_localised(language), category="hate_speech")

    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(content)
        if match:
            logger.warning(f"Guardrail triggered (prompt_injection): matched '{match.group()}'")
            return GuardrailResult(triggered=True, response=_localised(language), category="prompt_injection")

    return GuardrailResult(triggered=False, response="", category="")


def session_ended_response(language: str = "en") -> str:
    """Text surfaced when the session is ended due to repeated violations.
    Sprint 6B wires this into a dedicated session-ended UI state.
    """
    return _localised(language, ended=True)


# --- Admin inspection helpers (Sprint 7.5) ---

_HUMAN_CATEGORY_LABELS: dict[str, str] = {
    "hate_speech": "Hate speech / dehumanising language",
    "prompt_injection": "Prompt injection + jailbreak attempts",
}


def get_patterns() -> list[dict[str, object]]:
    """Return the active patterns grouped by category for the admin viewer.

    Read-only. Patterns are source-code-hardcoded in v1; admin-editable
    rules are a future sprint if the tuning exercise demands it.
    """
    return [
        {
            "category": "hate_speech",
            "label": _HUMAN_CATEGORY_LABELS["hate_speech"],
            "patterns": [p.pattern for p in _HATE_PATTERNS],
        },
        {
            "category": "prompt_injection",
            "label": _HUMAN_CATEGORY_LABELS["prompt_injection"],
            "patterns": [p.pattern for p in _INJECTION_PATTERNS],
        },
    ]


def get_thresholds() -> dict[str, int]:
    """Expose the current warn / end thresholds from `BackendConfig`."""
    return {
        "warn_at": int(backend_config.guardrail_warn_at),
        "end_at": int(backend_config.guardrail_max_triggers),
    }


def get_sample_responses(language: str = "en") -> dict[str, str]:
    """Fixed responses the user sees on a trigger + at session-end."""
    return {
        "violation": _localised(language, ended=False),
        "session_ended": _localised(language, ended=True),
    }
