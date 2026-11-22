"""Compare the same two-input EXE under the Windows loader, pe_map, and AOT."""
import ctypes
from pathlib import Path
import struct
import subprocess
import sys

from exe_entry_check import Observation, check, run
from cpu_exe_aot import translate
from native_map_check import Mapper, STATUS


def mapped_child(mapper_path, image, *libraries):
    providers = {p.name.lower(): ctypes.CDLL(str(p)) for p in libraries}
    return run_mapped(mapper_path, image, providers)


def run_mapped(mapper_path, image, providers):
    mapper = Mapper(mapper_path)
    base, status, detail, _ = mapper(image, providers)
    if not base or status != STATUS["ok"]:
        raise AssertionError(f"mapping {image.name}: {status}, {detail}")
    try:
        start = ctypes.CDLL(str(mapper_path)).pe_map_run
        start.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        start.restype = ctypes.c_int
        code = ctypes.c_uint32()
        check("started", start(base, ctypes.byref(code)), 1)
        return code.value
    finally:
        mapper.release(base)


def run_mapped_child(mapper_path, native, data, *libraries):
    child = subprocess.run([sys.executable, "-B", __file__, "--child", mapper_path,
                            native, *libraries], input=data, capture_output=True, timeout=15)
    return Observation(child.stderr, child.stdout, child.returncode)


def compare(mapper_path, native, lifted, io, mix, bypass=None):
    mapper = Mapper(mapper_path)
    for bindings in ({}, {io.name.lower(): ctypes.CDLL(str(io))}):
        base, status, detail, requests = mapper(native, bindings)
        if base:
            mapper.release(base)
            raise AssertionError("mapped with a missing provider")
        check("missing provider status", status, STATUS["unresolved"])
        dll, symbol = requests[-1]
        if dll.lower() in bindings:
            raise AssertionError(f"expected a missing provider, got {dll}!{symbol}")
        check("diagnostic", detail, f"unresolved import {dll}!{symbol}")
        if bindings:
            check("missing mix", (dll.lower(), symbol), (mix.name.lower(), "mix_args"))
        print(f"before entry: {detail}")

    for selector in (0, 1):
        data = bytes([selector])
        original = run(native, data)
        check("native trace length", len(original.arguments), 16)
        check("native output length", len(original.output), 8)
        if bypass:
            # The nested leaf reverses the zero/nonzero branch for selectors 0 and 1.
            check("frame-selected branch", original, run(bypass, bytes([1 - selector])))
            skipped = run(bypass, data)
            for field in Observation._fields:
                if getattr(skipped, field) == getattr(original, field):
                    raise AssertionError(f"selector {selector}: {field} missed the bypassed frame")
        check("translated EXE", run(lifted, data), original)
        check("mapped EXE", run_mapped_child(mapper_path, native, data, io, mix), original)
        print(f"selector={selector} arguments={original.arguments.hex()} "
              f"output={original.output.hex()} exit={original.exit_code:#x}")


def compare_two_providers(mapper_path, native, lifted, io, mix, second):
    mapper = Mapper(mapper_path)
    bindings = {p.name.lower(): ctypes.CDLL(str(p)) for p in (io, mix)}
    base, status, detail, requests = mapper(native, bindings)
    if base:
        mapper.release(base)
        raise AssertionError("mapped without the second provider")
    check("missing second provider status", status, STATUS["unresolved"])
    dll, symbol = requests[-1]
    check("missing second import", (dll.lower(), symbol), (second.name.lower(), "accumulate_args"))
    diagnostic = f"unresolved import {dll}!{symbol}"
    check("missing second provider diagnostic", detail, diagnostic)
    for extra in ((), ((mix, "accumulate_args"),)):
        try:
            translate(native, io, mix, extra, entry_export="native_entry")
        except ValueError as exc:
            if f"unbound import {dll}!{symbol}" not in str(exc):
                raise
        else:
            raise AssertionError("translated without the correct second provider")
    print(f"before entry: {diagnostic}")

    invalid_symbols = ("trace-value", "3trace", "_Reserved", "trace__value", "class", "and",
                       "lifted", "lifted_callee2", "word", "store", "uint64_t", "mix_args")
    for invalid in invalid_symbols:
        try:
            translate(native, io, mix, ((second, invalid),), entry_export="native_entry")
        except ValueError as exc:
            if "import symbol" not in str(exc) or repr(invalid) not in str(exc):
                raise
        else:
            raise AssertionError(f"accepted invalid import spelling {invalid!r}")
    print(f"rejected {len(invalid_symbols)} invalid, reserved, and duplicate import symbols before emission")

    for selector, (x, y) in enumerate(((0x1000002fc, 0x100000000), (41, 9))):
        first_args = (x + 7, y - 3)
        first_result = first_args[0] - first_args[1] + 11
        second_args = (first_result + x, x)
        second_result = sum(second_args) + 17
        expected = Observation(struct.pack("<4Q", *first_args, *second_args),
                               struct.pack("<2Q", first_result, second_result),
                               (second_result + x) & 0xffffffff)
        data = bytes([selector])
        check("native EXE", run(native, data), expected)
        check("translated EXE", run(lifted, data), expected)
        check("mapped EXE", run_mapped_child(mapper_path, native, data, io, mix, second), expected)
        print(f"selector={selector} first={first_args} second={second_args} "
              f"output={expected.output.hex()} exit={expected.exit_code:#x}")


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        sys.exit(mapped_child(*map(Path, sys.argv[2:])))
    if sys.argv[1] == "--two-providers":
        compare_two_providers(*map(Path, sys.argv[2:]))
    else:
        compare(*map(Path, sys.argv[1:]))
