"""Skill index injection middleware.

Ported verbatim from oracle-sqlcl-chat/app/skills.py. The middleware appends
the contents of skills/SKILLS.md to the system prompt on every model call,
and exposes a `load_skill` tool the agent can use to read a single skill
file on demand.
"""
from __future__ import annotations

from typing import Awaitable, Callable

import anyio
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.messages import SystemMessage
from langchain.tools import tool
from loguru import logger


@tool
async def load_skill(skill_path: str) -> str:
    """Load the full content of a skill file into the agent's context.

    Use when you need detailed instructions for a specific topic listed in
    the skill index (e.g. "skills/sql-dev/sql-patterns.md").

    Args:
        skill_path: Relative path to a skill markdown file under ./skills/.
    """
    file_path = anyio.Path(skill_path)
    return await file_path.read_text(encoding="utf-8")


async def load_skill_index() -> str:
    try:
        file_path = anyio.Path("./skills/SKILLS.md")
        return await file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error(f"Error loading skill index: {exc}")
        return "No skills available at the moment."


class SkillMiddleware(AgentMiddleware):
    """Inject the SKILLS.md index into the system prompt on every model call."""

    tools = [load_skill]

    def __init__(self) -> None:
        self.skills_prompt = ""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        self.skills_prompt = await load_skill_index()
        skills_addendum = (
            f"\n\n## Available Skills\n\n{self.skills_prompt}\n\n"
            "Use the load_skill tool when you need detailed information "
            "about handling a specific type of request."
        )
        new_content = list(request.system_message.content_blocks) + [
            {"type": "text", "text": skills_addendum}
        ]
        new_system_message = SystemMessage(content=new_content)
        modified_request = request.override(system_message=new_system_message)
        return await handler(modified_request)
