"""Shared pieces of the pixel_aot draw checks: the recording lower() wrapper, the reference program and
the constant-buffer variant every family builds on, and helpers used by more than one family."""
import functools
from pathlib import Path
import math
import struct

import pixel_aot
from pixel_aot_ops.dispatch import claimants as _claimants


# First word of each line of every program lower() accepted in this run. tools/form_coverage.py counts
# these when this test passes; a program a check expects to be rejected raises before it is recorded.
ACCEPTED = set()


claimants = functools.lru_cache(maxsize=None)(_claimants)


def lower(instructions, *args, **kwargs):
    source = pixel_aot.lower(instructions, *args, **kwargs)
    ACCEPTED.update(line.split()[0] for line in instructions if line.strip() and not line.endswith(":"))
    for line in instructions:
        # Forms are tried family module by family module (tools/pixel_aot_ops/dispatch.py), so no instruction may
        # match the forms of two families: then the order of the modules would decide how it is lowered.
        if len(families := claimants(line)) > 1:
            raise AssertionError(f"Forms of more than one family match {line!r}: {', '.join(families)}")
    return source


def write_record(path):
    """Save ACCEPTED where CTest's FORM_COVERAGE_RECORD points; nothing is written without it."""
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("".join(f"{word}\n" for word in sorted(ACCEPTED)), encoding="utf-8")


RAMP = (0, 16, 37, 64, 101, 153, 219, 254)


def assembly(swap):
    red, blue = ("v14", "v12") if swap else ("v12", "v14")
    return [
        "s_mov_b64 s[50:51], exec",
        "s_wqm_b64 exec, exec",
        "s_mov_b32 m0, s24",
        "v_interp_p1_f32_e32 v8, v0, attr0.x",
        "v_interp_p1_f32_e32 v9, v0, attr0.y",
        "v_interp_p2_f32_e32 v9, v1, attr0.y",
        "v_interp_p2_f32_e32 v8, v1, attr0.x",
        "s_and_b64 exec, exec, s[50:51]",
        "s_mov_b32 s21, 0",
        "s_load_dwordx8 s[28:35], s[20:21], null",
        "s_mov_b32 s40, 1",
        "s_mov_b32 s41, 2",
        "s_mov_b32 s42, 3",
        "s_mov_b32 s43, 4",
        "s_waitcnt lgkmcnt(0)",
        "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D",
        "s_waitcnt vmcnt(0)",
        f"v_cvt_pkrtz_f16_f32_e32 v16, {red}, v13",
        f"v_cvt_pkrtz_f16_f32_e32 v17, {blue}, v15",
        "exp mrt0 v16, v16, v17, v17 done compr vm",
        "s_endpgm",
    ]


def must_reject(function, *args):
    try:
        function(*args)
    except (ValueError, KeyError):
        return
    raise AssertionError(f"{function.__name__} accepted invalid input")


def translate(instructions):
    return lower(instructions, 20, 24, [1, 2, 3, 4], constant_descriptor=64)


def with_constants(body):
    """Load constant words 3 to 6 into s44 to s47, then run body on the sample in v12 to v15."""
    program = assembly(False)
    pos = program.index("s_mov_b32 s40, 1")
    program.insert(pos, "s_load_dwordx4 s[44:47], s[20:21], 0x40")
    pos = program.index("s_waitcnt vmcnt(0)")
    program[pos:pos] = [
        "s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc",
        "s_waitcnt lgkmcnt(0)",
    ]
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[pos:pos] = body
    return program


def half_rtz(x):
    bits, = struct.unpack("<H", struct.pack("<e", x))
    rounded, = struct.unpack("<e", struct.pack("<H", bits))
    return struct.unpack("<e", struct.pack("<H", bits - (abs(rounded) > abs(x))))[0]


def half_value(word):
    return struct.unpack("<e", struct.pack("<H", word & 0xffff))[0]


def narrow_reference(x):
    if abs(x) >= 65520:
        return 0xfc00 if x < 0 else 0x7c00
    return struct.unpack("<H", struct.pack("<e", x))[0]


def single(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]
def sdwa_readback(value, high):
    return [line.format(r=value, h=high) for line in SDWA_READBACK]


SDWA_READBACK = ["v_subrev_f32_e32 {r}, 1.0, {r}", "v_mul_f32_e32 {r}, 0x4b000000, {r}", "v_mul_f32_e32 {h}, 0x3b800000, {r}", "v_floor_f32_e32 {h}, {h}", "v_fmac_f32_e32 {r}, 0xc3800000, {h}"]
M32 = 0xffffffff
byte = lambda value, n: (value >> (8 * n)) & 0xff
signed = lambda value: value - (1 << 32) if value & 0x80000000 else value


def ubyte(n, dst, src, spelling, clamp=False):
    return f"v_cvt_f32_ubyte{n}_{spelling} v{dst}, {src}{' clamp' if clamp else ''}"


# Inline constants of 16-bit float operands as binary16 values, kept apart from the lowering's table.
F16_INLINE = {"0.5": 0.5, "-0.5": -0.5, "1.0": 1.0, "-1.0": -1.0, "2.0": 2.0, "-2.0": -2.0, "4.0": 4.0, "-4.0": -4.0,
              "0.15915494": half_value(0x3118)}
assert abs(F16_INLINE["0.15915494"] - 1 / (2 * math.pi)) < 2.0 ** -12


def f16_const(token, bug):
    """An inline constant as the instruction reads it. const_bits reads a float constant as the low half of its
    binary32 encoding; int_value reads an integer constant as that number instead of as a bit pattern."""
    if "." in token:
        if bug == "const_bits":
            return half_value(struct.unpack("<I", struct.pack("<f", float(token)))[0] & 0xffff)
        return F16_INLINE[token]
    if bug == "int_value":
        return float(int(token))
    return half_value(int(token) & 0xffff)


def move(register, source):
    return f"v_or_b32_e64 v{register}, 0, {source}"
f32 = lambda x: struct.unpack("<f", struct.pack("<f", x))[0]
