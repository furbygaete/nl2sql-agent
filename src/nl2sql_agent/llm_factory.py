import os

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from loguru import logger

from .settings import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Pick a chat model from env-driven settings.

    Resolution order matches oracle-sqlcl-chat: Anthropic wins over OpenAI when
    both are set, so a developer can flip providers by setting one extra var
    without unsetting the other.

    Note: pydantic-settings reads .env into the Settings object but does NOT
    export to os.environ. Provider SDKs (openai, anthropic, langsmith) read
    keys from the process environment directly, so we both pass api_key= to
    init_chat_model AND mirror the values into os.environ so any sub-library
    that bypasses the kwarg still finds them.
    """
    if settings.anthropic_api_key:
        if not settings.anthropic_model:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is set but ANTHROPIC_MODEL is empty. "
                "Set ANTHROPIC_MODEL (e.g. 'claude-sonnet-4-6')."
            )
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
        logger.info(f"LLM provider: Anthropic ({settings.anthropic_model})")
        return init_chat_model(
            model=settings.anthropic_model,
            model_provider="anthropic",
            api_key=settings.anthropic_api_key,
        )

    if settings.openai_api_key:
        if not settings.openai_model:
            raise RuntimeError(
                "OPENAI_API_KEY is set but OPENAI_MODEL is empty."
            )
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
        logger.info(f"LLM provider: OpenAI ({settings.openai_model})")
        return init_chat_model(
            model=settings.openai_model,
            model_provider="openai",
            api_key=settings.openai_api_key,
        )

    raise RuntimeError(
        "No LLM provider configured. Set OPENAI_API_KEY+OPENAI_MODEL or "
        "ANTHROPIC_API_KEY+ANTHROPIC_MODEL."
    )
