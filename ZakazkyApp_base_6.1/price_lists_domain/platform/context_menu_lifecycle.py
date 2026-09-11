"""Reuse owned Tk menus without repeating commands or changing their contents.

Called directly by the existing workspace installers, not a runtime patch layer.
The saved Tcl binding is reused too: binding a new Python callback on each safety
pass would otherwise retain its Tcl command until the Treeview is destroyed.
"""
from __future__ import annotations

from typing import Any, Callable

_STATE = "_turto_context_menu_binding"
_SEQUENCE = "<Button-3>"


def reuse_context_menus(tree: Any, owner: str, menus: tuple[Any, ...]) -> bool:
    """Reuse only a live, complete menu set owned by this exact installer."""
    state = getattr(tree, _STATE, None)
    if not isinstance(state, dict) or state.get("owner") != owner:
        return False
    if not menus or tuple(state.get("menus", ())) != menus:
        return False
    try:
        if not all(menu is not None and menu.winfo_exists() for menu in menus):
            return False
        token, script = state["command"], state["script"]
        if not token or not script or not tree.tk.call("info", "commands", token):
            return False
        if str(tree.bind(_SEQUENCE) or "") != script:
            # Historical safety installers deliberately own this binding. Restore
            # the same Tcl script without registering another Python callback.
            tree.bind(_SEQUENCE, script, add=False)
        return True
    except Exception:
        return False


def replace_context_menus(
    tree: Any, owner: str, menus: tuple[Any, ...], popup: Callable[..., Any]
) -> None:
    """Install a new set, disposing only the previous set owned by this helper."""
    previous = getattr(tree, _STATE, None)
    command = tree.bind(_SEQUENCE, popup, add=False)
    script = str(tree.bind(_SEQUENCE) or "")
    setattr(tree, _STATE, {
        "owner": owner, "menus": menus, "command": command, "script": script,
    })
    if not isinstance(previous, dict):
        return
    # Do not destroy another layer's menus or callbacks. Only the exact resources
    # recorded by an earlier successful installation of this helper are ours.
    old_command = previous.get("command")
    if old_command and old_command != command:
        try:
            tree.deletecommand(old_command)
        except Exception:
            pass
    for menu in previous.get("menus", ()):
        if menu not in menus:
            try:
                menu.destroy()
            except Exception:
                pass
