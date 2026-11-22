"""Draw family `mode_register`: pixel_aot_check.py draw --family mode_register.

s_setreg_imm32_b32 (forms/sopk.py), ported from R0Y00/Xbox2Windows#640 by rasptum. Two writes are accepted: a whole
scratch-base register (FLAT_SCR_LO, FLAT_SCR_HI), which no lowered instruction reads, and MODE[3:2], the binary16 and
binary64 rounding mode, as tracked state. The program opens with the scratch base writes. MODE[3:2] then selects round
toward zero for an exact widening, restores round to nearest even for two narrowings, and selects round toward zero
again before a second exact widening and the truncating pack. Channel 0 widens S0, channels 1 and 2 narrow and widen
back (channel 2 a subnormal scaled by 2^24) and channel 3 widens -|S0|.
"""
import struct
import subprocess

from .common import compile_shader, half_rtz, half_value, must_reject, narrow_reference, translate, with_constants
from .half import HALF_BODY
from .narrow import NARROW_BODY

FLAT_SCRATCH_WRITES = [
    "s_setreg_imm32_b32 hwreg(HW_REG_FLAT_SCR_LO), 0",
    "s_setreg_imm32_b32 hwreg(HW_REG_FLAT_SCR_HI), 0x400",
]
HALF_RTZ = "s_setreg_imm32_b32 hwreg(HW_REG_MODE, 2, 2), 3"
HALF_RNE = "s_setreg_imm32_b32 hwreg(HW_REG_MODE, 2, 2), 0"
MODE_BODY = [
    HALF_RTZ,
    "v_cvt_f32_f16_e32 v12, s44",
    HALF_RNE,
    "v_cvt_f16_f32_e32 v13, s45",
    "v_cvt_f32_f16_e32 v13, v13",
    "v_cvt_f16_f32_e32 v14, s46",
    "v_cvt_f32_f16_e32 v14, v14",
    "v_mul_f32_e32 v14, 0x4b800000, v14",
    HALF_RTZ,
    "v_cvt_f32_f16_e64 v15, -|s47|",
]
# Each set: the half in S44, two binary32 inputs whose nearest-even and truncated halves differ, the half in S47, and
# the wrong references (channel, value) that truncation after the restore would give.
MODE_SETS = (
    ((0xdeadc500, 1 + 3 * 2.0 ** -11, 1.5 * 2.0 ** -24, 0xbeef7bff), ((1, 1 + 2.0 ** -10), (2, 1.0))),
    ((0x00003c01, -(2.0 ** -14 - 2.0 ** -25), 65519.0, 0x00000001), ((1, -1023 * 2.0 ** -24),)),
)
PACKED_BODY = [
    "v_mov_b32_e32 v19, s45",
    "v_pk_add_f16 v22, s44, v19",
    "v_cvt_f32_f16_e32 v12, v22",
]


def mode_program():
    return FLAT_SCRATCH_WRITES + with_constants(MODE_BODY)


def expect_value_error(function, program, text):
    try:
        function(program)
    except ValueError as error:
        if text not in str(error):
            raise AssertionError(f"Expected an error naming {text!r}, got {error}")
        return
    raise AssertionError(f"Expected {text!r} to be refused")


def check_mode_register_draw(directory, compiler, renderer, backend):
    source = directory / "mode_register.hlsl"
    shader = directory / "mode_register.cso"
    case = directory / "mode_register.case"
    source.write_text(translate(mode_program()), encoding="ascii")
    compile_shader(compiler, source, shader)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    for (first, second, third, last), wrongs in MODE_SETS:
        words = [first, *(struct.unpack("<I", struct.pack("<f", x))[0] for x in (second, third)), last]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        narrowed = half_value(narrow_reference(third))
        expected = [half_value(first), half_value(narrow_reference(second)),
                    narrowed * 2.0 ** 24 if abs(narrowed) < 2.0 ** -14 else narrowed, -abs(half_value(last))]
        for x in (*expected, *(value for _, value in wrongs)):
            assert half_rtz(x) == x, x
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
        for channel, value in wrongs:
            assert struct.pack("<f", value) != struct.pack("<f", expected[channel])
            wrong_values = list(expected)
            wrong_values[channel] = value
            case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A truncated narrowing escaped detection in channel {channel}")


def controls(directory):
    """s_setreg_imm32_b32 is accepted for the scratch base and for MODE[3:2] as tracked rounding state."""
    program = mode_program()
    as_nops = [("s_nop 0" if line.startswith("s_setreg_imm32_b32 ") else line) for line in program]
    assert as_nops.count("s_nop 0") == 5
    # Every accepted write leaves the lowered result unchanged: generated names carry the instruction index, so the
    # program must translate exactly like s_nop 0 at the same positions.
    assert translate(program) == translate(as_nops)
    plain = with_constants(NARROW_BODY)
    nop = translate(["s_nop 0"] + plain)
    # The scratch base is a whole 32-bit register with any immediate; a field of it is refused.
    for value in ("0", "0x400", "-1", "0x41", "0xfffffffe", "-2147483648", "4294967295"):
        for register in ("LO", "HI"):
            assert translate([f"s_setreg_imm32_b32 hwreg(HW_REG_FLAT_SCR_{register}), {value}"] + plain) == nop
    for write in ("hwreg(HW_REG_FLAT_SCR_LO, 0, 16), 0", "hwreg(HW_REG_FLAT_SCR_HI, 16, 16), 0",
                  "hwreg(HW_REG_FLAT_SCR_LO), s48", "hwreg(HW_REG_FLAT_SCR_LO), 0x100000000",
                  "hwreg(HW_REG_FLAT_SCR_LO), 4294967296", "hwreg(HW_REG_FLAT_SCR_HI), -2147483649",
                  "hwreg(HW_REG_MODE, 0, 2), 3", "hwreg(HW_REG_MODE, 0, 2), 0", "hwreg(HW_REG_MODE, 2, 1), 0",
                  "hwreg(HW_REG_MODE, 3, 2), 0", "hwreg(HW_REG_MODE, 0, 4), 12", "hwreg(HW_REG_MODE, 4, 4), 15",
                  "hwreg(HW_REG_MODE), 0", "hwreg(HW_REG_MODE), 0x2f0", "hwreg(HW_REG_STATUS, 2, 2), 0",
                  "hwreg(HW_REG_STATUS), 0", "hwreg(HW_REG_TRAPSTS, 2, 2), 3", "hwreg(HW_REG_LDS_ALLOC), 0",
                  "hwreg(HW_REG_SHADER_CYCLES), 0", "hwreg(HW_REG_GPR_ALLOC), 0", "hwreg(HW_REG_IB_STS), 0"):
        expect_value_error(translate, [f"s_setreg_imm32_b32 {write}"] + plain, "Unsupported hardware register write")
    # The scratch base stays unobservable: its readers are not lowered.
    for reader in ("scratch_load_dword v12, off, s48", "scratch_store_dword off, v12, s48 offset:16",
                   "flat_load_dword v12, v[12:13]", "s_getreg_b32 s48, hwreg(HW_REG_FLAT_SCR_LO)"):
        must_reject(translate, with_constants([*FLAT_SCRATCH_WRITES, reader]))
    # Nearest even is the entry state, so writing it first is no change. The directed modes are refused.
    assert translate([HALF_RNE] + plain) == nop
    assert translate([HALF_RTZ, HALF_RNE] + plain) == translate(["s_nop 0", "s_nop 0"] + plain)
    for value in ("1", "2", "4", "7", "-1", "0x103"):
        expect_value_error(translate, [f"s_setreg_imm32_b32 hwreg(HW_REG_MODE, 2, 2), {value}"] + plain,
                           "Unsupported binary16 rounding mode")
    # The register forms of the same access stay unsupported.
    must_reject(translate, ["s_setreg_b32 hwreg(HW_REG_MODE, 2, 2), s48"] + plain)
    must_reject(translate, ["s_getreg_b32 s48, hwreg(HW_REG_MODE, 2, 2)"] + plain)
    # Like the hints, nothing may sit between the color export and s_endpgm.
    must_reject(translate, plain[:-1] + [HALF_RNE, plain[-1]])
    must_reject(translate, plain[:-1] + [FLAT_SCRATCH_WRITES[0], plain[-1]])
    # The write is state, not a hint: under round toward zero the nearest-even narrowing and the packed binary16
    # arithmetic are refused by name, the last write wins, and restoring nearest even first makes the same programs
    # translate exactly as without the writes.
    expect_value_error(translate, [HALF_RTZ] + plain, "under round toward zero: v_cvt_f16_f32_e32")
    expect_value_error(translate, [HALF_RNE, HALF_RTZ] + plain, "under round toward zero: v_cvt_f16_f32_e32")
    expect_value_error(translate, [line for line in program if line != HALF_RNE],
                       "under round toward zero: v_cvt_f16_f32_e32")
    packed = with_constants(PACKED_BODY)
    translate(packed)
    expect_value_error(translate, [HALF_RTZ] + packed, "under round toward zero: v_pk_add_f16")
    assert translate([HALF_RTZ, HALF_RNE] + packed) == translate(["s_nop 0", "s_nop 0"] + packed)
    for operation in ("v_cvt_f16_f32_e64 v12, -|s44|", "v_cvt_f16_u16_e32 v12, v12", "v_add_f16_e32 v12, v12, v13",
                      "v_cvt_f32_f64_e32 v12, v[12:13]", "v_dot2_f32_f16 v12, v12, v13, v14",
                      "v_fma_mixlo_f16 v12, v12, v13, v14", "v_interp_p2_f16 v12, v1, attr0.x"):
        expect_value_error(translate, with_constants([HALF_RTZ, operation]), "under round toward zero")
    # The exact widening and the pack that always truncates do not depend on the mode.
    assert translate([HALF_RTZ] + with_constants(HALF_BODY)) == translate(["s_nop 0"] + with_constants(HALF_BODY))
    # The mode follows control flow: a uniform branch that sets round toward zero on one path leaves a mode that is not
    # nearest even on every path at the join, so a narrowing after it is refused; set on both paths, it is known.
    body = with_constants(NARROW_BODY)
    start = body.index(NARROW_BODY[0])
    branch = ["s_cmp_eq_u32 s44, 0", "s_cbranch_scc1 BB0_1", HALF_RTZ, "BB0_1:"]
    expect_value_error(translate, body[:start] + branch + body[start:], "under round not known on every path")
    both = ["s_cmp_eq_u32 s44, 0", "s_cbranch_scc1 BB0_1", HALF_RTZ, "BB0_1:", HALF_RNE]
    translate(body[:start] + both + body[start:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(mode_program(), translate)]


draw = check_mode_register_draw
