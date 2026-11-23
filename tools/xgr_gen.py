#!/usr/bin/env python3
"""Generate the xgameruntime.dll gateway's interface table (src/xgr/xgr_gateway.cpp).

Input: tools/xgr/interfaces.toml, the classes (CLSID), interfaces (IID) and vtable slots learned from our
own traces of Microsoft's public GDK samples (docs/design/runtime.md, section 2), and the shimgen specs
(tools/shimgen/specs/*.toml) for each flat function's signature and whether x2w_gdk.dll implements it.

Output: xgr_table.inc with, per class, one wrapper per slot that names a function

    static RET xgr_<Class>_<slot>(void* self, PARAMS) noexcept { return x2w_impl_<Function>(ARGS); }

(a vtable method is the flat function with `this` first), or a typed stub for a spec function x2w_gdk
does not implement (logs through x2w_stub_called, zeroes the spec's out-params, returns its default),
and null for a slot no spec describes (the gateway's logging thunk answers E_NOTIMPL).

    python -B tools/xgr_gen.py --out BUILD/xgr/xgr_table.inc [--table tools/xgr/interfaces.toml]
    python -B tools/xgr_gen.py --check      # validate the table only
"""
import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import shimgen  # noqa: E402

GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_SLOTS = 256  # XGR_SLOTS in src/xgr/xgr_thunks.asm
# Return types that are structs: a C++ member function returns them through a hidden pointer passed
# after `this` (rdx), so the wrapper takes that pointer explicitly and returns it.
STRUCT_RETURNS = {"XSystemAnalyticsInfo"}


class TableError(ValueError):
    pass


def guid_initializer(text):
    text = text.lower()
    if not GUID.match(text):
        raise TableError(f"{text!r} is not a GUID")
    parts = text.split("-")
    tail = parts[3] + parts[4]
    data4 = ", ".join(f"0x{tail[i:i + 2]}" for i in range(0, 16, 2))
    return f"{{0x{parts[0]}, 0x{parts[1]}, 0x{parts[2]}, {{{data4}}}}}"


def load_table(path):
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    classes = data.get("classes", [])
    seen_clsid, seen_iid, seen_name = set(), set(), set()
    for klass in classes:
        for key in ("name", "clsid", "evidence"):
            if key not in klass:
                raise TableError(f"class {klass.get('name')!r} needs {key}")
        if not IDENT.match(klass["name"]) or klass["name"] in seen_name:
            raise TableError(f"class name {klass['name']!r} is not a unique identifier")
        seen_name.add(klass["name"])
        clsid = klass["clsid"].lower()
        guid_initializer(clsid)
        if clsid in seen_clsid:
            raise TableError(f"CLSID {clsid} is listed twice")
        seen_clsid.add(clsid)
        interfaces = klass.get("interfaces", [])
        if not interfaces:
            raise TableError(f"{klass['name']}: needs at least one interface")
        for interface in interfaces:
            for key in ("name", "iid", "evidence"):
                if key not in interface:
                    raise TableError(f"{klass['name']}: interface {interface.get('name')!r} needs {key}")
            iid = interface["iid"].lower()
            guid_initializer(iid)
            if iid in seen_iid:
                raise TableError(f"IID {iid} is listed twice")
            seen_iid.add(iid)
        slots = {}
        for slot in klass.get("slots", []):
            index = slot.get("index")
            if not isinstance(index, int) or not 3 <= index < MAX_SLOTS:
                raise TableError(f"{klass['name']}: slot index {index!r} must be 3..{MAX_SLOTS - 1}")
            if index in slots:
                raise TableError(f"{klass['name']}: slot {index} is listed twice")
            if "evidence" not in slot:
                raise TableError(f"{klass['name']}: slot {index} needs evidence")
            function = slot.get("function", "")
            if function and not IDENT.match(function):
                raise TableError(f"{klass['name']}: slot {index} function {function!r}")
            slots[index] = slot
        klass["_slots"] = slots
    return classes


def wrapper(klass, index, slot, specs):
    """(C++ definition, target expression) for one slot."""
    function = slot.get("function", "")
    spec = specs.functions.get(function) if function else None
    if spec is None:
        return None, "nullptr"
    name = f"xgr_{klass['name']}_{index}"
    params = ", ".join(["void* /*self*/"] + [f"{t} {n}" for t, n in spec.params])
    args = ", ".join(n for _, n in spec.params)
    lines = [f"// slot {index}: {function} ({spec.doc_url(specs.families)})"]
    if spec.returns in STRUCT_RETURNS:
        params = ", ".join(["void* /*self*/", f"{spec.returns}* result"] + [f"{t} {n}" for t, n in spec.params])
        value = f"x2w_impl_{function}({args})" if spec.body == "impl" else "{}"
        if spec.body != "impl":
            lines.append(f"// (not implemented in x2w_gdk: returns a zeroed {spec.returns})")
        lines.append(f"static {spec.returns}* {name}({params}) noexcept {{ *result = {value}; return result; }}")
        return "\n".join(lines), f"reinterpret_cast<void*>(&{name})"
    if spec.body == "impl":
        call = f"x2w_impl_{function}({args})"
        body = f"{call};" if spec.returns == "void" else f"return {call};"
        lines.append(f"static {spec.returns} {name}({params}) noexcept {{ {body} }}")
    else:
        body = [f'    x2w_stub_called("xgameruntime.dll!{function}", "xgr gateway {klass["name"]} slot {index}", '
                f"_ReturnAddress());"]
        for out in spec.out:
            body.append(f"    if ({out}) *{out} = {{}};")
        default = spec.default_return()
        body.append("    return;" if default is None else f"    return {default};")
        unused = [n for _, n in spec.params if n not in spec.out]
        for n in unused:
            body.insert(0, f"    (void){n};")
        lines.append(f"static {spec.returns} {name}({params}) noexcept\n{{\n" + "\n".join(body) + "\n}")
    return "\n".join(lines), f"reinterpret_cast<void*>(&{name})"


def render(classes, specs, source):
    out = [
        f"// Generated by tools/xgr_gen.py from {source} and tools/shimgen/specs. Do not edit; regenerate.",
        "// Included by src/xgr/xgr_gateway.cpp after XgrClass and XgrInterface.",
        "",
    ]
    class_rows, interface_rows = [], []
    for class_index, klass in enumerate(classes):
        slots = klass["_slots"]
        count = max([3] + [i + 1 for i in slots])
        targets = ["nullptr"] * count
        for index in sorted(slots):
            definition, target = wrapper(klass, index, slots[index], specs)
            if definition:
                out.append(definition)
            targets[index] = target
        out.append(f"static void* const xgr_targets_{klass['name']}[{count}] = {{")
        out.extend(f"    {t},  // {i}" for i, t in enumerate(targets))
        out.append("};")
        out.append("")
        class_rows.append(f'    {{"{klass["name"]}", {guid_initializer(klass["clsid"])}, xgr_targets_{klass["name"]}, '
                          f"{count}u}},")
        for interface in klass["interfaces"]:
            interface_rows.append(f'    {{"{interface["name"]}", {guid_initializer(interface["iid"])}, {class_index}u, '
                                  f"{int(interface.get('slots', 0))}u}},")
    out.append(f"static const XgrClass xgr_classes[{max(1, len(class_rows))}] = {{")
    out.extend(class_rows or ['    {"(none)", {}, nullptr, 0u},'])
    out.append("};")
    out.append(f"static const unsigned xgr_class_count = {len(class_rows)}u;")
    out.append(f"static const XgrInterface xgr_interfaces[{max(1, len(interface_rows))}] = {{")
    out.extend(interface_rows or ['    {"(none)", {}, 0u, 0u},'])
    out.append("};")
    out.append(f"static const unsigned xgr_interface_count = {len(interface_rows)}u;")
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default=str(ROOT / "tools" / "xgr" / "interfaces.toml"))
    parser.add_argument("--specs", default=str(ROOT / "tools" / "shimgen" / "specs"))
    parser.add_argument("--out")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        classes = load_table(args.table)
        specs = shimgen.Specs([args.specs])
    except (TableError, shimgen.SpecError, tomllib.TOMLDecodeError) as error:
        print(f"xgr_gen: {error}", file=sys.stderr)
        return 1
    named = sum(1 for k in classes for s in k["_slots"].values() if s.get("function"))
    implemented = sum(1 for k in classes for s in k["_slots"].values()
                      if s.get("function") in specs.functions and specs.functions[s["function"]].body == "impl")
    print(f"xgr_gen: {len(classes)} classes, {sum(len(k['interfaces']) for k in classes)} interfaces, "
          f"{sum(len(k['_slots']) for k in classes)} slots ({named} named, {implemented} implemented)")
    if args.check:
        return 0
    if not args.out:
        parser.error("--out is required without --check")
    text = render(classes, specs, Path(args.table).name)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
