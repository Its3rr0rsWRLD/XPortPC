"""Draw family `raw_word`: pixel_aot_check.py draw --family raw_word."""
import struct
import subprocess

from .common import byte, must_reject, translate, ubyte, with_constants


# Raw 32-bit words through the constant buffer, moves, selects and sign-bit operations. The constant buffer is declared
# uint4 and a move or select of a raw word is an unsigned copy, so no float type touches the word. On the RTX 4070 Ti
# (driver 32.0.16.1088) a float4 constant buffer made the driver treat a sign-bit operation on a word as a float
# negation: a negative binary32 NaN pattern came back as 0x7fffffff, and the high word 0x00264543 of a binary64 (a
# binary32 denormal) lost its low 20 bits after a flip of its sign; WARP and the same shaders over a uint4 buffer
# were exact. These draws keep that exactness checked on both backends. Words: negative NaNs with the payload in
# the quiet bit, below it and all ones, a positive signalling NaN, the sign bit alone, the smallest denormal, and a
# denormal with a payload.
RAW_SIGN = 0x80000000
RAW_WORDS = (0xff800001, 0xffc00000, 0xfffffffe, 0x7f800001, 0x80000000, 0x00000001, 0x00264543)
RAW_MASK = 0xffffffff  # itself a negative NaN pattern, read from the constant buffer as the AND mask of one program


def raw_readback(register):
    return [ubyte(n, 12 + n, register, "e32") for n in range(4)]


# (name, body, model(word) -> expected word, {bug: wrong(word) -> word}). The word is constant word 3 (s44); s45 is
# RAW_MASK, s46 and s47 are zero.
RAW_WORD_PROGRAMS = (
    # The step-1 program: a copy through v_or, then a sign flip of the whole word.
    ("or_xor", ["v_or_b32_e64 v18, 0, s44", "v_xor_b32_e64 v19, 0x80000000, v18", *raw_readback("v19")],
     lambda w: w ^ RAW_SIGN,
     {"sign_cleared": lambda w: (w ^ RAW_SIGN) & 0x7fffffff, "quieted": lambda w: (w ^ RAW_SIGN) | 0x400000,
      "payload_zeroed": lambda w: (w ^ RAW_SIGN) & 0xff800000, "canonical_nan": lambda w: 0x7fffffff if (w & 0x7fffffff) > 0x7f800000 else w ^ RAW_SIGN}),
    # Constant buffer, v_mov, sign flip, then a v_cndmask select whose condition is always true.
    ("mov_xor_select",
     ["v_mov_b32_e32 v18, s44", "v_xor_b32_e32 v19, 0x80000000, v18", "v_cmp_class_f32_e64 vcc_lo, s46, 0x3ff",
      "v_cndmask_b32_e32 v20, v18, v19, vcc_lo", *raw_readback("v20")],
     lambda w: w ^ RAW_SIGN,
     {"sign_cleared": lambda w: (w ^ RAW_SIGN) & 0x7fffffff, "quieted": lambda w: (w ^ RAW_SIGN) | 0x400000,
      "unselected": lambda w: w}),
    # The same with a condition that is always false, so the select takes its first source.
    ("mov_xor_select_false",
     ["v_mov_b32_e32 v18, s44", "v_xor_b32_e32 v19, 0x80000000, v18", "v_cmp_class_f32_e64 vcc_lo, s46, 0",
      "v_cndmask_b32_e64 v20, v19, v18, vcc_lo", *raw_readback("v20")],
     lambda w: w ^ RAW_SIGN,
     {"sign_cleared": lambda w: (w ^ RAW_SIGN) & 0x7fffffff, "payload_zeroed": lambda w: (w ^ RAW_SIGN) & 0xff800000,
      "unselected": lambda w: w}),
    # Scalar and vector move chains with no arithmetic: the word must arrive unchanged, and the select picks it.
    ("move_chain",
     ["s_mov_b32 s48, s44", "s_mov_b32 s49, s48", "v_mov_b32_e32 v18, s49", "v_mov_b32_e32 v19, v18",
      "v_cmp_class_f32_e64 vcc_lo, s46, 0x3ff", "v_cndmask_b32_e32 v20, 0, v19, vcc_lo", *raw_readback("v20")],
     lambda w: w,
     {"sign_cleared": lambda w: w & 0x7fffffff, "quieted": lambda w: w | 0x400000, "payload_zeroed": lambda w: w & 0xff800000,
      "sign_flipped": lambda w: w ^ RAW_SIGN}),
    # The shape that failed on hardware: the flipped word, kept whole, is ANDed with a mask read from the buffer.
    ("xor_and_mask", ["v_xor_b32_e64 v19, 0x80000000, s44", "v_and_b32_e32 v20, s45, v19", *raw_readback("v20")],
     lambda w: (w ^ RAW_SIGN) & RAW_MASK,
     {"sign_cleared": lambda w: (w ^ RAW_SIGN) & 0x7fffffff, "canonical_nan": lambda w: 0x7fffffff if (w & 0x7fffffff) > 0x7f800000 else w ^ RAW_SIGN,
      "quieted": lambda w: ((w ^ RAW_SIGN) | 0x400000) & RAW_MASK}),
    # Setting the sign bit, and clearing it, on the word kept whole.
    ("or_sign_and_abs", ["v_or_b32_e64 v19, 0x80000000, s44", "v_and_b32_e64 v20, 0x7fffffff, s44",
                         "v_xor_b32_e32 v21, v19, v20", "v_xor_b32_e32 v22, v19, v20", "v_and_b32_e32 v23, s45, v19",
                         "v_and_b32_e32 v24, s45, v20", "v_or_b32_e32 v25, v23, v24", *raw_readback("v25")],
     lambda w: (w | RAW_SIGN) | (w & 0x7fffffff),
     {"sign_cleared": lambda w: w & 0x7fffffff, "canonical_nan": lambda w: 0x7fffffff if (w & 0x7fffffff) > 0x7f800000 else w | RAW_SIGN}),
)


def raw_word_constants(word):
    constants = bytearray(256)
    struct.pack_into("<4I", constants, 12, word, RAW_MASK, 0, 0)
    return constants


def check_raw_word_draws(directory, compiler, renderer, backend):
    case = directory / "raw.case"
    for index, (name, body, model, bugs) in enumerate(RAW_WORD_PROGRAMS):
        source = directory / f"raw{index}.hlsl"
        shader = directory / f"raw{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = {bug: False for bug in bugs}
        for word in RAW_WORDS:
            constants = raw_word_constants(word)
            expected = [float(byte(model(word), n)) for n in range(4)]
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode == 77:  # no adapter: a skip, reported by pixel_aot_check.py
                raise subprocess.CalledProcessError(77, draw, result.stdout, result.stderr)
            if result.returncode:
                raise AssertionError(f"raw word {word:#010x} through {name} is not bit-exact on {backend}: "
                                     f"{result.stdout}{result.stderr}")
            for bug, wrong in bugs.items():
                if wrong(word) == model(word):
                    continue
                separated[bug] = True
                case.write_bytes(constants + struct.pack("<4f", *[float(byte(wrong(word), n)) for n in range(4)]) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"Wrong reference {bug} escaped detection in {name}, word {word:#010x}")
        assert all(separated.values()), (name, separated)


def check_raw_word_controls():
    # The constant buffer is unsigned and no raw word in a move, select or sign flip takes a float type.
    for name, body, model, bugs in RAW_WORD_PROGRAMS:
        source = translate(with_constants(body))
        assert "uint4 params[16]" in source and "float4 params" not in source, name
        main = source.split("float4 main", 1)[1]
        if not any("v_cmp_class" in line for line in body):  # a class test reads the word as a float on purpose
            assert "asfloat(" not in main, (name, main)
    main = translate(with_constants(RAW_WORD_PROGRAMS[1][1])).split("float4 main", 1)[1]
    assert "uint movw" in main and "uint selw" in main and "= (2147483648u ^ movw" in main, main
    # A float source keeps the float move and select; a source with a modifier does too.
    main = translate(with_constants(["v_mov_b32_e32 v18, 1.0", "v_mov_b32_e32 v19, -0.5",
                                     "v_cmp_class_f32_e64 vcc_lo, s46, 0x3ff", "v_cndmask_b32_e32 v12, 0.5, 1.0, vcc_lo",
                                     "v_cndmask_b32_e64 v13, -v18, |v19|, vcc_lo"])).split("float4 main", 1)[1]
    assert "float alu20 = 1.0f;" in main and "float alu21 = (-0.5f);" in main and "movw" not in main, main
    assert "float alu23 = cmp22 ? 1.0f : 0.5f;" in main and "float alu24 = cmp22 ?" in main and "selw" not in main, main
    # A raw word moved into a destination keeps working as the tracked kept half of a 16-bit result.
    main = translate(with_constants(["v_mov_b32_e32 v18, s44", "v_cvt_f16_f32_e32 v18, s45"])).split("float4 main", 1)[1]
    assert "(movw20 & 0xffff0000u) | narrow16(" in main, main
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, v19"]))
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, s60"]))
    must_reject(translate, with_constants(["v_cndmask_b32_e32 v18, s44, v19, vcc_lo"]))


def controls(directory):
    check_raw_word_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for _, body, *_ in RAW_WORD_PROGRAMS),
    ]


draw = check_raw_word_draws
