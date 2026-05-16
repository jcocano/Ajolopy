"""``ajolopy new <project-name>`` subcommand.

The handler orchestrates four discrete phases:

1. **Validate** the project name (``^[a-z][a-z0-9-]{1,40}$``) and the
   target directory (must not already exist; refuses path traversal /
   absolute paths). Validation failures exit with :data:`EXIT_USAGE`
   (the documented argparse exit code) or :data:`EXIT_FAILED` for an
   existing destination.
2. **Resolve** the four wizard answers — primary LLM provider, example
   feature, Dockerfile inclusion, eval inclusion — either via
   ``input()`` prompts (default) or from CLI flags + defaults when
   ``--yes`` is set.
3. **Render** the template tree under
   :mod:`ajolopy.cli.commands._templates.new` into the destination
   directory. ``.tmpl`` files are run through :func:`str.format` with
   the documented substitution context; everything else is copied
   verbatim. Feature-specific subtrees (``feature_agent`` /
   ``feature_workflow`` / ``feature_mcp``) are merged on top of the
   shared scaffold so only one variant ships per project.
4. **Report** the per-file ``✓`` lines and the documented
   "Next steps" block to ``stdout``.

The renderer is pure: every file IO call goes through the standard
library, and every prompt goes through :func:`builtins.input` so the
test seam can patch it cleanly with :func:`pytest.MonkeyPatch.setattr`.
"""

import argparse  # noqa: TC003 -- argparse.Namespace is used at runtime by argparse itself
import builtins
import re
import shutil
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import IO, TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable
    from importlib.resources.abc import Traversable

__all__ = [
    "EXIT_FAILED",
    "EXIT_INTERRUPTED",
    "EXIT_OK",
    "EXIT_USAGE",
    "cmd_new",
    "register",
]


# ---------------------------------------------------------------------------
# Exit-code constants — module-level so tests assert against names, not
# magic numbers. Mirrors the convention used by every other subcommand.
# ---------------------------------------------------------------------------
EXIT_OK: Final = 0
EXIT_FAILED: Final = 1
EXIT_USAGE: Final = 2
EXIT_INTERRUPTED: Final = 130  # Shell convention for SIGINT (Ctrl+C).


# ---------------------------------------------------------------------------
# Validation regex + answer vocabularies.
# ---------------------------------------------------------------------------
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
_VALID_LLM = ("anthropic", "openai", "gemini")
_VALID_FEATURE = ("agent", "workflow", "mcp")

# Maximum number of times a single interactive prompt is retried before
# the wizard gives up. The cap matches the documented UX in the spec
# (`Invalid -> re-prompt up to 3 times then exit`).
_MAX_PROMPT_RETRIES: Final = 3


# ---------------------------------------------------------------------------
# Provider -> model / env-var / extra mapping.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _ProviderDefaults:
    """Default config emitted into the generated scaffold per provider."""

    model: str
    env_var: str
    extra: str


_PROVIDER_DEFAULTS: dict[str, _ProviderDefaults] = {
    "anthropic": _ProviderDefaults(
        model="claude-opus-4-7",
        env_var="ANTHROPIC_API_KEY",
        extra="anthropic",
    ),
    "openai": _ProviderDefaults(
        model="gpt-4o",
        env_var="OPENAI_API_KEY",
        extra="openai",
    ),
    "gemini": _ProviderDefaults(
        model="gemini-2.0-flash-exp",
        env_var="GOOGLE_API_KEY",
        extra="gemini",
    ),
}


# ---------------------------------------------------------------------------
# Wizard answer container.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _WizardAnswers:
    """Resolved answers from the four wizard questions."""

    llm: str
    feature: str
    include_docker: bool
    include_eval: bool


# ---------------------------------------------------------------------------
# argparse registration
# ---------------------------------------------------------------------------
def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Attach the ``new`` subparser to the dispatcher.

    ``_SubParsersAction`` is the documented type for argparse's
    subparser registry; the pyright ignore mirrors the convention used
    by every other ``ajolopy`` subcommand.
    """
    parser = sub.add_parser(
        "new",
        help="Scaffold a new Ajolopy project under ./<project-name>/.",
        description=(
            "Generate a minimal NestJS-style Ajolopy project. Asks 4 "
            "questions (LLM, feature, Dockerfile, eval) and writes the "
            "templated tree to ./<project-name>/."
        ),
    )
    parser.add_argument(
        "project_name",
        metavar="PROJECT_NAME",
        help=(
            "Kebab-case project slug. Matches ^[a-z][a-z0-9-]{1,40}$. "
            "Used as the directory name and -- when snake-cased -- as "
            "the Python package name."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip every interactive prompt; use flag-supplied values or defaults.",
    )
    parser.add_argument(
        "--llm",
        choices=_VALID_LLM,
        default=None,
        help="Pre-answer for the primary LLM provider question.",
    )
    parser.add_argument(
        "--feature",
        choices=_VALID_FEATURE,
        default=None,
        help="Pre-answer for the example-feature question.",
    )
    parser.add_argument(
        "--no-docker",
        dest="no_docker",
        action="store_true",
        help="Skip generating the Dockerfile.",
    )
    parser.add_argument(
        "--no-eval",
        dest="no_eval",
        action="store_true",
        help="Skip generating the sample @Eval suite and dataset.",
    )
    parser.set_defaults(func=cmd_new)


# ---------------------------------------------------------------------------
# Entry point — wired into argparse via `set_defaults(func=...)`.
# ---------------------------------------------------------------------------
def cmd_new(args: argparse.Namespace) -> int:
    """Dispatcher entry — runs the command against the live streams."""
    return _command(args, stdout=sys.stdout, stderr=sys.stderr)


def _command(
    args: argparse.Namespace,
    *,
    stdout: IO[str],
    stderr: IO[str],
) -> int:
    """Orchestrate validate -> resolve answers -> render -> report."""
    project_name: str = args.project_name
    if not _is_valid_name(project_name):
        print(
            f"ajolopy new: project name {project_name!r} must be kebab-case "
            f"(regex {_NAME_RE.pattern!r}).",
            file=stderr,
        )
        return EXIT_USAGE

    if _looks_like_path(project_name):
        print(
            f"ajolopy new: project name {project_name!r} must not contain "
            f"path separators or traversal segments.",
            file=stderr,
        )
        return EXIT_USAGE

    destination = Path.cwd() / project_name
    if destination.exists():
        print(
            f"ajolopy new: directory already exists: {destination}",
            file=stderr,
        )
        return EXIT_FAILED

    try:
        answers = _resolve_answers(args, stderr=stderr)
    except _InvalidAnswerError as exc:
        print(f"ajolopy new: {exc}", file=stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        # The shell convention is 128 + SIGINT (=2) -> 130. Surface the
        # number rather than re-raise so the parent process sees the
        # documented exit code on every platform.
        print("", file=stderr)
        print("ajolopy new: aborted by user (Ctrl+C).", file=stderr)
        return EXIT_INTERRUPTED

    context = _build_context(project_name, answers)

    try:
        written = _render_tree(destination, answers, context)
    except OSError as exc:
        # Roll back a partial scaffold so a re-run does not collide with
        # half-written files.
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        print(f"ajolopy new: failed to write project tree: {exc}", file=stderr)
        return EXIT_FAILED

    _report_creation(
        project_name=project_name,
        written=written,
        destination=destination,
        env_var=_PROVIDER_DEFAULTS[answers.llm].env_var,
        stdout=stdout,
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _is_valid_name(name: str) -> bool:
    """Return ``True`` when ``name`` matches the documented regex."""
    return bool(_NAME_RE.fullmatch(name))


def _looks_like_path(name: str) -> bool:
    """Return ``True`` when ``name`` carries path separators or traversal.

    Defence in depth — the kebab-case regex already rejects ``/``, ``\\``
    and ``.`` characters, but a regex slip would otherwise expose a path
    traversal sink. The check stays explicit so any future regex change
    keeps the traversal guarantee.
    """
    if name in {".", ".."}:
        return True
    return any(ch in name for ch in ("/", "\\", ".", ":"))


# ---------------------------------------------------------------------------
# Wizard / answer resolution
# ---------------------------------------------------------------------------
class _InvalidAnswerError(RuntimeError):
    """Wizard could not resolve one of the four answers."""


def _resolve_answers(
    args: argparse.Namespace,
    *,
    stderr: IO[str],
) -> _WizardAnswers:
    """Return the resolved wizard answers (interactive or via flags)."""
    if args.yes:
        return _WizardAnswers(
            llm=args.llm or _VALID_LLM[0],
            feature=args.feature or _VALID_FEATURE[0],
            include_docker=not bool(args.no_docker),
            include_eval=not bool(args.no_eval),
        )

    llm = _prompt_choice(
        question="Primary LLM provider?",
        choices=_VALID_LLM,
        preset=args.llm,
        stderr=stderr,
    )
    feature = _prompt_choice(
        question="Example feature?",
        choices=_VALID_FEATURE,
        preset=args.feature,
        stderr=stderr,
    )
    if args.no_docker:
        include_docker = False
    else:
        include_docker = _prompt_yes_no(
            question="Include Dockerfile?",
            default_yes=True,
            stderr=stderr,
        )
    if args.no_eval:
        include_eval = False
    else:
        include_eval = _prompt_yes_no(
            question="Include sample eval?",
            default_yes=True,
            stderr=stderr,
        )
    return _WizardAnswers(
        llm=llm,
        feature=feature,
        include_docker=include_docker,
        include_eval=include_eval,
    )


def _prompt_choice(
    *,
    question: str,
    choices: tuple[str, ...],
    preset: str | None,
    stderr: IO[str],
) -> str:
    """Return one of ``choices``; resolve via ``preset`` or interactive input."""
    if preset is not None:
        # argparse already constrained the value to ``choices`` via
        # ``choices=`` so we trust it without re-validation.
        return preset
    options = "/".join(choices)
    prompt = f"? {question} [{options}] "
    for _ in range(_MAX_PROMPT_RETRIES):
        raw = builtins.input(prompt).strip().lower()
        if not raw:
            return choices[0]
        if raw in choices:
            return raw
        print(
            f"  invalid: expected one of {options}; got {raw!r}.",
            file=stderr,
        )
    raise _InvalidAnswerError(
        f"too many invalid answers for {question!r}; expected one of {options}."
    )


def _prompt_yes_no(
    *,
    question: str,
    default_yes: bool,
    stderr: IO[str],
) -> bool:
    """Return a boolean; ``default_yes`` controls the default on empty input."""
    options = "Y/n" if default_yes else "y/N"
    prompt = f"? {question} [{options}] "
    for _ in range(_MAX_PROMPT_RETRIES):
        raw = builtins.input(prompt).strip().lower()
        if not raw:
            return default_yes
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print(
            f"  invalid: expected y/n; got {raw!r}.",
            file=stderr,
        )
    raise _InvalidAnswerError(f"too many invalid answers for {question!r}; expected y/n.")


# ---------------------------------------------------------------------------
# Substitution context
# ---------------------------------------------------------------------------
def _build_context(project_name: str, answers: _WizardAnswers) -> dict[str, str]:
    """Return the ``str.format`` substitution map for the template tree."""
    provider = _PROVIDER_DEFAULTS[answers.llm]
    package_name = project_name.replace("-", "_")
    class_prefix = "".join(part.capitalize() for part in project_name.split("-"))
    return {
        "project_name": project_name,
        "package_name": package_name,
        "class_prefix": class_prefix,
        "llm_provider": answers.llm,
        "llm_model": provider.model,
        "llm_env_var": provider.env_var,
        "llm_extra": provider.extra,
        "feature": answers.feature,
        # Extra lines appended at the bottom of ``.env.example``. The
        # base template injects this verbatim so feature-specific
        # secrets stay in one file without forking the template tree.
        "extra_env_lines": _extra_env_lines(answers.feature),
        # ``@Eval`` accepts ``agent=`` OR ``workflow=`` -- never both.
        # Templates render the kwarg dynamically so a workflow scaffold
        # gets ``workflow=Support`` without forking the eval tree.
        "eval_target_kwarg": "workflow" if answers.feature == "workflow" else "agent",
    }


def _extra_env_lines(feature: str) -> str:
    """Return additional ``.env.example`` lines for the chosen feature.

    ``mcp`` ships a commented-out ``GITHUB_PERSONAL_ACCESS_TOKEN`` so the
    user can plug the sample GitHub MCP server without re-reading the
    docs. Other features add nothing.
    """
    if feature == "mcp":
        return (
            "\n# Required by the example GitHub MCP integration.\n# GITHUB_PERSONAL_ACCESS_TOKEN=\n"
        )
    return ""


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------
_TEMPLATE_ROOT_PACKAGE = "ajolopy.cli.commands._templates.new"
_TEMPLATE_SUFFIX = ".tmpl"
_BASE_SUBDIR = "base"
_FEATURE_SUBDIR_PREFIX = "feature_"
_EVAL_SUBDIR = "eval"
_DOCKER_FILES: tuple[str, ...] = ("Dockerfile.tmpl",)


def _render_tree(
    destination: Path,
    answers: _WizardAnswers,
    context: dict[str, str],
) -> list[Path]:
    """Render every applicable template under ``destination``.

    Returns the list of written file paths in the order they were
    created so the CLI can echo a deterministic ``✓`` block to
    stdout.
    """
    root = resources.files(_TEMPLATE_ROOT_PACKAGE)

    destination.mkdir(parents=True)

    written: list[Path] = []
    written.extend(_render_subtree(root / _BASE_SUBDIR, destination, context))
    written.extend(
        _render_subtree(
            root / f"{_FEATURE_SUBDIR_PREFIX}{answers.feature}",
            destination,
            context,
        )
    )
    if answers.include_eval:
        written.extend(_render_subtree(root / _EVAL_SUBDIR, destination, context))
    if answers.include_docker:
        written.extend(_render_docker(root, destination, context))
    return written


def _render_subtree(
    source_root: Traversable,
    destination: Path,
    context: dict[str, str],
) -> list[Path]:
    """Walk every entry below ``source_root`` and render it under ``destination``.

    Path components are also passed through :func:`str.format`, so a
    directory named ``__package__`` becomes the chosen package name. The
    sentinel uses Python keyword markers (``__name__``) so the source
    tree is still browsable / importable in the installed package — a
    plain ``{package_name}`` segment would clash with the substitution
    pass that runs on file contents.
    """
    written: list[Path] = []
    for entry, relative in _walk(source_root):
        rendered_relative = _render_path(relative, context)
        target = destination / _strip_template_suffix(rendered_relative)
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = entry.read_text(encoding="utf-8")
        if relative.endswith(_TEMPLATE_SUFFIX):
            content = content.format(**context)
        target.write_text(content, encoding="utf-8")
        written.append(target)
    return written


_PATH_TOKEN_TO_CONTEXT_KEY: dict[str, str] = {
    "__package__": "package_name",
}


def _render_path(relative: str, context: dict[str, str]) -> str:
    """Translate sentinel path segments into their context values."""
    parts: list[str] = []
    for segment in relative.split("/"):
        key = _PATH_TOKEN_TO_CONTEXT_KEY.get(segment)
        parts.append(context[key] if key is not None else segment)
    return "/".join(parts)


def _walk(root: Traversable) -> Iterable[tuple[Traversable, str]]:
    """Yield ``(entry, relative_posix_path)`` for every entry under ``root``.

    Returned entries are ordered by ``str(entry)`` so the generation log
    is deterministic across platforms and Python versions.
    """
    if not root.is_dir():
        return
    stack: list[tuple[Traversable, str]] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        stack.append((child, child.name))
    while stack:
        entry, relative = stack.pop(0)
        yield entry, relative
        if entry.is_dir():
            for nested in sorted(entry.iterdir(), key=lambda item: item.name):
                stack.append((nested, f"{relative}/{nested.name}"))


def _strip_template_suffix(relative: str) -> str:
    """Return ``relative`` with the ``.tmpl`` suffix removed (if present)."""
    if relative.endswith(_TEMPLATE_SUFFIX):
        return relative[: -len(_TEMPLATE_SUFFIX)]
    return relative


def _render_docker(
    template_root: Traversable,
    destination: Path,
    context: dict[str, str],
) -> list[Path]:
    """Render the Dockerfile.

    Prefers the shared :mod:`ajolopy.templates.docker.dockerfile`
    generator (AJ-41) when importable; falls back to the static
    ``Dockerfile.tmpl`` shipped alongside the new-command templates.
    """
    docker_target = destination / "Dockerfile"
    try:
        from ajolopy.templates.docker.dockerfile import render_dockerfile
    except ImportError:
        rendered = _render_static_dockerfile(template_root, context)
    else:
        rendered = render_dockerfile(app_module=f"{context['package_name']}.main:app")
    docker_target.write_text(rendered, encoding="utf-8")
    return [docker_target]


def _render_static_dockerfile(
    template_root: Traversable,
    context: dict[str, str],
) -> str:
    """Read and substitute the static ``Dockerfile.tmpl`` fallback."""
    for candidate in _DOCKER_FILES:
        entry = template_root / candidate
        if entry.is_file():
            return entry.read_text(encoding="utf-8").format(**context)
    raise FileNotFoundError(
        "neither ajolopy.templates.docker.dockerfile nor the static "
        "Dockerfile.tmpl fallback is available."
    )


# ---------------------------------------------------------------------------
# Output reporting
# ---------------------------------------------------------------------------
def _report_creation(
    *,
    project_name: str,
    written: list[Path],
    destination: Path,
    env_var: str,
    stdout: IO[str],
) -> None:
    """Print the per-file ``✓`` lines + the documented next-steps block."""
    print(f"Creating {project_name}/...", file=stdout)
    for path in written:
        try:
            relative = path.relative_to(destination)
        except ValueError:
            relative = path
        print(f"  ✓ {relative}", file=stdout)
    print("", file=stdout)
    print("Next steps:", file=stdout)
    print(f"  cd {project_name}", file=stdout)
    print("  uv sync", file=stdout)
    print(f"  cp .env.example .env  # then fill in {env_var}", file=stdout)
    print("  ajolopy dev", file=stdout)
