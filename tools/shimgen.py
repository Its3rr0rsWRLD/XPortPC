"""Generate desktop shim DLL sources for console import DLLs from an x2w_report import list.

Usage:
  python -B tools/shimgen.py [--report REPORT.json | --manifest MANIFEST.json | --run-log RUN.log]
                             [--all-specs DLL]... [--out DIR] [--specs DIR]... [--override FILE.toml]...
                             [--dll NAME]... [--include NAME]... [--exclude NAME]...
  python -B tools/shimgen.py --impl-header FILE [--check]

Input. --report takes tools/x2w_report.py's report.json ("x2w-report 1"); --manifest takes a JSON object
mapping DLL names to function lists ({"name.dll": ["Fn", "#12"]}, optionally under a "dlls" key). From a
report, a DLL is generated when no route already provides it: DLLs the title ships ("package"), DLLs with
Windows namesakes ("windows" routes) and the repository's hand-written shims (src/*.def, e.g. xmem.dll) are
skipped unless --include names them. --dll limits the run to the named DLLs; --exclude drops some.
--run-log takes an x2w_launch --log file and uses its "dynamic-resolve dll!name -> shim|missing" lines:
the names a title asked GetProcAddress for in DLLs it loaded at run time (PC GDK builds reach the Gaming
Runtime only this way: xgameruntime.lib loads xgameruntime.dll and resolves names). --all-specs DLL adds
every function of every spec to DLL (used for xgameruntime.dll, whose dynamic name list is not known
before a run). A family whose spec sets `dll` (console libraries with no public documentation, such as
chad.dll) is left out of --all-specs; --family-dlls generates each such DLL with its family's functions.

Specs. Each tools/shimgen/specs/*.toml file describes one API family from public documentation (format in
specs/xgameruntime.toml). For every imported function the generator picks one body:

  forward  only when the family's forwarding is on at run time (X2W_FORWARD=<family>,... or "all"; off for
           every family by default): load the family's PC DLL from X2W_FORWARD_DIR or System32, resolve the
           function by name and call through. If the DLL, its anchor export or the function is missing, the
           fallback below runs and the reason is logged once.
  impl     a hand-written implementation in x2w_gdk.dll (src/gdk), called as x2w_impl_<name>.
  stub     a typed safe stub: out-params zeroed, out-buffers cleared, the documented default returned
           (E_NOTIMPL for HRESULT, zero/false/null otherwise, or the spec's stub_return), first call logged
           through x2w_unimplemented (stderr and, under x2w_launch, the run log).
  unknown  a function no spec describes: an untyped stub that logs its first call and returns 0 in RAX,
           or E_NOTIMPL for names ending in Async, Result or ResultSize (every Gaming Runtime *Async call
           returns HRESULT, and a 0 from an async start would leave the title waiting forever).
           Ordinal imports (#N) are exported by ordinal (NONAME) the same way.

--override files use the spec format and are merged over the specs by function name: they can force
`mode = "stub"`, change `stub_return`, set `forward = false`, give an unknown function a signature, or set
a family's forward_dll/forward_default in a [families.<family>] table.

Output (--out, default out/shimgen): per DLL <stem>.cpp, <stem>.def and <stem>_exports.h (declarations of
the typed exports, for source-built fixtures), shims.cmake (one x2w_generated_shim() call per DLL, read by
CMakeLists.txt) and shimgen.json (what each function became). The report stays names-only: nothing from
the title's bytes is read or copied.

--impl-header writes src/gdk/x2w_gdk_impl.h, the declarations of every impl = true function, from the
specs; --check fails instead if the file differs. The C++ compiler then checks the hand-written
definitions against the specs.
"""
import argparse
from collections import OrderedDict
import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "tools" / "shimgen" / "specs"
IMPL_HEADER = ROOT / "src" / "gdk" / "x2w_gdk_impl.h"
GENERATOR = "shimgen 1"
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROVIDED_CLASSES = {"package", "windows"}
ASYNC_SUFFIXES = ("Async", "Result", "ResultSize")


class SpecError(ValueError):
    pass


def split_params(text):
    """[(type, name)] from a C parameter list; "" and "void" give []."""
    text = text.strip()
    if not text or text == "void":
        return []
    params = []
    for raw in text.split(","):
        raw = " ".join(raw.split())
        match = re.match(r"^(.*?[\s\*&])([A-Za-z_][A-Za-z0-9_]*)$", raw)
        if not match or not match.group(1).strip():
            raise SpecError(f"cannot parse parameter {raw!r}")
        params.append((match.group(1).strip(), match.group(2)))
    return params


class Function:
    FIELDS = {"name", "returns", "params", "doc", "impl", "out", "out_buffers", "stub_return", "forward", "mode"}

    def __init__(self, entry, family, source):
        unknown = set(entry) - self.FIELDS
        if unknown:
            raise SpecError(f"{source}: {entry.get('name')}: unknown fields {sorted(unknown)}")
        self.name = entry["name"]
        if not IDENT.match(self.name):
            raise SpecError(f"{source}: {self.name!r} is not a C identifier")
        self.family = family
        self.source = source
        self.returns = entry.get("returns")
        self.params_text = entry.get("params")
        self.doc = entry.get("doc", "")
        self.impl = bool(entry.get("impl", False))
        self.out = list(entry.get("out", []))
        self.out_buffers = list(entry.get("out_buffers", []))
        self.stub_return = entry.get("stub_return")
        self.forward = entry.get("forward", True)
        self.mode = entry.get("mode")
        self.validate()

    def validate(self):
        if self.returns is None or self.params_text is None:
            raise SpecError(f"{self.source}: {self.name} needs returns and params")
        self.params = split_params(self.params_text)
        names = {name for _, name in self.params}
        for name in self.out:
            if name not in names:
                raise SpecError(f"{self.source}: {self.name}: out {name!r} is not a parameter")
        for pair in self.out_buffers:
            buffer, _, size = pair.partition(":")
            if buffer not in names or size not in names:
                raise SpecError(f"{self.source}: {self.name}: out_buffers {pair!r} must name two parameters")
        if self.mode not in (None, "impl", "stub"):
            raise SpecError(f"{self.source}: {self.name}: mode must be impl or stub")
        if self.mode == "impl" and not self.impl:
            raise SpecError(f"{self.source}: {self.name}: mode impl needs a hand-written implementation")

    def merge(self, entry, source):
        """Apply an override entry."""
        for key, value in entry.items():
            if key not in self.FIELDS:
                raise SpecError(f"{source}: {self.name}: unknown field {key!r}")
            if key == "name":
                continue
            setattr(self, "params_text" if key == "params" else key, value)
        self.source = f"{self.source} + {source}"
        self.validate()

    @property
    def body(self):
        if self.mode == "stub" or not self.impl:
            return "stub"
        return "impl"

    def doc_url(self, families):
        if self.doc.startswith("http"):
            return self.doc
        root = families.get(self.family, {}).get("doc_root", "")
        return root + self.doc if self.doc else root

    def signature(self, name):
        params = ", ".join(f"{t} {n}" for t, n in self.params) or "void"
        return f"{self.returns} {name}({params}) noexcept"

    def default_return(self):
        if self.stub_return is not None:
            return self.stub_return
        if self.returns == "void":
            return None
        if self.returns == "HRESULT":
            return "E_NOTIMPL"
        return "{}"


class Specs:
    def __init__(self, directories, overrides=()):
        self.families = OrderedDict()
        self.functions = OrderedDict()
        for directory in directories:
            for path in sorted(Path(directory).glob("*.toml")):
                self.load(path)
        for path in overrides:
            self.load_override(Path(path))

    def family_fields(self, data, source):
        keys = ("forward_dll", "forward_anchor", "forward_default", "doc_root", "dll", "undocumented")
        fields = {k: data[k] for k in keys if k in data}
        return fields

    def load(self, path):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        family = data.get("family")
        if not family or not IDENT.match(family):
            raise SpecError(f"{path.name}: needs a family identifier")
        fields = self.family_fields(data, path.name)
        known = self.families.setdefault(family, {})
        for key, value in fields.items():
            if key == "doc_root":
                continue
            if key in known and known[key] != value:
                raise SpecError(f"{path.name}: family {family} {key} disagrees with another spec file")
            known[key] = value
        known.setdefault("doc_root", fields.get("doc_root", ""))
        for entry in data.get("functions", []):
            entry = dict(entry)
            if "doc" in entry and not entry["doc"].startswith("http") and fields.get("doc_root"):
                entry["doc"] = fields["doc_root"] + entry["doc"]
            function = Function(entry, family, path.name)
            if function.name in self.functions:
                raise SpecError(f"{path.name}: {function.name} is already in {self.functions[function.name].source}")
            self.functions[function.name] = function

    def load_override(self, path):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for family, fields in data.get("families", {}).items():
            self.families.setdefault(family, {}).update(fields)
        default_family = data.get("family", "override")
        if "family" in data:
            fields = self.family_fields(data, path.name)
            self.families.setdefault(default_family, {}).update(fields)
        for entry in data.get("functions", []):
            name = entry.get("name")
            if name in self.functions:
                self.functions[name].merge(entry, path.name)
            else:
                function = Function(dict(entry), entry.get("family", default_family), path.name)
                self.functions[name] = function


def hand_written_shims():
    """LIBRARY names of the repository's own .def files (xmem.dll, d3d12_xs.dll, ...)."""
    names = set()
    for path in (ROOT / "src").glob("*.def"):
        for line in path.read_text(encoding="utf-8").splitlines():
            words = line.split(";", 1)[0].split()
            if words and words[0].upper() == "LIBRARY":
                dll = words[1].strip('"').lower()
                names.add(dll if dll.endswith(".dll") else dll + ".dll")
    return names


def imports_from_report(report, include=(), log=print):
    if report.get("schema") != "x2w-report 1":
        raise SystemExit(f"unexpected report schema {report.get('schema')!r}")
    by_dll = OrderedDict()
    for row in report["imports"]:
        by_dll.setdefault(row["dll"].lower(), []).append(row)
    own = hand_written_shims()
    chosen = OrderedDict()
    for dll, rows in by_dll.items():
        routes = {row["route"] for row in rows}
        classes = {row["class"] for row in rows}
        reason = None
        if dll in own:
            reason = "hand-written shim in src/"
        elif "package" in routes or "package" in classes:
            reason = "the title ships this DLL"
        elif "windows" in routes or "windows" in classes:
            reason = "Windows has a DLL of this name"
        if reason and dll not in include:
            log(f"skip {dll}: {reason} (--include {dll} to generate it anyway)")
            continue
        chosen[dll] = [row["function"] for row in rows]
    return chosen


def imports_from_manifest(manifest):
    data = manifest.get("dlls", manifest)
    if not isinstance(data, dict):
        raise SystemExit("a manifest is a JSON object mapping DLL names to function lists")
    return OrderedDict((dll.lower(), list(functions)) for dll, functions in data.items())


def imports_from_run_log(text):
    """DLL -> names from x2w_launch run-log lines "dynamic-resolve dll!name -> route"."""
    chosen = OrderedDict()
    for line in text.splitlines():
        match = re.match(r"^dynamic-resolve (\S+?)!(\S+) -> (\S+)", line)
        # "unknown-0x..." names a handle no module owns: there is no DLL to generate.
        if match and match.group(3) in ("shim", "missing") and not match.group(1).startswith("unknown-"):
            chosen.setdefault(match.group(1).lower(), []).append(match.group(2))
    return chosen


def dll_stem(dll):
    return dll[:-4] if dll.lower().endswith(".dll") else dll


def target_name(dll):
    return "x2w_shim_" + re.sub(r"[^A-Za-z0-9_]", "_", dll_stem(dll))


def c_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def plan_dll(dll, functions, specs):
    """[(export name or None, ordinal or None, Function or None, body)] in import order, deduplicated."""
    seen, plan, skipped = set(), [], []
    for function in functions:
        if function in seen:
            continue
        seen.add(function)
        if function.startswith("#"):
            plan.append((None, int(function[1:]), None, "unknown"))
            continue
        if not IDENT.match(function) or function.startswith("x2w_"):
            skipped.append(function)
            continue
        spec = specs.functions.get(function)
        plan.append((function, None, spec, spec.body if spec else "unknown"))
    return plan, skipped


def forward_block(spec, specs, call):
    family = specs.families.get(spec.family, {})
    dll = family.get("forward_dll")
    if not dll or not spec.forward:
        return []
    anchor = family.get("forward_anchor", "")
    default = 1 if family.get("forward_default") else 0
    types = ", ".join(t for t, _ in spec.params)
    lines = [f"    using Forward = {spec.returns} (*)({types});",
             f"    static void* const forward = x2w_forward_resolve({c_string(spec.family)}, {c_string(dll)},"
             f" {c_string(anchor)}, {c_string(spec.name)}, {default});"]
    if spec.returns == "void":
        lines.append(f"    if (forward) {{ reinterpret_cast<Forward>(forward)({call}); return; }}")
    else:
        lines.append(f"    if (forward) return reinterpret_cast<Forward>(forward)({call});")
    return lines


def render_dll(dll, plan, specs):
    stem = dll_stem(dll)
    cpp = [f"// Generated by tools/shimgen.py ({GENERATOR}) for {dll}. Do not edit; regenerate instead.",
           "// Each export forwards (when its family's forwarding is on), calls a hand-written implementation",
           "// in x2w_gdk.dll, or is a safe stub that logs its first call. See tools/shimgen.py.",
           '#include "x2w_gdk.h"', "#include <intrin.h>", "#include <string.h>", "",
           "#define X2W_FIRST_CALL(symbol, detail) \\",
           "    do { \\",
           "        static volatile LONG x2w_once = 0; \\",
           "        if (!x2w_once && !InterlockedExchange(&x2w_once, 1)) \\",
           "            x2w_stub_called(symbol, detail, _ReturnAddress()); \\",
           "    } while (0)", "",
           f'extern "C" const char* x2w_export_x2w_shimgen_dll() noexcept {{ return {c_string(dll + " " + GENERATOR)}; }}',
           ""]
    header = [f"// Generated by tools/shimgen.py ({GENERATOR}): the typed exports of {dll}.", "#pragma once",
              '#include "x2w_gdk_types.h"', "", 'extern "C" {']
    exports = ["x2w_shimgen_dll = x2w_export_x2w_shimgen_dll"]
    rows = []
    for name, ordinal, spec, body in plan:
        symbol = f"{stem}!{name}" if name else f"{stem}!#{ordinal}"
        internal = f"x2w_export_{name}" if name else f"x2w_export_ordinal_{ordinal}"
        if spec is None:
            hresult = name is not None and name.endswith(ASYNC_SUFFIXES)
            value = "static_cast<uintptr_t>(static_cast<ULONG>(E_NOTIMPL))" if hresult else "0"
            detail = "untyped stub returns E_NOTIMPL" if hresult else "untyped stub returns 0"
            cpp += [f"// {symbol}: no spec. {detail}.",
                    f'extern "C" uintptr_t {internal}() noexcept',
                    "{", f"    X2W_FIRST_CALL({c_string(symbol)}, {c_string(detail)});",
                    f"    return {value};", "}", ""]
            exports.append(f"{name} = {internal}" if name else f"{internal} @{ordinal} NONAME")
            rows.append(OrderedDict(function=name or f"#{ordinal}", body="unknown", detail=detail))
            continue
        call = ", ".join(n for _, n in spec.params)
        url = spec.doc_url(specs.families)
        cpp += [f"// {symbol}: {body}. {url or 'No public documentation: the signature is an assumption.'}",
                f'extern "C" {spec.signature(internal)}', "{"]
        cpp += forward_block(spec, specs, call)
        if body == "impl":
            cpp.append(f"    {'return ' if spec.returns != 'void' else ''}x2w_impl_{spec.name}({call});")
            detail = "x2w_gdk implementation"
        else:
            for out in spec.out:
                cpp.append(f"    if ({out}) *{out} = {{}};")
            for pair in spec.out_buffers:
                buffer, _, size = pair.partition(":")
                cpp.append(f"    if ({buffer} && {size}) memset({buffer}, 0, {size});")
            for _, param in spec.params:
                if param not in spec.out and all(not p.startswith(param + ":") for p in spec.out_buffers):
                    cpp.append(f"    (void){param};")
            value = spec.default_return()
            detail = f"stub returns {value if value is not None else 'nothing'}"
            cpp.append(f"    X2W_FIRST_CALL({c_string(symbol)}, {c_string(detail)});")
            if value is not None:
                cpp.append(f"    return {value};")
        cpp += ["}", ""]
        header.append(f"__declspec(dllimport) {spec.signature(spec.name)};")
        exports.append(f"{name} = {internal}")
        forwarding = bool(specs.families.get(spec.family, {}).get("forward_dll")) and spec.forward
        rows.append(OrderedDict(function=name, body=body, family=spec.family, forward=forwarding, detail=detail,
                                doc=url))
    header += ["}", ""]
    library = stem if "." not in stem else f'"{stem}"'
    definition = [f"LIBRARY {library}", "EXPORTS"] + [f"    {line}" for line in exports]
    return "\n".join(cpp) + "\n", "\n".join(definition) + "\n", "\n".join(header), rows


def write_if_changed(path, text):
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8", newline="\n")


def generate(imports, specs, out, log=print):
    out.mkdir(parents=True, exist_ok=True)
    summary = OrderedDict(generator=GENERATOR, dlls=OrderedDict())
    cmake = ["# Generated by tools/shimgen.py. One generated shim per console DLL name."]
    for dll, functions in imports.items():
        plan, skipped = plan_dll(dll, functions, specs)
        stem = dll_stem(dll)
        cpp, definition, header, rows = render_dll(dll, plan, specs)
        write_if_changed(out / f"{stem}.cpp", cpp)
        write_if_changed(out / f"{stem}.def", definition)
        write_if_changed(out / f"{stem}_exports.h", header)
        cmake.append(f'x2w_generated_shim({target_name(dll)} "{stem}" "${{CMAKE_CURRENT_LIST_DIR}}/{stem}.cpp"'
                     f' "${{CMAKE_CURRENT_LIST_DIR}}/{stem}.def")')
        counts = OrderedDict((b, sum(1 for r in rows if r["body"] == b)) for b in ("impl", "stub", "unknown"))
        forwardable = sum(1 for r in rows if r.get("forward"))
        summary["dlls"][dll] = OrderedDict(target=target_name(dll), counts=counts, forwardable=forwardable,
                                           skipped=skipped, functions=rows)
        log(f"{dll}: {len(rows)} exports: impl {counts['impl']}, stub {counts['stub']}, unknown {counts['unknown']}"
            f" ({forwardable} can forward)" + (f"; skipped non-identifier names {skipped}" if skipped else ""))
    write_if_changed(out / "shims.cmake", "\n".join(cmake) + "\n")
    write_if_changed(out / "shimgen.json", json.dumps(summary, indent=2) + "\n")
    return summary


def impl_header(specs):
    lines = ["#pragma once",
             "// Generated by tools/shimgen.py --impl-header from tools/shimgen/specs. Do not edit; regenerate.",
             "// The hand-written implementations in src/gdk/*.cpp, exported by x2w_gdk.dll and called by the",
             "// generated shims. Their definitions must match these declarations, so the compiler checks the",
             "// specs against the code.",
             '#include "x2w_gdk_types.h"', "", "#ifndef X2W_GDK_API", "#ifdef X2W_GDK_EXPORTS",
             "#define X2W_GDK_API __declspec(dllexport)", "#else", "#define X2W_GDK_API __declspec(dllimport)",
             "#endif", "#endif", "", 'extern "C" {']
    family = None
    for spec in specs.functions.values():
        if not spec.impl:
            continue
        if spec.family != family:
            family = spec.family
            lines += ["", f"// {family}"]
        lines.append(f"X2W_GDK_API {spec.signature('x2w_impl_' + spec.name)};")
    lines += ["", "}  // extern \"C\"", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--report", type=Path, help="tools/x2w_report.py report.json")
    source.add_argument("--manifest", type=Path, help="JSON object: DLL name -> function names")
    source.add_argument("--run-log", type=Path, help="x2w_launch --log file (dynamic-resolve lines)")
    parser.add_argument("--all-specs", action="append", default=[], help="DLL that exports every spec function")
    parser.add_argument("--family-dlls", action="store_true",
                        help="generate each DLL a spec family names with `dll`, with that family's functions")
    parser.add_argument("--out", type=Path, default=ROOT / "out" / "shimgen")
    parser.add_argument("--specs", type=Path, action="append", help="spec directory (default tools/shimgen/specs)")
    parser.add_argument("--override", type=Path, action="append", default=[])
    parser.add_argument("--dll", action="append", default=[], help="generate only these DLLs")
    parser.add_argument("--include", action="append", default=[], help="generate a DLL the report routes elsewhere")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--impl-header", type=Path, nargs="?", const=IMPL_HEADER)
    parser.add_argument("--check", action="store_true", help="with --impl-header: fail if the file is stale")
    args = parser.parse_args(argv)

    try:
        specs = Specs(args.specs or [SPEC_DIR], args.override)
    except (SpecError, tomllib.TOMLDecodeError) as error:
        raise SystemExit(f"shimgen: {error}")
    if args.impl_header:
        text = impl_header(specs)
        if args.check:
            current = args.impl_header.read_text(encoding="utf-8") if args.impl_header.exists() else ""
            if current.replace("\r\n", "\n") != text:
                raise SystemExit(f"shimgen: {args.impl_header} is stale; run tools/shimgen.py --impl-header")
            print(f"{args.impl_header.name} is up to date")
            return 0
        write_if_changed(args.impl_header, text)
        print(f"wrote {args.impl_header}")
        return 0
    if not args.report and not args.manifest and not args.run_log and not args.all_specs and not args.family_dlls:
        parser.error("give --report, --manifest, --run-log, --all-specs or --family-dlls")
    include = {d.lower() for d in args.include}
    if args.report:
        imports = imports_from_report(json.loads(args.report.read_text(encoding="utf-8")), include)
    elif args.manifest:
        imports = imports_from_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    elif args.run_log:
        imports = imports_from_run_log(args.run_log.read_text(encoding="utf-8", errors="replace"))
    else:
        imports = OrderedDict()
    family_dll = {f: v["dll"].lower() for f, v in specs.families.items() if v.get("dll")}
    for dll in args.all_specs:
        imports.setdefault(dll.lower(), []).extend(n for n, s in specs.functions.items() if s.family not in family_dll)
    if args.family_dlls:
        for name, spec in specs.functions.items():
            if spec.family in family_dll:
                imports.setdefault(family_dll[spec.family], []).append(name)
    wanted = {d.lower() for d in args.dll}
    excluded = {d.lower() for d in args.exclude}
    imports = OrderedDict((d, f) for d, f in imports.items() if (not wanted or d in wanted) and d not in excluded)
    if not imports:
        print("shimgen: no DLLs to generate", file=sys.stderr)
    generate(imports, specs, args.out)
    print(f"wrote {len(imports)} shim(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
