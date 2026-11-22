"""Compare native and translated ADX instructions (ADCX, ADOX) in 32-bit and 64-bit forms."""
import ctypes
from pathlib import Path
import sys

import pefile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

U64 = ctypes.c_uint64
EXPORTS = ("adcx32_op", "adcx64_op", "adox32_op", "adox64_op", "adx_dual64",
           "shl1_adox32", "imul_seto32", "andn_clears_of32")


def emit(image, output):
    parts = [
        "#include <intrin.h>\n",
        INTEGER_HEADER,
        'extern "C" __declspec(dllexport) int host_has_adx() {\n'
        "    int regs[4]{};\n"
        "    __cpuid(regs, 0);\n"
        "    if (regs[0] < 7) return 0;\n"
        "    __cpuidex(regs, 7, 0);\n"
        "    return (regs[1] & (1 << 19)) != 0;\n"
        "}\n",
    ]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = c; r9 = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word c, word out) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, U64, ctypes.POINTER(U64)], U64
    return lib


def check(native_path, lifted_path):
    lifted = load_lib(lifted_path)
    lifted.host_has_adx.argtypes, lifted.host_has_adx.restype = [], ctypes.c_int
    if not lifted.host_has_adx():
        print("Host CPU lacks ADX (CPUID leaf 7 EBX bit 19); skipping native differential check.")
        sys.exit(77)
    native = load_lib(native_path)
    slot = U64(0)
    pair = (U64 * 2)(0, 0)
    vals = (0, 1, 0x7fffffff, 0x80000000, 0xfffffffe, 0xffffffff,
            0xdeadbeef00000000, 0x7fffffffffffffff, 0x8000000000000000,
            0xfffffffffffffffe, 0xffffffffffffffff)

    cases = 0
    for name, bits, is_adox in (("adcx32_op", 32, False), ("adcx64_op", 64, False),
                                ("adox32_op", 32, True), ("adox64_op", 64, True)):
        mask = (1 << bits) - 1
        for a in vals:
            for b in vals:
                for cin in (0, 1):
                    total = (a & mask) + (b & mask) + cin
                    want_v = total & mask
                    carry_out = 1 if total > mask else 0
                    want_f = carry_out if is_adox else (carry_out << 1)
                    for lib, label in ((native, "native"), (lifted, "lifted")):
                        slot.value = 0xdeadbeef
                        got = getattr(lib, name)(a, b, cin, ctypes.byref(slot))
                        if (got, slot.value) != (want_v, want_f):
                            raise AssertionError(
                                f"{label} {name}({a:#x}, {b:#x}, {cin}) = ({got:#x}, {slot.value:#x}), "
                                f"expected ({want_v:#x}, {want_f:#x})"
                            )
                    cases += 1

    mask64 = (1 << 64) - 1
    dual_vals = (0, 1, 0x8000000000000000, 0xfffffffffffffffe, 0xffffffffffffffff)
    for a in dual_vals:
        for b in dual_vals:
            for c in dual_vals:
                t1 = a + c
                cf = 1 if t1 > mask64 else 0
                rax = t1 & mask64
                t2 = b + c
                of = 1 if t2 > mask64 else 0
                r11 = t2 & mask64
                t3 = rax + b + cf
                cf = 1 if t3 > mask64 else 0
                rax = t3 & mask64
                t4 = r11 + a + of
                of = 1 if t4 > mask64 else 0
                r11 = t4 & mask64
                want_f = (cf << 1) | of
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    pair[0] = pair[1] = 0xdeadbeef
                    got = lib.adx_dual64(a, b, c, pair)
                    if (got, pair[0], pair[1]) != (rax, r11, want_f):
                        raise AssertionError(
                            f"{label} adx_dual64({a:#x}, {b:#x}, {c:#x}) = ({got:#x}, {pair[0]:#x}, {pair[1]:#x}), "
                            f"expected ({rax:#x}, {r11:#x}, {want_f:#x})"
                        )
                cases += 1

    for a in (0x00000000, 0x40000000, 0x80000000, 0xc0000000):
        shl_of = 1 if (((a >> 31) ^ ((a >> 30) & 1)) != 0) else 0
        want_sum = (10 + 20 + shl_of) & 0xffffffff
        for lib, label in ((native, "native"), (lifted, "lifted")):
            slot.value = 0xdeadbeef
            got = lib.shl1_adox32(a, 10, 20, ctypes.byref(slot))
            if (got, slot.value) != (want_sum, 0):
                raise AssertionError(f"{label} shl1_adox32({a:#x}) = ({got:#x}, {slot.value}), expected ({want_sum:#x}, 0)")
        cases += 1

    for a, b, want_of in ((100, 200, 0), (0x10000, 0x10000, 1), (-0x10000 & 0xffffffff, 0x10000, 1), (0x7fffffff, 1, 0)):
        for lib, label in ((native, "native"), (lifted, "lifted")):
            got = lib.imul_seto32(a, b, 0, ctypes.byref(slot))
            if got != want_of:
                raise AssertionError(f"{label} imul_seto32({a:#x}, {b:#x}) = {got}, expected {want_of}")
        cases += 1

    for lib, label in ((native, "native"), (lifted, "lifted")):
        got = lib.andn_clears_of32(0x1234, 0x5678, 0, ctypes.byref(slot))
        if got != 0:
            raise AssertionError(f"{label} andn_clears_of32 = {got}, expected 0")
    cases += 1

    print(f"{cases} ADX cases (ADCX, ADOX, dual-carry chains, and OF producer compositions) matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(native, other)
    else:
        raise ValueError(mode)
