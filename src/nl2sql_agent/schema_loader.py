import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROMPT_CHAR_BUDGET = 20_000


def _foreign_key_map(foreign_keys: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for fk in foreign_keys:
        col_name = fk.get("column_name")
        ref_table = fk.get("referenced_table", "?")
        ref_column = fk.get("referenced_column", "?")
        if col_name:
            mapping[col_name] = f"{ref_table}.{ref_column}"
    return mapping


def render_table_line(table: dict[str, Any]) -> str:
    """Single-line TABLE … description for one schema table dict (matches ``as_prompt`` format)."""
    table_name = table.get("name", "<unknown_table>")
    columns = table.get("columns", [])
    fk_map = _foreign_key_map(table.get("foreign_keys", []))

    rendered_columns: list[str] = []
    for column in columns:
        col_name = column.get("name", "<unknown_column>")
        data_type = column.get("data_type", "UNKNOWN")
        fk_ref = fk_map.get(col_name)
        if fk_ref:
            rendered_columns.append(f"{col_name} {data_type} FK->{fk_ref}")
        else:
            rendered_columns.append(f"{col_name} {data_type}")

    return f"TABLE {table_name} ({', '.join(rendered_columns)})"


@dataclass(frozen=True)
class SchemaContext:
    raw_schema: dict[str, Any]
    prompt_char_budget: int = DEFAULT_PROMPT_CHAR_BUDGET

    def as_prompt(self) -> str:
        lines: list[str] = []
        tables = self.raw_schema.get("tables", [])

        for table in tables:
            lines.append(render_table_line(table))

        views = self.raw_schema.get("views", [])
        if views:
            names = ", ".join(v.get("name", "<unknown_view>") for v in views)
            lines.append(f"VIEWS {names}")

        synonyms = self.raw_schema.get("synonyms", [])
        if synonyms:
            rendered_synonyms = ", ".join(
                f"{s.get('name', '<unknown_synonym>')}->{s.get('table_owner', '?')}.{s.get('table_name', '?')}"
                for s in synonyms
            )
            lines.append(f"SYNONYMS {rendered_synonyms}")

        prompt = "\n".join(lines)
        if len(prompt) <= self.prompt_char_budget:
            return prompt

        return prompt[: self.prompt_char_budget - 3] + "..."

    def known_object_names(self) -> set[str]:
        """Uppercased table, view, and synonym names from ``schema.json`` for catalog checks."""
        names: set[str] = set()
        for table in self.raw_schema.get("tables", []):
            n = table.get("name")
            if isinstance(n, str) and n.strip():
                names.add(n.strip().upper())
        for view in self.raw_schema.get("views", []):
            n = view.get("name")
            if isinstance(n, str) and n.strip():
                names.add(n.strip().upper())
        for syn in self.raw_schema.get("synonyms", []):
            n = syn.get("name")
            if isinstance(n, str) and n.strip():
                names.add(n.strip().upper())
        return names


def load_schema(path: str | Path, *, prompt_char_budget: int | None = None) -> SchemaContext:
    schema_path = Path(path)
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_path}")

    budget = (
        prompt_char_budget
        if prompt_char_budget is not None
        else DEFAULT_PROMPT_CHAR_BUDGET
    )

    content = _read_schema_text(schema_path)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        # SQLcl can hard-wrap long JSON lines, injecting raw newlines mid-token.
        # Retrying with line breaks removed recovers otherwise valid payloads.
        compact_content = content.replace("\r", "").replace("\n", "")
        try:
            data = json.loads(compact_content)
        except json.JSONDecodeError:
            # Some environments prepend banner lines (e.g. JAVA_TOOL_OPTIONS) before JSON.
            # Recover by slicing from first opening brace to last closing brace.
            payload = _extract_json_payload(compact_content)
            if payload is not None:
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    preview = content.lstrip().replace("\n", " ")[:180]
                    raise ValueError(
                        "Schema file is not valid JSON. Re-run export_schema.sql and ensure "
                        "the output file contains only JSON content. "
                        f"Preview: {preview}"
                    ) from exc
            else:
                preview = content.lstrip().replace("\n", " ")[:180]
                raise ValueError(
                    "Schema file is not valid JSON. Re-run export_schema.sql and ensure "
                    "the output file contains only JSON content. "
                    f"Preview: {preview}"
                ) from exc
        else:
            return SchemaContext(raw_schema=data, prompt_char_budget=budget)
    return SchemaContext(raw_schema=data, prompt_char_budget=budget)


def _read_schema_text(schema_path: Path) -> str:
    try:
        raw = schema_path.read_bytes()
    except PermissionError as exc:
        raise PermissionError(
            f"Schema file '{schema_path}' is locked by another process. "
            "Close SQLcl/editor handles and retry."
        ) from exc

    # SQLcl output can be UTF-16 depending on shell redirection.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")

    # Some shells can emit UTF-16LE/BE without BOM when redirecting output.
    # Heuristic: if many NUL bytes are present, infer endianness by position.
    if b"\x00" in raw:
        even_nuls = raw[0::2].count(0)
        odd_nuls = raw[1::2].count(0)
        if odd_nuls > even_nuls:
            return raw.decode("utf-16-le")
        if even_nuls > odd_nuls:
            return raw.decode("utf-16-be")

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # Fallback for UTF-8 with BOM and unexpected shell behavior.
        return raw.decode("utf-8-sig")


def _extract_json_payload(content: str) -> str | None:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None
    return content[start : end + 1]
