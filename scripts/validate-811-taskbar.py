#!/usr/bin/env python3
"""Exercise real Shell links, cached old icons and taskbar resource extraction."""
from pathlib import Path
import shutil
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
sys.path.insert(0, str(BASE))


def render_icon(icon, size, background=0x242424):
    import win32gui
    import win32ui
    from PIL import Image
    screen = win32gui.GetDC(0)
    source = win32ui.CreateDCFromHandle(screen)
    dc = source.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source, size, size)
    previous = dc.SelectObject(bitmap)
    try:
        dc.FillSolidRect((0, 0, size, size), background)
        win32gui.DrawIconEx(dc.GetSafeHdc(), 0, 0, icon, size, size, 0, None, 3)
        return Image.frombytes("RGB", (size, size), bitmap.GetBitmapBits(True), "raw", "BGRX")
    finally:
        dc.SelectObject(previous)
        win32gui.DeleteObject(bitmap.GetHandle())
        dc.DeleteDC()
        win32gui.ReleaseDC(0, screen)


def shell_image(path, small=True):
    from win32com.shell import shell, shellcon
    import win32gui
    import win32api
    flags = shellcon.SHGFI_ICON | (shellcon.SHGFI_SMALLICON if small else 0)
    result, info = shell.SHGetFileInfo(str(path), 0, flags)
    assert result and info[0], str(path)
    try:
        return render_icon(info[0], win32api.GetSystemMetrics(49 if small else 11))
    finally:
        win32gui.DestroyIcon(info[0])


def make_link(path, target, icon, arguments="", app_id=""):
    import pythoncom
    from win32com.shell import shell
    from win32com.propsys import propsys, pscon
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
        pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.SetPath(str(target))
    link.SetArguments(arguments)
    link.SetWorkingDirectory(str(target.parent))
    link.SetDescription("Vlastní popis uživatele")
    link.SetIconLocation(str(icon), 0)
    if app_id:
        props = link.QueryInterface(propsys.IID_IPropertyStore)
        props.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(app_id))
        props.Commit()
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path), 0)


def check_shortcut_upgrade():
    import pythoncom
    from win32com.shell import shell
    from win32com.propsys import propsys, pscon
    from PIL import Image
    from windows_branding import repair_shortcuts, APP_USER_MODEL_ID, TASKBAR_ICON_NAME
    previews = REPO / "dist/branding-preview"
    previews.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="turto-taskbar-811-") as td:
        temp = Path(td)
        root = temp / "CRM s mezerou"
        bundle = root / "_internal"
        bundle.mkdir(parents=True)
        target = root / "TURTO CRM.exe"
        # A real Windows executable is required for Shell icon lookup.
        shutil.copy2(sys.executable, target)
        icon = bundle / TASKBAR_ICON_NAME
        shutil.copy2(BASE / TASKBAR_ICON_NAME, icon)
        old_icon = bundle / "turto_logo.ico"
        with Image.open(BASE / "turto_icon.png") as source:
            white = Image.new("RGBA", source.size, "white")
            white.alpha_composite(source)
            white.save(old_icon, sizes=[(16, 16), (32, 32), (256, 256)])
        folder = temp / "TaskBar"
        folder.mkdir()
        owned = folder / "CRM připnuté.lnk"
        setup = folder / "Databáze.lnk"
        make_link(owned, target, old_icon, app_id="TURTO.CRM")
        make_link(setup, target, old_icon, "--data-setup")
        # A matching filename or product name must never authorize modification.
        foreign = folder / "TURTO CRM.lnk"
        make_link(foreign, Path(sys.executable), old_icon, '"foreign.py"')
        foreign_bytes = foreign.read_bytes()
        before = shell_image(owned)
        before.save(previews / "taskbar-shortcut-before.png")
        report = repair_shortcuts(root, icon, folders=(folder,))
        assert report["errors"] == [], report
        assert set(report["updated"]) == {str(owned), str(setup)}, report
        assert foreign.read_bytes() == foreign_bytes
        for path, arguments in ((owned, ""), (setup, "--data-setup")):
            link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
            link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(path))
            # Shell normalizes 8.3 paths (RUNNER~1) to their long form when
            # saving a link. Compare the actual target, not the spelling.
            assert Path(link.GetPath(shell.SLGP_RAWPATH)[0]).samefile(target)
            assert link.GetArguments() == arguments
            assert Path(link.GetWorkingDirectory()).samefile(root)
            assert link.GetDescription() == "Vlastní popis uživatele"
            linked_icon, icon_index = link.GetIconLocation()
            assert Path(linked_icon).samefile(icon) and icon_index == 0
            props = link.QueryInterface(propsys.IID_IPropertyStore)
            assert props.GetValue(pscon.PKEY_AppUserModel_ID).GetValue() == APP_USER_MODEL_ID
        expected = shell_image(icon)
        deadline = time.monotonic() + 5
        while True:
            after = shell_image(owned)
            if after.tobytes() == expected.tobytes() or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        after.save(previews / "taskbar-shortcut-after.png")
        assert before.tobytes() != expected.tobytes(), "Fixture did not contain the old white background"
        assert after.tobytes() == expected.tobytes(), "Shell retained the old icon after shortcut migration"
        before_bytes = {p: p.read_bytes() for p in folder.glob("*.lnk")}
        assert repair_shortcuts(root, icon, folders=(folder,)) == {"updated": [], "errors": []}
        assert all(p.read_bytes() == b for p, b in before_bytes.items())
    print("Windows taskbar shortcut migration, Shell cache and foreign-link protection: OK")


def check_installed(root):
    from windows_branding import TASKBAR_ICON_NAME
    from PIL import Image
    icon = root / "_internal" / TASKBAR_ICON_NAME
    assert icon.read_bytes() == (BASE / "turto_logo.ico").read_bytes()
    # Inspect the executable through the Shell as well as the loose ICO. This
    # catches a build whose EXE still embeds the former white-tile artwork.
    for small in (True, False):
        assert shell_image(root / "TURTO CRM.exe", small).tobytes() == shell_image(icon, small).tobytes()
    with Image.open(icon) as im:
        assert im.ico.getimage((256, 256)).getchannel("A").getextrema() == (0, 255)
    print("Installed executable and taskbar resource icons: OK")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        check_installed(Path(sys.argv[1]))
    else:
        check_shortcut_upgrade()
