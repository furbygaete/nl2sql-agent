"""Select a small, relevant subset of tables for the LLM prompt (no full schema.json in-context)."""

from __future__ import annotations

import difflib
import re
from typing import Any

from nl2sql_agent.schema_loader import SchemaContext, render_table_line

_QUESTION_STOP_WORDS = frozenset(
    {
        "A",
        "AN",
        "AND",
        "ARE",
        "AS",
        "DA",
        "DAS",
        "DE",
        "DO",
        "DOS",
        "FOR",
        "HOW",
        "IN",
        "IS",
        "MANY",
        "O",
        "OF",
        "ON",
        "OS",
        "POR",
        "QUAL",
        "QUAIS",
        "QUANTAS",
        "QUANTOS",
        "QUE",
        "THE",
        "THERE",
        "TO",
        "TOTAL",
    }
)


def _tables_list(raw: dict[str, Any]) -> list[dict[str, Any]]:
    tables = raw.get("tables", [])
    return [t for t in tables if isinstance(t, dict)]


def _table_name(table: dict[str, Any]) -> str:
    return str(table.get("name", "") or "").strip().upper()


def _question_tokens(question: str) -> set[str]:
    # Oracle-style identifiers and ordinary words (e.g. MG_CLIENTS, clientes)
    found = re.findall(r"\b[A-Za-z][A-Za-z0-9_]{1,}\b", question)
    out: set[str] = set()
    for tok in found:
        upper = tok.upper()
        if len(upper) < 3 or upper in _QUESTION_STOP_WORDS:
            continue
        out.add(upper)
        # Basic singularization so "clients" can match "client".
        if upper.endswith("ES") and len(upper) >= 6:
            out.add(upper[:-2])
        elif upper.endswith("S") and len(upper) >= 5:
            out.add(upper[:-1])
    return out


def _entity_hints(question: str) -> set[str]:
    """
    Capture likely business entities from counting-style questions:
    "how many clients ...", "number of invoices", "quantos pedidos ...".
    """
    hints: set[str] = set()
    patterns = [
        r"\bhow\s+many\s+([A-Za-z][A-Za-z0-9_]*)\b",
        r"\b(?:count|number|total)\s+of\s+([A-Za-z][A-Za-z0-9_]*)\b",
        r"\bquant(?:os|as)\s+([A-Za-z][A-Za-z0-9_]*)\b",
        r"\bn[úu]mero\s+de\s+([A-Za-z][A-Za-z0-9_]*)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, question, flags=re.IGNORECASE):
            token = match.group(1).upper()
            if len(token) < 3:
                continue
            hints.add(token)
            if token.endswith("ES") and len(token) >= 6:
                hints.add(token[:-2])
            elif token.endswith("S") and len(token) >= 5:
                hints.add(token[:-1])
    return hints


def _normalized_alpha(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", s, flags=re.ASCII).upper()


def _score_table(
    table: dict[str, Any],
    tokens: set[str],
    entity_hints: set[str],
    question_norm: str,
) -> float:
    name = _table_name(table)
    if not name:
        return 0.0
    score = 0.0
    name_parts = {p for p in name.split("_") if len(p) >= 3}

    for tok in tokens:
        if tok == name:
            score += 120.0
        elif tok in name or name in tok:
            score += 55.0
        else:
            r = difflib.SequenceMatcher(None, tok, name).ratio()
            if r >= 0.72:
                score += 35.0 * r
            elif r >= 0.55:
                score += 18.0 * r

        for part in name_parts:
            if len(part) >= 4 and (part in tok or tok in part):
                score += 12.0
            pr = difflib.SequenceMatcher(None, tok, part).ratio()
            if pr >= 0.8:
                score += 10.0 * pr

    for hint in entity_hints:
        if hint == name:
            score += 85.0
            continue
        if hint in name or name in hint:
            score += 45.0
            continue
        hr = difflib.SequenceMatcher(None, hint, name).ratio()
        if hr >= 0.75:
            score += 28.0 * hr

    if question_norm and len(question_norm) >= 6:
        rn = _normalized_alpha(name)
        if rn and (rn in question_norm or question_norm in rn):
            score += 25.0
        qr = difflib.SequenceMatcher(None, question_norm[: min(80, len(question_norm))], rn).ratio()
        if qr >= 0.5:
            score += 15.0 * qr

    for col in table.get("columns", []) or []:
        if not isinstance(col, dict):
            continue
        cn = str(col.get("name", "") or "").upper()
        if len(cn) < 3:
            continue
        for tok in tokens:
            if tok == cn or tok in cn or cn in tok:
                score += 6.0

    return score


def _fk_neighbor_names(table: dict[str, Any], known: set[str]) -> set[str]:
    out: set[str] = set()
    for fk in table.get("foreign_keys", []) or []:
        if not isinstance(fk, dict):
            continue
        ref = str(fk.get("referenced_table", "") or "").strip().upper()
        if ref and ref in known:
            out.add(ref)
    return out


def _by_name_map(tables: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    m: dict[str, dict[str, Any]] = {}
    for t in tables:
        n = _table_name(t)
        if n:
            m[n] = t
    return m


def build_llm_schema_prompt(
    ctx: SchemaContext,
    question: str,
    *,
    enabled: bool,
    max_tables: int,
    fuzzy_name_cutoff: float = 0.42,
) -> tuple[str, list[str]]:
    """
    Build schema text for the LLM. When ``enabled``, only scored + FK-neighbor
    tables are included (within ``ctx.prompt_char_budget``). Otherwise uses
    ``ctx.as_prompt()`` (legacy truncation).

    Returns ``(prompt_text, table_names_included)``.
    """
    if not enabled:
        return ctx.as_prompt(), []

    raw = ctx.raw_schema
    tables = _tables_list(raw)
    if not tables:
        return ctx.as_prompt(), []

    name_map = _by_name_map(tables)
    known = set(name_map.keys())
    tokens = _question_tokens(question)
    hints = _entity_hints(question)
    qnorm = _normalized_alpha(question)

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for t in tables:
        n = _table_name(t)
        if not n:
            continue
        s = _score_table(t, tokens, hints, qnorm)
        scored.append((s, n, t))

    scored.sort(key=lambda x: (-x[0], x[1]))

    chosen: dict[str, dict[str, Any]] = {}
    # Primary: high-score tables first
    for s, n, t in scored:
        if s <= 0:
            break
        if n not in chosen:
            chosen[n] = t
        if len(chosen) >= max_tables:
            break

    # Fuzzy match on full table name list if we still have few picks
    if len(chosen) < min(5, max_tables // 2):
        all_names = sorted(known)
        blob = " ".join(sorted(tokens))[:200].upper()
        if blob.strip():
            for match in difflib.get_close_matches(
                blob,
                all_names,
                n=max_tables,
                cutoff=fuzzy_name_cutoff,
            ):
                if match in name_map and match not in chosen:
                    chosen[match] = name_map[match]
                if len(chosen) >= max_tables:
                    break

    # FK expansion (does not count toward max_tables as harshly — cap total)
    expanded = dict(chosen)
    for n, t in list(chosen.items()):
        for nb in _fk_neighbor_names(t, known):
            if nb not in expanded and len(expanded) < max_tables + 8:
                expanded[nb] = name_map[nb]

    ordered_names = sorted(
        expanded.keys(),
        key=lambda x: (-_score_table(expanded[x], tokens, hints, qnorm), x),
    )
    ordered_tables = [expanded[n] for n in ordered_names if n in expanded]

    # No lexical / fuzzy hit — still give the model a bounded slice of the catalog
    if not ordered_tables:
        ordered_tables = sorted(tables, key=_table_name)[:max_tables]

    lines: list[str] = []
    for t in ordered_tables:
        lines.append(render_table_line(t))

    views = raw.get("views", [])
    if views:
        names = ", ".join(str(v.get("name", "")) for v in views if isinstance(v, dict))
        if names:
            lines.append(f"VIEWS {names}")

    synonyms = raw.get("synonyms", [])
    if synonyms:
        rendered_synonyms = ", ".join(
            f"{s.get('name', '')}->{s.get('table_owner', '?')}.{s.get('table_name', '?')}"
            for s in synonyms
            if isinstance(s, dict)
        )
        if rendered_synonyms:
            lines.append(f"SYNONYMS {rendered_synonyms}")

    prompt = "\n".join(lines)
    if len(prompt) <= ctx.prompt_char_budget:
        used = [_table_name(t) for t in ordered_tables]
        return prompt, used

    # Trim by dropping lowest-scored tables until within budget
    trimmed = list(ordered_tables)
    prompt_out = prompt
    while len(trimmed) > 1:
        scores = [
            (_score_table(t, tokens, hints, qnorm), _table_name(t), t)
            for t in trimmed
        ]
        scores.sort(key=lambda x: (x[0], x[1]))
        trimmed.remove(scores[0][2])
        prompt_try = "\n".join(render_table_line(t) for t in trimmed)
        prompt_out = prompt_try
        if len(prompt_try) <= ctx.prompt_char_budget:
            break

    if len(prompt_out) > ctx.prompt_char_budget:
        prompt_out = prompt_out[: ctx.prompt_char_budget - 3] + "..."

    used = [_table_name(t) for t in trimmed]
    return prompt_out, used
