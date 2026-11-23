"""Draw family `select_vcc`: pixel_aot_check.py draw --family select_vcc.

s_cselect_b64 vcc, -1, 0 and its variants, the SCC-to-VCC copy RADV emits before a v_cndmask whose condition came from a
scalar compare (sascha deferred.frag in the corpus). VCC takes the same bit for every lane: SCC for (-1, 0), its negation
for (0, -1), and a constant for equal sources. The compare is s_cmp_lt_u32 on two constant words (s44 < s45), each
v_cndmask picks between two raw words (s46 for the clear bit, s47 for the set bit) and the low byte of each result is
read back, so the readback is exact. The wrong references are the polarity of the first two selects exchanged, SCC
read as <= (the equal-operands set), and the constant selects exchanged.
"""
import struct
import subprocess

from .common import DrawBatch, half_rtz, must_reject, translate, ubyte, with_constants

BODY = [
    "v_mov_b32_e32 v19, s46", "v_mov_b32_e32 v20, s47",
    "s_cmp_lt_u32 s44, s45",
    "s_cselect_b64 vcc, -1, 0", "v_cndmask_b32_e32 v18, v19, v20, vcc",
    "s_cselect_b64 vcc, 0, -1", "v_cndmask_b32_e32 v21, v19, v20, vcc",
    "s_cselect_b64 vcc, -1, -1", "v_cndmask_b32_e32 v22, v19, v20, vcc",
    "s_cselect_b64 vcc, 0, 0", "v_cndmask_b32_e32 v23, v19, v20, vcc",
    ubyte(0, 12, "v18", "e32"), ubyte(0, 13, "v21", "e32"), ubyte(0, 14, "v22", "e32"), ubyte(0, 15, "v23", "e32"),
]
CLEAR, SET = 0x11d4c3a5, 0x6e77b2f8  # the words chosen by a clear and a set bit; their low bytes are 0xa5 and 0xf8
# (s44, s45): less, greater, equal.
SETS = ((1, 2), (5, 2), (3, 3), (0, 0xffffffff))


def model(a, b, bug=None):
    bit = a <= b if bug == "le" else a < b
    x, y = CLEAR & 0xff, SET & 0xff
    first, second = (x, y) if bit else (y, x)
    if bug == "inverted":
        first, second = second, first
    third, fourth = (x, y) if bug == "constants_swapped" else (y, x)
    return [float(first), float(second), float(third), float(fourth)]


def draw(directory, compiler, renderer, backend):
    source, shader = directory / "select_vcc.hlsl", directory / "select_vcc.cso"
    source.write_text(translate(with_constants(BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    with DrawBatch(directory, renderer, backend, shader, "select_vcc") as batch:
        for a, b in SETS:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, a, b, CLEAR, SET)
            expected = model(a, b)
            assert all(half_rtz(x) == x for x in expected)
            batch.add(constants + struct.pack("<4f", *expected) * 64, "pass", f"s_cselect_b64 vcc gives other than {expected} for {a}, {b}")
            for bug in ("inverted", "le", "constants_swapped"):
                wrong = model(a, b, bug)
                if wrong != expected:
                    batch.add(constants + struct.pack("<4f", *wrong) * 64, "mismatch", f"Wrong vcc select ({bug}) escaped for {a}, {b}")
    # Each wrong reference is distinguishable on some set.
    for bug in ("inverted", "le", "constants_swapped"):
        assert any(model(a, b, bug) != model(a, b) for a, b in SETS), bug


def controls(directory):
    main = translate(with_constants(BODY)).split("float4 main")[1]
    assert main.count("bool lm") == 2, main  # the (-1, 0) and (0, -1) selects; equal sources are constants
    assert "bool lm" in main and "!(" in main, main
    cmp = "s_cmp_lt_u32 s44, s45"
    prefix = ["v_mov_b32_e32 v19, s46", "v_mov_b32_e32 v20, s47"]
    select = [cmp, "s_cselect_b64 vcc, -1, 0", "v_cndmask_b32_e32 v18, v19, v20, vcc"]
    translate(with_constants([*prefix, *select]))
    # SCC must be tracked; only the constants 0 and -1 are lane masks; a pair or another source is not this form.
    must_reject(translate, with_constants([*prefix, *select[1:]]))
    for line in ("s_cselect_b64 vcc, -1, 5", "s_cselect_b64 vcc, s[44:45], 0", "s_cselect_b64 vcc, 0xffffffff, 0",
                 "s_cselect_b64 vcc_lo, -1, 0", "s_cselect_b32 vcc, -1, 0"):
        must_reject(translate, with_constants([*prefix, cmp, line, select[2]]))
    # A write over a scalar load in flight is refused.
    must_reject(translate, with_constants([*prefix, cmp, "s_load_dword vcc_lo, s[20:21], 0x40", "s_cselect_b64 vcc, -1, 0"]))


# No binary_fixtures: the program is wave64 (v_cndmask on vcc), which the wave32 assembler of `binary` mode rejects.
