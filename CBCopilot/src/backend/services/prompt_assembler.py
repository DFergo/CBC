"""Assemble the system prompt from the 3-tier stack + survey context + RAG.

Layers (SPEC §4.1):

    [core.md]               ← resolved company → frontend → global
    [guardrails.md]         ← resolved company → frontend → global
    [role prompt]
      ├─ cba_advisor.md     ← single-company mode
      └─ compare_all.md     ← Compare All mode (skips company tier)
    [context_template.md]   ← rendered with survey variables
    [knowledge]             ← glossary (language-aware) + organizations (resolver)
    [RAG chunks]            ← scope-aware: company / frontend / global / session

Inputs come from Sprint 4B's resolvers (prompts, orgs), Sprint 5's RAG
service (scope-keyed indexes), and the session's survey data.

Guardrails + core are non-negotiable — even if a company-tier override
replaces the role prompt, core + guardrails still land first (lessons-
learned #5).
"""
import logging
from dataclasses import dataclass
from typing import Any

from src.services import (
    knowledge_store,
    rag_service,
    resolvers,
    session_rag,
)

logger = logging.getLogger("prompt_assembler")

# Per SPEC §4.2 — admin-configurable later.
RAG_TOP_K_PER_SCOPE = 5


@dataclass
class AssembledPrompt:
    """Debug-friendly view of what went into the system prompt."""
    text: str
    layers: dict[str, str]       # "core" → rendered text, "guardrails" → ..., etc.
    rag_chunks_used: int
    rag_paths: list[dict[str, Any]]


# --- Layer 1-2: core + guardrails ---

def _resolve_fixed(name: str, frontend_id: str | None, company_slug: str | None) -> str:
    r = resolvers.resolve_prompt(name, frontend_id, company_slug, is_compare_all=False)
    return (r.content or "").strip()


# --- Layer 3: role prompt ---

def _resolve_role(frontend_id: str | None, company_slug: str | None, is_compare_all: bool) -> str:
    name = "compare_all.md" if is_compare_all else "cba_advisor.md"
    r = resolvers.resolve_prompt(name, frontend_id, company_slug, is_compare_all=is_compare_all)
    return (r.content or "").strip()


# --- Layer 4: context template ---

def _render_context(template: str, survey: dict[str, Any], language: str) -> str:
    """Naive `{var}` substitution — no Jinja. Missing vars → empty string.

    Template variables covered (SPEC §4.1):
    - flat:  company, country, region, name, organization, position, language,
             query, comparison_scope
    - derived blocks (empty when irrelevant):
      - `comparison_scope_line`: one-line scope when Compare All, else empty
      - `identity_block`: the optional name/org/position lines when the user
        filled them in; empty when they kept the session anonymous
    """
    company = survey.get("company_display_name") or survey.get("company_slug") or ""
    name = (survey.get("name") or "").strip()
    org = (survey.get("organization") or "").strip()
    position = (survey.get("position") or "").strip()
    comparison_scope = (survey.get("comparison_scope") or "").strip()
    is_compare_all = bool(survey.get("is_compare_all"))

    # Derived blocks
    comparison_scope_line = (
        f"- **Comparison scope:** {comparison_scope}" if (is_compare_all and comparison_scope) else ""
    )
    identity_parts: list[str] = []
    if name:
        identity_parts.append(f"- **Name:** {name}")
    if org:
        identity_parts.append(f"- **Organization:** {org}")
    if position:
        identity_parts.append(f"- **Position:** {position}")
    identity_block = "\n".join(identity_parts)

    vars_ = {
        "company": company,
        "country": survey.get("country", ""),
        "region": survey.get("region", ""),
        "name": name,
        "organization": org,
        "position": position,
        "language": language,
        "query": survey.get("initial_query", ""),
        "comparison_scope": comparison_scope,
        "comparison_scope_line": comparison_scope_line,
        "identity_block": identity_block,
    }
    out = template
    for k, v in vars_.items():
        out = out.replace("{" + k + "}", str(v))
    # Collapse double blank lines left behind by empty derived blocks
    while "\n\n\n" in out:
        out = out.replace("\n\n\n", "\n\n")
    return out.strip()


# --- Layer 5: knowledge ---

def _render_glossary(language: str) -> str:
    """Render the glossary as a compact reference block in the session's language."""
    try:
        terms = knowledge_store.list_glossary_terms()
    except Exception as e:
        logger.warning(f"Could not load glossary: {e}")
        return ""
    if not terms:
        return ""
    lines = ["## Glossary (for reference)"]
    for t in terms:
        data = t.model_dump() if hasattr(t, "model_dump") else dict(t)
        term = data.get("term", "")
        translations = data.get("translations") or {}
        localised = translations.get(language) or term
        definition = (data.get("definition") or "").strip()
        if term and definition:
            lines.append(f"- **{localised}** ({term}): {definition}")
    return "\n".join(lines)


def _render_orgs(frontend_id: str | None) -> str:
    """Organizations list resolved per-frontend (inherit / own / combine)."""
    try:
        result = resolvers.resolve_orgs(frontend_id)
    except Exception as e:
        logger.warning(f"Could not resolve orgs: {e}")
        return ""
    orgs = result.get("organizations") or []
    if not orgs:
        return ""
    lines = ["## Organizations (unions / federations the user may reference)"]
    for o in orgs:
        name = o.get("name", "")
        desc = (o.get("description") or "").strip()
        if name:
            lines.append(f"- **{name}**: {desc}" if desc else f"- {name}")
    return "\n".join(lines)


# --- Layer 6: RAG ---

def _resolve_rag(
    frontend_id: str | None,
    company_slug: str | None,
    is_compare_all: bool,
    survey: dict[str, Any],
    query_text: str,
    session_token: str | None,
) -> tuple[list[rag_service.Chunk], list[dict[str, Any]]]:
    """Run the Sprint 5 query stack. Returns (chunks, raw_paths_for_debug)."""
    if not frontend_id:
        return [], []
    paths = resolvers.resolve_rag_paths(
        frontend_id=frontend_id,
        company_slug=company_slug,
        is_compare_all=is_compare_all,
        comparison_scope=survey.get("comparison_scope"),
        user_country=survey.get("country"),
    )
    scope_keys = [p["scope_key"] or "global" for p in paths.paths]
    chunks = rag_service.query_scopes(scope_keys, query_text, top_k_per_scope=RAG_TOP_K_PER_SCOPE)
    # Plus the session's own uploads, if any
    if session_token:
        try:
            session_chunks = session_rag.query(session_token, query_text, top_k=RAG_TOP_K_PER_SCOPE)
            for c in session_chunks:
                chunks.append(
                    rag_service.Chunk(
                        text=c["text"],
                        score=c["score"],
                        source=c["source"],
                        tier="session",
                        scope_key=c["scope_key"],
                    )
                )
        except Exception as e:
            logger.warning(f"Session RAG query failed for {session_token}: {e}")
    # Rerank: sort by score desc
    chunks.sort(key=lambda c: c.score, reverse=True)
    return chunks, [
        {"tier": p["tier"], "scope_key": p["scope_key"], "doc_count": p["doc_count"]}
        for p in paths.paths
    ]


def _render_chunks(chunks: list[rag_service.Chunk], max_chunks: int) -> str:
    if not chunks:
        return ""
    take = chunks[:max_chunks]
    lines = ["## Retrieved CBA / policy excerpts"]
    for c in take:
        lines.append(f"\n### Source: {c.source}  (tier={c.tier})")
        lines.append(c.text.strip())
    return "\n".join(lines)


# --- Top-level assembly ---

def assemble(
    survey: dict[str, Any],
    frontend_id: str | None,
    language: str = "en",
    query_text: str | None = None,
    session_token: str | None = None,
    max_rag_chunks: int = 20,
) -> AssembledPrompt:
    """Build the system prompt for a session's next LLM call.

    `query_text` drives the RAG retrieval — typically the user's latest turn.
    For the first turn (initial query injection), pass `survey.initial_query`.
    """
    company_slug = survey.get("company_slug") or None
    is_compare_all = bool(survey.get("is_compare_all"))
    q = query_text or survey.get("initial_query") or ""

    core_text = _resolve_fixed("core.md", frontend_id, company_slug)
    guardrails_text = _resolve_fixed("guardrails.md", frontend_id, company_slug)
    role_text = _resolve_role(frontend_id, company_slug, is_compare_all)

    template_raw = _resolve_fixed("context_template.md", frontend_id, company_slug)
    context_text = _render_context(template_raw, survey, language) if template_raw else ""

    glossary_text = _render_glossary(language)
    orgs_text = _render_orgs(frontend_id)

    chunks, rag_paths = _resolve_rag(
        frontend_id=frontend_id,
        company_slug=company_slug,
        is_compare_all=is_compare_all,
        survey=survey,
        query_text=q,
        session_token=session_token,
    )
    rag_text = _render_chunks(chunks, max_chunks=max_rag_chunks)

    layers = {
        "core": core_text,
        "guardrails": guardrails_text,
        "role": role_text,
        "context": context_text,
        "glossary": glossary_text,
        "organizations": orgs_text,
        "rag": rag_text,
    }
    ordered = [v for v in (core_text, guardrails_text, role_text, context_text, glossary_text, orgs_text, rag_text) if v]
    text = "\n\n".join(ordered).strip()
    return AssembledPrompt(
        text=text,
        layers=layers,
        rag_chunks_used=min(len(chunks), max_rag_chunks),
        rag_paths=rag_paths,
    )
