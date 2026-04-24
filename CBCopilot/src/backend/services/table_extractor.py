"""Structured table extraction for Sprint 16.

Trade unions reading CBAs want numbers — salary schedules, shift tables, overtime
rates. Vector RAG handles prose well but blurs tables: BGE-M3 embeds the table
structure + digits as one opaque vector that rarely wins a retrieval race
against prose chunks talking about the same topic. Contextual Retrieval
partially helps for prose but doesn't fix tables either.

This module treats tables as first-class data: at ingest we detect and extract
every table from the source document, persist each one as a standalone CSV, and
build a small metadata "card" (name + description + source location) that gets
embedded into a separate Chroma collection (`cbc_tables`). At query time the
prompt assembler retrieves the top-K relevant cards alongside the top-K prose
chunks and injects the matched tables' raw CSV into the prompt under a
`## Relevant tables` section.

What this gets us:
- Queries like "dame la tabla salarial" return the table verbatim, not a
  paraphrase. The LLM can do arithmetic on real numbers.
- Compare All mode side-by-sides two companies' salary tables natively.
- CR becomes optional (its hardest use case is covered).

Scanned PDFs (image-only) extract nothing via pdfplumber; we accept that as
low-fidelity rather than bolt on Tesseract. The source doc still goes through
the normal RAG pipeline so the chat keeps working on the surrounding prose.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Iterable

from src.services._paths import DATA_DIR, CAMPAIGNS_DIR, DOCUMENTS_DIR, company_dir, frontend_dir

logger = logging.getLogger("table_extractor")


# --- Data model -------------------------------------------------------------

@dataclass
class TableSpec:
    """Canonical representation of one extracted table.

    `id` is derived from a hash of the CSV content so re-extracting the same
    table on the same document produces a stable id (enables idempotent
    re-index and chroma upsert without duplicates).
    """

    id: str
    doc_name: str
    name: str
    description: str
    source_location: str  # heading for .md; "page N" for .pdf
    csv_text: str
    columns: list[str]
    row_count: int

    def as_card_text(self) -> str:
        """The string embedded into the `cbc_tables` Chroma collection. Kept
        short and high-signal — retrieval matches the query against this, not
        the CSV itself. Including the column list gives BM25/vector enough
        surface to match queries that name a column like "salario base"."""
        cols = ", ".join(self.columns) if self.columns else ""
        parts = [
            f"Table: {self.name}",
            f"Document: {self.doc_name}",
            f"Location: {self.source_location}",
        ]
        if self.description and self.description != self.name:
            parts.append(f"Description: {self.description}")
        if cols:
            parts.append(f"Columns: {cols}")
        parts.append(f"Row count: {self.row_count}")
        return "\n".join(parts)

    def as_manifest_dict(self) -> dict[str, Any]:
        """What goes into manifest.json. CSV text excluded to keep the manifest
        small — the CSV lives in its own file."""
        d = asdict(self)
        d.pop("csv_text", None)
        return d


# --- Markdown table extraction ---------------------------------------------

# Markdown pipe-table row. Leading/trailing `|` optional, we require at least
# one internal `|` to reject plain text that happens to contain a single `|`.
_PIPE_ROW = re.compile(r"^\s*\|?(?:[^|\n]*\|){1,}[^|\n]*\|?\s*$")
# Separator row that marks "the header above is actually a table header":
# |---|---| or | :---: | ---: | etc. Dashes + optional colons, at least one `|`.
_SEP_ROW = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*){1,}\|?\s*$")
# Heading line we attribute the table to.
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _split_md_row(raw: str) -> list[str]:
    """Split a pipe-table row into its cells. Strips surrounding whitespace
    and the optional leading/trailing pipes. Doesn't handle escaped pipes
    (`\\|`) — CBAs don't use them in practice."""
    s = raw.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _rows_to_csv(rows: list[list[str]]) -> str:
    """Serialise a list of cell-rows as RFC-4180 CSV. Python's csv module
    handles quoting + commas inside cells correctly; we just feed it."""
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _nearby_prose(lines: list[str], table_end_idx: int, window: int = 3) -> str:
    """Return up to `window` non-blank lines of prose immediately BEFORE the
    table start, excluding headings (they're captured separately as
    source_location). Used to autogenerate the table description."""
    # We're called with the last line of the table; walk backwards to its
    # start, then scan further back for prose.
    i = table_end_idx
    # Rewind to table start (contiguous pipe rows + separator).
    while i > 0 and (_PIPE_ROW.match(lines[i]) or _SEP_ROW.match(lines[i])):
        i -= 1
    # Now collect up to `window` non-empty, non-heading lines above.
    collected: list[str] = []
    j = i
    while j > 0 and len(collected) < window:
        j -= 1
        ln = lines[j].rstrip()
        if not ln.strip():
            if collected:
                break  # blank line ends the prose block
            continue
        if _HEADING.match(ln):
            break
        collected.append(ln)
    return " ".join(reversed(collected)).strip()


def _heading_chain(lines: list[str], table_start_idx: int) -> str:
    """Walk upwards from table_start and return the chain of enclosing
    headings as "H1 › H2 › H3". Duplicate-level headings replace their
    ancestor at the same level. Gives the admin a meaningful location like
    "ANEXO I › Tabla A — Salario base" instead of just the nearest `###`."""
    chain: dict[int, str] = {}
    for idx in range(table_start_idx - 1, -1, -1):
        m = _HEADING.match(lines[idx])
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2).strip()
        # Only the deepest-seen at each level sticks — we walk upward so
        # earlier lines are ancestors (shallower) but headings at a level
        # lower than one already seen are nested and shouldn't overwrite.
        if level not in chain:
            chain[level] = text
        if level == 1:
            break  # reached the root of the doc
    if not chain:
        return ""
    ordered = [chain[k] for k in sorted(chain.keys())]
    return " › ".join(ordered)


def extract_markdown_tables(md_text: str, doc_name: str) -> list[TableSpec]:
    """Scan a markdown document for pipe-tables and return a TableSpec per
    detected table. A valid pipe-table is: one header row, one separator row
    (---|---), and at least one data row.

    Handles:
    - Tables without a leading/trailing `|` on each row.
    - Cells containing commas or internal whitespace.
    - Multiple tables in the same document (each independent).
    - Heading chains for source_location ("ANEXO I › Tabla A — Salario base").
    """
    lines = md_text.splitlines()
    tables: list[TableSpec] = []

    i = 0
    while i < len(lines) - 2:
        # Look for: pipe row + separator + at least one pipe row below.
        if not _PIPE_ROW.match(lines[i]):
            i += 1
            continue
        if not _SEP_ROW.match(lines[i + 1]):
            i += 1
            continue
        # Found a header + separator. Grab contiguous data rows below.
        header_cells = _split_md_row(lines[i])
        data_rows: list[list[str]] = []
        k = i + 2
        while k < len(lines) and _PIPE_ROW.match(lines[k]) and not _SEP_ROW.match(lines[k]):
            cells = _split_md_row(lines[k])
            # Pad / trim to header width.
            if len(cells) < len(header_cells):
                cells += [""] * (len(header_cells) - len(cells))
            elif len(cells) > len(header_cells):
                cells = cells[: len(header_cells)]
            data_rows.append(cells)
            k += 1
        if not data_rows:
            i = k
            continue

        csv_text = _rows_to_csv([header_cells, *data_rows])
        location = _heading_chain(lines, i) or "(no heading)"
        description = _nearby_prose(lines, k - 1) or location
        # A cleaner display name: use the deepest heading if we found one,
        # otherwise fall back to the first column header pattern.
        if " › " in location:
            name = location.rsplit(" › ", 1)[-1]
        elif location and location != "(no heading)":
            name = location
        else:
            name = f"Table ({', '.join(header_cells[:3])})"

        tid = hashlib.sha1(csv_text.encode("utf-8")).hexdigest()[:16]
        tables.append(
            TableSpec(
                id=tid,
                doc_name=doc_name,
                name=name,
                description=description,
                source_location=location,
                csv_text=csv_text,
                columns=header_cells,
                row_count=len(data_rows),
            )
        )
        i = k

    if tables:
        logger.info(f"md tables: {doc_name} → {len(tables)} tables")
    return tables


# --- PDF table extraction ---------------------------------------------------

def extract_pdf_tables(pdf_path: Path, doc_name: str) -> list[TableSpec]:
    """Extract tables from a vector PDF via pdfplumber. Returns `[]` with a
    WARN log for scanned / image-only PDFs — that's the accepted low-fidelity
    behaviour for Sprint 16 (no OCR fallback)."""
    try:
        import pdfplumber
    except ImportError:
        logger.error(
            "pdfplumber not installed — PDF table extraction disabled. "
            "Add `pdfplumber>=0.11` to requirements.txt and rebuild the image."
        )
        return []

    tables: list[TableSpec] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                try:
                    raw_tables = page.extract_tables() or []
                except Exception as e:
                    logger.warning(f"pdf tables: {doc_name} p{page_idx} extract failed: {e}")
                    continue
                for t_idx, raw in enumerate(raw_tables, start=1):
                    if not raw or len(raw) < 2:
                        continue
                    # pdfplumber returns rows of Optional[str]; normalise None → "".
                    header = [(c or "").strip() for c in raw[0]]
                    data = [[(c or "").strip() for c in r] for r in raw[1:]]
                    if not any(any(c for c in r) for r in data):
                        continue  # empty grid from a scanned page
                    csv_text = _rows_to_csv([header, *data])
                    location = f"page {page_idx}"
                    if len(raw_tables) > 1:
                        location += f" (table {t_idx})"
                    name = f"Table p{page_idx}" if len(raw_tables) == 1 else f"Table p{page_idx}.{t_idx}"
                    tid = hashlib.sha1(csv_text.encode("utf-8")).hexdigest()[:16]
                    tables.append(
                        TableSpec(
                            id=tid,
                            doc_name=doc_name,
                            name=name,
                            description=name,
                            source_location=location,
                            csv_text=csv_text,
                            columns=header,
                            row_count=len(data),
                        )
                    )
    except Exception as e:
        logger.warning(f"pdf tables: {doc_name} open failed: {e}")
        return []

    if tables:
        logger.info(f"pdf tables: {doc_name} → {len(tables)} tables across {page_idx} pages")
    else:
        logger.info(
            f"pdf tables: {doc_name} → 0 tables extracted "
            f"(vector PDF without tables, or scanned / image-only PDF)"
        )
    return tables


# --- Dispatcher -------------------------------------------------------------

def extract_tables_for_file(doc_path: Path) -> list[TableSpec]:
    """Route to the right extractor by extension. Unsupported types return
    `[]` silently."""
    ext = doc_path.suffix.lower()
    name = doc_path.name
    if ext == ".md":
        try:
            text = doc_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"md tables: {name} read failed: {e}")
            return []
        return extract_markdown_tables(text, name)
    if ext == ".pdf":
        return extract_pdf_tables(doc_path, name)
    return []


# --- Persistence layer ------------------------------------------------------
#
# Tables live alongside the scope's documents so deleting a scope's docs
# neatly takes the extracted tables with it. Layout:
#
#   /app/data/tables/{doc_stem}/{table_id}.csv + manifest.json            (global)
#   /app/data/campaigns/{fid}/tables/{doc_stem}/...                       (frontend)
#   /app/data/campaigns/{fid}/companies/{slug}/tables/{doc_stem}/...      (company)
#
# `doc_stem` = filename without extension, sanitised for filesystem use.


def _sanitise(s: str) -> str:
    """Strip `/` and normalise control chars so doc names like
    `CBA/Amcor.md` can't escape the tables directory."""
    return re.sub(r"[^\w\-.]+", "_", s).strip("._") or "unnamed"


def tables_root_for(scope_key: str) -> Path:
    if scope_key == "global":
        return DATA_DIR / "tables"
    parts = scope_key.split("/")
    if len(parts) == 1:
        return frontend_dir(parts[0]) / "tables"
    if len(parts) == 2:
        return company_dir(parts[0], parts[1]) / "tables"
    raise ValueError(f"Bad scope_key {scope_key!r}")


def tables_dir_for(scope_key: str, doc_name: str) -> Path:
    stem = _sanitise(Path(doc_name).stem)
    return tables_root_for(scope_key) / stem


def save_tables_for_doc(scope_key: str, doc_name: str, tables: list[TableSpec]) -> Path:
    """Persist one doc's tables. Wipes the doc's previous table dir first so
    re-extraction produces a clean state even when a table is removed from
    the source between runs. Writes manifest.json with all metadata + one
    {table_id}.csv per table. Returns the directory path."""
    dest = tables_dir_for(scope_key, doc_name)
    import shutil
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    manifest = {
        "doc_name": doc_name,
        "scope_key": scope_key,
        "tables": [t.as_manifest_dict() for t in tables],
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for t in tables:
        (dest / f"{t.id}.csv").write_text(t.csv_text, encoding="utf-8")
    return dest


def load_manifest(scope_key: str, doc_name: str) -> dict[str, Any] | None:
    """Read the stored manifest for one doc. Returns None if no manifest
    exists (doc never extracted, or had no tables)."""
    p = tables_dir_for(scope_key, doc_name) / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"manifest load failed for {scope_key}/{doc_name}: {e}")
        return None


def load_csv(scope_key: str, doc_name: str, table_id: str) -> str | None:
    """Read one table's CSV. Returns None if the file is missing."""
    p = tables_dir_for(scope_key, doc_name) / f"{table_id}.csv"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"csv load failed for {scope_key}/{doc_name}/{table_id}: {e}")
        return None


def list_scope_tables(scope_key: str) -> list[dict[str, Any]]:
    """Enumerate every table saved under a scope, grouped by doc. Used by the
    admin UI (TablesSection) to render the per-scope table list."""
    root = tables_root_for(scope_key)
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for doc_dir in sorted(root.iterdir()):
        if not doc_dir.is_dir():
            continue
        manifest_path = doc_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(m)
    return out


def delete_scope_tables(scope_key: str) -> None:
    """Remove every stored table + manifest under a scope. Called when the
    scope itself is wiped (scope deletion or wipe-and-reindex-all)."""
    root = tables_root_for(scope_key)
    if not root.exists():
        return
    import shutil
    try:
        shutil.rmtree(root)
    except OSError as e:
        logger.warning(f"delete_scope_tables({scope_key}) failed: {e}")


def delete_doc_tables(scope_key: str, doc_name: str) -> None:
    """Remove one doc's table dir + manifest. Called by the rag_watcher when
    a file is deleted / moved."""
    d = tables_dir_for(scope_key, doc_name)
    if not d.exists():
        return
    import shutil
    try:
        shutil.rmtree(d)
    except OSError as e:
        logger.warning(f"delete_doc_tables({scope_key}, {doc_name}) failed: {e}")
