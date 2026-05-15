# AJ-45 — Vercel deploy target (`vercel.json` + warning gate)

> Tracked in [`board.json`](../board.json) as `AJ-45`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source-of-truth for the design: Brief v4.0 §10 + vault doc
> `07 - Deploy y Docker.md`, section `## ajolopy deploy vercel`. If this file
> ever conflicts with the Brief or that doc, those documents win.

## What

Ship the `vercel` deploy target — a concrete `DeployTarget` (per AJ-37's
Protocol) that:

1. Prints an **interactive warning gate** to stdout explaining Vercel's
   limitations for Python AI apps (300s timeout, no in-proc state, cold
   starts breaking SSE).
2. Asks the user to confirm with `y` / `Y` / `yes`. Anything else (empty
   input, `n`, `N`, garbage) aborts with `DeployUserAbortError`. `ctx.yes`
   short-circuits the prompt for scripted runs.
3. On confirmation, emits a single file — `vercel.json` — matching the
   Brief verbatim:

   ```json
   {
     "version": 2,
     "builds": [{"src": "main.py", "use": "@vercel/python"}],
     "routes": [{"src": "/(.*)", "dest": "main.py"}]
   }
   ```

4. Prints three `next_steps`: `vercel login`, `vercel link`,
   `vercel deploy --prod`.

The new target replaces the in-tree `VercelStub` at registration time.
`__init__.py` swaps the import + the `register_target(...)` call; `stubs.py`
drops the `VercelStub` class.

## Why

Brief v4.0 calls multi-deploy a v0.1 non-negotiable. AJ-37 shipped the
command + Protocol + reference Docker target. AJ-45 closes the Vercel slot.

The warning gate is the only target in v0.1 that prompts the user inside
`prepare()`. Brief 07's `ajolopy deploy vercel` section is explicit about
why: Vercel is the platform most likely to look attractive ("zero ops,
free tier") and the most likely to **fail catastrophically in production**
for an AI workload that has any of the listed traits. Surfacing the
limitations *before* writing `vercel.json` is the framework's job; doing
it as text in the docs is not enough — most users will paste
`ajolopy deploy vercel` first and read second.

## Public surface

```python
from ajolopy.cli.deploy.vercel import VercelTarget

target = VercelTarget()              # production: defaults to sys.stdin / sys.stdout
target = VercelTarget(stdin=..., stdout=...)  # tests inject io.StringIO
```

`VercelTarget` is the production target registered by
`src/ajolopy/cli/deploy/__init__.py`. Constructor parameters:

| Parameter | Type            | Default      | Description |
| --------- | --------------- | ------------ | ----------- |
| `stdin`   | `IO[str] \| None` | `sys.stdin`  | Where the warning prompt reads the answer from. |
| `stdout`  | `IO[str] \| None` | `sys.stdout` | Where the warning text is printed. |

Both knobs exist purely so tests can drive the gate without touching
process-wide streams. Production builds the target via the registry with
no arguments — the defaults must work.

`name` / `description` are `ClassVar[str]`, mirroring `DockerTarget`:
`name = "vercel"`, description mentions Vercel and the warning gate.

## Deliberate departure from "targets are pure"

AJ-37's `base.py` documents the invariant: targets are pure;
`prepare()` returns bytes, the command driver writes them. AJ-45's
warning gate violates that on purpose — `prepare()` writes to `stdout`
and reads from `stdin` before returning anything. The Brief defines
this as the documented escape hatch (warning gate is part of the spec)
and `DeployUserAbortError` is the contract that lets the command driver
treat the prompt result the same as any other error.

Why this is OK:

- The exception type already exists in `errors.py` for exactly this
  use case.
- The command driver in `commands/deploy.py` already maps it to
  `EXIT_USER_ABORT` without a traceback.
- The two streams are injectable, so tests stay hermetic.
- No other target inherits the relaxation — it is target-local.

If a second target ever needs interaction, we promote `prompt()` into
its own method on the Protocol; today, with one example, target-local
is cheaper than a protocol change.

## `vercel.json` template

Rendered via `json.dumps(payload, indent=2)` with a trailing newline:

```json
{
  "version": 2,
  "builds": [
    {
      "src": "main.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "main.py"
    }
  ]
}
```

The Brief shows the inline form; the JSON shape is equivalent and the
two-space indent matches the AJ-41 template style.

## Warning gate text

Printed to `stdout` (the injectable stream) before the prompt:

```
Vercel for Python AI apps has serious limitations:
  - Serverless function timeout: 300s max (Pro plan)
  - No persistent in-process state (in-memory Memory backends fail)
  - Cold starts can break long SSE streams

If your app has:
  - Workflows > 5 min          -> use Fly.io or Railway
  - Persistent in-proc memory  -> use Fly.io or Railway
  - Long streaming             -> use Fly.io or Railway

Vercel works well for:
  - Single-turn short agents
  - Batch endpoints
  - Non-streaming APIs

Continue with Vercel? (y/N)
```

## Next steps

`next_steps` yields, in order:

```
vercel login
vercel link             # link to an existing project
vercel deploy --prod    # production deploy
```

## Acceptance criteria

- [ ] `VercelTarget` lives in `src/ajolopy/cli/deploy/vercel.py` and is
  registered by `src/ajolopy/cli/deploy/__init__.py` in place of
  `VercelStub`.
- [ ] `VercelStub` is removed from `stubs.py`; the other three stubs and
  the file's docstring remain intact.
- [ ] With `ctx.yes=True`, `prepare()` skips the prompt and returns one
  file: `Path("vercel.json")`. The JSON parses cleanly and matches the
  documented structure (`version=2`, single build with `@vercel/python`,
  single route `/(.*)` → `main.py`).
- [ ] With `ctx.yes=False` and `stdin=StringIO("y\n")` or
  `StringIO("yes\n")`, `prepare()` proceeds and writes the file.
- [ ] With `ctx.yes=False` and `stdin=StringIO("n\n")` or
  `StringIO("\n")` (default N), `prepare()` raises
  `DeployUserAbortError`.
- [ ] With `ctx.yes=False`, the warning text printed to the injected
  `stdout` contains the four documented sections: limitations,
  "if your app has", "Vercel works well for", and the "Continue?"
  prompt.
- [ ] `next_steps()` yields exactly three strings — `vercel login`,
  `vercel link`, `vercel deploy --prod` — in that order.
- [ ] `name == "vercel"`; `description` mentions "Vercel".
- [ ] CLI: `ajolopy deploy vercel --yes` against an empty `tmp_path`
  writes `vercel.json` and exits `EXIT_OK`. Without `--yes`, declining
  the gate exits `EXIT_USER_ABORT` (1) and writes nothing.
- [ ] `tests/cli/deploy/test_stubs.py` drops the `VercelStub` row and
  import. `tests/cli/commands/test_deploy.py` drops the `vercel` row
  from the stub parametrize and adds the gate happy/abort path.
- [ ] `docs/reference/cli-deploy.md` updates the Vercel row + adds a
  short note about the warning gate.
- [ ] Quality gates: ruff check + format clean over the touched files,
  pyright strict clean over the same, pytest green, `mkdocs build
  --strict` passes.

## Out of scope

- Invoking the `vercel` CLI from `prepare()`. v0.1 stops at writing the
  manifest; the user runs the printed `vercel login` / `vercel link` /
  `vercel deploy --prod` themselves. Same contract as `docker`.
- Per-project tuning of `vercel.json` (custom routes, env wiring,
  output directory). The template is the documented v0.1 surface; users
  hand-edit the emitted file for now. A follow-up item can add knobs if
  real users ask.
- A general "warning gate" helper on the Protocol. Target-local until a
  second target needs the pattern (see "Deliberate departure" above).

## Implementation notes

- The four cloud-target slots (AJ-42 / 43 / 44 / 45) are in-flight in
  parallel. Each lands a small module + flips one line in `__init__.py`
  and `stubs.py`. Rebase on top of whichever lands first; the registry's
  last-write-wins semantics make ordering between the four cosmetic.
- `json.dumps(..., indent=2)` is the only renderer needed. No new
  dependency.
