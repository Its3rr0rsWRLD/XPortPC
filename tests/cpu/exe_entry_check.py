"""Compare complete Windows processes, including a translated inverted branch."""
from functools import partial
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
from typing import NamedTuple

import pefile
from exe_process import launch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_exe_aot import translate as translate_exe

translate = partial(translate_exe, entry_export="native_entry")


class Observation(NamedTuple):
    arguments: bytes
    output: bytes
    exit_code: int


def observation(row):
    if not row["process_signaled"] or not all(row[name]["eof"] for name in ("stdout", "stderr")):
        raise AssertionError(f"expected process signal and both EOFs: {row}")
    return Observation(row["stderr"]["bytes"], row["stdout"]["bytes"], row["code"])


def run(executable, selector):
    return observation(launch([executable], selector))


def check(label, actual, expected):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def compare(native, lifted, inverted_native, inverted_lifted, *, targets=False):
    references = [
        Observation(struct.pack("<QQ", 0x100000303, 0xfffffffd), bytes.fromhex("1103000000000000"), 0x60d),
        Observation(struct.pack("<QQ", 48, 6), bytes.fromhex("3500000000000000"), 0x57),
    ]
    control = list(reversed(references))
    if targets:
        control = [
            Observation(struct.pack("<QQ", 0x100000305, 0xfffffffd), struct.pack("<Q", 0x313), 0x60f),
            references[1],
        ]
        references[1] = Observation(struct.pack("<QQ", 50, 6), struct.pack("<Q", 55), 0x69)
    for selector, expected in enumerate(references):
        data = bytes([selector])
        original = run(native, data)
        check(f"native selector {selector}", original, expected)
        check(f"AOT selector {selector}", run(lifted, data), original)
        inverted = run(inverted_native, data)
        check("inverted native", inverted, control[selector])
        check("inverted AOT", run(inverted_lifted, data), inverted)
        for field in Observation._fields:
            if getattr(original, field) == getattr(inverted, field):
                raise AssertionError(f"selector {selector}: {field} missed the inverted branch")
        first, second = struct.unpack("<QQ", original.arguments)
        print(f"selector={selector} import=({first:#x}, {second:#x}) "
              f"output={original.output.hex()} exit={original.exit_code:#x} (inversion detected)")
    for program in (native, lifted, inverted_native, inverted_lifted):
        check("empty stdin", run(program, b""), Observation(b"", b"", 2))


def compare_nested(native, lifted, bypass, bypass_lifted):
    references = [
        Observation(struct.pack("<QQ", 0x100000303, 0xfffffffc), struct.pack("<Q", 0x312), 0xfffff9f1),
        Observation(struct.pack("<QQ", 48, 5), struct.pack("<Q", 54), 0x57),
    ]
    bypass_references = [
        Observation(struct.pack("<QQ", 0x1000002fc, 0xffffffff), struct.pack("<Q", 0x308), 0x308),
        Observation(struct.pack("<QQ", 41, 8), struct.pack("<Q", 44), 44),
    ]
    for selector, expected in enumerate(references):
        data = bytes([selector])
        check(f"nested native selector {selector}", run(native, data), expected)
        check(f"nested AOT selector {selector}", run(lifted, data), expected)
        direct = run(bypass, data)
        check(f"bypass native selector {selector}", direct, bypass_references[selector])
        check(f"bypass AOT selector {selector}", run(bypass_lifted, data), direct)
        for field in Observation._fields:
            if getattr(direct, field) == getattr(expected, field):
                raise AssertionError(f"selector {selector}: {field} missed the bypass")
        print(f"selector={selector} nested output={expected.output.hex()} exit={expected.exit_code:#x} "
              "(bypass detected)")
    for program in (native, lifted):
        check("empty stdin", run(program, b""), Observation(b"", b"", 2))


def check_header_guards(native, io_provider, mix_provider):
    native_path, io_path, mix_path = map(Path, (native, io_provider, mix_provider))
    expected = translate(native_path, io_path, mix_path)
    with TemporaryDirectory() as folder:
        short_dirs = Path(folder) / "short-dirs.exe"
        with pefile.PE(str(native_path), fast_load=True) as pe:
            pe.OPTIONAL_HEADER.NumberOfRvaAndSizes = 4
            pe.write(str(short_dirs))
        if translate(short_dirs, io_path, mix_path) != expected:
            raise AssertionError("4-directory PE32+ executable changed the translation")

        rejections = [
            ("tls.exe", lambda pe: setattr(pe.OPTIONAL_HEADER.DATA_DIRECTORY[9], "VirtualAddress", 0x1000),
             "TLS startup"),
            ("dll.exe", lambda pe: setattr(pe.FILE_HEADER, "Characteristics",
                                           pe.FILE_HEADER.Characteristics | 0x2000),
             "AMD64 PE32+ executable"),
            ("nonexec.exe", lambda pe: setattr(pe.FILE_HEADER, "Characteristics",
                                               pe.FILE_HEADER.Characteristics & ~0x2),
             "AMD64 PE32+ executable"),
        ]
        for name, mutate, reason in rejections:
            copy = Path(folder) / name
            with pefile.PE(str(native_path), fast_load=True) as pe:
                mutate(pe)
                pe.write(str(copy))
            try:
                translate(copy, io_path, mix_path)
            except ValueError as exc:
                if reason not in str(exc):
                    raise AssertionError(f"{name}: expected {reason!r}, got {exc}") from exc
            else:
                raise AssertionError(f"{name}: accepted, expected {reason!r}")
    print("4-directory EXE translation and 3 PE header rejection controls passed")


if __name__ == "__main__":
    if sys.argv[1] == "--targets":
        compare(*sys.argv[2:], targets=True)
    elif sys.argv[1] == "--nested":
        compare_nested(*sys.argv[2:])
    else:
        compare(*sys.argv[1:5])
        if len(sys.argv) > 5:
            check_header_guards(sys.argv[1], sys.argv[5], sys.argv[6])
