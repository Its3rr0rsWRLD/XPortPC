"""SOPC controls: all 18 RDNA2 scalar comparisons in one accepted program, and the neighbours that must be refused
(from R0Y00/Xbox2Windows#494 by Dr Doom). The forms are forms/sopc.py; their draws are int_compare and salu_rest.
Upstream checked its own HLSL spelling; these checks name ours (forms/sopc.py): the signed relations compare int(),
the 64-bit ones both words, and the b64 bit tests read bit S1[5:0] through s_lshr_b64."""
from .common import ACCEPTED, must_reject, translate, with_constants

SOPC_OPS = (
    "s_cmp_eq_i32", "s_cmp_lg_i32", "s_cmp_gt_i32", "s_cmp_ge_i32", "s_cmp_lt_i32", "s_cmp_le_i32",
    "s_cmp_eq_u32", "s_cmp_lg_u32", "s_cmp_gt_u32", "s_cmp_ge_u32", "s_cmp_lt_u32", "s_cmp_le_u32",
    "s_cmp_eq_u64", "s_cmp_lg_u64",
    "s_bitcmp0_b32", "s_bitcmp1_b32",
    "s_bitcmp0_b64", "s_bitcmp1_b64",
)


def sopc_group():
    body = ["s_mov_b32 s70, 0", "s_mov_b32 s71, 0", "s_mov_b32 s72, 1", "s_mov_b32 s73, 0"]
    for op in SOPC_OPS[:12]:
        body.extend([f"{op} s44, s45", "s_cmov_b64 s[70:71], s[72:73]"])
    body.extend([
        "s_cmp_eq_u64 s[44:45], s[46:47]", "s_cmov_b64 s[70:71], s[72:73]",
        "s_cmp_lg_u64 s[44:45], s[46:47]", "s_cmov_b64 s[70:71], s[72:73]",
        "s_bitcmp0_b32 s44, 5", "s_cmov_b64 s[70:71], s[72:73]",
        "s_bitcmp1_b32 s44, 5", "s_cmov_b64 s[70:71], s[72:73]",
        "s_bitcmp0_b64 s[44:45], 37", "s_cmov_b64 s[70:71], s[72:73]",
        "s_bitcmp1_b64 s[44:45], 37", "s_cmov_b64 s[70:71], s[72:73]",
    ])
    return with_constants(body)


def controls(directory):
    source = translate(sopc_group())
    assert set(SOPC_OPS) <= ACCEPTED
    for expected in (
        "(params[0].w == params[1].x)",
        "(int(params[0].w) < int(params[1].x))",
        "(params[0].w < params[1].x)",
        "((params[0].w == params[1].y) && (params[1].x == params[1].z))",
        "(!((params[0].w == params[1].y) && (params[1].x == params[1].z)))",
        "(((params[0].w >> (5u & 31u)) & 1u) == 0u)",
        "(((params[0].w >> (5u & 31u)) & 1u) == 1u)",
        "((s_lshr_b64(uint2(params[0].w, params[1].x), 37u).x & 1u) == 0u)",
        "((s_lshr_b64(uint2(params[0].w, params[1].x), 37u).x & 1u) == 1u)",
    ):
        assert expected in source, expected
    for bad in (
        "s_cmp_gt_u64 s[44:45], s[46:47]",
        "s_cmp_eq_i64 s[44:45], s[46:47]",
        "s_cmp_eq_u64 s[65:66], s[46:47]",
        "s_cmp_eq_u32 s106, s44",
        "s_cmp_eq_u64 s[105:106], s[46:47]",
    ):
        must_reject(translate, with_constants([bad]))


def binary_fixtures():
    return [(sopc_group(), translate)]
