"""Test-suite preamble for the contextual-rag example.

Sets a dummy ``ANTHROPIC_API_KEY`` *before* the smoke test is collected
so importing ``contextual_rag.*`` — which decorates at import time and
instantiates the Anthropic provider — does not require a real key in
CI or on a developer's first ``uv run pytest`` after cloning.

No SDK monkeypatching happens here: the smoke test never calls a
provider, so the dummy key is enough to satisfy decoration-time
validation.
"""

import os

# Set before any ``contextual_rag.*`` module is imported. ``conftest.py``
# is evaluated by pytest at collection time, ahead of test modules.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-dummy")
