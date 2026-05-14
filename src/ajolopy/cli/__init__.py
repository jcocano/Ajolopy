"""``ajolopy`` console-script entry point.

This package houses the first user-facing CLI command (``mcp-serve``,
AJ-60) and the dispatcher that the upcoming AJ-32 ff items (``new``,
``dev``, ``generate``, ``env``, ``deploy``, ``build``, ``info``,
``doctor``) will plug into. The structure is intentionally tiny so it
does not pre-judge those items' design.
"""

from .dispatcher import main

__all__ = ["main"]
