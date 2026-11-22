"""Draw family `predicate`: pixel_aot_check.py draw --family predicate."""
import math
import struct
import subprocess

from .common import must_reject, translate, with_constants


# The gfx10 predicate number is a four-bit truth table. Bits 0..3 select
# less, equal, greater and unordered respectively, independent of the HLSL.
PREDICATES = ("f", "lt", "eq", "le", "gt", "lg", "ge", "o",
              "u", "nge", "nlg", "ngt", "nle", "neq", "nlt", "tru")


def predicate_group(first, sdwa=False):
    # Copy runtime constants into vector registers using supported operations.
    body = ["v_sub_f32_e64 v18, s45, 0", "v_sub_f32_e64 v19, s47, 0"]
    for channel, op in enumerate(PREDICATES[first:first + 4]):
        compare = (f"v_cmp_{op}_f32_sdwa vcc_lo, s44, v18 src0_sel:DWORD src1_sel:DWORD" if sdwa
                   else f"v_cmp_{op}_f32_e32 vcc_lo, s44, v18")
        body.extend([compare,
                     f"v_cndmask_b32_e32 v{12 + channel}, 0, v19, vcc_lo"])
    return with_constants(body)


def check_predicate_draws(directory, compiler, renderer, backend):
    source = directory / "predicates.hlsl"
    shader = directory / "predicates.cso"
    case = directory / "predicates.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    # Isolate each negated relation so another predicate cannot supply the unordered test. An
    # unordered relational fcmp alone is not enough: the Windows 10 in-box WARP 10.0.19041
    # evaluates fcmp ult, ule, ugt and uge as their ordered forms.
    for op in ("nge", "nlg", "ngt", "nle", "nlt"):
        isolated = with_constants(["v_sub_f32_e64 v18, s45, 0",
                                   f"v_cmp_{op}_f32_e32 vcc_lo, s44, v18",
                                   "v_cndmask_b32_e32 v12, 0, 1.0, vcc_lo"])
        source.write_text(translate(isolated), encoding="ascii")
        listing = directory / f"{op}.ll"
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main",
                        "-Fc", listing, "-Fo", shader, source], check=True)
        dxil = listing.read_text(encoding="utf-8")
        if not any(text in dxil for text in ("@dx.op.isSpecialFloat.f32(i32 8,", "fcmp uno ", "fcmp ueq ")):
            raise AssertionError(f"{op.upper()} lacks an explicit unordered comparison in DXIL")
    inputs = ((-1, 1, 0), (-0.0, 0.0, 1), (1, -1, 2),
              (math.nan, 1, 3), (1, math.nan, 3))
    for first in range(0, 16, 4):
        source.write_text(translate(predicate_group(first)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        for left, right, relation in inputs:
            constants = bytearray(256)
            struct.pack_into("<4f", constants, 12, left, right, 0, 1)
            pixel = struct.pack("<4f", *((op >> relation) & 1 for op in range(first, first + 4)))
            case.write_bytes(constants + pixel * 64)
            try:
                subprocess.run(draw, check=True)
            except subprocess.CalledProcessError as error:
                channels = ", ".join(
                    f"{channel}={op}" for channel, op in enumerate(PREDICATES[first:first + 4])
                )
                error.add_note(
                    f"Predicate draw on {backend}, first={first}, left={left!r}, right={right!r}, channels {channels}"
                )
                raise
    # Keep the unordered oracle and change only the NaN operand to equal.
    struct.pack_into("<f", constants, 16, 1.0)
    case.write_bytes(constants + pixel * 64)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Replacing NaN with a finite equal operand escaped detection")


# Three-bit truth table for signed and unsigned 32-bit integer comparisons (bits 0..2: <, ==, >).
INT_PREDICATES = ("f", "lt", "eq", "le", "gt", "ne", "ge", "t")
# Normal and signed-zero IEEE-754 bit patterns: the signed and unsigned orders differ (-0.0 vs +0.0, +1.0 vs -1.0)
# and so do the integer and float orders (-2.0 vs -1.0).
INT_PAIRS = ((0x80000000, 0x00000000), (0xbf800000, 0xbf800000), (0x3f800000, 0xbf800000), (0xc0000000, 0xbf800000))


def int_predicate_group(kind, encoding, first, *, wave64=False):
    # v_mov_b32 copies the runtime constants as raw words, so all 32 bits survive unchanged.
    dst = ("vcc" if wave64 else "vcc_lo") if encoding == "e32" else ("s[52:53]" if wave64 else "s52")
    body = ["v_mov_b32_e32 v18, s45", "v_mov_b32_e32 v19, s47"]
    for channel, op in enumerate(INT_PREDICATES[first:first + 4]):
        body.extend([f"v_cmp_{op}_{kind}_{encoding} {dst}, s44, v18",
                     f"v_cndmask_b32_{encoding} v{12 + channel}, 0, v19, {dst}"])
    return with_constants(body)


def int_relation(left, right, kind):
    if kind == "i32":
        left, right = (v - 0x100000000 if v & 0x80000000 else v for v in (left, right))
    return 0 if left < right else (1 if left == right else 2)


def int_case(case, left, right, first, relation):
    constants = bytearray(256)
    struct.pack_into("<IIff", constants, 12, left, right, 0.0, 1.0)
    pixel = struct.pack("<4f", *((op >> relation) & 1 for op in range(first, first + 4)))
    case.write_bytes(constants + pixel * 64)


def check_int_predicate_draws(directory, compiler, renderer, backend):
    source = directory / "int_predicates.hlsl"
    shader = directory / "int_predicates.cso"
    case = directory / "int_predicates.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    for kind in ("i32", "u32"):
        for encoding in ("e32", "e64"):
            for first in (0, 4):
                source.write_text(translate(int_predicate_group(kind, encoding, first)), encoding="ascii")
                subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
                for left, right in INT_PAIRS:
                    int_case(case, left, right, first, int_relation(left, right, kind))
                    subprocess.run(draw, check=True)
                # Wrong reference: the other signedness, on the pair whose signed and unsigned orders differ.
                other = "u32" if kind == "i32" else "i32"
                left, right = INT_PAIRS[0]
                assert int_relation(left, right, other) != int_relation(left, right, kind)
                int_case(case, left, right, first, int_relation(left, right, other))
                wrong = subprocess.run(draw, capture_output=True, text=True)
                if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
                    raise AssertionError(f"A {kind} {encoding} comparison against the {other} oracle escaped detection")


def check_predicate_family(directory, compiler, renderer, backend):
    check_predicate_draws(directory, compiler, renderer, backend)
    check_int_predicate_draws(directory, compiler, renderer, backend)


def controls(directory):
    # 32-bit integer comparisons: signed vs unsigned reads of the raw words, wave64 spelling, inline constants and
    # literals as their bit patterns, and refusals.
    i32_source = translate(int_predicate_group("i32", "e32", 0))
    u32_source = translate(int_predicate_group("u32", "e64", 4))
    assert "bool cmp24 = asint(params[0].w) < asint(movw20);" in i32_source, i32_source
    assert "bool cmp26 = params[0].w >= movw20;" in u32_source, u32_source
    assert translate(int_predicate_group("i32", "e32", 0, wave64=True)) == i32_source
    assert translate(int_predicate_group("u32", "e64", 4, wave64=True)) == u32_source
    for kind, token, expected in (
        ("i32", "-1", "asint(4294967295u)"),
        ("u32", "-1", "4294967295u"),
        ("i32", "0x80000000", "asint(2147483648u)"),
        ("u32", "0x80000000", "2147483648u"),
        ("i32", "1.0", "asint(1065353216u)"),
        ("u32", "1.0", "1065353216u"),
    ):
        prog = with_constants(["v_mov_b32_e32 v18, s45",
                               f"v_cmp_lt_{kind}_e32 vcc_lo, {token}, v18",
                               "v_cndmask_b32_e32 v12, 0, 1.0, vcc_lo"])
        assert f"bool cmp21 = {expected} < " in translate(prog), (kind, token)
    base_int = int_predicate_group("i32", "e64", 0)
    for bad in (
        "v_cmp_lt_i32_e64 s52, -s44, v18",
        "v_cmp_lt_i32_e64 s52, |s44|, v18",
        "v_cmp_lt_i32_e64 s52, abs(s44), v18",
        "v_cmp_lt_i32_e64 s52, s44, -v18",
        "v_cmp_lt_i32_e64 s52, s44, v18 clamp",
        "v_cmpx_lt_i32_e64 s52, s44, v18",
        "v_cmp_lt_i32_e64 s52, 0x100000000, v18",
        "v_cmp_lt_i32_e64 s52, s44, v30",  # unset register
    ):
        changed = [line.replace("v_cmp_lt_i32_e64 s52, s44, v18", bad) for line in base_int]
        assert changed != base_int
        must_reject(translate, changed)
    pos = base_int.index("s_waitcnt vmcnt(0)")
    must_reject(translate, base_int[:pos] + ["v_cmp_eq_u32_e32 vcc_lo, v12, v13"] + base_int[pos:])
    load = next(i for i, line in enumerate(base_int) if line.startswith("s_buffer_load_dwordx4"))
    pos = base_int.index("s_waitcnt lgkmcnt(0)", load)
    must_reject(translate, base_int[:pos] + ["v_cmp_eq_i32_e32 vcc_lo, s44, 0"] + base_int[pos:])
    pos = base_int.index("s_wqm_b64 exec, exec") + 1
    # Whole-quad mode is not a reason to refuse (CF-2a: every lane is active there).
    translate(base_int[:pos] + ["v_cmp_eq_i32_e32 vcc_lo, 0, 0"] + base_int[pos:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((predicate_group(first), translate) for first in range(0, 16, 4)),
        *((int_predicate_group(kind, encoding, first), translate)
          for kind in ("i32", "u32") for encoding in ("e32", "e64") for first in (0, 4)),
    ]


draw = check_predicate_family
