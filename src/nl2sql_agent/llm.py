from openai import OpenAI

from nl2sql_agent.schema_loader import SchemaContext
from nl2sql_agent.schema_retrieval import build_llm_schema_prompt
from nl2sql_agent.settings import Settings


SYSTEM_TEMPLATE = (
    "You are an Oracle SQL generator. "
    "Output one read-only SQL statement and nothing else. "
    "No markdown. No commentary. "
    "Use only tables and columns from the provided schema context. "
    "If the user does not specify a limit, append "
    "'FETCH FIRST {max_rows} ROWS ONLY'."
)

REPAIR_SYSTEM_TEMPLATE = (
    "You repair Oracle SQL for a read-only execution path. "
    "Output one read-only SQL statement and nothing else. "
    "No markdown. No commentary. "
    "Keep semantics of the question. "
    "Use only tables and columns from provided schema context. "
    "If the question does not specify a limit, append "
    "'FETCH FIRST {max_rows} ROWS ONLY'."
)


class SqlGenerator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = OpenAI(api_key=settings.openai_api_key)

    def generate_sql(
        self, question: str, ctx: SchemaContext
    ) -> tuple[str, list[str] | None]:
        system_prompt = SYSTEM_TEMPLATE.format(max_rows=self._settings.max_rows)
        if self._settings.schema_retrieval_enabled:
            schema_text, tables_used = build_llm_schema_prompt(
                ctx,
                question,
                enabled=True,
                max_tables=self._settings.schema_retrieval_max_tables,
                fuzzy_name_cutoff=self._settings.schema_retrieval_fuzzy_cutoff,
            )
            meta: list[str] | None = tables_used
        else:
            schema_text = ctx.as_prompt()
            meta = None

        user_prompt = (
            f"Question:\n{question}\n\n"
            f"Schema:\n{schema_text}\n\n"
            "Return a single Oracle SQL statement."
        )

        response = self._client.responses.create(
            model=self._settings.openai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        sql = response.output_text.strip()
        return _strip_sql_fences(sql), meta

    def repair_sql(
        self,
        question: str,
        previous_sql: str,
        issue: str,
        ctx: SchemaContext,
    ) -> str:
        system_prompt = REPAIR_SYSTEM_TEMPLATE.format(max_rows=self._settings.max_rows)
        if self._settings.schema_retrieval_enabled:
            schema_text, _ = build_llm_schema_prompt(
                ctx,
                question,
                enabled=True,
                max_tables=self._settings.schema_retrieval_max_tables,
                fuzzy_name_cutoff=self._settings.schema_retrieval_fuzzy_cutoff,
            )
        else:
            schema_text = ctx.as_prompt()

        user_prompt = (
            f"Question:\n{question}\n\n"
            f"Previous SQL:\n{previous_sql}\n\n"
            f"Issue to fix:\n{issue}\n\n"
            f"Schema:\n{schema_text}\n\n"
            "Return a single repaired Oracle SQL statement."
        )

        response = self._client.responses.create(
            model=self._settings.openai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return _strip_sql_fences(response.output_text.strip())


def _strip_sql_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            inner = "\n".join(lines[1:-1]).strip()
            if inner.lower().startswith("sql"):
                inner = inner[3:].lstrip()
            return inner
    return stripped
