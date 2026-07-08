# Importing the modules registers every provider with the base registry.
from app.llm.providers import anthropic_provider  # noqa: F401
from app.llm.providers import gemini_provider  # noqa: F401
from app.llm.providers import stubs  # noqa: F401
