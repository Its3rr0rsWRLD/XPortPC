"""Draw family `mul24`: pixel_aot_check.py draw --family mul24.

The 24-bit integer multiplies v_mul_i32_i24, v_mul_u32_u24, v_mul_hi_i32_i24 and v_mul_hi_u32_u24 in e32 and e64 (forms/
valu_int.py), ported from R0Y00/Xbox2Windows#542 by Alexander: draws, wrong references and controls. Every product is
folded into one word by a rotate, xor and add chain, whose four bytes are exported as exact floats, so all eight 32-bit
results reach the readback. The lowering here is this translator's own (valu_int.py); upstream's HLSL text checks are
replaced by the acceptance and refusal controls.
"""
import struct
import subprocess

from .common import compile_shader, half_rtz, must_reject, translate, with_constants


MUL24_BODY = [
    "v_mov_b32_e32 v28, s45",
    "v_mov_b32_e32 v29, s46",
    "v_mov_b32_e32 v30, s47",
    "v_mov_b32_e32 v31, s44",
    "v_mul_i32_i24_e32 v20, s44, v28",
    "v_mul_i32_i24_e64 v21, s46, s47",
    "v_mul_u32_u24_e32 v22, s45, v29",
    "v_mul_u32_u24_e64 v23, s47, s44",
    "v_mul_hi_i32_i24_e32 v24, s44, v28",
    "v_mul_hi_i32_i24_e64 v25, s46, s47",
    "v_mul_hi_u32_u24_e32 v26, s45, v29",
    "v_mul_hi_u32_u24_e64 v27, s47, s44",
    "v_mov_b32_e32 v16, 0x2468ace1",
    *[
        line
        for reg in ("v20", "v21", "v22", "v23", "v24", "v25", "v26", "v27")
        for line in (
            "v_lshlrev_b32_e32 v17, 5, v16",
            "v_lshrrev_b32_e32 v18, 27, v16",
            "v_or_b32_e32 v16, v17, v18",
            f"v_xor_b32_e32 v16, {reg}, v16",
            "v_add_nc_u32_e32 v16, 0x9e3779b9, v16",
        )
    ],
    "v_cvt_f32_ubyte0_e32 v12, v16",
    "v_cvt_f32_ubyte1_e32 v13, v16",
    "v_cvt_f32_ubyte2_e32 v14, v16",
    "v_cvt_f32_ubyte3_e32 v15, v16",
]

MUL24_SETS = (
    (0xab800000, 0xcd000200, 0xef7fffff, 0x12800000),
    (0xff800000, 0xee800000, 0xddffffff, 0xccffffff),
    (0x7f000000, 0x80ffffff, 0x99000001, 0xaa000000),
    (0x34ffffff, 0x56000001, 0x78123456, 0x9a654321),
    (0xdeadbeef, 0xcafebabe, 0x00abcdef, 0xff112233),
)


def mul24_values():
    return with_constants(MUL24_BODY)


def mul24_reference(words, *, mode="exact"):
    """Independent 48-bit Python integer reference for 24-bit integer multiplies."""
    mask32 = 0xffffffff

    def u24(x):
        return (x & mask32) if mode == "no_mask_24" else (x & 0xffffff)

    def s24(x):
        if mode == "no_mask_24":
            x &= mask32
            return x - 0x100000000 if (x & 0x80000000) else x
        v = x & 0xffffff
        return v - 0x1000000 if (v & 0x800000) else v

    def mul_i24(a, b):
        if mode == "i24_as_u24":
            return (u24(a) * u24(b)) & mask32
        return (s24(a) * s24(b)) & mask32

    def mul_u24(a, b):
        if mode == "u24_as_i24":
            return (s24(a) * s24(b)) & mask32
        return (u24(a) * u24(b)) & mask32

    def mul_hi_i24(a, b):
        if mode == "hi_i24_as_u24":
            return ((u24(a) * u24(b)) >> 32) & mask32
        prod = s24(a) * s24(b)
        if mode == "hi_i24_bad_lo0" and prod < 0 and (prod & mask32) == 0:
            return ((prod >> 32) - 1) & mask32
        return (prod >> 32) & mask32

    def mul_hi_u24(a, b):
        if mode == "hi_u24_as_i24":
            return ((s24(a) * s24(b)) >> 32) & mask32
        return ((u24(a) * u24(b)) >> 32) & mask32

    s44, s45, s46, s47 = words
    results = (
        mul_i24(s44, s45), mul_i24(s46, s47),
        mul_u24(s45, s46), mul_u24(s47, s44),
        mul_hi_i24(s44, s45), mul_hi_i24(s46, s47),
        mul_hi_u24(s45, s46), mul_hi_u24(s47, s44),
    )
    acc = 0x2468ace1
    for r in results:
        acc = (((acc << 5) | (acc >> 27)) & mask32) ^ (r & mask32)
        acc = (acc + 0x9e3779b9) & mask32
    return [float((acc >> (8 * k)) & 0xff) for k in range(4)]


def check_mul24_draws(directory, compiler, renderer, backend):
    source = directory / "mul24.hlsl"
    shader = directory / "mul24.cso"
    source.write_text(translate(mul24_values()), encoding="ascii")
    compile_shader(compiler, source, shader)

    cases = []

    def add_case(words, expected, status):
        path = directory / f"mul24-{len(cases)}.case"
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        path.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        cases.append((path, status))

    for words in MUL24_SETS:
        add_case(words, mul24_reference(words), "pass")
    for mode in ("no_mask_24", "i24_as_u24", "u24_as_i24", "hi_i24_as_u24", "hi_i24_bad_lo0", "hi_u24_as_i24"):
        words = next(w for w in MUL24_SETS if mul24_reference(w, mode=mode) != mul24_reference(w))
        add_case(words, mul24_reference(words, mode=mode), "mismatch")
    # End batch with a passing reference after negative controls.
    add_case(MUL24_SETS[0], mul24_reference(MUL24_SETS[0]), "pass")

    # Each case is drawn on its own (upstream batches them with --check-pixel-batch): a pass must match, a mismatch
    # must be detected.
    for path, status in cases:
        draw = [renderer, backend, "--check-pixel-case", shader, path]
        if status == "pass":
            subprocess.run(draw, check=True)
            continue
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"A wrong 24-bit multiply reference escaped detection in {path.name}")

    # Mutated shader control: replacing v_mul_hi_i32_i24_e32 with v_mul_hi_u32_u24_e32 must mismatch.
    wrong_prog = [
        line.replace("v_mul_hi_i32_i24_e32 v24, s44, v28", "v_mul_hi_u32_u24_e32 v24, s44, v28")
        for line in mul24_values()
    ]
    source.write_text(translate(wrong_prog), encoding="ascii")
    compile_shader(compiler, source, shader)
    mut_case = directory / "mul24-mut.case"
    constants = bytearray(256)
    struct.pack_into("<4I", constants, 12, *MUL24_SETS[0])
    mut_case.write_bytes(constants + struct.pack("<4f", *mul24_reference(MUL24_SETS[0])) * 64)
    wrong = subprocess.run([renderer, backend, "--check-pixel-case", shader, mut_case], capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Replacing v_mul_hi_i32_i24_e32 with v_mul_hi_u32_u24_e32 escaped detection")


def controls(directory):
    translate(mul24_values())
    # (Upstream also refuses v_mul_i32_i24_sdwa; here the SDWA forms of the 24-bit multiplies are lowered by sdwa_int.)
    for words in MUL24_SETS:
        expected = mul24_reference(words)
        for ch in expected:
            assert half_rtz(ch) == ch, (words, expected)
    for mode in ("no_mask_24", "i24_as_u24", "u24_as_i24", "hi_i24_as_u24", "hi_i24_bad_lo0", "hi_u24_as_i24"):
        assert any(mul24_reference(w, mode=mode) != mul24_reference(w) for w in MUL24_SETS), mode
    base_m24 = mul24_values()
    for bad in (
        "v_mul_i32_i24_e64 v21, -s46, s47",
        "v_mul_i32_i24_e64 v21, |s46|, s47",
        "v_mul_i32_i24_e64 v21, abs(s46), s47",
        "v_mul_i32_i24_e64 v21, s46, s47 clamp",
        "v_mul_u32_u24_e64 v23, s47, s44 clamp",
        "v_mul_hi_i32_i24_e64 v25, s46, s47 clamp",
        "v_mul_hi_u32_u24_e64 v27, s47, s44 clamp",
        "v_mul_i32_i24_e64 v21, s46",
        "v_mul_u32_u24_e32 v256, s45, v29",
        "v_mul_hi_u32_u24_e64 v27, s47, 0x100000000",
    ):
        changed = [line.replace("v_mul_i32_i24_e64 v21, s46, s47", bad) for line in base_m24]
        assert changed != base_m24, bad
        must_reject(translate, changed)
    wait = base_m24.index("s_waitcnt vmcnt(0)")
    must_reject(translate, base_m24[:wait] + ["v_mul_i32_i24_e32 v12, 1, v28"] + base_m24[wait:])
    must_reject(translate, base_m24[:wait] + ["v_mul_hi_u32_u24_e64 v13, 1, 2"] + base_m24[wait:])
    load = next(i for i, line in enumerate(base_m24) if line.startswith("s_buffer_load_dwordx4"))
    lgkm = base_m24.index("s_waitcnt lgkmcnt(0)", load)
    must_reject(translate, base_m24[:lgkm] + ["v_mul_u32_u24_e64 v20, s44, 2"] + base_m24[lgkm:])
    wqm = base_m24.index("s_wqm_b64 exec, exec") + 1
    # Whole-quad mode does not restrict VALU here (control-flow.md, CF-2a), so upstream's refusal of a multiply in it
    # is an acceptance in this translator.
    translate(base_m24[:wqm] + ["v_mul_hi_i32_i24_e64 v20, 1, 2"] + base_m24[wqm:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(mul24_values(), translate)]


draw = check_mul24_draws
