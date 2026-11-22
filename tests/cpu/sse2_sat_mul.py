"""Differential check for baseline 128-bit SSE2 packed saturating, multiply, min/max, avg, and sad lowering."""
import ctypes
import struct
import sys
from pathlib import Path

import pefile
from iced_x86 import Decoder

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

EXPORTS = (
    "paddsb_op", "paddsw_op", "paddusb_op", "paddusw_op",
    "psubsb_op", "psubsw_op", "psubusb_op", "psubusw_op",
    "pmulhw_op", "pmulhuw_op", "pmullw_op", "pmaddwd_op", "pmuludq_op",
    "pminub_op", "pmaxub_op", "pminsw_op", "pmaxsw_op",
    "pavgb_op", "pavgw_op", "psadbw_op",
)


def emit(native_dll: Path, output_cpp: Path) -> None:
    parts = [INTEGER_HEADER]
    with pefile.PE(str(native_dll), fast_load=True) as pe:
        for name in EXPORTS:
            ranges = function_ranges(pe, export_rva(pe, name))
            body = [ins for lo, hi in ranges for ins in region(pe, lo, hi)]
            code = lower(body, ["rcx = a; rdx = b; r8 = dst;"], {}, {}, {})
            parts.append(
                f'extern "C" __declspec(dllexport) uint64_t {name}(uint64_t a, uint64_t b, uint64_t dst) {{\n{code}\n}}'
            )
    output_cpp.write_text("\n".join(parts) + "\n", encoding="utf-8")


def clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else (hi if v > hi else v)


def ref(name: str, a: bytes, b: bytes) -> bytes:
    if name == "paddsb_op":
        return struct.pack("<16b", *(clamp(x + y, -128, 127) for x, y in zip(struct.unpack("<16b", a), struct.unpack("<16b", b))))
    if name == "paddsw_op":
        return struct.pack("<8h", *(clamp(x + y, -32768, 32767) for x, y in zip(struct.unpack("<8h", a), struct.unpack("<8h", b))))
    if name == "paddusb_op":
        return struct.pack("<16B", *(clamp(x + y, 0, 255) for x, y in zip(a, b)))
    if name == "paddusw_op":
        return struct.pack("<8H", *(clamp(x + y, 0, 65535) for x, y in zip(struct.unpack("<8H", a), struct.unpack("<8H", b))))
    if name == "psubsb_op":
        return struct.pack("<16b", *(clamp(x - y, -128, 127) for x, y in zip(struct.unpack("<16b", a), struct.unpack("<16b", b))))
    if name == "psubsw_op":
        return struct.pack("<8h", *(clamp(x - y, -32768, 32767) for x, y in zip(struct.unpack("<8h", a), struct.unpack("<8h", b))))
    if name == "psubusb_op":
        return struct.pack("<16B", *(clamp(x - y, 0, 255) for x, y in zip(a, b)))
    if name == "psubusw_op":
        return struct.pack("<8H", *(clamp(x - y, 0, 65535) for x, y in zip(struct.unpack("<8H", a), struct.unpack("<8H", b))))
    if name == "pmulhw_op":
        return struct.pack("<8h", *(((x * y) >> 16) for x, y in zip(struct.unpack("<8h", a), struct.unpack("<8h", b))))
    if name == "pmulhuw_op":
        return struct.pack("<8H", *(((x * y) >> 16) for x, y in zip(struct.unpack("<8H", a), struct.unpack("<8H", b))))
    if name == "pmullw_op":
        return struct.pack("<8H", *(((x * y) & 0xffff) for x, y in zip(struct.unpack("<8h", a), struct.unpack("<8h", b))))
    if name == "pmaddwd_op":
        xs, ys = struct.unpack("<8h", a), struct.unpack("<8h", b)
        out = [((xs[2 * i] * ys[2 * i] + xs[2 * i + 1] * ys[2 * i + 1]) & 0xffffffff) for i in range(4)]
        return struct.pack("<4I", *out)
    if name == "pmuludq_op":
        xs, ys = struct.unpack("<4I", a), struct.unpack("<4I", b)
        return struct.pack("<2Q", xs[0] * ys[0], xs[2] * ys[2])
    if name == "pminub_op":
        return bytes(min(x, y) for x, y in zip(a, b))
    if name == "pmaxub_op":
        return bytes(max(x, y) for x, y in zip(a, b))
    if name == "pminsw_op":
        return struct.pack("<8h", *(min(x, y) for x, y in zip(struct.unpack("<8h", a), struct.unpack("<8h", b))))
    if name == "pmaxsw_op":
        return struct.pack("<8h", *(max(x, y) for x, y in zip(struct.unpack("<8h", a), struct.unpack("<8h", b))))
    if name == "pavgb_op":
        return bytes(((x + y + 1) >> 1) for x, y in zip(a, b))
    if name == "pavgw_op":
        return struct.pack("<8H", *(((x + y + 1) >> 1) for x, y in zip(struct.unpack("<8H", a), struct.unpack("<8H", b))))
    if name == "psadbw_op":
        lo = sum(abs(x - y) for x, y in zip(a[:8], b[:8]))
        hi = sum(abs(x - y) for x, y in zip(a[8:], b[8:]))
        return struct.pack("<2Q", lo, hi)
    raise AssertionError(name)


def check_controls() -> None:
    # 64-bit MMX paddsb mm0, mm1 (0F EC C1) followed by ret (C3) must be rejected.
    mmx = list(Decoder(64, b"\x0f\xec\xc1\xc3", ip=0x1000))
    try:
        lower(mmx, [], {}, {}, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected 64-bit MMX paddsb to be rejected")


def check(native_dll: Path, lifted_dll: Path) -> None:
    check_controls()
    native = ctypes.CDLL(str(native_dll))
    lifted = ctypes.CDLL(str(lifted_dll))
    # Include saturation extremes, INT16_MIN*INT16_MIN overflow pair for pmaddwd, and unsigned extremes.
    a_bytes = bytes([
        0x00, 0x80, 0x00, 0x80, 0x7f, 0x7f, 0xff, 0xff,
        0x00, 0x01, 0x7f, 0x80, 0xfe, 0x55, 0xaa, 0x33,
    ])
    b_bytes = bytes([
        0x00, 0x80, 0x00, 0x80, 0x7f, 0x7f, 0x01, 0x00,
        0xff, 0x02, 0x01, 0x80, 0x03, 0xaa, 0x55, 0xcc,
    ])
    a_buf = (ctypes.c_ubyte * 16)(*a_bytes)
    b_buf = (ctypes.c_ubyte * 16)(*b_bytes)
    out_n = (ctypes.c_ubyte * 16)()
    out_l = (ctypes.c_ubyte * 16)()
    for name in EXPORTS:
        fn_n = getattr(native, name)
        fn_l = getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        fn_n(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_n))
        fn_l(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_l))
        got_n, got_l = bytes(out_n), bytes(out_l)
        expected = ref(name, a_bytes, b_bytes)
        if got_n != expected or got_l != expected:
            raise AssertionError(f"{name}: expected={expected.hex()} native={got_n.hex()} lifted={got_l.hex()}")
    print(f"{len(EXPORTS)} baseline 128-bit SSE2 saturating/mul/minmax/avg/sad cases matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:4]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(Path(native), Path(other))
    else:
        raise SystemExit(f"unknown mode {mode}")
