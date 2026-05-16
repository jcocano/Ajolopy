# AJ-75 — v0.1.1 patch release: README, classifier, model strings

> Tracked in [`board.json`](../board.json). Type=fix, priority=p1,
> milestone=v0.1.x.

## What

Patch release that corrects three drifts surfaced by an external
review of the v0.1.0 PyPI page:

1. **`Development Status :: 1 - Planning`** classifier in
   `pyproject.toml` contradicts the project tagline "for building
   AI-native applications in **production**". Bump to
   `Development Status :: 4 - Beta` — the surface is locked, the gates
   are green, the framework ships working code with full test
   coverage. Beta is honest; Planning is wrong.
2. **`claude-sonnet-4-7`** is used as the canonical demo model across
   the entire repo (355 occurrences). Anthropic's current 4.7 model is
   **Opus 4.7**, not Sonnet — Sonnet 4.7 has not shipped. The repo's
   model strings should reflect what users can actually invoke today.
   Replace `claude-sonnet-4-7` with `claude-opus-4-7` across README,
   docs, tutorial, examples, dogfood, specs, and tests.
3. **"Bedrock / Azure"** is listed as covered by the universal
   OpenAI-compatible provider in two places (README line 127,
   `specs/universal-openai-provider.md` line 28). v0.1's
   `_PREFIX_DEFAULTS` only ships `{ollama, groq, together, mistral,
   deepseek, openrouter}`. Bedrock and Azure are deferred (documented
   correctly elsewhere in the same spec). Remove the inaccurate
   mention.

## Scope

### 1. Model string rewrite

Single global replacement: `claude-sonnet-4-7` → `claude-opus-4-7`.
355 occurrences across:

- `README.md` (the killer demo).
- `docs/quickstart.md`, `docs/reference/*.md`, `docs/tutorial/*.md`.
- All six `examples/*/` agent code + READMEs + evals.
- `dogfood/docsbot/`.
- 19 `specs/*.md` files.

Surgical prose edits where the word "Sonnet" appears outside the
model string and refers specifically to the demo's primary model:

- `docs/tutorial/step-1-hello.md:143` — "if Sonnet returns" →
  "if Opus returns".
- `examples/support-agent/src/support_agent/agents/team.py:7` —
  rephrase the docstring to match the new primary model.
- `specs/pricing-catalog.md:30,202,203` — pricing examples that
  reference Sonnet 4.7 are illustrative; update to Opus 4.7 for
  internal consistency.

Generic mentions of "Sonnet" as a tier label (e.g. "you might need
Sonnet", "the next Sonnet release") stay — they're framework-style
references to the tier, not to the demo's primary model.

### 2. Classifier bump

In `pyproject.toml`:

```diff
-    "Development Status :: 1 - Planning",
+    "Development Status :: 4 - Beta",
```

### 3. Multi-provider list

`README.md:127`: remove "Bedrock / Azure" from the universal
OpenAI-compatible list. Match the same wording the polished launch
drafts use ("plus any OpenAI-compatible endpoint via `base_urls=`").

`specs/universal-openai-provider.md:28`: rewrite the overreaching
"covers Together, Groq, Mistral, DeepSeek, OpenRouter, Bedrock, and
Azure on day [one]" claim to reflect what v0.1 actually ships.

### 4. Version bump

`pyproject.toml` and `src/ajolopy/__init__.py`: `0.1.0` → `0.1.1`.

The patch is consumer-visible (README + model strings), so a patch
bump is mandatory. The release workflow (`release.yml`, AJ-56)
gates on `pyproject.toml` and `src/ajolopy/__init__.py` matching the
tag — both must move together.

## Out of scope

- Anything that adds primitives or kwargs. v0.1's locked surface
  stays.
- Bedrock / Azure as actual prefixes — those land when the framework
  ships `AsyncAzureOpenAI` plumbing and a LiteLLM-style Bedrock
  gateway. Out of scope per the existing universal-provider spec.
- README rewrites beyond the three drift fixes above. Other reviewer
  notes (Python 3.14 deployment risk, single-maintainer bus factor,
  competition density) are accurate but not bugs — facts of the
  project's current state. No edits required.

## Acceptance criteria

- [x] AJ-75 promoted to ready, claimed, branch `fix/v0-1-1-readme-classifier-models`.
- [ ] No `claude-sonnet-4-7` string remains in `README.md`, `docs/`,
      `examples/`, `dogfood/`, `specs/`, `tests/`, or `src/`.
- [ ] `pyproject.toml` classifier reads `Development Status :: 4 - Beta`.
- [ ] `pyproject.toml` version is `0.1.1`.
- [ ] `src/ajolopy/__init__.py` `__version__` is `"0.1.1"`.
- [ ] README's universal-provider list no longer mentions Bedrock or
      Azure.
- [ ] `specs/universal-openai-provider.md` overreaching claim
      rewritten.
- [ ] `uv run ruff check` clean.
- [ ] `uv run ruff format --check` clean.
- [ ] `uv run pyright` clean.
- [ ] `uv run pytest` green.
- [ ] `uv run --group docs mkdocs build --strict` green (catches
      link rot from the rewrites).
- [ ] `uv build` + `twine check dist/*` succeed locally (pre-flight
      for the release workflow).
- [ ] AJ-75 transitions to `done` as the final commit on this PR
      (current convention from AGENTS.md).
- [ ] Post-merge: tag `v0.1.1` and push — workflow ships to PyPI.
