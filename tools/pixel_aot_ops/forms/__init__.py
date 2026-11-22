"""Instruction families. Every module in this directory is imported here, in name order, and registers its forms
with @form (see ../dispatch.py); a new family is a new module and needs no other registration."""
import importlib
import pkgutil

FAMILIES = tuple(sorted(info.name for info in pkgutil.iter_modules(__path__) if not info.name.startswith("_")))
for _name in FAMILIES:
    importlib.import_module(f"{__name__}.{_name}")
