"""Draw family `rndne`: pixel_aot_check.py draw --family rndne.

v_rndne_f32 in e32 and e64 (neg, abs, clamp), ported from R0Y00/Xbox2Windows#512 by Novatory (upstream's standalone
tests/pixel_rndne_check.py, the pixel_aot_rndne_* tests): ties to even in both signs, trunc, floor and ceil mutations,
a dropped clamp, and the sign of a rounded zero compared as an integer before the export.
"""
import struct
import subprocess

from .common import assembly, must_reject, translate, with_constants


def e32_program():
    return with_constants([
        "v_rndne_f32_e32 v12, s44",
        "v_rndne_f32_e32 v13, s45",
        "v_rndne_f32_e32 v14, s46",
        "v_rndne_f32_e32 v15, s47",
    ])


def e64_program():
    return with_constants([
        "v_rndne_f32_e64 v12, -s44",
        "v_rndne_f32_e64 v13, |s45|",
        "v_rndne_f32_e64 v14, s46 clamp",
        "v_rndne_f32_e64 v15, s47",
    ])


def check_rejections():
    # Reject v_rndne_f32 of an interpolated coordinate inside the whole-quad region.
    quad_prog = assembly(False)
    restore = quad_prog.index("s_and_b64 exec, exec, s[50:51]")
    quad_prog.insert(restore, "v_rndne_f32_e32 v8, v8")
    must_reject(translate, quad_prog)
    # Reject wrong arity (two operands).
    must_reject(translate, with_constants(["v_rndne_f32_e32 v12, s44, s45"]))
    # Reject reading an outstanding sample before s_waitcnt vmcnt(0).
    unwaited = assembly(False)
    unwaited.remove("s_waitcnt vmcnt(0)")
    pack = unwaited.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    unwaited.insert(pack, "v_rndne_f32_e32 v12, v12")
    must_reject(translate, unwaited)


def compile_ps(compiler, hlsl_text, directory, stem):
    src = directory / f"{stem}.hlsl"
    cso = directory / f"{stem}.cso"
    src.write_text(hlsl_text, encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", cso, src], check=True)
    return cso


def pack_case(inputs, expected):
    # with_constants reads constant buffer words 3..6 (byte offset 0xc).
    cb = bytes(12) + struct.pack("<4f", *inputs) + bytes(256 - 28)
    return cb + struct.pack("<4f", *expected) * 64


def run(directory, compiler, renderer, backend):

    e32_cso = compile_ps(compiler, translate(e32_program()), directory, "rndne_e32")
    case = directory / "rndne.case"
    cases = (
        ((0.5, 1.5, 2.5, 3.5), (0.0, 2.0, 2.0, 4.0)),
        ((-0.5, -1.5, -2.5, -3.5), (-0.0, -2.0, -2.0, -4.0)),
        ((0.25, 0.75, -0.25, -0.75), (0.0, 1.0, -0.0, -1.0)),
    )
    for inputs, expected in cases:
        case.write_bytes(pack_case(inputs, expected))
        res = subprocess.run([renderer, backend, "--check-pixel-case", e32_cso, case])
        if res.returncode:
            return res.returncode

    # Mutation controls: trunc, floor, and ceil must diverge from round-to-nearest-even on half-way ties.
    case.write_bytes(pack_case((0.5, 1.5, 2.5, -1.5), (0.0, 2.0, 2.0, -2.0)))
    for alt in ("v_trunc_f32_e32", "v_floor_f32_e32", "v_ceil_f32_e32"):
        mutated = [s.replace("v_rndne_f32_e32", alt) for s in e32_program()]
        mut_cso = compile_ps(compiler, translate(mutated), directory, f"mut_{alt}")
        wrong = subprocess.run([renderer, backend, "--check-pixel-case", mut_cso, case],
                               capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Replacing v_rndne_f32_e32 with {alt} escaped detection")

    # VOP3 (_e64) with negate, abs, and clamp modifiers.
    e64_cso = compile_ps(compiler, translate(e64_program()), directory, "rndne_e64")
    case.write_bytes(pack_case((1.5, -2.5, 3.5, -0.75), (-2.0, 2.0, 1.0, -1.0)))
    subprocess.run([renderer, backend, "--check-pixel-case", e64_cso, case], check=True)

    # Mutation control: dropping clamp on v14 produces 4.0 instead of 1.0.
    unclamped = [s.replace(" clamp", "") for s in e64_program()]
    unclamped_cso = compile_ps(compiler, translate(unclamped), directory, "rndne_e64_unclamped")
    wrong = subprocess.run([renderer, backend, "--check-pixel-case", unclamped_cso, case],
                           capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Dropping clamp from v_rndne_f32_e64 escaped detection")

    # Compare the sign as an integer before color export can erase the zero sign.
    sign_body = [
        "v_rndne_f32_e32 v18, s44",
        "v_cmp_lt_i32_e32 vcc_lo, v18, 0",
        "v_mov_b32_e32 v19, 1.0",
        "v_cndmask_b32_e32 v12, 0, v19, vcc_lo",
        "v_mov_b32_e32 v13, 0",
        "v_mov_b32_e32 v14, 0",
        "v_mov_b32_e32 v15, 0",
    ]
    signed_zero = compile_ps(compiler, translate(with_constants(sign_body)), directory, "rndne_zero_sign")
    for value, sign in ((-0.25, 1.0), (0.25, 0.0)):
        case.write_bytes(pack_case((value, 0, 0, 0), (sign, 0, 0, 0)))
        subprocess.run([renderer, backend, "--check-pixel-case", signed_zero, case], check=True)
    case.write_bytes(pack_case((-0.25, 0, 0, 0), (0.0, 0, 0, 0)))
    wrong = subprocess.run([renderer, backend, "--check-pixel-case", signed_zero, case],
                           capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("A wrong zero sign escaped detection")

    return 0


def controls(directory):
    check_rejections()
    translate(e32_program())
    translate(e64_program())


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(e32_program(), translate), (e64_program(), translate)]


draw = run
