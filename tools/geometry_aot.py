"""Offline lowering of a gfx1013 NGG geometry shader (ES+GS merged wave) to a D3D12 vertex and geometry shader pair
(card G-1, docs/design/stages.md).

On gfx10 with NGG, RADV runs the API vertex shader (the ES half) and the API geometry shader (the GS half) as one
hardware wave. The ES half writes each vertex's outputs to LDS at lane * es_stride; after s_barrier, the GS half reads
the three input vertices through the 16-bit vertex indices in v0 and v1, writes every emitted vertex to its LDS slot
(gs_lane_stride per GS invocation, vertex_stride per vertex) with a per-vertex primitive flag byte, and a fixed
epilogue counts the emitted primitives across the subgroup, allocates them (GS_ALLOC_REQ), exports each primitive from
its flags and each vertex from LDS. Mesa's ac_nir_lower_ngg_gs.c (MIT) builds that frame; this module recognizes it.

The translation splits the wave back into the two API stages:
- the ES half becomes an HLSL vertex shader whose output struct EsOutput holds the ES LDS words (TEXCOORDn, uint4);
- the GS half becomes an HLSL geometry shader reading `triangle EsOutput input[3]`: an LDS read of input vertex k at
  byte B is input[k] word B / 4, an LDS write to emitted vertex k is the output word of that vertex, and each
  primitive the flags complete is appended as its own strip, in the vertex order RADV's primitive export gives it
  (k-2, k-1+odd, k-odd: provoking vertex first). Each output word reaches the D3D12 output named by the export the
  epilogue makes from it (pos0 to SV_Position, paramN to TEXCOORDN, in tools/vertex_aot.py's order).
The epilogue, the pipeline-statistics GDS block and the frame's barriers and allocation are dropped: the desktop
input assembler, geometry stage and rasterizer do that work. The ALU, scalar-memory and buffer forms are the pixel
stage's (tools/pixel_aot_ops), through tools/vertex_aot.py's per-line loop and user-SGPR role map.

Only what is proved is accepted. Refused, each with its own reason: a frame that differs from RADV's (instruction by
instruction, registers renamed consistently), an even max_vertices (RADV swizzles the vertex slots), line or point
output, provoking-vertex-last order, culling, pos1..3 exports, the primitive id (v2), the invocation id (v3, GS
instancing), vertex offsets 3..5 (adjacency), a GS read of an SGPR the ES half writes, a GS read of an ES word the ES
half does not write, a primitive flag that is not a constant, control flow inside either body, and any LDS access
that is not one of the three I/O patterns above.

Usage:
    python tools/geometry_aot.py PROGRAM.s --user-sgprs MAP.json --vs-output VS.hlsl --gs-output GS.hlsl
                                 [--layout OUT.json]
MAP.json is tools/vertex_aot.py's role map, plus {"role": "ngg_lds_layout"} and {"role": "ngg_query_state"} for the
two NGG user SGPRs the frame reads (RADV's AC_UD_NGG_LDS_LAYOUT and AC_UD_NGG_STATE).
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pixel_aot_ops.dispatch import dispatch  # noqa: E402,F401  (registers the forms)
from pixel_aot_ops.hlsl import HELPERS, PREAMBLE  # noqa: E402
from pixel_aot_ops.lowering import Lowering  # noqa: E402
from pixel_aot_ops.forms.vop3p import place_fma_mix  # noqa: E402
from pixel_aot_ops.registers import vector_u32  # noqa: E402
import vertex_aot  # noqa: E402

M32 = 0xffffffff
GS_ROLES = ("ngg_lds_layout", "ngg_query_state")
MAX_PARAMS = vertex_aot.MAX_PARAMS
# The LDS bytes before the first GS output vertex: RADV's lds_scratch_size, the per-wave counts the epilogue writes at
# the layout base (ac_nir_lower_ngg_gs.c ngg_gs_out_vertex_addr adds it to every vertex address).
SCRATCH_BYTES = 4

ES_REASONS = {
    **{f"v{n}": f"entry VGPR v{n} of an ES+GS wave is a GS input (vertex offsets, primitive id, invocation id); the ES "
                "half may not read it" for n in range(5)},
    **{f"v{n}": f"entry VGPR v{n} of an NGG vertex shader has no role in the vertex contract (v5 is the vertex id, "
                "v8 the instance id)" for n in (6, 7)},
}
GS_REASONS = {
    "v0": "v0 (GS vertex offsets 0 and 1) is read only by the LDS address idiom v_mad_u32_u16 vA, stride, v0, 0",
    "v1": "v1 (GS vertex offsets 2 and 3) is read only by the LDS address idiom v_mad_u32_u16 vA, stride, v1, 0",
    "v2": "the GS primitive id (v2) is not lowered yet (SV_PrimitiveID needs its own draw check)",
    "v3": "the GS invocation id (v3) needs the GS instance count from pipeline state (GS instancing is not lowered)",
    "v4": "v4 (GS vertex offsets 4 and 5) is adjacency input, which is not lowered",
    **{f"v{n}": f"v{n} holds this lane's ES input (vertex or instance id), not the GS primitive's; the GS half may "
                "not read it" for n in range(5, 9)},
}

# --- templates ---------------------------------------------------------------------------------------------------------
# A template line is matched in full. %name is a register (bound once, consistently, and to no other name's register),
# $name a number, @name a branch label. Everything else is literal. The text is RADV 25.2.8's output for gfx1013
# (ACO), with the registers of the corpus program vksamples__shader_object__material_pass_through.geom.

ES_HEAD = ["s_pack_ll_b32_b16 %c0, 0, s3", "s_bfe_u64 exec, -1, %c0", "s_cbranch_execz @es_end"]
GS_HEAD = ["@es_end:", "s_waitcnt lgkmcnt(0)", "s_barrier", "s_lshl_b32 %c0, s3, 8", "s_pack_ll_b32_b16 %L, %L, 0",
           "s_bfe_u64 %m, -1, %c0", "s_mov_b64 exec, %m", "s_cbranch_execz @gs_end"]
# Pipeline statistics (ac_nir_lower_ngg_gs.c, GS primitive counting under a shader query): with the query bit set, the
# first active lane adds the wave's GS invocation count to two GDS counters.
GDS_BLOCK = [
    "s_and_b64 %g0, -1, exec", "s_bcnt1_i32_b64 %g1, %g0", "s_ff1_i32_b64 %g2, exec", "s_lshl_b64 %g3, 1, %g2",
    "s_and_b64 %qm, %qm, %g3", "s_waitcnt_depctr 0xffe3", "s_and_saveexec_b64 %qm, %qm", "s_cbranch_execz @gs_end",
    "s_movk_i32 m0, 0x100", "v_mov_b32_e32 %d0, %g1", "v_mov_b32_e32 %d1, 0", "ds_add_u32 %d1, %d0 gds",
    "v_mov_b32_e32 %d2, 4", "ds_add_u32 %d2, %d0 gds",
]
# The epilogue up to the vertex reads (%t lane in the subgroup, %a vertex address, %f primitive flag, %z the exported
# primitive index, %e the vertex-export mask), the reads themselves are parsed, then EPILOGUE_TAIL.
EPILOGUE_HEAD = [
    "@gs_end:", "s_waitcnt expcnt(0)", "s_waitcnt_depctr 0xffe3", "s_mov_b64 exec, -1", "s_waitcnt lgkmcnt(0)",
    "s_barrier", "s_bfe_u32 %w, s3, 0x40018", "s_lshl_b32 %c, %w, 6", "s_bfe_u32 s2, s2, 0x9000c",
    "v_mbcnt_lo_u32_b32 %t, -1, %c", "v_mbcnt_hi_u32_b32 %t, -1, %t", "v_mad_u32_u24 %a, $S, %t, %L",
    "s_waitcnt_depctr 0xfffe", "v_cmpx_gt_i32_e32 s2, %t", "s_cbranch_execz @b25", "ds_read_u8 %f, %a offset:$F",
    "@b25:", "s_waitcnt_depctr 0xffe3", "s_andn2_b64 exec, -1, exec", "v_mov_b32_e32 %f, 0", "s_mov_b64 exec, -1",
    "s_waitcnt lgkmcnt(0)", "v_cmp_ne_i32_e32 vcc, 0, %f", "s_mov_b64 exec, 1", "s_bcnt1_i32_b64 %c, vcc",
    "s_add_u32 %p, %L, %w", "v_mov_b32_e32 %x, %c", "v_mov_b32_e32 %y, %p", "ds_write_b8 %y, %x",
    "s_waitcnt lgkmcnt(0)", "s_barrier", "v_mov_b32_e32 %z, %L", "ds_read_b32 %z, %z", "s_waitcnt_depctr 0xffe3",
    "s_mov_b64 exec, -1", "v_mbcnt_lo_u32_b32 %y, -1, 0", "v_mbcnt_hi_u32_b32 %y, -1, %y",
    "v_mad_i32_i24 %x, %y, -8, 24", "s_waitcnt lgkmcnt(0)", "v_permlane16_b32 %z, %z, 0, 0",
    "v_lshlrev_b32_e32 %x, %x, %z", "v_msad_u8 %x, 0, %x, 0", "v_readlane_b32 %p, %x, %w", "s_sub_i32 %p, %p, %c",
    "s_lshr_b32 s3, s3, 28", "v_mbcnt_lo_u32_b32 %z, vcc_lo, %p", "s_add_u32 s3, s3, -1", "v_readlane_b32 s3, %x, s3",
    "v_mbcnt_hi_u32_b32 %z, vcc_hi, %z", "s_cmp_lg_i32 s3, 0", "s_mul_i32 s2, s2, src_scc", "s_cmp_eq_i32 %w, 0",
    "s_cbranch_scc0 @b45", "s_cmp_eq_i32 s2, 0", "s_cbranch_scc0 @b42", "s_movk_i32 m0, 0x1001",
    "s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)", "v_cmpx_eq_i32_e32 0, %y", "s_cbranch_execz @b45", "v_mov_b32_e32 %y, 0",
    "v_mov_b32_e32 %x, -1", "exp prim %y, off, off, off done", "exp pos0 %x, %x, %x, %x done", "s_branch @b45",
    "@b42:", "s_lshl_b32 %w, s2, 12", "s_or_b32 m0, %w, s3", "s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)",
    "@b45:", "s_waitcnt expcnt(0)", "s_mov_b64 exec, vcc", "s_cbranch_execz @b51", "v_mul_lo_u32 %y, $S, %z",
    "v_mov_b32_sdwa %x, %t dst_sel:BYTE_0 dst_unused:UNUSED_PRESERVE src0_sel:BYTE_0", "v_add_nc_u32_e32 %y, %L, %y",
    "ds_write_b8 %y, %x offset:$F1",
    "@b51:", "s_waitcnt_depctr 0xffe3", "s_mov_b64 exec, -1", "s_waitcnt lgkmcnt(0)", "s_barrier",
    "v_cmpx_gt_i32_e32 s2, %t", "s_mov_b64 vcc, exec",
    # The primitive export argument of a triangle with the provoking vertex first (ac_nir_lower_ngg_gs.c
    # ngg_gs_process_out_primitive): indices k-2, k-1+odd, k-odd in 10-bit fields, the null bit from the flag.
    "v_bfe_u32 %y, %f, 1, 1", "v_not_b32_e32 %f, %f", "v_sub_nc_u32_e32 %x, %z, %y", "v_add_lshl_u32 %y, %z, %y, 10",
    "v_add_nc_u32_e32 %z, -2, %z", "v_lshlrev_b32_e32 %x, 20, %x", "v_add_nc_u32_e32 %y, 0xfffffc00, %y",
    "v_or3_b32 %x, %x, %z, %y", "v_lshl_or_b32 %f, %f, 31, %x",
    "s_mov_b64 exec, -1", "s_waitcnt_depctr 0xfffe", "v_cmpx_gt_i32_e32 s3, %t", "s_mov_b64 %e, exec",
    "s_cbranch_execz @b63", "ds_read_u8 %a, %a offset:$F1", "s_waitcnt lgkmcnt(0)", "v_mad_u32_u24 %a, $S, %a, %L",
]
EPILOGUE_TAIL_HEAD = ["@b63:", "s_waitcnt_depctr 0xffe3", "s_mov_b64 exec, vcc", "s_cbranch_execz @b69",
                      "exp prim %f, off, off, off done", "@b69:", "s_waitcnt expcnt(0)", "s_mov_b64 exec, %e",
                      "s_cbranch_execz @b75", "s_waitcnt lgkmcnt(0)"]

# The registers the corpus program bound to each template name, block by block (ES head, GS head, statistics block,
# epilogue). A match must keep which names share a register (RADV reuses s0, s1 and s[0:1] across the epilogue): a
# renaming that merged or split two of them could change what the frame computes.
REFERENCE = [{"c0": "s0"}, {"c0": "s0", "L": "s23", "m": "s[0:1]"},
             {"g0": "s[4:5]", "g1": "s4", "g2": "s5", "g3": "s[6:7]", "qm": "s[0:1]", "d0": "v0", "d1": "v1", "d2": "v2"},
             {"w": "s0", "c": "s1", "t": "v0", "a": "v1", "L": "s23", "f": "v2", "p": "s4", "x": "v4", "y": "v3",
              "z": "v5", "e": "s[0:1]"}]


def _check_overlaps(blocks):
    for reference, block in zip(REFERENCE, blocks):
        actual = {n: v for (k, n), v in block.value.items() if k == "%"}
        names = sorted(reference)
        for j, u in enumerate(names):
            for v in names[j + 1:]:
                ref = bool(set(_registers(reference[u])) & set(_registers(reference[v])))
                act = bool(set(_registers(actual[u])) & set(_registers(actual[v])))
                if ref != act:
                    raise ValueError(f"NGG GS frame: registers {actual[u]} and {actual[v]} "
                                     f"{'do not ' if ref else ''}overlap where RADV's frame "
                                     f"{'reuses' if ref else 'keeps apart'} them")


_TOKEN = re.compile(r"([%$@])([A-Za-z_]\w*)")
_KINDS = {"%": r"(s\d+|s\[\d+:\d+\]|v\d+|v\[\d+:\d+\])", "$": r"(0x[0-9a-f]+|-?\d+)", "@": r"([A-Za-z_.$][\w.$]*)"}


def _compile(template):
    parts, names, at = [], [], 0
    for m in _TOKEN.finditer(template):
        parts.append(re.escape(template[at:m.start()]))
        parts.append(_KINDS[m[1]])
        names.append((m[1], m[2]))
        at = m.end()
    parts.append(re.escape(template[at:]))
    return re.compile("".join(parts)), names


class Binder:
    """Consistent bindings of template names: one value per name and one name per value, per kind."""

    def __init__(self):
        self.value = {}
        self.owner = {}

    def bind(self, kind, name, text):
        value = int(text, 0) if kind == "$" else text
        if (kind, name) in self.value:
            return self.value[(kind, name)] == value
        if kind != "$" and (kind, value) in self.owner:
            return False
        self.value[(kind, name)] = value
        if kind != "$":
            self.owner[(kind, value)] = name
        return True

    def get(self, kind, name):
        return self.value[(kind, name)]

    def scoped(self, *keep):
        """A binder for the next block: registers are reused across blocks, so only the names in keep carry over."""
        out = Binder()
        for name in keep:
            kind, name = name[0], name[1:]
            if (kind, name) in self.value:
                out.bind(kind, name, str(self.value[(kind, name)]))
        return out

    def match(self, template, line):
        regex, names = _compile(template)
        m = regex.fullmatch(line)
        if not m:
            return False
        trial = Binder()
        trial.value, trial.owner = dict(self.value), dict(self.owner)
        if not all(trial.bind(kind, name, m[k + 1]) for k, (kind, name) in enumerate(names)):
            return False
        self.value, self.owner = trial.value, trial.owner
        return True


class Cursor:
    def __init__(self, lines, binder):
        self.lines, self.pos, self.b = lines, 0, binder

    def peek(self):
        return self.lines[self.pos] if self.pos < len(self.lines) else "end of program"

    def take(self, templates, what):
        for template in templates:
            if not self.b.match(template, self.peek()):
                raise ValueError(f"NGG GS frame ({what}): expected {template!r}, found {self.peek()!r}")
            self.pos += 1


# --- operand model for the frame checks ------------------------------------------------------------------------------

def _registers(token):
    token = token.strip().split()[0] if token.strip() else ""
    if m := re.fullmatch(r"([sv])\[(\d+):(\d+)\]", token):
        return [f"{m[1]}{n}" for n in range(int(m[2]), int(m[3]) + 1)]
    if re.fullmatch(r"[sv]\d+", token):
        return [token]
    if m := re.fullmatch(r"\|?-?([sv]\d+)\|?", token.replace("abs(", "").replace(")", "")):
        return [m[1]]
    if token in ("vcc", "vcc_lo", "vcc_hi", "exec", "exec_lo", "exec_hi", "m0", "scc"):
        return [token]
    return []


NO_DESTINATION = re.compile(r"(?:ds_write\w*|ds_add\w*|buffer_store\w*|global_store\w*|s_store\w*|exp|s_cmp\w*"
                            r"|s_bitcmp\w*|v_cmp_\w*|v_cmpx_\w*|s_waitcnt\w*|s_cbranch\w*|s_branch|s_endpgm|s_nop"
                            r"|s_clause|s_setprio|s_barrier|s_sendmsg\w*|s_denorm_mode|s_round_mode)$")


def operands(line):
    """(written registers, read registers) of a line, as far as the frame checks need them."""
    head, _, rest = line.partition(" ")
    ops = [token.strip() for token in rest.split(",")] if rest else []
    written, read = [], []
    if NO_DESTINATION.match(head) or not ops:
        for token in ops:
            read += _registers(token)
        if head.startswith(("v_cmp_", "v_cmpx_")) and ops:
            read = [r for token in ops[1:] for r in _registers(token)]  # the first operand is vcc or an SGPR pair
        return written, read
    written = _registers(ops[0])
    for token in ops[1:]:
        read += _registers(token)
    if re.fullmatch(r"v_f?mac_\w+", head) or head.startswith(("s_cselect", "s_addc", "s_subb", "v_cndmask")):
        read += written if head.startswith("v_") else []
    return written, read


def _strip_labels(program):
    """Drop the labels no branch names (RADV labels every block, the LLVM route labels branch targets only)."""
    targets = {line.split()[-1] for line in program if re.match(r"s_(?:c?branch\w*)\b", line)}
    return [line for line in program if not (vertex_aot._is_label(line) and line[:-1] not in targets)]


# --- frame -----------------------------------------------------------------------------------------------------------

def split_frame(instructions):
    """Match RADV's NGG ES+GS frame. Returns (es_body, gs_body, frame): the two bodies with the frame removed and
    frame = {"lds": SGPR of the LDS layout, "query_mask": the s_cselect destination, "vertex_stride", "flag_offset",
    "reads": {VGPR: field byte}, "exports": [(target, [field byte or None] * 4, done)]}."""
    program = _strip_labels(vertex_aot._clean(instructions))
    b = Binder()
    c = Cursor(program, b)
    while c.peek().startswith("s_setprio"):
        c.pos += 1
    blocks = [b]
    c.take(ES_HEAD, "the ES region")
    end = b.get("@", "es_end") + ":"
    if end not in program[c.pos:]:
        raise ValueError("NGG GS frame: the ES region's branch names no later label")
    stop = program.index(end, c.pos)
    es_body = program[c.pos:stop]
    c.pos = stop
    c.b = b = b.scoped("@es_end")
    blocks.append(b)
    c.take(GS_HEAD, "the GS region")
    gs_end = b.get("@", "gs_end")
    branch = f"s_cbranch_scc0 {gs_end}"
    if branch not in program[c.pos:]:
        raise ValueError("NGG GS frame: no s_cbranch_scc0 to the epilogue (the pipeline-statistics test) after the "
                         "GS body; the frame differs from RADV's triangle-strip frame (line or point output, an even "
                         "max_vertices, or another compiler's frame)")
    stop = program.index(branch, c.pos)
    gs_body = program[c.pos:stop]
    c.pos = stop + 1
    lds = b.get("%", "L")
    c.b = b = b.scoped("@gs_end")
    blocks.append(b)
    c.take(GDS_BLOCK, "the pipeline-statistics block")
    query_mask = b.get("%", "qm")
    c.b = b = b.scoped("@gs_end", "%L")
    blocks.append(b)
    c.take(EPILOGUE_HEAD, "the epilogue")
    stride, flag = b.get("$", "S"), b.get("$", "F")
    if not b.match("$F1", str(flag + 1)):
        raise ValueError("NGG GS frame: the export-index byte is not the byte after the primitive flag")
    address = b.get("%", "a")
    reads = {}
    overwritten = False
    while not c.peek().endswith(":"):
        line = c.peek()
        m = re.fullmatch(r"ds_read(2)?_b(32|64|96|128) (v\d+|v\[\d+:\d+\]), (v\d+)"
                         r"(?: offset:(\d+)| offset0:(\d+) offset1:(\d+)| offset1:(\d+))?", line)
        if not m or m[4] != address or overwritten:
            raise ValueError(f"NGG GS frame: expected an LDS read of the exported vertex through {address}, found "
                             f"{line!r}")
        dest = _registers(m[3])
        if m[1]:
            if m[2] != "32":
                raise ValueError(f"NGG GS frame: unsupported vertex read {line!r}")
            first, second = int(m[6] or 0), int(m[7] or m[8] or 0)
            fields = [4 * first, 4 * second]
        else:
            start = int(m[5] or 0)
            fields = [start + 4 * j for j in range(int(m[2]) // 32)]
        if len(dest) != len(fields):
            raise ValueError(f"NGG GS frame: destination width of {line!r}")
        for register, field in zip(dest, fields):
            if field < SCRATCH_BYTES or field >= flag or field % 4:
                raise ValueError(f"NGG GS frame: vertex read at byte {field} is not an output word")
            reads[register] = field - SCRATCH_BYTES
        overwritten = address in dest
        c.pos += 1
    c.take(EPILOGUE_TAIL_HEAD, "the epilogue's exports")
    exports = []
    while c.peek().startswith("exp "):
        m = re.fullmatch(r"exp (pos\d+|param\d+) (\S+), (\S+), (\S+), (\S+?)((?: done| vm)*)", c.peek())
        if not m:
            raise ValueError(f"NGG GS frame: unsupported export {c.peek()!r}")
        fields = []
        for token in m.groups()[1:5]:
            if token == "off":
                fields.append(None)
            elif token in reads:
                fields.append(reads[token])
            else:
                raise ValueError(f"NGG GS frame: export source {token} is not a vertex word read from LDS")
        exports.append((m[1], fields, "done" in m[6].split()))
        c.pos += 1
    c.take(["@b75:", "s_endpgm"], "the end of the program")
    _check_overlaps(blocks)
    if c.pos != len(program):
        raise ValueError(f"NGG GS frame: instructions after s_endpgm: {c.peek()!r}")
    if stride % 4 or not SCRATCH_BYTES <= flag <= stride:
        raise ValueError(f"NGG GS frame: vertex stride {stride} and primitive-flag offset {flag} are not RADV's layout")
    return es_body, gs_body, {"lds": lds, "query_mask": query_mask, "vertex_stride": stride,
                              "flag_offset": flag, "exports": exports}


# --- body idioms -----------------------------------------------------------------------------------------------------

def _immediate(token):
    return int(token, 0) & M32 if re.fullmatch(r"-?\d+|0x[0-9a-f]+", token) else None


def _scan(body, half, frame, roles, es_written=frozenset()):
    """Remove the frame idioms from a body and tag the registers they produce. Returns (lines, io) where each io entry
    is (index in lines, kind, value) for an LDS access the lowering handles itself, and the info dict: es_stride,
    gs_lane_stride, constants (VGPR -> value of a v_mov_b32 of an immediate, at each line)."""
    tags = {}
    out, info = [], {"es_stride": None, "gs_lane_stride": None, "query": None}
    entry_live = {"v0", "v1"} if half == "gs" else set()
    scc = None  # "query" between s_bitcmp1 of the query bits and the end of the GS body
    written_here = set()
    lds = frame["lds"] if half == "gs" else None
    query = next((f"s{n}" for n, role in roles.items() if role == ("ngg_query_state",)), None)
    for line in body:
        head, _, rest = line.partition(" ")
        ops = [token.strip() for token in rest.split(",")] if rest else []
        written, read = operands(line)
        kind = None
        if head == "s_bfe_u32" and ops[1:] == ["s3", "0x40018"]:
            kind = ("wave_id", ops[0])
        elif head == "s_lshl_b32" and len(ops) == 3 and ops[2] == "6" and tags.get(ops[1]) == "wave_id":
            kind = ("wave_base", ops[0])
        elif head == "v_mbcnt_lo_u32_b32" and len(ops) == 3 and ops[1] == "-1" and tags.get(ops[2]) == "wave_base":
            kind = ("mbcnt_lo", ops[0])
        elif head == "v_mbcnt_hi_u32_b32" and len(ops) == 3 and ops[1] == "-1" and ops[2] == ops[0] \
                and tags.get(ops[2]) == "mbcnt_lo":
            kind = ("lane", ops[0])
        elif half == "es" and re.fullmatch(r"v_mul_u32_u24(?:_e32)?", head) and len(ops) == 3 \
                and tags.get(ops[2]) == "lane" and _immediate(ops[1]) is not None:
            if info["es_stride"] not in (None, _immediate(ops[1])):
                raise ValueError("The ES half computes two LDS strides")
            info["es_stride"] = _immediate(ops[1])
            kind = (("es_out",), ops[0])
        elif half == "gs" and head == "v_mad_u32_u24" and len(ops) == 4 and tags.get(ops[2]) == "lane" \
                and ops[3] == lds and _immediate(ops[1]) is not None:
            if info["gs_lane_stride"] not in (None, _immediate(ops[1])):
                raise ValueError("The GS half computes two output-vertex strides")
            info["gs_lane_stride"] = _immediate(ops[1])
            kind = (("gs_out",), ops[0])
        elif half == "gs" and head == "v_mad_u32_u16":
            m = re.fullmatch(r"v_mad_u32_u16 (v\d+), (\S+), (v[01]), 0( op_sel:\[0,1,0,0\])?", line)
            if not m or _immediate(m[2]) is None:
                raise ValueError(f"Refused {line!r}: not the LDS address idiom v_mad_u32_u16 vA, stride, v0|v1, 0 "
                                 "(adjacency input and other vertex-offset uses are not lowered)")
            vertex = {("v0", None): 0, ("v0", " op_sel:[0,1,0,0]"): 1, ("v1", None): 2}.get((m[3], m[4]))
            if vertex is None:
                raise ValueError(f"Refused {line!r}: vertex offset 3 is adjacency input, which is not lowered")
            if m[3] not in entry_live:
                raise ValueError(f"Refused {line!r}: {m[3]} no longer holds the GS vertex offsets")
            if info["es_stride"] not in (None, _immediate(m[2])):
                raise ValueError("The GS half reads its input vertices with two LDS strides")
            info["es_stride"] = _immediate(m[2])
            kind = (("es_in", vertex), m[1])
        elif half == "gs" and query and head == "s_bfe_u32" and ops == [query, query, "0x30006"]:
            kind = ("query_bits", ops[0])
        elif half == "gs" and head == "s_bitcmp1_b32" and len(ops) == 2 and ops[1] == "0" \
                and tags.get(ops[0]) == "query_bits":
            if scc is not None:
                raise ValueError("The query bit is tested twice")
            scc = "query"
            info["query"] = True
            continue
        elif half == "gs" and head == "s_cselect_b64" and ops[1:] == ["-1", "0"] and scc == "query" \
                and ops[0] == frame["query_mask"]:
            kind = ("query_mask", ops[0])
        if kind:
            # An idiom line reads only the frame values its pattern names (merged_wave_info, the wave base, the lane,
            # the vertex offsets, the LDS layout, the query bits).
            tag, register = kind
            for r in written:
                tags.pop(r, None)
                entry_live.discard(r)
            if scc == "query" and head.startswith("s_") and head != "s_cselect_b64":
                raise ValueError(f"Refused {line!r}: writes SCC between the query-bit test and the epilogue branch")
            tags[register] = tag
            continue
        # An ordinary line: it may read no frame value except an LDS address in the address operand of an LDS access.
        address = ops[0] if head.startswith("ds_write") else (ops[1].split()[0] if head.startswith("ds_read")
                                                             and len(ops) > 1 else None)
        for r in read:
            if r in tags and not (r == address and isinstance(tags[r], tuple)):
                raise ValueError(f"Refused {line!r}: reads the frame value in {r} ({tags[r]})")
            if r in ("s2", "s3", "m0"):
                raise ValueError(f"Refused {line!r}: reads the frame register {r} (gs_tg_info, merged_wave_info or "
                                 "m0)")
            if r in entry_live:
                raise ValueError(f"Refused {line!r}: {GS_REASONS[r]}")
            if half == "gs" and r == lds:
                raise ValueError(f"Refused {line!r}: reads the NGG LDS-layout SGPR {lds} as data")
            if half == "gs" and r == query:
                raise ValueError(f"Refused {line!r}: reads the NGG state SGPR {query} as data")
            if r in es_written and r not in written_here and r.startswith("s"):
                raise ValueError(f"Refused {line!r}: reads {r}, which the ES half writes (its value in the GS half "
                                 "depends on whether the ES half ran)")
        if scc == "query" and head.startswith("s_") and not re.match(
                r"s_(?:mov_b32|mov_b64|movk_i32|load_dword\w*|buffer_load_dword\w*|waitcnt\w*|nop|clause|setprio|"
                r"mul_i32|pack_\w+)$", head):
            raise ValueError(f"Refused {line!r}: may write or read SCC between the query-bit test and the epilogue "
                             "branch")
        if head.startswith("ds_") and (address is None or address not in tags or not isinstance(tags[address], tuple)):
            raise ValueError(f"Refused {line!r}: an LDS access that is not the ES output, GS input or GS output "
                             "pattern (NGG culling and other lane-cooperative LDS use are refused)")
        tag = tags[address] if head.startswith("ds_") else None
        for r in written:
            tags.pop(r, None)
            entry_live.discard(r)
            written_here.add(r)
        if tag is not None:
            # The address operand names the I/O pattern now, not a register the lowering tracks.
            line = re.sub(rf"(?<=[ ,]){re.escape(address)}(?=,|$| )", "lds", line, count=1) if head.startswith(
                "ds_write") else re.sub(rf", {re.escape(address)}(?=,|$| )", ", lds", line, count=1)
        out.append((line, tag))
    if half == "gs":
        if scc != "query":
            raise ValueError("The GS body does not test the query bit (s_bitcmp1_b32 of the NGG state's bit 6) for "
                             "the epilogue branch")
        if "query_mask" not in tags.values():
            raise ValueError("The GS body does not compute the pipeline-statistics mask the epilogue reads")
    return out, info


def _ds_access(line):
    """(kind "read" or "write", registers, byte offsets, byte width per register) of a DS line."""
    m = re.fullmatch(r"ds_(read|write)(2)?_(b8|b32|b64|b96|b128|u8)(?:_d16\w*)? (\S+)(?:, (\S+))?(?:, (\S+))?"
                     r"(?: offset:(\d+)| offset0:(\d+) offset1:(\d+)| offset0:(\d+)| offset1:(\d+))?", line)
    if not m:
        raise ValueError(f"Refused {line!r}: unsupported LDS form")
    op, two, width = m[1], m[2], m[3]
    if op == "read":
        data = [m[4]]
    else:
        data = [m[5]] + ([m[6]] if two else [])
    if width in ("b8", "u8"):
        if two or op == "read":
            raise ValueError(f"Refused {line!r}: a byte LDS read")
        return op, _registers(data[0]), [int(m[7] or 0)], 1
    if two:
        if width != "b32":
            raise ValueError(f"Refused {line!r}: ds_{op}2 other than b32")
        first = int(m[8] or m[10] or 0)
        second = int(m[9] or m[11] or 0)
        regs = _registers(data[0]) + (_registers(data[1]) if op == "write" else [])
        if len(regs) != 2:
            raise ValueError(f"Refused {line!r}: operand width")
        return op, regs, [4 * first, 4 * second], 4
    regs = _registers(data[0])
    if len(regs) != {"b32": 1, "b64": 2, "b96": 3, "b128": 4}[width]:
        raise ValueError(f"Refused {line!r}: operand width")
    start = int(m[7] or 0)
    return op, regs, [start + 4 * j for j in range(len(regs))], 4


# --- lowering --------------------------------------------------------------------------------------------------------

def _split_roles(user_sgprs):
    rest, frame_roles = {}, {}
    for number, role in (user_sgprs or {}).items():
        if role and role[0] in GS_ROLES:
            if len(role) != 1 or role[0] in frame_roles.values():
                raise ValueError(f"At most one {role[0]} user SGPR, with no parameters")
            frame_roles[number] = role[0]
        else:
            rest[number] = role
    return rest, frame_roles


def _state(entry_scalar, entry_vectors, has_constants):
    st = Lowering(dict(entry_scalar), dict(entry_vectors), [PREAMBLE], {}, (), 0 if has_constants else None, {})
    st.constant_limit = vertex_aot.CONSTANT_BYTES
    return st


class DsQueue:
    """LDS reads complete in issue order (RDNA 2 ISA, s_waitcnt: LGKM_CNT counts LDS in order, scalar memory out of
    order), so lgkmcnt(N) completes all but the newest N LDS reads when no scalar load is outstanding."""

    def __init__(self, st):
        self.st, self.reads = st, []

    def issue(self, registers):
        self.reads.append(list(registers))
        self.st.pending.update(registers)

    def wait(self, count):
        st = self.st
        ds = {r for group in self.reads for r in group}
        if count == 0:
            st.pending.clear()
            self.reads = []
            return
        if st.pending - ds:
            raise ValueError("lgkmcnt above 0 with a scalar load outstanding: the scalar load may complete in any order")
        keep = self.reads[len(self.reads) - count:] if count < len(self.reads) else self.reads
        for group in self.reads[:len(self.reads) - len(keep)]:
            st.pending.difference_update(group)
        self.reads = keep


def _wait(st, queue, i, line):
    """s_waitcnt with the vmcnt part to Lowering.vm_wait (as tools/vertex_aot.py does) and the lgkmcnt part to the
    LDS queue; True when the line was a combined s_waitcnt."""
    m = re.fullmatch(r"s_waitcnt((?: (?:vmcnt|expcnt|lgkmcnt)\(\d+\))+)", line)
    if not m:
        return False
    fields = re.findall(r"(\w+)\((\d+)\)", m[1])
    if len({name for name, _ in fields}) != len(fields):
        raise ValueError("Only wait counts without repeats are supported")
    for name, n in fields:
        if int(n) > (7 if name == "expcnt" else 63):
            raise ValueError(f"{name} count exceeds its gfx10 field")
        if name == "vmcnt":
            st.vm_wait(int(n))
        elif name == "lgkmcnt":
            queue.wait(int(n))
    return True


def _refuse_lines(lines):
    for line in lines:
        if line.startswith("ds_"):
            continue
        if vertex_aot._is_label(line):
            raise ValueError(f"Refused {line!r}: control flow inside an NGG GS body is not lowered")
        for pattern, reason in vertex_aot.REFUSALS:
            if re.fullmatch(pattern, line):
                raise ValueError(f"Refused {line!r}: {reason}")


def lower(instructions, user_sgprs, input_primitive="triangle"):
    """Returns (vertex HLSL, geometry HLSL, layout). layout: {"es_words": N, "es_stride", "vertex_stride",
    "max_vertices", "outputs": [(target, channels defined)], "params": [N, ...], "primitives": [(a, b, c), ...]
    (emitted vertex indices, in append order), "vertices": {k: {output word: True}}, "instance_id": bool}."""
    if input_primitive != "triangle":
        raise ValueError("Only triangle input is lowered (point, line and adjacency input are not)")
    es_body, gs_body, frame = split_frame(instructions)
    roles, frame_roles = _split_roles(user_sgprs)
    lds = frame["lds"]
    if int(lds[1:]) not in frame_roles or frame_roles[int(lds[1:])] != "ngg_lds_layout":
        raise ValueError(f"The frame reads the NGG LDS layout from {lds}; the role map must give it "
                         "{\"role\": \"ngg_lds_layout\"}")
    if "ngg_query_state" not in frame_roles.values():
        raise ValueError("The frame tests the NGG state SGPR's query bit; the role map must give that SGPR "
                         "{\"role\": \"ngg_query_state\"}")
    roles_all = {**roles, **{n: (r,) for n, r in frame_roles.items()}}
    entry_scalar, tables, root, has_constants = vertex_aot._role_map(roles, "ngg")

    es_lines, es_info = _scan(es_body, "es", frame, roles_all)
    es_written = {r for line, _ in es_lines for r in operands(line)[0] if r.startswith("s")}
    es_written |= {r for line in es_body for r in operands(line)[0] if r.startswith("s")}
    es_vector_written = {r for line in es_body for r in operands(line)[0] if r.startswith("v")}
    for register in ("v0", "v1"):
        if register in es_vector_written:
            raise ValueError(f"The ES half writes {register}, which holds the GS vertex offsets the GS half reads")
    for number, role in frame_roles.items():
        if f"s{number}" in es_written:
            raise ValueError(f"The ES half writes s{number}, the {role} SGPR the GS half's frame reads")
    gs_lines, gs_info = _scan(gs_body, "gs", frame, roles_all, es_written)
    es_stride, gs_stride = es_info["es_stride"], gs_info["es_stride"]
    if es_stride is None:
        raise ValueError("The ES half writes no LDS outputs")
    if gs_stride is not None and gs_stride != es_stride:
        raise ValueError(f"The GS half reads input vertices with stride {gs_stride}; the ES half writes them with "
                         f"{es_stride}")
    vertex_stride, flag_offset = frame["vertex_stride"], frame["flag_offset"]
    lane = gs_info["gs_lane_stride"]
    if lane is None:
        raise ValueError("The GS half emits no vertex")
    if lane % vertex_stride:
        raise ValueError(f"GS output stride {lane} is not a whole number of {vertex_stride}-byte vertices")
    max_vertices = lane // vertex_stride
    if not max_vertices % 2:
        raise ValueError(f"max_vertices {max_vertices} is even: RADV swizzles the output vertex slots "
                         "(ac_nir_lower_ngg_gs.c ngg_gs_out_vertex_addr), which is not matched")
    if es_stride % 4 or es_stride > 0xffff:
        raise ValueError(f"ES LDS stride {es_stride} is not a word multiple")
    _refuse_lines([line for line, _ in es_lines] + [line for line, _ in gs_lines])

    # The ES half: a vertex shader whose outputs are the ES LDS words.
    st = _state(entry_scalar, {reg: ("uint", name) for reg, name in vertex_aot.ENTRY_VGPRS["ngg"].items()},
                has_constants)
    queue = DsQueue(st)
    es_words = {}
    es_io = {i: tag for i, (_, tag) in enumerate(es_lines)}

    def es_special(i, line):
        if _wait(st, queue, i, line):
            return True
        if not line.startswith("ds_"):
            return False
        op, regs, offsets, width = _ds_access(line)
        if op != "write" or width != 4 or es_io[i] != ("es_out",):
            raise ValueError(f"Refused {line!r}: the ES half only writes its output words")
        for register, offset in zip(regs, offsets):
            if offset % 4 or offset + 4 > es_stride:
                raise ValueError(f"Refused {line!r}: ES output byte {offset} is outside the {es_stride}-byte item")
            if offset // 4 in es_words:
                raise ValueError(f"Refused {line!r}: ES output word {offset // 4} is written twice")
            name = f"esw{offset // 4}"
            st.lines.append(f"    uint {name} = {vector_u32(register, st.scalar, st.vector, st.pending, st.sample_pending)};")
            es_words[offset // 4] = name
        return True

    uses_instance = vertex_aot.run_body(st, [line for line, _ in es_lines], tables, "ngg", es_special,
                                        reasons=ES_REASONS)
    _check_state(st)
    es_count = max(es_words) + 1
    es_vectors = -(-es_count // 4)
    es_struct = ["struct EsOutput {", *(f"    uint4 es{j} : TEXCOORD{j};" for j in range(es_vectors)), "};"]
    inputs = "uint vid : SV_VertexID" + (", uint iid : SV_InstanceID" if uses_instance else "")
    uses_vsharps = any(len(entry) == 2 for _, entries in tables.values() for entry in entries.values())
    place_fma_mix(st)
    st.lines[st.lines.index(PREAMBLE)] = "\n".join([HELPERS, *es_struct, f"EsOutput main({inputs}) {{"])
    stores = ["    EsOutput es_out;"]
    for j in range(es_vectors):
        words = [es_words.get(4 * j + c, "0u") for c in range(4)]
        stores.append(f"    es_out.es{j} = uint4({', '.join(words)});")
    vs_source = "\n".join([*vertex_aot.declarations(st, root, has_constants, uses_vsharps), *st.lines, *stores,
                           "    return es_out;", "}", ""])

    # The GS half.
    g = _state(entry_scalar, {}, has_constants)
    gqueue = DsQueue(g)
    gs_io = {i: tag for i, (_, tag) in enumerate(gs_lines)}
    constants = {}
    vertices = {}  # emitted vertex -> {output byte: HLSL word}
    flags = {}
    counter = [0]

    def gs_special(i, line):
        if _wait(g, gqueue, i, line):
            return True
        head, _, rest = line.partition(" ")
        if head == "v_mov_b32_e32" or head == "v_mov_b32":
            ops = [t.strip() for t in rest.split(",")]
            value = _immediate(ops[1])
            constants[ops[0]] = value
            return False
        if not line.startswith("ds_"):
            for r in operands(line)[0]:
                constants.pop(r, None)
            return False
        op, regs, offsets, width = _ds_access(line)
        tag = gs_io[i]
        if op == "read":
            if tag[0] != "es_in":
                raise ValueError(f"Refused {line!r}: the GS half reads only its input vertices from LDS")
            names = []
            for register, offset in zip(regs, offsets):
                if offset % 4 or offset + 4 > es_stride:
                    raise ValueError(f"Refused {line!r}: input byte {offset} is outside the {es_stride}-byte ES item")
                word = offset // 4
                if word not in es_words:
                    raise ValueError(f"Refused {line!r}: reads ES word {word}, which the ES half does not write")
                name = f"gin{counter[0]}"
                counter[0] += 1
                g.lines.append(f"    uint {name} = input[{tag[1]}].es{word // 4}.{'xyzw'[word % 4]};")
                names.append((register, name))
            for register, name in names:
                g.vector[register] = ("uint", name)
                constants.pop(register, None)
            gqueue.issue([register for register, _ in names])
            return True
        if tag[0] != "gs_out":
            raise ValueError(f"Refused {line!r}: the GS half writes only its output vertices to LDS")
        for register, offset in zip(regs, offsets):
            if offset < SCRATCH_BYTES:
                raise ValueError(f"Refused {line!r}: writes the LDS scratch area")
            k, field = divmod(offset - SCRATCH_BYTES, vertex_stride)
            if k >= max_vertices:
                raise ValueError(f"Refused {line!r}: vertex {k} is past max_vertices {max_vertices}")
            if width == 1:
                if field != flag_offset - SCRATCH_BYTES:
                    raise ValueError(f"Refused {line!r}: a byte store that is not vertex {k}'s primitive flag")
                if register not in constants or constants[register] is None:
                    raise ValueError(f"Refused {line!r}: the primitive flag of vertex {k} is not a constant")
                if k in flags:
                    raise ValueError(f"Refused {line!r}: the primitive flag of vertex {k} is written twice")
                flags[k] = constants[register] & 0xff
                continue
            if field % 4 or field + 4 > flag_offset - SCRATCH_BYTES:
                raise ValueError(f"Refused {line!r}: byte {field} of vertex {k} is not an output word")
            slot = vertices.setdefault(k, {})
            if field in slot:
                raise ValueError(f"Refused {line!r}: output byte {field} of vertex {k} is written twice")
            name = f"gout{k}_{field // 4}"
            g.lines.append(f"    uint {name} = {vector_u32(register, g.scalar, g.vector, g.pending, g.sample_pending)};")
            slot[field] = name
        return True

    vertex_aot.run_body(g, [line for line, _ in gs_lines], tables, "ngg", gs_special, entry_vgprs={},
                        reasons=GS_REASONS)
    _check_state(g)
    primitives = _primitives(flags, vertices, max_vertices)
    outputs, params = _outputs(frame["exports"])
    gs_source = _assemble_gs(g, root, has_constants, uses_vsharps, es_struct, outputs, vertices, primitives)
    layout = {"es_words": es_count, "es_stride": es_stride, "vertex_stride": vertex_stride, "max_vertices": max_vertices,
              "outputs": [(target, [f is not None for f in fields]) for target, fields in outputs],
              "params": params, "primitives": primitives, "instance_id": uses_instance,
              "vertices": {k: sorted(v) for k, v in vertices.items()}}
    return vs_source, gs_source, layout


def _check_state(st):
    if st.ex != "true" or st.wqm or st.exported or st.flat_attrs or st.quad_position or st.samples:
        raise ValueError("A pixel-stage operation reached the geometry lowering")


def _primitives(flags, vertices, max_vertices):
    """The triangles the primitive flags complete (ac_nir_lower_ngg_gs.c: bit 0 completes a primitive, bit 1 odd,
    bit 2 live; no culling, so every emitted vertex is live), as RADV's provoking-vertex-first export orders them."""
    out = []
    for k in sorted(flags):
        flag = flags[k]
        if flag == 0:  # a slot the GS did not emit (ngg_gs_clear_primflags)
            if k in vertices:
                raise ValueError(f"Vertex {k} has outputs but a cleared primitive flag")
            continue
        if flag & ~7 or not flag & 4:
            raise ValueError(f"Primitive flag {flag:#x} of vertex {k}: only live vertices (bit 2) without culling "
                             "are lowered")
        if flag & 1:
            if k < 2 or any(flags.get(j, 0) == 0 for j in (k - 2, k - 1)):
                raise ValueError(f"Vertex {k} completes a triangle without two emitted vertices before it")
            odd = flag >> 1 & 1
            out.append((k - 2, k - 1 + odd, k - odd))
        elif flag & 2:
            raise ValueError(f"Primitive flag {flag:#x} of vertex {k}: odd without completing a primitive")
    emitted = [k for k in flags if flags[k]]
    if emitted != list(range(len(emitted))):
        raise ValueError("The emitted vertices are not 0..n-1")
    if not out:
        raise ValueError("The GS completes no primitive")
    if 3 * len(out) > 1024:
        raise ValueError("More than 1024 appended vertices")
    for k in vertices:
        if flags.get(k, 0) == 0:
            raise ValueError(f"Vertex {k} has outputs but no primitive flag")
    return out


def _outputs(exports):
    """[(target, [field byte or None] * 4)] in tools/vertex_aot.py's output order: TEXCOORD0, SV_Position, then
    TEXCOORD1..N. pos1..3 (layer, viewport, clip distances) need PA_CL_VS_OUT_CNTL state and are refused."""
    seen = {}
    for target, fields, done in exports:
        if target in seen:
            raise ValueError(f"The epilogue exports {target} twice")
        if target != "pos0" and target.startswith("pos"):
            raise ValueError(f"Refused export {target}: pos1..3 need PA_CL_VS_OUT_CNTL state, which the geometry "
                             "lowering does not take yet")
        if target.startswith("param") and int(target[5:]) >= MAX_PARAMS:
            raise ValueError(f"Refused export {target}: parameter index out of range")
        seen[target] = fields
    if "pos0" not in seen:
        raise ValueError("The epilogue does not export pos0")
    if [t for t, _, done in exports if done] != ["pos0"]:
        raise ValueError("pos0 must be the one export with done")
    params = sorted(int(t[5:]) for t in seen if t.startswith("param"))
    order = (["param0"] if 0 in params else []) + ["pos0"] + [f"param{n}" for n in params if n]
    return [(t, seen[t]) for t in order], params


def _assemble_gs(st, root, has_constants, uses_vsharps, es_struct, outputs, vertices, primitives):
    place_fma_mix(st)
    members = [f"    float4 {t} : {'SV_Position' if t == 'pos0' else 'TEXCOORD' + t[5:]};" for t, _ in outputs]
    header = [HELPERS, *es_struct, "struct GsOutput {", *members, "};",
              f"[maxvertexcount({3 * len(primitives)})]",
              "void main(triangle EsOutput input[3], inout TriangleStream<GsOutput> stream) {"]
    st.lines[st.lines.index(PREAMBLE)] = "\n".join(header)
    tail = ["    GsOutput gs_out;"]
    for j, triangle in enumerate(primitives):
        tail.append(f"    // triangle {j}: emitted vertices {triangle[0]}, {triangle[1]}, {triangle[2]}")
        for k in triangle:
            words = vertices.get(k, {})
            for target, fields in outputs:
                parts = ["0u" if f is None else words.get(f, "0u") for f in fields]
                tail.append(f"    gs_out.{target} = asfloat(uint4({', '.join(parts)}));")
            tail.append("    stream.Append(gs_out);")
        tail.append("    stream.RestartStrip();")
    return "\n".join([*vertex_aot.declarations(st, root, has_constants, uses_vsharps), *st.lines, *tail, "}", ""])


def parse_role_map(data):
    out = {}
    rest = {}
    for key, value in data.items():
        if isinstance(value, dict) and value.get("role") in GS_ROLES:
            if not re.fullmatch(r"\d+", key) or len(value) != 1:
                raise ValueError(f"Malformed user-SGPR map entry {key!r}")
            out[int(key)] = (value["role"],)
        else:
            rest[key] = value
    out.update(vertex_aot.parse_role_map(rest))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("program", type=Path)
    parser.add_argument("--user-sgprs", type=Path, required=True)
    parser.add_argument("--vs-output", type=Path, required=True)
    parser.add_argument("--gs-output", type=Path, required=True)
    parser.add_argument("--layout", type=Path)
    args = parser.parse_args()
    try:
        roles = parse_role_map(json.loads(args.user_sgprs.read_text(encoding="utf-8")))
        vs, gs, layout = lower(args.program.read_text(encoding="utf-8").splitlines(), roles)
    except ValueError as error:
        print(f"geometry_aot: {error}", file=sys.stderr)
        return 1
    args.vs_output.write_text(vs, encoding="ascii")
    args.gs_output.write_text(gs, encoding="ascii")
    summary = {k: layout[k] for k in ("es_words", "max_vertices", "params", "primitives", "instance_id")}
    if args.layout:
        args.layout.write_text(json.dumps(layout, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
