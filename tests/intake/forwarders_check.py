"""Package export forwarders with locally compiled PE fixtures. Never load a fixture."""

from pathlib import Path
import shutil
import struct
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pefile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from dependency_paths import trace
from pe_inventory import parse_image, scan

FORWARD = "intake_forward.dll"
PROVIDER = "intake_provider.dll"
# Linkers differ in how a .def file declares forwarders, so the test writes them into a copy of the DLL.
TARGETS = {
    "forwarded_value": "intake_provider.named_value",
    "forwarded_ordinal": "intake_provider.#77",
    "forwarded_chain": "intake_forward.forwarded_value",
    "forwarded_missing": "intake_provider.absent_value",
    "forwarded_loop": "intake_forward.forwarded_loop",
    "forwarded_absent": "intake_absent.absent_value",
}


def forward_exports(source, targets):
    """Return the DLL with an export table in a new section whose named exports forward to targets."""
    def align(value, alignment):
        return -(-value // alignment) * alignment

    with pefile.PE(str(source)) as pe:
        directory = pe.DIRECTORY_ENTRY_EXPORT.struct
        ordinals = {s.name.decode(): s.ordinal for s in pe.DIRECTORY_ENTRY_EXPORT.symbols if s.name}
        assert ordinals.keys() == targets.keys(), sorted(ordinals)
        names = sorted(targets)
        strings = bytearray(pe.get_string_at_rva(directory.Name) + b"\0")
        offsets = {}
        for text in (*names, *(targets[n] for n in names)):
            offsets.setdefault(text, len(strings))
            strings += text.encode() + b"\0"

        header = pe.sections[-1].get_file_offset() + pe.sections[-1].sizeof()
        last = max(pe.sections, key=lambda s: s.VirtualAddress)
        optional = pe.OPTIONAL_HEADER
        rva = align(last.VirtualAddress + max(last.Misc_VirtualSize, last.SizeOfRawData), optional.SectionAlignment)
        count = directory.NumberOfFunctions
        functions, pointers = rva + 40, rva + 40 + 4 * count
        numbers = pointers + 4 * len(names)
        text = numbers + 2 * len(names)
        table = [0] * count
        for name in names:
            table[ordinals[name] - directory.Base] = text + offsets[targets[name]]
        blob = struct.pack("<2I2H7I", 0, directory.TimeDateStamp, 0, 0, text, directory.Base, count, len(names),
                           functions, pointers, numbers)
        blob += struct.pack(f"<{count}I", *table) + struct.pack(f"<{len(names)}I", *(text + offsets[n] for n in names))
        blob += struct.pack(f"<{len(names)}H", *(ordinals[n] - directory.Base for n in names)) + strings

        optional.DATA_DIRECTORY[0].VirtualAddress, optional.DATA_DIRECTORY[0].Size = rva, len(blob)
        optional.SizeOfImage = align(rva + len(blob), optional.SectionAlignment)
        optional.CheckSum = 0
        pe.FILE_HEADER.NumberOfSections += 1
        image = bytearray(pe.write())
        end = max(s.PointerToRawData + s.SizeOfRawData for s in pe.sections)
        assert len(image) == end, "unexpected data after the last section"
        assert header + 40 <= optional.SizeOfHeaders and not any(image[header:header + 40]), "no room for a header"
        raw = align(end, optional.FileAlignment)
        size = align(len(blob), optional.FileAlignment)
        image[header:header + 40] = struct.pack("<8s6I2HI", b".fwdexp", len(blob), rva, size, raw, 0, 0, 0, 0,
                                                0x40000040)  # initialized, readable data
    return bytes(image.ljust(raw, b"\0") + blob.ljust(size, b"\0"))


def check(root, caller, forward, provider):
    for image in (caller, provider):
        shutil.copyfile(image, root / image.name)
    (root / forward.name).write_bytes(forward_exports(forward, TARGETS))
    entry = caller.name
    report = scan(root)
    # The rewrite adds no pefile warnings and turns each placeholder into its forwarder.
    assert report["images"][FORWARD]["parse_warnings"] == parse_image(forward)[0]["parse_warnings"]
    assert {e["name"]: e["forwarder"] for e in report["images"][FORWARD]["exports"]} == TARGETS
    # MSVC callers also import the CRT and KERNEL32; only the forwarder DLL's rows are under test.
    rows = {r["symbol"]: r for r in report["imports"]
            if r["image"] == entry and r["dll"].lower() == FORWARD.lower()}
    assert set(rows) == set(TARGETS)
    assert all(r["bundle_exports_in"] == [FORWARD] for r in rows.values())

    def hops(symbol):
        chain = rows[symbol]["package_resolution"]["chain"]
        return rows[symbol]["package_resolution"]["status"], [(s["provider"], s["symbol"]) for s in chain]

    assert hops("forwarded_value") == ("export_present", [(FORWARD, "forwarded_value"), (PROVIDER, "named_value")])
    assert hops("forwarded_ordinal") == ("export_present", [(FORWARD, "forwarded_ordinal"), (PROVIDER, "#77")])
    assert hops("forwarded_chain") == ("export_present", [
        (FORWARD, "forwarded_chain"), (FORWARD, "forwarded_value"), (PROVIDER, "named_value")])
    assert hops("forwarded_missing") == ("export_not_found", [
        (FORWARD, "forwarded_missing"), (PROVIDER, "absent_value")])
    assert hops("forwarded_loop") == ("forwarder_cycle", [(FORWARD, "forwarded_loop")] * 2)
    assert hops("forwarded_absent") == ("provider_not_found", [
        (FORWARD, "forwarded_absent"), ("intake_absent.dll", "absent_value")])
    assert rows["forwarded_absent"]["package_resolution"]["chain"][-1]["dll"] == "intake_absent.dll"
    assert all(s["package"] for s in rows["forwarded_chain"]["package_resolution"]["chain"])
    assert not rows["forwarded_absent"]["package_resolution"]["chain"][-1]["package"]
    unresolved = {r["symbol"] for r in report["unresolved_edges"] if r["image"] == entry}
    assert unresolved == {"forwarded_missing", "forwarded_loop", "forwarded_absent"}

    paths = trace(report, entry)
    # The forwarder target is loaded with the provider, so it is reachable without a direct import.
    assert paths["reachable"][PROVIDER]["path"] == (entry, FORWARD, PROVIDER)
    assert paths["reachable"][PROVIDER]["reasons"] == ("normal", "forwarder")
    assert not paths["reachable"][PROVIDER]["conditional"]
    problems = {f["symbol"]: f for f in paths["findings"]}
    assert {s: f["problem"] for s, f in problems.items()} == {
        "forwarded_missing": "export_not_found", "forwarded_loop": "forwarder_cycle",
        "forwarded_absent": "provider_not_found"}
    assert problems["forwarded_missing"]["package_chain"][-1]["symbol"] == "absent_value"

    check_descriptor_names(root, caller, report, entry)

    # The loader maps a KnownDLL from System32 before it searches the application directory, so a
    # package file named kernel32.dll is never loaded. Its exports must not decide KERNEL32 imports.
    shadow = root / "kernel32.dll"
    shutil.copyfile(provider, shadow)
    shadowed = scan(root)
    shadow.unlink()
    assert "kernel32.dll" in shadowed["known_dlls"] and "kernel32.dll" in shadowed["images"]
    system = [r for r in shadowed["imports"] if r["image"] == entry and r["dll"] == "kernel32.dll"]
    assert system and all(r["bundle_exports_in"] == [] for r in system)
    for r in system:
        assert r["package_resolution"]["status"] == r["desktop_resolution"]["status"] == "export_present"
        first = r["package_resolution"]["chain"][0]
        assert (first["provider"], first["package"], first["known_dll"]) == ("kernel32.dll", False, True)
        assert [(s["provider"], s["symbol"], s["package"]) for s in r["package_resolution"]["chain"]] == [
            (s["provider"], s["symbol"], False) for s in r["desktop_resolution"]["chain"]]
    shadowed_paths = trace(shadowed, entry)
    assert "kernel32.dll" in shadowed_paths["unlinked_in_this_graph"]
    assert not any(f["dll"] == "kernel32.dll" for f in shadowed_paths["findings"])

    # Put the source-built KnownDLL only in a separate synthetic system directory.
    with TemporaryDirectory() as directory:
        system_dir = Path(directory)
        system_copy = system_dir / FORWARD
        (root / FORWARD).rename(system_copy)
        try:
            with patch("pe_inventory.known_dlls", return_value={FORWARD}), patch("pe_inventory.api_sets", return_value={}):
                first_system = scan(root, system=system_dir)
                with TemporaryDirectory(dir=root) as other:
                    shutil.copyfile(provider, Path(other) / PROVIDER)
                    duplicate = trace(scan(root, system=system_dir), entry)
        finally:
            system_copy.rename(root / FORWARD)
    edges = {r["symbol"]: r for r in first_system["imports"] if r["image"] == entry and r["dll"] == FORWARD}
    resolved = edges["forwarded_value"]
    assert not resolved["bundle_exports_in"]
    assert resolved["package_resolution"]["status"] == "export_present"
    assert [s["package"] for s in resolved["package_resolution"]["chain"]] == [False, True]
    missing = {r["symbol"] for r in first_system["unresolved_edges"] if r["image"] == entry and r["dll"] == FORWARD}
    assert "forwarded_value" not in missing and "forwarded_missing" in missing
    assert PROVIDER in trace(first_system, entry)["reachable"]
    assert any(f["symbol"] == "forwarded_value" and f["problem"] == "ambiguous_package_basename"
               for f in duplicate["findings"])

    # Older inventories lack package chains and keep the first-hop bundled result.
    for row in report["imports"]:
        del row["package_resolution"]
    legacy = trace(report, entry)
    assert not legacy["findings"] and PROVIDER in legacy["unlinked_in_this_graph"]


def check_descriptor_names(root, caller, report, entry):
    """An import descriptor may omit the extension. The loader then appends .dll, unless the name
    ends with a dot, which stops the append and is dropped from the file name."""
    def results(rows):
        return {(r["dll"], r["symbol"]): (r["bundle_exports_in"], r["desktop_export"],
                                         r["package_resolution"]) for r in rows}

    expected = results(r for r in report["imports"] if r["image"] == entry)
    with pefile.PE(str(caller), fast_load=True) as pe:
        pe.parse_data_directories(directories=[1])
        descriptor, = [d for d in pe.DIRECTORY_ENTRY_IMPORT if d.dll.lower() == FORWARD.encode()]
        offset = pe.get_offset_from_rva(descriptor.struct.Name)
        image = bytearray(pe.__data__)
    stored = len(FORWARD)
    for name, provider in ((b"INTAKE_FORWARD", FORWARD), (b"intake_forward.", "intake_forward")):
        # Same-length rewrite of the descriptor's name; the rest of the image is unchanged.
        image[offset:offset + stored] = name.ljust(stored, b"\0")
        (root / entry).write_bytes(image)
        rows = [r for r in scan(root)["imports"] if r["image"] == entry]
        named = {r["dll"] for r in rows} - {r["dll"] for r in report["imports"] if r["image"] == entry}
        if provider == FORWARD:
            assert not named and results(rows) == expected, named
        else:
            assert named == {provider}, named
            assert {r["desktop_export"] for r in rows if r["dll"] == provider} == {"provider_not_found"}
            assert all(not r["bundle_exports_in"] and r["package_resolution"] is None
                       for r in rows if r["dll"] == provider)
    (root / entry).write_bytes(caller.read_bytes())


if __name__ == "__main__":
    with TemporaryDirectory() as temporary:
        check(Path(temporary), *map(Path, sys.argv[1:4]))
