"""Test-suite preamble for the support-agent example.

Sets a dummy ``ANTHROPIC_API_KEY`` *before* ``test_smoke.py`` is collected
so importing the example's agents — which decorate at import time and
instantiate the provider — does not require a real key in CI or on a
developer's first ``uv run pytest`` after cloning.

No SDK monkeypatching happens here: the smoke test never calls a provider,
so the dummy key is enough to satisfy decoration-time validation.
"""

import os

# Set before any ``support_agent.*`` module is imported. ``conftest.py``
# is evaluated by pytest at collection time, ahead of test modules.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-dummy")
