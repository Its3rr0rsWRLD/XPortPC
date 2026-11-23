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
# Values a class's `fallback` may name: what a slot with no implementation answers (default E_NOTIMPL).
FALLBACKS = {
    "E_NOTIMPL": 0x80004001,
    "E_GAMEUSER_NO_DEFAULT_USER": 0x89245106,  # src/gdk/x2w_gdk_types.h, XUser error codes
}


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


def load_slots(owner, entries):
    slots = {}
    for slot in entries:
        index = slot.get("index")
        if not isinstance(index, int) or not 3 <= index < MAX_SLOTS:
            raise TableError(f"{owner}: slot index {index!r} must be 3..{MAX_SLOTS - 1}")
        if index in slots:
            raise TableError(f"{owner}: slot {index} is listed twice")
        unknown = set(slot) - {"index", "function", "evidence", "impl", "returns", "params", "inferred"}
        if unknown:
            raise TableError(f"{owner}: slot {index}: unknown fields {sorted(unknown)}")
        if "evidence" not in slot:
            raise TableError(f"{owner}: slot {index} needs evidence")
        function = slot.get("function", "")
        if function and not IDENT.match(function):
            raise TableError(f"{owner}: slot {index} function {function!r}")
        if not isinstance(slot.get("inferred", False), bool):
            raise TableError(f"{owner}: slot {index}: inferred must be true or false")
        if slot.get("inferred") and not function:
            raise TableError(f"{owner}: slot {index}: an inferred slot names the function it is taken to be")
        if slot.get("impl") not in (None, "xgr"):
            raise TableError(f"{owner}: slot {index}: impl must be \"xgr\" (src/xgr/xgr_extra.cpp) or absent")
        if slot.get("impl") == "xgr":
            if not function or "returns" not in slot or "params" not in slot:
                raise TableError(f"{owner}: slot {index}: impl = \"xgr\" needs function, returns and params")
            shimgen.split_params(slot["params"])
        slots[index] = slot
    return slots


def load_table(path):
    """[class] with class["interfaces"][i]["_slots"] = {index: slot}, inherited slots included."""
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
        if klass.get("fallback", "E_NOTIMPL") not in FALLBACKS:
            raise TableError(f"{klass['name']}: fallback must be one of {sorted(FALLBACKS)}")
        unknown = set(klass) - {"name", "clsid", "evidence", "interfaces", "fallback"}
        if unknown:
            raise TableError(f"{klass['name']}: unknown fields {sorted(unknown)}")
        clsid = klass["clsid"].lower()
        guid_initializer(clsid)
        if clsid in seen_clsid:
            raise TableError(f"CLSID {clsid} is listed twice")
        seen_clsid.add(clsid)
        interfaces = klass.get("interfaces", [])
        if not interfaces:
            raise TableError(f"{klass['name']}: needs at least one interface")
        by_name = {}
        for interface in interfaces:
            for key in ("name", "iid", "evidence"):
                if key not in interface:
                    raise TableError(f"{klass['name']}: interface {interface.get('name')!r} needs {key}")
            if not IDENT.match(interface["name"]) or interface["name"] in seen_name:
                raise TableError(f"interface name {interface['name']!r} is not a unique identifier")
            seen_name.add(interface["name"])
            iid = interface["iid"].lower()
            guid_initializer(iid)
            if iid in seen_iid:
                raise TableError(f"IID {iid} is listed twice")
            seen_iid.add(iid)
            interface["_own"] = load_slots(interface["name"], interface.get("slots", []))
            by_name[interface["name"]] = interface
        for interface in interfaces:
            # Versions are append-only: an interface that extends another has all of its slots first.
            chain, current = [], interface
            while current is not None:
                if current["name"] in [c["name"] for c in chain]:
                    raise TableError(f"{interface['name']}: extends loops")
                chain.append(current)
                base = current.get("extends")
                if base and base not in by_name:
                    raise TableError(f"{current['name']}: extends unknown interface {base!r} of {klass['name']}")
                current = by_name.get(base) if base else None
            merged = {}
            for link in reversed(chain):
                for index, slot in link["_own"].items():
                    if index in merged and merged[index].get("function") != slot.get("function"):
                        raise TableError(f"{interface['name']}: slot {index} disagrees with {link['name']}")
                    merged[index] = slot
            interface["_slots"] = merged
    return classes


def wrapper(owner, index, slot, specs, cache):
    """(C++ definition or None, target expression) for one slot; one wrapper per (function, kind)."""
    function = slot.get("function", "")
    if slot.get("impl") == "xgr":
        returns, params = slot["returns"], shimgen.split_params(slot["params"])
        callee, doc, body_kind = f"xgr_impl_{function}", "src/xgr/xgr_extra.cpp", "impl"
        spec = None
    else:
        spec = specs.functions.get(function) if function else None
        if spec is None:
            return None, "nullptr"
        returns, params = spec.returns, spec.params
        callee, doc, body_kind = f"x2w_impl_{function}", spec.doc_url(specs.families), spec.body
    name = f"xgr_m_{function}"
    target = f"reinterpret_cast<void*>(&{name})"
    if name in cache:
        return None, target
    cache.add(name)
    args = ", ".join(n for _, n in params)
    lines = [f"// {function} ({doc})"]
    if returns in STRUCT_RETURNS:
        plist = ", ".join(["void* /*self*/", f"{returns}* result"] + [f"{t} {n}" for t, n in params])
        value = f"{callee}({args})" if body_kind == "impl" else "{}"
        if body_kind != "impl":
            lines.append(f"// (not implemented: returns a zeroed {returns})")
        lines.append(f"static {returns}* {name}({plist}) noexcept {{ *result = {value}; return result; }}")
        return "\n".join(lines), target
    plist = ", ".join(["void* /*self*/"] + [f"{t} {n}" for t, n in params])
    if body_kind == "impl":
        call = f"{callee}({args})"
        body = f"{call};" if returns == "void" else f"return {call};"
        lines.append(f"static {returns} {name}({plist}) noexcept {{ {body} }}")
    else:
        body = [f'    x2w_stub_called("xgameruntime.dll!{function}", "xgr gateway {owner} slot {index}", _ReturnAddress());']
        for out in spec.out:
            body.append(f"    if ({out}) *{out} = {{}};")
        for n in [n for _, n in params if n not in spec.out]:
            body.insert(0, f"    (void){n};")
        default = spec.default_return()
        body.append("    return;" if default is None else f"    return {default};")
        lines.append(f"static {returns} {name}({plist}) noexcept\n{{\n" + "\n".join(body) + "\n}")
    return "\n".join(lines), target


def xgr_declarations(classes):
    out, seen = [], set()
    for klass in classes:
        for interface in klass["interfaces"]:
            for slot in interface["_own"].values():
                if slot.get("impl") == "xgr" and slot["function"] not in seen:
                    seen.add(slot["function"])
                    out.append(f"{slot['returns']} xgr_impl_{slot['function']}({slot['params'] or 'void'}) noexcept;")
    return out


def render(classes, specs, source):
    out = [
        f"// Generated by tools/xgr_gen.py from {source} and tools/shimgen/specs. Do not edit; regenerate.",
        "// Included by src/xgr/xgr_gateway.cpp after XgrClass and XgrInterface.",
        "",
    ]
    declarations = xgr_declarations(classes)
    if declarations:
        out.append("// Gateway-local implementations (src/xgr/xgr_extra.cpp).")
        out.extend(declarations)
        out.append("")
    class_rows, interface_rows, cache = [], [], set()
    for class_index, klass in enumerate(classes):
        fallback = FALLBACKS[klass.get("fallback", "E_NOTIMPL")]
        class_rows.append(f'    {{"{klass["name"]}", {guid_initializer(klass["clsid"])}, '
                          f'static_cast<long>(0x{fallback:08x}u)}},')
        for interface in klass["interfaces"]:
            slots = interface["_slots"]
            count = max([3] + [i + 1 for i in slots])
            targets = ["nullptr"] * count
            inferred = ["nullptr"] * count
            for index in sorted(slots):
                definition, target = wrapper(interface["name"], index, slots[index], specs, cache)
                if definition:
                    out.append(definition)
                # An inferred slot (position not traced) is never served by default: a wrong guess that writes
                # through an argument corrupts the title's memory. X2W_XGR_INFERRED=1 serves it (experiments).
                (inferred if slots[index].get("inferred") else targets)[index] = target
            name = interface["name"]
            out.append(f"static void* const xgr_targets_{name}[{count}] = {{")
            for i, t in enumerate(targets):
                label = slots[i].get("function", "") if i in slots else ("IUnknown" if i < 3 else "")
                if i in slots and slots[i].get("inferred"):
                    label += " (inferred: not served)"
                out.append(f"    {t},  // {i} {label}".rstrip())
            out.append("};")
            inferred_ref = "nullptr"
            if any(t != "nullptr" for t in inferred) or any(s.get("inferred") for s in slots.values()):
                inferred_ref = f"xgr_inferred_{name}"
                out.append(f"static void* const xgr_inferred_{name}[{count}] = {{")
                for i, t in enumerate(inferred):
                    out.append(f"    {t},  // {i} {slots[i].get('function', '') if i in slots and slots[i].get('inferred') else ''}".rstrip())
                out.append("};")
                out.append(f"static const char* const xgr_inferred_names_{name}[{count}] = {{")
                for i in range(count):
                    label = slots[i]["function"] if i in slots and slots[i].get("inferred") else ""
                    out.append(f'    {f"{chr(34)}{label}{chr(34)}" if label else "nullptr"},')
                out.append("};")
            out.append("")
            names_ref = f"xgr_inferred_names_{name}" if inferred_ref != "nullptr" else "nullptr"
            interface_rows.append(f'    {{"{name}", {guid_initializer(interface["iid"])}, {class_index}u, '
                                  f"xgr_targets_{name}, {count}u, {inferred_ref}, {names_ref}}},")
    out.append(f"static const XgrClass xgr_classes[{max(1, len(class_rows))}] = {{")
    out.extend(class_rows or ['    {"(none)", {}, 0},'])
    out.append("};")
    out.append(f"static const unsigned xgr_class_count = {len(class_rows)}u;")
    out.append(f"static const XgrInterface xgr_interfaces[{max(1, len(interface_rows))}] = {{")
    out.extend(interface_rows or ['    {"(none)", {}, 0u, nullptr, 0u, nullptr, nullptr},'])
    out.append("};")
    out.append(f"static const unsigned xgr_interface_count = {len(interface_rows)}u;")
    return "\n".join(out) + "\n"


def audit(classes, specs):
    """Prints, per shimgen family, which flat functions the gateway reaches through a slot. A function with no
    slot cannot be called by a PC GDK title (its CLSID/IID/slot is not yet learned); the title's query for it
    gets a logging fallback object (src/xgr/xgr_gateway.cpp), not a crash."""
    reached = {s.get("function") for k in classes for i in k["interfaces"] for s in i["_slots"].values()
               if not s.get("inferred")}
    families = {}
    for name, function in specs.functions.items():
        families.setdefault(function.family, []).append((name, name in reached))
    for family in sorted(families):
        rows = families[family]
        missing = [n for n, ok in rows if not ok]
        print(f"xgr_audit {family}: {len(rows) - len(missing)}/{len(rows)} reachable"
              + (f"; no slot: {', '.join(missing)}" if missing else ""))
    for klass in classes:
        for interface in klass["interfaces"]:
            print(f"xgr_audit interface {interface['name']} ({klass['name']}, fallback "
                  f"{klass.get('fallback', 'E_NOTIMPL')}): {len(interface['_slots'])} slots mapped")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default=str(ROOT / "tools" / "xgr" / "interfaces.toml"))
    parser.add_argument("--specs", default=str(ROOT / "tools" / "shimgen" / "specs"))
    parser.add_argument("--out")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true", help="print which spec functions the gateway reaches")
    args = parser.parse_args(argv)
    try:
        classes = load_table(args.table)
        specs = shimgen.Specs([args.specs])
    except (TableError, shimgen.SpecError, tomllib.TOMLDecodeError) as error:
        print(f"xgr_gen: {error}", file=sys.stderr)
        return 1
    own = [s for k in classes for i in k["interfaces"] for s in i["_own"].values()]
    named = sum(1 for s in own if s.get("function"))
    implemented = sum(1 for s in own if s.get("impl") == "xgr" or (
        s.get("function") in specs.functions and specs.functions[s["function"]].body == "impl"))
    inferred = sum(1 for s in own if s.get("inferred"))
    print(f"xgr_gen: {len(classes)} classes, {sum(len(k['interfaces']) for k in classes)} interfaces, "
          f"{len(own)} slots ({named} named, {implemented} implemented, {inferred} inferred and not served)")
    if args.audit:
        audit(classes, specs)
        return 0
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
