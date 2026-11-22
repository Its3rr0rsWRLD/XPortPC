"""Exercise offline pixel translation with independently assembled test programs."""
from pathlib import Path
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pixel_aot
from pixel_aot import disassemble, native_program
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pixel_memory_check as titlemem

# First word of each line of every program lower() accepted in this run. tools/form_coverage.py counts
# these when this test passes; a program a check expects to be rejected raises before it is recorded.
ACCEPTED = set()


def lower(instructions, *args, **kwargs):
    source = pixel_aot.lower(instructions, *args, **kwargs)
    ACCEPTED.update(line.split()[0] for line in instructions if line.strip())
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


DUAL_CASES = ("forward", "reverse", "reuse")


def dual_program(case="forward", *, swap_weights=False):
    program = assembly(False)
    first = next(i for i, line in enumerate(program) if line.startswith("image_sample"))
    sample_a = program[first]
    sample_b = sample_a.replace("v[12:15]", "v[20:23]").replace("s[28:35]", "s[56:63]")
    load_b = "s_load_dwordx8 s[56:63], s[20:21], 0x20"
    if case == "reuse":
        # Finish A before reloading the same descriptor registers for B.
        program[first:first+1] = [sample_a, "s_waitcnt vmcnt(0)",
                                  load_b.replace("56:63", "28:35"), "s_waitcnt lgkmcnt(0)",
                                  sample_b.replace("56:63", "28:35")]
    elif case in ("forward", "reverse"):
        program[first:first+1] = [sample_a, sample_b] if case == "forward" else [sample_b, sample_a]
        program.insert(program.index("s_mov_b32 s40, 1"), load_b)
    else:
        raise ValueError(f"Unknown dual-texture case: {case}")
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    a, b = ("0x3e800000", "0x3f400000") if swap_weights else ("0x3f400000", "0x3e800000")
    ops = []
    for i in range(4):
        ops.extend([f"v_mul_legacy_f32_e32 v{12+i}, {a}, v{12+i}",
                    f"v_fma_f32 v{12+i}, {b}, v{20+i}, v{12+i}"])
    program[pos:pos] = ops
    return program


def translate_dual(instructions):
    return lower(instructions, 20, 24, [1, 2, 3, 4], second_texture_offset=32)


def shader_record(blob: bytes, name: bytes) -> bytes:
    encoder = zlib.compressobj(wbits=-15)
    payload = encoder.compress(blob) + encoder.flush()
    return (bytes([len(name) + 1]) + name + b"\0\0"
            + struct.pack("<4I", len(payload), 0, len(payload), len(blob)) + payload)


def envelope(code: bytes, name: bytes = b"fixture", *, private_data: bytes | None = None) -> bytes:
    program_start = 256
    image = bytearray(program_start) + code
    image[:4] = b"FSSM"
    struct.pack_into("<I", image, 192, program_start - 40)
    native = b"XBCH" + bytes(12) + struct.pack("<II", len(image), 0) + zlib.compress(image)
    program = (bytes(24) + b"XDAT" + struct.pack("<II", 1, 0)
               + struct.pack("<III", 13, 48, len(native)) + native)
    sections = [b"DXIL" + struct.pack("<I", len(program)) + program]
    if private_data is not None:
        sections.append(b"PRIV" + struct.pack("<I", len(private_data)) + private_data)
    offset = 32 + 4 * len(sections)
    offsets = bytearray()
    for section in sections:
        offsets.extend(struct.pack("<I", offset))
        offset += len(section)
    blob = b"DXBC" + bytes(16) + struct.pack("<3I", 1, offset, len(sections)) + offsets + b"".join(sections)
    return shader_record(blob, name)


def must_reject(function, *args):
    try:
        function(*args)
    except (ValueError, KeyError):
        return
    raise AssertionError(f"{function.__name__} accepted invalid input")


def check_container_selector(directory: Path, code: bytes, library: str | None = None) -> None:
    archive = directory / "same-name.rpf"
    records = [envelope(code, private_data=metadata) for metadata in (b"first", b"second")]
    containers = []
    for record in records:
        archive.write_bytes(record)
        container, native = native_program(archive, "fixture")
        assert native == code
        containers.append(container)
    digests = [hashlib.sha256(blob).hexdigest() for blob in containers]
    first, second = records
    broken = b"\x08fixture\0\0" + struct.pack("<4I", 2, 0, 2, 8) + b"\x07\xff"
    archive.write_bytes(first + second)
    must_reject(native_program, archive, "fixture")
    for digest, blob in zip(digests, containers, strict=True):
        assert native_program(archive, "fixture", container_sha256=digest.upper()) == (blob, code)

    for order in (broken + first, first + broken):
        archive.write_bytes(order)
        assert native_program(archive, "fixture", container_sha256=digests[0]) == (containers[0], code)
    # A bad frame can claim bytes covering a subsequent record of the same name.
    archive.write_bytes(b"\x08fixture\0\0" + struct.pack("<4I", len(first) + 2, 0, len(first) + 2, 8)
                        + b"\x07\xff" + first)
    assert native_program(archive, "fixture", container_sha256=digests[0]) == (containers[0], code)
    archive.write_bytes(first * 257 + second)
    assert native_program(archive, "fixture", container_sha256=digests[1]) == (containers[1], code)

    archive.write_bytes(envelope(code))
    intact, _ = native_program(archive, "fixture")
    corrupt = intact[:-1] + bytes([intact[-1] ^ 1])
    archive.write_bytes(first + shader_record(corrupt, b"fixture"))
    try:
        native_program(archive, "fixture", container_sha256=hashlib.sha256(corrupt).hexdigest())
    except zlib.error as error:
        assert "incorrect data check" in str(error), error
    else:
        raise AssertionError("Container selection hid a corrupt native stream")

    for contents, digest, reason in (
        (first + second, hashlib.sha256(code).hexdigest(), "No record matches the name and container SHA-256"),
        (first + second, "bad", "Invalid decoded container SHA-256"),
        (first + broken + first + second, digests[0], "Multiple records match the name and container SHA-256"),
    ):
        archive.write_bytes(contents)
        try:
            native_program(archive, "fixture", container_sha256=digest)
        except ValueError as error:
            assert str(error) == reason, error
        else:
            raise AssertionError("Container selection accepted an invalid digest or ambiguous record")

    if library is None:
        return
    archive.write_bytes(first + second)
    output = directory / "selected.hlsl"
    command = [sys.executable, "-B", Path(pixel_aot.__file__), archive, "fixture", "--llvm", library,
               "--texture-sgpr", "20", "--interp-sgpr", "24", "--sampler-words", "1", "2", "3", "4",
               "--output", output]
    ambiguous = subprocess.run(command, capture_output=True, text=True)
    assert ambiguous.returncode == 1 and "Multiple records match the name" in ambiguous.stderr
    for digest in digests:
        result = subprocess.run([*command, "--container-sha256", digest], capture_output=True, text=True, check=True)
        summary = json.loads(result.stdout)
        assert summary["container_sha256"] == digest
        assert summary["native_sha256"] == hashlib.sha256(code).hexdigest()
        assert output.read_text(encoding="utf-8") == lower(assembly(False), 20, 24, [1, 2, 3, 4])
    wrong = subprocess.run([*command, "--container-sha256", "0" * 64], capture_output=True, text=True)
    assert wrong.returncode == 1 and "No record matches the name and container SHA-256" in wrong.stderr


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


# s_movk_i32 sign-extends its 16-bit immediate. s_bfe_u32 takes bytes 1 and 3 of each result, and each byte is
# widened as a binary16 subnormal and scaled by 2^24 to the exact integer: 0x8000 gives 0xffff8000 (bytes 0x80 and
# 0xff) and 0x7fff gives 0x00007fff (bytes 0x7f and 0x00). Zero extension would export 0 for byte 3 of 0x8000.
MOVK_BODY = [
    "s_movk_i32 s48, 0x8000",
    "s_movk_i32 s51, 0x7fff",
    "s_bfe_u32 s49, s48, 0x80018",
    "s_bfe_u32 s50, s48, 0x80008",
    "s_bfe_u32 s52, s51, 0x80008",
    "s_bfe_u32 s53, s51, 0x80018",
    *[line for channel, source in enumerate(("s49", "s50", "s52", "s53"))
      for line in (f"v_cvt_f32_f16_e32 v{12 + channel}, {source}", f"v_mul_f32_e32 v{12 + channel}, 0x4b800000, v{12 + channel}")],
]
MOVK_EXPECTED = [255.0, 128.0, 127.0, 0.0]


def check_movk_draw(directory, compiler, renderer, backend):
    source = directory / "movk.hlsl"
    shader = directory / "movk.cso"
    case = directory / "movk.case"
    words = [(imm - 0x10000 if imm & 0x8000 else imm) & 0xffffffff for imm in (0x8000, 0x7fff)]
    assert [float((words[0] >> 24) & 0xff), float((words[0] >> 8) & 0xff),
            float((words[1] >> 8) & 0xff), float((words[1] >> 24) & 0xff)] == MOVK_EXPECTED
    source.write_text(translate(with_constants(MOVK_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytes(256)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *MOVK_EXPECTED) * 64)
    subprocess.run(draw, check=True)
    # Zero extension clears byte 3 of 0x8000; sign-extending 0x7fff as negative sets byte 3.
    for channel, value in ((0, 0.0), (3, 255.0)):
        wrong = list(MOVK_EXPECTED)
        wrong[channel] = value
        case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"A wrong s_movk_i32 extension escaped detection in channel {channel}")


def with_scalar_constant_reads() -> list[str]:
    program = with_constants(["v_mov_b32_e32 v12, s61", "v_mov_b32_e32 v13, s62", "v_mov_b32_e32 v14, s63"])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc")
    program[load:load + 1] = [
        "s_buffer_load_dword s61, s[44:47], null",
        "s_buffer_load_dword s62, s[44:47], 0x8",
        "s_buffer_load_dword s63, s[44:47], 0xfc",
    ]
    return program


def curve():
    return with_constants([
        "v_max_f32_e32 v18, s46, v12",
        "v_log_f32_e32 v18, v18",
        "v_rcp_f32_e32 v19, s44",
        "v_mul_legacy_f32_e32 v18, v19, v18",
        "v_exp_f32_e32 v18, v18",
        "v_sub_f32_e32 v19, 1.0, v13",
        "v_fma_f32 v12, s45, v18, -v19",
        "v_fmac_f32_e32 v12, s47, v13",
        "v_min_f32_e32 v12, 1.0, v12",
        "v_mul_legacy_f32_e64 v12, v12, 1.0 clamp",
    ])


def shaping():
    return with_constants([
        "v_max_f32_e32 v18, s46, v12",
        "v_sqrt_f32_e32 v18, v18",
        "v_mul_f32_e32 v18, s45, v18",
        "v_add_f32_e32 v19, s44, v13",
        "v_rsq_f32_e32 v19, v19",
        "v_add_f32_e32 v18, v19, v18",
        "v_mul_f32_e32 v20, s44, v13",
        "v_floor_f32_e32 v21, v20",
        "v_fract_f32_e32 v20, v20",
        "v_fma_f32 v12, s47, v20, v18",
        "v_sub_f32_e32 v12, v12, v21",
        "v_mul_f32_e64 v12, v12, 1.0 clamp",
    ])


def truncate_values() -> list[str]:
    return with_constants([
        "v_add_f32_e32 v12, s44, v12",
        "v_trunc_f32_e32 v12, v12",
        "v_trunc_f32_e32 v13, s45",
        "v_trunc_f32_e64 v14, -|s46|",
        "v_trunc_f32_e64 v15, s47 clamp",
    ])


def select(wave64=False):
    """Compare into lane masks and select; LLVM names the masks by wavefront width."""
    vcc, first, second = ("vcc", "s[52:53]", "s[54:55]") if wave64 else ("vcc_lo", "s52", "s53")
    return with_constants([
        f"v_cmp_nlt_f32_e64 {second}, v12, v13",
        f"v_cndmask_b32_e64 v14, 0, 1.0, {second}",
        f"v_cmp_eq_f32_e32 {vcc}, v12, v13",
        f"v_cndmask_b32_e32 v15, s47, v15, {vcc}",
        f"v_cmp_lt_f32_e32 {vcc}, s44, v12",
        "v_sub_f32_e32 v18, 1.0, v12",
        f"v_cmp_ge_f32_e64 {first}, v13, s45",
        f"v_cndmask_b32_e64 v13, v13, s46, {first}",
        f"v_cndmask_b32_e32 v12, v12, v18, {vcc}",
    ])


def absolute_value():
    program = assembly(False)
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[pos:pos] = [
        "v_sub_f32_e32 v12, 0.5, v12",
        "v_sub_f32_e64 v12, |v12|, 0",
    ]
    return program


def ceiling():
    return with_constants([
        "v_ceil_f32_e32 v12, s44",
        "v_ceil_f32_e64 v13, -|s45|",
        "v_ceil_f32_e64 v14, |s46|",
        "v_ceil_f32_e64 v15, |s47| clamp",
    ])


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


# v_cmp_class_f32 is true when the class of S0 is in the mask S1 (LLVM SIInstrFlags::ClassFlags).
# Each channel tests one property: +inf against its own bit, a quiet NaN against both NaN bits,
# -0 against the +0 bit and a positive denormal against its bit, so neither the sign of zero
# nor a denormal flushed to zero can pass.
CLASS_BITS = (0x7f800000, 0x7fc00000, 0x80000000, 0x00000001)
CLASS_BODY = [
    "v_mov_b32_e32 v19, 1.0",
    "v_cmp_class_f32_e64 vcc_lo, s44, 0x200",
    "v_cndmask_b32_e32 v12, 0, v19, vcc_lo",
    "v_cmp_class_f32_e64 vcc_lo, s45, 3",
    "v_cndmask_b32_e32 v13, 0, v19, vcc_lo",
    "v_mov_b32_e32 v18, 64",
    "v_cmp_class_f32_e32 vcc_lo, s46, v18",
    "v_cndmask_b32_e32 v14, 0, v19, vcc_lo",
    "v_cmp_class_f32_e64 s0, s47, 0x80",
    "v_cndmask_b32_e64 v15, 0, v19, s0",
]


def check_class_draw(directory, compiler, renderer, backend):
    source = directory / "class.hlsl"
    shader = directory / "class.cso"
    case = directory / "class.case"
    source.write_text(translate(with_constants(CLASS_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytearray(256)
    struct.pack_into("<4I", constants, 12, *CLASS_BITS)
    expected = [1.0, 1.0, 0.0, 1.0]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
    subprocess.run(draw, check=True)
    # A wrong class in any channel flips its result; the renderer must report each flip.
    for k in range(4):
        wrong_values = list(expected)
        wrong_values[k] = 1.0 - wrong_values[k]
        case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"A wrong class result escaped detection in channel {k}")


# v_fract_f32 clamps x - floor(x) to 0x3f7fffff. For -2**-30 the unclamped difference rounds to 1.0;
# the other inputs are exact and stay below the clamp.
FRACT_INPUTS = (-2.0 ** -30, -0.25, 2.75, -2.0 ** -23)
FRACT_CLAMP = struct.unpack("<f", struct.pack("<I", 0x3f7fffff))[0]


# VOP3 (e64) encodings that the translator already accepts but no other fixture draws: floor, fract, max, min and
# fmac with source modifiers, and the 16 comparisons writing an SGPR mask from negated operands. Negating both
# operands swaps the less and greater relations and keeps equality and unordered.
E64_ARITH = (
    (["v_floor_f32_e64 v12, -|s44|", "v_fract_f32_e64 v13, -s45",
      "v_max_f32_e64 v14, -s46, |s47|", "v_min_f32_e64 v15, s46, -|s47|"],
     [-3.0, 0.75, 4.0, -4.0], ((0, 2.0), (1, 0.25), (2, -3.0), (3, 3.0))),
    (["v_mov_b32_e32 v12, s46", "v_fmac_f32_e64 v12, -s44, |s45|",
      "v_mov_b32_e32 v13, 0", "v_mov_b32_e32 v14, 0", "v_mov_b32_e32 v15, 0"],
     [-0.125, 0.0, 0.0, 0.0], ((0, 6.125),)),
)
E64_ARITH_INPUTS = (2.5, 1.25, 3.0, -4.0)


def predicate_group_e64(first):
    body = ["v_sub_f32_e64 v18, s45, 0", "v_sub_f32_e64 v19, s47, 0"]
    for channel, op in enumerate(PREDICATES[first:first + 4]):
        body.extend([f"v_cmp_{op}_f32_e64 s0, -s44, -v18", f"v_cndmask_b32_e64 v{12 + channel}, 0, v19, s0"])
    return with_constants(body)


def check_e64_draws(directory, compiler, renderer, backend):
    source = directory / "e64.hlsl"
    shader = directory / "e64.cso"
    case = directory / "e64.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    x, y, z, w = E64_ARITH_INPUTS
    assert [math.floor(-abs(x)), -y - math.floor(-y), max(-z, abs(w)), min(z, -abs(w))] == E64_ARITH[0][1]
    assert [-x * abs(y) + z, 0.0, 0.0, 0.0] == E64_ARITH[1][1]
    for body, expected, wrongs in E64_ARITH:
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        constants = bytearray(256)
        struct.pack_into("<4f", constants, 12, *E64_ARITH_INPUTS)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
        for channel, value in wrongs:
            wrong_values = list(expected)
            wrong_values[channel] = value
            case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong e64 result escaped detection in channel {channel}")
    inputs = ((-1, 1, 0), (-0.0, 0.0, 1), (1, -1, 2), (math.nan, 1, 3), (1, math.nan, 3))
    negated = {0: 2, 1: 1, 2: 0, 3: 3}
    for first in range(0, 16, 4):
        source.write_text(translate(predicate_group_e64(first)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        for left, right, relation in inputs:
            constants = bytearray(256)
            struct.pack_into("<4f", constants, 12, left, right, 0, 1)
            expected = [float((op >> negated[relation]) & 1) for op in range(first, first + 4)]
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            # A lowering that dropped the negations would follow the original relation.
            unnegated = [float((op >> relation) & 1) for op in range(first, first + 4)]
            if unnegated != expected:
                case.write_bytes(constants + struct.pack("<4f", *unnegated) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"Dropped e64 negation escaped detection, first={first}, left={left}")


def check_fract_draw(directory, compiler, renderer, backend):
    source = directory / "fract.hlsl"
    shader = directory / "fract.cso"
    case = directory / "fract.case"
    program = with_constants([f"v_fract_f32_e32 v{12 + i}, s{44 + i}" for i in range(4)])
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, *FRACT_INPUTS)
    expected = [min(single(x - math.floor(x)), FRACT_CLAMP) for x in FRACT_INPUTS]
    assert expected[0] == FRACT_CLAMP and single(FRACT_INPUTS[0] - math.floor(FRACT_INPUTS[0])) == 1.0
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *map(half_rtz, expected)) * 64)
    subprocess.run(draw, check=True)
    # An unclamped fract exports 1.0 for the first input; the renderer must tell it from the clamp.
    case.write_bytes(constants + struct.pack("<4f", 1.0, *map(half_rtz, expected[1:])) * 64)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("An unclamped fract result escaped detection")


# v_mad_f32 and v_mac_f32 round the product before the add and flush binary32 denormals.
# 4097 * 4097 = 2**24 + 2**13 + 1 rounds to 2**24 + 2**13, so the unfused sum is 0 where a fused one is 1.0.
# 2**-127 is a denormal input: flushed, the second sum is 0.5; preserved, it is 1.0.
MAD_INPUTS = (4097.0, -16785408.0, 2.0 ** -127, 2.0 ** 126)
MAD_BODY = [
    "v_mad_f32 v12, s44, s44, s45",
    "v_mov_b32_e32 v13, s47",
    "v_mad_f32 v13, s46, v13, 0.5",
    "v_mov_b32_e32 v15, s44",
    "v_mov_b32_e32 v14, s45",
    "v_mac_f32_e32 v14, s44, v15",
    "v_mad_f32 v15, 0.5, 4.0, 0.5",
]


def check_mad_draw(directory, compiler, renderer, backend):
    source = directory / "mad.hlsl"
    shader = directory / "mad.cso"
    case = directory / "mad.case"
    source.write_text(translate(with_constants(MAD_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, *MAD_INPUTS)
    a, c, tiny, large = MAD_INPUTS
    unfused = single(single(a * a) + c)
    assert unfused == 0.0 and single(a * a + c) == 1.0
    assert single(tiny) == tiny and 0 < tiny < 2.0 ** -126 and single(tiny * large) == 0.5
    expected = [unfused, 0.5, unfused, 2.5]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *map(half_rtz, expected)) * 64)
    subprocess.run(draw, check=True)
    # A fused multiply-add or a denormal-preserving one exports 1.0; the renderer must tell each case apart.
    for wrong_values in ([1.0, 0.5, unfused, 2.5], [unfused, 1.0, unfused, 2.5], [unfused, 0.5, 1.0, 2.5]):
        case.write_bytes(constants + struct.pack("<4f", *map(half_rtz, wrong_values)) * 64)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"A fused or denormal-preserving result escaped detection: {wrong_values}")


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


# The SDWA comparisons with whole-dword selections repeat the 16-predicate draws, including NaN on either side.
# For each group a reference that inverts the unordered (NaN) result must report a mismatch.
def check_sdwa_predicate_draws(directory, compiler, renderer, backend):
    source = directory / "sdwa_predicates.hlsl"
    shader = directory / "sdwa_predicates.cso"
    case = directory / "sdwa_predicates.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    inputs = ((-1, 1, 0), (-0.0, 0.0, 1), (1, -1, 2), (math.nan, 1, 3), (1, math.nan, 3))
    for first in range(0, 16, 4):
        source.write_text(translate(predicate_group(first, sdwa=True)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        for left, right, relation in inputs:
            constants = bytearray(256)
            struct.pack_into("<4f", constants, 12, left, right, 0, 1)
            expected = [float((op >> relation) & 1) for op in range(first, first + 4)]
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
        wrong = [1.0 - value for value in expected]
        case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"An inverted unordered SDWA comparison escaped detection, first={first}")


def half_rtz(x):
    bits, = struct.unpack("<H", struct.pack("<e", x))
    rounded, = struct.unpack("<e", struct.pack("<H", bits))
    return struct.unpack("<e", struct.pack("<H", bits - (abs(rounded) > abs(x))))[0]


# v_cvt_f32_f16 widens the binary16 in the low half of S0; the high half holds junk that must be ignored.
# The second channel applies -|x| to -5.0, the third is the largest finite half and the fourth is the
# smallest subnormal half, 2**-24, scaled by 2**24 so a flushed subnormal exports 0 instead of 1.0.
HALF_WORDS = (0xdead3c00, 0x0000c500, 0x00007bff, 0xbeef0001)
HALF_BODY = [
    "v_cvt_f32_f16_e32 v12, s44",
    "v_cvt_f32_f16_e64 v13, -|s45|",
    "v_cvt_f32_f16_e32 v14, s46",
    "v_cvt_f32_f16_e32 v15, s47",
    "v_mul_f32_e32 v15, 0x4b800000, v15",
]


def half_value(word):
    return struct.unpack("<e", struct.pack("<H", word & 0xffff))[0]


def check_half_draw(directory, compiler, renderer, backend):
    source = directory / "half.hlsl"
    shader = directory / "half.cso"
    case = directory / "half.case"
    source.write_text(translate(with_constants(HALF_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytearray(256)
    struct.pack_into("<4I", constants, 12, *HALF_WORDS)
    first, second, third, fourth = map(half_value, HALF_WORDS)
    expected = [first, -abs(second), third, fourth * 2.0 ** 24]
    assert expected == [1.0, -5.0, 65504.0, 1.0] and fourth == 2.0 ** -24
    # Reading the high half, dropping the negation, a wrong exponent and a flushed subnormal.
    wrong = [half_value(HALF_WORDS[0] >> 16), 5.0, 32752.0, 0.0]
    for x in (*expected, *wrong):
        assert half_rtz(x) == x, x
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
    subprocess.run(draw, check=True)
    for k in range(4):
        wrong_values = list(expected)
        wrong_values[k] = wrong[k]
        case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"A wrong half conversion escaped detection in channel {k}")


# v_cvt_f16_f32 rounds to nearest even and, on GFX10, writes only the low half of the destination. Channels 0
# and 1 read the whole word: v12 starts as 1.0, so after the conversion it is 1 + h * 2^-23 when the high half
# is kept, and (v12 - 1) * 2^23 splits into the low and high bytes of the binary16 encoding h. Channel 2
# widens -|S0| back to binary32 and channel 3 widens a subnormal result scaled by 2^24. Each set lists wrong
# references (channel, value) for the property it isolates.
NARROW_BODY = [
    "v_mov_b32_e32 v12, 1.0",
    "v_cvt_f16_f32_e32 v12, s44",
    "v_subrev_f32_e32 v12, 1.0, v12",
    "v_mul_f32_e32 v12, 0x4b000000, v12",
    "v_mul_f32_e32 v13, 0x3b800000, v12",
    "v_floor_f32_e32 v13, v13",
    "v_fmac_f32_e32 v12, 0xc3800000, v13",
    "v_cvt_f16_f32_e64 v14, -|s45|",
    "v_cvt_f32_f16_e32 v14, v14",
    "v_cvt_f16_f32_e32 v15, s46",
    "v_cvt_f32_f16_e32 v15, v15",
    "v_mul_f32_e32 v15, 0x4b800000, v15",
]
NARROW_SETS = (
    # Ties to even in the normal range and at the smallest subnormal.
    ((1 + 2.0 ** -11, 1 + 3 * 2.0 ** -11, 1.5 * 2.0 ** -24), ((0, 1.0), (2, -(1 + 2.0 ** -10)), (3, 1.0))),
    # The largest value below the overflow tie, -0, and the tie between zero and 2^-24.
    ((65520 - 2.0 ** -8, -0.0, 2.0 ** -25), ((1, 124.0), (2, 0.0), (3, 1.0))),
    # The overflow tie gives infinity; rounding carries a subnormal into the smallest normal; a negative subnormal.
    ((65520.0, 2.0 ** -14 - 2.0 ** -25, -3 * 2.0 ** -24), ((1, 123.0), (2, -1023 * 2.0 ** -24), (3, 3.0))),
    # A negative subnormal encoding, the negation modifier and a binary32 subnormal input.
    ((-3 * 2.0 ** -24, 3.0, 2.0 ** -149), ((1, 0.0), (2, 3.0))),
)


def narrow_reference(x):
    if abs(x) >= 65520:
        return 0xfc00 if x < 0 else 0x7c00
    return struct.unpack("<H", struct.pack("<e", x))[0]


def check_narrow_draw(directory, compiler, renderer, backend):
    source = directory / "narrow.hlsl"
    shader = directory / "narrow.cso"
    case = directory / "narrow.case"
    source.write_text(translate(with_constants(NARROW_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    for inputs, wrongs in NARROW_SETS:
        words = [struct.unpack("<I", struct.pack("<f", x))[0] for x in inputs]
        assert [struct.unpack("<f", struct.pack("<I", w))[0] for w in words] == list(inputs)
        constants = bytearray(256)
        struct.pack_into("<3I", constants, 12, *words)
        h = narrow_reference(inputs[0])
        expected = [float(h & 0xff), float(h >> 8), -abs(half_value(narrow_reference(-abs(inputs[1])))),
                    half_value(narrow_reference(inputs[2])) * 2.0 ** 24]
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
                raise AssertionError(f"A wrong narrowing escaped detection for {inputs} in channel {channel}")


def arithmetic():
    """Add, multiply, reversed subtraction and moves on the sample and constant words 8 to 11."""
    program = assembly(False)
    pos = program.index("s_mov_b32 s40, 1")
    program.insert(pos, "s_load_dwordx4 s[44:47], s[20:21], 0x40")
    pos = program.index("s_waitcnt vmcnt(0)")
    program[pos:pos] = [
        "s_buffer_load_dwordx4 s[44:47], s[44:47], 0x20",
        "s_waitcnt lgkmcnt(0)",
    ]
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[pos:pos] = [
        "v_mov_b32_e32 v18, v12",
        "v_mul_f32_e32 v18, s44, v18",
        "v_add_f32_e64 v12, v18, s45 clamp",
        "v_mov_b32_e64 v19, s46",
        "v_subrev_f32_e32 v19, v13, v19",
        "v_mul_f32_e64 v19, v19, -2.0",
        "v_subrev_f32_e64 v13, s47, v19 clamp",
        "v_add_f32_e32 v14, -0.5, v14",
        "v_mov_b32_e32 v20, 0x3e800000",
        "v_mul_f32_e32 v20, v20, v18",
        "v_mov_b32_e32 v15, v20",
    ]
    return program


def arithmetic_case(directory, *constants):
    """Expected colors for arithmetic(). Each step must be exact in binary32, so neither the
    rounding of add, subtract and multiply nor fusion can change the result."""
    def exact(value):
        rounded, = struct.unpack("<f", struct.pack("<f", value))
        assert rounded == value, value
        return rounded
    scale, bias, pivot, offset = map(exact, constants)
    case = bytearray(256)
    struct.pack_into("<4f", case, 32, scale, bias, pivot, offset)
    ramp = (0, 16, 37, 64, 101, 153, 219, 254)
    for y in ramp:
        for x in ramp:
            r, g, b = (struct.unpack("<f", struct.pack("<f", c / 255))[0] for c in (x, y, 128))
            scaled = exact(scale * r)
            red = min(1, max(0, exact(scaled + bias)))
            green = min(1, max(0, exact(exact(exact(pivot - g) * -2.0) - offset)))
            color = (red, green, exact(-0.5 + b), exact(0.25 * scaled))
            case.extend(struct.pack("<4f", *map(half_rtz, color)))
    path = directory / "arithmetic.case"
    path.write_bytes(case)
    return path


def curve_case(directory, gain):
    gamma, floor, mix = 2.0, .125, .25
    case = bytearray(256)
    struct.pack_into("<4f", case, 12, gamma, gain, floor, mix)
    for y in RAMP:
        for x in RAMP:
            g = y / 255
            r = gain * math.sqrt(max(floor, x / 255)) - (1 - g) + mix * g
            case.extend(struct.pack("<4f", half_rtz(min(1, max(0, r))), half_rtz(g), half_rtz(128/255), 1))
    path = directory / "curve.case"
    path.write_bytes(case)
    return path


def shaping_case(directory, gain):
    scale, floor, mix = 2.0, .125, .25
    case = bytearray(256)
    struct.pack_into("<4f", case, 12, scale, gain, floor, mix)
    for y in RAMP:
        for x in RAMP:
            g = y / 255
            scaled = scale * g
            r = (gain * math.sqrt(max(floor, x / 255))
                 + 1.0 / math.sqrt(scale + g)
                 + mix * (scaled - math.floor(scaled))
                 - math.floor(scaled))
            case.extend(struct.pack("<4f", half_rtz(min(1, max(0, r))), half_rtz(g), half_rtz(128/255), 1))
    path = directory / "shaping.case"
    path.write_bytes(case)
    return path


def truncate_case(directory: Path, bias: float, green: float, blue: float, alpha: float) -> Path:
    case = bytearray(256)
    struct.pack_into("<4f", case, 12, bias, green, blue, alpha)
    # modf returns the integer component as a float and preserves the sign of zero.
    green = math.modf(green)[1]
    blue = math.modf(-abs(blue))[1]
    alpha = max(0.0, min(1.0, math.modf(alpha)[1]))
    for _ in RAMP:
        for x in RAMP:
            red = math.modf(bias + x / 255)[1]
            case.extend(struct.pack("<4f", red, green, blue, alpha))
    path = directory / "truncate.case"
    path.write_bytes(case)
    return path


def absolute_case(directory):
    case = bytearray(256)
    for y in RAMP:
        for x in RAMP:
            red = abs(0.5 - x / 255)
            case.extend(struct.pack("<4f", half_rtz(red), half_rtz(y / 255), half_rtz(128 / 255), 1))
    path = directory / "absolute.case"
    path.write_bytes(case)
    return path


def single(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def select_case(directory, fold, limit, capped, unequal):
    """Expected colors for select(): every step is exact in binary32, so no device tolerance applies."""
    case = bytearray(256)
    struct.pack_into("<4f", case, 12, fold, limit, capped, unequal)
    ramp = (0, 16, 37, 64, 101, 153, 219, 254)
    for y in ramp:
        for x in ramp:
            r, g = single(x / 255), single(y / 255)
            color = (single(1 - r) if fold < r else r, capped if g >= limit else g,
                     0.0 if r < g else 1.0, 1.0 if r == g else unequal)
            case.extend(struct.pack("<4f", *map(half_rtz, color)))
    path = directory / "select.case"
    path.write_bytes(case)
    return path


# v_cube{id,sc,tc,ma}_f32 follow LLVM's ConstantFoldAMDGCNCubeIntrinsic. The direction sets cover all
# six faces, the y/x and z/x ties (the later axis in z, y, x order wins) and -0 on the major axis,
# which selects the positive face. Each set has one wrong reference for the property it isolates.
CUBE_BODY = [
    "v_mov_b32_e32 v18, s45",
    "v_mov_b32_e32 v19, s46",
    "v_cubeid_f32 v12, s44, v18, v19",
    "v_cubesc_f32 v13, s44, v18, v19",
    "v_cubetc_f32 v14, s44, v18, v19",
    "v_cubema_f32 v15, s44, v18, v19",
]
CUBE_SETS = (
    ((2.0, -2.0, 1.0), (0, 1.0)),
    ((-1.5, 0.25, -1.5), (0, 1.0)),
    ((-3.0, 1.0, 2.0), (3, 6.0)),
    ((0.0, 0.0, -0.0), (0, 5.0)),
    ((1.0, 0.5, -0.25), (1, -0.25)),
    ((0.25, 1.0, 0.5), (2, -0.5)),
)


def cube_reference(x, y, z):
    if abs(z) >= abs(x) and abs(z) >= abs(y):
        face, sc, tc, ma = (5.0, -x, -y, z) if z < 0 else (4.0, x, -y, z)
    elif abs(y) >= abs(x):
        face, sc, tc, ma = (3.0, x, -z, y) if y < 0 else (2.0, x, z, y)
    else:
        face, sc, tc, ma = (1.0, z, -y, x) if x < 0 else (0.0, -z, -y, x)
    return [face, sc, tc, ma + ma]


def check_cube_draw(directory, compiler, renderer, backend):
    source = directory / "cube.hlsl"
    shader = directory / "cube.cso"
    case = directory / "cube.case"
    source.write_text(translate(with_constants(CUBE_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    faces = set()
    for direction, (channel, wrong_value) in CUBE_SETS:
        constants = bytearray(256)
        struct.pack_into("<3f", constants, 12, *direction)
        expected = cube_reference(*direction)
        faces.add(expected[0])
        assert all(half_rtz(x) == x for x in (*expected, wrong_value)) and wrong_value != expected[channel]
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
        wrong_values = list(expected)
        wrong_values[channel] = wrong_value
        case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"A wrong cube result escaped detection for {direction}")
    assert faces == {0.0, 1.0, 2.0, 3.0, 4.0, 5.0}
    assert math.copysign(1.0, cube_reference(0.0, 0.0, -0.0)[3]) < 0


SCALAR64_SETS = (
    # (a_lo, a_hi, b_lo, b_hi, sh_lo, sh_hi, bfm_w, bfm_off, bfe_src, bfe_ctrl_a, bfe_ctrl_b, alt)
    (0x89abcdef, 0x91234567, 0x55aa55aa, 0x7fffffff, 5, 37, 12, 28, 0x9a345f50, 0x00080004, 0x00100018, 0x55aa55aa),
    (0x0000a5a5, 0x0f0f0000, 0xffff5a5a, 0xf0f0ffff, 0, 100, 40, 16, 0x9a345f50, 0x00000000, 0x00000000, 0x00000000),
)


def scalar64():
    """Exercise 64-bit SOP1/SOP2 scalar ALU and 32-bit BFE, packing 40 output bits into exact binary16 floats."""
    program = assembly(False)
    pos = program.index("s_mov_b32 s40, 1")
    program.insert(pos, "s_load_dwordx4 s[44:47], s[20:21], 0x40")
    pos = program.index("s_waitcnt vmcnt(0)")
    program[pos:pos] = [
        "s_buffer_load_dwordx4 s[52:55], s[44:47], 0x10",
        "s_buffer_load_dwordx4 s[56:59], s[44:47], 0x20",
        "s_buffer_load_dwordx4 s[60:63], s[44:47], 0x30",
        "s_waitcnt lgkmcnt(0)",
    ]

    body = [
        "s_mov_b32 s64, 0",
        "s_mov_b32 s65, 0",
        "s_mov_b32 s66, 0",
        "s_mov_b32 s67, 0",
        "s_mov_b32 s78, 0",
        "s_mov_b32 s79, 0",
        "s_mov_b32 s82, s63",
        "s_mov_b32 s83, 0",
    ]

    def capture_scc(bit_index):
        body.extend([
            "s_mov_b32 s70, 0",
            "s_mov_b32 s71, 0",
            f"s_bfm_b64 s[74:75], 1, {bit_index}",
            "s_cmov_b64 s[70:71], s[74:75]",
            "s_or_b64 s[66:67], s[66:67], s[70:71]",
        ])

    def mix_acc(pair):
        body.extend([
            "s_lshl_b64 s[68:69], s[64:65], 3",
            "s_lshr_b64 s[64:65], s[64:65], 61",
            "s_or_b64 s[64:65], s[64:65], s[68:69]",
            f"s_xor_b64 s[64:65], s[64:65], {pair}",
        ])

    # Bit 0: s_and_b64 + two consecutive s_cmov_b64 (inline -1 sign-extended and SCC preserved).
    body.extend([
        "s_and_b64 s[72:73], s[52:53], s[54:55]",
        "s_cmov_b64 s[78:79], -1",
    ])
    capture_scc(0)
    mix_acc("s[72:73]")
    mix_acc("s[78:79]")

    # Bit 1: s_or_b64 (full 64-bit union saved in s[84:85] + SCC probe on s[82:83]).
    body.append("s_or_b64 s[84:85], s[52:53], s[54:55]")
    mix_acc("s[84:85]")
    body.append("s_or_b64 s[72:73], s[82:83], 0")
    capture_scc(1)

    # Bit 2: s_xor_b64 (register pair and zero-extended 32-bit hex literal).
    body.append("s_xor_b64 s[72:73], s[52:53], s[54:55]")
    mix_acc("s[72:73]")
    body.append("s_xor_b64 s[72:73], s[82:83], 0x55aa55aa")
    capture_scc(2)
    mix_acc("s[72:73]")

    # Bit 3: s_andn2_b64 (register pair + SCC probe).
    body.append("s_andn2_b64 s[72:73], s[52:53], s[54:55]")
    mix_acc("s[72:73]")
    body.append("s_andn2_b64 s[72:73], s[82:83], 0xf0f0f0f")
    capture_scc(3)

    # Bit 4: s_orn2_b64 (register pair + inline -1 proving 64-bit all-ones inversion).
    body.append("s_orn2_b64 s[72:73], s[52:53], s[54:55]")
    mix_acc("s[72:73]")
    body.append("s_orn2_b64 s[72:73], s[82:83], -1")
    capture_scc(4)

    # Bit 5: s_not_b64 + s_brev_b64 (s_brev_b64 placed before capture_scc to verify SCC preservation).
    body.append("s_not_b64 s[72:73], s[52:53]")
    mix_acc("s[72:73]")
    body.extend([
        "s_not_b64 s[72:73], s[84:85]",
        "s_brev_b64 s[86:87], s[52:53]",
    ])
    capture_scc(5)
    mix_acc("s[86:87]")

    # Bit 6: s_lshl_b64 across small/zero and >=32/wrapped shift counts.
    body.append("s_lshl_b64 s[72:73], s[52:53], s56")
    mix_acc("s[72:73]")
    body.append("s_lshl_b64 s[72:73], s[52:53], s57")
    mix_acc("s[72:73]")
    body.append("s_lshl_b64 s[72:73], s[82:83], s57")
    capture_scc(6)

    # Bit 7: s_lshr_b64 across small/zero and >=32/wrapped shift counts.
    body.append("s_lshr_b64 s[72:73], s[52:53], s56")
    mix_acc("s[72:73]")
    body.append("s_lshr_b64 s[72:73], s[52:53], s57")
    mix_acc("s[72:73]")
    body.append("s_lshr_b64 s[72:73], s[82:83], s56")
    capture_scc(7)

    # Bit 8: s_ashr_i64 (signed) + s_bfm_b64 (preserving SCC, plus w=0 and w=32 boundaries).
    body.append("s_ashr_i64 s[72:73], s[52:53], s56")
    mix_acc("s[72:73]")
    body.append("s_ashr_i64 s[72:73], s[52:53], s57")
    mix_acc("s[72:73]")
    body.extend([
        "s_ashr_i64 s[72:73], s[82:83], s56",
        "s_bfm_b64 s[86:87], s58, s59",
    ])
    capture_scc(8)
    mix_acc("s[86:87]")
    body.append("s_bfm_b64 s[88:89], 0, 5")
    mix_acc("s[88:89]")
    body.append("s_bfm_b64 s[88:89], 32, 16")
    mix_acc("s[88:89]")

    # Bit 9: s_bfe_u32 (SCC observed via s_cmov_b64 into acc) and s_bfe_i32 (SCC observed in bit 9).
    body.extend([
        "s_mov_b32 s78, 0",
        "s_mov_b32 s79, 0",
        "s_bfe_u32 s72, s60, s61",
        "s_cmov_b64 s[78:79], 0x13572468",
        "s_bfe_u32 s73, s60, s62",
    ])
    mix_acc("s[72:73]")
    mix_acc("s[78:79]")
    body.extend([
        "s_bfe_i32 s72, s60, s61",
        "s_bfe_i32 s73, s60, s62",
    ])
    capture_scc(9)
    mix_acc("s[72:73]")

    # Fold all 64 bits of acc into bits [29:0] of s64, then export 4 x 10-bit fields as 1 + k/1024.
    body.extend([
        "s_lshr_b64 s[68:69], s[64:65], 30",
        "s_xor_b64 s[64:65], s[64:65], s[68:69]",
        "s_lshr_b64 s[68:69], s[64:65], 30",
        "s_xor_b64 s[64:65], s[64:65], s[68:69]",
    ])
    for channel, (src, ctrl) in enumerate((("s64", "0xa0000"), ("s64", "0xa000a"),
                                           ("s64", "0xa0014"), ("s66", "0xa0000"))):
        body.extend([
            f"s_bfe_u32 s80, {src}, {ctrl}",
            "s_mov_b32 s81, 0",
            "s_lshl_b64 s[80:81], s[80:81], 13",
            "s_or_b64 s[80:81], s[80:81], 0x3f800000",
            f"v_mov_b32_e32 v{12 + channel}, s80",
        ])

    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[pos:pos] = body
    return program


def scalar64_reference(program, words):
    """Independent Python ISA reference for scalar64() using wide integers."""
    mask32, mask64 = 0xffffffff, 0xffffffffffffffff
    regs = {}
    scc = None
    channels = {}

    def read32(tok):
        if tok.startswith("s"):
            return regs[tok] & mask32
        return int(tok, 0) & mask32

    def read64(tok, signed=False):
        if tok.startswith("s["):
            lo, hi = map(int, tok[2:-1].split(":"))
            return (regs[f"s{lo}"] & mask32) | ((regs[f"s{hi}"] & mask32) << 32)
        if tok.startswith("0x"):
            v = int(tok, 16)
            return v | (0xffffffff00000000 if signed and (v & 0x80000000) else 0)
        return int(tok, 0) & mask64

    def write64(tok, val):
        lo, hi = map(int, tok[2:-1].split(":"))
        val &= mask64
        regs[f"s{lo}"] = val & mask32
        regs[f"s{hi}"] = (val >> 32) & mask32

    for line in program:
        op, _, rest = line.partition(" ")
        ops = [t.strip() for t in rest.split(",")] if rest else []
        if op == "s_buffer_load_dwordx4":
            lo = int(ops[0][2:-1].split(":")[0])
            start = (0 if ops[2] == "null" else int(ops[2], 16)) // 4
            for j in range(4):
                regs[f"s{lo + j}"] = words[start + j]
        elif op == "s_mov_b32" and ops[0].startswith("s") and not ops[1].startswith("s2"):
            regs[ops[0]] = read32(ops[1])
        elif op == "s_and_b64" and ops[0].startswith("s["):
            v = read64(ops[1]) & read64(ops[2])
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_or_b64":
            v = read64(ops[1]) | read64(ops[2])
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_xor_b64":
            v = read64(ops[1]) ^ read64(ops[2])
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_andn2_b64":
            v = read64(ops[1]) & (~read64(ops[2]) & mask64)
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_orn2_b64":
            v = read64(ops[1]) | (~read64(ops[2]) & mask64)
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_not_b64":
            v = ~read64(ops[1]) & mask64
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_brev_b64":
            x = read64(ops[1])
            v = int(f"{x:064b}"[::-1], 2)
            write64(ops[0], v)
        elif op == "s_cmov_b64":
            assert scc is not None
            if scc:
                write64(ops[0], read64(ops[1]))
        elif op == "s_lshl_b64":
            v = (read64(ops[1]) << (read32(ops[2]) & 63)) & mask64
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_lshr_b64":
            v = read64(ops[1]) >> (read32(ops[2]) & 63)
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_ashr_i64":
            x = read64(ops[1], signed=True)
            if x >= (1 << 63):
                x -= 1 << 64
            v = (x >> (read32(ops[2]) & 63)) & mask64
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_bfm_b64":
            w = read32(ops[1]) & 63
            off = read32(ops[2]) & 63
            v = (((1 << w) - 1) << off) & mask64
            write64(ops[0], v)
        elif op in ("s_bfe_u32", "s_bfe_i32"):
            src = read32(ops[1])
            ctrl = read32(ops[2])
            off = ctrl & 31
            w = (ctrl >> 16) & 127
            if w == 0:
                v = 0
            elif op == "s_bfe_u32":
                v = (src >> off) & ((1 << min(w, 32)) - 1)
            else:
                if off + w < 32:
                    raw = (src >> off) & ((1 << w) - 1)
                    if raw & (1 << (w - 1)):
                        raw -= 1 << w
                else:
                    raw = (src - (1 << 32) if src & 0x80000000 else src) >> off
                v = raw & mask32
            regs[ops[0]] = v
            scc = v != 0
        elif op == "v_mov_b32_e32" and ops[0] in ("v12", "v13", "v14", "v15"):
            bits = regs[ops[1]] & mask32
            val, = struct.unpack("<f", struct.pack("<I", bits))
            assert half_rtz(val) == val, hex(bits)
            channels[ops[0]] = val
    return tuple(channels[f"v{12 + c}"] for c in range(4)), regs["s66"] & 0x3ff


def scalar64_case(directory, values):
    constants = bytearray(256)
    struct.pack_into("<12I", constants, 16, *values)
    words = struct.unpack("<64I", constants)
    color, _ = scalar64_reference(scalar64(), words)
    path = directory / "scalar64.case"
    path.write_bytes(constants + struct.pack("<4f", *color) * 64)
    return path


# SDWA moves and half widening. In SDWA_PRESERVE_BODY each move writes a 16-bit field into WORD_0 of a register
# holding 1.0 and keeps its high half, so the word is 1 + f * 2^-23; (v - 1) * 2^23 is split into the low and high
# bytes of f. Channels 0 and 1 read WORD_1 of S0; channels 2 and 3 read BYTE_2 of S1 sign-extended to 16 bits.
# SDWA_PAD_BODY writes BYTE_0 of S0 to BYTE_3 and WORD_0 of S2 to WORD_1 with zero padding, and widens each half
# of S1, the low one through -|x|. Each constant set has wrong references (channel, value) for one selection.
def sdwa_readback(value, high):
    return [line.format(r=value, h=high) for line in SDWA_READBACK]


SDWA_READBACK = ["v_subrev_f32_e32 {r}, 1.0, {r}", "v_mul_f32_e32 {r}, 0x4b000000, {r}", "v_mul_f32_e32 {h}, 0x3b800000, {r}", "v_floor_f32_e32 {h}, {h}", "v_fmac_f32_e32 {r}, 0xc3800000, {h}"]
SDWA_PRESERVE_BODY = [
    "v_mov_b32_e32 v12, 1.0",
    "v_mov_b32_sdwa v12, s44 dst_sel:WORD_0 dst_unused:UNUSED_PRESERVE src0_sel:WORD_1",
    *sdwa_readback("v12", "v13"),
    "v_mov_b32_e32 v14, 1.0",
    "v_mov_b32_sdwa v14, sext(s45) dst_sel:WORD_0 dst_unused:UNUSED_PRESERVE src0_sel:BYTE_2",
    *sdwa_readback("v14", "v15"),
]
SDWA_PAD_BODY = [
    "v_mov_b32_sdwa v12, s44 dst_sel:BYTE_3 dst_unused:UNUSED_PAD src0_sel:BYTE_0",
    "v_cvt_f32_f16_sdwa v13, s45 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1",
    "v_cvt_f32_f16_sdwa v14, -|s45| dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
    "v_mov_b32_sdwa v15, s46 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_0",
]
SDWA_SETS = (
    # A wrong WORD_0 selection; a zero-extended byte.
    (SDWA_PRESERVE_BODY, (0x12345678, 0x00c00000, 0), [52.0, 18.0, 192.0, 255.0], ((0, 120.0), (1, 86.0), (3, 0.0))),
    (SDWA_PRESERVE_BODY, (0xfedc0000, 0x007f0000, 0), [220.0, 254.0, 127.0, 0.0], ((0, 0.0), (3, 255.0))),
    # BYTE_1 instead of BYTE_0; the other half of S1 in channels 1 and 2; WORD_1 instead of WORD_0 of S2.
    (SDWA_PAD_BODY, (0x0000c340, 0xc5003c00, 0x3f80c0a0), [2.0, -5.0, -1.0, -5.0], ((0, -128.0), (1, 1.0), (2, -5.0), (3, 1.0))),
    (SDWA_PAD_BODY, (0x000047c0, 0x38004900, 0x00004120), [-2.0, 0.5, -10.0, 10.0], ((0, 32768.0), (1, 10.0), (2, -0.5), (3, 0.0))),
)


def sdwa_reference(body, words):
    """Selections and widening on the integer words, independent of the lowering."""
    x, y, z = words
    if body is SDWA_PRESERVE_BODY:
        first = x >> 16
        byte = (y >> 16) & 0xff
        second = (byte - 0x100 if byte & 0x80 else byte) & 0xffff
        return [float(first & 0xff), float(first >> 8), float(second & 0xff), float(second >> 8)]
    as_float = lambda w: struct.unpack("<f", struct.pack("<I", w))[0]
    return [as_float((x & 0xff) << 24), half_value(y >> 16), -abs(half_value(y)), as_float((z & 0xffff) << 16)]


def check_sdwa_draw(directory, compiler, renderer, backend):
    for name, body in (("sdwa_preserve", SDWA_PRESERVE_BODY), ("sdwa_pad", SDWA_PAD_BODY)):
        source = directory / f"{name}.hlsl"
        shader = directory / f"{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    case = directory / "sdwa.case"
    for body, words, expected, wrongs in SDWA_SETS:
        assert sdwa_reference(body, words) == expected, (words, expected)
        shader = directory / ("sdwa_preserve.cso" if body is SDWA_PRESERVE_BODY else "sdwa_pad.cso")
        constants = bytearray(256)
        struct.pack_into("<3I", constants, 12, *words)
        for x in (*expected, *(value for _, value in wrongs)):
            assert half_rtz(x) == x, x
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
        for channel, value in wrongs:
            assert value != expected[channel]
            wrong_values = list(expected)
            wrong_values[channel] = value
            case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong SDWA selection escaped detection for {words} in channel {channel}")


# SDWA forms of exact arithmetic with whole-dword sources. Programs 0 to 2 draw each operation once with source
# modifiers, an inline constant, clamp and the legacy zero rule; program 2 also places the low byte of a sum into
# BYTE_3. Program 3 keeps WORD_0 and BYTE_2 results inside 1.0 (UNUSED_PRESERVE) and pads the low word of a
# result into WORD_1; a reference that moves the high word there instead must fail.
# Every result is exact in binary32 and after the half export. Each program has wrong references (channel, value).
def sdwa_arith(op, dst, operands, dst_sel="DWORD", unused="UNUSED_PAD", clamp=False):
    sels = " src0_sel:DWORD src1_sel:DWORD" if len(operands) == 2 else " src0_sel:DWORD"
    return (f"v_{op}_f32_sdwa {dst}, {', '.join(operands)}{' clamp' if clamp else ''}"
            f" dst_sel:{dst_sel} dst_unused:{unused}{sels}")


SDWA_ARITH = (
    ([
        "v_mov_b32_e32 v18, s45",
        sdwa_arith("add", "v12", ["s44", "v18"]),
        sdwa_arith("sub", "v13", ["-s44", "v18"]),
        sdwa_arith("subrev", "v14", ["s46", "v18"], clamp=True),
        sdwa_arith("mul", "v15", ["-|s46|", "v18"]),
    ], (1.5, 2.25, -3.0, 0.0), [3.75, -3.75, 1.0, -6.75], ((0, 0.75), (1, -0.75), (2, 5.25), (3, 6.75))),
    ([
        "v_mov_b32_e32 v18, s45",
        "v_mov_b32_e32 v19, s47",
        sdwa_arith("max", "v12", ["s44", "v18"]),
        sdwa_arith("min", "v13", ["0.5", "v18"]),
        sdwa_arith("mul_legacy", "v14", ["s46", "v19"]),
        sdwa_arith("floor", "v15", ["-s45"]),
    ], (-0.75, 2.5, 0.0, math.inf), [2.5, 0.5, 0.0, -3.0], ((0, -0.75), (1, 2.5), (2, -0.0), (3, -2.0))),
    ([
        sdwa_arith("ceil", "v12", ["s44"]),
        sdwa_arith("fract", "v13", ["-s45"]),
        sdwa_arith("trunc", "v14", ["|s46|"]),
        "v_mov_b32_e32 v19, 0",
        sdwa_arith("add", "v15", ["s47", "v19"], dst_sel="BYTE_3"),
    ], (-1.25, 2.75, -2.5, 0x3f800040), [-1.0, 0.25, 2.0, 2.0], ((0, -2.0), (1, 0.75), (2, -2.0), (3, 1.0))),
    ([
        "v_mov_b32_e32 v18, s45",
        "v_mov_b32_e32 v12, 1.0",
        sdwa_arith("mul", "v12", ["s44", "v18"], "WORD_0", "UNUSED_PRESERVE"),
        *sdwa_readback("v12", "v13"),
        "v_mov_b32_e32 v14, 1.0",
        sdwa_arith("floor", "v14", ["s46"], "BYTE_2", "UNUSED_PRESERVE"),
        sdwa_arith("mul", "v15", ["s47", "v18"], "WORD_1"),
    ], (0x3f801234, 1.0, 8388613.0, 0xc0a03fff), [52.0, 18.0, 0.51953125, 1.9921875],
     ((0, 128.0), (1, 63.0), (2, 1.0), (3, -5.0))),
)


def sdwa_arith_reference(index, inputs):
    """Python binary32 arithmetic on the constant words, independent of the lowering."""
    as_float = lambda w: struct.unpack("<f", struct.pack("<I", w))[0]
    bits = lambda x: struct.unpack("<I", struct.pack("<f", x))[0]
    x, y, z, w = (as_float(v) if isinstance(v, int) else v for v in inputs)
    if index == 0:
        return [x + y, -x - y, min(max(y - z, 0.0), 1.0), -abs(z) * y]
    if index == 1:
        return [max(x, y), min(0.5, y), 0.0 if z == 0 or w == 0 else z * w, float(math.floor(-y))]
    if index == 2:
        return [float(math.ceil(x)), -y - math.floor(-y), float(math.trunc(abs(z))), as_float((bits(w + 0.0) & 0xff) << 24)]
    product = bits(x * y) & 0xffff
    return [float(product & 0xff), float(product >> 8),
            as_float((0x3f800000 & ~0xff0000) | ((bits(float(math.floor(z))) & 0xff) << 16)), as_float((bits(w * y) & 0xffff) << 16)]


def check_sdwa_arith_draws(directory, compiler, renderer, backend):
    case = directory / "sdwa_arith.case"
    for index, (body, inputs, expected, wrongs) in enumerate(SDWA_ARITH):
        assert sdwa_arith_reference(index, inputs) == expected, (index, sdwa_arith_reference(index, inputs))
        source = directory / f"sdwa_arith{index}.hlsl"
        shader = directory / f"sdwa_arith{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        words = [v if isinstance(v, int) else struct.unpack("<I", struct.pack("<f", v))[0] for v in inputs]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        for x in (*expected, *(value for _, value in wrongs)):
            assert half_rtz(x) == x, x
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
        for channel, value in wrongs:
            assert struct.pack("<f", value) != struct.pack("<f", expected[channel])
            wrong_values = list(expected)
            wrong_values[channel] = value
            case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong SDWA arithmetic result escaped detection in program {index}, channel {channel}")


# 32-bit vector integer values, byte readback, bitwise operations and shifts. Each draw exports four bytes:
# v_cvt_f32_ubyteN turns byte N into the exact float 0..255, which the half export keeps exactly.
# Words that pass through a v_mov_b32 are float-normal (a nonzero, non-255 exponent field), so a round trip
# through binary32 cannot change them. Shift counts are words with bits above the low five set, and the shifted
# values have the top bit set, so a count that is not masked, a logical shift where an arithmetic one is
# required, and operands in the written order all give different bytes. Each program has wrong references
# (channel, function of the words) built from those plausible bugs.
M32 = 0xffffffff
byte = lambda value, n: (value >> (8 * n)) & 0xff
reverse_bits = lambda value: int(f"{value:032b}"[::-1], 2)
signed = lambda value: value - (1 << 32) if value & 0x80000000 else value
arith_shift = lambda value, count: (signed(value) >> count) & M32
exponent = lambda word: (word >> 23) & 0xff


def ubyte(n, dst, src, spelling, clamp=False):
    return f"v_cvt_f32_ubyte{n}_{spelling} v{dst}, {src}{' clamp' if clamp else ''}"


INT_PROGRAMS = (
    # Bitwise operations, e32: an SGPR, a literal and an inline constant against a register, bytes 0 to 3.
    ([
        "v_mov_b32_e32 v18, s45",
        "v_and_b32_e32 v19, s44, v18",
        "v_or_b32_e32 v20, 0x0f0f0f0f, v18",
        "v_xor_b32_e32 v21, s46, v18",
        "v_xnor_b32_e32 v22, 5, v18",
        ubyte(0, 12, "v19", "e32"), ubyte(1, 13, "v20", "e32"), ubyte(2, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(x & y, 0), byte(0x0f0f0f0f | y, 1), byte(z ^ y, 2), byte(~(5 ^ y) & M32, 3)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
     [(3, lambda x, y, z, w: byte(5 ^ y, 3)),  # xor for xnor
      (0, lambda x, y, z, w: byte(x & y, 1)),  # wrong byte
      (1, lambda x, y, z, w: byte(0x0f0f0f0f & y, 1)),  # and for or
      (2, lambda x, y, z, w: byte(~(z ^ y) & M32, 2))]),  # xnor for xor
    # Bitwise operations, e64 and the e64 byte converts.
    ([
        "v_mov_b32_e32 v18, s45",
        "v_and_b32_e64 v19, 63, v18",
        "v_or_b32_e64 v20, s47, v18",
        "v_xor_b32_e64 v21, s46, v18",
        "v_xnor_b32_e64 v22, s44, v18",
        ubyte(0, 12, "v19", "e64"), ubyte(3, 13, "v20", "e64"), ubyte(1, 14, "v21", "e64"), ubyte(2, 15, "v22", "e64"),
    ], lambda x, y, z, w: [byte(63 & y, 0), byte(w | y, 3), byte(z ^ y, 1), byte(~(x ^ y) & M32, 2)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
     [(3, lambda x, y, z, w: byte(x ^ y, 2)),
      (0, lambda x, y, z, w: byte(63 | y, 0)),
      (1, lambda x, y, z, w: byte(w & y, 3)),
      (2, lambda x, y, z, w: byte(z ^ y, 2))]),
    # not and bit reversal, both spellings, a register source for the reversal.
    ([
        "v_not_b32_e32 v18, s44",
        "v_not_b32_e64 v19, s45",
        "v_bfrev_b32_e32 v20, s46",
        "v_bfrev_b32_e64 v21, v19",
        ubyte(3, 12, "v18", "e32"), ubyte(1, 13, "v19", "e32"), ubyte(0, 14, "v20", "e64"), ubyte(2, 15, "v21", "e64"),
    ], lambda x, y, z, w: [byte(~x & M32, 3), byte(~y & M32, 1), byte(reverse_bits(z), 0), byte(reverse_bits(~y & M32), 2)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
     [(0, lambda x, y, z, w: byte(x, 3)),  # no inversion
      (1, lambda x, y, z, w: byte(y, 1)),  # no inversion in the e64 form
      (2, lambda x, y, z, w: byte(z, 3)),  # bytes swapped, bits kept
      (3, lambda x, y, z, w: byte(~y & M32, 2))]),  # reversal dropped
    # Shifts, e32. The count is the first source: an inline constant, then SGPR words with the high bits set.
    ([
        "v_mov_b32_e32 v18, s44",
        "v_lshlrev_b32_e32 v19, 4, v18",
        "v_lshrrev_b32_e32 v20, s45, v18",
        "v_ashrrev_i32_e32 v21, s46, v18",
        "v_lshlrev_b32_e32 v22, s47, v18",
        ubyte(2, 12, "v19", "e32"), ubyte(1, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((x << 4) & M32, 2), byte(x >> (y & 31), 1), byte(arith_shift(x, z & 31), 3),
                           byte((x << (w & 31)) & M32, 3)],
     ((0xa5c3e187, 0x00000025, 0xffffffe3, 0x3c96b45a), (0x83d5f2a9, 0x00000041, 0x7ffffff8, 0x0000003b)),
     [(0, lambda x, y, z, w: byte((4 << (x & 31)) & M32, 2)),  # operands in the written order
      (1, lambda x, y, z, w: byte(x >> y if y < 32 else 0, 1)),  # count not masked
      (2, lambda x, y, z, w: byte(x >> (z & 31), 3)),  # logical for arithmetic
      (3, lambda x, y, z, w: byte((x << w) & M32 if w < 32 else 0, 3))]),  # count not masked
    # Shifts, e64: SGPR count, inline count above 31, a literal count with high bits, a literal shifted value.
    ([
        "v_mov_b32_e32 v18, s44",
        "v_lshlrev_b32_e64 v19, s45, v18",
        "v_lshrrev_b32_e64 v20, 33, v18",
        "v_ashrrev_i32_e64 v21, 0xffff0023, v18",
        "v_ashrrev_i32_e64 v22, s46, 0x8000c3a5",
        ubyte(1, 12, "v19", "e64"), ubyte(3, 13, "v20", "e64"), ubyte(3, 14, "v21", "e64"), ubyte(3, 15, "v22", "e64"),
    ], lambda x, y, z, w: [byte((x << (y & 31)) & M32, 1), byte(x >> 1, 3), byte(arith_shift(x, 3), 3),
                           byte(arith_shift(0x8000c3a5, z & 31), 3)],
     ((0xa5c3e187, 0x00000025, 0xffffffe3, 0), (0x83d5f2a9, 0x00000041, 0x7fffffe5, 0)),
     [(0, lambda x, y, z, w: byte((x << y) & M32 if y < 32 else 0, 1)),  # count not masked
      (1, lambda x, y, z, w: byte(arith_shift(x, 1), 3)),  # arithmetic for logical
      (2, lambda x, y, z, w: byte(x >> 3, 3)),  # logical for arithmetic
      (3, lambda x, y, z, w: byte(0x8000c3a5 >> (z & 31), 3)),  # logical for arithmetic
      (3, lambda x, y, z, w: byte(arith_shift(z, 0x8000c3a5 & 31), 3))]),  # operands in the written order
    # Byte converts straight from an SGPR, a literal and an inline constant, with clamp in the e64 form.
    ([
        ubyte(0, 12, "s44", "e32"),
        ubyte(1, 13, "s45", "e64"),
        ubyte(2, 14, "0xab0000", "e32"),
        ubyte(3, 15, "s47", "e64", clamp=True),
    ], lambda x, y, z, w: [byte(x, 0), byte(y, 1), 0xab, min(byte(w, 3), 1)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x00ffffff)),
     [(0, lambda x, y, z, w: byte(x, 1)),
      (1, lambda x, y, z, w: byte(y, 0)),
      (2, lambda x, y, z, w: 0xab0000 & 0xff),
      (3, lambda x, y, z, w: byte(w, 3))]),  # clamp ignored
    # Byte converts of a numeric register, an inline float and a negative inline integer.
    ([
        "v_mov_b32_e32 v18, s44",
        ubyte(1, 12, "v18", "e32"),
        ubyte(2, 13, "1.0", "e64"),
        ubyte(0, 14, "-2", "e32"),
        ubyte(3, 15, "v18", "e64"),
    ], lambda x, y, z, w: [byte(x, 1), 0x80, 0xfe, byte(x, 3)],
     ((0xa5c3e187, 0, 0, 0), (0x93f1c2d4, 0, 0, 0)),
     [(1, lambda x, y, z, w: byte(0x3f800000, 3)),
      (2, lambda x, y, z, w: 0x02),
      (3, lambda x, y, z, w: byte(x, 2))]),
)


def check_int_draws(directory, compiler, renderer, backend):
    case = directory / "int.case"
    for index, (body, reference, sets, bugs) in enumerate(INT_PROGRAMS):
        source = directory / f"int{index}.hlsl"
        shader = directory / f"int{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = [False] * len(bugs)
        for words in sets:
            if "v_mov_b32_e32 v18, s45" in body:
                assert 0 < exponent(words[1]) < 255, hex(words[1])
            if "v_mov_b32_e32 v18, s44" in body:
                assert 0 < exponent(words[0]) < 255, hex(words[0])
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = [float(value) for value in reference(*words)]
            for x in expected:
                assert half_rtz(x) == x, x
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for k, (channel, buggy) in enumerate(bugs):
                value = float(buggy(*words))
                if value == expected[channel]:
                    continue
                separated[k] = True
                assert half_rtz(value) == value, value
                wrong_values = list(expected)
                wrong_values[channel] = value
                case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong integer result escaped detection in program {index}, channel {channel}, words {words}")
        assert all(separated), (index, separated)


# Binary16 arithmetic (the _f16 VALU forms). Every program is drawn with several constant sets and each channel
# is compared with an independent model: exact float64 arithmetic on the binary16 inputs, rounded once to
# binary16 by struct "e" (nearest even). Value programs widen the result with v_cvt_f32_f16, which gives the
# binary16 exactly through the half export. Bit programs preset the destination to 1.0 and split (v - 1) * 2^23
# into the low and high byte of the 16-bit result, as NARROW_BODY does, so signed zero, subnormal and infinite
# results and the kept high half are read bit for bit. The source words carry junk in the high half. Each program
# lists the plausible lowering bugs to model; a bug is drawn as a wrong reference wherever it changes a channel
# and must be reported as a mismatch. The channels of a bug-free model are asserted against the instruction
# semantics by hand in F16_EXPECTED.
def f16_in(word, bug):
    x = half_value(word)
    if bug == "flush" and x != 0 and abs(x) < 2.0 ** -14:
        return math.copysign(0.0, x)
    return x


def f16_out(x, bug):
    """The binary16 encoding of an exact result; half_up rounds ties away from zero, flush drops subnormals."""
    bits = narrow_reference(x)
    if bug == "half_up" and abs(x) < 65520:
        magnitude, mag = abs(x), bits & 0x7fff
        low = mag if half_value(mag) <= magnitude else mag - 1
        if low + 1 < 0x7c00 and magnitude - half_value(low) == half_value(low + 1) - magnitude:
            bits = (bits & 0x8000) | (low + 1)
    if bug == "flush" and 0 < (bits & 0x7fff) < 0x400:
        bits &= 0x8000
    return bits


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


def kept_sign(x, result):
    return math.copysign(0.0, x) if result == 0 else float(result)


def f16_floor(x):
    return x if abs(x) >= 1024 else kept_sign(x, math.floor(x))


def f16_ceil(x):
    return x if abs(x) >= 1024 else kept_sign(x, math.ceil(x))


def f16_trunc(x):
    return x if abs(x) >= 1024 else kept_sign(x, math.trunc(x))


def f16_rndne(x, bug):
    if abs(x) >= 1024:
        return x
    if bug == "rndne_away" and abs(x) % 1 == 0.5:
        return kept_sign(x, math.copysign(math.floor(abs(x) + 0.5), x))
    return kept_sign(x, round(x))


def f16_fract(x, bug):
    result = x - math.floor(x)
    return result if bug == "fract_no_clamp" else min(result, half_value(0x3bff))


def f16_ldexp(x, word, bug):
    exponent = word & 0xffff
    if bug != "unsigned_exp" and exponent & 0x8000:
        exponent -= 0x10000
    # The bound is independent of the lowering's: well beyond where a nonzero binary16 can still result.
    return math.ldexp(x, max(-200, min(200, exponent)))


def f16_words(*lows, junk=(0xdead, 0xbeef, 0x4d2f, 0xfc01)):
    """Constant words 3 to 6: the given low halves under junk high halves."""
    return tuple((high << 16) | low for high, low in zip(junk, (*lows, 0, 0, 0, 0)))


def f16_values(*results, bug=None):
    return [half_value(f16_out(x, bug)) for x in results]


def f16_bit_channels(*results, bug=None):
    """Two channels per result. Zeroing the high half instead of keeping it leaves a binary32 denormal in the
    destination, so (v - 1) * 2^23 is -2^23, which splits into -32768 * 256 + 0."""
    if bug == "high_zero":
        return [0.0, -32768.0] * len(results)
    return [value for x in results for bits in (f16_out(x, bug),) for value in (float(bits & 0xff), float(bits >> 8))]


def f16_values_readback():
    return [f"v_cvt_f32_f16_e32 v{r}, v{r}" for r in range(12, 16)]


def f16_bits_program(setup, first, second):
    """Run two operations into registers preset to 1.0 and read both encodings bit for bit."""
    return [*setup, "v_mov_b32_e32 v12, 1.0", first, *sdwa_readback("v12", "v13"),
            "v_mov_b32_e32 v14, 1.0", second, *sdwa_readback("v14", "v15")]


def f16_model_v1(words, bug):
    a, b, c, d = (f16_in(w, bug) for w in words)
    return f16_values(a + b, -a - (b if bug == "no_abs" else abs(b)), (c - b) if bug == "no_reverse" else b - c, d * b, bug=bug)


def f16_model_v2(words, bug):
    a, b = (f16_in(w, bug) for w in words[:2])
    return f16_values(max(-a if bug == "no_abs" else -abs(a), b), min(a, b), f16_const("0.5", bug) + b, half_value(0x3c02) + b, bug=bug)


def f16_model_v3(words, bug):
    x = f16_in(words[0], bug)
    return f16_values(f16_floor(x), f16_ceil(-x if bug == "no_abs" else -abs(x)), f16_trunc(x), f16_rndne(x, bug), bug=bug)


def f16_model_v4(words, bug):
    a, b, c = (f16_in(w, bug) for w in words[:3])
    return f16_values(f16_fract(a, bug), f16_fract(-abs(b), bug), f16_ldexp(c, words[3], bug), math.ldexp(-c, -3), bug=bug)


def f16_model_high(words, bug):
    a, b, c = (f16_in(w, bug) for w in words[:3])
    marker = half_value(words[3] >> 16)
    return [half_value(f16_out(a + b, bug)), 0.0 if bug == "high_zero" else marker, half_value(f16_out(c * b, bug)), 0.0]


def f16_model_b1(words, bug):
    a, b, c = (f16_in(w, bug) for w in words[:3])
    return f16_bit_channels(a + b, c * b, bug=bug)


def f16_model_b2(words, bug):
    a, b = (f16_in(w, bug) for w in words[:2])
    return f16_bit_channels((a - b) if bug == "no_reverse" else b - a, b - f16_const("0.15915494", bug), bug=bug)


def f16_model_b3(words, bug):
    a, b, c = (f16_in(w, bug) for w in words[:3])
    return f16_bit_channels(min(a, b), max(c, b), bug=bug)


def f16_model_b4(words, bug):
    x, y = f16_in(words[0], bug), f16_in(words[3], bug)
    return f16_bit_channels(f16_ldexp(x, words[1], bug), f16_ldexp(y, words[2], bug), bug=bug)


def f16_model_b5(words, bug):
    return f16_bit_channels(f16_floor(f16_in(words[0], bug)), f16_ceil(f16_in(words[2], bug)), bug=bug)


def f16_model_b6(words, bug):
    return f16_bit_channels(f16_trunc(f16_in(words[0], bug)), f16_rndne(f16_in(words[2], bug), bug), bug=bug)


def f16_model_b7(words, bug):
    b = f16_in(words[1], bug)
    return f16_bit_channels(f16_const("3", bug) * b, f16_const("64", bug) + b, bug=bug)


F16_B_SETUP = ["v_mov_b32_e32 v18, s45"]
# (name, body, model, constant sets, bugs). Operand forms: s44 to s47 are the sets' words; v18 and v19 copy s45
# and s47 so the e32 forms have a vector second operand.
F16_PROGRAMS = (
    ("v1", ["v_mov_b32_e32 v18, s45", "v_add_f16_e32 v12, s44, v18", "v_sub_f16_e64 v13, -s44, |v18|",
            "v_subrev_f16_e32 v14, s46, v18", "v_mul_f16_e32 v15, s47, v18", *f16_values_readback()],
     f16_model_v1,
     # Ties that round down to even in the sum, the negated sum and the product; the operand order of subrev;
     # an absolute value on the second operand.
     [f16_words(0x3c00, 0x1000, 0x3800, 0x3c03), f16_words(0x3c01, 0x3e00, 0x3c00, 0x3c03),
      f16_words(0xba00, 0xb400, 0xbe00, 0xc200)],
     ("half_up", "no_reverse", "no_abs")),
    ("v2", ["v_mov_b32_e32 v18, s45", "v_max_f16_e64 v12, -|s44|, v18", "v_min_f16_e32 v13, s44, v18",
            "v_add_f16_e32 v14, 0.5, v18", "v_add_f16_e32 v15, 0x3c02, v18", *f16_values_readback()],
     f16_model_v2,
     # The inline 0.5 and a literal; 1 + 2^-9 plus 2^-11 is a tie that rounds down to even.
     [f16_words(0xba00, 0x3400), f16_words(0x4200, 0xc100), f16_words(0x3c00, 0x1000)],
     ("half_up", "const_bits", "no_abs")),
    ("v3", ["v_floor_f16_e32 v12, s44", "v_ceil_f16_e64 v13, -|s44|", "v_trunc_f16_e32 v14, s44",
            "v_rndne_f16_e64 v15, s44", *f16_values_readback()],
     f16_model_v3,
     # 2.5, -2.5 and -1.5, and 1023.5, the last half-integer.
     [f16_words(low) for low in (0x4100, 0xc100, 0xbe00, 0x63ff)],
     ("rndne_away", "no_abs")),
    ("v4", ["v_mov_b32_e32 v19, s47", "v_fract_f16_e32 v12, s44", "v_fract_f16_e64 v13, -|s45|",
            "v_ldexp_f16_e32 v14, s46, v19", "v_ldexp_f16_e64 v15, -s46, -3", *f16_values_readback()],
     f16_model_v4,
     # fract of a negative value, of the tiniest negative half (it must stay below 1.0), and ldexp by a
     # positive and a negative register exponent and by the inline constant -3.
     [f16_words(0xb400, 0x4180, 0x3e00, 3), f16_words(0x8001, 0xbf00, 0xba00, 0xfffe),
      f16_words(0x4248, 0xc248, 0x4248, 0xffff)],
     ("fract_no_clamp", "unsigned_exp")),
    ("high", ["v_mov_b32_e32 v18, s45", "v_mov_b32_e32 v12, s47", "v_add_f16_e32 v12, s44, v18",
              "v_cvt_f32_f16_sdwa v13, v12 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1",
              "v_cvt_f32_f16_e32 v12, v12", "v_mul_f16_e64 v20, s46, v18",
              "v_cvt_f32_f16_sdwa v15, v20 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1",
              "v_cvt_f32_f16_e32 v14, v20"],
     f16_model_high,
     # The destination of the add holds a marker in its high half (5.0, then -0.75) and keeps it; the
     # destination of the multiply was never written, so its high half is zero.
     [f16_words(0x3c00, 0x1000, 0x3800, junk=(0xdead, 0xbeef, 0x4d2f, 0x4500)) [:3] + (0x45001234,),
      f16_words(0xc200, 0x3e00, 0x4000, junk=(0xdead, 0xbeef, 0x4d2f, 0x4500))[:3] + (0xba00ffff,)],
     ("half_up", "high_zero")),
    ("b1", f16_bits_program(F16_B_SETUP, "v_add_f16_e32 v12, s44, v18", "v_mul_f16_e64 v14, s46, v18"),
     f16_model_b1,
     # 65504 + 16 overflows at the tie; -0 + -0; an add of two subnormals, and a product that is the smallest
     # subnormal; the largest subnormal from 2^-14 - 2^-24 and a product that ties to -0; x + -x is +0, and a
     # product rounding to -3 * 2^-24; the sum and product that are 65504 and infinity.
     [f16_words(0x7bff, 0x4c00, 0x8000), f16_words(0x8000, 0x8000, 0x0c00), f16_words(0x0001, 0x0001, 0x0c00),
      f16_words(0x0001, 0x0c00, 0x0c00), f16_words(0x0400, 0x8001, 0x3800), f16_words(0x4248, 0xc248, 0x0001),
      f16_words(0x7bff, 0x4bff, 0x7bff)],
     ("half_up", "flush", "high_zero")),
    ("b2", f16_bits_program(F16_B_SETUP, "v_subrev_f16_e32 v12, s44, v18", "v_sub_f16_e64 v14, v18, 0.15915494"),
     f16_model_b2,
     # b - a and b - 1/(2*pi): equal operands, a signed zero, a subnormal, negative overflow, and a tie.
     [f16_words(0x3800, 0x3800), f16_words(0x8000, 0x0000), f16_words(0x0001, 0x0000), f16_words(0x7bff, 0xfbff),
      f16_words(0x3c01, 0x1000)],
     ("half_up", "no_reverse", "flush", "const_bits", "high_zero")),
    ("b3", f16_bits_program(F16_B_SETUP, "v_min_f16_e32 v12, s44, v18", "v_max_f16_e64 v14, s46, v18"),
     f16_model_b3,
     [f16_words(0x7c00, 0x3c00, 0x7c00), f16_words(0x0001, 0x0002, 0x8001), f16_words(0xbc00, 0x3c00, 0xbc00)],
     ("flush", "high_zero")),
    ("b4", f16_bits_program(["v_mov_b32_e32 v18, s45", "v_mov_b32_e32 v19, s47"], "v_ldexp_f16_e32 v12, s44, v18",
                            "v_ldexp_f16_e64 v14, v19, s46"),
     f16_model_b4,
     # (x, exponent 1, exponent 2, y): 2^-24, the tie 2^-25 that rounds to 0, 1.5 * 2^-25 rounding up to 2^-24,
     # -2^-26, a subnormal input scaled back, overflow, an exponent of -32768 (from 0x8000), zero and
     # infinity-sized exponents, and the largest half halved.
     [f16_words(0x3c00, 0xffe8, 0xffe7, 0x3c00), f16_words(0x3e00, 0xffe7, 0xffe6, 0xbc00),
      f16_words(0x0001, 24, 10, 0x0001), f16_words(0x3c00, 0x03e8, 0x8000, 0xbc00),
      f16_words(0x0000, 0x7fff, 0xfffb, 0x8000), f16_words(0x7bff, 1, 0xffff, 0x7bff),
      f16_words(0x4200, 0xfffd, 3, 0x3a00)],
     ("half_up", "flush", "unsigned_exp", "high_zero")),
    ("b5", f16_bits_program(F16_B_SETUP, "v_floor_f16_e32 v12, s44", "v_ceil_f16_e64 v14, s46"),
     f16_model_b5,
     # -0.5, 0.5, signed zeros, -2.5 and 2.5, and the smallest subnormals of each sign.
     [f16_words(0xb800, 0, 0xb800), f16_words(0x3800, 0, 0x3800), f16_words(0x8000, 0, 0x0000),
      f16_words(0xc100, 0, 0x4100), f16_words(0x8001, 0, 0x0001), f16_words(0x0001, 0, 0x8001)],
     ("flush", "high_zero")),
    ("b6", f16_bits_program(F16_B_SETUP, "v_trunc_f16_e32 v12, s44", "v_rndne_f16_e64 v14, s46"),
     f16_model_b6,
     [f16_words(0xb800, 0, 0xb800), f16_words(0x3800, 0, 0x3800), f16_words(0x4100, 0, 0x4100),
      f16_words(0xc100, 0, 0xc100), f16_words(0x7bff, 0, 0x7bff), f16_words(0x03ff, 0, 0x83ff)],
     ("rndne_away", "high_zero")),
    ("b7", f16_bits_program(F16_B_SETUP, "v_mul_f16_e32 v12, 3, v18", "v_add_f16_e64 v14, 64, v18"),
     f16_model_b7,
     # The integer inline constants 3 and 64 are subnormal bit patterns, not the numbers 3 and 64.
     [f16_words(0, 0x4000), f16_words(0, 0x0200), f16_words(0, 0x8200)],
     ("int_value", "flush", "high_zero")),
)
# Hand-computed channels of the bug-free models for one set of each program, so that a model and a lowering
# cannot be wrong in the same way: tie to even 1 + 2^-11 -> 1, -(1 + 2^-11) -> -1, 2^-11 - 0.5, 1.5 * 2^-11 * ...
F16_EXPECTED = {
    "v1": (0, [1.0, -1.0, 2.0 ** -11 - 0.5, (1 + 3 * 2.0 ** -10) * 2.0 ** -11]),
    "v2": (0, [0.25, -0.75, 0.75, 1 + 2.0 ** -9 + 0.25]),
    "v3": (1, [-3.0, -2.0, -2.0, -2.0]),
    "v4": (0, [0.75, 0.25, 12.0, -0.1875]),
    "high": (0, [1.0, 5.0, 2.0 ** -12, 0.0]),
    "b1": (0, [0x00, 0x7c, 0x00, 0x80]),
    "b2": (4, [0x00, 0xbc, 0x14, 0xb1]),
    "b4": (1, [0x01, 0x00, 0x00, 0x80]),
    "b5": (0, [0x00, 0xbc, 0x00, 0x80]),
    "b6": (1, [0x00, 0x00, 0x00, 0x00]),
    "b7": (0, [0x06, 0x00, 0x00, 0x40]),
}


def check_f16_models() -> None:
    """The models against hand-computed channels, and each listed bug against the sets that must expose it."""
    by_name = {name: (model, sets, bugs) for name, _, model, sets, bugs in F16_PROGRAMS}
    for name, (index, expected) in F16_EXPECTED.items():
        model, sets, _ = by_name[name]
        assert model(sets[index], None) == [float(v) for v in expected], (name, model(sets[index], None))
    for name, (model, sets, bugs) in by_name.items():
        for bug in bugs:
            assert any(model(words, bug) != model(words, None) for words in sets), (name, bug)
        for words in sets:
            for bug in (None, *bugs):
                for x in model(words, bug):
                    assert half_rtz(x) == x or x in (math.inf, -math.inf), (name, bug, x)


def check_f16_draws(directory, compiler, renderer, backend):
    check_f16_models()
    case = directory / "f16.case"
    for name, body, model, sets, bugs in F16_PROGRAMS:
        source = directory / f"f16_{name}.hlsl"
        shader = directory / f"f16_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = model(words, None)
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for bug in bugs:
                wrong = model(words, bug)
                if struct.pack("<4f", *wrong) == struct.pack("<4f", *expected):
                    continue
                case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A binary16 lowering bug ({bug}) escaped detection in {name} for words {words}")
# Binary16 comparisons and class tests (v_cmp_<p>_f16, v_cmp_class_f16). Each draw exports the four lane-mask results
# through v_cndmask_b32 (0 or 1.0), as the binary32 predicate draws do; words reach vector registers through
# v_or_b32, so no pattern passes through a float register. Inputs are binary16 words under junk high halves.
# The reference is independent: the binary16 values are decoded by struct "e" and compared as Python floats, whose
# relations (less, equal, greater, unordered) are looked up in the gfx10 truth-table number of each predicate. The class
# reference decodes the encoding with float functions. Each program lists the plausible lowering bugs to model; each
# must change a channel on some set and is drawn as a wrong reference that must report a mismatch.
def relation_ref(a, b):
    return 3 if math.isnan(a) or math.isnan(b) else 0 if a < b else 1 if a == b else 2


def f32_word(word):
    return struct.unpack("<f", struct.pack("<I", word & M32))[0]


def cmp_in(word, bug):
    """A source word as the lowering must read it: the low half as binary16. high_half reads the whole word as
    binary32; flush reads binary16 subnormals as zero."""
    if bug == "high_half":
        return f32_word(word)
    x = half_value(word)
    if bug == "flush" and x != 0 and abs(x) < 2.0 ** -14:
        return math.copysign(0.0, x)
    return x


def cmp_model(first, x_mod, y_mod):
    def model(words, bug):
        x, y = cmp_in(words[0], bug), cmp_in(words[1], bug)
        if bug != "no_mod":
            x, y = x_mod(x), y_mod(y)
        out = []
        for op in range(first, first + 4):
            relation = relation_ref(x, y)
            # nan_ordered: an unordered operand is treated as ordered, so no predicate fires on it.
            out.append(0.0 if bug == "nan_ordered" and relation == 3 else float((op >> relation) & 1))
        return out
    return model


identity = lambda value: value
negate = lambda value: -value


def cmp_words(x, y, z=0, w=0, hx=0xdead, hy=0xbeef):
    return ((hx << 16) | x, (hy << 16) | y, z, w)


# (S0, S1) low halves, kept to what the three-minute hardware test budget allows. Each set stands for a class of cases:
# ordinary values, -0 against +0, a quiet NaN first, a signaling NaN second, infinities of opposite sign, a subnormal
# against zero (equal if subnormals are flushed), equal binary16 values under a NaN high half (a whole-register read
# is unordered) and a larger value under a large high half (a whole-register read reverses the relation).
F16_CMP_SETS = (
    cmp_words(0xbc00, 0x3c00), cmp_words(0x8000, 0x0000), cmp_words(0x7e00, 0x3c00), cmp_words(0x3c00, 0x7d00),
    cmp_words(0x7c00, 0xfc00), cmp_words(0x0001, 0x0000), cmp_words(0x3c00, 0x3c00, hx=0x7fc0, hy=0x0000),
    cmp_words(0x4000, 0x3c00, hx=0x0000, hy=0x7f00),
)
F16_CMP_BUGS = ("nan_ordered", "high_half", "flush")


def cmp_group(first, spelling):
    body = ["v_or_b32_e64 v18, s45, 0", "v_mov_b32_e32 v19, 1.0"]
    for channel, op in enumerate(PREDICATES[first:first + 4]):
        if spelling == "e32":
            body.extend([f"v_cmp_{op}_f16_e32 vcc_lo, s44, v18", f"v_cndmask_b32_e32 v{12 + channel}, 0, v19, vcc_lo"])
        else:
            body.extend([f"v_cmp_{op}_f16_e64 s0, -s44, -v18", f"v_cndmask_b32_e64 v{12 + channel}, 0, v19, s0"])
    return body


F16_CMP_MODS_BODY = [
    "v_or_b32_e64 v18, s45, 0", "v_mov_b32_e32 v19, 1.0",
    "v_cmp_lt_f16_e64 s0, |s44|, v18", "v_cndmask_b32_e64 v12, 0, v19, s0",
    "v_cmp_eq_f16_e64 s0, -s44, |v18|", "v_cndmask_b32_e64 v13, 0, v19, s0",
    "v_cmp_nge_f16_e64 s0, |s44|, -v18", "v_cndmask_b32_e64 v14, 0, v19, s0",
    "v_cmp_u_f16_e64 s0, -|s44|, v18", "v_cndmask_b32_e64 v15, 0, v19, s0",
]


def f16_cmp_mods_model(words, bug):
    x, y = cmp_in(words[0], bug), cmp_in(words[1], bug)
    mods = bug != "no_mod"
    relations = [relation_ref(abs(x) if mods else x, y), relation_ref(-x if mods else x, abs(y) if mods else y),
                 relation_ref(abs(x) if mods else x, -y if mods else y), relation_ref(-abs(x) if mods else x, y)]
    truth = [PREDICATES.index(op) for op in ("lt", "eq", "nge", "u")]
    out = [float((truth[c] >> relations[c]) & 1) for c in range(4)]
    return [0.0 if bug == "nan_ordered" and relations[c] == 3 else out[c] for c in range(4)]


# Inline binary16 constants as the first source: 0.5, -0.5 and 1.0 are the binary16 values 0x3800, 0xb800 and 0x3c00;
# read as the low half of their binary32 encodings they would all be +0. Channels: 0.5 < Y, 0.5 == Z, -0.5 > Y, not(1.0 < Y).
F16_CMP_CONST_BODY = [
    "v_or_b32_e64 v18, s45, 0", "v_mov_b32_e32 v19, 1.0",
    "v_cmp_lt_f16_e32 vcc_lo, 0.5, v18", "v_cndmask_b32_e32 v12, 0, v19, vcc_lo",
    "v_cmp_eq_f16_e64 s0, 0.5, s46", "v_cndmask_b32_e64 v13, 0, v19, s0",
    "v_cmp_gt_f16_e64 s0, -0.5, v18", "v_cndmask_b32_e64 v14, 0, v19, s0",
    "v_cmp_nlt_f16_e32 vcc_lo, 1.0, v18", "v_cndmask_b32_e32 v15, 0, v19, vcc_lo",
]


def f16_cmp_const_model(words, bug):
    const = lambda token: f16_const(token, "const_bits" if bug == "const_bits" else None)
    y, z = cmp_in(words[1], bug), cmp_in(words[2], bug)
    # nan_ordered: not(1.0 < Y) is evaluated as 1.0 >= Y, which is false for a NaN.
    nlt = const("1.0") >= y if bug == "nan_ordered" else not const("1.0") < y
    return [float(const("0.5") < y), float(const("0.5") == z), float(const("-0.5") > y), float(nlt)]


F16_CMP_CONST_SETS = (
    cmp_words(0, 0x3800, 0x3800), cmp_words(0, 0x0000, 0x0000), cmp_words(0, 0x3c00, 0x3800),
    cmp_words(0, 0xb800, 0x0000), cmp_words(0, 0x7e00, 0x3800), cmp_words(0, 0xbc00, 0xb800),
)

F16_CMP_PROGRAMS = tuple(
    (f"{spelling}_{first // 4}", cmp_group(first, spelling),
     cmp_model(first, identity if spelling == "e32" else negate, identity if spelling == "e32" else negate),
     F16_CMP_SETS, tuple(bug for bug in F16_CMP_BUGS if bug != "nan_ordered" or first >= 8)  # f..o never fire on NaN
     + (() if spelling == "e32" else ("no_mod",)))
    for spelling in ("e32", "e64") for first in range(0, 16, 4)
) + (
    ("mods", F16_CMP_MODS_BODY, f16_cmp_mods_model, F16_CMP_SETS, F16_CMP_BUGS + ("no_mod",)),
    ("const", F16_CMP_CONST_BODY, f16_cmp_const_model, F16_CMP_CONST_SETS, ("const_bits", "high_half", "nan_ordered")),
)
# Hand-computed channels of the bug-free models: program, set index, channels. e32_0 is f, lt, eq, le; e32_1 is gt,
# lg, ge, o; e32_2 is u, nge, nlg, ngt; e32_3 is nle, neq, nlt, tru. The e64 programs compare -S0 with -S1.
F16_CMP_EXPECTED = (
    ("e32_0", 0, [0, 1, 0, 1]),    # -1 against 1
    ("e32_0", 1, [0, 0, 1, 1]),    # -0 against +0 is equal
    ("e32_0", 2, [0, 0, 0, 0]),    # quiet NaN: no ordered predicate holds
    ("e32_1", 2, [0, 0, 0, 0]),
    ("e32_2", 3, [1, 1, 1, 1]),    # a signaling NaN is unordered
    ("e32_3", 3, [1, 1, 1, 1]),
    ("e32_3", 6, [0, 0, 1, 1]),    # equal halves under a NaN high half are equal
    ("e64_1", 0, [1, 1, 1, 1]),    # -(-1) against -(1): greater
    ("e64_3", 6, [0, 0, 1, 1]),
    ("const", 0, [0, 1, 0, 1]),    # 0.5 < 0.5 false, 0.5 == 0.5 true, -0.5 > 0.5 false, not (1.0 < 0.5) true
    ("const", 1, [0, 0, 0, 1]),    # Y = Z = 0
)


# v_cmp_class_f16: the class of the binary16 in the low half of S0 against a 32-bit mask (bit order as class32).
# Channels: S0 against the SGPR mask S1 (e64), against the vector mask S2 (e32), -|S0| against the literal 0x8c
# (-inf, -normal, +subnormal; e64), and the inline constant 0.5 (+normal) against the SGPR mask S3 (e64).
F16_CLASS_BODY = [
    "v_or_b32_e64 v18, s46, 0", "v_mov_b32_e32 v19, 1.0",
    "v_cmp_class_f16_e64 s0, s44, s45", "v_cndmask_b32_e64 v12, 0, v19, s0",
    "v_cmp_class_f16_e32 vcc_lo, s44, v18", "v_cndmask_b32_e32 v13, 0, v19, vcc_lo",
    "v_cmp_class_f16_e64 s0, -|s44|, 0x8c", "v_cndmask_b32_e64 v14, 0, v19, s0",
    "v_cmp_class_f16_e64 s0, 0.5, s47", "v_cndmask_b32_e64 v15, 0, v19, s0",
]


def class16_ref(word):
    low = word & 0xffff
    x = half_value(low)
    sign = low >> 15
    if math.isnan(x):
        return 0x2 if low & 0x200 else 0x1
    if math.isinf(x):
        return 0x4 if sign else 0x200
    if x == 0:
        return 0x20 if sign else 0x40
    if abs(x) < 2.0 ** -14:
        return 0x10 if sign else 0x80
    return 0x8 if sign else 0x100


def class32_ref(word):
    sign, exponent, mantissa = word >> 31, (word >> 23) & 0xff, word & 0x7fffff
    if exponent == 0xff and mantissa:
        return 0x2 if mantissa & 0x400000 else 0x1
    if exponent == 0xff:
        return 0x4 if sign else 0x200
    if exponent == 0:
        return (0x20 if sign else 0x40) if mantissa == 0 else (0x10 if sign else 0x80)
    return 0x8 if sign else 0x100


def f16_class_model(words, bug):
    x, m0, m1, m3 = words

    def classify(word):
        if bug == "high_half":
            return class32_ref(word)
        c = class16_ref(word)
        if bug == "swap_nan" and c in (1, 2):
            return 3 - c  # signaling and quiet NaN exchanged
        if bug == "sub_zero" and c in (0x10, 0x80):
            return c << 1 if c == 0x10 else c >> 1  # a subnormal classed as the zero of its sign
        return c

    if bug == "no_mod":
        channel2 = classify(x)
    elif bug == "high_half":
        channel2 = classify(0x80000000 | (x & 0x7fffffff))
    else:
        channel2 = classify(0x8000 | (x & 0x7fff))
    half = 0 if bug == "const_bits" else 0x3800  # the low half of the binary32 encoding of 0.5 is 0
    return [float(classify(x) & m0 != 0), float(classify(x) & m1 != 0), float(channel2 & 0x8c != 0),
            float(class16_ref(half) & m3 != 0)]


# One input per class and per edge of the encoding, each under a different high half (a binary32 NaN, an infinity,
# zero, all ones), with the mask of its own class in S1 and the complement in S2, and the other way round.
F16_CLASS_WORDS = ((0x7d00, 0x7f80), (0xfc01, 0xdead), (0x7e00, 0x0000), (0xfe00, 0xffff), (0xfc00, 0x7fc0),
                   (0x7c00, 0x0000), (0xbc00, 0x7f80), (0x3c00, 0xffff), (0x8001, 0x0000), (0x0001, 0x7fc0),
                   (0x83ff, 0xbeef), (0x03ff, 0x0000), (0x8000, 0x7f80), (0x0000, 0xffff), (0x0400, 0xff80),
                   (0x7bff, 0x1234), (0xfbff, 0x0000), (0x8400, 0x7fc0))
F16_CLASS_SETS = tuple(
    ((high << 16) | low, *masks, 0x100 if index % 2 == 0 else 0x40)
    for index, (low, high) in enumerate(F16_CLASS_WORDS)
    for masks in (((class16_ref(low), 0x3ff ^ class16_ref(low)) if index % 2 == 0 else (0x3ff ^ class16_ref(low), class16_ref(low))),)
)
F16_CLASS_BUGS = ("swap_nan", "sub_zero", "high_half", "no_mod", "const_bits")
# Hand-computed channels: (S0, S1, S2, S3) and the four results.
F16_CLASS_EXPECTED = (
    ((0x7f807d00, 0x1, 0x3fe, 0x100), [1, 0, 0, 1]),   # a signaling NaN is class bit 0; -|x| is no listed class; 0.5 is +normal
    ((0x7f807d00, 0x2, 0x3fd, 0x40), [0, 1, 0, 0]),    # not bit 1; 0.5 is not +0
    ((0x00000001, 0x80, 0x37f, 0x100), [1, 0, 0, 1]),  # +subnormal is class bit 7; -|x| is -subnormal, outside 0x8c
    ((0xffff8000, 0x20, 0x3df, 0x40), [1, 0, 0, 0]),   # -0 is class bit 5, not +0
    ((0x7bfffc00, 0x4, 0x3fb, 0x100), [1, 0, 1, 1]),  # -inf is bit 2 and in 0x8c after -|x|
)


F16_CMP_PROGRAM_BY_NAME = {name: (model, sets) for name, _, model, sets, _ in F16_CMP_PROGRAMS}
F16_CLASS_PROGRAMS = (("class", F16_CLASS_BODY, f16_class_model, F16_CLASS_SETS, F16_CLASS_BUGS),)


def check_f16_cmp_models():
    """The models against hand-computed channels, and each listed bug against the sets that must expose it."""
    for name, index, expected in F16_CMP_EXPECTED:
        model, sets = F16_CMP_PROGRAM_BY_NAME[name]
        assert model(sets[index], None) == [float(v) for v in expected], (name, index, model(sets[index], None))
    for words, expected in F16_CLASS_EXPECTED:
        assert f16_class_model(words, None) == [float(v) for v in expected], words
    for name, _, model, sets, bugs in (*F16_CMP_PROGRAMS, *F16_CLASS_PROGRAMS):
        for bug in bugs:
            assert any(model(words, bug) != model(words, None) for words in sets), (name, bug)



def check_f16_cmp_draws(directory, compiler, renderer, backend):
    check_f16_cmp_models()
    case = directory / "f16cmp.case"
    for name, body, model, sets, bugs in (*F16_CMP_PROGRAMS, *F16_CLASS_PROGRAMS):
        source = directory / f"f16cmp_{name}.hlsl"
        shader = directory / f"f16cmp_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        drawn = dict.fromkeys(bugs, 0)
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = model(words, None)
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            try:
                subprocess.run(draw, check=True)
            except subprocess.CalledProcessError as error:
                error.add_note(f"Binary16 comparison draw {name} on {backend}, words {[hex(w) for w in words]}")
                raise
            for bug in bugs:
                wrong = model(words, bug)
                # One exposing set per bug establishes that the renderer notices it.
                if wrong == expected or drawn[bug] == 1:
                    continue
                drawn[bug] += 1
                case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A binary16 comparison bug ({bug}) escaped detection in {name} for words {words}")
        assert all(count > 0 for count in drawn.values()), (name, drawn)


# Integer add, subtract, multiply and three-input forms. The same shape as INT_PROGRAMS: body, a reference over the
# four constant words, the constant sets, and wrong references (channel, function) that must each be detected.
# Results that need a vector source are copied with v_or_b32 so that no word passes through a float register.
u24 = lambda value: value & 0xffffff
i24 = lambda value: (value & 0xffffff) - (1 << 24) if value & 0x800000 else value & 0xffffff
hi_u = lambda a, b: (a * b) >> 32
hi_i = lambda a, b: ((signed(a) * signed(b)) >> 32) & M32
sat_u = lambda value: min(max(value, 0), M32)
sat_i = lambda value: (min(max(value, -(1 << 31)), (1 << 31) - 1)) & M32


def copy(dst, src):
    return f"v_or_b32_e64 v{dst}, {src}, 0"


ARITH_PROGRAMS = (
    # VOP2 add and subtract, e32 and e64: wrapping sums, subtraction order, a literal in the e64 form.
    ([
        copy(18, "s44"),
        "v_add_nc_u32_e32 v19, s45, v18",
        "v_sub_nc_u32_e32 v20, s45, v18",
        "v_subrev_nc_u32_e32 v21, s45, v18",
        "v_subrev_nc_u32_e64 v22, s46, 0x7fff0001",
        ubyte(3, 12, "v19", "e32"), ubyte(0, 13, "v20", "e32"), ubyte(2, 14, "v21", "e64"), ubyte(1, 15, "v22", "e64"),
    ], lambda x, y, z, w: [byte((y + x) & M32, 3), byte((y - x) & M32, 0), byte((x - y) & M32, 2),
                           byte((0x7fff0001 - z) & M32, 1)],
     ((0xa5c3e187, 0xc2f0171d, 0x3d1e8f2b, 0), (0x13579bdf, 0x2468ace0, 0xf1e2d3c4, 0)),
     [(0, lambda x, y, z, w: byte(min(x + y, M32), 3)),  # saturating instead of wrapping
      (1, lambda x, y, z, w: byte((x - y) & M32, 0)),  # sub with the operands swapped
      (2, lambda x, y, z, w: byte((y - x) & M32, 2)),  # subrev as sub
      (3, lambda x, y, z, w: byte((z - 0x7fff0001) & M32, 1))]),  # subrev as sub
    # VOP3 clamp on the unsigned add, sub and subrev: saturation at both ends.
    ([
        "v_add_nc_u32_e64 v19, s44, s45 clamp",
        "v_sub_nc_u32_e64 v20, s44, s45 clamp",
        "v_subrev_nc_u32_e64 v21, s44, s45 clamp",
        "v_add_nc_u32_e64 v22, s44, s45",
        ubyte(0, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(2, 14, "v21", "e32"), ubyte(1, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(sat_u(x + y), 0), byte(sat_u(x - y), 3), byte(sat_u(y - x), 2), byte((x + y) & M32, 1)],
     ((0xa5c3e187, 0xc2f0171d, 0, 0), (0x93f1c2d4, 0x5a1b7e69, 0, 0)),
     [(0, lambda x, y, z, w: byte((x + y) & M32, 0)),  # clamp ignored
      (1, lambda x, y, z, w: byte((x - y) & M32, 3)),  # clamp ignored
      (2, lambda x, y, z, w: byte(sat_u(x - y), 2)),  # operands swapped
      (2, lambda x, y, z, w: byte((y - x) & M32, 2)),  # clamp ignored
      (3, lambda x, y, z, w: byte(sat_u(x + y), 1))]),  # clamp applied to the wrapping form
    # VOP3-only signed add and subtract: wrap, and clamp to INT_MAX and INT_MIN.
    ([
        "v_add_nc_i32 v19, s44, s45 clamp",
        "v_add_nc_i32 v20, s44, s45",
        "v_sub_nc_i32 v21, s44, s47 clamp",
        "v_sub_nc_i32_e64 v22, s44, s47",
        ubyte(3, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(sat_i(signed(x) + signed(y)), 3), byte((x + y) & M32, 3),
                           byte(sat_i(signed(x) - signed(w)), 3), byte((x - w) & M32, 3)],
     ((0x7ffffff0, 0x00000100, 0, 0xffffff00), (0x80000010, 0xffffff00, 0, 0x00000100),
      (0x00000010, 0xfffffff0, 0, 0xffffff00)),
     [(0, lambda x, y, z, w: byte(sat_u(x + y), 3)),  # unsigned saturation
      (0, lambda x, y, z, w: byte((x + y) & M32, 3)),  # clamp ignored
      (1, lambda x, y, z, w: byte(sat_i(signed(x) + signed(y)), 3)),  # clamp applied to the wrapping form
      (2, lambda x, y, z, w: byte(sat_u(x - w), 3)),  # unsigned saturation
      (2, lambda x, y, z, w: byte((x - w) & M32, 3)),  # clamp ignored
      (3, lambda x, y, z, w: byte(sat_i(signed(x) - signed(w)), 3))]),  # clamp applied to the wrapping form
    # 24-bit multiplies, low half: operands masked to 24 bits, i24 sign-extended from bit 23.
    ([
        copy(18, "s44"),
        "v_mul_u32_u24_e32 v19, s45, v18",
        "v_mul_i32_i24_e32 v20, s45, v18",
        "v_mul_i32_i24_e64 v21, s46, 0x00fffff1",
        "v_mul_u32_u24_e64 v22, 0x01000003, s47",
        ubyte(3, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((u24(y) * u24(x)) & M32, 3), byte((i24(y) * i24(x)) & M32, 3),
                           byte((i24(z) * -15) & M32, 3), byte((3 * u24(w)) & M32, 3)],
     ((0xa5c3e187, 0x3c1b7e69, 0xc2f0171d, 0x6d1e8f2b), (0x93f1c2d4, 0x5a96b45a, 0x4be3a05c, 0x1c2d3e4f)),
     [(0, lambda x, y, z, w: byte((y * x) & M32, 3)),  # no 24-bit mask
      (1, lambda x, y, z, w: byte((u24(y) * u24(x)) & M32, 3)),  # unsigned for signed
      (2, lambda x, y, z, w: byte((u24(z) * 0xfffff1) & M32, 3)),  # unsigned for signed
      (3, lambda x, y, z, w: byte((0x01000003 * w) & M32, 3))]),  # no 24-bit mask
    # 24-bit multiplies, high half: bits 47:32 of the unsigned product, bits 63:32 of the sign-extended product.
    ([
        copy(18, "s44"),
        "v_mul_hi_u32_u24_e32 v19, s45, v18",
        "v_mul_hi_i32_i24_e32 v20, s45, v18",
        "v_mul_hi_u32_u24_e64 v21, s46, s47",
        "v_mul_hi_i32_i24_e64 v22, s46, s47",
        ubyte(0, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(1, 14, "v21", "e32"), ubyte(0, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(hi_u(u24(y), u24(x)), 0), byte(((i24(y) * i24(x)) >> 32) & M32, 3),
                           byte(hi_u(u24(z), u24(w)), 1), byte(((i24(z) * i24(w)) >> 32) & M32, 0)],
     ((0xa5c3e187, 0x3c1b7e69, 0xc2f0171d, 0x6d1e8f2b), (0x93f1c2d4, 0x5a96b45a, 0x4be3a05c, 0x1c2d3e4f),
      (0x0123456f, 0x7a5c3b2d, 0x7d3e1f2c, 0x1b2c3d4e)),
     [(0, lambda x, y, z, w: byte((u24(y) * u24(x)) & M32, 0)),  # low half
      (0, lambda x, y, z, w: byte(hi_u(y, x), 0)),  # no 24-bit mask
      (1, lambda x, y, z, w: byte(hi_u(u24(y), u24(x)), 3)),  # unsigned for signed
      (1, lambda x, y, z, w: byte((i24(y) * i24(x)) & M32, 3)),  # low half
      (2, lambda x, y, z, w: byte((u24(z) * u24(w)) & M32, 1)),  # low half
      (3, lambda x, y, z, w: byte(hi_u(u24(z), u24(w)), 0)),  # unsigned for signed
      (3, lambda x, y, z, w: byte((i24(z) * i24(w)) & M32, 0))]),  # low half
    # VOP3-only 32-bit multiplies: low word, unsigned high word, signed high word with mixed and equal signs.
    ([
        "v_mul_lo_u32 v19, s44, s45",
        "v_mul_hi_u32 v20, s44, s45",
        "v_mul_hi_i32 v21, s44, s46",
        "v_mul_hi_i32_e64 v22, s46, s47",
        ubyte(2, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(1, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((x * y) & M32, 2), byte(hi_u(x, y), 3), byte(hi_i(x, z), 3), byte(hi_i(z, w), 1)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0xc4e3a05c, 0x8c8d9f10),
      (M32, M32, 0x7fffffff, 0x80000000)),
     [(0, lambda x, y, z, w: byte(hi_u(x, y), 2)),  # high word for low
      (1, lambda x, y, z, w: byte((x * y) & M32, 3)),  # low word for high
      (1, lambda x, y, z, w: byte(hi_i(x, y), 3)),  # signed for unsigned
      (2, lambda x, y, z, w: byte(hi_u(x, z), 3)),  # unsigned for signed
      (3, lambda x, y, z, w: byte(hi_u(z, w), 1)),  # unsigned for signed
      (3, lambda x, y, z, w: byte((z * w) & M32, 1))]),  # low word for high
    # Multiply-add with 24-bit operands: the addend is the third source; literal, inline constants.
    ([
        copy(18, "s46"),
        "v_mad_u32_u24 v19, s44, s45, v18",
        "v_mad_i32_i24 v20, s44, v18, s47",
        "v_mad_u32_u24 v21, 0x01000005, s46, 7",
        "v_mad_i32_i24_e64 v22, v18, -3, s47",
        ubyte(3, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((u24(x) * u24(y) + z) & M32, 3), byte((i24(x) * i24(z) + w) & M32, 3),
                           byte((5 * u24(z) + 7) & M32, 3), byte((i24(z) * -3 + w) & M32, 3)],
     ((0xa5c3e187, 0x3c1b7e69, 0xc2f0171d, 0x6d1e8f2b), (0x93f1c2d4, 0x5a96b45a, 0x4be3a05c, 0x1c2d3e4f)),
     [(0, lambda x, y, z, w: byte((u24(x) * u24(z) + y) & M32, 3)),  # operands in the wrong slots
      (0, lambda x, y, z, w: byte((x * y + z) & M32, 3)),  # no 24-bit mask
      (1, lambda x, y, z, w: byte((u24(x) * u24(z) + w) & M32, 3)),  # unsigned for signed
      (1, lambda x, y, z, w: byte((i24(x) * i24(w) + z) & M32, 3)),  # operands in the wrong slots
      (2, lambda x, y, z, w: byte((0x01000005 * z + 7) & M32, 3)),  # no 24-bit mask
      (3, lambda x, y, z, w: byte((u24(z) * 0xfffffd + w) & M32, 3))]),  # unsigned for signed
    # Three-input adds and bitwise forms; the operand order matters for and_or.
    ([
        copy(18, "s46"),
        "v_add3_u32 v19, s44, s45, v18",
        "v_and_or_b32 v20, s44, v18, s45",
        "v_or3_b32 v21, s44, 0x0000f0f0, v18",
        "v_xor3_b32_e64 v22, v18, s45, s47",
        ubyte(2, 12, "v19", "e32"), ubyte(0, 13, "v20", "e32"), ubyte(1, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((x + y + z) & M32, 2), byte((x & z) | y, 0), byte(x | 0xf0f0 | z, 1), byte(z ^ y ^ w, 3)],
     ((0xa5c3e187, 0x3c96b45a, 0xc2f0171d, 0x6d1e8f2b), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
     [(0, lambda x, y, z, w: byte((x + y) & M32, 2)),  # third source dropped
      (1, lambda x, y, z, w: byte((x & y) | z, 0)),  # operands in the wrong slots
      (1, lambda x, y, z, w: byte((x & z) & y, 0)),  # and for or
      (2, lambda x, y, z, w: byte(x | 0xf0f0, 1)),  # third source dropped
      (3, lambda x, y, z, w: byte(z | y | w, 3)),  # or for xor
      (3, lambda x, y, z, w: byte(z ^ y, 3))]),  # third source dropped
    # xad, and the shift-add forms: counts masked to five bits, counts above 31 in an SGPR and as an inline constant.
    ([
        copy(18, "s46"),
        copy(23, "s47"),
        "v_xad_u32 v19, s44, s45, v18",
        "v_lshl_add_u32 v20, s44, s45, v18",
        "v_add_lshl_u32 v21, s44, s45, v23",
        "v_lshl_or_b32 v22, s44, 33, v18",
        ubyte(1, 12, "v19", "e32"), ubyte(2, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(0, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(((x ^ y) + z) & M32, 1), byte(((x << (y & 31)) + z) & M32, 2),
                           byte(((x + y) << (w & 31)) & M32, 3), byte(((x << 1) | z) & M32, 0)],
     ((0xa5c3e187, 0x00000025, 0xc2f0171d, 0x0000003b), (0x83d5f2a9, 0x00000043, 0x13572468, 0x00000041),
      (0x12345678, 0x0000000d, 0x9abcdef0, 0x00000007)),
     [(0, lambda x, y, z, w: byte((((x + y) & M32) ^ z), 1)),  # add then xor
      (0, lambda x, y, z, w: byte(((x ^ y) ^ z), 1)),  # xor for add
      (1, lambda x, y, z, w: byte(((x << y) + z) & M32 if y < 32 else z, 2)),  # count not masked
      (1, lambda x, y, z, w: byte(((y << (x & 31)) + z) & M32, 2)),  # operands in the wrong slots
      (2, lambda x, y, z, w: byte(((x + y) << w) & M32 if w < 32 else 0, 3)),  # count not masked
      (2, lambda x, y, z, w: byte((x + (y << (w & 31))) & M32, 3)),  # shift applied to the wrong operand
      (3, lambda x, y, z, w: byte(z, 0)),  # count not masked
      (3, lambda x, y, z, w: byte(((x << 1) + z) & M32, 0))]),  # add for or
    # e32 spellings with a literal and with inline constants, the 24-bit mask of an all-ones constant.
    ([
        copy(18, "s44"),
        "v_add_nc_u32_e32 v19, 0x7ff00001, v18",
        "v_sub_nc_u32_e32 v20, 7, v18",
        "v_mul_hi_u32_u24_e32 v21, 0x00fedcba, v18",
        "v_mul_u32_u24_e32 v22, -1, v18",
        ubyte(2, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(0, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((0x7ff00001 + x) & M32, 2), byte((7 - x) & M32, 3), byte(hi_u(0xfedcba, u24(x)), 0),
                           byte((0xffffff * u24(x)) & M32, 3)],
     ((0xa5c3e187, 0, 0, 0), (0x93f1c2d4, 0, 0, 0)),
     [(0, lambda x, y, z, w: byte((0x7ff00001 + x) & M32, 3)),  # wrong byte
      (1, lambda x, y, z, w: byte((x - 7) & M32, 3)),  # operands swapped
      (2, lambda x, y, z, w: byte(hi_u(0xfedcba, x), 0)),  # no 24-bit mask
      (3, lambda x, y, z, w: byte((M32 * x) & M32, 3))]),  # no 24-bit mask on the constant
)


def check_arith_draws(directory, compiler, renderer, backend):
    case = directory / "arith.case"
    for index, (body, reference, sets, bugs) in enumerate(ARITH_PROGRAMS):
        source = directory / f"arith{index}.hlsl"
        shader = directory / f"arith{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = [False] * len(bugs)
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = [float(value) for value in reference(*words)]
            for x in expected:
                assert half_rtz(x) == x, x
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for k, (channel, buggy) in enumerate(bugs):
                value = float(buggy(*words))
                if value == expected[channel]:
                    continue
                separated[k] = True
                assert half_rtz(value) == value, value
                wrong_values = list(expected)
                wrong_values[channel] = value
                case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong arithmetic result escaped detection in program {index}, channel {channel}, words {words}")
        assert all(separated), (index, separated)


# MUBUF and global loads through runtime V# words and title memory. The constant buffer holds the inputs in words 3 to 6
# (loaded into s44 to s47 by with_constants) and three V# in words 8 to 11, 12 to 15 and 16 to 19; the descriptor-table
# entries at byte offsets 0x80, 0x90 and 0xa0 name those words, and each buffer program loads them into s[52:55],
# s[56:59] and s[60:63]. Memory is the pixel_memory_check section: slot 0 at 0xffffff00 (0x200 bytes, so it crosses the
# 4 GiB line at offset 0x100) and slot 1 at 0x200000400 (0x100 bytes); data exists on both sides of every limit a V#
# sets, so a missing check shows. Byte N of a loaded dword is read with v_cvt_f32_ubyteN. Integer words reach address
# registers through v_or_b32 with 0, not v_mov_b32, so no float conversion is involved. The references follow the gfx10
# rules of Mesa's ac_set_buf_desc_word3 (see tools/pixel_aot.py) on Python integers; a "flaw" switches one rule off to
# make a plausible wrong reference.
VSHARP_OFFSETS = {0x80: 8, 0x90: 12, 0xa0: 16}
BASE0, SIZE0, BASE1, SIZE1 = titlemem.BASE0, titlemem.SIZE0, titlemem.BASE1, titlemem.SIZE1
RANGES = ((BASE0, BASE0 + SIZE0, 0), (BASE1, BASE1 + SIZE1, 1))
LOAD_MEMORY = titlemem.section(RANGES, titlemem.SLOTS)
NOISE = (1 << 24) | (0x14 << 12) | 0xfac  # RESOURCE_LEVEL, a FORMAT value and DST_SEL_XYZW: fields the loads ignore
ZERO = (0, 0, 0, 0)


def translate_loads(instructions):
    return lower(instructions, 20, 24, [1, 2, 3, 4], constant_descriptor=64, buffer_descriptors=VSHARP_OFFSETS)


def vsharp(base, stride, records, select, swizzle=False, add_tid=False):
    assert base >> 48 == 0 and stride < 1 << 14
    return (base & M32, (base >> 32) | stride << 16 | swizzle << 31, records, NOISE | select << 28 | add_tid << 23)


def title_word(address):
    for begin, end, slot in RANGES:
        if begin <= address and address + 4 <= end and address % 4 == 0:
            return int.from_bytes(titlemem.SLOTS[slot][address - begin:address - begin + 4], "little")
    return None  # a lookup miss


def effective(terms, flaws):
    if "nocarry" in flaws:  # each 32-bit half summed on its own
        return (sum(t >> 32 for t in terms) << 32 | sum(t & M32 for t in terms) & M32) % (1 << 64)
    return sum(terms) % (1 << 64)


def settle(words, flaws):
    """Turn per-dword outcomes ('oob', 'miss' or a value) into the destination registers."""
    if "swap_dwords" in flaws:
        words = words[::-1]
    if "all_or_nothing" in flaws and "oob" in words:
        return [0] * len(words)
    out = []
    for word in words:
        if word == "miss" and "stale" in flaws:
            out.append(out[-1] if out else 0x5a5a5a5a)  # the previous register's value instead of 0
        else:
            out.append(0 if isinstance(word, str) else word)
    return out


def buffer_load(vs, soffset, voffset, inst, index, count, flaws=()):
    base, stride, records, select = vs[0] | (vs[1] & 0xffff) << 32, (vs[1] >> 16) & 0x3fff, vs[2], (vs[3] >> 28) & 3
    inst, soffset, index = (0 if "noinst" in flaws else inst), (0 if "nosoffset" in flaws else soffset), (0 if "noindex" in flaws else index)
    words = []
    for j in range(count):
        offset = voffset + inst + 4 * j
        index_out = index > records if "index_gt" in flaws else index >= records
        in_range = (not index_out and not (offset > stride if "isa_offset" in flaws else offset >= stride),
                    not index_out and not ("offset_in_mode1" in flaws and offset >= stride),
                    records != 0 and not ("index_check_mode2" in flaws and index >= records),
                    offset <= records if "le_records" in flaws else offset < records)[select]
        if offset >= 1 << 32 or vs[1] >> 31 or (vs[3] >> 23) & 1 or not (in_range or "nocheck" in flaws):
            words.append("oob")
            continue
        product = 0 if "nostride" in flaws else stride * index
        product &= M32 if "mul32" in flaws else (1 << 64) - 1
        word = title_word(effective([base, soffset, product, offset], flaws))
        words.append("miss" if word is None else word)
    return settle(words, flaws)


def global_load(base, voffset, inst, count, flaws=()):
    inst = 0 if "no_imm" in flaws else abs(inst) if "abs_imm" in flaws else inst & M32 if "imm_zext" in flaws else inst
    voffset = 0 if "no_voffset" in flaws else voffset
    words = [title_word(effective([base, voffset, inst % (1 << 64), 4 * j], flaws)) for j in range(count)]
    return settle(["miss" if w is None else w for w in words], flaws)


def load_program(*lines):
    return ["s_load_dwordx4 s[52:55], s[20:21], 0x80", "s_load_dwordx4 s[56:59], s[20:21], 0x90",
            "s_load_dwordx4 s[60:63], s[20:21], 0xa0", "s_waitcnt lgkmcnt(0)", *lines]


def global_program(*lines):
    return list(lines)


def readback(*pairs):
    return [ubyte(n, 12 + channel, f"v{register}", "e32") for channel, (register, n) in enumerate(pairs)]


def move(register, source):
    return f"v_or_b32_e64 v{register}, 0, {source}"


def bytes_of(values, *picks):
    return [byte(values[k], n) for k, n in picks]


def ref_addressing(w, v, f=()):
    return [byte(buffer_load(v[0], w[0], w[1], 8, 0, 1, f)[0], 0), byte(buffer_load(v[0], 0, 0, 4, w[2], 1, f)[0], 1),
            byte(buffer_load(v[0], w[0], w[1], 12, w[2], 1, f)[0] if "swap" not in f else
                 buffer_load(v[0], w[0], w[2], 12, w[1], 1)[0], 2),
            byte(buffer_load(v[0], w[0], 0, 16, 0, 1, f)[0], 3)]


def ref_structured(w, v, f=()):
    return [byte(buffer_load(v[0], 0, 0, 28, w[0], 1, f)[0], 0), byte(buffer_load(v[0], 0, w[1], 0, 0, 1, f)[0], 1),
            byte(buffer_load(v[1], 0, 0, 0, w[2], 1, f)[0], 2), byte(buffer_load(v[1], 0, w[3], 0, 0, 1, f)[0], 3)]


def ref_modes23(w, v, f=()):
    return [byte(buffer_load(v[0], 0, w[0], 0, 0, 1, f)[0], 0), byte(buffer_load(v[0], 0, 0, 0, w[1], 1, f)[0], 1),
            byte(buffer_load(v[1], w[3], w[2], 0, 0, 1, f)[0], 2), byte(buffer_load(v[1], w[3], w[2], 4, 0, 1, f)[0], 3)]


def ref_x4(w, v, f=()):
    return bytes_of(buffer_load(v[0], 0, w[0], 0, 0, 4, f), (0, 0), (1, 0), (2, 0), (3, 0))


def ref_x2x3(w, v, f=()):
    x2, x3 = buffer_load(v[0], 0, w[0], 0, 0, 2, f), buffer_load(v[0], 0, w[1], 0, 0, 3, f)
    return [byte(x2[0], 1), byte(x2[1], 0), byte(x3[1], 2), byte(x3[2], 3)]


def ref_carry(w, v, f=()):
    return bytes_of(buffer_load(v[0], w[0], w[1], 0, 0, 4, f), (0, 0), (1, 0), (2, 0), (3, 0))


def ref_wide_stride(w, v, f=()):
    return [byte(buffer_load(v[0], 0, 0, 16, w[0], 1, f)[0], 0), byte(buffer_load(v[0], 0, w[1], 4, w[0], 1, f)[0], 1),
            byte(buffer_load(v[0], w[2], 0, 0, w[0], 1, f)[0], 2), byte(buffer_load(v[0], 0, 0, 0x28, w[0], 1, f)[0], 3)]


def ref_global(w, v, f=()):
    base = w[0] | w[1] << 32
    g3 = global_load(w[3] | w[1] << 32, 0, -2048, 2, f)
    return [byte(global_load(base, 0, -16, 1, f)[0], 0), byte(global_load(base, w[2], 8, 1, f)[0], 1),
            byte(g3[0], 2), byte(g3[1], 3)]


def ref_global_carry(w, v, f=()):
    base = w[0] | w[1] << 32
    x3, x4 = global_load(base, w[2], 0, 3, f), global_load(base, 0, 4, 4, f)
    return [byte(x3[1], 0), byte(x3[2], 0), byte(x4[1], 0), byte(x4[2], 0)]


STRIDE_INDEX = 0x50000
STRIDE_BASE = BASE1 + 0x80 - 0x3ffc * STRIDE_INDEX  # base + stride * index lands in slot 1 only if the product keeps all 64 bits
assert 0 < STRIDE_BASE < 1 << 48 and 0x3ffc * STRIDE_INDEX >> 32

LOAD_PROGRAMS = (
    # Structured V# (OOB_SELECT 0, stride 0x20, base in slot 1, so base bits 32 to 47 share word 1 with the stride):
    # offen, idxen, both (index in the first register) and neither, with soffset (s44) and the instruction offset.
    (load_program(
        move(18, "s45"), move(19, "s46"), move(22, "s46"), move(23, "s45"),
        "buffer_load_dword v24, v18, s[52:55], s44 offen offset:8",
        "buffer_load_dword v25, v19, s[52:55], 0 idxen offset:4",
        "buffer_load_dword v26, v[22:23], s[52:55], s44 idxen offen offset:12",
        "buffer_load_dword v27, off, s[52:55], s44 offset:16",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((0x40, 4, 3, 0), (vsharp(BASE1, 0x20, 8, 0), ZERO, ZERO)),
      ((0x20, 0x10, 5, 0), (vsharp(BASE1, 0x20, 8, 0), ZERO, ZERO))],
     ref_addressing,
     [(0, {"nosoffset"}), (1, {"nostride"}), (2, {"swap"}), (3, {"noinst"}), (1, {"noindex"})]),
    # OOB_SELECT 0 (index < records and offset < stride) and 1 (index < records): set 1 reads the last dword inside each
    # limit, set 2 the first dword outside it. The offset is not checked in mode 1.
    (load_program(
        move(18, "s44"), move(19, "s45"), move(20, "s46"), move(22, "s47"), move(23, "s47"),
        "v_and_b32_e64 v21, 0, s44",
        "buffer_load_dword v24, v18, s[52:55], 0 idxen offset:28",
        "buffer_load_dword v25, v19, s[52:55], 0 offen",
        "buffer_load_dword v26, v20, s[56:59], 0 idxen",
        "buffer_load_dword v27, v[21:22], s[56:59], 0 idxen offen",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((3, 0x1c, 5, 0x24), (vsharp(BASE1, 0x20, 4, 0), vsharp(BASE1 + 0x10, 0x10, 6, 1), ZERO)),
      ((4, 0x20, 6, 0x24), (vsharp(BASE1, 0x20, 4, 0), vsharp(BASE1 + 0x10, 0x10, 6, 1), ZERO))],
     ref_structured,
     [(0, {"nocheck"}), (0, {"index_gt"}), (1, {"nocheck"}), (1, {"isa_offset"}), (2, {"nocheck"}), (2, {"index_gt"}),
      (3, {"offset_in_mode1"})]),
    # OOB_SELECT 2 (num_records == 0 only; the index and offset are unchecked, and stride 0 ignores the index) and 3
    # (raw, offset < num_records, soffset outside the check).
    (load_program(
        move(18, "s44"), move(19, "s45"), move(20, "s46"),
        "buffer_load_dword v24, v18, s[52:55], 0 offen",
        "buffer_load_dword v25, v19, s[52:55], 0 idxen",
        "buffer_load_dword v26, v20, s[56:59], s47 offen",
        "buffer_load_dword v27, v20, s[56:59], s47 offen offset:4",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((0x10, 1000, 0x1c, 0x20), (vsharp(BASE0 + 0x40, 0, 1, 2), vsharp(BASE0 + 0x80, 0, 0x20, 3), ZERO)),
      ((0x10, 1000, 0x18, 0x40), (vsharp(BASE0 + 0x40, 0, 0, 2), vsharp(BASE0 + 0x80, 0, 0x20, 3), ZERO))],
     ref_modes23,
     [(0, {"nocheck"}), (1, {"nocheck"}), (1, {"index_check_mode2"}), (2, {"nosoffset"}), (3, {"nocheck"}), (3, {"le_records"})]),
    # buffer_load_dwordx4: every dword in order, then a window that crosses num_records so that only the first two
    # dwords are in range (each dword is checked on its own).
    (load_program(
        move(18, "s44"),
        "buffer_load_dwordx4 v[24:27], v18, s[52:55], 0 offen glc slc dlc",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 0), (26, 0), (27, 0))),
     [((0x08, 0, 0, 0), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO, ZERO)),
      ((0x28, 0, 0, 0), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO, ZERO))],
     ref_x4,
     [(0, {"swap_dwords"}), (3, {"swap_dwords"}), (2, {"nocheck"}), (0, {"all_or_nothing"})]),
    # buffer_load_dwordx2 and x3, the same window rule, and a different byte of each dword.
    (load_program(
        move(18, "s44"), move(19, "s45"),
        "buffer_load_dwordx2 v[24:25], v18, s[52:55], 0 offen",
        "buffer_load_dwordx3 v[26:28], v19, s[52:55], 0 offen",
        "s_waitcnt vmcnt(0)", *readback((24, 1), (25, 0), (27, 2), (28, 3))),
     [((0x20, 0x24, 0, 0), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO, ZERO)),
      ((0x2c, 0x28, 0, 0), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO, ZERO))],
     ref_x2x3,
     [(0, {"swap_dwords"}), (1, {"swap_dwords"}), (3, {"swap_dwords"}), (1, {"nocheck"}), (3, {"nocheck"}), (0, {"all_or_nothing"})]),
    # Address carries: base 0xfffffff0 plus soffset 0x20 crosses 4 GiB, and base plus voffset 8 plus 4 * dword does too.
    (load_program(
        move(18, "s45"),
        "buffer_load_dwordx4 v[24:27], v18, s[52:55], s44 offen",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 0), (26, 0), (27, 0))),
     [((0x20, 0, 0, 0), (vsharp(0xfffffff0, 0, 0x100, 3), ZERO, ZERO)),
      ((0, 8, 0, 0), (vsharp(0xfffffff0, 0, 0x100, 3), ZERO, ZERO))],
     ref_carry,
     [(0, {"nocarry"}), (2, {"nocarry"})]),
    # A lookup miss inside num_records: the V# allows 0x100 bytes, but title memory ends 0x40 bytes after the base. The
    # window crosses that end, so the first two dwords hit and the last two miss and read 0.
    (load_program(
        move(18, "s44"),
        "buffer_load_dwordx4 v[24:27], v18, s[52:55], 0 offen",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 0), (26, 0), (27, 0))),
     [((0x38, 0, 0, 0), (vsharp(BASE0 + 0x1c0, 0, 0x100, 3), ZERO, ZERO)),
      ((0x30, 0, 0, 0), (vsharp(BASE0 + 0x1c0, 0, 0x100, 3), ZERO, ZERO))],
     ref_x4,
     [(2, {"stale"}), (3, {"stale"}), (0, {"swap_dwords"})]),
    # base + stride * index needs more than 32 bits: 0x3ffc * 0x50000 is above 4 GiB, and the base makes the sum land in slot 1.
    (load_program(
        move(18, "s44"), move(22, "s44"), move(23, "s45"),
        "buffer_load_dword v24, v18, s[52:55], 0 idxen offset:16",
        "buffer_load_dword v25, v[22:23], s[52:55], 0 idxen offen offset:4",
        "buffer_load_dword v26, v18, s[52:55], s46 idxen",
        "buffer_load_dword v27, v18, s[52:55], 0 idxen offset:40",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((STRIDE_INDEX, 0x14, 0x20, 0), (vsharp(STRIDE_BASE, 0x3ffc, 0x60000, 0), ZERO, ZERO))],
     ref_wide_stride,
     [(0, {"mul32"}), (1, {"mul32"}), (2, {"nosoffset"}), (3, {"nostride"})]),
    # global_load: a 64-bit VGPR pair with a negative immediate, an SGPR base plus a 32-bit VGPR offset, and an x2 load whose
    # base is 2048 above its data (the most negative 12-bit immediate).
    (global_program(
        move(18, "s44"), move(19, "s45"), move(20, "s46"), move(21, "s47"), move(22, "s45"),
        "global_load_dword v24, v[18:19], off offset:-16",
        "global_load_dword v25, v20, s[44:45] offset:8",
        "global_load_dwordx2 v[26:27], v[21:22], off offset:-2048 glc",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((BASE1 + 0x40 & M32, 2, 0x10, BASE1 + 0x20 + 2048 & M32), (ZERO, ZERO, ZERO)),
      ((0x80, 1, 0x20, 0x8e0), (ZERO, ZERO, ZERO))],
     ref_global,
     [(0, {"imm_zext"}), (0, {"abs_imm"}), (1, {"no_voffset"}), (2, {"no_imm"}), (3, {"no_imm"})]),
    # global_load carries and misses: x3 with an SGPR base and x4 with a register pair from 0xfffffff8, which crosses 4 GiB
    # inside the dwords; then a base at the end of title memory, where the later dwords miss and read 0.
    (global_program(
        move(18, "s44"), move(19, "s45"), move(20, "s46"),
        "global_load_dwordx3 v[26:28], v20, s[44:45]",
        "global_load_dwordx4 v[30:33], v[18:19], off offset:4 dlc",
        "s_waitcnt vmcnt(0)", *readback((27, 0), (28, 0), (31, 0), (32, 0))),
     [((0xfffffff8, 0, 0, 0), (ZERO, ZERO, ZERO)),
      ((0xf8, 1, 0, 0), (ZERO, ZERO, ZERO))],
     ref_global_carry,
     [(1, {"nocarry"}), (2, {"nocarry"}), (1, {"swap_dwords"}), (1, {"stale"}), (2, {"stale"})]),
)


def check_load_draws(directory, compiler, renderer, backend):
    case = directory / "loads.case"
    for index, (body, sets, reference, bugs) in enumerate(LOAD_PROGRAMS):
        source = directory / f"load{index}.hlsl"
        shader = directory / f"load{index}.cso"
        source.write_text(translate_loads(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = [False] * len(bugs)
        for inputs, sharps in sets:
            words = [0] * 64
            words[3:7] = inputs
            words[8:20] = [word for vs in sharps for word in vs]
            expected = [float(value) for value in reference(inputs, sharps)]
            for value in expected:
                assert half_rtz(value) == value, value
            case.write_bytes(titlemem.case_file(words, expected, LOAD_MEMORY))
            subprocess.run(draw, check=True)
            for k, (channel, flaws) in enumerate(bugs):
                value = float(reference(inputs, sharps, flaws)[channel])
                if value == expected[channel]:
                    continue
                separated[k] = True
                wrong = list(expected)
                wrong[channel] = value
                case.write_bytes(titlemem.case_file(words, wrong, LOAD_MEMORY))
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong load result escaped detection in program {index}, channel {channel}, {sorted(flaws)}")
        assert all(separated), (index, separated)


def check_load_controls() -> None:
    wait = ["s_waitcnt lgkmcnt(0)"]
    descriptor = ["s_load_dwordx4 s[52:55], s[20:21], 0x80"]
    load = "buffer_load_dword v24, v18, s[52:55], 0 offen"
    ready = [move(18, "s45"), *descriptor, *wait]

    def buffer_case(*lines):
        return translate_loads(with_constants([*ready, *lines]))

    # Memory declarations and the title lookup are present only when a program loads, and V# words are runtime parameters.
    source = buffer_case(load, "s_waitcnt vmcnt(0)", ubyte(0, 12, "v24", "e32"))
    assert pixel_aot.TITLE_LOOKUP.read_text(encoding="utf-8") in source and pixel_aot.TITLE_DECLARATIONS in source, source
    assert "uint4 rsrc" in source and "asuint(params[2].x), asuint(params[2].y)" in source, source
    assert "title_memory" not in translate(curve()) and "TitleLookup" not in translate(curve())
    # A load's registers are unusable before vmcnt(0); a store over one, a V# not yet loaded and a bad window are refused.
    must_reject(translate_loads, with_constants([*ready, load, ubyte(0, 12, "v24", "e32")]))
    must_reject(translate_loads, with_constants([*ready, load, "v_or_b32_e64 v25, 0, v24"]))
    must_reject(translate_loads, with_constants([*ready, load, "v_add_f32_e64 v25, v24, 1.0"]))
    must_reject(translate_loads, with_constants([*ready, load, "v_or_b32_e64 v24, 0, s44"]))
    must_reject(translate_loads, with_constants([move(18, "s45"), *descriptor, load]))
    must_reject(translate_loads, with_constants([*ready, "s_waitcnt vmcnt(0)", ubyte(0, 12, "v24", "e32")]))
    # Descriptor offsets that overlap the texture descriptor (0 to 31) or the constant descriptor (0x40 to 0x4f), or are
    # misaligned, and buffer descriptors without a constant descriptor.
    program = with_constants([*ready, load, "s_waitcnt vmcnt(0)", ubyte(0, 12, "v24", "e32")])
    for offsets in ({0x10: 8}, {0x20: 8, 0x1c: 12}, {0x40: 8}, {0x3c: 8}, {0x84: 8}, {0x80: 61}, {0x80: -1}, {0x80: 8, 0x88: 12}):
        must_reject(lambda: lower(program, 20, 24, [1, 2, 3, 4], 64, buffer_descriptors=offsets))
    must_reject(lambda: lower(program, 20, 24, [1, 2, 3, 4], None, buffer_descriptors={0x80: 8}))
    must_reject(lambda: lower(program, 20, 24, [1, 2, 3, 4], 64, buffer_descriptors={0x80: 8}, second_texture_offset=0x80))
    must_reject(lambda: lower(program, 20, 24, [1, 2, 3, 4], 64))  # a descriptor that is not declared is still refused
    # flat loads, unsupported modifiers and malformed operands.
    must_reject(translate_loads, with_constants([move(18, "s45"), move(19, "s46"), "flat_load_dword v24, v[18:19]"]))
    for bad in ("buffer_load_dword v[24:25], v18, s[52:55], 0 offen tfe",
                "buffer_load_dword v24, v18, s[52:55], 0 offen lds",
                "buffer_load_dword v24, v18, s[52:55], 0 offen offset:4096",
                "buffer_load_dword v24, v18, s[52:55], 0 offen offen",
                "buffer_load_dword v24, v18, s[52:55], 0 offen glc glc",
                "buffer_load_dword v24, v18, s[52:55], 0",
                "buffer_load_dword v24, off, s[52:55], 0 offen",
                "buffer_load_dword v24, v18, s[52:55], 0 offen idxen",
                "buffer_load_dword v24, v18, s[53:56], 0 offen",
                "buffer_load_dword v24, v18, s[52:55], 1 offen",
                "buffer_load_dwordx2 v24, v18, s[52:55], 0 offen",
                "buffer_load_dwordx2 v[24:26], v18, s[52:55], 0 offen",
                "buffer_load_dword v24, v[18:19], s[52:55], 0 offen",
                "buffer_load_dword v24, v18, s[28:31], 0 offen",  # texture descriptor words are not numbers
                "buffer_load_dword v24, v30, s[52:55], 0 offen",
                "buffer_load_ubyte v24, v18, s[52:55], 0 offen",
                "buffer_load_format_x v24, v18, s[52:55], 0 offen",
                "buffer_store_dword v24, v18, s[52:55], 0 offen",
                "buffer_load_dword v24, v18, s[52:55], s70 offen"):
        must_reject(translate_loads, with_constants([*ready, bad]))
    for bad in ("global_load_dword v24, v[18:19], off tfe", "global_load_dword v24, v[18:19], off offset:2048",
                "global_load_dword v24, v[18:19], off offset:-2049", "global_load_dword v24, v18, off",
                "global_load_dword v24, v[18:19], s[44:45]", "global_load_dword v24, v20, s[45:46]",
                "global_load_dword v24, v20, s44", "global_load_dword v24, v[18:19], off offset:4 offset:4",
                "global_load_ubyte v24, v[18:19], off", "global_store_dword v[18:19], v24, off"):
        must_reject(translate_loads, with_constants([move(18, "s44"), move(19, "s45"), move(20, "s46"), bad]))


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


# v_fmaak_f32 computes S0 * S1 + K and v_fmamk_f32 computes S0 * K + S1, with K a 32-bit literal.
# Every product and sum is exact in binary32, so the reference does not depend on fusion. Swapping
# the literal with S1 changes each result.
LITERAL_FMA_INPUTS = (1.5, 2.5, -3.0, 0.75)
LITERAL_FMA_BODY = [
    "v_mov_b32_e32 v13, s45",
    "v_fmaak_f32 v12, s44, v13, 0x3e800000",
    "v_fmamk_f32 v13, s44, 0x40400000, v13",
    "v_mov_b32_e32 v15, s47",
    "v_fmaak_f32 v14, s46, v15, 0xbf000000",
    "v_fmamk_f32 v15, s46, 0x3f000000, v15",
]


def check_literal_fma_draw(directory, compiler, renderer, backend):
    source = directory / "literal_fma.hlsl"
    shader = directory / "literal_fma.cso"
    case = directory / "literal_fma.case"
    source.write_text(translate(with_constants(LITERAL_FMA_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, *LITERAL_FMA_INPUTS)
    a, b, c, d = LITERAL_FMA_INPUTS
    expected = [a * b + 0.25, a * 3.0 + b, c * d - 0.5, c * 0.5 + d]
    swapped = [a * 0.25 + b, a * b + 3.0, c * -0.5 + d, c * d + 0.5]
    for x in (*expected, *swapped):
        assert single(x) == x == half_rtz(x), x
    assert all(x != y for x, y in zip(expected, swapped))
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
    subprocess.run(draw, check=True)
    # Treating the literal as S1, or S1 as the literal, must change the exported color.
    for k in range(4):
        wrong_values = list(expected)
        wrong_values[k] = swapped[k]
        case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Swapped literal multiply-add operands escaped detection in channel {k}")


HINT_NAMES = ("s_clause", "s_setprio", "s_sleep")


def scheduling_hints():
    # Hints the compiler places between instructions. native_program ends the code at s_endpgm,
    # so s_code_end padding never reaches the translator and is not part of the fixture.
    program = assembly(False)
    program.insert(program.index("s_waitcnt vmcnt(0)"), "s_clause 0x1")
    program.insert(1, "s_setprio 2")
    program.insert(program.index("s_waitcnt vmcnt(0)"), "s_sleep 1")
    return program


def check_scheduling_hints():
    """Scheduling hints change timing only. Generated names carry the instruction index, so
    each hint must translate exactly like s_nop 0 at the same position."""
    plain = assembly(False)
    hinted = scheduling_hints()
    as_nops = [("s_nop 0" if line.split(" ")[0] in HINT_NAMES else line)
               for line in hinted]
    assert translate(hinted) == translate(as_nops)
    nop = translate(["s_nop 0"] + plain)
    for hint, limit in (("s_clause", 0x3f), ("s_setprio", 3), ("s_sleep", 0x7f)):
        assert translate([f"{hint} {limit}"] + plain) == nop
        assert translate([f"{hint} {hex(limit)}"] + plain) == nop
        must_reject(translate, [f"{hint} {limit + 1}"] + plain)
    # s_code_end stays unknown, and nothing may follow the program end or sit between the color
    # export and s_endpgm.
    must_reject(translate, ["s_code_end"] + plain)
    must_reject(translate, plain + ["s_code_end"])
    must_reject(translate, plain + ["s_nop 0"])
    must_reject(translate, plain[:-1] + ["s_setprio 0", plain[-1]])


def check_f16_cmp_controls():
    # Both sources are widened from their low halves and compared in binary32 (exact for binary16); the class is
    # read from the 16-bit encoding after the modifiers, and the mask stays a 32-bit integer.
    body = translate(with_constants(["v_mov_b32_e32 v18, s45", "v_cmp_nge_f16_e32 vcc_lo, s44, v18",
                                     "v_cmp_lt_f16_e64 s0, -0.5, |v18|"])).split("float4 main", 1)[1]
    for expected in ("precise float cmpa", "widen16((asuint(params[0].w) & 0xffffu))", "widen16(0xb800u)", "isnan(cmpa"):
        assert expected in body, expected
    body = translate(with_constants(["v_mov_b32_e32 v18, s46", "v_cmp_class_f16_e32 vcc_lo, s44, v18",
                                     "v_cmp_class_f16_e64 s0, -|s44|, 0x8c", "v_cmp_class_f16_e64 s1, 0.5, s47"])).split("float4 main", 1)[1]
    for expected in ("class16((((asuint(params[0].w) & 0xffffu) & 0x7fffu) ^ 0x8000u)) & 140u) != 0u",
                     "class16(0x3800u) & asuint(", "class16((asuint(params[0].w) & 0xffffu)) & asuint("):
        assert expected in body, expected
    assert translate(with_constants(["v_cmp_class_f16 vcc_lo, s44, 3"])) == translate(with_constants(["v_cmp_class_f16_e32 vcc_lo, s44, 3"]))
    for operation in ("v_cmp_lt_f16_e64 s0, s44, v13 op_sel:[1,0]", "v_cmp_lt_f16_e64 s0, s44, v13 op_sel:[0,1]",
                      "v_cmp_class_f16_e64 s0, s44, 3 op_sel:[1,0]",
                      "v_cmp_lt_f16_sdwa vcc_lo, s44, v13 src0_sel:WORD_1 src1_sel:WORD_0",
                      "v_cmp_class_f16_sdwa vcc_lo, s44, v13 src0_sel:WORD_0 src1_sel:DWORD",
                      "v_cmp_lt_f16_dpp vcc_lo, v13, v14 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
                      "v_cmpx_lt_f16_e32 s44, v13", "v_cmpx_class_f16_e32 s44, v13",
                      "v_cmp_class_f16_e64 s0, s44, 1.0", "v_cmp_class_f16_e64 s0, s44, 0.5",
                      "v_cmp_class_f16_e64 s0, s44, -s45", "v_cmp_class_f16_e64 s0, s44, |s45|",
                      "v_cmp_class_f16_e64 s0, s44, 0x123456789",
                      "v_cmp_lt_f16_e32 vcc_lo, 1.5, v13", "v_cmp_lt_f16_e32 vcc_lo, 65, v13",
                      "v_cmp_lt_f16_e32 vcc_lo, 0x12345, v13", "v_cmp_lt_f16_e64 s0, --s44, v13",
                      "v_cmp_lt_f16_e32 vcc_lo, s44", "v_cmp_class_f16_e64 s0, s44", "v_cmp_lt_f16_e32 vcc_lo, s44, v13, v14",
                      "v_cmp_lt_f16_e64 s0, s44, v13 clamp", "v_cmp_lt_f16_e64 s0, s44, v13 mul:2",
                      "v_cmp_lt_f16_e32 vcc_lo, s44, v30", "v_cmp_class_f16_e32 vcc_lo, s44, v30",
                      "v_cmp_class_f16_e32 vcc_lo, v30, s44"):
        must_reject(translate, with_constants([operation]))
    # A source cannot be read before the sample or the scalar load it depends on arrives.
    program = with_constants(["v_cmp_lt_f16_e32 vcc_lo, s44, v13"])
    translate(program)
    wait = program.index("s_waitcnt vmcnt(0)")
    for operation in ("v_cmp_lt_f16_e32 vcc_lo, s44, v13", "v_cmp_lt_f16_e32 vcc_lo, 0.5, v12",
                      "v_cmp_class_f16_e64 s0, v12, 3", "v_cmp_class_f16_e32 vcc_lo, 0x3c00, v13"):
        must_reject(translate, program[:wait] + [operation] + program[wait:])
    scalar_wait = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc"))
    for operation in ("v_cmp_lt_f16_e64 s0, s44, s47", "v_cmp_class_f16_e64 s0, s46, s47", "v_cmp_class_f16_e64 s0, 0.5, s47",
                      "v_cmp_class_f16_e64 s0, s47, 3"):
        must_reject(translate, program[:scalar_wait] + [operation] + program[scalar_wait:])
        translate(program[:scalar_wait + 1] + [operation] + program[scalar_wait + 1:])


# MIMG loads, level queries and gathers on the 8x8 R8G8B8A8 fixture texture, whose texel (x, y) is (RAMP[x], RAMP[y], 128, 255)
# and which has one mip level. Every coordinate comes from the case constants (or an inline constant) so the draw does not
# depend on the pixel. Outputs are exported directly, as unorm floats, or through v_cvt_f32_ubyte0 for the integer words of
# image_get_resinfo. The texture is square, so width and height are not told apart by the draws; there is one level, so
# a level above 0 is out of range. The wrong references are the plausible lowering bugs: swapped x and y, the first N
# channels instead of the dmask channels, clamped or wrapped coordinates, an ignored mip index, an unzeroed
# out-of-range level, a changed footprint order and the wrong gather component.
IMG = "dim:SQ_RSRC_IMG_2D"
SRC = "s[28:35]"
f32 = lambda x: struct.unpack("<f", struct.pack("<f", x))[0]
unorm_export = lambda byte_value: half_rtz(f32(byte_value / 255.0))
float_bits = lambda x: struct.unpack("<I", struct.pack("<f", x))[0]


def texel(x, y):
    """The fixture texel as bytes; any coordinate outside the 8x8 base level reads zero."""
    return (RAMP[x], RAMP[y], 128, 255) if x < 8 and y < 8 else (0, 0, 0, 0)


def pick(values, dmask):
    return [value for c, value in enumerate(values) if dmask >> c & 1]


def image_load_body(*loads):
    """loads: (op, destination, dmask, source sgprs, modifiers). Coordinates move to v18 and up, one group per load."""
    body = []
    first = 18
    for op, dst, dmask, sources, modifiers in loads:
        regs = []
        for source in sources:
            body.append(move(first + len(regs), source))
            regs.append(first + len(regs))
        address = f"v{regs[0]}" if len(regs) == 1 else f"v[{regs[0]}:{regs[-1]}]"
        body.append(f"image_{op} {dst}, {address}, {SRC} dmask:{dmask:#x} {IMG}{modifiers}")
        first += len(regs)
    return [*body, "s_waitcnt vmcnt(0)"]


def image_gather_body(op, dmask):
    return ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45",
            f"image_{op} v[12:15], v[18:19], {SRC}, s[40:43] dmask:{dmask:#x} {IMG}", "s_waitcnt vmcnt(0)"]


def info_body(*queries):
    """queries: (destination base, dmask, level sgpr). Outputs are v12..v15 from the listed result registers."""
    body = []
    for n, (base, dmask, level) in enumerate(queries):
        body.append(move(30 + n, level))
        count = bin(dmask).count("1")
        dst = f"v{base}" if count == 1 else f"v[{base}:{base + count - 1}]"
        body.append(f"image_get_resinfo {dst}, v{30 + n}, {SRC} dmask:{dmask:#x} {IMG}")
    return [*body, "s_waitcnt vmcnt(0)"]


def exported(*values):
    return [unorm_export(v) for v in values]


# (name, body, constant words, reference floats, wrong reference floats)
GATHER_WORDS = (float_bits(3.25 / 8), float_bits(5.75 / 8), 0, 0)
# At (3.25, 5.75) texels the footprint is columns 2 and 3 and rows 5 and 6. The order is lower left, lower right,
# upper right, upper left, so red is [37, 64, 64, 37] and green is [219, 219, 153, 153].
GL, GR, GT, GB = RAMP[2], RAMP[3], RAMP[5], RAMP[6]
IMAGE_PROGRAMS = (
    ("load", image_load_body(("load", "v[12:15]", 0xf, ("s44", "s45"), " unorm")), (2, 5, 0, 0),
     exported(*texel(2, 5)), [exported(*texel(5, 2))]),
    ("pack", image_load_body(("load", "v[12:13]", 0x5, ("s44", "s45"), " unorm glc"),
                             ("load", "v[14:15]", 0xa, ("s46", "s47"), " dlc")), (6, 1, 3, 4),
     exported(*pick(texel(6, 1), 0x5), *pick(texel(3, 4), 0xa)),
     [exported(*texel(6, 1)[:2], *texel(3, 4)[:2]), exported(*pick(texel(6, 1), 0x5), *texel(3, 4)[:2]),
      exported(*texel(6, 1)[:2], *pick(texel(3, 4), 0xa))]),
    ("single", image_load_body(("load", "v12", 0x2, ("s44", "s45"), ""), ("load", "v13", 0x8, ("s46", "s47"), ""),
                               ("load", "v14", 0x4, ("s44", "s45"), " unorm slc"), ("load", "v15", 0x1, ("s46", "s47"), " unorm")),
     (1, 6, 7, 0),
     exported(texel(1, 6)[1], texel(7, 0)[3], texel(1, 6)[2], texel(7, 0)[0]),
     [exported(texel(1, 6)[0], texel(7, 0)[1], texel(1, 6)[2], texel(7, 0)[0])]),
    ("edge", image_load_body(("load", "v[12:13]", 0x3, ("s44", "s45"), " unorm"), ("load", "v[14:15]", 0x3, ("s46", "s47"), " unorm")),
     (7, 7, 8, 2),
     exported(*texel(7, 7)[:2], 0, 0),
     [exported(*texel(7, 7)[:2], *texel(7, 2)[:2]), exported(*texel(7, 7)[:2], *texel(0, 2)[:2])]),
    ("range", image_load_body(("load", "v[12:13]", 0x3, ("s44", "s45"), " unorm"), ("load", "v[14:15]", 0x3, ("s46", "s47"), " unorm")),
     (M32, 1, 3, 8),
     exported(0, 0, 0, 0),
     [exported(*texel(0, 1)[:2], *texel(3, 7)[:2]), exported(*texel(7, 1)[:2], *texel(3, 0)[:2])]),
    ("mip", image_load_body(("load_mip", "v[12:13]", 0x3, ("s44", "s45", "s46"), " unorm"),
                            ("load_mip", "v[14:15]", 0x3, ("s44", "s45", "s47"), " unorm")), (2, 5, 0, 1),
     exported(*texel(2, 5)[:2], 0, 0),
     [exported(*texel(2, 5)[:2], *texel(2, 5)[:2])]),
    ("info0", [*info_body((20, 0xb, "s44"), (23, 0x9, "s45")),
               ubyte(0, 12, "v20", "e32"), ubyte(0, 13, "v21", "e32"), ubyte(0, 14, "v22", "e32"), ubyte(0, 15, "v23", "e64")],
     (0, 1, 0, 0), [8.0, 8.0, 1.0, 0.0], [[8.0, 8.0, 1.0, 4.0], [8.0, 8.0, 0.0, 0.0], [8.0, 8.0, 4.0, 0.0]]),
    ("info1", [*info_body((20, 0xa, "s45"), (22, 0x8, "s44"), (23, 0x1, "s44")),
               ubyte(0, 12, "v20", "e32"), ubyte(0, 13, "v21", "e64"), ubyte(0, 14, "v22", "e32"), ubyte(0, 15, "v23", "e32")],
     (0, 1, 0, 0), [0.0, 1.0, 1.0, 8.0], [[4.0, 1.0, 1.0, 8.0], [0.0, 0.0, 1.0, 8.0], [0.0, 1.0, 4.0, 8.0]]),
    ("gather_r", image_gather_body("gather4_lz", 0x1), GATHER_WORDS,
     exported(GL, GR, GR, GL), [exported(GR, GL, GL, GR), exported(GT, GT, GB, GB), exported(RAMP[2], RAMP[2], RAMP[3], RAMP[3])]),
    ("gather_g", image_gather_body("gather4_lz", 0x2), GATHER_WORDS,
     exported(GB, GB, GT, GT), [exported(GT, GT, GB, GB), exported(GL, GR, GR, GL), exported(GB, GT, GT, GB)]),
    ("gather_a", image_gather_body("gather4_lz", 0x8), GATHER_WORDS,
     exported(255, 255, 255, 255), [exported(128, 128, 128, 128)]),
    ("gather_b", image_gather_body("gather4_lz", 0x4), GATHER_WORDS,
     exported(128, 128, 128, 128), [exported(255, 255, 255, 255)]),
)


def check_image_draws(directory, compiler, renderer, backend):
    case = directory / "image.case"
    for name, body, words, reference, bugs in IMAGE_PROGRAMS:
        source = directory / f"image_{name}.hlsl"
        shader = directory / f"image_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        for x in reference:
            assert half_rtz(x) == x, x
        case.write_bytes(constants + struct.pack("<4f", *reference) * 64)
        subprocess.run(draw, check=True)
        for wrong in bugs:
            assert wrong != reference and all(half_rtz(x) == x for x in wrong), (name, wrong)
            case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong image result escaped detection in {name}: {wrong}")


def check_image_controls():
    load = ["image_load v[12:15], v[18:19], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm"]
    gather = "image_gather4_lz v[12:15], v[18:19], s[28:35], s[40:43] dmask:0x1 dim:SQ_RSRC_IMG_2D"
    ready = [move(18, "s44"), move(19, "s45")]
    # Direct3D loads, level queries and gathers; the helpers make out-of-range reads zero explicitly.
    source = translate(with_constants([*ready, *load, "s_waitcnt vmcnt(0)"]))
    assert "image_load2d(tex, " in source and "t.Load(int3(int(x), int(y), int(mip)))" in source, source
    assert "if (x >= w || y >= h) return float4(0.0f" in source and "if (mip >= levels)" in source, source
    source = translate(with_constants([*info_body((20, 0xb, "s44")), ubyte(0, 12, "v20", "e32")]))
    assert "image_resinfo2d(tex, " in source and "uint4(w, h, 0u, levels)" in source, source
    source = translate(with_constants([*ready, "image_gather4_lz v[12:15], v[18:19], s[28:35], s[40:43] dmask:0x4 dim:SQ_RSRC_IMG_2D",
                                       "s_waitcnt vmcnt(0)"]))
    assert "tex.GatherBlue(samp, float2(" in source, source
    # The implicit-level gather is refused: its level comes from derivatives, which Gather* does not reproduce.
    must_reject(translate, with_constants([*ready, gather.replace("gather4_lz", "gather4"), "s_waitcnt vmcnt(0)"]))
    # Two dmask bits on a gather, a zero dmask, and unsupported modifiers or dimensions are refused.
    for line in (gather.replace("0x1", "0x3"), gather.replace("0x1", "0x0"), gather.replace("0x1", "0x5"),
                 load[0].replace("0xf", "0x0"), load[0] + " a16", load[0] + " d16", load[0] + " tfe", load[0] + " lwe",
                 load[0].replace("IMG_2D", "IMG_2D_ARRAY"), load[0].replace("IMG_2D", "IMG_3D"), load[0] + " r128",
                 gather + " unorm", gather + " a16", gather.replace("IMG_2D", "IMG_2D_ARRAY"),
                 "image_get_resinfo v[12:14], v18, s[28:35] dmask:0x7 dim:SQ_RSRC_IMG_2D unorm",
                 "image_get_resinfo v12, v18, s[28:35] dmask:0x4 dim:SQ_RSRC_IMG_2D",
                 "image_load v[12:14], v[18:19], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                 "image_load v[12:15], v[18:20], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                 "image_load_mip v[12:15], v[18:19], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                 "image_load v[12:15], v[18:19], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                 gather.replace("s[40:43]", "s[44:47]"), "image_gather4 v[12:15], v[18:19], s[28:35] dmask:0x1 dim:SQ_RSRC_IMG_2D"):
        must_reject(translate, with_constants([*ready, line, "s_waitcnt vmcnt(0)"]))
    # The image descriptor must be a loaded T#, and the coordinates must be set.
    must_reject(translate, with_constants([*ready, load[0].replace("s[28:35]", "s[36:43]"), "s_waitcnt vmcnt(0)"]))
    must_reject(translate, with_constants([*ready, load[0].replace("v[18:19]", "v[24:25]"), "s_waitcnt vmcnt(0)"]))
    # A load result read before s_waitcnt vmcnt(0), an integer word and a destination that overlaps an outstanding load.
    must_reject(translate, with_constants([*ready, *load]))
    must_reject(translate, with_constants([*ready, *load, ubyte(0, 12, "v12", "e32")]))
    must_reject(translate, with_constants([*info_body((20, 0xb, "s44"))[:-1], ubyte(0, 12, "v20", "e32")]))
    must_reject(translate, with_constants([*ready, *load, load[0].replace("v[12:15]", "v[14:17]")]))
    must_reject(translate, with_constants([*ready, gather, ubyte(0, 13, "v13", "e32")]))
    # A gather coordinate read from a register under an outstanding sample is refused as well.
    must_reject(translate, with_constants([*ready, *load, gather.replace("v[18:19]", "v[12:13]")]))


def check_controls(directory):
    check_scheduling_hints()
    check_constant_descriptor_bounds()
    check_scalar_constant_reads()
    check_load_controls()
    check_image_controls()
    # Whole-dword SDWA comparisons lower exactly as the e32 forms; byte and word selections are refused.
    for first in range(0, 16, 4):
        assert translate(predicate_group(first, sdwa=True)) == translate(predicate_group(first)), first
    must_reject(translate, with_constants(["v_sub_f32_e64 v18, s45, 0",
        "v_cmp_lt_f32_sdwa vcc_lo, s44, v18 src0_sel:WORD_1 src1_sel:DWORD"]))
    # v_cvt_f32_f16 widens the low half through widen16 and applies modifiers after widening.
    body = translate(with_constants(HALF_BODY)).split("float4 main", 1)[1]
    assert body.count("widen16(asuint(") == 4 and "(-abs(widen16(" in body, body
    must_reject(translate, with_constants(["v_cvt_f32_f16_e32 v12, 1.0"]))
    must_reject(translate, with_constants(["v_cvt_f32_f16_sdwa v12, s44 src0_sel:WORD_1"]))
    # v_cvt_f16_f32 keeps the destination's high half and narrows the modified source through narrow16.
    body = translate(with_constants(NARROW_BODY)).split("float4 main", 1)[1]
    assert body.count("narrow16(") == 3 and body.count("& 0xffff0000u) | narrow16(") == 3, body
    assert "narrow16((-abs(" in body, body
    must_reject(translate, with_constants(["v_cvt_f16_f32_e64 v12, s44 clamp"]))
    must_reject(translate, with_constants(["v_cvt_f16_f32_sdwa v12, s44 dst_sel:WORD_1"]))
    # An inline integer keeps its bit pattern, and a destination holding interpolation state is refused.
    body = translate(with_constants(["v_cvt_f16_f32_e32 v12, -1", "v_cvt_f16_f32_e64 v13, -|0.5|"])).split("float4 main", 1)[1]
    assert "narrow16(asfloat(4294967295u))" in body and "narrow16((-abs(0.5f)))" in body, body
    for register in ("v0", "v1", "v8", "v9"):
        must_reject(translate, with_constants([f"v_cvt_f16_f32_e32 {register}, s44"]))
    # Binary16 arithmetic computes once in binary32 from the widened low halves, narrows once and keeps the
    # destination's high half; subrev swaps its operands, and a modifier acts on bit 15 before widening.
    body = translate(with_constants(F16_PROGRAMS[0][1])).split("float4 main", 1)[1]
    assert body.count("& 0xffff0000u) | narrow16(") == 4 and body.count("narrow16(") == 4, body
    assert "widen16(((asuint(params[0].w) & 0xffffu) ^ 0x8000u)) - widen16(((asuint(alu20) & 0xffffu) & 0x7fffu))" in body, body
    assert "widen16((asuint(alu20) & 0xffffu)) - widen16((asuint(params[1].y) & 0xffffu))" in body, body
    # An inline constant is a binary16 value, an integer inline constant is a bit pattern and a literal supplies
    # its low half; a destination that was never written contributes a zero high half.
    body = translate(with_constants(["v_add_f16_e32 v20, 0.5, v13", "v_add_f16_e32 v21, 3, v13", "v_add_f16_e64 v22, -3, v13",
                                     "v_add_f16_e32 v23, 0x3c02, v13", "v_add_f16_e32 v24, 0.15915494, v13",
                                     "v_add_f16_e64 v25, -|0.5|, v13"])).split("float4 main", 1)[1]
    for expected in ("widen16(0x3800u)", "widen16(0x3u)", "widen16(0xfffdu)", "widen16(0x3c02u)", "widen16(0x3118u)",
                     "widen16(((0x3800u & 0x7fffu) ^ 0x8000u))"):
        assert expected in body, expected
    assert body.count("asfloat(0u | narrow16(") == 6, body
    assert translate(with_constants(["v_add_f16 v12, s44, v13"])) == translate(with_constants(["v_add_f16_e32 v12, s44, v13"]))
    body = translate(with_constants(["v_ldexp_f16_e64 v12, s44, -3", "v_ldexp_f16_e64 v13, s44, 0xfffd",
                                     "v_ldexp_f16_e32 v14, s44, v15", "v_ldexp_f16_e64 v15, -s44, 5",
                                     "v_fract_f16_e64 v20, s44 clamp", "v_max_f16_e64 v21, s44, 0.5 clamp"])).split("float4 main", 1)[1]
    for expected in (", -3)", ", 5)", "((int((asuint(sample16.w) & 0xffffu)) ^ 0x8000) - 0x8000)",
                     "narrow16(saturate(widen16(fract16(", "narrow16(saturate(max("):
        assert expected in body, expected
    assert body.count(", -3)") == 2, body
    must_reject(translate, with_constants(["v_add_f16_e64 v12, s44, v13 mul:2"]))
    must_reject(translate, with_constants(["v_add_f16_e64 v12, s44, v13 div:2"]))
    must_reject(translate, with_constants(["v_mul_f16_e64 v12, s44, v13 op_sel:[0,0,1]"]))
    must_reject(translate, with_constants(["v_add_f16_e64 v12, s44, v13 clamp mul:2"]))
    must_reject(translate, with_constants(["v_add_f16_e32 v12, s44, v13 clamp"]))
    must_reject(translate, with_constants(["v_add_f16_sdwa v12, v13, v14 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_0 src1_sel:WORD_0"]))
    must_reject(translate, with_constants(["v_add_f16_dpp v12, v13, v14 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf"]))
    for operation in ("v_fma_f16 v12, s44, v13, v14", "v_fmac_f16_e32 v12, s44, v13", "v_mad_f16 v12, s44, v13, v14",
                      "v_sqrt_f16_e32 v12, s44", "v_rcp_f16_e32 v12, s44", "v_rsq_f16_e32 v12, s44",
                      "v_log_f16_e32 v12, s44", "v_exp_f16_e32 v12, s44", "v_sin_f16_e32 v12, s44", "v_cos_f16_e32 v12, s44",
                      "v_add_f16_e32 v12, s44", "v_floor_f16_e32 v12, s44, v13", "v_ldexp_f16_e64 v12, s44",
                      "v_add_f16_e32 v12, 1.5, v13", "v_add_f16_e32 v12, 65, v13", "v_add_f16_e32 v12, -17, v13",
                      "v_add_f16_e32 v12, 0x12345, v13", "v_add_f16_e64 v12, --0.5, v13", "v_add_f16_e64 v12, |-s44|, v13",
                      "v_add_f16_e64 v12, neg(s44), v13", "v_add_f16_e32 v12, s44, v13, v14",
                      "v_ldexp_f16_e64 v12, v13, 1.0", "v_ldexp_f16_e64 v12, v13, -s44", "v_ldexp_f16_e64 v12, v13, |s44|",
                      "v_ldexp_f16_e64 v12, v13, 65", "v_ldexp_f16_e64 v12, v13, 0x12345", "v_ldexp_f16_e64 v12, v13, s44 clamp mul:2"):
        must_reject(translate, with_constants([operation]))
    check_f16_cmp_controls()
    # The destination's old value must be numeric (v0, v1, v8 and v9 hold interpolation state), a source cannot
    # be read before the sample or the scalar load it depends on arrives, and nothing may overwrite a sample
    # destination before vmcnt(0).
    for register in ("v0", "v1", "v8", "v9"):
        must_reject(translate, with_constants([f"v_mul_f16_e32 {register}, s44, v13"]))
        must_reject(translate, with_constants([f"v_floor_f16_e32 {register}, s44"]))
    program = with_constants(["v_add_f16_e32 v20, s44, v13"])
    translate(program)
    wait = program.index("s_waitcnt vmcnt(0)")
    for operation in ("v_add_f16_e32 v20, s44, v13", "v_add_f16_e32 v20, v12, v13", "v_add_f16_e32 v12, 0.5, v13",
                      "v_floor_f16_e32 v13, 0.5"):
        must_reject(translate, program[:wait] + [operation] + program[wait:])
    scalar_wait = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc"))
    for operation in ("v_add_f16_e64 v20, s44, s47", "v_ldexp_f16_e64 v20, s44, s45", "v_ceil_f16_e64 v20, s46"):
        must_reject(translate, program[:scalar_wait] + [operation] + program[scalar_wait:])
        translate(program[:scalar_wait + 1] + [operation] + program[scalar_wait + 1:])
    archive = directory / "input.bin"
    code = bytes.fromhex("000080bf 000081bf")  # s_nop 0 followed by s_endpgm
    check_container_selector(directory, code)
    record = envelope(code)
    archive.write_bytes(b"another_fixture\0" + record)
    assert native_program(archive, "fixture")[1] == code
    long_name = b"synthetic_pixel_with_a_printable_length"
    archive.write_bytes(envelope(code, long_name))
    assert native_program(archive, long_name.decode())[1] == code
    for invalid in (record[:-1], record + b"\0" + record, envelope(code + code)):
        archive.write_bytes(invalid)
        must_reject(native_program, archive, "fixture")

    # LLVM 15 prints "exp mrt0 v16, ..."; newer LLVM prints "exp mrt0, v16, ...".
    for program in (assembly(False), assembly(True), curve(), shaping(), arithmetic()):
        modern = [line.replace("exp mrt0 ", "exp mrt0, ") for line in program]
        assert modern != program
        assert translate(modern) == translate(program)
        must_reject(translate, [line.replace("exp mrt0 ", "exp mrt0,, ") for line in program])

    # The literal of v_fmaak_f32 is its last operand and that of v_fmamk_f32 its second; a register there is refused.
    body = translate(with_constants(LITERAL_FMA_BODY)).split("float4 main", 1)[1]
    assert body.count("mad(") == 4 and "asfloat(1048576000u)" in body, body
    must_reject(translate, with_constants(["v_fmaak_f32 v12, s44, v13, v14"]))
    must_reject(translate, with_constants(["v_fmamk_f32 v12, s44, v13, 0x3e800000"]))
    must_reject(translate, with_constants(["v_fmaak_f32 v12, s44, 0x3e800000"]))
    for old, new in (("v_sqrt_f32_e32 v18, v18", "v_sqrt_f32_e32 v18, v18, v18"),
                     ("v_add_f32_e32 v19, s44, v13", "v_add_f32_e32 v19, v13")):
        must_reject(translate, [line.replace(old, new) for line in shaping()])

    program = truncate_values()
    source = translate(program)
    assert "trunc(params[1].x)" in source
    must_reject(translate, [line.replace("v13, s45", "v13, s45, v12") for line in program])
    wait = program.index("s_waitcnt vmcnt(0)")
    program.remove("v_trunc_f32_e32 v13, s45")
    program.insert(wait, "v_trunc_f32_e32 v13, s45")
    must_reject(translate, program)

    # v_cmp_class_f32 classifies the raw encoding; a mask with modifiers or a non-numeric operand is refused.
    body = translate(with_constants(CLASS_BODY)).split("float4 main", 1)[1]
    assert body.count("class32(") == 4 and "& 512u" in body and "asuint(alu" in body, body
    must_reject(translate, with_constants(["v_cmp_class_f32_e64 vcc_lo, s44, -s45"]))
    must_reject(translate, with_constants(["v_cmp_class_f32_e64 vcc_lo, s44"]))

    program = absolute_value()
    alternate = [line.replace("|v12|", "abs(v12)") for line in program]
    assert translate(program) == translate(alternate)
    # Each cube operation reads the three coordinates once and needs all three operands.
    body = translate(with_constants(CUBE_BODY)).split("float4 main", 1)[1]
    assert body.count("precise float3 cube") == 4 and body.count("* 2.0f)") == 1, body
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", "v_cubeid_f32 v12, s44, v18"]))
    # SDWA moves select and place fields; UNUSED_SEXT, byte selections for half widening and
    # non-canonical SDWA text are refused.
    body = translate(with_constants(SDWA_PRESERVE_BODY + SDWA_PAD_BODY)).split("float4 main", 1)[1]
    assert body.count("& 0xffff0000u) | ") == 2 and body.count("asint(") == 1 and body.count("widen16(") == 2, body
    must_reject(translate, with_constants(["v_mov_b32_sdwa v12, s44 dst_sel:BYTE_0 dst_unused:UNUSED_SEXT src0_sel:WORD_1"]))
    must_reject(translate, with_constants(["v_cvt_f32_f16_sdwa v12, s44 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:BYTE_1"]))
    must_reject(translate, with_constants(["v_mov_b32_sdwa v12, s44 src0_sel:WORD_1"]))
    # UNUSED_PRESERVE keeps bits only from a tracked numeric value; DWORD and padded writes may replace anything.
    for register in ("v0", "v1", "v8", "v9", "v20"):
        must_reject(translate, with_constants([f"v_mov_b32_sdwa {register}, s44 dst_sel:WORD_0 dst_unused:UNUSED_PRESERVE src0_sel:WORD_1"]))
    body = translate(with_constants(["v_mov_b32_sdwa v12, -0.5 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
                                     "v_mov_b32_sdwa v20, s44 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_0",
                                     "v_mov_b32_sdwa v13, v20 dst_sel:DWORD dst_unused:UNUSED_PRESERVE src0_sel:DWORD"])).split("float4 main", 1)[1]
    assert "asuint((-0.5f))" in body, body
    # SDWA arithmetic takes whole-dword sources only and refuses output modifiers and a src1_sel on a unary op.
    body = translate(with_constants(SDWA_ARITH[3][0])).split("float4 main", 1)[1]
    assert body.count("& 0xffff0000u) | ") == 1 and body.count("& 0xff00ffffu) | ") == 1, body
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", sdwa_arith("add", "v12", ["s44", "v18 mul:2"])]))
    must_reject(translate, with_constants([sdwa_arith("add", "v12", ["s44", "v13"]).replace("src0_sel:DWORD", "src0_sel:WORD_1")]))
    must_reject(translate, with_constants([sdwa_arith("floor", "v12", ["s44"]) + " src1_sel:DWORD"]))
    # A partial UNUSED_PRESERVE result needs a tracked numeric destination, as for SDWA moves.
    for register in ("v0", "v8", "v20"):
        must_reject(translate, with_constants([sdwa_arith("floor", register, ["s44"], "BYTE_2", "UNUSED_PRESERVE")]))

    program = assembly(False)
    for old, new in (("s_mov_b32 s21, 0", "s_mov_b32 s21, 1"),
                     ("s_mov_b32 s40, 1", "s_mov_b32 s40, 8"),
                     ("attr0.y", "attr1.y"),
                     ("s_wqm_b64 exec, exec", "s_branch 0")):
        must_reject(translate, [line.replace(old, new) for line in program])
    must_reject(translate, program[:-1])
    for wait in ("s_waitcnt vmcnt(0)", "s_waitcnt lgkmcnt(0)"):
        must_reject(translate, [line for line in program if line != wait])

    wait = program.index("s_waitcnt vmcnt(0)")
    overwrite = "v_floor_f32_e32 v13, 1.0"
    must_reject(translate, program[:wait] + [overwrite] + program[wait:])
    free = translate(program[:wait] + ["v_floor_f32_e32 v24, 1.0"] + program[wait:])
    late = translate(program[:wait+1] + [overwrite] + program[wait+1:])
    assert "export16(sample15.y)" in free
    assert "export16(alu17)" in late

    program = arithmetic()
    source = translate(program)
    for expected in ("= sample16.x;", "= (params[2].x * alu20);", "= saturate((alu21 + params[2].y));",
                     "= params[2].z;", "= (alu23 - sample16.y);", "= saturate((alu25 - params[2].w));",
                     "= asfloat(1048576000u);", "= alu29;"):
        assert expected in source, expected
    # A move is a bit copy: LLVM prints integer inline constants as integers.
    for operand, expected in (("1", "asfloat(1u)"), ("-4", "asfloat(4294967292u)"),
                              ("-0.5", "(-0.5f)"), ("0.15915494", "0.15915494f"), ("s40", "asfloat(1u)")):
        changed = [line.replace("v20, 0x3e800000", f"v20, {operand}") for line in program]
        assert f"alu28 = {expected};" in translate(changed), operand
    for old, new in (("v18, v12", "v18, v0"), ("v18, v12", "v18, v8"), ("v18, v12", "v18, v30"),
                     ("v19, s46", "v19, s28"), ("v19, s46", "v19, -s46"), ("v19, s46", "v19, s46 clamp"),
                     ("v18, v12", "v18, v12, v13"), ("v14, -0.5, v14", "v14, v14"),
                     ("v19, v13, v19", "v19, v13, v19, v18"), ("s45 clamp", "s45 clamp mul:2")):
        changed = [line.replace(old, new) for line in program]
        assert changed != program
        must_reject(translate, changed)
    first = program.index("v_mov_b32_e32 v18, v12")
    early = program[:first-1] + [program[first], program[first-1]] + program[first+1:]
    assert early[first] == "s_waitcnt vmcnt(0)"
    must_reject(translate, early)  # copies the sample before the wait
    # Until vmcnt(0), the sample may still fill v12 to v15, so a move into one of them has no defined
    # order with it. The same move into a free register, or into v12 after the wait, is accepted.
    wait = program.index("s_waitcnt vmcnt(0)")
    for register in ("v12", "v13", "v14", "v15"):
        must_reject(translate, program[:wait] + [f"v_mov_b32_e32 {register}, 1.0"] + program[wait:])
    must_reject(translate, program[:wait] + ["v_ceil_f32_e32 v12, 1.0"] + program[wait:])
    free = translate(program[:wait] + ["v_mov_b32_e32 v21, 1.0"] + program[wait:])
    assert free.index("tex.Sample") < free.index("= 1.0f;") < free.index("= sample16.x;")
    late = translate(program[:wait+1] + ["v_mov_b32_e32 v12, 1.0"] + program[wait+1:])
    assert "= 1.0f;" in late and "= sample16.x;" not in late
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v17, v14, v15")
    must_reject(translate, program[:pos] + ["v_mov_b32_e32 v20, v16"] + program[pos:])
    pos = program.index("s_wqm_b64 exec, exec") + 1
    must_reject(translate, program[:pos] + ["v_mov_b32_e32 v20, 1.0"] + program[pos:])
    pos = program.index("v_interp_p1_f32_e32 v9, v0, attr0.y")
    partial = program[:pos] + ["v_interp_p1_f32_e32 v10, v0, attr0.x"] + program[pos:]
    translate(partial)  # an unpaired first phase is allowed, but its partial value is not numeric
    must_reject(translate, [line.replace("v18, v12", "v18, v10") for line in partial])
    pos = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0x20"))
    must_reject(translate, program[:pos] + ["v_mov_b32_e64 v19, s46"] + program[pos:])

    for old, new in (("0x40", "0x48"), ("0xc", "0xfe"), ("0xc", "0x100"),
                     ("s_waitcnt lgkmcnt(0)", "s_nop 0"), ("s[44:47], 0xc", "s[40:43], 0xc")):
        must_reject(translate, [line.replace(old, new) for line in curve()])
    source = translate(select())
    assert translate(select(True)) == source
    for expected in ("(sample16.x >= sample16.y || isnan(sample16.x) || isnan(sample16.y))",
                     "sample16.x == sample16.y",
                     "params[0].w < sample16.x", "sample16.y >= params[1].x",
                     "? 1.0f : asfloat(0u);", "? sample16.w : params[1].z;"):
        assert expected in source, expected
    for wave64 in (False, True):
        program = select(wave64)
        mask = "s[52:53]" if wave64 else "s52"
        absolute_compare = [line.replace("v13, s45", "v13, |v12|") for line in program]
        assert "abs(" in translate(absolute_compare)
        pos = program.index(f"v_cndmask_b32_e64 v13, v13, s46, {mask}")
        must_reject(translate, program[:pos] + ["s_mov_b32 s52, 0"] + program[pos:])
        for old, new in ((f"s46, {mask}", "s46, s[53:54]" if wave64 else "s46, s50"),
                         ("v_cmp_eq_f32_e32", "v_cmp_eq_f64_e32"),
                         ("v_cmp_ge_f32_e64", "v_cmpx_ge_f32_e64"),
                         (f"v_cmp_ge_f32_e64 {mask}", "v_cmp_ge_f32_e64 " + ("s[56:57]" if wave64 else "s56")),
                         ("v13, s45", "v13, |v12"),
                         ("v15, s47, v15", "v15, s50, v15")):
            changed = [line.replace(old, new) for line in program]
            assert changed != program
            must_reject(translate, changed)
        pos = program.index("s_waitcnt vmcnt(0)")
        must_reject(translate, program[:pos] + program[pos+1:])
    # v_fract_f32 goes through the clamped helper, never through a bare D3D frac.
    body = translate(shaping()).split("float4 main", 1)[1]
    assert "fract32(" in body and "frac(" not in body, body
    # v_mad_f32 and v_mac_f32 use the unfused, denormal-flushing helper, never the fma lowering.
    body = translate(with_constants(MAD_BODY)).split("float4 main", 1)[1]
    assert body.count("mad32(") == 4 and " mad(" not in body, body
    must_reject(translate, with_constants(["v_mad_f32 v12, s44, s45"]))
    must_reject(translate, with_constants(["v_mac_f32_e32 v14, s44, v15, v14"]))

    # Integer vector values: the lowering, then refusals for modifiers, clamp, unset registers and pending samples.
    source = translate(with_constants(INT_PROGRAMS[3][0])).split("float4 main", 1)[1]
    assert "asint(" in source and "<< (" in source and "& 31u" in source
    for line in ("v_and_b32_e64 v19, -s44, v18", "v_xor_b32_e64 v19, -v18, s44", "v_or_b32_e64 v19, |s44|, v18",
                 "v_not_b32_e64 v19, -s44", "v_lshlrev_b32_e64 v19, -s44, v18",
                 "v_and_b32_e64 v19, s44, v18 clamp", "v_and_b32_e64 v19, s44, v18 mul:2",
                 "v_cvt_f32_ubyte0_e64 v19, -s44", "v_cvt_f32_ubyte0_e64 v19, s44 mul:2",
                 "v_cvt_f32_ubyte0_e32 v19, s44 clamp",
                 "v_and_b32_e32 v19, s44, v30", "v_and_b32_e32 v19, v30, v18", "v_not_b32_e32 v19, v30",
                 "v_bfrev_b32_e32 v19, v30", "v_ashrrev_i32_e32 v19, s44, v30", "v_cvt_f32_ubyte1_e32 v19, v30",
                 "v_and_b32_e32 v19, s90, v18", "v_lshrrev_b32_e32 v19, m0, v18"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", line]))
    plain = with_constants(["v_mov_b32_e32 v18, s45", "v_and_b32_e32 v19, s44, v18", "v_cvt_f32_ubyte0_e32 v12, v19"])
    assert "uint valu" in translate(plain)
    program = assembly(False)
    wait = program.index("s_waitcnt vmcnt(0)")
    for early in ("v_cvt_f32_ubyte0_e32 v18, v13", "v_and_b32_e32 v18, s44, v13", "v_not_b32_e32 v18, v13",
                  "v_cvt_f32_ubyte0_e32 v13, 5", "v_not_b32_e32 v13, 5"):
        must_reject(translate, program[:wait] + [early] + program[wait:])
    assert "& 255u" in translate(program[:wait + 1] + ["v_cvt_f32_ubyte0_e32 v18, v13"] + program[wait + 1:])
    program = with_constants(["v_mov_b32_e32 v18, s45"])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    for early in ("v_not_b32_e32 v19, s44", "v_cvt_f32_ubyte0_e32 v19, s44", "v_and_b32_e32 v19, s44, v18"):
        must_reject(translate, program[:load] + [early] + program[load:])
    # Integer add, subtract, multiply and three-input forms: the lowering, then refusals.
    source = translate(with_constants(ARITH_PROGRAMS[5][0])).split("float4 main", 1)[1]
    assert "mul_hi_u32(" in source and "mul_hi_i32(" in source
    assert "uint mul_hi_u32(" in translate(with_constants(ARITH_PROGRAMS[5][0]))
    assert "uint v_add_sat_i32(" in translate(with_constants(ARITH_PROGRAMS[2][0]))
    assert "mul_hi_u32(" not in translate(with_constants(INT_PROGRAMS[0][0]))
    for line in ("v_add_nc_u32_e64 v19, -s44, v18", "v_sub_nc_u32_e64 v19, s44, -v18", "v_subrev_nc_u32_e64 v19, |s44|, v18",
                 "v_mul_u32_u24_e64 v19, -s44, v18", "v_mul_hi_i32_i24_e64 v19, s44, |v18|", "v_add_nc_i32 v19, -s44, v18",
                 "v_mul_lo_u32 v19, |s44|, v18", "v_mad_u32_u24 v19, -s44, v18, 5", "v_add3_u32 v19, -s44, s45, v18",
                 "v_xad_u32 v19, s44, -s45, v18", "v_lshl_or_b32 v19, s44, 3, -v18",
                 "v_add_nc_u32_e64 v19, s44, v18 mul:2", "v_mul_lo_u32 v19, s44, v18 mul:2", "v_add3_u32 v19, s44, s45, v18 mul:2",
                 "v_add_nc_u32_e64 v19, s44, v18 div:2"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", line]))
    # clamp that llvm-mc rejects, and clamp on forms that llvm-mc assembles but whose saturation is not modelled.
    for line in ("v_add_nc_u32_e32 v19, s44, v18 clamp", "v_add3_u32 v19, s44, s45, v18 clamp",
                 "v_xad_u32 v19, s44, s45, v18 clamp", "v_lshl_add_u32 v19, s44, s45, v18 clamp",
                 "v_and_or_b32 v19, s44, s45, v18 clamp", "v_mul_lo_u32 v19, s44, v18 clamp",
                 "v_mul_hi_u32 v19, s44, v18 clamp", "v_mul_hi_u32_u24_e64 v19, s44, v18 clamp",
                 "v_mul_u32_u24_e64 v19, s44, v18 clamp", "v_mul_i32_i24_e64 v19, s44, v18 clamp",
                 "v_mad_u32_u24 v19, s44, v18, 5 clamp", "v_mad_i32_i24 v19, s44, v18, 5 clamp",
                 "v_mul_lo_u32_e32 v19, s44, v18", "v_add_nc_i32_e32 v19, s44, v18"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", line]))
    for line in ("v_add_nc_u32_e32 v19, s44, v30", "v_sub_nc_u32_e32 v19, v30, v18", "v_mul_i32_i24_e32 v19, s44, v30",
                 "v_mul_hi_u32 v19, s44, v30", "v_add3_u32 v19, s44, v30, v18", "v_xad_u32 v19, s44, v18, v30",
                 "v_add_nc_u32_e32 v19, s90, v18", "v_add3_u32 v19, m0, s44, v18"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", line]))
    plain = with_constants(["v_mov_b32_e32 v18, s45", "v_add3_u32 v19, s44, 3, v18", "v_cvt_f32_ubyte0_e32 v12, v19"])
    assert "uint valu" in translate(plain)
    program = assembly(False)
    wait = program.index("s_waitcnt vmcnt(0)")
    for early in ("v_add_nc_u32_e32 v18, s44, v13", "v_mul_u32_u24_e32 v18, s44, v13", "v_mul_hi_i32 v18, s44, v13",
                  "v_add3_u32 v18, s44, 3, v13", "v_xad_u32 v18, v13, 3, 5", "v_add3_u32 v13, s44, 3, 5",
                  "v_add_nc_u32_e64 v14, s44, 5"):
        must_reject(translate, program[:wait] + [early] + program[wait:])
    program = with_constants(["v_mov_b32_e32 v18, s45"])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    for early in ("v_add_nc_u32_e32 v19, s44, v18", "v_mul_lo_u32 v19, s44, v18", "v_add3_u32 v19, s44, s45, v18"):
        must_reject(translate, program[:load] + [early] + program[load:])
    # 64-bit scalar ALU and 32-bit BFE controls.
    program = scalar64()
    source = translate(program)
    for expected in ("uint2 s_lshl_b64(", "uint2 s_lshr_b64(", "uint2 s_ashr_i64(",
                     "uint2 s_bfm_b64(", "uint s_bfe_u32(", "uint s_bfe_i32(",
                     "reversebits(", "asfloat(salu"):
        assert expected in source, expected
    # Existing programs without shifts/bfm/bfe emit none of the scalar helper functions.
    assert "uint2 s_lshl_b64(" not in translate(assembly(False))
    # Verify 32-bit hex literal sign-extension for s_ashr_i64 vs zero-extension for b64 ops.
    ashr_pos = program.index("s_ashr_i64 s[72:73], s[52:53], s56")
    signed_lit = translate(program[:ashr_pos] + ["s_ashr_i64 s[72:73], 0x80000000, 4"] + program[ashr_pos+1:])
    assert "s_ashr_i64(uint2(2147483648u, 4294967295u), 4u)" in signed_lit
    unsigned_lit = translate(program[:ashr_pos] + ["s_and_b64 s[72:73], s[52:53], 0x80000000"] + program[ashr_pos+1:])
    assert "2147483648u" in unsigned_lit and "0u)" in unsigned_lit
    # Verify all 10 SCC observation bits flip between the two constant sets.
    refs = []
    for values in SCALAR64_SETS:
        constants = bytearray(256)
        struct.pack_into("<12I", constants, 16, *values)
        refs.append(scalar64_reference(program, struct.unpack("<64I", constants)))
    assert (refs[0][1] ^ refs[1][1]) == 0x3ff, (bin(refs[0][1]), bin(refs[1][1]))
    # Negative controls: exec save/restore, #257 ops, out-of-scope 64-bit ops, invalid operands and SCC rules.
    body_start = program.index("s_and_b64 s[72:73], s[52:53], s[54:55]")
    for bad in (
        "s_and_saveexec_b64 s[70:71], s[52:53]",
        "s_or_saveexec_b64 s[70:71], s[52:53]",
        "s_andn2_saveexec_b64 s[70:71], s[52:53]",
        "s_or_b64 exec, exec, s[52:53]",
        "s_and_b64 vcc, s[52:53], s[54:55]",
        "s_cmov_b64 exec, s[52:53]",
        "s_not_b64 vcc, s[52:53]",
        "s_and_b64 s[70:71], exec, s[52:53]",
        "s_xor_b64 s[70:71], vcc, s[52:53]",
        "s_cmov_b64 s[70:71], s[52:53]",  # before any SCC write
        "s_and_b64 s[53:54], s[52:53], s[54:55]",  # unaligned pair
        "s_and_b64 s[106:107], s[52:53], s[54:55]",  # out-of-range SGPR pair
        "s_bfe_u32 s106, s60, 0x80004",  # out-of-range SGPR
        "s_bfe_u32 s70, v12, 0x80004",  # VGPR source
        "s_bfe_u32 s70, m0, 0x80004",  # m0 source
        "s_and_b64 s[70:71], s[28:29], s[52:53]",  # texture descriptor source
        "s_and_b64 s[70:71], s[44:45], s[52:53]",  # CBV descriptor source
        "s_and_b64 s[70:71], s[50:51], s[52:53]",  # saved exec source
        "s_and_b64 s[70:71], s[20:21], s[52:53]",  # texture_ptr source
        "s_and_b64 s[70:71], s[90:91], s[52:53]",  # unset source
        "s_cselect_b64 s[70:71], s[52:53], s[54:55]",
        "s_bfe_u64 s[70:71], s[52:53], s61",
        "s_bfe_i64 s[70:71], s[52:53], s61",
        "s_nand_b64 s[70:71], s[52:53], s[54:55]",
        "s_nor_b64 s[70:71], s[52:53], s[54:55]",
        "s_xnor_b64 s[70:71], s[52:53], s[54:55]",
        "s_cmp_eq_u64 s[52:53], s[54:55]",
        "s_bitcmp1_b64 s[52:53], 0",
        "s_bfm_b32 s70, 4, 8",
        "s_add_u32 s70, s56, s57",
        "s_and_b32 s70, s56, s57",
        "s_not_b32 s70, s56",
        "s_cmp_eq_i32 s56, s57",
        "s_cselect_b32 s70, s56, s57",
    ):
        must_reject(translate, program[:body_start] + [bad] + program[body_start:])
    # s_cmov_b64 rejects unset or non-numeric destination pairs even after SCC is set.
    after_and = body_start + 1
    for bad_dst in ("s[90:91]", "s[44:45]", "s[50:51]", "s[28:29]"):
        must_reject(translate, program[:after_and] + [f"s_cmov_b64 {bad_dst}, s[52:53]"] + program[after_and:])
    # Pending scalar load read and write overlap must be rejected.
    load_wait = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[60:63], s[44:47], 0x30"))
    for early in ("s_and_b64 s[70:71], s[52:53], s[54:55]", "s_not_b64 s[52:53], 0", "s_bfe_u32 s60, 1, 0x80004"):
        must_reject(translate, program[:load_wait] + [early] + program[load_wait:])
    # s_wqm_b64 and exec-restoring s_and_b64 clear tracked SCC.
    wqm_pos = program.index("s_wqm_b64 exec, exec")
    exec_restore_pos = program.index("s_and_b64 exec, exec, s[50:51]")
    prefix = ["s_mov_b32 s90, 0", "s_mov_b32 s91, 0", "s_not_b64 s[92:93], 0"]
    must_reject(translate, program[:wqm_pos] + prefix + [program[wqm_pos], "s_cmov_b64 s[90:91], s[92:93]"] + program[wqm_pos+1:])
    must_reject(translate, program[:exec_restore_pos] + prefix + [program[exec_restore_pos], "s_cmov_b64 s[90:91], s[92:93]"] + program[exec_restore_pos+1:])
    # A scalar result cannot supply a sampler word, texture address high word, or v_cndmask condition.
    sample_pos = program.index("image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D")
    must_reject(translate, program[:sample_pos] + ["s_bfe_u32 s40, 1, 0x10000"] + program[sample_pos:])
    sel = select(True)
    cnd_pos = sel.index("v_cndmask_b32_e64 v13, v13, s46, s[52:53]")
    must_reject(translate, sel[:cnd_pos] + ["s_not_b64 s[52:53], 0"] + sel[cnd_pos:])


def check_binary(directory, assembler, objcopy, library):
    fixtures = [(assembly(False), translate), (assembly(True), translate), (curve(), translate), (shaping(), translate), (select(), translate), (absolute_value(), translate),
                (arithmetic(), translate), (with_scalar_constant_reads(), translate), (truncate_values(), translate),
                (ceiling(), translate), (scalar64(), translate)]
    fixtures.append((with_constants(CLASS_BODY), translate))
    fixtures.extend((predicate_group(first), translate) for first in range(0, 16, 4))
    fixtures.extend((predicate_group(first, sdwa=True), translate) for first in range(0, 16, 4))
    fixtures.append((with_constants(CUBE_BODY), translate))
    fixtures.append((with_constants(MAD_BODY), translate))
    fixtures.extend((dual_program(case), translate_dual) for case in DUAL_CASES)
    fixtures.append((with_constants(MOVK_BODY), translate))
    fixtures.append((with_constants(HALF_BODY), translate))
    fixtures.append((with_constants(NARROW_BODY), translate))
    fixtures.append((dual_program(swap_weights=True), translate_dual))
    fixtures.extend((with_constants(body), translate) for body, *_ in E64_ARITH)
    fixtures.extend((predicate_group_e64(first), translate) for first in range(0, 16, 4))
    fixtures.append((with_constants(LITERAL_FMA_BODY), translate))
    fixtures.extend((with_constants(body), translate) for body in (SDWA_PRESERVE_BODY, SDWA_PAD_BODY))
    fixtures.extend((with_constants(body), translate) for body, *_ in SDWA_ARITH)
    fixtures.extend((with_constants(body), translate) for body, *_ in INT_PROGRAMS)
    fixtures.extend((with_constants(body), translate) for _, body, *_ in F16_PROGRAMS)
    fixtures.extend((with_constants(body), translate) for _, body, *_ in (*F16_CMP_PROGRAMS, *F16_CLASS_PROGRAMS))
    fixtures.extend((with_constants(body), translate) for body, *_ in ARITH_PROGRAMS)
    fixtures.extend((with_constants(body), translate_loads) for body, *_ in LOAD_PROGRAMS)
    fixtures.extend((with_constants(body), translate) for _, body, *_ in IMAGE_PROGRAMS)
    fixtures.append((scheduling_hints(), translate))
    for index, (instructions, lower_fixture) in enumerate(fixtures):
        source = directory / "fixture.s"
        obj = directory / "fixture.o"
        binary = directory / "fixture.bin"
        source.write_text("\n".join(instructions) + "\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013",
                        "-filetype=obj", source, "-o", obj], check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
        archive = directory / "fixture.rpf"
        archive.write_bytes(envelope(binary.read_bytes()))
        _, native = native_program(archive, "fixture")
        assert native == binary.read_bytes()
        assert lower_fixture(disassemble(native, library)) == lower_fixture(instructions)
        if index == 0:
            check_container_selector(directory, native, library)


def check_ceiling_draws(directory, compiler, renderer, backend):
    instructions = ceiling()
    source = directory / "ceiling.hlsl"
    shader = directory / "ceiling.cso"
    case = directory / "ceiling.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    source.write_text(translate(instructions), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    for a, b, c, d in ((-1.75, 1.75, -1.75, -1.75), (-2.0, 2.0, 0.0, 0.0),
                       (-0.75, 0.75, -0.75, -0.75), (2.25, -2.75, 2.25, 2.25)):
        constants = bytearray(256)
        struct.pack_into("<4f", constants, 12, a, b, c, d)
        # Python's integer results lose the sign of zero. The readback compares float bits.
        expected = struct.pack("<4f", math.copysign(math.ceil(a), a),
                               math.copysign(math.ceil(-abs(b)), -1), math.ceil(abs(c)),
                               min(math.ceil(abs(d)), 1))
        case.write_bytes(constants + expected * 64)
        subprocess.run(draw, check=True)

    floor = [line.replace("v_ceil_f32_e32", "v_floor_f32_e32") for line in instructions]
    source.write_text(translate(floor), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Replacing ceiling with floor escaped detection")


def check_render(directory, compiler, renderer, backend):
    check_movk_draw(directory, compiler, renderer, backend)
    check_half_draw(directory, compiler, renderer, backend)
    check_narrow_draw(directory, compiler, renderer, backend)
    for swap in (False, True):
        source = directory / "fixture.hlsl"
        shader = directory / "fixture.cso"
        source.write_text(translate(assembly(swap)), encoding="ascii")
        subprocess.run([compiler, "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel", shader]
        result = subprocess.run([*draw, "bgra" if swap else "rgba"])
        if result.returncode:
            return result.returncode
        if swap:
            wrong = subprocess.run([*draw, "rgba"], capture_output=True, text=True)
            if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
                raise AssertionError("The renderer failed to detect the changed channel order")
    program = arithmetic()
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    for constants in ((4.0, -.0625, .125, -.015625), (2.0, -.03125, .0625, -.0078125)):
        draw = [renderer, backend, "--check-pixel-case", shader, arithmetic_case(directory, *constants)]
        subprocess.run(draw, check=True)
    swapped = [line.replace("v_subrev_f32", "v_sub_f32") for line in program]
    source.write_text(translate(swapped), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Swapped subtraction operands escaped detection")

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

    for program_fn, case_fn in ((curve, curve_case), (shaping, shaping_case)):
        source.write_text(translate(program_fn()), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        for gain in (.75, 1.125):
            case = case_fn(directory, gain)
            draw = [renderer, backend, "--check-pixel-case", shader, case]
            subprocess.run(draw, check=True)
        corrupted = bytearray(case.read_bytes())
        struct.pack_into("<f", corrupted, 16, 0.0)
        case.write_bytes(corrupted)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError("Stale reference accepted after changing the bound constants")

    program = truncate_values()
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    for constants in ((1.75, -1.75, -2.75, 2.75), (-1.75, 2.75, 3.75, -1.75)):
        case = truncate_case(directory, *constants)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        subprocess.run(draw, check=True)
    rounded_down = [line.replace("v_trunc_f32", "v_floor_f32") for line in program]
    source.write_text(translate(rounded_down), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Rounding toward negative infinity escaped detection")

    program = absolute_value()
    case = absolute_case(directory)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    subprocess.run(draw, check=True)

    without_abs = [line.replace("|v12|", "v12") for line in program]
    source.write_text(translate(without_abs), encoding="ascii")
    subprocess.run([compiler, "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("The renderer failed to detect the missing absolute value")
    check_ceiling_draws(directory, compiler, renderer, backend)
    source.write_text(translate(select()), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    for constants in ((.5, .75, .375, .25), (.125, .5, 1.0, 0.0)):
        case = select_case(directory, *constants)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        subprocess.run(draw, check=True)
    corrupted = bytearray(case.read_bytes())
    struct.pack_into("<f", corrupted, 12, .5)
    case.write_bytes(corrupted)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Stale reference accepted after moving the comparison threshold")
    # Binary32 values on either side of a half-ULP midpoint, in both signs.
    values = (1 + 3 / 4096, 1 + 1 / 4096, -1 - 3 / 4096, -1 - 1 / 4096)
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, *values)
    program = with_constants([f"v_sub_f32_e64 v{12 + i}, s{44 + i}, 0" for i in range(4)])
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    case = directory / "signed-export.case"
    case.write_bytes(constants + struct.pack("<4f", *map(half_rtz, values)) * 64)
    subprocess.run([renderer, backend, "--check-pixel-case", shader, case], check=True)
    check_class_draw(directory, compiler, renderer, backend)
    check_predicate_draws(directory, compiler, renderer, backend)
    check_sdwa_predicate_draws(directory, compiler, renderer, backend)
    check_literal_fma_draw(directory, compiler, renderer, backend)
    check_e64_draws(directory, compiler, renderer, backend)
    capture = directory / "blend.rgba"
    draw = [renderer, backend, "--dual-pixel", shader, capture]
    for case in DUAL_CASES:
        source.write_text(translate_dual(dual_program(case)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        subprocess.run(draw, check=True)
    wrong = subprocess.run([renderer, backend, "--dual-pixel-swapped", shader, capture], capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Swapped texture bindings escaped detection")
    source.write_text(translate_dual(dual_program(swap_weights=True)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Swapped blend weights escaped detection")
    check_cube_draw(directory, compiler, renderer, backend)
    check_sdwa_draw(directory, compiler, renderer, backend)
    check_sdwa_arith_draws(directory, compiler, renderer, backend)
    check_int_draws(directory, compiler, renderer, backend)
    check_f16_draws(directory, compiler, renderer, backend)
    check_f16_cmp_draws(directory, compiler, renderer, backend)
    check_arith_draws(directory, compiler, renderer, backend)
    check_load_draws(directory, compiler, renderer, backend)
    check_image_draws(directory, compiler, renderer, backend)
    check_fract_draw(directory, compiler, renderer, backend)

    program = scalar64()
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    for values in SCALAR64_SETS:
        case = scalar64_case(directory, values)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        subprocess.run(draw, check=True)
    # Mutations verified against Set 1 (where negative signed values and SCC=1 paths are active).
    set1_case = scalar64_case(directory, SCALAR64_SETS[0])
    draw = [renderer, backend, "--check-pixel-case", shader, set1_case]
    for old, new, label in (
        ("s_ashr_i64 s[72:73], s[52:53], s56", "s_lshr_b64 s[72:73], s[52:53], s56", "signed right shift"),
        ("s_bfe_i32 s72, s60, s61", "s_bfe_u32 s72, s60, s61", "signed bitfield extract"),
        ("s_andn2_b64 s[72:73], s[52:53], s[54:55]", "s_and_b64 s[72:73], s[52:53], s[54:55]", "andn2 inversion"),
        ("s_cmov_b64 s[78:79], -1", "s_cmov_b64 s[78:79], 0", "conditional move"),
    ):
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")
    check_mad_draw(directory, compiler, renderer, backend)
    return 0


def main():
    mode, *args = sys.argv[1:]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        check_controls(directory)
        if mode == "binary":
            check_binary(directory, *args)
        elif mode == "draw":
            return check_render(directory, *args)
        else:
            raise ValueError("Expected binary or draw mode")


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:  # also on skip or failure; tools/form_coverage.py reads the test's status from JUnit
        write_record(os.environ.get("FORM_COVERAGE_RECORD"))
