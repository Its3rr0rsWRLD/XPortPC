"""Differential checks and rejection controls for 8- and 16-bit register writes and return widths,
plus 64-bit IMUL, CL shifts and MOVSX (qword_ops), the flags of INC, TEST and CMP (flag_results) and
three-operand IMUL into destinations not defined before it (imul3_fresh)."""

import ctypes
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import pefile
from iced_x86 import Decoder, Mnemonic, Register

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_switch_aot import translate
from cpu_leaf_aot import export_rva
from direct_check import GUARDS, MASK, SENTINELS, input_pairs, observe, register_probe

# Consecutive low bytes of RAX defined at every reachable RET of each export that the test calls.
WIDTHS = {"byte_merge": 8, "word_ops": 8, "byte_shift": 8, "byte_unary": 8, "al_less": 1,
          "mixed_width": 1, "ax_copy": 2, "zx_byte": 8, "set_less": 1, "set_zx": 8, "store_only": 0,
          "store_ret0": 0, "qword_ops": 8, "flag_results": 8, "imul3_fresh": 8}

FOCUSED_INPUTS = {"qword_ops": [(32, 0x8000000000000080)], "flag_results": [(255, 255)]}


def merge(register, value, width):
    """An x86 write of the low width bytes of value into register."""
    low = (1 << width * 8) - 1
    return (register & ~low | value & low) & MASK


def signed(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def reference(name, x, y, rax):
    """RAX and the three trace words after name(x, y, trace), entered with RAX = rax."""
    trace = [MASK] * 3
    if name == "byte_merge":
        rax, trace[0] = merge(x, y, 1), merge(y, x, 1)
    elif name == "word_ops":
        rax = merge(x, x + y, 2)
        trace = [merge(y, y - x, 2), merge(x, y * -3, 2), merge(x, y & 0xff, 2)]
    elif name == "byte_shift":
        count = x & 31  # five-bit count mask for 8- and 16-bit operands
        rax = merge(y, (y & 0xff) << count, 1)
        trace = [merge(y, signed(y, 8) >> count, 1), merge(y, (y & 0xffff) >> count, 2),
                 merge(y, signed(y, 16) >> count, 2)]
    elif name == "byte_unary":
        rax = merge(x, x + 1, 1)
        trace = [merge(x, -x, 2), merge(y, ~y, 1), merge(y, y - 1, 1)]
    elif name == "al_less":
        rax = merge(rax, int(x < y), 1)
    elif name == "mixed_width":
        rax = merge(rax, y, 1) if x & 1 else y & 0xffffffff
    elif name == "ax_copy":
        rax = merge(rax, y, 2)
    elif name == "zx_byte":
        rax = y & 0xff
    elif name == "set_less":
        rax, trace[0] = merge(rax, int(signed(x, 64) < signed(y, 64)), 1), merge(y, x, 1)
    elif name == "set_zx":
        rax = int(x & 0xff < y & 0xff)
    elif name == "store_only":
        trace[0] = y
    elif name == "store_ret0":
        trace[1] = x
    elif name == "qword_ops":
        scale = 2 ** (x % 64)
        rax = x * y & MASK
        trace = [y * scale & MASK, signed(y, 64) // scale & MASK, signed(y, 8) & MASK]
    elif name == "flag_results":
        incremented = (x + 1) % 256
        difference = (x - y) % (MASK + 1)
        # TEST always clears the carry flag.
        trace = [int(incremented == 0), 0, int(signed(x, 64) <= signed(y, 64))]
        rax = difference >> 63
    elif name == "imul3_fresh":
        # The low bits of a product do not depend on signedness; MOVZX clears R9 above the word.
        rax = x * 0x1010101 & 0xffffffff
        trace[0], trace[1] = y * -5 & MASK, x * 0x7fff & 0xffff
    return rax, (GUARDS[0], *trace, GUARDS[1])


def shift_inputs():
    """Counts 0..31 and count bytes above 31, under nonzero upper halves of RCX and RDX."""
    counts = [*range(32), 0x21, 0x3f, 0x80, 0xff]
    lows = (0x0001, 0x007f, 0x0080, 0x00ff, 0x8001, 0x7fff, 0x8000, 0xffff, 0x1234, 0xc3a5)
    uppers = ((0, 0), (0xdeadbeef00000000, 0x0123456789ab0000), (0xffffff00, MASK & ~0xffff))
    return [(count | high, low | upper) for count in counts for low in lows for high, upper in uppers]


def check(probe_path, original_path, lifted_path):
    probe = register_probe(probe_path)
    native, lifted = ctypes.CDLL(original_path), ctypes.CDLL(lifted_path)
    _, functions = translate(original_path, list(WIDTHS))
    widths = {name: function.return_width for name, function in zip(WIDTHS, functions)}
    if widths != WIDTHS:
        raise AssertionError(f"return widths {widths} != {WIDTHS}")
    total = 0
    for name, width in WIDTHS.items():
        source, translation = getattr(native, name), getattr(lifted, "lifted_" + name)
        # register_probe calls the target with RAX holding the target's own address.
        caller = ctypes.cast(source, ctypes.c_void_p).value
        low = (1 << width * 8) - 1
        carried = 0
        if name in FOCUSED_INPUTS:
            # The focused input pins each mutation; the general pairs vary every operand.
            inputs = FOCUSED_INPUTS[name] + input_pairs()
        else:
            inputs = shift_inputs() if name == "byte_shift" else input_pairs()
        for x, y in inputs:
            want, trace = reference(name, x, y, caller)
            original, actual = observe(probe, source, x, y), observe(probe, translation, x, y)
            if original != (want, trace, SENTINELS):
                raise AssertionError(f"original {name}({x:#x}, {y:#x}): {original} != {want:#x} {trace}")
            if (actual[0] & low, *actual[1:]) != (want & low, trace, SENTINELS):
                raise AssertionError(f"lifted_{name}({x:#x}, {y:#x}): {actual} != {want:#x} masked {low:#x}")
            if width < 8 and original[0] >> width * 8 == caller >> width * 8:
                carried += 1
            total += 1
        if width < 8:
            print(f"{name}: return width {width}; RAX bytes {width} to 7 of the original still held the caller's "
                  f"RAX {caller:#x} in {carried} of {len(inputs)} calls")
    print(f"{total} inputs match the reference on the defined RAX bytes, the guarded trace, RBX and RSI")


def check_return_reports(original_path):
    """A loop without a reachable RET reports None; a reachable RET that defines no RAX byte reports 0.

    self_loop is translated and inspected here and is never called."""
    for name, width, report in (("self_loop", None, "no reachable normal return"),
                                ("store_only", 0, "0 low byte(s) are defined at every reachable RET")):
        source, (function,) = translate(original_path, [name])
        comments = [line for line in source.splitlines() if line.startswith("// RAX: ")]
        if function.return_width != width or comments != ["// RAX: " + report]:
            raise AssertionError(f"{name}: return width {function.return_width}, source comments {comments}")
        returns = sum(line.strip() == "return rax;" for line in source.splitlines())
        if bool(returns) != (width is not None):
            raise AssertionError(f"{name}: {returns} return statements with return width {width}")
        print(f"inspected {name}: return_width {width}, {returns} return statement(s), source says: {report}")


def instruction(pe, name, mnemonic, register=None):
    entry = export_rva(pe, name)
    for ins in Decoder(64, pe.get_data(entry, 0x40), ip=entry):
        if ins.mnemonic == mnemonic and (register is None or ins.op1_register == register):
            return ins
    raise AssertionError(f"no {mnemonic} in {name}")


def check_rejections(original_path):
    data = Path(original_path).read_bytes()
    with pefile.PE(data=data, fast_load=True) as pe:
        controls = [
            ("byte_merge", instruction(pe, "byte_merge", Mnemonic.MOV, Register.DL), "8a e2", "unsupported register"),
            ("zx_byte", instruction(pe, "zx_byte", Mnemonic.MOVZX), "83 c0 00", "undefined register rax"),
            # After SETB AL only AL is defined, so a 32-bit read of EAX must be refused.
            ("set_zx", instruction(pe, "set_zx", Mnemonic.MOVZX), "83 c0 00", "undefined register rax"),
            ("store_ret0", instruction(pe, "store_ret0", Mnemonic.RET), "c2 08 00", "unsupported control flow"),
        ]
        offsets = [pe.get_offset_from_rva(ins.ip) for _, ins, _, _ in controls]
    with TemporaryDirectory() as folder:
        path = Path(folder) / "control.dll"
        for (name, ins, patch, reason), offset in zip(controls, offsets):
            patch = bytes.fromhex(patch)
            replacement = Decoder(64, patch, ip=ins.ip).decode()
            if len(patch) != ins.len or replacement.len != ins.len:
                raise AssertionError(f"{name}: {ins} and {replacement} differ in length")
            damaged = bytearray(data)
            damaged[offset:offset + ins.len] = patch
            path.write_bytes(damaged)
            run_control(name, f"{ins} -> {replacement}", path, reason)
    exports = (("join_wide", "undefined register rax"), ("cmov_word", "unsupported partial register write"),
               ("address_return", "return value may hold a guest address"),
               ("imul2_undefined", "undefined register rax"))
    for name, reason in exports:
        run_control(name, "source export", original_path, reason)
    print(f"{len(controls) + len(exports)} rejection controls passed")


def run_control(name, change, image, reason):
    try:
        translate(image, [name])
    except ValueError as exc:
        if reason not in str(exc):
            raise AssertionError(f"{name} ({change}): expected {reason!r}, got {exc}") from exc
        print(f"rejected {name} ({change}): {exc}")
    else:
        raise AssertionError(f"accepted control {name} ({change})")


if __name__ == "__main__":
    check(*sys.argv[1:])
    check_return_reports(sys.argv[2])
    check_rejections(sys.argv[2])
