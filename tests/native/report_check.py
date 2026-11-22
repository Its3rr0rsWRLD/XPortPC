"""Check tools/x2w_report.py: import classification, PE facts and that a report holds no title bytes.

Usage:
  report_check.py                          synthetic PE images built here; runs on any host
  report_check.py --title EXE --shims DIR  the source-built rung 1 title (tests/native/rung1_title.cpp)

The synthetic images are written by this file from scratch: headers, an import table, a TLS directory, a
relocation block and sections filled with seeded random bytes and sentinel strings. They are never run.
The names-only property is checked the same way for both: every string in report.json must be a DLL or
function name from the image's import tables, a section name, the program's file name, a hex number,
section access flags, an RDNA ISA mnemonic or a
string that the report tools themselves contain (or pefile's machine and subsystem names); and no 8-byte window of any section's raw data, nor its hex
spelling, may appear in report.json or report.md. A tampered copy of each report must fail the check.
"""
import argparse
import json
from pathlib import Path
import random
import re
import struct
import subprocess
import sys
import tempfile
import unittest

import pefile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import x2w_report  # noqa: E402

TOOL_SOURCES = [ROOT / "tools" / name for name in
                ("x2w_report.py", "scan_unsupported_shaders.py", "shader_census.py", "resource_inventory.py")]
HEX = re.compile(r"0x[0-9a-f]+")
FLAGS = re.compile(r"[R-][W-][X-]")  # section access flags
IMAGE_BASE = 0x140000000
SENTINELS = (b"X2W-SENTINEL-RDATA-0123", b"X2W-SENTINEL-DATA-4567")


# ---- synthetic images ------------------------------------------------------------------------------

def build_pe(imports=(), exports=(), *, dll=False, tls_template=0, seed=1):
    """A PE32+ image: .text (seeded bytes), .rdata (import/export/TLS tables), .data, .reloc."""
    rng = random.Random(seed)
    text = bytearray(rng.randbytes(0x200))
    data = bytearray(rng.randbytes(0x200))
    data[0x40:0x40 + len(SENTINELS[1])] = SENTINELS[1]
    data[0x100:0x104] = b"\0\0\0\0"  # TLS index slot
    rdata = bytearray()
    R = 0x2000

    def put(blob, align=8):
        while len(rdata) % align:
            rdata.append(0)
        rva = R + len(rdata)
        rdata.extend(blob)
        return rva

    dirs = {}
    put(SENTINELS[0] + b"\0")
    if imports:
        descriptors = put(bytes(20 * (len(imports) + 1)))
        dirs[1] = (descriptors, 20 * (len(imports) + 1))
        for i, (name, symbols) in enumerate(imports):
            name_rva = put(name.encode() + b"\0", 2)
            words = []
            for symbol in symbols:
                if isinstance(symbol, int):
                    words.append((1 << 63) | symbol)
                else:
                    words.append(put(struct.pack("<H", 0) + symbol.encode() + b"\0", 2))
            table = b"".join(struct.pack("<Q", w) for w in words) + bytes(8)
            ilt, iat = put(table), put(table)
            offset = descriptors - R + 20 * i
            rdata[offset:offset + 20] = struct.pack("<5I", ilt, 0, 0, name_rva, iat)
    if exports:
        names = sorted(exports)
        dll_name = put(b"provider.dll\0")
        functions = put(b"".join(struct.pack("<I", 0x1000 + 16 * i) for i in range(len(names))))
        name_rvas = [put(n.encode() + b"\0", 1) for n in names]
        name_table = put(b"".join(struct.pack("<I", r) for r in name_rvas), 4)
        ordinals = put(b"".join(struct.pack("<H", i) for i in range(len(names))), 2)
        directory = put(struct.pack("<2I2H7I", 0, 0, 0, 0, dll_name, 1, len(names), len(names), functions,
                                    name_table, ordinals), 4)
        dirs[0] = (directory, 40)
    callbacks = put(struct.pack("<2Q", IMAGE_BASE + 0x1010, 0))
    template = IMAGE_BASE + 0x3000
    tls = put(struct.pack("<4Q2I", template, template + tls_template, IMAGE_BASE + 0x3100,
                          IMAGE_BASE + callbacks, 0, 0))
    dirs[9] = (tls, 40)
    rdata.extend(bytes(-len(rdata) % 0x200))
    fixups = [tls + 8 * i for i in range(4)] + [callbacks]
    block = struct.pack("<2I", R, 8 + 2 * len(fixups)) + b"".join(
        struct.pack("<H", (10 << 12) | (f - R)) for f in fixups)
    reloc = bytearray(block + bytes(0x200 - len(block)))
    dirs[5] = (0x4000, len(block))
    sections = [(b".text", 0x1000, text, 0x60000020), (b".rdata", 0x2000, rdata, 0x40000040),
                (b".data", 0x3000, data, 0xC0000040), (b".reloc", 0x4000, reloc, 0x42000040)]
    directories = b"".join(struct.pack("<2I", *dirs.get(i, (0, 0))) for i in range(16))
    optional = struct.pack("<HBBIIIIIQIIHHHHHHIIIIHHQQQQII", 0x20B, 14, 0, 0x200, 0x600, 0, 0x1000, 0x1000,
                           IMAGE_BASE, 0x1000, 0x200, 6, 0, 0, 0, 6, 0, 0, 0x5000, 0x400, 0, 3, 0x8160,
                           0x100000, 0x1000, 0x100000, 0x1000, 0, 16) + directories
    characteristics = 0x22 | (0x2000 if dll else 0)
    header = bytearray(0x400)
    header[0:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x40)
    nt = b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, len(sections), 0, 0, 0, len(optional), characteristics)
    table = b""
    raw = 0x400
    for name, rva, body, flags in sections:
        table += struct.pack("<8s6I2HI", name, len(body), rva, len(body), raw, 0, 0, 0, 0, flags)
        raw += len(body)
    blob = nt + optional + table
    header[0x40:0x40 + len(blob)] = blob
    return bytes(header) + b"".join(bytes(body) for _, _, body, _ in sections)


# ---- the names-only property -------------------------------------------------------------------------

def allowed_names(title):
    pe = pefile.PE(str(title))
    try:
        names = {x2w_report.clean_name(title.name)}
        names.update(x2w_report.clean_name(s.Name) for s in pe.sections)
        for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
            for entry in getattr(pe, attribute, []):
                names.add(x2w_report.clean_name(entry.dll).lower())
                names.update(x2w_report.clean_name(i.name) if i.name else f"#{i.ordinal}" for i in entry.imports)
        sections = [s.get_data() for s in pe.sections]
    finally:
        pe.close()
    return names, sections


def strings_of(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings_of(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_of(item)
    elif isinstance(value, str):
        yield value


def assert_names_only(json_path, md_path, title, extra=()):
    """Raise AssertionError if a report could hold anything from the title other than names and counts."""
    names, sections = allowed_names(title)
    names.update(extra)
    tools = "\n".join(path.read_text(encoding="utf-8") for path in TOOL_SOURCES)
    # Machine and subsystem names come from pefile's own tables.
    names.update(key.replace(prefix, "") for table, prefix in ((pefile.MACHINE_TYPE, "IMAGE_FILE_MACHINE_"),
                                                              (pefile.SUBSYSTEM_TYPE, "IMAGE_SUBSYSTEM_"))
                 for key in table if isinstance(key, str))
    report = json.loads(json_path.read_text(encoding="utf-8"))
    from scan_unsupported_shaders import is_opcode_recognized  # ISA mnemonics in the shader histogram

    for text in strings_of(report):
        if not (text in names or text in tools or HEX.fullmatch(text) or FLAGS.fullmatch(text)
                or (re.fullmatch(r"[a-z][a-z0-9_]*", text) and is_opcode_recognized(text))):
            raise AssertionError(f"report.json holds a string that is not a name: {text!r}")
    blobs = [json_path.read_bytes(), md_path.read_bytes()]
    hexes = [blob.decode("utf-8", "replace").lower() for blob in blobs]
    joined = "\n".join(sorted(names))
    for index, raw in enumerate(sections):
        for offset in range(0, max(0, len(raw) - 7)):
            window = raw[offset:offset + 8]
            if len(set(window)) < 4:
                continue  # padding and small integers
            printable = all(0x20 <= b < 0x7F for b in window)
            if printable and window.decode("ascii") in joined:
                continue  # part of an import, section or program name
            for blob in blobs:
                if window in blob:
                    raise AssertionError(f"report holds raw bytes of section {index} at offset {offset:#x}")
            spelled = window.hex()
            for text in hexes:
                if spelled in text:
                    raise AssertionError(f"report holds hex of section {index} at offset {offset:#x}")


def assert_tamper_detected(json_path, md_path, title, extra=()):
    """Controls: a copied section string and a hex dump of section bytes (in either file) must each fail."""
    _, sections = allowed_names(title)
    raw = max(sections, key=lambda s: len(set(s)))
    start = next(i for i in range(len(raw) - 16) if len(set(raw[i:i + 16])) >= 8)
    with tempfile.TemporaryDirectory() as scratch:
        for kind in ("string", "hex", "markdown"):
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")
            if kind == "string":
                report["program_note"] = raw[start:start + 16].decode("latin-1")
            elif kind == "hex":
                report["dump"] = raw[start:start + 16].hex()
            else:
                markdown += " ".join(f"{b:02X}" for b in raw[start:start + 16]).replace(" ", "") + "\n"
            copy, md_copy = Path(scratch) / "report.json", Path(scratch) / "report.md"
            copy.write_text(json.dumps(report), encoding="utf-8")
            md_copy.write_text(markdown, encoding="utf-8")
            try:
                assert_names_only(copy, md_copy, title, extra)
            except AssertionError:
                continue
            raise AssertionError(f"tampered report ({kind}) passed the names-only check")


# ---- synthetic checks ----------------------------------------------------------------------------------

TITLE_IMPORTS = [
    ("xmem.dll", ["XMemAlloc", "XMemFree", "X2wNotInShim"]),
    ("KERNEL32.dll", ["GetCurrentThreadId", "X2wNotInKernel32"]),
    ("x2w_missing.dll", ["X2wMissingFirst", 7]),
    ("title_pkg.dll", ["PkgExport", "PkgAbsent", 3]),
]


class SyntheticReport(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        self.game = root / "game"
        self.windows = root / "windows"
        self.game.mkdir()
        self.windows.mkdir()
        self.title = self.game / "synthetic_title.exe"
        self.title.write_bytes(build_pe(TITLE_IMPORTS))
        (self.game / "title_pkg.dll").write_bytes(build_pe(exports=["PkgExport"], dll=True, seed=2))
        (self.windows / "kernel32.dll").write_bytes(build_pe(exports=["GetCurrentThreadId"], dll=True, seed=3))
        self.out = root / "out"

    def tearDown(self):
        self.scratch.cleanup()

    def run_tool(self, *extra):
        argv = [str(self.title), "--windows-dir", str(self.windows), "--out", str(self.out), *extra]
        self.assertEqual(x2w_report.main(argv), 0)
        return json.loads((self.out / "report.json").read_text(encoding="utf-8"))

    def test_classification_follows_the_launcher_routes(self):
        report = self.run_tool()
        got = {(i["dll"], i["function"]): i["class"] for i in report["imports"]}
        self.assertEqual(got, {
            ("xmem.dll", "XMemAlloc"): "implemented", ("xmem.dll", "XMemFree"): "implemented",
            ("xmem.dll", "X2wNotInShim"): "stub",
            ("kernel32.dll", "GetCurrentThreadId"): "windows", ("kernel32.dll", "X2wNotInKernel32"): "stub",
            ("x2w_missing.dll", "X2wMissingFirst"): "missing", ("x2w_missing.dll", "#7"): "missing",
            ("title_pkg.dll", "PkgExport"): "package", ("title_pkg.dll", "PkgAbsent"): "stub",
            ("title_pkg.dll", "#3"): "stub",
        })
        self.assertEqual(report["per_dll"]["xmem.dll"]["implemented"], 2)
        self.assertEqual(report["per_dll"]["title_pkg.dll"]["stub"], 2)
        totals = report["import_totals"]
        self.assertEqual((totals["dlls"], totals["functions"]), (4, 10))
        self.assertEqual([totals[c] for c in x2w_report.CLASSES], [2, 1, 1, 4, 2, 0])
        self.assertEqual(report["routes"]["package_dlls"], ["title_pkg.dll"])

    def test_without_a_windows_lookup_windows_imports_are_unverified(self):
        routes = x2w_report.Routes(self.game, None, x2w_report.WindowsLookup(None))
        if routes.windows.available:
            self.skipTest("this host has the Windows lookup")
        self.assertEqual(routes.classify("kernel32.dll", "GetCurrentThreadId", None)[0], "unverified")
        self.assertEqual(routes.classify("xmem.dll", "XMemAlloc", None)[0], "implemented")

    def test_built_shim_directories_replace_the_def_files(self):
        shims = Path(self.scratch.name) / "shims"
        shims.mkdir()
        (shims / "xmem.dll").write_bytes(build_pe(exports=["X2wNotInShim"], dll=True, seed=4))
        report = self.run_tool("--shims", str(shims))
        got = {(i["dll"], i["function"]): i["class"] for i in report["imports"]}
        self.assertEqual(got[("xmem.dll", "X2wNotInShim")], "implemented")
        self.assertEqual(got[("xmem.dll", "XMemAlloc")], "stub")
        # Without the DLL in any shim directory, xmem.dll falls through to the later routes.
        self.assertEqual(got[("title_pkg.dll", "PkgExport")], "package")

    def test_pe_facts_and_preflight(self):
        report = self.run_tool()
        facts = report["pe"]
        self.assertEqual((facts["machine"], facts["format"], facts["subsystem"]), ("AMD64", "PE32+", "WINDOWS_CUI"))
        self.assertEqual([s["name"] for s in facts["sections"]], [".text", ".rdata", ".data", ".reloc"])
        self.assertEqual([s["flags"] for s in facts["sections"]], ["R-X", "R--", "RW-", "R--"])
        self.assertEqual((facts["entry_rva"], facts["entry_section"]), (0x1000, ".text"))
        self.assertEqual(facts["tls"]["callback_rvas"], [0x1010])
        self.assertEqual((facts["relocations"]["present"], facts["relocations"]["blocks"],
                          facts["relocations"]["entries"]), (True, 1, 5))
        self.assertTrue(all(check["ok"] for check in report["pe_map_preflight"]), report["pe_map_preflight"])
        self.title.write_bytes(build_pe(TITLE_IMPORTS, tls_template=16))
        failed = [c["check"] for c in self.run_tool()["pe_map_preflight"] if not c["ok"]]
        self.assertEqual(failed, ["empty TLS data template"])

    def test_report_holds_names_and_counts_only(self):
        self.run_tool()
        md = (self.out / "report.md").read_text(encoding="utf-8")
        self.assertIn("| `x2w_missing.dll` | `#7` | import | missing | none |", md)
        self.assertIn("| `xmem.dll` | 2 | 0 | 0 | 1 | 0 | 0 |", md)
        for path in (self.out / "report.json", self.out / "report.md"):
            for sentinel in SENTINELS:
                self.assertNotIn(sentinel, path.read_bytes())
        assert_names_only(self.out / "report.json", self.out / "report.md", self.title)
        assert_tamper_detected(self.out / "report.json", self.out / "report.md", self.title)

    def test_shader_census_reports_counts_and_isa_names_only(self):
        shaders = Path(self.scratch.name) / "shaders"
        shaders.mkdir()
        (shaders / "ps_secret_title_name.s").write_text(
            "v_mov_b32 v0, v1\nv_frobnicate_titlesecret v1, v2\nimage_bvh_intersect_ray v[0:3], v[4:14], s[0:3]\n"
            "s_endpgm\n", encoding="utf-8")
        sys.path.insert(0, str(ROOT / "tests"))
        from shader_census_check import archive_fixture
        archive = Path(self.scratch.name) / "shaders_archive.bin"
        archive.write_bytes(archive_fixture())
        report = self.run_tool("--shaders", str(shaders), "--shader-archive", str(archive))
        folder = report["shader_census"]["folder"]
        self.assertEqual((folder["shaders"], folder["stages"]), (1, {"pixel": 1}))
        self.assertGreaterEqual(folder["unrecognized_instructions"], 1)
        self.assertTrue(all(re.fullmatch(r"[a-z][a-z0-9_]*", op) for op in folder["unsupported_forms"]))
        archives = report["shader_census"]["archives"]
        self.assertEqual((archives[0]["records"], archives[0]["stages"]), (4, {"compute": 1, "pixel": 3}))
        for path in (self.out / "report.json", self.out / "report.md"):
            text = path.read_text(encoding="utf-8")
            for leaked in ("titlesecret", "secret_title_name", "owned_shader", "v[4:14]"):
                self.assertNotIn(leaked, text)
        assert_names_only(self.out / "report.json", self.out / "report.md", self.title, extra={archive.name})


# ---- the source-built rung 1 title ------------------------------------------------------------------

def check_rung1(title, shims):
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "out"
        command = [sys.executable, "-B", str(ROOT / "tools" / "x2w_report.py"), str(title), "--shims", str(shims),
                   "--out", str(out)]
        if not x2w_report.WindowsLookup().available:
            # Off Windows (the Linux cross-build harness), a synthetic kernel32.dll stands in for System32.
            windows = Path(scratch) / "windows"
            windows.mkdir()
            names, _ = allowed_names(title)
            (windows / "kernel32.dll").write_bytes(build_pe(exports=[
                n for n in ("CreateThread", "WaitForSingleObject", "CloseHandle", "GetCurrentProcess",
                            "GetEnvironmentVariableA") if n in names], dll=True, seed=5))
            command += ["--windows-dir", str(windows)]
        run = subprocess.run(command, capture_output=True, text=True, timeout=120)
        print(run.stdout + run.stderr, end="")
        assert run.returncode == 0, run.returncode
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        print((out / "report.md").read_text(encoding="utf-8"))
        got = {(i["dll"], i["function"]): i["class"] for i in report["imports"]}
        windows = "windows"
        expected = {
            ("xmem.dll", "XMemAlloc"): "implemented", ("xmem.dll", "XMemFree"): "implemented",
            ("xmem.dll", "XMemVirtualQuery"): "implemented", ("xmem.dll", "X2wNotInShim"): "stub",
            ("d3d12_xs.dll", "D3D12SerializeVersionedRootSignature"): "implemented",
            ("x2w_missing.dll", "X2wMissingFirst"): "missing", ("x2w_missing.dll", "X2wMissingSecond"): "missing",
            ("x2w_missing.dll", "#7"): "missing",
        }
        for name in ("CreateThread", "WaitForSingleObject", "CloseHandle", "GetCurrentProcess",
                     "GetEnvironmentVariableA"):
            expected[("kernel32.dll", name)] = windows
        for key, cls in expected.items():
            assert got.get(key) == cls, f"{key}: {got.get(key)} != {cls}"
        extra = {k: v for k, v in got.items() if k not in expected}
        assert all(k[0] == "kernel32.dll" and v == windows for k, v in extra.items()), extra
        totals = report["import_totals"]
        assert (totals["implemented"], totals["stub"], totals["missing"]) == (4, 1, 3), totals
        facts = report["pe"]
        assert (facts["machine"], facts["format"], facts["subsystem"]) == ("AMD64", "PE32+", "WINDOWS_CUI"), facts
        assert facts["tls"]["callbacks"] == 1 and facts["tls"]["template_bytes"] == 0, facts["tls"]
        assert facts["relocations"]["present"] and facts["entry_section"] == ".text", facts
        assert all(c["ok"] for c in report["pe_map_preflight"]), report["pe_map_preflight"]
        assert_names_only(out / "report.json", out / "report.md", title)
        assert_tamper_detected(out / "report.json", out / "report.md", title)
    print("native_report_rung1: classifications, PE facts and the names-only property behaved")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", type=Path)
    parser.add_argument("--shims", type=Path)
    args, rest = parser.parse_known_args()
    if args.title:
        return check_rung1(args.title, args.shims)
    program = unittest.main(argv=[sys.argv[0], *rest], exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
