"""The pixel_aot draw checks, one module per draw family (docs/design/module-layout.md).

A module here that defines draw(directory, compiler, renderer, backend) is a draw family named after the module (a
trailing underscore, as in class_.py, is dropped). A module may also define controls(directory), checks that need no
GPU and run in the `controls` mode, and binary_fixtures(), programs the `binary` mode assembles and lowers again.
Modules are found by listing this directory: nothing else registers a family. common.py holds what several share.
"""
import importlib
from pathlib import Path
import pkgutil
import re
import sys

_TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

# The order the families ran in before they had modules, so that --list-families and an unfiltered draw run keep it.
# A new family needs no entry here: families not listed follow these, in name order.
LEGACY_ORDER = (
    "movk",
    "half",
    "narrow",
    "channel",
    "arithmetic",
    "scalar_constant",
    "curve_shaping",
    "truncate",
    "abs",
    "ceiling",
    "select",
    "signed_export",
    "class",
    "predicate",
    "sdwa_predicate",
    "literal_fma",
    "e64",
    "dual",
    "cube",
    "sdwa",
    "sdwa_arith",
    "int",
    "f16",
    "f16_cmp",
    "arith",
    "load",
    "image",
    "fract",
    "scalar64",
    "mad",
    "raw_word",
    "fma_mix",
    "cf_uniform",
    "scalar_load",
    "pkrtz",
)


def family_name(module_name):
    return module_name.removesuffix("_")


def _order(name):
    family = family_name(name)
    return (LEGACY_ORDER.index(family) if family in LEGACY_ORDER else len(LEGACY_ORDER), name)


_NAMES = sorted((info.name for info in pkgutil.iter_modules(__path__)
                 if info.name != "common" and not info.name.startswith("_")), key=_order)

# A module is a draw family if it binds `draw` at its top level. Finding that in the source keeps the family list
# (--list-families, CMake) free of importing every module, some of which compute large tables when imported.
_DRAW = re.compile(r"^(?:def draw\b|draw\s*=|from\s+\S+\s+import\s+[^#\n]*\bdraw\b)", re.MULTILINE)


def _has_draw(name):
    return bool(_DRAW.search((Path(__file__).resolve().parent / f"{name}.py").read_text(encoding="utf-8")))


FAMILY_MODULES = {family_name(name): name for name in _NAMES if _has_draw(name)}  # family name -> module name, in order


def _load(name):
    """The module called `name` (a module name, as in _NAMES), imported on first use."""
    return importlib.import_module(f"{__name__}.{name}")


def family(name):
    """The module of the draw family `name`."""
    return _load(FAMILY_MODULES[name])


def modules():
    """Every module, imported (the controls and binary modes need them all)."""
    return tuple(_load(name) for name in _NAMES)


def __getattr__(name):
    # MODULES and FAMILIES import everything, so they exist only for the code that asks for them.
    if name == "MODULES":
        return modules()
    if name == "FAMILIES":
        return {family_name(module.__name__.rsplit(".", 1)[1]): module for module in modules() if hasattr(module, "draw")}
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
