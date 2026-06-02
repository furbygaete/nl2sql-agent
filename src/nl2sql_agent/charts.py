"""Deterministic chart rendering helpers for tabular tool results."""
from __future__ import annotations

import ast
import base64
import datetime as dt
import io
import json
from typing import Any

from loguru import logger


def parse_tabular_tool_result(raw_content: str) -> tuple[list[str], list[list[Any]]] | None:
    """Parse `run_select_sql` output text into (columns, rows)."""
    text = (raw_content or "").strip()
    if not text:
        return None

    payload: dict[str, Any] | None = None
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            payload = loaded
    except json.JSONDecodeError:
        try:
            loaded = ast.literal_eval(text)
            if isinstance(loaded, dict):
                payload = loaded
        except (ValueError, SyntaxError):
            payload = None

    if not payload:
        return None

    raw_columns = payload.get("columns")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        return None

    columns: list[str] = []
    if isinstance(raw_columns, list):
        columns = [str(col) for col in raw_columns]

    if not columns and raw_rows and isinstance(raw_rows[0], dict):
        columns = [str(col) for col in raw_rows[0].keys()]
    if not columns:
        return None

    normalized_rows: list[list[Any]] = []
    for row in raw_rows:
        if isinstance(row, dict):
            normalized_rows.append([row.get(col) for col in columns])
        elif isinstance(row, list):
            normalized_rows.append(row)
        else:
            normalized_rows.append([row])
    return columns, normalized_rows


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _to_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time())
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            # Handles common ISO strings emitted by the SQL tool.
            return dt.datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _column_values(rows: list[list[Any]], idx: int) -> list[Any]:
    values: list[Any] = []
    for row in rows:
        if idx < len(row):
            values.append(row[idx])
    return values


def _best_numeric_column(rows: list[list[Any]], columns: list[str]) -> int | None:
    best_idx: int | None = None
    best_score = 0.0
    for idx, _ in enumerate(columns):
        vals = _column_values(rows, idx)
        if not vals:
            continue
        numeric_count = sum(1 for val in vals if _to_float(val) is not None)
        score = numeric_count / max(len(vals), 1)
        if score > best_score and numeric_count > 0:
            best_idx = idx
            best_score = score
    return best_idx


def _is_temporal_column(rows: list[list[Any]], idx: int) -> bool:
    vals = _column_values(rows, idx)
    if not vals:
        return False
    parsed = sum(1 for val in vals if _to_datetime(val) is not None)
    return parsed >= max(2, int(len(vals) * 0.6))


def generate_chart_image_payload(
    columns: list[str],
    rows: list[list[Any]],
    *,
    max_points: int = 30,
) -> dict[str, Any] | None:
    """Render a simple line/bar chart and return SSE-friendly payload."""
    if len(columns) < 2 or len(rows) < 2:
        return None

    y_idx = _best_numeric_column(rows, columns)
    if y_idx is None:
        return None

    x_idx = 0 if y_idx != 0 else (1 if len(columns) > 1 else None)
    if x_idx is None:
        return None

    chart_type = "line" if _is_temporal_column(rows, x_idx) else "bar"
    pairs: list[tuple[Any, float]] = []
    for row in rows:
        if x_idx >= len(row) or y_idx >= len(row):
            continue
        y_val = _to_float(row[y_idx])
        if y_val is None:
            continue
        pairs.append((row[x_idx], y_val))

    if len(pairs) < 2:
        return None

    if chart_type == "bar":
        # Keep the strongest bars only so labels stay legible.
        pairs = sorted(pairs, key=lambda item: abs(item[1]), reverse=True)[:max_points]
        pairs = list(reversed(pairs))
    else:
        pairs = pairs[:max_points]

    x_values = [str(item[0]) for item in pairs]
    y_values = [item[1] for item in pairs]

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4.2))
        if chart_type == "line":
            ax.plot(x_values, y_values, marker="o", linewidth=2.2, color="#4F46E5")
        else:
            ax.bar(x_values, y_values, color="#4F46E5")
            ax.tick_params(axis="x", labelrotation=35)

        ax.set_xlabel(columns[x_idx])
        ax.set_ylabel(columns[y_idx])
        ax.set_title(f"{columns[y_idx]} by {columns[x_idx]}")
        ax.grid(axis="y", linestyle="--", alpha=0.25)
        fig.tight_layout()

        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=130, bbox_inches="tight")
        plt.close(fig)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        logger.warning(f"Chart rendering failed: {exc}")
        return None

    return {
        "mime": "image/png",
        "data": encoded,
        "spec": {
            "chart_type": chart_type,
            "x": columns[x_idx],
            "y": columns[y_idx],
            "points": len(pairs),
        },
    }
