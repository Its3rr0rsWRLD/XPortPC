"""Report what a title's executable needs from XPortPC, without running or loading it.

Usage:
  python -B tools/x2w_report.py TITLE.exe [--folder DIR] [--shims DIR]... [--windows-dir DIR]
                                [--shaders DIR] [--shader-archive FILE]... [--llvm LIB] [--out DIR]

The tool reads the PE headers and the import tables with pefile and writes report.md and report.json to
--out (default out/x2w-report). Each import (ordinary and delay, by name or "#ordinal") is classified the way
x2w_launch would route it:

  implemented  a --shims DIR holds the DLL and exports the function (without --shims, the repository's
               src/*.def files stand in for the built shims);
  package      a DLL of that name beside the executable (or in --folder) exports the function by name;
  windows      Windows has the DLL and the function (on Windows: System32 and API sets, looked up with
               LoadLibraryEx(DONT_RESOLVE_DLL_REFERENCES) and GetProcAddress, so no DLL code runs; elsewhere
               only with --windows-dir);
  stub         some route has the DLL but not the function, so x2w_launch binds a logging stub;
  missing      no route has the DLL, so x2w_launch binds a logging stub;
  unverified   no Windows lookup was available on this host.

The report holds names, counts and classifications only: DLL and function names from the import tables,
section names, sizes, RVAs and counts. It never copies section bytes, embedded data, other strings or
assets. tests/native/report_check.py checks that property. The optional shader census reads
already-extracted shader files (--shaders, through tools/scan_unsupported_shaders.py) and shader archives
(--shader-archive, through tools/shader_census.py) in place and reports totals and an opcode histogram only:
no shader names, file names, instruction text or rejection messages.
"""
import argparse
from collections import Counter, OrderedDict
import contextlib
import json
import mmap
import os
from pathlib import Path
import struct
import sys

import pefile

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ("implemented", "package", "windows", "stub", "missing", "unverified")
SCHEMA = "x2w-report 1"
# Section flags as pe_map applies them.
SCN_EXECUTE, SCN_READ, SCN_WRITE = 0x20000000, 0x40000000, 0x80000000


def clean_name(raw):
    """A name from the file as printable ASCII; anything else is escaped, never passed through."""
    if isinstance(raw, str):
        raw = raw.encode("latin-1", "backslashreplace")
    raw = raw.split(b"\0", 1)[0]
    return "".join(chr(b) if 0x20 < b < 0x7f and b != 0x5c else f"\\x{b:02x}" for b in raw)


def def_exports(path):
    """(dll, names) from a module-definition file: LIBRARY name and the EXPORTS names."""
    library, names, exports = None, set(), False
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.split(";", 1)[0].strip()
        if not text:
            continue
        words = text.split()
        if words[0].upper() == "LIBRARY":
            library = words[1].strip('"')
            exports = False
        elif words[0].upper() == "EXPORTS":
            exports = True
        elif exports:
            names.add(words[0].split("=", 1)[0])
    if not library:
        raise ValueError(f"{path.name} has no LIBRARY line")
    dll = library.lower()
    return (dll if dll.endswith(".dll") else dll + ".dll"), names


def pe_exports(path):
    """Named exports, exported ordinals and forwarded names of a DLL file, read without loading it."""
    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
        names, ordinals, forwarded = set(), set(), set()
        for symbol in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []):
            ordinals.add(symbol.ordinal)
            if symbol.name:
                name = symbol.name.decode("latin-1")
                names.add(name)
                if symbol.forwarder:
                    forwarded.add(name)
        return names, ordinals, forwarded
    finally:
        pe.close()


def find_file(directory, name):
    """directory/name with Windows' case-insensitive match, or None."""
    if directory is None or not directory.is_dir():
        return None
    exact = directory / name
    if exact.is_file():
        return exact
    folded = name.casefold()
    for entry in directory.iterdir():
        if entry.name.casefold() == folded and entry.is_file():
            return entry
    return None


class DllExports:
    def __init__(self, path=None, names=(), ordinals=(), forwarded=(), source=""):
        self.path, self.source = path, source
        self.names, self.ordinals, self.forwarded = set(names), set(ordinals), set(forwarded)
        self.readable = True

    @classmethod
    def read(cls, path, source):
        try:
            names, ordinals, forwarded = pe_exports(path)
        except (OSError, pefile.PEFormatError):
            entry = cls(path, source=source)
            entry.readable = False
            return entry
        return cls(path, names, ordinals, forwarded, source)


class WindowsLookup:
    """Whether Windows provides dll!function, without running any DLL code."""

    def __init__(self, windows_dir=None):
        self.directory = windows_dir
        self.cache = {}
        self.available = windows_dir is not None or os.name == "nt"
        self.source = ("--windows-dir" if windows_dir is not None else
                       "System32 via LoadLibraryEx(DONT_RESOLVE_DLL_REFERENCES)" if os.name == "nt" else "none")
        if windows_dir is None and os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.LoadLibraryExW.restype = wintypes.HMODULE
            kernel32.LoadLibraryExW.argtypes = (wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD)
            kernel32.GetProcAddress.restype = ctypes.c_void_p
            kernel32.GetProcAddress.argtypes = (wintypes.HMODULE, ctypes.c_void_p)
            self.kernel32, self.ctypes = kernel32, ctypes

    def module(self, dll):
        """True or False for a DLL, or None when there is no lookup."""
        if not self.available:
            return None
        if dll not in self.cache:
            if self.directory is not None:
                path = find_file(self.directory, dll)
                self.cache[dll] = DllExports.read(path, "windows") if path else None
            else:
                # DONT_RESOLVE_DLL_REFERENCES (1) maps without DllMain; SEARCH_SYSTEM32 (0x800) keeps the
                # lookup to Windows' own DLLs and API sets.
                handle = self.kernel32.LoadLibraryExW(dll, None, 0x1 | 0x800)
                if handle:
                    self.cache[dll] = handle
                else:
                    # If the loader refuses the flags, read the export table of System32's file instead.
                    path = find_file(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32", dll)
                    self.cache[dll] = DllExports.read(path, "windows") if path else None
        return self.cache[dll] is not None

    def has(self, dll, name, ordinal):
        entry = self.cache.get(dll)
        if isinstance(entry, DllExports):
            return name in entry.names if name is not None else ordinal in entry.ordinals
        if name is not None:
            key = self.ctypes.c_char_p(name.encode("latin-1"))
            return bool(self.kernel32.GetProcAddress(entry, self.ctypes.cast(key, self.ctypes.c_void_p)))
        return bool(self.kernel32.GetProcAddress(entry, ordinal))


class Routes:
    """x2w_launch's import routes: shim directories, the program's folder, Windows, then a stub."""

    def __init__(self, folder, shim_dirs=None, windows=None):
        self.folder = folder
        self.windows = windows or WindowsLookup()
        self.shims = OrderedDict()
        self.shim_source = "shim directories" if shim_dirs else "src/*.def (no --shims given)"
        self.shim_dirs = list(shim_dirs or [])
        if not shim_dirs:
            for path in sorted((ROOT / "src").glob("*.def")):
                dll, names = def_exports(path)
                self.shims[dll] = DllExports(None, names, source="def")
        self.packages = {}

    def shim(self, dll):
        if not self.shim_dirs:
            return self.shims.get(dll)
        if dll not in self.shims:
            self.shims[dll] = None
            for directory in self.shim_dirs:
                path = find_file(directory, dll)
                if path:
                    self.shims[dll] = DllExports.read(path, "shim")
                    break
        return self.shims[dll]

    def package(self, dll):
        if dll not in self.packages:
            path = find_file(self.folder, dll)
            self.packages[dll] = DllExports.read(path, "package") if path else None
        return self.packages[dll]

    def classify(self, dll, name, ordinal):
        """(class, route) for one import."""
        shim = self.shim(dll)
        if shim is not None:
            if name is None and shim.source == "def":
                return "stub", "shim (an ordinal cannot be checked against a .def file)"
            found = name in shim.names if name is not None else ordinal in shim.ordinals
            return ("implemented", "shim") if shim.readable and found else ("stub", "shim")
        package = self.package(dll)
        if package is not None:
            # pe_map_export resolves names only, and not forwarded exports.
            found = name is not None and name in package.names and name not in package.forwarded
            return ("package", "package") if package.readable and found else ("stub", "package")
        present = self.windows.module(dll)
        if present is None:
            return "unverified", "windows lookup unavailable"
        if present:
            return ("windows", "windows") if self.windows.has(dll, name, ordinal) else ("stub", "windows")
        return "missing", "none"


def section_flags(characteristics):
    return "".join(flag if characteristics & bit else "-" for flag, bit in
                   (("R", SCN_READ), ("W", SCN_WRITE), ("X", SCN_EXECUTE)))


def section_of(pe, rva):
    for section in pe.sections:
        span = section.Misc_VirtualSize or section.SizeOfRawData
        if section.VirtualAddress <= rva < section.VirtualAddress + span:
            return section
    return None


def read_rva(pe, rva, length):
    data = pe.get_data(rva, length)
    if len(data) != length:
        raise ValueError(f"truncated header data at RVA {rva:#x}")
    return data


def directory(pe, index):
    dirs = pe.OPTIONAL_HEADER.DATA_DIRECTORY
    return dirs[index] if len(dirs) > index else None


def pe_facts(pe):
    file_header, optional = pe.FILE_HEADER, pe.OPTIONAL_HEADER
    plus = optional.Magic == 0x20B
    sections = []
    for section in pe.sections:
        sections.append(OrderedDict(
            name=clean_name(section.Name), virtual_address=section.VirtualAddress,
            virtual_size=section.Misc_VirtualSize, raw_size=section.SizeOfRawData,
            flags=section_flags(section.Characteristics)))
    entry = optional.AddressOfEntryPoint
    entry_section = section_of(pe, entry) if entry else None

    tls = OrderedDict(present=False, callbacks=0, callback_rvas=[], template_bytes=0, zero_fill=0)
    tls_dir = directory(pe, 9)
    if tls_dir is not None and tls_dir.VirtualAddress:
        tls["present"] = True
        fmt, width = ("<4Q2I", 8) if plus else ("<6I", 4)
        start, end, _index, callbacks, zero_fill, _flags = struct.unpack(
            fmt, read_rva(pe, tls_dir.VirtualAddress, struct.calcsize(fmt)))
        tls["template_bytes"] = max(0, end - start)
        tls["zero_fill"] = zero_fill
        if callbacks:
            table = callbacks - optional.ImageBase
            for i in range(257):
                (va,) = struct.unpack("<Q" if plus else "<I", read_rva(pe, table + width * i, width))
                if not va:
                    break
                tls["callback_rvas"].append(va - optional.ImageBase)
            tls["callbacks"] = len(tls["callback_rvas"])

    relocations = OrderedDict(present=False, directory_size=0, blocks=0, entries=0,
                              stripped=bool(file_header.Characteristics & 0x0001))
    reloc_dir = directory(pe, 5)
    if reloc_dir is not None and reloc_dir.VirtualAddress and reloc_dir.Size:
        relocations.update(present=True, directory_size=reloc_dir.Size)
        offset = 0
        while offset + 8 <= reloc_dir.Size:
            _page, size = struct.unpack("<2I", read_rva(pe, reloc_dir.VirtualAddress + offset, 8))
            if size < 8:
                break
            relocations["blocks"] += 1
            relocations["entries"] += (size - 8) // 2
            offset += size

    exceptions = directory(pe, 3)
    machine = file_header.Machine
    subsystem = optional.Subsystem
    characteristics = file_header.Characteristics
    dll_characteristics = optional.DllCharacteristics
    return OrderedDict(
        machine=pefile.MACHINE_TYPE.get(machine, f"0x{machine:x}").replace("IMAGE_FILE_MACHINE_", ""),
        format="PE32+" if plus else "PE32",
        subsystem=pefile.SUBSYSTEM_TYPE.get(subsystem, f"0x{subsystem:x}").replace("IMAGE_SUBSYSTEM_", ""),
        dll=bool(characteristics & 0x2000),
        large_address_aware=bool(characteristics & 0x0020),
        dynamic_base=bool(dll_characteristics & 0x0040),
        high_entropy_va=bool(dll_characteristics & 0x0020),
        nx_compat=bool(dll_characteristics & 0x0100),
        image_base=f"0x{optional.ImageBase:x}",
        size_of_image=optional.SizeOfImage,
        section_alignment=optional.SectionAlignment,
        file_alignment=optional.FileAlignment,
        entry_rva=entry,
        entry_section=clean_name(entry_section.Name) if entry_section else None,
        sections=sections,
        tls=tls,
        relocations=relocations,
        exception_functions=(exceptions.Size // 12) if exceptions is not None and exceptions.VirtualAddress else 0,
    )


def imports_of(pe):
    """(kind, dll, name or None, ordinal or None) for every ordinary and delay import, in table order."""
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                           pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    rows, delay_rva_based = [], []
    for kind, attribute in (("import", "DIRECTORY_ENTRY_IMPORT"), ("delay", "DIRECTORY_ENTRY_DELAY_IMPORT")):
        for entry in getattr(pe, attribute, []):
            dll = clean_name(entry.dll).lower()
            if kind == "delay":
                delay_rva_based.append(bool(entry.struct.grAttrs & 1))
            for symbol in entry.imports:
                name = clean_name(symbol.name) if symbol.name else None
                rows.append((kind, dll, name, None if name else symbol.ordinal))
    return rows, delay_rva_based


def preflight(facts, delay_rva_based):
    """The pe_map requirements a title can fail before any of its code runs."""
    executable = [s for s in facts["sections"] if "X" in s["flags"]]

    def in_executable(rva):
        return any(s["virtual_address"] <= rva < s["virtual_address"] + (s["virtual_size"] or s["raw_size"])
                   for s in executable)

    alignment = facts["section_alignment"]
    tls = facts["tls"]
    checks = [
        ("x64 PE32+ image", facts["machine"] == "AMD64" and facts["format"] == "PE32+"),
        ("section alignment is a power of two of at least 0x1000",
         alignment >= 0x1000 and not alignment & (alignment - 1)),
        ("entry point in an executable section", not facts["entry_rva"] or in_executable(facts["entry_rva"])),
        ("empty TLS data template", tls["template_bytes"] == 0 and tls["zero_fill"] == 0),
        ("TLS callbacks in executable sections", all(in_executable(rva) for rva in tls["callback_rvas"])),
        ("at most 256 TLS callbacks", tls["callbacks"] <= 256),
        ("relocations not stripped", not facts["relocations"]["stripped"]),
        ("delay imports use RVAs", all(delay_rva_based)),
        ("an EXE, not a DLL", not facts["dll"]),
    ]
    return [OrderedDict(check=name, ok=bool(ok)) for name, ok in checks]


def shader_folder_census(folder, llvm=None):
    """Totals and opcode histograms from tools/scan_unsupported_shaders.py, without any shader's name or text."""
    sys.path.insert(0, str(ROOT / "tools"))
    import scan_unsupported_shaders as scan

    with contextlib.redirect_stdout(sys.stderr):
        results = scan.scan_directory_or_files([folder], llvm)
    stages, categories, unsupported, isa = Counter(), Counter(), Counter(), Counter()
    unrecognized = 0
    for result in results:
        stages[result["stage"]] += 1
        categories["decode_failed" if result["lower_status"] == "decode_failed"
                   else result["compatibility_category"]] += 1
        for item in result["unsupported_details"]:
            opcode = item["opcode"]
            # Only names the ISA tables know are reported; anything else is counted without its text.
            if scan.is_opcode_recognized(opcode):
                unsupported[opcode.lower()] += 1
                isa[scan.classify_isa_category(opcode)] += 1
            else:
                unrecognized += 1
    return OrderedDict(
        source="tools/scan_unsupported_shaders.py", shaders=len(results), stages=dict(sorted(stages.items())),
        categories=dict(sorted(categories.items())),
        instructions=sum(r["total_instructions"] for r in results),
        supported_instructions=sum(r["supported_instructions"] for r in results),
        unsupported_forms=dict(unsupported.most_common()), unsupported_by_isa_category=dict(isa.most_common()),
        unrecognized_instructions=unrecognized)


def shader_archive_census(path):
    """Population counts from tools/shader_census.py for one archive, read in place."""
    sys.path.insert(0, str(ROOT / "tools"))
    from shader_census import census

    with path.open("rb") as stream:
        if stream.seek(0, 2) == 0:
            data = b""
            result = census(data)
        else:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                result = census(data)
    return OrderedDict(
        source="tools/shader_census.py", records=result["archive_records"]["count"],
        stages=dict(sorted(result["archive_records"]["stages"].items())),
        dxbc_header_digests=result["dxbc_header_digests"]["count"],
        distinct_containers=result["classification_cache"]["count"],
        candidate_rejections=dict(sorted(result["candidate_rejections"].items())))


def build_report(title, folder=None, shim_dirs=None, windows_dir=None, shaders=None, archives=(), llvm=None):
    folder = folder or title.parent
    pe = pefile.PE(str(title), fast_load=True)
    try:
        facts = pe_facts(pe)
        rows, delay_rva_based = imports_of(pe)
    finally:
        pe.close()
    routes = Routes(folder, shim_dirs, WindowsLookup(windows_dir))
    per_dll = OrderedDict()
    imports = []
    for kind, dll, name, ordinal in rows:
        cls, route = routes.classify(dll, name, ordinal)
        function = name if name is not None else f"#{ordinal}"
        imports.append(OrderedDict(dll=dll, function=function, kind=kind, **{"class": cls}, route=route))
        totals = per_dll.setdefault(dll, OrderedDict((c, 0) for c in CLASSES))
        totals[cls] += 1
    overall = OrderedDict((c, sum(t[c] for t in per_dll.values())) for c in CLASSES)
    report = OrderedDict(
        schema=SCHEMA,
        program=clean_name(title.name),
        pe=facts,
        pe_map_preflight=preflight(facts, delay_rva_based),
        routes=OrderedDict(shims=routes.shim_source, windows=routes.windows.source,
                           package_dlls=sorted(d for d, e in routes.packages.items() if e is not None)),
        import_totals=OrderedDict(dlls=len(per_dll), functions=len(imports), **overall),
        per_dll=per_dll,
        imports=imports,
        shader_census=OrderedDict(
            folder=shader_folder_census(shaders, llvm) if shaders else None,
            archives=[OrderedDict(archive=clean_name(p.name), **shader_archive_census(p)) for p in archives]),
    )
    return report


def render_markdown(report):
    facts = report["pe"]
    lines = [f"# x2w_report: `{report['program']}`", "",
             "Names, counts and classifications only. No title bytes, data or assets.", "",
             "## PE", "", "| Field | Value |", "|---|---|"]
    for key in ("machine", "format", "subsystem", "dll", "image_base", "size_of_image", "entry_rva",
                "entry_section", "section_alignment", "file_alignment", "dynamic_base", "high_entropy_va",
                "nx_compat", "large_address_aware", "exception_functions"):
        value = facts[key]
        lines.append(f"| {key} | `{hex(value) if key in ('entry_rva', 'size_of_image') else value}` |")
    tls, relocations = facts["tls"], facts["relocations"]
    lines.append(f"| tls | present `{tls['present']}`, callbacks `{tls['callbacks']}`"
                 f" at `{', '.join(hex(r) for r in tls['callback_rvas']) or '-'}`,"
                 f" template `{tls['template_bytes']}` B, zero fill `{tls['zero_fill']}` B |")
    lines.append(f"| relocations | present `{relocations['present']}`, blocks `{relocations['blocks']}`,"
                 f" entries `{relocations['entries']}`, stripped `{relocations['stripped']}` |")
    lines += ["", "| Section | RVA | Virtual size | Raw size | Flags |", "|---|---:|---:|---:|---|"]
    for section in facts["sections"]:
        lines.append(f"| `{section['name']}` | `{section['virtual_address']:#x}` | {section['virtual_size']} |"
                     f" {section['raw_size']} | `{section['flags']}` |")
    lines += ["", "## pe_map preflight", ""]
    lines += [f"- {'ok' if c['ok'] else 'FAIL'}: {c['check']}" for c in report["pe_map_preflight"]]
    routes = report["routes"]
    totals = report["import_totals"]
    lines += ["", "## Imports", "",
              f"Shims: {routes['shims']}. Windows lookup: {routes['windows']}.", "",
              f"{totals['functions']} functions from {totals['dlls']} DLLs: "
              + ", ".join(f"{c} {totals[c]}" for c in CLASSES) + ".", "",
              "| DLL | " + " | ".join(CLASSES) + " |", "|---|" + "---:|" * len(CLASSES)]
    for dll, counts in report["per_dll"].items():
        lines.append(f"| `{dll}` | " + " | ".join(str(counts[c]) for c in CLASSES) + " |")
    needed = [i for i in report["imports"] if i["class"] in ("stub", "missing", "unverified")]
    lines += ["", "### Not provided yet", ""]
    if needed:
        lines += ["| DLL | Function | Kind | Class | Route |", "|---|---|---|---|---|"]
        lines += [f"| `{i['dll']}` | `{i['function']}` | {i['kind']} | {i['class']} | {i['route']} |"
                  for i in needed]
    else:
        lines.append("Every import has a route.")
    census = report["shader_census"]
    if census["folder"] or census["archives"]:
        lines += ["", "## Shader census", ""]
        folder = census["folder"]
        if folder:
            lines += [f"Folder scan: {folder['shaders']} shaders, {folder['instructions']} instructions,"
                      f" {folder['supported_instructions']} supported,"
                      f" {folder['unrecognized_instructions']} unrecognized.", "",
                      "Stages: " + (", ".join(f"{k} {v}" for k, v in folder["stages"].items()) or "none") + ".",
                      "Categories: " + (", ".join(f"{k} {v}" for k, v in folder["categories"].items()) or "none")
                      + ".", "", "| Unsupported form | Instructions |", "|---|---:|"]
            lines += [f"| `{op}` | {n} |" for op, n in folder["unsupported_forms"].items()]
        for archive in census["archives"]:
            lines += ["", f"Archive `{archive['archive']}`: {archive['records']} records"
                      f" ({', '.join(f'{k} {v}' for k, v in archive['stages'].items()) or 'none'}),"
                      f" {archive['dxbc_header_digests']} header digests,"
                      f" {archive['distinct_containers']} distinct containers."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("title", type=Path, help="The title's executable")
    parser.add_argument("--folder", type=Path, help="Folder searched for the title's own DLLs (default: beside it)")
    parser.add_argument("--shims", type=Path, action="append", help="A directory of built shim DLLs, as for x2w_launch")
    parser.add_argument("--windows-dir", type=Path, help="Read Windows DLL exports from this directory instead")
    parser.add_argument("--shaders", type=Path, help="Already-extracted shader files to scan in place")
    parser.add_argument("--shader-archive", type=Path, action="append", default=[], help="A shader archive to count")
    parser.add_argument("--llvm", help="libLLVM with AMDGPU support, for binary shaders in --shaders")
    parser.add_argument("--out", type=Path, default=Path("out/x2w-report"))
    args = parser.parse_args(argv)
    try:
        report = build_report(args.title, args.folder, args.shims, args.windows_dir, args.shaders,
                              args.shader_archive, args.llvm)
    except (OSError, ValueError, pefile.PEFormatError) as error:
        parser.exit(1, f"x2w_report: {error}\n")
    args.out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = args.out / "report.json", args.out / "report.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    totals = report["import_totals"]
    print(f"x2w_report: {totals['functions']} imports from {totals['dlls']} DLLs: "
          + ", ".join(f"{c} {totals[c]}" for c in CLASSES))
    print(f"x2w_report: wrote {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
