"""Feature variants: agent / workflow / mcp generate distinct ``support.py``."""

from pathlib import Path

from ajolopy.cli.commands import new as new_cmd
from tests.cli.new.conftest import invoke_new


def _generate(tmp_cwd: Path, feature: str) -> Path:
    """Generate a project with the requested feature and return its root."""
    result = invoke_new(
        [
            "my-agent",
            "--yes",
            "--feature",
            feature,
            "--no-docker",
            "--no-eval",
        ]
    )
    assert result.exit_code == new_cmd.EXIT_OK, result.stderr
    return tmp_cwd / "my-agent"


class TestFeatureAgent:
    """``--feature agent`` (the default) emits a single ``@Agent`` + ``@Tool``."""

    def test_agent_variant_shape(self, tmp_cwd: Path) -> None:
        project = _generate(tmp_cwd, "agent")
        text = (project / "src" / "my_agent" / "agents" / "support.py").read_text(encoding="utf-8")
        assert "@Agent" in text
        assert "@Tool" in text
        assert "@Workflow" not in text
        assert "@MCP" not in text
        assert "class Support" in text


class TestFeatureWorkflow:
    """``--feature workflow`` emits 2 specialists + a coordinator."""

    def test_workflow_variant_shape(self, tmp_cwd: Path) -> None:
        project = _generate(tmp_cwd, "workflow")
        text = (project / "src" / "my_agent" / "agents" / "support.py").read_text(encoding="utf-8")
        assert "@Workflow" in text
        # Two specialist agents.
        assert "class Triage" in text
        assert "class Billing" in text
        # Workflow coordinator is the Support class.
        assert "class Support" in text

    def test_workflow_variant_exposes_stream_chat(self, tmp_cwd: Path) -> None:
        """AJ-95 regression: the workflow scaffold must mount ``/chat``.

        Before AJ-95 the ``@Workflow`` orchestrator had no HTTP surface,
        so ``ajolopy dev`` started but ``curl /chat`` returned 404.
        """
        project = _generate(tmp_cwd, "workflow")
        text = (project / "src" / "my_agent" / "agents" / "support.py").read_text(encoding="utf-8")
        assert '@Stream("/chat")' in text
        assert "Annotated[ChatRequest, Body()]" in text
        assert "class ChatRequest(BaseModel)" in text


class TestFeatureMCP:
    """``--feature mcp`` emits an ``@MCP`` integrations class + agent.

    ``.env.example`` carries the documented commented-out token line.
    """

    def test_mcp_variant_shape(self, tmp_cwd: Path) -> None:
        project = _generate(tmp_cwd, "mcp")
        text = (project / "src" / "my_agent" / "agents" / "support.py").read_text(encoding="utf-8")
        assert "@MCP" in text
        assert "class Integrations" in text
        assert "integrations=[Integrations]" in text
        assert "class Support" in text

    def test_mcp_env_example_includes_github_token_comment(self, tmp_cwd: Path) -> None:
        project = _generate(tmp_cwd, "mcp")
        text = (project / ".env.example").read_text(encoding="utf-8")
        assert "# GITHUB_PERSONAL_ACCESS_TOKEN=" in text

    def test_mcp_variant_exposes_stream_chat(self, tmp_cwd: Path) -> None:
        """AJ-95 regression: the mcp scaffold must mount ``/chat``.

        Before AJ-95 the MCP-flavoured ``@Agent`` had no HTTP surface,
        so ``ajolopy dev`` started but ``curl /chat`` returned 404.
        """
        project = _generate(tmp_cwd, "mcp")
        text = (project / "src" / "my_agent" / "agents" / "support.py").read_text(encoding="utf-8")
        assert '@Stream("/chat")' in text
        assert "Annotated[ChatRequest, Body()]" in text
        assert "class ChatRequest(BaseModel)" in text


class TestEvalKwargPerFeature:
    """The eval target kwarg flips to ``workflow=`` when the feature is workflow."""

    def test_workflow_feature_uses_workflow_kwarg(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes", "--feature", "workflow"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        text = (tmp_cwd / "my-agent" / "evals" / "support_eval.py").read_text(encoding="utf-8")
        assert "@Eval(workflow=Support" in text

    def test_agent_feature_uses_agent_kwarg(self, tmp_cwd: Path) -> None:
        result = invoke_new(["my-agent", "--yes", "--feature", "agent"])
        assert result.exit_code == new_cmd.EXIT_OK, result.stderr
        text = (tmp_cwd / "my-agent" / "evals" / "support_eval.py").read_text(encoding="utf-8")
        assert "@Eval(agent=Support" in text
