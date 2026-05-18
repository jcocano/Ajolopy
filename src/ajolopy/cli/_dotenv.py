"""Shared ``.env`` autoloader for the ``ajolopy`` CLI.

Called from the dispatcher before any subcommand runs (AJ-93), so every
CLI invocation that imports user code (``dev``, ``eval``, ``doctor``,
``env:show / validate / diff``, ``generate``) sees the same env vars a
production server would. Originally lived inside ``cli/commands/dev.py``
(AJ-88); extracted here so every subcommand inherits the behaviour
without each having to call it manually.

The contract — identical to what ``ajolopy dev`` used to provide:

- Only ``cwd/.env`` is read (no parent-directory walk). Matches what
  ``ajolopy new`` documents in its "Next steps" block and what
  :class:`ajolopy.config.BaseConfig` loads internally via
  ``pydantic-settings``.
- Shell-exported variables ALWAYS win. If ``KEY`` is already in
  ``environ``, the ``.env`` value is ignored. Standard precedence —
  same as ``pydantic-settings`` and ``docker compose``.
- Bare ``KEY=`` (no value) is skipped so we never clobber a shell-set
  value with an empty string by accident.
- Parsing delegates to :func:`dotenv.dotenv_values`. ``python-dotenv``
  is a hard transitive dep of ``pydantic-settings`` (a direct framework
  dep), so importing it costs nothing extra and the parse semantics
  match what the framework's own ``ConfigService`` uses at bootstrap.

Idempotent: calling it twice from the same process is safe (second
call no-ops keys that were already loaded by the first).
"""

import logging

# NOTE: ``Path`` MUST be imported at runtime (not under ``if TYPE_CHECKING:``).
# Python 3.14 + PEP 649 defers annotation evaluation, but the framework's
# repo-wide rule forbids ``from __future__ import annotations``, so any
# tooling that introspects ``load_dotenv``'s signature via
# ``inspect.signature()`` would evaluate the annotation at call time and
# crash on a missing name. Same pattern as ``AsyncGenerator`` in the
# scaffolded ``support.py``.
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import MutableMapping

__all__ = ["load_dotenv"]


_logger = logging.getLogger(__name__)


def load_dotenv(*, cwd: Path, environ: MutableMapping[str, str]) -> bool:
    """Load ``cwd/.env`` into ``environ`` without clobbering existing keys.

    Args:
        cwd: The directory to look for ``.env`` in. The dispatcher passes
            :func:`Path.cwd`; tests pass a ``tmp_path``.
        environ: The mutable mapping to populate. Production passes
            :data:`os.environ`; tests pass a plain ``dict[str, str]`` so
            the process env stays untouched.

    Returns:
        ``True`` if ``cwd/.env`` exists, ``False`` otherwise.
    """
    env_path = cwd / ".env"
    if not env_path.is_file():
        _logger.debug("ajolopy: no .env file at %s; continuing.", env_path)
        return False

    from dotenv import dotenv_values

    loaded = dotenv_values(env_path)
    applied = 0
    for key, value in loaded.items():
        if value is None:
            continue
        if key in environ:
            continue
        environ[key] = value
        applied += 1
    _logger.debug(
        "ajolopy: loaded %d env var(s) from %s (skipped the rest as already set).",
        applied,
        env_path,
    )
    return True
