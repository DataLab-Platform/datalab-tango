"""Dependency rules for host-independent plugin layers."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "datalab_tango"
PACKAGE_NAME = "datalab_tango"
HOST_MODULES = (
    "PyQt5",
    "PyQt6",
    "PySide6",
    "datalab",
    f"{PACKAGE_NAME}.adapters",
    f"{PACKAGE_NAME}.instrument",
    "js",
    "pyodide",
    "qtpy",
)
#: Only the device connection may import PyTango, and only when connecting
TANGO_MODULE = "core/backend.py"
#: Standalone simulated devices, which no other module may import
SIMULATION_MODULE = "simulation.py"


def _module_imports(filename: Path, top_level_only: bool = False) -> set[str]:
    """Return absolute names of the modules imported by one source file."""
    tree = ast.parse(filename.read_text(encoding="utf-8"), filename=str(filename))
    relative_parts = filename.relative_to(PACKAGE_ROOT).with_suffix("").parts
    package_parts = (PACKAGE_NAME, *relative_parts[:-1])
    nodes = tree.body if top_level_only else list(ast.walk(tree))
    imports: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                imports.add(node.module or "")
                continue
            base_parts = package_parts[: len(package_parts) - node.level + 1]
            if node.module is not None:
                imports.add(".".join((*base_parts, *node.module.split("."))))
            else:
                imports.update(
                    ".".join((*base_parts, *alias.name.split(".")))
                    for alias in node.names
                )
    return imports


def _matches(name: str, prefixes) -> bool:
    """Return True if a module name is one of the prefixes or below them."""
    return any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)


def test_package_root_does_not_import_host_adapters() -> None:
    """Importing package identity must not load a host adapter."""
    imports = _module_imports(PACKAGE_ROOT / "__init__.py")
    assert not any(name.startswith(f"{PACKAGE_NAME}.") for name in imports)


def test_core_does_not_import_hosts() -> None:
    """The core works without DataLab, Qt or the browser."""
    violations = [
        f"{filename.relative_to(PACKAGE_ROOT)} imports {name}"
        for filename in sorted((PACKAGE_ROOT / "core").rglob("*.py"))
        for name in sorted(_module_imports(filename))
        if _matches(name, HOST_MODULES)
    ]
    assert not violations, "\n".join(violations)


def test_pytango_is_imported_only_when_connecting() -> None:
    """PyTango is imported by the device connection only, inside its methods."""
    violations = []
    for filename in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = filename.relative_to(PACKAGE_ROOT).as_posix()
        if relative == SIMULATION_MODULE:
            continue
        imports = _module_imports(filename)
        top_level = _module_imports(filename, top_level_only=True)
        if relative != TANGO_MODULE and any(_matches(n, ("tango",)) for n in imports):
            violations.append(relative)
        if any(_matches(name, ("tango",)) for name in top_level):
            violations.append(f"{relative} (module level)")
        if f"{PACKAGE_NAME}.simulation" in imports:
            violations.append(f"{relative} imports the simulation")
    assert not violations, "\n".join(violations)
