"""Regression: scaffolding templates must reference real models.

If a ``.tmpl`` under ``cli/commands/_templates/`` hard-codes a model string
that the upstream provider has not released, every ``ajolopy generate ...``
call ships code that crashes on the first invocation — the worst possible
first impression for a new user. The pricing catalog is authoritative on
what models the framework supports, so the assertion is simply: every
model string a template embeds must be a key in ``pricing.json``.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_ROOT = REPO_ROOT / "src" / "ajolopy" / "cli" / "commands" / "_templates"
PRICING_PATH = REPO_ROOT / "src" / "ajolopy" / "observability" / "pricing.json"

# Captures both ``model="..."`` (agents, single-LLM kwargs) and
# ``coordinator="..."`` (workflow router). Add new model-bearing kwargs
# here if the template surface grows.
_MODEL_KWARG_RE = re.compile(r'(?:model|coordinator)="([^"]+)"')


def _known_models() -> set[str]:
    return set(json.loads(PRICING_PATH.read_text("utf-8")).keys())


def _is_placeholder(value: str) -> bool:
    """``{llm_model}`` and friends are substituted by the wizard at render."""
    return value.startswith("{") and value.endswith("}")


@pytest.mark.parametrize(
    "template",
    sorted(TEMPLATES_ROOT.rglob("*.tmpl")),
    ids=lambda p: str(p.relative_to(TEMPLATES_ROOT)),
)
def test_template_model_strings_exist_in_pricing_catalog(template: Path) -> None:
    text = template.read_text(encoding="utf-8")
    literal = [m for m in _MODEL_KWARG_RE.findall(text) if not _is_placeholder(m)]
    if not literal:
        pytest.skip("template only references template-time placeholders")
    known = _known_models()
    unknown = sorted(set(literal) - known)
    assert not unknown, (
        f"{template.relative_to(REPO_ROOT)} references model(s) not in "
        f"the pricing catalog: {unknown}. Scaffolded user code would "
        f"crash at first invocation. Bump to a released model present "
        f"in src/ajolopy/observability/pricing.json."
    )
