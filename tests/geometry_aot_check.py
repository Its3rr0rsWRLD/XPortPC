"""Exercise offline NGG geometry-shader translation (card G-1, docs/design/stages.md).

Modes:
    geometry_aot_check.py --list-families
    geometry_aot_check.py controls                                     no DXC, no GPU
    geometry_aot_check.py draw <dxc> <offscreen_check> warp|hardware [--family NAME ...]
    geometry_aot_check.py binary <llvm-mc> <llvm-objcopy>              assemble, disassemble (wave64) and lower again

A draw translates an ES+GS program with tools/geometry_aot.py into a vertex shader (vs_6_0) and a geometry shader
(gs_6_0), draws a triangle list through both and compares every stream-output dword of the GS output with a reference
computed here by a model of the merged console wave (GeometryModel): the ES half runs once per vertex lane and writes a
64 KiB LDS byte array, the GS half runs once per primitive lane with the console's packed vertex offsets in v0 and v1
and writes its output vertices and primitive flags to the same array, and the reference then assembles the triangles
from the flags as RADV's epilogue exports them (ac_nir_lower_ngg_gs.c: indices k-2, k-1+odd, k-odd) and reads each
vertex's exported words at the byte offsets the program's epilogue reads. The model does not use the translator's frame
matcher: it runs the ES and GS bodies the test wrote, idiom lines included, and takes the vertex layout (stride, flag
offset, export map) from the test's own parameters. Each family also proves its wrong references are caught: the D3D
strip order for odd triangles, a dropped strip cut, a dead vertex slot drawn, input vertices 1 and 2 swapped, an ES
word read one word off, the base vertex ignored, a fused multiply-add.

The programs: "corpus" is the committed RADV dump of Vulkan-Samples shader_object material_pass_through.geom
(tests/corpus/isa/stages; Apache-2.0, see tests/corpus/README.md) with its user-SGPR roles as
tools/stage_corpus_report.py reads them; "explode" and "strips" are hand-written in RADV's shape with the frame text of
that dump: a four-vertex strip with an odd triangle and a cleared fifth slot, GS arithmetic on the three input
vertices (a face normal), constants read by both halves and partial lgkmcnt waits; and two strips separated by a cut
with permuted inputs and raw (NaN) words passed through.
"""
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import corpus_translate  # noqa: E402
import geometry_aot  # noqa: E402
import stage_corpus_report  # noqa: E402
from pixel_aot_ops.dispatch import claimants  # noqa: E402
import vertex_aot_check as vc  # noqa: E402

M32 = 0xffffffff
HIGH = vc.HIGH
CORPUS = ROOT / "tests" / "corpus" / "isa" / "stages" / "vksamples__shader_object__material_pass_through.geom+skybox.vert.s"
ACCEPTED = set()


def lower(program, roles):
    vs, gs, layout = geometry_aot.lower(program, roles)
    lines = [line.split(";")[0].strip() for line in program]
    ACCEPTED.update(line.split()[0] for line in lines if line and not line.endswith(":"))
    for line in lines:
        if len(families := claimants(line)) > 1:
            raise AssertionError(f"Forms of more than one family match {line!r}: {', '.join(families)}")
    return vs, gs, layout


def write_record(path):
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("".join(f"{word}\n" for word in sorted(ACCEPTED)), encoding="utf-8")


def must_refuse(program, roles, reason):
    try:
        geometry_aot.lower(program, roles)
    except ValueError as error:
        if reason not in str(error):
            raise AssertionError(f"Refused for another reason: {error} (expected {reason!r})")
        return
    raise AssertionError(f"Accepted a program that must be refused ({reason})")


# --- the frame, as RADV 25.2.8 prints it for gfx1013 (the corpus dump above, registers kept) --------------------------

GDS = """BB8:
s_and_b64 s[4:5], -1, exec
s_bcnt1_i32_b64 s4, s[4:5]
s_ff1_i32_b64 s5, exec
s_lshl_b64 s[6:7], 1, s5
s_and_b64 s[0:1], s[0:1], s[6:7]
s_waitcnt_depctr 0xffe3
s_and_saveexec_b64 s[0:1], s[0:1]
s_cbranch_execz BB21
BB9:
s_movk_i32 m0, 0x100
v_mov_b32_e32 v0, s4
v_mov_b32_e32 v1, 0
ds_add_u32 v1, v0 gds
v_mov_b32_e32 v2, 4
ds_add_u32 v2, v0 gds"""

EPILOGUE = """BB21:
s_waitcnt expcnt(0)
s_waitcnt_depctr 0xffe3
s_mov_b64 exec, -1
s_waitcnt lgkmcnt(0)
s_barrier
s_bfe_u32 s0, s3, 0x40018
s_lshl_b32 s1, s0, 6
s_bfe_u32 s2, s2, 0x9000c
v_mbcnt_lo_u32_b32 v0, -1, s1
v_mbcnt_hi_u32_b32 v0, -1, v0
v_mad_u32_u24 v1, {S}, v0, {L}
s_waitcnt_depctr 0xfffe
v_cmpx_gt_i32_e32 s2, v0
s_cbranch_execz BB25
BB22:
ds_read_u8 v2, v1 offset:{F}
BB25:
s_waitcnt_depctr 0xffe3
s_andn2_b64 exec, -1, exec
v_mov_b32_e32 v2, 0
BB27:
s_mov_b64 exec, -1
s_waitcnt lgkmcnt(0)
v_cmp_ne_i32_e32 vcc, 0, v2
s_mov_b64 exec, 1
s_bcnt1_i32_b64 s1, vcc
BB28:
s_add_u32 s4, {L}, s0
v_mov_b32_e32 v4, s1
v_mov_b32_e32 v3, s4
ds_write_b8 v3, v4
s_waitcnt lgkmcnt(0)
s_barrier
v_mov_b32_e32 v5, {L}
ds_read_b32 v5, v5
BB33:
s_waitcnt_depctr 0xffe3
s_mov_b64 exec, -1
v_mbcnt_lo_u32_b32 v3, -1, 0
v_mbcnt_hi_u32_b32 v3, -1, v3
v_mad_i32_i24 v4, v3, -8, 24
s_waitcnt lgkmcnt(0)
v_permlane16_b32 v5, v5, 0, 0
v_lshlrev_b32_e32 v4, v4, v5
v_msad_u8 v4, 0, v4, 0
v_readlane_b32 s4, v4, s0
s_sub_i32 s4, s4, s1
s_lshr_b32 s3, s3, 28
v_mbcnt_lo_u32_b32 v5, vcc_lo, s4
s_add_u32 s3, s3, -1
v_readlane_b32 s3, v4, s3
v_mbcnt_hi_u32_b32 v5, vcc_hi, v5
s_cmp_lg_i32 s3, 0
s_mul_i32 s2, s2, src_scc
s_cmp_eq_i32 s0, 0
s_cbranch_scc0 BB45
BB34:
s_cmp_eq_i32 s2, 0
s_cbranch_scc0 BB42
BB35:
s_movk_i32 m0, 0x1001
s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)
v_cmpx_eq_i32_e32 0, v3
s_cbranch_execz BB45
BB36:
v_mov_b32_e32 v3, 0
v_mov_b32_e32 v4, -1
exp prim v3, off, off, off done
exp pos0 v4, v4, v4, v4 done
s_branch BB45
BB42:
s_lshl_b32 s0, s2, 12
s_or_b32 m0, s0, s3
s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)
BB45:
s_waitcnt expcnt(0)
s_mov_b64 exec, vcc
s_cbranch_execz BB51
BB46:
v_mul_lo_u32 v3, {S}, v5
v_mov_b32_sdwa v4, v0 dst_sel:BYTE_0 dst_unused:UNUSED_PRESERVE src0_sel:BYTE_0
v_add_nc_u32_e32 v3, {L}, v3
ds_write_b8 v3, v4 offset:{F1}
BB51:
s_waitcnt_depctr 0xffe3
s_mov_b64 exec, -1
s_waitcnt lgkmcnt(0)
s_barrier
v_cmpx_gt_i32_e32 s2, v0
s_mov_b64 vcc, exec
BB52:
v_bfe_u32 v3, v2, 1, 1
v_not_b32_e32 v2, v2
v_sub_nc_u32_e32 v4, v5, v3
v_add_lshl_u32 v3, v5, v3, 10
v_add_nc_u32_e32 v5, -2, v5
v_lshlrev_b32_e32 v4, 20, v4
v_add_nc_u32_e32 v3, 0xfffffc00, v3
v_or3_b32 v4, v4, v5, v3
v_lshl_or_b32 v2, v2, 31, v4
BB57:
s_mov_b64 exec, -1
s_waitcnt_depctr 0xfffe
v_cmpx_gt_i32_e32 s3, v0
s_mov_b64 s[0:1], exec
s_cbranch_execz BB63
BB58:
ds_read_u8 v1, v1 offset:{F1}
s_waitcnt lgkmcnt(0)
v_mad_u32_u24 v1, {S}, v1, {L}
{READS}
BB63:
s_waitcnt_depctr 0xffe3
s_mov_b64 exec, vcc
s_cbranch_execz BB69
BB64:
exp prim v2, off, off, off done
BB69:
s_waitcnt expcnt(0)
s_mov_b64 exec, s[0:1]
s_cbranch_execz BB75
BB70:
s_waitcnt lgkmcnt(0)
{EXPORTS}
BB75:
s_endpgm"""


def frame(es_body, gs_body, lds, stride, flag, reads, exports):
    """A whole ES+GS program: the ES region, the GS region, the statistics block and the epilogue. reads are the
    epilogue's vertex reads through v1, exports its exp lines."""
    epilogue = EPILOGUE.format(S=stride, F=flag, F1=flag + 1, L=lds, READS="\n".join(reads),
                               EXPORTS="\n".join(exports))
    return ["s_setprio 3", "s_pack_ll_b32_b16 s0, 0, s3", "s_bfe_u64 exec, -1, s0", "s_cbranch_execz BB6", "BB1:",
            *es_body, "BB6:", "s_waitcnt lgkmcnt(0)", "s_barrier", "s_lshl_b32 s0, s3, 8",
            f"s_pack_ll_b32_b16 {lds}, {lds}, 0", "s_bfe_u64 s[0:1], -1, s0", "s_mov_b64 exec, s[0:1]",
            "s_cbranch_execz BB21", "BB7:", *gs_body, "s_cbranch_scc0 BB21", *GDS.split("\n"), *epilogue.split("\n")]


def lane_idiom(sgpr, vgpr):
    return [f"s_bfe_u32 {sgpr}, s3, 0x40018", f"s_lshl_b32 {sgpr}, {sgpr}, 6", f"v_mbcnt_lo_u32_b32 {vgpr}, -1, {sgpr}",
            f"v_mbcnt_hi_u32_b32 {vgpr}, -1, {vgpr}"]


# --- programs ----------------------------------------------------------------------------------------------------------

LDS = "s24"
QUERY = "s25"
ROLES = {8: ("descriptors", HIGH, {0: ("vsharp", 0), 16: ("vsharp", 4)}), 9: ("base_vertex",),
         10: ("descriptors", HIGH, {0: ("constants",)}), 24: ("ngg_lds_layout",), 25: ("ngg_query_state",)}

# ES: two V#s through the list in s8, the base vertex in s9, constants through s10; four position words and two raw
# words per vertex, stride 28 (seven dwords).
ES_A = [
    "s_mov_b32 s0, s9",
    "s_movk_i32 s9, 0x8000",
    "s_load_dwordx8 s[12:19], s[8:9], null",
    "v_add_nc_u32_e32 v5, s0, v5",
    "s_movk_i32 s11, 0x8000",
    "s_load_dwordx4 s[20:23], s[10:11], null",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dwordx4 v[6:9], v5, s[12:15], 0 idxen",
    "buffer_load_dwordx2 v[10:11], v5, s[16:19], 0 idxen offset:4",
    "s_buffer_load_dwordx8 s[28:35], s[20:23], null",
    *lane_idiom("s1", "v12"),
    "v_mul_u32_u24_e32 v12, 28, v12",
    "s_waitcnt lgkmcnt(0)",
    "s_waitcnt vmcnt(1)",
    *[line for c in range(4) for line in (f"v_mul_f32_e64 v{13 + c}, s{28 + c}, v{6 + c}",
                                          f"v_add_f32_e32 v{13 + c}, s{32 + c}, v{13 + c}")],
    "ds_write2_b32 v12, v13, v14 offset1:1",
    "ds_write2_b32 v12, v15, v16 offset0:2 offset1:3",
    "s_waitcnt vmcnt(0)",
    "ds_write2_b32 v12, v10, v11 offset0:4 offset1:5",
]

QUERY_IDIOM = [f"s_bfe_u32 {QUERY}, {QUERY}, 0x30006", f"s_bitcmp1_b32 {QUERY}, 0", "s_cselect_b64 s[0:1], -1, 0"]


def emit(address, k, stride, words, flag_register):
    """ds_write lines for emitted vertex k: the words (registers, in output-word order) and the flag byte."""
    base = (k * stride + geometry_aot.SCRATCH_BYTES) // 4
    lines = []
    for j in range(0, len(words) - 1, 2):
        lines.append(f"ds_write2_b32 {address}, {words[j]}, {words[j + 1]} offset0:{base + j} offset1:{base + j + 1}")
    if len(words) % 2:
        lines.append(f"ds_write_b32 {address}, {words[-1]} offset:{4 * (base + len(words) - 1)}")
    lines.append(f"ds_write_b8 {address}, {flag_register} offset:{k * stride + stride}")
    return lines


# GS "explode": face normal n = (p1 - p0) x (p2 - p0); a strip of four vertices p0 + n*c, p1 + n*c, p2 + n*c,
# p1 + p2 - p0 (two triangles, the second odd), param1 = (n.x, raw word 4 of vertex 0); max_vertices 5, the last
# slot cleared. Vertex stride 28: six output words and the flag (seven dwords).
EXPLODE_STRIDE, EXPLODE_FLAG, EXPLODE_MAX = 28, 28, 5
GS_EXPLODE = [
    "v_mad_u32_u16 v2, 28, v0, 0",
    "ds_read2_b32 v[20:21], v2 offset1:1",
    "ds_read2_b32 v[22:23], v2 offset0:2 offset1:3",
    "ds_read_b32 v24, v2 offset:16",
    "s_bfe_u32 s0, s3, 0x40018",
    "v_mov_b32_e32 v40, 4",
    "v_mad_u32_u16 v0, 28, v0, 0 op_sel:[0,1,0,0]",
    "v_mad_u32_u16 v1, 28, v1, 0",
    "v_mov_b32_e32 v41, 5",
    "v_mov_b32_e32 v42, 7",
    "v_mov_b32_e32 v43, 0",
    "s_lshl_b32 s0, s0, 6",
    "s_movk_i32 s11, 0x8000",
    "s_load_dwordx4 s[4:7], s[10:11], null",
    QUERY_IDIOM[0],
    "v_mbcnt_lo_u32_b32 v3, -1, s0",
    QUERY_IDIOM[1],
    QUERY_IDIOM[2],
    "v_mbcnt_hi_u32_b32 v3, -1, v3",
    f"v_mad_u32_u24 v3, {EXPLODE_STRIDE * EXPLODE_MAX}, v3, {LDS}",
    "ds_read2_b32 v[25:26], v0 offset1:1",
    "ds_read2_b32 v[27:28], v0 offset0:2 offset1:3",
    "ds_read2_b32 v[29:30], v1 offset1:1",
    "ds_read2_b32 v[31:32], v1 offset0:2 offset1:3",
    "s_waitcnt lgkmcnt(0)",
    "s_buffer_load_dwordx2 s[12:13], s[4:7], 0x20",
    "v_sub_f32_e32 v50, v25, v20",
    "v_sub_f32_e32 v51, v26, v21",
    "v_sub_f32_e32 v52, v27, v22",
    "v_sub_f32_e32 v53, v29, v20",
    "v_sub_f32_e32 v54, v30, v21",
    "v_sub_f32_e32 v55, v31, v22",
    "v_mul_f32_e32 v56, v51, v55",
    "v_mul_f32_e32 v59, v52, v54",
    "v_sub_f32_e32 v56, v56, v59",
    "v_mul_f32_e32 v57, v52, v53",
    "v_mul_f32_e32 v59, v50, v55",
    "v_sub_f32_e32 v57, v57, v59",
    "v_mul_f32_e32 v58, v50, v54",
    "v_mul_f32_e32 v59, v51, v53",
    "v_sub_f32_e32 v58, v58, v59",
    "s_waitcnt lgkmcnt(0)",
    *[f"v_mac_f32_e32 v{20 + c}, s12, v{56 + c}" for c in range(3)],
    *[f"v_mac_f32_e32 v{25 + c}, s12, v{56 + c}" for c in range(3)],
    *[f"v_mac_f32_e32 v{29 + c}, s12, v{56 + c}" for c in range(3)],
    *[f"v_add_f32_e32 v{60 + c}, v{25 + c}, v{29 + c}" for c in range(4)],
    *[f"v_sub_f32_e32 v{60 + c}, v{60 + c}, v{20 + c}" for c in range(4)],
    "v_mul_f32_e32 v64, s13, v56",
    *emit("v3", 0, EXPLODE_STRIDE, ["v20", "v21", "v22", "v23", "v64", "v24"], "v40"),
    *emit("v3", 1, EXPLODE_STRIDE, ["v25", "v26", "v27", "v28", "v64", "v24"], "v40"),
    *emit("v3", 2, EXPLODE_STRIDE, ["v29", "v30", "v31", "v32", "v64", "v24"], "v41"),
    *emit("v3", 3, EXPLODE_STRIDE, ["v60", "v61", "v62", "v63", "v64", "v24"], "v42"),
    f"ds_write_b8 v3, v43 offset:{4 * EXPLODE_STRIDE + EXPLODE_FLAG}",
]
EXPLODE_READS = ["ds_read2_b32 v[4:5], v1 offset0:1 offset1:2", "ds_read2_b32 v[6:7], v1 offset0:3 offset1:4",
                 "ds_read2_b32 v[8:9], v1 offset0:5 offset1:6"]
EXPLODE_EXPORTS = ["exp pos0 v4, v5, v6, v7 done vm", "exp param1 v8, v9, off, off"]
EXPLODE_LAYOUT = {"es_stride": 28, "stride": EXPLODE_STRIDE, "flag": EXPLODE_FLAG, "max": EXPLODE_MAX,
                  "exports": [("pos0", [0, 4, 8, 12]), ("param1", [16, 20, None, None])]}
EXPLODE = frame(ES_A, GS_EXPLODE, LDS, EXPLODE_STRIDE, EXPLODE_FLAG, EXPLODE_READS, EXPLODE_EXPORTS)

# GS "strips": two strips separated by a cut, inputs in the order 2, 0, 1 and then 1, 2, 0; the raw ES words pass
# through as param0 (NaN payloads must survive) and param2 holds vertex 0's x scaled by a constant read in the GS.
# max_vertices 7, the last slot cleared. Vertex stride 44: ten output words and the flag (eleven dwords).
STRIPS_STRIDE, STRIPS_FLAG, STRIPS_MAX = 44, 44, 7
GS_STRIPS = [
    *QUERY_IDIOM[:1],
    "v_mad_u32_u16 v2, 28, v1, 0",
    "v_mad_u32_u16 v4, 28, v0, 0",
    "v_mad_u32_u16 v5, 28, v0, 0 op_sel:[0,1,0,0]",
    *lane_idiom("s1", "v6"),
    f"v_mad_u32_u24 v6, {STRIPS_STRIDE * STRIPS_MAX}, v6, {LDS}",
    *QUERY_IDIOM[1:],
    "ds_read2_b32 v[10:11], v2 offset1:1",
    "ds_read2_b32 v[12:13], v2 offset0:2 offset1:3",
    "ds_read2_b32 v[14:15], v2 offset0:4 offset1:5",
    "ds_read2_b32 v[16:17], v4 offset1:1",
    "ds_read2_b32 v[18:19], v4 offset0:2 offset1:3",
    "ds_read2_b32 v[20:21], v4 offset0:4 offset1:5",
    "ds_read2_b32 v[22:23], v5 offset1:1",
    "ds_read2_b32 v[24:25], v5 offset0:2 offset1:3",
    "ds_read2_b32 v[26:27], v5 offset0:4 offset1:5",
    "v_mov_b32_e32 v40, 4",
    "v_mov_b32_e32 v41, 5",
    "v_mov_b32_e32 v42, 0",
    "s_waitcnt lgkmcnt(6)",
    "v_mul_f32_e32 v30, 0.5, v10",
    "s_waitcnt lgkmcnt(3)",
    "v_mul_f32_e32 v31, 0.5, v16",
    "s_waitcnt lgkmcnt(0)",
    "v_mul_f32_e32 v32, 0.5, v22",
    *emit("v6", 0, STRIPS_STRIDE, ["v10", "v11", "v12", "v13", "v14", "v15", "v42", "v42", "v30", "v42"], "v40"),
    *emit("v6", 1, STRIPS_STRIDE, ["v16", "v17", "v18", "v19", "v20", "v21", "v42", "v42", "v31", "v42"], "v40"),
    *emit("v6", 2, STRIPS_STRIDE, ["v22", "v23", "v24", "v25", "v26", "v27", "v42", "v42", "v32", "v42"], "v41"),
    *emit("v6", 3, STRIPS_STRIDE, ["v22", "v23", "v24", "v25", "v26", "v27", "v42", "v42", "v32", "v42"], "v40"),
    *emit("v6", 4, STRIPS_STRIDE, ["v10", "v11", "v12", "v13", "v14", "v15", "v42", "v42", "v30", "v42"], "v40"),
    *emit("v6", 5, STRIPS_STRIDE, ["v16", "v17", "v18", "v19", "v20", "v21", "v42", "v42", "v31", "v42"], "v41"),
    f"ds_write_b8 v6, v42 offset:{6 * STRIPS_STRIDE + STRIPS_FLAG}",
]
STRIPS_READS = ["ds_read2_b32 v[4:5], v1 offset0:1 offset1:2", "ds_read2_b32 v[6:7], v1 offset0:3 offset1:4",
                "ds_read2_b32 v[8:9], v1 offset0:5 offset1:6", "ds_read2_b32 v[10:11], v1 offset0:7 offset1:8",
                "ds_read_b32 v12, v1 offset:36"]
STRIPS_EXPORTS = ["exp pos0 v4, v5, v6, v7 done vm", "exp param0 v8, v9, v10, v11", "exp param2 v12, off, off, off"]
STRIPS_LAYOUT = {"es_stride": 28, "stride": STRIPS_STRIDE, "flag": STRIPS_FLAG, "max": STRIPS_MAX,
                 "exports": [("param0", [16, 20, 24, 28]), ("pos0", [0, 4, 8, 12]), ("param2", [32, None, None, None])]}
STRIPS = frame(ES_A, GS_STRIPS, LDS, STRIPS_STRIDE, STRIPS_FLAG, STRIPS_READS, STRIPS_EXPORTS)


def corpus_program():
    program = corpus_translate.read_dump(CORPUS)
    return program, stage_corpus_report.geometry_contract(program)


CORPUS_LAYOUT = {"es_stride": 20, "stride": 20, "flag": 20, "max": 3, "exports": [("pos0", [0, 4, 8, 12])]}


# --- the reference model -----------------------------------------------------------------------------------------------

class GeometryModel:
    """The merged wave, lane by lane. flaws switch single rules to a plausible wrong one."""

    def __init__(self, roles, constants, memory, flaws=(), descriptors=None, push=()):
        self.roles, self.constants, self.memory, self.flaws = roles, constants, memory, set(flaws)
        self.descriptors = constants[:64] if descriptors is None else descriptors
        self.push = list(push) + [0] * (32 - len(push))
        self.vertex = vc.Model(roles, constants, memory, flaws, descriptors, push, "ngg")

    def entry(self, base_vertex, lds_base):
        s = {}
        for number, role in self.roles.items():
            if role[0] == "descriptors":
                s[number] = ("pointer", number)
            elif role[0] == "base_vertex":
                s[number] = 0 if "base_ignored" in self.flaws else base_vertex
            elif role[0] == "inline":
                s[number] = self.push[role[1]]
            elif role[0] == "ngg_lds_layout":
                s[number] = lds_base
            elif role[0] == "ngg_query_state":
                s[number] = 0  # the pipeline-statistics query bit is clear
        s[3] = 0  # merged_wave_info: wave 0 of the subgroup (bits 24..27)
        s[2] = 0
        return s

    def run(self, body, lane, s, v, lds):
        def word(token):
            token = token.split()[0]
            if token.startswith("-") and not re.fullmatch(r"-\d+", token):
                return word(token[1:]) ^ 0x80000000
            if re.fullmatch(r"v\d+", token):
                return v[int(token[1:])]
            if re.fullmatch(r"s\d+", token):
                value = s[int(token[1:])]
                assert isinstance(value, int), (token, value)
                return value
            if token in vc.INLINE_FLOAT:
                return vc.INLINE_FLOAT[token]
            if re.fullmatch(r"-?\d+|0x[0-9a-f]+", token):
                return int(token, 0) & M32
            raise AssertionError(f"Model has no operand {token}")

        def span(token):
            if m := re.fullmatch(r"([sv])\[(\d+):(\d+)\]", token):
                return list(range(int(m[2]), int(m[3]) + 1))
            return [int(token[1:])]

        scc = 0
        for raw in body:
            line = raw.split(";")[0].strip()
            if not line or line.endswith(":"):
                continue
            head, _, rest = line.partition(" ")
            ops = [t.strip() for t in rest.split(",")]
            name = re.sub(r"_e(32|64)$", "", head)
            if name in ("s_setprio", "s_clause", "s_nop", "s_waitcnt", "s_waitcnt_depctr", "s_barrier"):
                continue
            if name == "s_mov_b32":
                s[int(ops[0][1:])] = s[int(ops[1][1:])] if ops[1].startswith("s") else word(ops[1])
            elif name == "s_movk_i32":
                imm = int(ops[1], 0)
                s[int(ops[0][1:])] = (imm - 0x10000 if imm & 0x8000 else imm) & M32
            elif name == "s_bfe_u32":
                imm = word(ops[2])
                offset, width = imm & 31, (imm >> 16) & 0x7f
                s[int(ops[0][1:])] = (word(ops[1]) >> offset) & ((1 << width) - 1)
            elif name == "s_lshl_b32":
                s[int(ops[0][1:])] = (word(ops[1]) << (word(ops[2]) & 31)) & M32
            elif name == "s_bitcmp1_b32":
                scc = word(ops[0]) >> word(ops[1]) & 1
            elif name == "s_cselect_b64":
                for n in span(ops[0]):
                    s[n] = M32 if scc else 0
            elif name.startswith("s_load_dword") or name.startswith("s_buffer_load_dword"):
                self.scalar_load(name, ops, s, span)
            elif name.startswith("buffer_load_dword"):
                self.vertex.fetch(ops, v, s, span)
            elif name == "v_mbcnt_lo_u32_b32":
                assert ops[1] == "-1"
                v[int(ops[0][1:])] = (min(lane, 32) + word(ops[2])) & M32
            elif name == "v_mbcnt_hi_u32_b32":
                assert ops[1] == "-1"
                v[int(ops[0][1:])] = (max(lane - 32, 0) + word(ops[2])) & M32
            elif name == "v_mul_u32_u24":
                v[int(ops[0][1:])] = ((word(ops[1]) & 0xffffff) * (word(ops[2]) & 0xffffff)) & M32
            elif name == "v_mad_u32_u24":
                v[int(ops[0][1:])] = ((word(ops[1]) & 0xffffff) * (word(ops[2]) & 0xffffff) + word(ops[3])) & M32
            elif name == "v_mad_u32_u16":
                # The input-vertex address: vertex 0 is v0[15:0], vertex 1 v0[31:16] (op_sel), vertex 2 v1[15:0].
                which = 1 if "op_sel:[0,1,0,0]" in line else (0 if ops[2] == "v0" else 2)
                b = word(ops[2]) >> 16 if which == 1 else word(ops[2])
                if "input_swap" in self.flaws and which in (1, 2):  # a wrong reference: vertices 1 and 2 exchanged
                    b = self.gs_entry[1] & 0xffff if which == 1 else self.gs_entry[0] >> 16
                v[int(ops[0][1:])] = ((word(ops[1]) & 0xffff) * (b & 0xffff) + word(ops[3])) & M32
            elif name == "v_add_nc_u32":
                v[int(ops[0][1:])] = (word(ops[1]) + word(ops[2])) & M32
            elif name == "v_mov_b32":
                v[int(ops[0][1:])] = word(ops[1])
            elif name == "v_mul_f32":
                v[int(ops[0][1:])] = vc.f32_mul(word(ops[1]), word(ops[2]))
            elif name == "v_add_f32":
                v[int(ops[0][1:])] = vc.f32_add(word(ops[1]), word(ops[2]))
            elif name == "v_sub_f32":
                v[int(ops[0][1:])] = vc.f32_add(word(ops[1]), word(ops[2]) ^ 0x80000000)
            elif name == "v_mad_f32":
                v[int(ops[0][1:])] = vc.f32_mad(word(ops[1]), word(ops[2]), word(ops[3]), "fused" in self.flaws)
            elif name == "v_mac_f32":
                v[int(ops[0][1:])] = vc.f32_mad(word(ops[1]), word(ops[2]), word(ops[0]), "fused" in self.flaws)
            elif name.startswith("ds_"):
                self.lds(name, line, ops, v, lds, word, span)
            else:
                raise AssertionError(f"Model has no instruction {line}")

    def scalar_load(self, name, ops, s, span):
        if name.startswith("s_load_dword"):
            pointer = s[span(ops[1])[0]]
            table_high, entries = self.roles[pointer[1]][1:]
            assert s[span(ops[1])[1]] == table_high
            offset = 0 if ops[2] == "null" else int(ops[2], 0)
            for j, n in enumerate(span(ops[0])):
                at = offset + 4 * j
                start = next(k for k in entries if k <= at < k + 16)
                entry = entries[start]
                s[n] = ("cbv", (at - start) // 4) if entry == ("constants",) else \
                    self.descriptors[entry[1] + (at - start) // 4]
        else:
            assert [s[n] for n in span(ops[1])] == [("cbv", j) for j in range(4)]
            offset = 0 if ops[2] == "null" else int(ops[2], 0)
            for j, n in enumerate(span(ops[0])):
                s[n] = self.constants[offset // 4 + j]

    def lds(self, name, line, ops, v, lds, word, span):
        def offsets():
            if m := re.search(r"offset0:(\d+) offset1:(\d+)", line):
                return [4 * int(m[1]), 4 * int(m[2])]
            if m := re.search(r"offset1:(\d+)", line):
                return [0, 4 * int(m[1])]
            if m := re.search(r"offset0:(\d+)", line):
                return [4 * int(m[1]), 0]
            m = re.search(r"offset:(\d+)", line)
            return [int(m[1]) if m else 0]

        if name.startswith("ds_write"):
            address = word(ops[0])
            if name == "ds_write_b8":
                lds[address + offsets()[0]] = word(ops[1]) & 0xff
                return
            if name == "ds_write2_b32":
                pairs = zip(offsets(), [word(ops[1]), word(ops[2].split()[0])])
            else:
                pairs = zip([offsets()[0] + 4 * j for j in range(len(span(ops[1].split()[0])))],
                            [v[n] for n in span(ops[1].split()[0])])
            for at, value in pairs:
                lds[address + at:address + at + 4] = value.to_bytes(4, "little")
            return
        address = word(ops[1])
        dest = span(ops[0])
        at = offsets() if name == "ds_read2_b32" else [offsets()[0] + 4 * j for j in range(len(dest))]
        if "es_word_shift" in self.flaws:
            # A wrong reference: the GS reads the next position word of its input vertex (x from y, ..., w from x).
            stride = self.layout["es_stride"]
            at = [o - (address + o) % stride + ((address + o) % stride + 4) % 16 if (address + o) % stride < 16 else o
                  for o in at]
        for n, offset in zip(dest, at):
            v[n] = int.from_bytes(lds[address + offset:address + offset + 4], "little")

    def draw(self, es_body, gs_body, layout, vertices, base_vertex, lds_base=0x6000):
        """Expected words and masks of the stream output: per primitive, per triangle, per vertex, each export in
        layout order (geometry_aot's output order). A channel the epilogue exports as off has mask 0."""
        assert len(vertices) % 3 == 0
        self.layout = layout
        lds = bytearray(0x10000)
        for lane, vertex_id in enumerate(vertices):
            s = self.entry(base_vertex, lds_base)
            self.run(es_body, lane, s, {5: vertex_id, 8: 0}, lds)
        stride, flag, max_vertices = layout["stride"], layout["flag"], layout["max"]
        expected, mask = [], []
        for prim in range(len(vertices) // 3):
            s = self.entry(base_vertex, lds_base)
            v = {0: (3 * prim) | (3 * prim + 1) << 16, 1: 3 * prim + 2, 2: prim, 3: 0}
            self.gs_entry = (v[0], v[1])
            self.run(gs_body, prim, s, v, lds)
            base = lds_base + prim * max_vertices * stride
            flags = [lds[base + k * stride + flag] for k in range(max_vertices)]
            triangles = []
            strip = []
            for k, f in enumerate(flags):
                if not f and "dead_kept" not in self.flaws:
                    continue
                if f & 1 or ("dead_kept" in self.flaws and not f and len(strip) >= 2):
                    odd = f >> 1 & 1
                    if "flags_as_one_strip" in self.flaws:
                        odd = (len(strip) - 2) & 1 if len(strip) >= 2 else 0
                    order = (k - 2, k - 1 + odd, k - odd)
                    if odd and "d3d_strip" in self.flaws:
                        order = (k - 1, k - 2, k)
                    if "flags_as_one_strip" not in self.flaws or len(strip) >= 2:
                        triangles.append(order)
                strip.append(k)
            if "flags_as_one_strip" in self.flaws:
                live = [k for k, f in enumerate(flags) if f]
                triangles = [(live[i], live[i + 1], live[i + 2]) if i % 2 == 0 else (live[i + 1], live[i], live[i + 2])
                             for i in range(len(live) - 2)]
            exports = sorted(layout["exports"], key=lambda e: -1 if e[0] == "pos0" else int(e[0][5:]))
            for triangle in triangles:
                for k in triangle:
                    address = base + k * stride + geometry_aot.SCRATCH_BYTES
                    for _, fields in exports:
                        for field in fields:
                            if field is None:
                                expected.append(0)
                                mask.append(0)
                            else:
                                word = int.from_bytes(lds[address + field:address + field + 4], "little")
                                expected.append(self.vertex.export_word(word))
                                mask.append(M32)
        return expected, mask


def geometry_case(vertices, base_vertex, params, constants, expected, mask, memory, descriptors=None, push=()):
    """tests/vertex_aot_render.cpp's case file with the GS output count in header word 20."""
    per_record = 4 * (1 + len(params))
    assert len(expected) % per_record == 0
    data = bytearray(vc.case_file(len(vertices), base_vertex, params, constants, expected, mask, None, memory,
                                  descriptors, 1, 0, push))
    struct.pack_into("<I", data, 20 * 4, len(expected) // per_record)
    return bytes(data)


# --- draws -------------------------------------------------------------------------------------------------------------

def compile_shader(compiler, source, directory, name, model):
    hlsl, shader = directory / f"{name}.hlsl", directory / f"{name}.cso"
    hlsl.write_text(source, encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", model, "-E", "main", "-Fo", shader, hlsl], check=True)
    return shader


def run_sets(directory, compiler, renderer, backend, name, program, roles, es_body, gs_body, model_layout, sets, flaws):
    vs, gs, layout = lower(program, roles)
    assert sorted(t for t, _ in model_layout["exports"]) == sorted(t for t, _ in layout["outputs"]), layout["outputs"]
    vs_cso = compile_shader(compiler, vs, directory, f"{name}_vs", "vs_6_0")
    gs_cso = compile_shader(compiler, gs, directory, f"{name}_gs", "gs_6_0")
    case = directory / f"{name}.case"
    draw = [renderer, backend, "--check-geometry-case", vs_cso, gs_cso, case]
    separated = dict.fromkeys(map(frozenset, flaws), False)
    for constants, memory, vertices, base, *more in sets:
        extras = more[0] if more else {}
        descriptors, push = extras.get("descriptors"), extras.get("push", ())
        model = lambda flaw=(): GeometryModel(roles, constants, memory, flaw, descriptors, push)  # noqa: E731
        expected, mask = model().draw(es_body, gs_body, model_layout, vertices, base)
        write = lambda e, m: case.write_bytes(geometry_case(  # noqa: E731
            vertices, base, layout["params"], constants, e, m, memory.section(), descriptors, push))
        write(expected, mask)
        result = subprocess.run(draw, capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode == 77:
            return 77
        if result.returncode:
            sys.stderr.write(result.stderr)
            raise AssertionError(f"{name}: the draw differs from the reference ({len(vertices)} vertices)")
        for flaw in separated:
            wrong, wrong_mask = model(flaw).draw(es_body, gs_body, model_layout, vertices, base)
            if wrong == expected or len(wrong) != len(expected):
                if len(wrong) != len(expected):
                    separated[flaw] = True  # a different record count: the harness's count check fails first
                    write(wrong, wrong_mask)
                    result = subprocess.run(draw, capture_output=True, text=True)
                    if result.returncode != 1:
                        raise AssertionError(f"{name}: a wrong reference ({sorted(flaw)}) with another record count "
                                             f"escaped detection: {result.stderr}")
                continue
            separated[flaw] = True
            write(wrong, mask)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "vertex_mismatch" not in result.stderr:
                raise AssertionError(f"{name}: a wrong reference ({sorted(flaw)}) escaped detection: {result.stderr}")
    missing = [sorted(f) for f, seen in separated.items() if not seen]
    assert not missing, f"{name}: these wrong references never differ from the right one: {missing}"
    return 0


def es_sets(seed, counts):
    """Constants (scale and offset per channel in words 0..7, the GS factors in words 8..9), V#s in descriptor words
    0..7: positions at a base above 4 GiB, the raw words from a V# whose base crosses it and whose memory holds NaN
    payloads, infinities, signed zero and subnormals (they only pass through)."""
    memory = vc.Memory([(vc.LOW_BASE, vc.words_bytes(vc.SPECIALS * 8)),
                        (vc.HIGH_BASE, vc.words_bytes(vc.float_words(seed, 0x100)))])
    out = []
    for j, (count, base) in enumerate(counts):
        descriptors = [0] * 64
        descriptors[0:4] = vc.vsharp(vc.HIGH_BASE + 0x40, 16, 64, 0)
        descriptors[4:8] = vc.vsharp(vc.LOW_BASE + 0x1c0, 12, 64, 1)
        out.append((vc.float_words(seed + 10 + j, 64), memory, list(range(count)), base, {"descriptors": descriptors}))
    return out


def body_of(program, start, stop):
    return program[program.index(start) + 1:program.index(stop)]


def corpus_sets():
    memory = vc.memory_for(51)
    sets = []
    for j, (count, base) in enumerate([(9, 0), (6, 7)]):
        descriptors = [0] * 64
        descriptors[0:4] = vc.vsharp(vc.HIGH_BASE + 0x80, 12, 64, 0)
        sets.append((vc.float_words(60 + j, 64), memory, list(range(count)), base,
                     {"descriptors": descriptors, "push": vc.float_words(70 + j, 12)}))
    return sets


def families():
    """name -> (program, roles, ES body, GS body, model layout, sets, wrong references)."""
    program, roles = corpus_program()
    return {
        # The committed corpus program (position pass-through), with push constants and a constant buffer.
        "corpus": (program, roles, body_of(program, "BB1:", "BB6:"), body_of(program, "BB7:", "s_cbranch_scc0 BB21"),
                   CORPUS_LAYOUT, corpus_sets(), [{"input_swap"}, {"es_word_shift"}, {"base_ignored"}, {"fused"}]),
        # A strip of four with an odd second triangle, a cleared fifth slot, GS arithmetic and constants.
        "explode": (EXPLODE, ROLES, ES_A, GS_EXPLODE, EXPLODE_LAYOUT, es_sets(31, [(6, 0), (9, 5)]),
                    [{"d3d_strip"}, {"input_swap"}, {"es_word_shift"}, {"base_ignored"}, {"dead_kept"}]),
        # Two strips separated by a cut, permuted inputs, raw words through param0, partial lgkmcnt waits.
        "strips": (STRIPS, ROLES, ES_A, GS_STRIPS, STRIPS_LAYOUT, es_sets(41, [(6, 0), (12, 3)]),
                   [{"flags_as_one_strip"}, {"input_swap"}, {"es_word_shift"}, {"base_ignored"}]),
    }


def draw_family(name):
    def draw(directory, compiler, renderer, backend):
        program, roles, es_body, gs_body, layout, sets, flaws = families()[name]
        return run_sets(directory, compiler, renderer, backend, name, program, roles, es_body, gs_body, layout, sets,
                        flaws)
    return draw


DRAW_FAMILIES = {name: draw_family(name) for name in ("corpus", "explode", "strips")}


# --- controls ----------------------------------------------------------------------------------------------------------

def replace(program, old, new, count=1):
    text = "\n".join(program)
    assert old in text, old
    return text.replace(old, new, count).split("\n")


def check_translation_shape():
    for name, program, layout in (("explode", EXPLODE, EXPLODE_LAYOUT), ("strips", STRIPS, STRIPS_LAYOUT)):
        vs, gs, out = lower(program, ROLES)
        assert out["max_vertices"] == layout["max"], out
        assert [t for t, _ in out["outputs"]] == [t for t, _ in layout["exports"]], out
        assert "TriangleStream<GsOutput>" in gs and "triangle EsOutput input[3]" in gs
        assert "struct EsOutput" in vs and "SV_VertexID" in vs
        assert gs.count("stream.RestartStrip();") == len(out["primitives"])
    _, _, out = lower(EXPLODE, ROLES)
    assert out["primitives"] == [(0, 1, 2), (1, 3, 2)], out["primitives"]
    _, _, out = lower(STRIPS, ROLES)
    assert out["primitives"] == [(0, 1, 2), (3, 4, 5)], out["primitives"]
    program, roles = corpus_program()
    _, gs, out = lower(program, roles)
    assert out["primitives"] == [(0, 1, 2)] and out["es_words"] == 4, out
    # The remaining corpus programs: the report's counts (3 of the 6 ES+GS programs translate).
    rows = [stage_corpus_report.translate(path) for path in sorted(CORPUS.parent.glob("*.s"))]
    translated = [row for row in rows if row[3] == "translated"]
    assert len(rows) == 22 and len(translated) == 3, [(r[0], r[3], r[5]) for r in rows]


def check_refusals():
    p, r = EXPLODE, ROLES
    gs_first = GS_EXPLODE[0]
    refusals = [
        # The frame, instruction by instruction and register by register.
        (replace(p, "s_pack_ll_b32_b16 s0, 0, s3", "s_pack_ll_b32_b16 s0, 0, s2"), r, "NGG GS frame (the ES"),
        (replace(p, "v_add_nc_u32_e32 v5, -2, v5", "v_add_nc_u32_e32 v5, -1, v5"), r, "NGG GS frame (the epilogue)"),
        (replace(p, "ds_add_u32 v2, v0 gds", "s_nop 0"), r, "the pipeline-statistics block"),
        (replace(p, "s_bcnt1_i32_b64 s1, vcc", "s_bcnt1_i32_b64 s0, vcc"), r, "NGG GS frame (the epilogue)"),
        (replace(replace(p, "s_mov_b64 s[0:1], exec\ns_cbranch_execz BB63", "s_mov_b64 s[6:7], exec\n"
                         "s_cbranch_execz BB63"), "s_mov_b64 exec, s[0:1]\ns_cbranch_execz BB75",
                 "s_mov_b64 exec, s[6:7]\ns_cbranch_execz BB75"), r, "overlap"),
        (replace(p, f"v_mad_u32_u24 v3, {EXPLODE_STRIDE * EXPLODE_MAX}, v3, {LDS}",
                 f"v_mad_u32_u24 v3, {EXPLODE_STRIDE * 4}, v3, {LDS}"), r, "is even"),
        (EXPLODE, {k: v for k, v in r.items() if k != 24}, "ngg_lds_layout"),
        (EXPLODE, {k: v for k, v in r.items() if k != 25}, "ngg_query_state"),
        # Frame values and entry registers in the bodies.
        (replace(p, "v_mul_f32_e32 v64, s13, v56", "v_mul_f32_e32 v64, s13, v2"), r, "reads the frame value"),
        (replace(p, "v_mul_f32_e32 v64, s13, v56", "v_mul_f32_e32 v64, s13, v3"), r, "reads the frame value"),
        (replace(p, gs_first, "v_mov_b32_e32 v44, v2\n" + gs_first), r, "primitive id"),
        (replace(p, gs_first, "v_and_b32_e32 v44, 31, v3\n" + gs_first), r, "invocation id"),
        (replace(p, gs_first, "v_mov_b32_e32 v44, v5\n" + gs_first), r, "this lane's ES input"),
        (replace(p, "s_movk_i32 s11, 0x8000\ns_load_dwordx4 s[4:7], s[10:11], null\n" + QUERY_IDIOM[0],
                 "s_load_dwordx4 s[4:7], s[10:11], null\n" + QUERY_IDIOM[0]), r, "which the ES half writes"),
        (replace(p, "v_add_nc_u32_e32 v5, s0, v5", "v_add_nc_u32_e32 v5, s0, v5\nv_mov_b32_e32 v1, v5"), r,
         "The ES half writes v1"),
        (replace(p, "v_add_nc_u32_e32 v5, s0, v5", "v_add_nc_u32_e32 v5, s0, v5\nv_mov_b32_e32 v6, v0"), r,
         "is a GS input"),
        (replace(p, "s_movk_i32 s11, 0x8000\ns_load_dwordx4 s[20:23]",
                 f"s_movk_i32 s11, 0x8000\ns_mov_b32 {LDS}, 0\ns_load_dwordx4 s[20:23]"), r, "ngg_lds_layout SGPR"),
        (replace(p, QUERY_IDIOM[2], QUERY_IDIOM[2] + "\ns_mov_b32 s40, 1\ns_and_b32 s40, s40, 1"), r, "between the query-bit test"),
        # Exports, LDS patterns, waits and flags.
        (replace(p, "exp param1 v8, v9, off, off", "exp param1 v8, v9, off, off\nexp pos1 v8, off, off, off"), r,
         "pos1..3"),
        (replace(p, "v_mul_f32_e32 v64, s13, v56", "v_mul_f32_e32 v64, s13, v56\nds_read_b32 v65, v3"), r,
         "reads only its input vertices"),
        (replace(p, "ds_write_b8 v3, v41 offset:84", "ds_write_b8 v3, v41 offset:84\nds_write_b32 v3, v20 offset:60"),
         r, "written twice"),
        (replace(p, "ds_read_b32 v24, v2 offset:16", "ds_read_b32 v24, v2 offset:24"), r,
         "which the ES half does not write"),
        (replace(p, "ds_write_b8 v3, v41 offset:84", "ds_write_b8 v3, v20 offset:84"), r, "not a constant"),
        (replace(p, "v_mov_b32_e32 v42, 7", "v_mov_b32_e32 v42, 6"), r, "odd without completing"),
        (replace(p, "v_mov_b32_e32 v41, 5", "v_mov_b32_e32 v41, 1"), r, "only live vertices"),
        (replace(p, "v_mul_f32_e32 v64, s13, v56", "v_mul_f32_e32 v64, s13, v56\nv_mbcnt_lo_u32_b32 v65, -1, 0"), r,
         "lane-cooperative"),
        (replace(p, "v_mul_f32_e32 v64, s13, v56", "v_mul_f32_e32 v64, s13, v56\nds_swizzle_b32 v65, v64"), r,
         "an LDS access that is not"),
        (replace(p, gs_first, "s_cbranch_vccz BB7\n" + gs_first), r, "control flow"),
        (replace(p, "s_waitcnt lgkmcnt(0)\ns_buffer_load_dwordx2", "s_waitcnt lgkmcnt(1)\ns_buffer_load_dwordx2"), r,
         "scalar load outstanding"),
        (replace(STRIPS, "s_waitcnt lgkmcnt(3)", "s_waitcnt lgkmcnt(6)"), r, "load completion"),
        (replace(p, "v_mad_u32_u16 v1, 28, v1, 0", "v_mad_u32_u16 v1, 28, v1, 0 op_sel:[0,1,0,0]"), r, "adjacency"),
        (replace(p, "v_mad_u32_u16 v1, 28, v1, 0", "v_mad_u32_u16 v1, 24, v1, 0"), r, "two LDS strides"),
    ]
    for program, roles, reason in refusals:
        must_refuse(program, roles, reason)
    return len(refusals)


def check_reference():
    """Every family's model runs on its sets, and every wrong reference changes at least one dword of some set (the
    draws check again that the renderer reports each one)."""
    for name, (program, roles, es_body, gs_body, layout, sets, flaws) in families().items():
        seen = dict.fromkeys(map(frozenset, flaws), False)
        for constants, memory, vertices, base, extras in sets:
            make = lambda flaw=(): GeometryModel(roles, constants, memory, flaw, extras.get("descriptors"),  # noqa
                                                 extras.get("push", ()))
            expected, mask = make().draw(es_body, gs_body, layout, vertices, base)
            assert expected and any(mask)
            for flaw in seen:
                if make(flaw).draw(es_body, gs_body, layout, vertices, base) != (expected, mask):
                    seen[flaw] = True
        assert all(seen.values()), (name, [sorted(f) for f, ok in seen.items() if not ok])


def check_controls():
    check_translation_shape()
    refused = check_refusals()
    check_reference()
    print(f"geometry_aot controls ok: {refused} refusals")


def llvm_disassemble(assembler, code):
    text = " ".join(f"0x{b:02x}" for b in code)
    result = subprocess.run([assembler, "--disassemble", "--show-encoding", "-triple=amdgcn--amdpal", "-mcpu=gfx1013",
                             "-mattr=+wavefrontsize64"], input=text, capture_output=True, text=True, check=True)
    out, offset = [], 0
    for line in result.stdout.splitlines():
        if not (m := re.fullmatch(r"\s*(.*?)\s*(?://|;)\s*encoding:\s*\[(.*)\]\s*", line)):
            continue
        out.append((offset, " ".join(m[1].split())))
        offset += len(m[2].split(","))
    assert offset == len(code), (offset, len(code))
    return out


def check_binary(directory, assembler, objcopy):
    """Assemble each program (wave64, as RADV compiles an NGG GS), disassemble it with llvm-mc, name its branch
    targets as a native program's would be, and lower it: both HLSL sources must be the same."""
    import pixel_aot
    programs = [(EXPLODE, ROLES), (STRIPS, ROLES), corpus_program()]
    for index, (program, roles) in enumerate(programs):
        source, obj, binary = directory / "g.s", directory / "g.o", directory / "g.bin"
        text = [line.split(";")[0].strip() for line in program]
        source.write_text("\n".join(line for line in text if line) + "\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-mattr=+wavefrontsize64",
                        "-filetype=obj", source, "-o", obj], check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
        code = binary.read_bytes()
        decoded = pixel_aot.name_branch_targets(llvm_disassemble(assembler, code), len(code))
        assert lower(decoded, roles)[:2] == lower(program, roles)[:2], index
    print(f"geometry_aot binary ok: {len(programs)} programs")


def check_render(directory, compiler, renderer, backend, families):
    for name in families or DRAW_FAMILIES:
        try:
            code = DRAW_FAMILIES[name](directory, compiler, renderer, backend)
        except subprocess.CalledProcessError as error:
            if error.returncode != 77:
                raise
            return 77
        if code:
            return code
    return 0


def main():
    mode, *args = sys.argv[1:]
    if mode == "--list-families":
        print("\n".join(DRAW_FAMILIES))
        return 0
    families = []
    while "--family" in args:
        at = args.index("--family")
        families.append(args[at + 1])
        del args[at:at + 2]
    unknown = [name for name in families if name not in DRAW_FAMILIES]
    if unknown or (families and mode != "draw"):
        raise ValueError(f"Unknown or misplaced --family {unknown}; known families: {', '.join(DRAW_FAMILIES)}")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        if mode == "controls":
            check_controls()
        elif mode == "binary":
            check_controls()
            check_binary(directory, *args)
        elif mode == "draw":
            if not families:
                check_controls()
            return check_render(directory, *args, families)
        else:
            raise ValueError("Expected controls, binary or draw mode")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        write_record(os.environ.get("FORM_COVERAGE_RECORD"))
