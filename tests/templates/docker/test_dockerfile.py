"""Tests for ``render_dockerfile``.

Mix of semantic assertions on individual lines (FROM, EXPOSE,
HEALTHCHECK, USER, CMD) and a snapshot test against the committed
``dockerfile_default.txt`` fixture. The semantic tests are what guards
behaviour; the snapshot is the reviewability signal — if it changes,
the diff goes through PR review.
"""

import re
from pathlib import Path

import pytest

from ajolopy.templates.docker import render_dockerfile


class TestDefaultOutput:
    def test_opens_with_syntax_directive(self) -> None:
        output = render_dockerfile()
        assert output.startswith("# syntax=docker/dockerfile:1.7\n")

    def test_has_exactly_three_from_lines(self) -> None:
        output = render_dockerfile()
        from_lines = [line for line in output.splitlines() if line.startswith("FROM ")]
        assert from_lines == [
            "FROM python:3.14-slim AS deps",
            "FROM deps AS development",
            "FROM deps AS production",
        ]

    def test_default_base_image_is_python_314_slim(self) -> None:
        # The first FROM line drives every other stage (deps -> dev,
        # deps -> prod), so pinning it covers the whole image graph.
        output = render_dockerfile()
        assert "FROM python:3.14-slim AS deps" in output

    def test_production_stage_creates_non_root_user(self) -> None:
        output = render_dockerfile()
        assert "RUN useradd -m appuser && chown -R appuser /app" in output
        assert "USER appuser" in output

    def test_production_healthcheck_curls_localhost_health(self) -> None:
        output = render_dockerfile()
        assert "HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3" in output
        assert "curl -f http://localhost:3000/health || exit 1" in output

    def test_production_cmd_uses_four_workers_and_no_access_log(self) -> None:
        output = render_dockerfile()
        # The production CMD is the last CMD in the file. Pulling the
        # last match is robust against the dev CMD also appearing.
        prod_cmds = re.findall(r"^CMD \[.*\]$", output, flags=re.MULTILINE)
        assert prod_cmds, "no CMD line found"
        prod_cmd = prod_cmds[-1]
        assert '"--workers", "4"' in prod_cmd
        assert '"--no-access-log"' in prod_cmd
        assert "--reload" not in prod_cmd

    def test_development_cmd_uses_reload(self) -> None:
        output = render_dockerfile()
        dev_cmds = re.findall(r"^CMD \[.*\]$", output, flags=re.MULTILINE)
        assert dev_cmds, "no CMD line found"
        dev_cmd = dev_cmds[0]
        assert "--reload" in dev_cmd
        assert "--workers" not in dev_cmd

    def test_default_is_deterministic(self) -> None:
        assert render_dockerfile() == render_dockerfile()


class TestPythonVersion:
    def test_alternate_version_swaps_base_image(self) -> None:
        output = render_dockerfile(python_version="3.13")
        assert "FROM python:3.13-slim AS deps" in output
        assert "FROM python:3.14-slim" not in output

    def test_slim_suffix_is_normalised(self) -> None:
        output = render_dockerfile(python_version="3.14-slim")
        assert "FROM python:3.14-slim AS deps" in output
        # The -slim suffix should NOT be duplicated.
        assert "python:3.14-slim-slim" not in output

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match=r"X\.Y"):
            render_dockerfile(python_version="")

    def test_major_only_raises(self) -> None:
        with pytest.raises(ValueError, match=r"X\.Y"):
            render_dockerfile(python_version="3")

    def test_garbage_string_raises(self) -> None:
        with pytest.raises(ValueError, match=r"X\.Y"):
            render_dockerfile(python_version="abc")


class TestPort:
    def test_port_updates_expose_and_healthcheck(self) -> None:
        output = render_dockerfile(port=8080)
        # Both EXPOSE lines (development + production) should follow.
        expose_lines = [line for line in output.splitlines() if line.startswith("EXPOSE ")]
        assert expose_lines == ["EXPOSE 8080", "EXPOSE 8080"]
        assert "http://localhost:8080/health" in output
        # And the default 3000 should not leak through anywhere.
        assert "3000" not in output

    @pytest.mark.parametrize("bad_port", [0, -1, 65536, 70_000])
    def test_out_of_range_port_raises(self, bad_port: int) -> None:
        with pytest.raises(ValueError, match="port="):
            render_dockerfile(port=bad_port)


class TestAppModule:
    def test_app_module_forwarded_to_both_uvicorn_cmds(self) -> None:
        output = render_dockerfile(app_module="api:app")
        cmds = re.findall(r"^CMD \[.*\]$", output, flags=re.MULTILINE)
        assert len(cmds) == 2
        for cmd in cmds:
            assert '"api:app"' in cmd
        # The default ``main:app`` should not leak.
        assert "main:app" not in output


class TestWorkers:
    def test_workers_updates_only_production_cmd(self) -> None:
        output = render_dockerfile(workers=2)
        cmds = re.findall(r"^CMD \[.*\]$", output, flags=re.MULTILINE)
        dev_cmd, prod_cmd = cmds
        # Development stays on --reload, no --workers.
        assert "--reload" in dev_cmd
        assert "--workers" not in dev_cmd
        # Production reflects the override.
        assert '"--workers", "2"' in prod_cmd

    def test_zero_or_negative_workers_raise(self) -> None:
        with pytest.raises(ValueError, match="workers="):
            render_dockerfile(workers=0)
        with pytest.raises(ValueError, match="workers="):
            render_dockerfile(workers=-1)


class TestSnapshot:
    def test_default_matches_committed_snapshot(self) -> None:
        snapshot = Path(__file__).parent / "__snapshots__" / "dockerfile_default.txt"
        assert render_dockerfile() == snapshot.read_text()
