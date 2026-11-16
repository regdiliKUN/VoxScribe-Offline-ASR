"""Windows desktop shortcut (.lnk) creation and verification.

Why this matters: Explorer's "Open file location" resolves the Shell Link's
``TargetPath``. As long as the link points at the real, absolute path of the
EXE (and not a launcher / wrapper), right-click -> "Open file location" opens
the folder that contains the EXE. We therefore create a genuine Shell Link via
COM, set TargetPath / WorkingDirectory / IconLocation, and read it back to
verify before reporting success.

Three independent creation strategies are available, so a missing pywin32 or
a hardened PowerShell policy cannot break first-run setup.
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path

from .errors import ShortcutError

log = logging.getLogger("voxscribe.shortcut")

SHORTCUT_NAME = "VoxScribe.lnk"
# A single description keeps the hover tooltip identical regardless of which
# of the three creation strategies succeeds (COM / PowerShell / pylnk3).
SHORTCUT_DESCRIPTION = "VoxScribe - 离线语音转文字"
DESKTOP_CSIDL = 0x0000  # CSIDL_DESKTOPDIRECTORY


@dataclass
class ShortcutResult:
    created: bool
    path: Path
    target: Path
    method: str
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.path.is_file()


def get_desktop_dir() -> Path:
    """Resolve the real desktop, including OneDrive-redirected desktops."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
        expanded = os.path.expandvars(str(value))
        p = Path(expanded)
        if p.is_dir():
            return p
    except (OSError, WindowsError):  # pragma: no cover - machine dependent
        pass

    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    for name in ("Desktop", "桌面", "OneDrive\\Desktop", "OneDrive - Personal\\Desktop"):
        p = Path(home) / name
        if p.is_dir():
            return p
    p = Path(home) / "Desktop"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _create_with_com(lnk: Path, exe: Path) -> str:
    import gc

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    shell = sc = None
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(str(lnk))
        sc.Targetpath = str(exe)
        sc.WorkingDirectory = str(exe.parent)
        sc.IconLocation = str(exe) + ",0"
        sc.Description = SHORTCUT_DESCRIPTION
        sc.Save()
        return "com"
    finally:
        # COM proxies must be released *before* CoUninitialize; otherwise
        # pywin32 emits "Win32 exception occurred releasing IUnknown" at
        # interpreter shutdown and can crash a frozen (windowless) process.
        sc = None
        shell = None
        gc.collect()
        pythoncom.CoUninitialize()


_PS_TEMPLATE = (
    "$ErrorActionPreference='Stop';"
    "$s=New-Object -ComObject WScript.Shell;"
    "$l=$s.CreateShortcut({lnk});"
    "$l.TargetPath={exe};"
    "$l.WorkingDirectory={work};"
    "$l.IconLocation={icon};"
    "$l.Description={desc};"
    "$l.Save();"
)


def _create_with_powershell(lnk: Path, exe: Path) -> str:
    def q(v: str) -> str:
        return "'" + v.replace("'", "''") + "'"

    script = _PS_TEMPLATE.format(
        lnk=q(str(lnk)), exe=q(str(exe)), work=q(str(exe.parent)),
        icon=q(str(exe) + ",0"), desc=q(SHORTCUT_DESCRIPTION),
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, timeout=30,
    )
    if proc.returncode != 0:
        raise ShortcutError("PowerShell 创建快捷方式失败",
                            detail=proc.stderr.decode("utf-8", "replace")[:500])
    return "powershell"


def _create_with_pylnk3(lnk: Path, exe: Path) -> str:
    import pylnk3
    pylnk3.for_file(
        str(exe), lnk_name=str(lnk),
        description=SHORTCUT_DESCRIPTION,
        icon_file=str(exe), work_dir=str(exe.parent),
    )
    return "pylnk3"


def read_shortcut_target(lnk: Path) -> tuple[str, str]:
    """Return (target_path, working_directory) from an existing .lnk."""
    try:
        import gc

        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        shell = sc = None
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            sc = shell.CreateShortCut(str(lnk))
            return str(sc.Targetpath), str(sc.WorkingDirectory)
        finally:
            sc = None
            shell = None
            gc.collect()
            pythoncom.CoUninitialize()
    except Exception:
        pass
    return _read_with_pylnk3(lnk)


def _read_with_pylnk3(lnk: Path) -> tuple[str, str]:
    """Fallback reader for environments without pywin32/COM."""
    import pylnk3
    obj = pylnk3.parse(str(lnk))
    # pylnk3 releases expose the working directory under different attribute
    # names; getattr keeps a missing attribute from aborting verification.
    work = getattr(obj, "work_dir", None) or getattr(obj, "working_dir", None) or ""
    return str(getattr(obj, "path", None) or ""), str(work)


def verify_shortcut(lnk: Path, expected_exe: Path) -> tuple[bool, str]:
    """Validate the link resolves to the real EXE and its parent folder exists."""
    if not lnk.is_file():
        return False, "快捷方式文件不存在"
    try:
        target, work = read_shortcut_target(lnk)
    except Exception as exc:
        return False, f"无法解析快捷方式: {exc}"
    try:
        same = Path(target).resolve() == Path(expected_exe).resolve()
    except OSError:
        same = False
    if not same:
        return False, f"目标不匹配: {target!r} != {str(expected_exe)!r}"
    if not Path(expected_exe).parent.is_dir():
        return False, "EXE 所在目录不存在"
    if work and Path(work).resolve() != Path(expected_exe).parent.resolve():
        return False, f"工作目录不正确: {work!r}"
    return True, "OK"


def create_shortcut(exe: Path | str | None = None, *, desktop: Path | str | None = None,
                    force: bool = False, name: str = SHORTCUT_NAME) -> ShortcutResult:
    """Create / repair the desktop shortcut. Idempotent by default."""
    from .paths import exe_path

    exe = Path(exe).resolve() if exe else exe_path()
    if not exe.is_file():
        raise ShortcutError("找不到 EXE 文件", detail=str(exe))
    desk = Path(desktop) if desktop else get_desktop_dir()
    desk.mkdir(parents=True, exist_ok=True)
    lnk = desk / name

    if lnk.is_file() and not force:
        ok, why = verify_shortcut(lnk, exe)
        if ok:
            return ShortcutResult(False, lnk, exe, "existing", "快捷方式已存在且有效")
        log.warning("Existing shortcut invalid (%s); recreating", why)

    errors: list[str] = []
    for maker in (_create_with_com, _create_with_powershell, _create_with_pylnk3):
        try:
            method = maker(lnk, exe)
            ok, why = verify_shortcut(lnk, exe)
            if ok:
                log.info("Desktop shortcut created via %s -> %s", method, lnk)
                return ShortcutResult(True, lnk, exe, method, "已创建桌面快捷方式")
            errors.append(f"{method}: verification failed ({why})")
        except Exception as exc:
            errors.append(f"{maker.__name__}: {type(exc).__name__}: {exc}")
            log.warning("Shortcut strategy %s failed: %s", maker.__name__, exc)

    raise ShortcutError("所有快捷方式创建方式均失败", detail=" | ".join(errors))
