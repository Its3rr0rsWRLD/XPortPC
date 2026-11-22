"""Draw family `f32_modes`: pixel_aot_check.py draw --family f32_modes.

The binary32 float mode of a draw made explicit and the two ways a bit pattern can be checked, ported from
R0Y00/Xbox2Windows#363 by abilliontokens.

- The uncompressed export `exp mrt0 vA, vB, vC, vD done vm` returns four distinct registers as binary32, or as uint4
  bit patterns with lower(integer_export=True), the lossless readback for integer moves, bit operations and bitcasts.
- denorm_mode draws one program under -denorm preserve and -denorm ftz with mode-matched references: v_min_f32 and
  v_max_f32 against 1.0 and -1.0 keep the least subnormal under preserve and export zero under ftz, while v_mul_f32 by
  1.0 folds to a move and exports identical raw bits in both, so it cannot tell the modes apart alone. The preserve
  build must fail the ftz reference.
- nan_class accepts a NaN by class on a masked channel (any sign or payload), logging both raw words; unmasked
  channels stay strict bitwise. A finite result on a masked channel, or a NaN on a strict finite one, must fail.
- integer_readback round-trips v_mov_b32 bit copies through the R32G32B32A32_UINT target.

The case-file trailer is the renderer's 'X2WF' section (common.write_case), not upstream's bare flags byte, so that it can
precede our 'X2WM' memory section. Other fixtures keep their plain `-T ps_6_0` compile (common.compile_shader is the
explicit-mode entry point); the RTX 5060 Ti (driver 32.0.16.2124) refused one curve program under -denorm preserve.
"""
import struct
import subprocess

from .common import compile_shader, flush_ftz, lower, must_reject, translate, with_constants, write_case

LEAST_SUBNORMAL = struct.unpack("<f", struct.pack("<I", 1))[0]
# v_min_f32/v_max_f32 on the least binary32 subnormal keep it under -denorm preserve and flush it to zero under ftz;
# v_mul_f32 by 1.0 folds to a move, so that channel exports identical bits under both modes. Two SGPR sources need the
# VOP3 (e64) encoding: a VOP2 source 1 must be a VGPR, which upstream's e32 spelling of these programs was not.
DENORM_BODY = [
    "v_min_f32_e64 v12, s44, s45",
    "v_max_f32_e64 v13, s44, s46",
    "v_mul_f32_e64 v14, s44, 1.0",
]
EXPORT = "exp mrt0 v12, v13, v14, v15 done vm"


def uncompressed_export(body):
    """Run body on the sample, then export v12 to v15 as four uncompressed binary32 channels."""
    program = with_constants(body)
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[pos:] = [EXPORT, "s_endpgm"]
    return program


def translate_integer(instructions):
    return lower(instructions, 20, 24, [1, 2, 3, 4], constant_descriptor=64, integer_export=True)


def nan_program():
    return uncompressed_export([
        "v_add_f32_e64 v12, s44, s47",
        "v_add_f32_e64 v13, s45, s46",
        "v_add_f32_e64 v14, s45, s45",
    ])


MOVE_WORDS = (0x7fc00001, 0xffc00003, 0x00000001, 0x80000000)


def move_program():
    return uncompressed_export([
        "v_mov_b32_e32 v12, s44",
        f"v_mov_b32_e32 v13, {MOVE_WORDS[1]:#x}",
        f"v_mov_b32_e32 v14, {MOVE_WORDS[2]:#x}",
        f"v_mov_b32_e32 v15, {MOVE_WORDS[3]:#x}",
    ])


def as_float(word):
    return struct.unpack("<f", struct.pack("<I", word))[0]


def mismatch(result, message):
    if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
        raise AssertionError(message)


def check_denorm_mode_draw(directory, compiler, renderer, backend):
    """Draw one program under both -denorm modes with mode-matched references."""
    source = directory / "denorm_mode.hlsl"
    shader = directory / "denorm_mode.cso"
    case = directory / "denorm_mode.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, LEAST_SUBNORMAL, 1.0, -1.0, 0.0)
    source.write_text(translate(uncompressed_export(DENORM_BODY)), encoding="ascii")
    passthrough = 1.0  # the untouched sample alpha
    preserve = (LEAST_SUBNORMAL, LEAST_SUBNORMAL, LEAST_SUBNORMAL, passthrough)
    ftz = (flush_ftz(LEAST_SUBNORMAL), flush_ftz(LEAST_SUBNORMAL), LEAST_SUBNORMAL, passthrough)
    write_case(case, constants, preserve)
    compile_shader(compiler, source, shader)
    subprocess.run(draw, check=True)
    # The folding channel expects the same raw subnormal under ftz, so this run passing proves the folded move exports
    # identical bits in both modes; the min and max channels expect the flush.
    write_case(case, constants, ftz)
    compile_shader(compiler, source, shader, mode="ftz")
    subprocess.run(draw, check=True)
    # The min and max channels differ between the modes, so the preserve build must fail the ftz reference still on disk.
    compile_shader(compiler, source, shader)
    mismatch(subprocess.run(draw, capture_output=True, text=True), "A preserve-mode export matched the ftz reference")


def check_nan_class_draw(directory, compiler, renderer, backend):
    """Check v_add_f32 NaN results by class on masked channels; finite channels stay strict."""
    source = directory / "nan_class.hlsl"
    shader = directory / "nan_class.cso"
    case = directory / "nan_class.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    words = (0x7fc00000, 0x7f800001, 0xffc00003, 0x3f800000)
    values = [as_float(word) for word in words]
    constants = bytearray(256)
    struct.pack_into("<4I", constants, 12, *words)
    program = nan_program()
    source.write_text(translate(program), encoding="ascii")
    compile_shader(compiler, source, shader)
    write_case(case, constants, (*values[:3], 1.0), nan_mask=0b0111)
    subprocess.run(draw, check=True)
    # A masked channel whose shader output is finite must fail on every backend.
    finite = [line.replace("v12, s44, s47", "v12, s47, s47") for line in program]
    source.write_text(translate(finite), encoding="ascii")
    compile_shader(compiler, source, shader)
    mismatch(subprocess.run(draw, capture_output=True, text=True), "A finite export satisfied a NaN-class channel")
    # A strict finite channel against a NaN export must also fail on every backend.
    nan_alpha = program[:-2] + ["v_add_f32_e64 v15, s45, s46"] + program[-2:]
    source.write_text(translate(nan_alpha), encoding="ascii")
    compile_shader(compiler, source, shader)
    mismatch(subprocess.run(draw, capture_output=True, text=True), "A NaN export satisfied the strict finite channel")


def check_integer_readback_draw(directory, compiler, renderer, backend):
    """Round-trip v_mov_b32 bit copies bit-for-bit through the integer readback target."""
    source = directory / "integer_readback.hlsl"
    shader = directory / "integer_readback.cso"
    case = directory / "integer_readback.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    constants = bytearray(256)
    struct.pack_into("<I", constants, 12, MOVE_WORDS[0])
    source.write_text(translate_integer(move_program()), encoding="ascii")
    compile_shader(compiler, source, shader)
    expected = tuple(as_float(word) for word in MOVE_WORDS)
    write_case(case, constants, expected, integer_rt=True)
    subprocess.run(draw, check=True)
    corrupted = list(expected)
    corrupted[2] = as_float(MOVE_WORDS[2] ^ 3)
    write_case(case, constants, corrupted, integer_rt=True)
    mismatch(subprocess.run(draw, capture_output=True, text=True), "A corrupted expected word escaped the integer readback")


def check_f32_modes_draws(directory, compiler, renderer, backend):
    check_denorm_mode_draw(directory, compiler, renderer, backend)
    check_nan_class_draw(directory, compiler, renderer, backend)
    check_integer_readback_draw(directory, compiler, renderer, backend)


def controls(directory):
    # Uncompressed binary32 exports need four distinct sampled, computed or raw-word registers; an integer export
    # refuses the compressed form and nothing may follow the export.
    program = uncompressed_export(["v_add_f32_e64 v12, s44, s45", "v_add_f32_e64 v13, s45, s46",
                                   "v_add_f32_e64 v14, s46, s47", "v_add_f32_e64 v15, s47, s44"])
    modern = [line.replace("exp mrt0 ", "exp mrt0, ") for line in program]
    assert translate(modern) == translate(program)
    body = translate(program).split("float4 main", 1)[1]
    assert "return float4(alu" in body and "export16(" not in body, body
    integral = translate_integer(program)
    assert "uint4 main" in integral and "return uint4(asuint(alu" in integral, integral
    # A raw word is exported as the float with its bits, or as itself in the integer export, never through a float op.
    raw = move_program()
    assert "return float4(asfloat(movw" in translate(raw), translate(raw)
    integral = translate_integer(raw)
    assert "return uint4(movw" in integral and "asfloat" not in integral.split("uint4 main", 1)[1], integral
    must_reject(translate_integer, with_constants([]))
    export = program.index(EXPORT)
    must_reject(translate, program[:export] + ["exp mrt0 v12, v12, v13, v14 done vm"] + program[export + 1:])
    must_reject(translate, program[:export + 1] + ["v_mov_b32_e32 v20, 1.0"] + program[export + 1:])
    # A sample register still outstanding at the export, a register that was never written and a second export.
    early = with_constants([])
    wait = early.index("s_waitcnt vmcnt(0)")
    must_reject(translate, early[:wait] + [EXPORT, "s_endpgm"])
    must_reject(translate, program[:export] + ["exp mrt0 v12, v13, v14, v30 done vm"] + program[export + 1:])
    must_reject(translate, program[:export + 1] + [EXPORT] + program[export + 1:])
    # The compressed and the uncompressed export are different instructions: neither spelling takes the other's form.
    must_reject(translate, program[:export] + ["exp mrt0 v12, v13, v14, v15 done compr vm"] + program[export + 1:])
    must_reject(translate, program[:export] + ["exp mrt0 v12, v13, v14, v15 vm"] + program[export + 1:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        (uncompressed_export(DENORM_BODY), translate),
        (nan_program(), translate),
        (move_program(), translate_integer),
    ]


draw = check_f32_modes_draws
