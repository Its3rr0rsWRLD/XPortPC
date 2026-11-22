"""Draw family `scalar_constant`: pixel_aot_check.py draw --family scalar_constant."""
import struct
import subprocess

from .common import RAMP, assembly, half_rtz, lower, must_reject, single, translate, with_constants
from .curve_shaping import curve


def with_scalar_constant_reads() -> list[str]:
    program = with_constants(["v_mov_b32_e32 v12, s61", "v_mov_b32_e32 v13, s62", "v_mov_b32_e32 v14, s63"])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc")
    program[load:load + 1] = [
        "s_buffer_load_dword s61, s[44:47], null",
        "s_buffer_load_dword s62, s[44:47], 0x8",
        "s_buffer_load_dword s63, s[44:47], 0xfc",
    ]
    return program


PAIR_LOADS = ("s_buffer_load_dwordx2 s[60:61], s[44:47], 0xc",
              "s_buffer_load_dwordx2 s[62:63], s[44:47], 0x14",
              "s_buffer_load_dwordx2 s[64:65], s[44:47], 0xf8")


def with_scalar_pair_reads() -> list[str]:
    """Read constant words 3 and 4, 5 and 6, 62 and 63 as pairs; the first pair spans two uint4 rows."""
    program = with_constants([
        "v_mul_f32_e32 v12, s60, v12",
        "v_max_f32_e32 v12, s64, v12",
        "v_add_f32_e32 v13, s61, v13",
        "v_sub_f32_e32 v14, s62, v14",
        "v_mov_b32_e32 v15, s63",
        "v_mul_f32_e32 v15, s65, v15",
    ])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc")
    program[load:load + 1] = PAIR_LOADS
    return program


def scalar_pair_case(directory, scale, bias, minuend, alpha, floor, gain):
    """Expected colors for with_scalar_pair_reads(). Every step is exact in binary32."""
    def exact(value):
        assert single(value) == value, value
        return value
    case = bytearray(256)
    struct.pack_into("<4f", case, 12, *map(exact, (scale, bias, minuend, alpha)))
    struct.pack_into("<2f", case, 248, exact(floor), exact(gain))
    for y in RAMP:
        for x in RAMP:
            r, g, b = (single(c / 255) for c in (x, y, 128))
            color = (max(floor, exact(scale * r)), exact(bias + g), exact(minuend - b), exact(gain * alpha))
            case.extend(struct.pack("<4f", *map(half_rtz, color)))
    path = directory / "scalar-pairs.case"
    path.write_bytes(case)
    return path


def check_scalar_pair_reads() -> None:
    program = with_scalar_pair_reads()
    source = translate(program)
    for field in ("(asfloat(params[0].w) * sample", "max(asfloat(params[15].z), ", "(asfloat(params[1].x) + sample",
                  "(asfloat(params[1].y) - sample", "= params[1].z;", "(asfloat(params[15].w) * asfloat(movw"):
        assert field in source, (field, source)

    load = PAIR_LOADS[1]
    # Wider loads are lowered too (the scalar_load family); the two here are refused because they also write the
    # outstanding s[60:61] of the first pair.
    for old, new in (("0x14", "0x15"), ("0x14", "0x16"),  # not dword-aligned
                     ("0x14", "0xfc"), ("0x14", "0x100"),  # the second word or both pass the 256 bound bytes
                     ("0x14", "s60"), ("0x14", "s60, 0x14"),  # an offset register that holds no known constant
                     ("s[62:63]", "s62"), ("s[62:63]", "s[62:62]"), ("s[62:63]", "s[62:64]"),
                     ("s[62:63]", "s[60:63]"), ("s[62:63]", "s[61:62]"), ("s[62:63]", "s[106:107]"),
                     ("s[44:47]", "s[28:31]"), ("s[44:47]", "s[44:45]"), ("s[44:47]", "s[44:46]"),
                     ("dwordx2", "dword"), ("dwordx2", "dwordx4"), ("s_buffer_load", "s_load"),
                     ("dwordx2 s[62:63]", "dwordx8 s[56:63]"), ("dwordx2 s[62:63]", "dwordx16 s[48:63]")):
        bad = load.replace(old, new)
        assert bad != load
        must_reject(translate, [bad if line == load else line for line in program])

    first = program.index(PAIR_LOADS[0])
    wait = program.index("s_waitcnt lgkmcnt(0)", first)
    descriptor = program.index("s_load_dwordx4 s[44:47], s[20:21], 0x40")
    must_reject(translate, program[:descriptor + 1] + [load] + program[descriptor + 1:])  # Descriptor still loading.
    must_reject(translate, program[:wait] + program[wait + 1:])  # Results read before the wait.
    for word in ("s62", "s63"):  # Neither word of the pair can be read or written until the wait.
        must_reject(translate, program[:wait] + [f"v_mov_b32_e32 v20, {word}"] + program[wait:])
        translate(program[:wait + 1] + [f"v_mov_b32_e32 v20, {word}"] + program[wait + 1:])
        must_reject(translate, program[:wait] + [f"s_mov_b32 {word}, 0"] + program[wait:])
        must_reject(translate, program[:wait] + [f"s_buffer_load_dword {word}, s[44:47], 0x8"] + program[wait:])
    must_reject(translate, program[:wait] + [load] + program[wait:])
    must_reject(translate, program[:wait] + ["s_mov_b64 s[62:63], exec"] + program[wait:])
    translate(program[:wait + 1] + [load, "s_waitcnt lgkmcnt(0)"] + program[wait + 1:])  # Reloading after the wait.
    must_reject(translate, program[:first] + ["s_mov_b32 s46, 0"] + program[first:])

    # A pair may land in the descriptor's own registers, which ends the descriptor.
    alias = [line.replace("s[64:65]", "s[46:47]").replace("s64", "s46").replace("s65", "s47") for line in program]
    assert alias != program and translate(alias) == source
    must_reject(translate, alias[:wait + 1] + [load] + alias[wait + 1:])


def check_scalar_pair_draws(directory, compiler, renderer, backend):
    source = directory / "pairs.hlsl"
    shader = directory / "pairs.cso"
    program = with_scalar_pair_reads()
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    for constants in ((2.0, -.0625, 1.0, .5, .25, .5), (.5, -.03125, .75, 2.0, .125, .25)):
        case = scalar_pair_case(directory, *constants)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        subprocess.run(draw, check=True)
    # Words 4, 6 and 63 are the second word of each pair; each must reach its own channel.
    reference = case.read_bytes()
    for offset in (16, 24, 252):
        corrupted = bytearray(reference)
        struct.pack_into("<f", corrupted, offset, 1.0)
        case.write_bytes(corrupted)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Changing the constant at byte {offset} escaped detection")
    case.write_bytes(reference)
    shifted = [line.replace("s[62:63], s[44:47], 0x14", "s[62:63], s[44:47], 0x10") for line in program]
    source.write_text(translate(shifted), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Reading the pair one word early escaped detection")


def check_constant_descriptor_bounds() -> None:
    for offset in (0, 28, 32):
        program = [line.replace("s[20:21], 0x40", f"s[20:21], {offset:#x}")
                   for line in curve()]
        if offset == 32:
            assert lower(program, 20, 24, [1, 2, 3, 4], offset) == translate(curve())
        else:
            try:
                lower(program, 20, 24, [1, 2, 3, 4], offset)
            except ValueError as error:
                assert "descriptors overlap" in str(error), error
            else:
                raise AssertionError(f"Constant descriptor at {offset} overlaps texture 0")


def check_scalar_constant_reads() -> None:
    program = with_scalar_constant_reads()
    source = translate(program)
    for field in ("params[0].x", "params[0].z", "params[15].w"):
        assert f"= {field};" in source

    load = "s_buffer_load_dword s62, s[44:47], 0x8"
    for bad in (load.replace("0x8", "0x9"), load.replace("0x8", "0x100"), load.replace("0x8", "s60"),
                load.replace("s[44:47]", "s[28:31]"), load.replace("s[44:47]", "s[44:46]")):
        must_reject(translate, [bad if line == load else line for line in program])

    first = program.index("s_buffer_load_dword s61, s[44:47], null")
    wait = program.index("s_waitcnt lgkmcnt(0)", first)
    descriptor = program.index("s_load_dwordx4 s[44:47], s[20:21], 0x40")
    must_reject(translate, program[:descriptor + 1] + [load] + program[descriptor + 1:])
    must_reject(translate, program[:wait] + program[wait + 1:])  # Result read before the wait.
    must_reject(translate, program[:wait] + [load] + program[wait:])  # Outstanding write to the same SGPR.
    must_reject(translate, program[:first] + ["s_mov_b32 s46, 0"] + program[first:])
    must_reject(translate, [line.replace("s[44:47]", "s[46:49]") for line in program])

    alias = [line.replace("s63", "s46") for line in program]
    assert translate(alias) == source
    must_reject(translate, alias[:wait + 1] + [load] + alias[wait + 1:])


def check_untracked_scalar_reads() -> None:
    """An SGPR the binding contract does not name (here s3) holds an unknown value. Reading it must refuse with
    ValueError, as every other refusal does; it raised KeyError before (found by tools/corpus_translate.py, where
    RADV programs read entry SGPRs such as s3). The tracked neighbours still translate."""
    program = assembly(False)
    for line in ("s_mov_b32 s60, s3", "s_movk_i32 s60, s3", "s_cmp_eq_i32 s3, 0", "s_bfe_u32 s60, s3, 0x20016",
                 "s_add_u32 s60, s3, 1", "v_mul_f32_e32 v20, s3, v8"):
        try:
            translate([line] + program)
        except ValueError as error:
            assert "Read of unset scalar register s3" in str(error), error
        else:
            raise AssertionError(f"{line} read an untracked SGPR")
    try:
        translate(["v_mul_f32_e32 v20, 1.0, v30"] + program)
    except ValueError as error:
        assert "Read of unset vector register v30" in str(error), error
    else:
        raise AssertionError("v_mul_f32 read an unset VGPR")
    for line in ("s_mov_b32 s60, s20", "s_mov_b32 s60, 7"):
        translate([line] + program)


def check_scalar_constant_draws(directory, compiler, renderer, backend):
    source = directory / "fixture.hlsl"
    shader = directory / "fixture.cso"
    program = with_scalar_constant_reads()
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    case = directory / "scalar-constants.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    for red, green, blue in ((.25, -.5, .75), (-.125, .625, .875)):
        constants = bytearray(256)
        for offset, value in ((0, red), (8, green), (252, blue)):
            struct.pack_into("<f", constants, offset, value)
        case.write_bytes(constants + struct.pack("<4f", red, green, blue, 1) * 64)
        subprocess.run(draw, check=True)
    wrong_word = [line.replace("s62, s[44:47], 0x8", "s62, s[44:47], 0x4") for line in program]
    source.write_text(translate(wrong_word), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Reading the neighboring constant word escaped detection")
    check_scalar_pair_draws(directory, compiler, renderer, backend)


def controls(directory):
    check_constant_descriptor_bounds()
    check_scalar_constant_reads()
    check_scalar_pair_reads()
    check_untracked_scalar_reads()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        (with_scalar_constant_reads(), translate),
        (with_scalar_pair_reads(), translate),
    ]


draw = check_scalar_constant_draws
