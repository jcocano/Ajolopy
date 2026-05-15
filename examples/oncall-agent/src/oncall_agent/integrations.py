"""External MCP integrations consumed by the on-call agent.

The module declares a single ``@MCP`` block:

- ``GitHubMCP`` points at the canonical GitHub MCP server
  (``@modelcontextprotocol/server-github`` on npm) over the ``stdio:``
  transport. The framework spawns ``npx -y`` for it at factory boot,
  performs the MCP handshake, discovers the server's tools, and
  injects them into every ``@Agent`` / ``@Workflow`` that lists
  ``integrations=[GitHubMCP]``.

Drift note — runtime requirements:
    Connecting to the GitHub MCP server requires the optional
    ``ajolopy[mcp]`` extra and a ``GITHUB_TOKEN`` env var. Without
    those, the decorator still validates at import time and the agent
    still boots; the server simply stays unhealthy and its tools are
    not advertised. The local ``@Tool`` on ``OnCallAgent`` still
    answers in that mode.
"""

from ajolopy import MCP


@MCP(
    servers={
        # The canonical GitHub MCP server, distributed on npm. The
        # ``stdio:`` scheme tells the framework to spawn the command
        # and speak the MCP stdio transport over the child's pipes.
        "github": "stdio:npx -y @modelcontextprotocol/server-github",
    },
    auth={
        # ``${GITHUB_TOKEN}`` is resolved against ``os.environ`` at
        # factory boot. Missing → server marked unhealthy (logged at
        # WARN); the rest of the app keeps serving.
        "github": {"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}},
    },
)
class GitHubMCP:
    """The GitHub MCP server, shared across the on-call agent.

    The class body is intentionally empty — ``@MCP`` is a
    declaration, not a runtime. Tools are discovered at factory boot
    and injected wherever a class lists
    ``integrations=[GitHubMCP]``.

    Discovered tools are namespaced ``github__<tool_name>`` so they
    cannot collide with the agent's local ``@Tool`` methods (which
    keep their bare names and always win on collisions).
    """


__all__ = ["GitHubMCP"]
