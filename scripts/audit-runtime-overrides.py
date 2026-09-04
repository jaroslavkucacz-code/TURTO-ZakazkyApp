#!/usr/bin/env python3
"""Static architecture audit for TURTO CRM runtime composition.

The application intentionally grew through additive version layers.  This tool
makes that composition visible: it reports every monkey-patched runtime target,
hidden apply-chain, dialog/popup class and geometry owner.  The output is stable
and suitable for CI review; it does not import the GUI.
"""
from __future__ import annotations

import ast
import collections
import json
import pathlib
import sys
from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    kind: str
    target: str
    detail: str = ""


def dotted(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return dotted(node.func)
    if isinstance(node, ast.Subscript):
        return dotted(node.value)
    return ""


def iter_targets(node: ast.AST) -> Iterable[ast.AST]:
    if isinstance(node, (ast.Tuple, ast.List)):
        for item in node.elts:
            yield from iter_targets(item)
    else:
        yield node


def source_name(path: pathlib.Path, root: pathlib.Path) -> str:
    return path.relative_to(root).as_posix()


def audit_file(path: pathlib.Path, root: pathlib.Path) -> list[Hit]:
    rel = source_name(path, root)
    try:
        text = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(text, filename=rel)
    except Exception as exc:
        return [Hit(rel, 0, "parse-error", "", str(exc))]

    hits: list[Hit] = []
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            raw_targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for raw in raw_targets:
                for target_node in iter_targets(raw):
                    target = dotted(target_node)
                    if target.startswith("M.") or target.startswith("app."):
                        hits.append(Hit(rel, node.lineno, "runtime-assignment", target))
                    elif ".App." in target or target.endswith(".__init__"):
                        hits.append(Hit(rel, node.lineno, "class-assignment", target))

        if isinstance(node, ast.Call):
            func = dotted(node.func)
            if func.endswith(".apply") and node.args:
                owner = dotted(node.func.value) if isinstance(node.func, ast.Attribute) else ""
                argument = dotted(node.args[0])
                hits.append(
                    Hit(rel, node.lineno, "apply-call", f"{owner}.apply", argument)
                )
            if func.endswith((".geometry", ".place", ".wm_geometry")):
                hits.append(Hit(rel, node.lineno, "geometry-call", func))
            if func.endswith((".transient", ".grab_set", ".grab_set_global")):
                hits.append(Hit(rel, node.lineno, "dialog-owner-call", func))
            if func in {"tk.Toplevel", "Toplevel", "M.tk.Toplevel"}:
                hits.append(Hit(rel, node.lineno, "toplevel-call", func))
            if func.endswith((".post", ".tk_popup")):
                hits.append(Hit(rel, node.lineno, "popup-post", func))

        if isinstance(node, ast.ClassDef):
            bases = [dotted(base) for base in node.bases]
            if any(base.endswith("Toplevel") for base in bases):
                method_names = {
                    child.name for child in node.body if isinstance(child, ast.FunctionDef)
                }
                hits.append(
                    Hit(
                        rel,
                        node.lineno,
                        "dialog-class",
                        node.name,
                        ",".join(sorted(method_names)),
                    )
                )

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Imports nested inside a function are hidden runtime dependencies.
            cursor = parent.get(node)
            nested = False
            while cursor is not None:
                if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested = True
                    break
                cursor = parent.get(cursor)
            if nested:
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    names = [f"{node.module or ''}.{alias.name}" for alias in node.names]
                for name in names:
                    if name.startswith("v") or name in {"crm_features", "crm_runtime"}:
                        hits.append(Hit(rel, node.lineno, "hidden-runtime-import", name))

    return hits


def main() -> None:
    repo = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    source = repo / "ZakazkyApp_base_6.1"
    paths = sorted(
        path
        for pattern in ("*.py", "*.pyw", "price_lists_domain/**/*.py", "offers_engine/**/*.py")
        for path in source.glob(pattern)
        if path.is_file()
    )
    hits = [hit for path in paths for hit in audit_file(path, repo)]

    assignments: dict[str, list[Hit]] = collections.defaultdict(list)
    for hit in hits:
        if hit.kind in {"runtime-assignment", "class-assignment"}:
            assignments[hit.target].append(hit)

    collisions = {
        target: values
        for target, values in assignments.items()
        if len({(item.file, item.line) for item in values}) > 1
    }
    hidden = [hit for hit in hits if hit.kind in {"hidden-runtime-import", "apply-call"}]
    dialogs = [hit for hit in hits if hit.kind in {"dialog-class", "toplevel-call", "geometry-call", "popup-post"}]

    print("=== TURTO CRM STATIC RUNTIME AUDIT ===")
    print(f"Python files scanned: {len(paths)}")
    print(f"Runtime/class assignments: {sum(len(v) for v in assignments.values())}")
    print(f"Targets with more than one owner: {len(collisions)}")
    for target, values in sorted(collisions.items()):
        print(f"COLLISION {target}")
        for item in values:
            print(f"  - {item.file}:{item.line}")

    print(f"Hidden imports/apply calls: {len(hidden)}")
    for item in hidden:
        print(f"HIDDEN {item.kind} {item.target} {item.detail} @ {item.file}:{item.line}")

    print(f"Dialog/popup/geometry hits: {len(dialogs)}")
    dialog_classes = [hit for hit in dialogs if hit.kind == "dialog-class"]
    print(f"Toplevel subclasses: {len(dialog_classes)}")
    for item in dialog_classes:
        print(f"DIALOG {item.target} @ {item.file}:{item.line}")

    report = {
        "files_scanned": len(paths),
        "assignment_targets": {
            key: [asdict(item) for item in value]
            for key, value in sorted(assignments.items())
        },
        "collisions": {
            key: [asdict(item) for item in value]
            for key, value in sorted(collisions.items())
        },
        "hidden_runtime_composition": [asdict(item) for item in hidden],
        "dialog_and_popup_hits": [asdict(item) for item in dialogs],
        "parse_errors": [asdict(item) for item in hits if item.kind == "parse-error"],
    }
    output = repo / "runtime-audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON report: {output}")

    if report["parse_errors"]:
        raise SystemExit("Static audit could not parse every Python file")


if __name__ == "__main__":
    main()
