"""Root ``@Module`` for the support-agent example.

Wires either:

- the Step 1 single ``Support`` agent (when ``SUPPORT_AGENT_MODE=single``), or
- the Step 3 ``SupportTeam`` workflow (default; the ``@Stream("/chat")`` route
  is identical so clients do not change between modes).

Both modules live side-by-side so a reader can `git diff` them to see the
delta between Step 1 and Step 3 without forking the file.
"""

import os

from ajolopy import Module
from support_agent.agents.support import Support

# Importing ``team`` also imports its module-scope ``Integrations`` class,
# whose ``@MCP`` decorator self-registers into the process-wide MCP
# registry at import time. The factory drains that registry at boot.
from support_agent.agents.team import (
    Billing,
    SupportTeam,
    Technical,
    Triage,
)


@Module(agents=[Support])
class _SingleAgentModule:
    """Step 1 wiring — one agent, one ``@Stream("/chat")`` endpoint."""


@Module(
    agents=[Triage, Billing, Technical],
    workflows=[SupportTeam],
)
class _TeamModule:
    """Step 3 wiring — three specialists behind one workflow.

    The ``Integrations`` ``@MCP`` block self-registers into the process-wide
    MCP registry at decoration time (when ``support_agent.agents.team`` is
    imported); the factory drains that registry at boot, so the team module
    does not list ``Integrations`` here. ``SupportTeam`` references it
    through the ``integrations=`` kwarg on its own decorator.
    """


# Module selection. ``ajolopy dev`` resolves ``src/support_agent/main.py:app``
# via the AJ-32 convention; the env var lets a reader flip between Step 1
# and Step 3 without touching any code.
#
# "team" is the default — and any unrecognised value also falls back to it
# so the example never silently boots an empty module.
_MODE = os.environ.get("SUPPORT_AGENT_MODE", "team").strip().lower()
AppModule: type = _SingleAgentModule if _MODE == "single" else _TeamModule

__all__ = ["AppModule"]
