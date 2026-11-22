"""Compare the same two-input EXE under the Windows loader, pe_map, and AOT."""
import ctypes
from pathlib import Path
import subprocess
import sys

from exe_entry_check import Observation, check, run
from native_map_check import Mapper, STATUS


def mapped_child(mapper_path, image, io, mix):
    mapper = Mapper(mapper_path)
    providers = {p.name.lower(): ctypes.CDLL(str(p)) for p in (io, mix)}
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
        child = subprocess.run([sys.executable, "-B", __file__, "--child", mapper_path,
                                native, io, mix], input=data, capture_output=True, timeout=15)
        check("mapped EXE", Observation(child.stderr, child.stdout, child.returncode), original)
        print(f"selector={selector} arguments={original.arguments.hex()} "
              f"output={original.output.hex()} exit={original.exit_code:#x}")


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        sys.exit(mapped_child(*map(Path, sys.argv[2:])))
    compare(*map(Path, sys.argv[1:]))
