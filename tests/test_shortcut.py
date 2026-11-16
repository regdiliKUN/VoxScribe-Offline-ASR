"""Desktop shortcut tests (iteration round 5 and later rounds)."""
from __future__ import annotations

from pathlib import Path

import pytest

from voxscribe.core import shortcut
from voxscribe.core.errors import ShortcutError


@pytest.fixture
def fake_exe(tmp_path):
    p = tmp_path / "程序 目录" / "VoxScribe.exe"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"MZ" + b"\x00" * 512)
    return p


@pytest.fixture
def fake_desktop(tmp_path):
    p = tmp_path / "Desktop"
    p.mkdir()
    return p


def test_get_desktop_dir_is_real_directory():
    p = shortcut.get_desktop_dir()
    assert p.is_dir()


def test_create_shortcut_points_to_exe(fake_exe, fake_desktop):
    r = shortcut.create_shortcut(fake_exe, desktop=fake_desktop)
    assert r.ok and r.created
    assert r.path.is_file()
    assert r.path.suffix == ".lnk"
    ok, why = shortcut.verify_shortcut(r.path, fake_exe)
    assert ok, why


def test_target_and_workdir_are_absolute_and_correct(fake_exe, fake_desktop):
    r = shortcut.create_shortcut(fake_exe, desktop=fake_desktop)
    target, work = shortcut.read_shortcut_target(r.path)
    assert Path(target).resolve() == fake_exe.resolve()
    assert Path(work).resolve() == fake_exe.parent.resolve()
    assert Path(target).is_absolute()


def test_shortcut_is_idempotent(fake_exe, fake_desktop):
    first = shortcut.create_shortcut(fake_exe, desktop=fake_desktop)
    second = shortcut.create_shortcut(fake_exe, desktop=fake_desktop)
    assert first.created and not second.created
    assert list(fake_desktop.glob("*.lnk")) == [first.path]


def test_force_recreates(fake_exe, fake_desktop):
    shortcut.create_shortcut(fake_exe, desktop=fake_desktop)
    again = shortcut.create_shortcut(fake_exe, desktop=fake_desktop, force=True)
    assert again.created


def test_broken_shortcut_is_repaired(fake_exe, fake_desktop, tmp_path):
    other = tmp_path / "other.exe"
    other.write_bytes(b"MZ")
    r = shortcut.create_shortcut(other, desktop=fake_desktop)
    ok, _ = shortcut.verify_shortcut(r.path, fake_exe)
    assert not ok
    repaired = shortcut.create_shortcut(fake_exe, desktop=fake_desktop)
    assert repaired.created
    assert shortcut.verify_shortcut(repaired.path, fake_exe)[0]


def test_missing_exe_raises(tmp_path, fake_desktop):
    with pytest.raises(ShortcutError):
        shortcut.create_shortcut(tmp_path / "nope.exe", desktop=fake_desktop)


def test_all_creation_strategies_share_one_description():
    """COM / PowerShell / pylnk3 must produce the same hover tooltip."""
    import inspect
    src = inspect.getsource(shortcut)
    assert "VoxScribe - Offline Speech to Text" not in src
    assert src.count("SHORTCUT_DESCRIPTION") >= 4  # constant + 3 strategies


def test_read_with_pylnk3_tolerates_missing_workdir(monkeypatch, tmp_path):
    """A pylnk3 link lacking work_dir/working_dir must not crash verification."""
    import sys
    import types

    class _Obj:
        path = r"C:\Program Files\VoxScribe.exe"
        # deliberately no work_dir / working_dir attributes

    fake = types.ModuleType("pylnk3")
    fake.parse = lambda _p: _Obj()
    monkeypatch.setitem(sys.modules, "pylnk3", fake)

    target, work = shortcut._read_with_pylnk3(tmp_path / "x.lnk")
    assert target.endswith("VoxScribe.exe")
    assert work == ""


def test_verify_rejects_nonexistent_link(fake_exe, tmp_path):
    ok, why = shortcut.verify_shortcut(tmp_path / "missing.lnk", fake_exe)
    assert not ok and "不存在" in why


def test_unicode_shortcut_path(fake_exe, tmp_path):
    desk = tmp_path / "中文 桌面"
    desk.mkdir()
    r = shortcut.create_shortcut(fake_exe, desktop=desk, name="语音转文字.lnk")
    assert shortcut.verify_shortcut(r.path, fake_exe)[0]
