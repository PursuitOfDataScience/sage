"""Chat providers behind one interface, so the model is a runtime choice.

Two layers, and the split is the point:

* **A profile entry** says *where* — a name, a base URL, an environment variable
  holding a key, a fallback list of model ids. That is data, and it is why adding
  Together, Groq, a vLLM server or Ollama needs no code at all.
* **An adapter** says *how* — registered under a `kind`, given the entry and the key.
  Two ship: `openai` for anything speaking `/chat/completions`, and `mistral` for the
  SDK. A provider with its own protocol is a third module and one `register`.

Both normalise onto `Chunk`, so nothing downstream knows which one is in use. Model
lists are discovered from the provider at runtime rather than hardcoded, because a
free tier's lineup changes without notice; the configured list is the fallback when
discovery fails.
"""

from __future__ import annotations

import logging
import os

from ..profile import ProviderEntry
from ..profile import active as _active
from ..registry import Registry
from .base import (
    STREAM_TIMEOUT_MS,
    Chunk,
    Model,
    Provider,
    family_of,
    flatten,
    tool_fragments,
)
from .openai_compat import OpenAICompatProvider, parse_sse

logger = logging.getLogger(__name__)

__all__ = [
    "STREAM_TIMEOUT_MS",
    "Chunk",
    "Model",
    "Provider",
    "adapters",
    "api_key",
    "build",
    "entry",
    "family_of",
    "flatten",
    "key_var",
    "names",
    "parse_key",
    "parse_sse",
    "tool_fragments",
]

# kind -> (entry, api_key) -> Provider
adapters: Registry = Registry("provider kind")

adapters.register("openai", OpenAICompatProvider)


def _mistral(entry: ProviderEntry, api_key: str) -> Provider:
    # Imported on demand: the SDK is an optional dependency, and a deployment using
    # only OpenAI-compatible endpoints should not need it installed to start.
    from .mistral import MistralProvider  # noqa: PLC0415

    return MistralProvider(entry, api_key)


adapters.register("mistral", _mistral)


def _vertex(entry: ProviderEntry, api_key: str) -> Provider:
    # On demand for symmetry with mistral, though this one has no extra dependency:
    # it is a subclass of the OpenAI adapter that swaps a static key for a token the
    # instance mints for itself. See sage/providers/vertex.py for why that is worth
    # a module.
    from .vertex import VertexProvider  # noqa: PLC0415

    return VertexProvider(entry, api_key)


adapters.register("vertex", _vertex)


def names() -> tuple[str, ...]:
    """Every provider the profile declares, in preference order."""
    return tuple(item.name for item in _active().providers)


def entry(name: str) -> ProviderEntry | None:
    return _active().provider(name)


def key_var(name: str) -> str:
    """The environment variable holding this provider's key, or ''."""
    found = entry(name)
    return found.key_env if found else ""


def api_key(name: str) -> str:
    """Provider key from the environment. The UI adds an `st.secrets` fallback."""
    variable = key_var(name)
    return os.getenv(variable, "") if variable else ""


def build(name: str, api_key: str) -> Provider:
    found = entry(name)
    if found is None:
        raise ValueError(f"Unknown provider: {name}")
    return adapters.get(found.kind)(found, api_key)


def parse_key(value: str) -> Model | None:
    """`'opencode:deepseek-v4-flash'` -> Model, or None if malformed.

    The provider half is checked against the profile rather than a pair of constants,
    which is what stops `SAGE_DEFAULT_MODEL` naming a provider this deployment does
    not have from selecting a model nothing can serve.
    """
    if not value or ":" not in value:
        return None
    provider, model_id = value.split(":", 1)
    if not model_id or provider not in names():
        return None
    return Model(provider, model_id)
