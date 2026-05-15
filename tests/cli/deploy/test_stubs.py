"""Tests for the v0.1 stub deploy targets."""

from pathlib import Path

import pytest

from ajolopy.cli.deploy import DeployContext
from ajolopy.cli.deploy.stubs import (
    FlyStub,
    RailwayStub,
    RenderStub,
    VercelStub,
)

_STUBS = [
    (FlyStub, "fly", "AJ-42", "Fly.io"),
    (RailwayStub, "railway", "AJ-43", "Railway"),
    (RenderStub, "render", "AJ-44", "Render"),
    (VercelStub, "vercel", "AJ-45", "Vercel"),
]


def _ctx(project_root: Path) -> DeployContext:
    return DeployContext(
        project_root=project_root,
        app_module="main:app",
        port=3000,
        python_version="3.14",
        project_name="acme",
        is_tty=False,
        yes=False,
        dry_run=False,
        force=False,
    )


@pytest.mark.parametrize(("stub_cls", "name", "board_id", "label"), _STUBS)
def test_stub_name_matches(
    stub_cls: type,
    name: str,
    board_id: str,
    label: str,
) -> None:
    del board_id, label
    instance = stub_cls()
    assert instance.name == name


@pytest.mark.parametrize(("stub_cls", "name", "board_id", "label"), _STUBS)
def test_stub_description_mentions_board_item(
    stub_cls: type,
    name: str,
    board_id: str,
    label: str,
) -> None:
    del name, label
    instance = stub_cls()
    assert board_id in instance.description


@pytest.mark.parametrize(("stub_cls", "name", "board_id", "label"), _STUBS)
def test_stub_prepare_emits_no_files(
    stub_cls: type,
    name: str,
    board_id: str,
    label: str,
    tmp_path: Path,
) -> None:
    del name, board_id, label
    instance = stub_cls()
    result = instance.prepare(_ctx(tmp_path))
    assert result.files == {}


@pytest.mark.parametrize(("stub_cls", "name", "board_id", "label"), _STUBS)
def test_stub_notes_point_at_board_item(
    stub_cls: type,
    name: str,
    board_id: str,
    label: str,
    tmp_path: Path,
) -> None:
    del name
    instance = stub_cls()
    result = instance.prepare(_ctx(tmp_path))
    assert len(result.notes) == 1
    assert board_id in result.notes[0]
    assert label in result.notes[0]


@pytest.mark.parametrize(("stub_cls", "name", "board_id", "label"), _STUBS)
def test_stub_next_steps_reference_board_item(
    stub_cls: type,
    name: str,
    board_id: str,
    label: str,
    tmp_path: Path,
) -> None:
    del name
    instance = stub_cls()
    ctx = _ctx(tmp_path)
    steps = list(instance.next_steps(ctx, instance.prepare(ctx)))
    assert len(steps) == 1
    assert board_id in steps[0]
    assert label in steps[0]
