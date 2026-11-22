"""Compare native and translated x64 integer bit-scan, bit-count, byte-swap, and bit-test instructions."""
import ctypes
from pathlib import Path
import sys

import pefile
from iced_x86 import Decoder

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

U64 = ctypes.c_uint64

UNARY_OUT_EXPORTS = ("bsf32", "bsf64", "bsr32", "bsr64", "popcnt32", "popcnt64", "lzcnt32", "lzcnt64", "btc64_imm")
UNARY_PLAIN_EXPORTS = ("bswap32", "bswap64")
BINARY_OUT_EXPORTS = ("bt32", "bt64", "bts32", "bts64", "btr32", "btr64", "btc32", "btc64")


def emit(image, output):
    parts = [
        "#include <intrin.h>\n",
        INTEGER_HEADER,
        'extern "C" __declspec(dllexport) int host_has_popcnt_lzcnt() {\n'
        "    int regs[4]{};\n"
        "    __cpuid(regs, 1);\n"
        "    if ((regs[2] & (1 << 23)) == 0) return 0;\n"
        "    __cpuid(regs, static_cast<int>(0x80000000u));\n"
        "    if (static_cast<unsigned>(regs[0]) < 0x80000001u) return 0;\n"
        "    __cpuid(regs, static_cast<int>(0x80000001u));\n"
        "    return (regs[2] & (1 << 5)) != 0;\n"
        "}\n",
    ]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in UNARY_OUT_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word out) {{\n{code}\n}}\n')
        for name in UNARY_PLAIN_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a) {{\n{code}\n}}\n')
        for name in BINARY_OUT_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = bit; r8 = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word bit, word out) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in UNARY_OUT_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, ctypes.POINTER(U64)], U64
    for name in UNARY_PLAIN_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64], U64
    for name in BINARY_OUT_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, ctypes.POINTER(U64)], U64
    return lib


def ref_bswap(a, bits):
    size = bits // 8
    return int.from_bytes((a & ((1 << bits) - 1)).to_bytes(size, "little"), "big")


def ref_popcnt(a, bits):
    v = (a & ((1 << bits) - 1)).bit_count()
    return v, (1 if v == 0 else 0)


def ref_lzcnt(a, bits):
    a &= (1 << bits) - 1
    if a == 0:
        return bits, 2
    v = bits - a.bit_length()
    return v, (1 if v == 0 else 0)


def ref_bt_op(op, a, bit, bits):
    mask = (1 << bits) - 1
    b = bit & (bits - 1)
    cf = (a >> b) & 1
    if op == "bt":
        return a, cf  # bt does not write destination (rax keeps all 64 bits)
    v = a & mask
    if op == "bts":
        v |= 1 << b
    elif op == "btr":
        v &= ~(1 << b)
    elif op == "btc":
        v ^= 1 << b
    return v & mask, cf


def check(native_path, lifted_path):
    lifted = load_lib(lifted_path)
    lifted.host_has_popcnt_lzcnt.argtypes, lifted.host_has_popcnt_lzcnt.restype = [], ctypes.c_int
    if not lifted.host_has_popcnt_lzcnt():
        print("Host CPU lacks POPCNT or LZCNT (CPUID leaf 1 ECX bit 23 / 80000001h ECX bit 5); skipping native differential check.")
        sys.exit(77)
    native = load_lib(native_path)
    slot = U64(0)
    values = (
        0, 1, 2, 0x80, 0x01020304, 0x55aa55aa, 0x7fffffff, 0x80000000, 0xffffffff,
        0xdeadbeef00000000, 0xdeadbeef00000001, 0x0123456789abcdef,
        0x8000000000000000, 0x7fffffffffffffff, 0xffffffffffffffff,
    )
    bits_list = (0, 1, 7, 15, 31, 32, 33, 47, 63, 64, 65, 0xffffffff)

    cases = 0
    for name, is_bsr, bits in (("bsf32", False, 32), ("bsf64", False, 64), ("bsr32", True, 32), ("bsr64", True, 64)):
        mask = (1 << bits) - 1
        for a in values:
            masked = a & mask
            for lib, label in ((native, "native"), (lifted, "lifted")):
                slot.value = 0xdeadbeef
                got = getattr(lib, name)(a, ctypes.byref(slot))
                if masked == 0:
                    if slot.value != 1:
                        raise AssertionError(f"{label} {name}({a:#x}) ZF = {slot.value}, expected 1")
                else:
                    want = (masked.bit_length() - 1) if is_bsr else ((masked & -masked).bit_length() - 1)
                    if (got, slot.value) != (want, 0):
                        raise AssertionError(f"{label} {name}({a:#x}) = ({got:#x}, {slot.value}), expected ({want:#x}, 0)")
            cases += 1

    for name, bits in (("bswap32", 32), ("bswap64", 64)):
        for a in values:
            want = ref_bswap(a, bits)
            for lib, label in ((native, "native"), (lifted, "lifted")):
                got = getattr(lib, name)(a)
                if got != want:
                    raise AssertionError(f"{label} {name}({a:#x}) = {got:#x}, expected {want:#x}")
            cases += 1

    for name, fn, bits in (("popcnt32", ref_popcnt, 32), ("popcnt64", ref_popcnt, 64),
                           ("lzcnt32", ref_lzcnt, 32), ("lzcnt64", ref_lzcnt, 64)):
        for a in values:
            want_v, want_f = fn(a, bits)
            for lib, label in ((native, "native"), (lifted, "lifted")):
                slot.value = 0xdeadbeef
                got = getattr(lib, name)(a, ctypes.byref(slot))
                if (got, slot.value) != (want_v, want_f):
                    raise AssertionError(
                        f"{label} {name}({a:#x}) = ({got:#x}, {slot.value:#x}), expected ({want_v:#x}, {want_f:#x})"
                    )
            cases += 1

    for name, op, bits in (
        ("bt32", "bt", 32), ("bt64", "bt", 64),
        ("bts32", "bts", 32), ("bts64", "bts", 64),
        ("btr32", "btr", 32), ("btr64", "btr", 64),
        ("btc32", "btc", 32), ("btc64", "btc", 64),
    ):
        for a in values:
            for bit in bits_list:
                want_v, want_cf = ref_bt_op(op, a, bit, bits)
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    slot.value = 0xdeadbeef
                    got = getattr(lib, name)(a, bit, ctypes.byref(slot))
                    if (got, slot.value) != (want_v, want_cf):
                        raise AssertionError(
                            f"{label} {name}({a:#x}, {bit:#x}) = ({got:#x}, {slot.value}), expected ({want_v:#x}, {want_cf})"
                        )
                cases += 1

    for a in values:
        want_v, want_cf = ref_bt_op("btc", a, 47, 64)
        for lib, label in ((native, "native"), (lifted, "lifted")):
            slot.value = 0xdeadbeef
            got = lib.btc64_imm(a, ctypes.byref(slot))
            if (got, slot.value) != (want_v, want_cf):
                raise AssertionError(f"{label} btc64_imm({a:#x}) = ({got:#x}, {slot.value}), expected ({want_v:#x}, {want_cf})")
        cases += 1

    print(f"{cases} integer bit-op cases (BSF, BSR, BSWAP, POPCNT, LZCNT, BT/BTS/BTR/BTC) matched native and translated DLLs")


def check_rejections():
    # Memory-operand BT (0F A3 11 = bt [rcx], edx) uses signed bit-offset scaling outside register-only lowering.
    try:
        lower(list(Decoder(64, bytes.fromhex("0f a3 11 c3"), ip=0x1000)), [], {}, {}, {})
    except ValueError as exc:
        if not str(exc).startswith("unsupported query operation at 0x1000"):
            raise AssertionError(f"unexpected diagnostic {exc}") from exc
    else:
        raise AssertionError("accepted memory-operand bt")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(native, other)
        check_rejections()
    else:
        raise ValueError(mode)
