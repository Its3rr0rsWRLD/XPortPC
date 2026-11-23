"""Offline lowering for a straight-line gfx1013 vertex shader (cards V-1 to V-3, docs/design/vertex-stage.md).

This module holds the vertex-stage contract: the hardware stage (a legacy VS, or an NGG ESGS wave whose passthrough
frame is matched and dropped, card V-2), the entry registers (vertex and instance id, the user-SGPR role map), the
descriptor loads that read V#s through a user-SGPR pointer, the exports (pos0 to SV_Position, pos1 and pos2 to clip
or cull distances under PA_CL_VS_OUT_CNTL state, paramN to TEXCOORDN) and the end of the program. Every other
instruction is lowered by the form registry of tools/pixel_aot_ops (docs/design/module-layout.md), through the same
`dispatch` and the same `Lowering` state as the pixel stage: vertex fetch, offset-addressed and global loads are the
pixel stage's MUBUF and GLOBAL forms, and partial vmcnt waits are its Lowering.vm_wait. A form covered once is
therefore lowered the same way in both stages, which is what tools/form_coverage.py assumes when it counts a form.

Usage:
    python tools/vertex_aot.py PROGRAM.s --user-sgprs MAP.json --output OUT.hlsl [--layout OUT.json]
                               [--vs-out-cntl 0xVALUE]
    python tools/vertex_aot.py CODE.bin --llvm LIBLLVM --user-sgprs MAP.json --output OUT.hlsl

PROGRAM.s holds one instruction per line as llvm-mc 15 prints it (text after ';' and '#' lines are ignored; labels
name branch targets, which only the NGG frame may have). CODE.bin is the raw code of one program, disassembled with
the given LLVM library. MAP.json gives the role of each user SGPR, keyed by its number:
    {"2": {"role": "descriptors", "high": 4294934528, "entries": {"0": {"vsharp": 8}, "16": {"vsharp": 12}}},
     "3": {"role": "base_vertex"}, "4": {"role": "start_instance"},
     "5": {"role": "descriptors", "high": 4294934528, "entries": {"0": "constants"}},
     "6": {"role": "inline", "word": 0}}
A "vsharp" entry names the first of the four descriptor words (b4, `vsharp_words`, 64 words) that hold that V# at
draw time, as the pixel path's buffer_descriptors name constant words. The "constants" entry is the constant buffer
that s_buffer_load reads (b0, `params`: 64 words, or as many uint4 as the program reads, up to 4096). {"constants": N} is the same constant buffer whose V#
is also read as data (a uniform block that buffer_load indexes at run time): its V# words are descriptor words N..N+3,
and the runtime keeps b0 equal to the title memory that V# addresses. A scalar load through a 64-bit address held in
inline words (buffer device address) reads title memory. An
"inline" SGPR holds push-constant word `word` (0 to 31), passed as a root constant (b3, `push_words`); an inline V# is
four inline SGPRs. The base vertex and start instance are root constants (b2); the desktop draw uses 0 for both.
--vs-out-cntl is the PA_CL_VS_OUT_CNTL value of the draw; without it an export to pos1..3 is refused.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pixel_aot_ops.dispatch import dispatch  # noqa: E402
from pixel_aot_ops.hlsl import (HELPERS, MEMORY_HELPERS, PREAMBLE, SALU_HELPERS, TITLE_DECLARATIONS,  # noqa: E402
                                TITLE_LOOKUP)
from pixel_aot_ops.lowering import Lowering  # noqa: E402
from pixel_aot_ops.forms.vop3p import place_fma_mix  # noqa: E402
from pixel_aot_ops.registers import sgpr_name, sgpr_pair, vector_u32  # noqa: E402
from vertex_corpus_report import features  # noqa: E402

RADV_ADDRESS_HIGH = 0xffff8000
# Entry VGPRs per hardware stage (docs/design/vertex-stage.md, Inputs). Legacy VS: v0 vertex id, v3 instance id. NGG
# (the ES half of a merged ESGS wave): v5 vertex id, v8 instance id, v0 the primitive payload; v1..v4 carry the other
# GS inputs. Reading any other entry VGPR before writing it is refused with its own reason.
ENTRY_VGPRS = {"legacy": {"v0": "vid", "v3": "iid"}, "ngg": {"v5": "vid", "v8": "iid"}}
ENTRY_VGPR_REASONS = {
    "legacy": {f"v{n}": f"entry VGPR v{n} of a legacy VS has no role in the vertex contract (v0 is the vertex id, "
               "v3 the instance id)" for n in (1, 2)},
    "ngg": {**{f"v{n}": f"entry VGPR v{n} of an NGG vertex shader has no role in the vertex contract (v5 is the "
               "vertex id, v8 the instance id)" for n in (1, 2, 3, 4, 6, 7)},
            "v0": "entry VGPR v0 of an NGG vertex shader is the primitive payload, which the frame exports; the vertex "
                  "body may not read it"},
}
# On gfx10 an NGG wave gets s0..s7 from the hardware (s2 gs_tg_info, s3 merged_wave_info); user SGPRs start at s8.
NGG_FIRST_USER_SGPR = 8
MAX_PARAMS = 32
# A constant buffer view is at most 4096 uint4 (D3D12); a scalar buffer load past that is refused.
CONSTANT_BYTES = 4096 * 16
PUSH_WORDS = 32

REFUSALS = (
    # Each: a pattern for the whole line, and the reason. Checked on the vertex body (the NGG frame removed) before
    # any lowering.
    (r"(?:s_branch|s_cbranch_\w+|s_setpc_b64|s_swappc_b64|s_call_b64|s_subvector_loop_\w+)\b.*",
     "control flow in the vertex stage is lowered in card V-5 (CF-1 and CF-2 in the vertex stage)"),
    (r"s_getpc_b64\b.*", "embedded constants (s_getpc_b64) are lowered in card V-5"),
    (r"(?:s_sendmsg|s_sendmsghalt|s_barrier)\b.*|exp prim\b.*",
     "an NGG frame operation (s_sendmsg, s_barrier, exp prim) outside the NGG passthrough frame"),
    (r"(?:ds_\w+|v_mbcnt\w*|s_bcnt\w*|v_readlane\w*|v_readfirstlane\w*|v_writelane\w*|v_permlane\w*|s_ff1\w*"
     r"|\w+_dpp|\w+_sdwa)\b.*", "a lane-cooperative operation (LDS, lane counts, cross-lane reads, DPP, SDWA) cannot "
     "be lowered one vertex per invocation; NGG culling is refused (docs/design/vertex-stage.md)"),
    (r"(?:buffer_load_format\w*|tbuffer_\w+)\b.*",
     "typed vertex fetch (buffer_load_format_*, tbuffer_*) needs a corpus build that exercises it (card V-3)"),
    (r"(?:flat_\w+|scratch_\w+)\b.*", "flat and scratch memory are not lowered in the vertex stage"),
    (r"(?:buffer_store\w*|buffer_atomic\w*|global_store\w*|global_atomic\w*|s_store\w*|s_buffer_store\w*"
     r"|image_store\w*|image_atomic\w*)\b.*", "a vertex shader with memory side effects is not lowered"),
    (r"image_\w+\b.*", "image operations in the vertex stage (image_sample_lz) are lowered in card V-5"),
    (r"v_interp_\w+\b.*", "interpolation is a pixel-stage operation"),
    (r".*\bexec(?:_lo|_hi)?\b.*", "execution mask reads and writes are not lowered in the vertex stage"),
)


# --- user SGPRs --------------------------------------------------------------------------------------------------------

def _role_map(user_sgprs, stage):
    """Validate the user-SGPR map. Returns (scalar entry values, descriptor tables, root constants used, constants)."""
    scalar = {}
    tables = {}
    root = set()  # "base_vertex", "start_instance", "push"
    constants = 0
    used_words = {}
    push_words = {}
    for key, role in sorted((user_sgprs or {}).items()):
        number = int(key)
        if not 0 <= number <= 105:
            raise ValueError(f"User SGPR s{number} is out of range")
        if stage == "ngg" and number < NGG_FIRST_USER_SGPR:
            raise ValueError(f"User SGPR s{number}: s0..s7 of an NGG wave are hardware SGPRs (s2 gs_tg_info, s3 "
                             "merged_wave_info), not user data")
        if not isinstance(role, tuple) or not role:
            raise ValueError(f"User SGPR s{number} has a malformed role {role!r}")
        kind = role[0]
        if kind in ("base_vertex", "start_instance"):
            if len(role) != 1 or kind in root:
                raise ValueError(f"At most one {kind.replace('_', '-')} user SGPR, with no parameters")
            root.add(kind)
            scalar[f"s{number}"] = ("uint", kind)
        elif kind == "inline":
            if len(role) != 2 or not isinstance(role[1], int) or not 0 <= role[1] < PUSH_WORDS:
                raise ValueError(f"User SGPR s{number}: an inline word needs its push-constant word, 0 to "
                                 f"{PUSH_WORDS - 1}")
            if role[1] in push_words:
                raise ValueError(f"Push-constant word {role[1]} is given to s{push_words[role[1]]} and s{number}")
            push_words[role[1]] = number
            root.add("push")
            scalar[f"s{number}"] = ("uint", f"push_words[{role[1] // 4}].{'xyzw'[role[1] % 4]}")
        elif kind == "descriptors":
            if len(role) != 3 or not isinstance(role[1], int) or not 0 <= role[1] <= 0xffffffff:
                raise ValueError(f"User SGPR s{number}: a descriptor list needs its 32-bit high word and its entries")
            entries = {}
            for offset, entry in sorted(role[2].items()):
                if not isinstance(offset, int) or offset < 0 or offset % 16 or offset > 0xffff0:
                    raise ValueError(f"Descriptor list in s{number}: entry offset {offset!r} is not 16-byte aligned")
                if entry == ("constants",):
                    constants += 1
                elif (len(entry) == 2 and entry[0] in ("vsharp", "constants") and isinstance(entry[1], int)
                      and 0 <= entry[1] <= 60):
                    constants += entry[0] == "constants"
                    for word in range(entry[1], entry[1] + 4):
                        if word in used_words:
                            raise ValueError(f"V# words overlap at constant word {word}")
                        used_words[word] = number
                else:
                    raise ValueError(f"Descriptor list in s{number}: unknown entry {entry!r}")
                entries[offset] = entry
            if not entries:
                raise ValueError(f"Descriptor list in s{number} declares no entries")
            tables[number] = (role[1], entries)
            scalar[f"s{number}"] = ("vdesc", number)
        else:
            raise ValueError(f"User SGPR s{number} has an unknown role {kind!r}")
    if constants > 1:
        raise ValueError("Only one constant-buffer V# (bound as b0) is lowered")
    return scalar, tables, root, constants == 1


def parse_role_map(data):
    """The JSON form of a user-SGPR map (see the module docstring) as the dict lower() takes."""
    out = {}
    for key, value in data.items():
        if not re.fullmatch(r"\d+", key) or not isinstance(value, dict) or "role" not in value:
            raise ValueError(f"Malformed user-SGPR map entry {key!r}")
        role = value["role"]
        if role == "descriptors":
            entries = {}
            for offset, entry in value.get("entries", {}).items():
                if entry == "constants":
                    entries[int(offset, 0)] = ("constants",)
                elif isinstance(entry, dict) and len(entry) == 1 and set(entry) <= {"vsharp", "constants"}:
                    entries[int(offset, 0)] = tuple(entry.items())[0]
                else:
                    raise ValueError(f"Malformed descriptor entry {entry!r}")
            out[int(key)] = ("descriptors", value.get("high"), entries)
        elif role == "inline":
            out[int(key)] = ("inline", value.get("word"))
        else:
            out[int(key)] = (role,)
    return out


# --- the NGG passthrough frame (card V-2) ------------------------------------------------------------------------------

def _clean(instructions):
    program = [line.split(";")[0].strip() for line in instructions]
    return [" ".join(line.split()) for line in program if line and not line.startswith("#")]


def _is_label(line):
    return re.fullmatch(r"[A-Za-z_.$][\w.$]*:", line) is not None


def is_ngg(program):
    """An NGG vertex shader starts with the frame's s_barrier (after s_setprio); a legacy VS never has one there."""
    first = next((line for line in program if not _is_label(line) and not line.startswith("s_setprio")), "")
    return first == "s_barrier"


def match_ngg_frame(program):
    """Match RADV's NGG passthrough frame (docs/design/vertex-stage.md) around a vertex body and return the body as a
    legacy-shaped program (s_setprio, the body, s_endpgm), or raise ValueError naming the first difference.

    The frame, with gs_tg_info in s2, merged_wave_info in s3 and the primitive payload in v0 (the gfx10 NGG entry
    layout; tools/vertex_corpus_report.py ngg_passthrough is the measuring reference):
        s_barrier ; s_and_b32 sT, s3, 0xf000000 ; s_cbranch_scc1 A
        s_bfe_u32 x, s2, 0x90016 ; s_lshl_b32 x, x, 12 ; s_bfe_u32 y, s2, 0x9000c ; s_or_b32 m0, x, y
        s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)
      A: two regions in either order, each ending at the label its s_cbranch_execz names:
        prim:   s_lshl_b32 c, s3, 8         ; s_bfe_u64 exec, -1, c ; s_cbranch_execz P ; exp prim v0, off, off, off done
        vertex: s_pack_ll_b32_b16 c, 0, s3  ; s_bfe_u64 exec, -1, c ; s_cbranch_execz V ; <vertex body>
      s_endpgm
    s_waitcnt expcnt(0) may stand before a count or the exec write. Every branch must land on its label. The frame's
    allocation and primitive export are what the desktop input assembler does itself, so they are dropped; the body
    is lowered as a legacy VS with the NGG entry roles."""
    lines = list(program)
    pos = 0
    prefix = []
    while pos < len(lines) and (lines[pos].startswith("s_setprio") or _is_label(lines[pos])):
        if not _is_label(lines[pos]):
            prefix.append(lines[pos])
        pos += 1

    def peek():
        return lines[pos] if pos < len(lines) else "end of program"

    def take(pattern, what):
        nonlocal pos
        if not (m := re.fullmatch(pattern, peek())):
            raise ValueError(f"NGG frame: expected {what}, found {peek()!r}")
        pos += 1
        return m.groups()

    def label(name, what):
        nonlocal pos
        if name is None:  # an optional label after a branch (the fall-through block)
            if pos < len(lines) and _is_label(lines[pos]):
                pos += 1
            return
        if peek() != f"{name}:":
            raise ValueError(f"NGG frame: {what} does not land on {name}:, found {peek()!r}")
        pos += 1

    def waits():
        nonlocal pos
        while peek() == "s_waitcnt expcnt(0)":
            pos += 1

    take(r"s_barrier", "s_barrier")
    take(r"s_and_b32 s\d+, s3, 0xf000000", "the wave-id test of merged_wave_info (s3)")
    (alloc_end,) = take(r"s_cbranch_scc1 (\S+)", "the branch around GS_ALLOC_REQ")
    label(None, "")
    x, = take(r"s_bfe_u32 (s\d+), s2, 0x90016", "the primitive count from gs_tg_info (s2)")
    take(rf"s_lshl_b32 {x}, {x}, 12", "the primitive count shift")
    y, = take(r"s_bfe_u32 (s\d+), s2, 0x9000c", "the vertex count from gs_tg_info (s2)")
    if y == x:
        raise ValueError("NGG frame: the vertex count overwrites the primitive count")
    take(rf"s_or_b32 m0, (?:{x}, {y}|{y}, {x})", "m0 = primitive count << 12 | vertex count")
    take(r"s_sendmsg sendmsg\(MSG_GS_ALLOC_REQ\)", "s_sendmsg GS_ALLOC_REQ")
    label(alloc_end, "the branch around GS_ALLOC_REQ")
    order, body = [], None
    for _ in range(2):
        waits()
        if re.fullmatch(r"s_lshl_b32 s\d+, s3, 8", peek()):
            kind, (count,) = "prim", take(r"s_lshl_b32 (s\d+), s3, 8", "")
        else:
            kind, (count,) = "vertex", take(r"s_pack_ll_b32_b16 (s\d+), 0, s3",
                                            "a primitive count (s_lshl_b32 c, s3, 8) or vertex count "
                                            "(s_pack_ll_b32_b16 c, 0, s3)")
        if kind in order:
            raise ValueError(f"NGG frame: the {kind} region repeats")
        order.append(kind)
        waits()
        take(rf"s_bfe_u64 exec, -1, {count}", f"the exec mask from the {kind} count")
        (end,) = take(r"s_cbranch_execz (\S+)", f"the branch around the {kind} region")
        label(None, "")
        if kind == "prim":
            take(r"exp prim v0, off, off, off done", "a single passthrough export of the payload v0")
            label(end, "the branch around the primitive export")
        else:
            if f"{end}:" not in lines[pos:]:
                raise ValueError(f"NGG frame: the branch around the vertex region names no later label {end}")
            stop = lines.index(f"{end}:", pos)
            body = lines[pos:stop]
            pos = stop + 1
    if lines[pos:] != ["s_endpgm"]:
        raise ValueError(f"NGG frame: expected s_endpgm after the two regions, found {peek()!r}")
    while body and body[-1] == "s_waitcnt expcnt(0)":
        body.pop()
    for line in body:
        if re.fullmatch(r"(?:s_barrier|s_sendmsg\w*|exp prim)\b.*", line):
            raise ValueError(f"NGG body: frame operation {line!r}")
    found = features([line for line in body if not _is_label(line)])
    frame_inputs = set(found["inputs_sgpr"] + found["inputs_special"]) & {"s2", "s3", "m0"}
    if frame_inputs:
        raise ValueError("NGG body: reads the frame register " + ", ".join(sorted(frame_inputs))
                         + " (gs_tg_info, merged_wave_info or m0) at entry")
    if order[0] == "vertex":
        # The primitive region runs after the body and reads merged_wave_info and the payload: both must survive.
        for register in ("v0", "s3"):
            if register in found["written"]:
                raise ValueError(f"NGG body: writes {register}, which the primitive export after the body reads")
    return prefix + body + ["s_endpgm"], order


# --- position exports (pos1..3) ----------------------------------------------------------------------------------------

def position_vectors(vs_out_cntl):
    """{"pos1": (kind, first distance, enabled channels), ...} from PA_CL_VS_OUT_CNTL (gfx10 field layout as Mesa's sid.h gives it:
    CLIP_DIST_ENA_0..7 bits 0..7, CULL_DIST_ENA_0..7 bits 8..15, USE_VTX_POINT_SIZE 16, EDGE_FLAG 17,
    RENDER_TARGET_INDX 18, VIEWPORT_INDX 19, KILL_FLAG 20, VS_OUT_MISC_VEC_ENA 21, VS_OUT_CCDIST0_VEC_ENA 22,
    VS_OUT_CCDIST1_VEC_ENA 23). Position exports after pos0 are the enabled vectors in that order: the misc vector,
    then distances 0..3, then 4..7. Only distance vectors are lowered, and each must be all clip or all cull (kind
    "clip" or "cull"); a distance channel whose bit is clear is undefined. Returns {} for no state (None)."""
    if vs_out_cntl is None:
        return {}
    if not isinstance(vs_out_cntl, int) or not 0 <= vs_out_cntl <= 0xffffffff:
        raise ValueError("PA_CL_VS_OUT_CNTL must be a 32-bit word")
    if vs_out_cntl >> 24:
        raise ValueError(f"PA_CL_VS_OUT_CNTL {vs_out_cntl:#x}: bits above VS_OUT_CCDIST1_VEC_ENA are not lowered")
    if vs_out_cntl & (0x3f << 16):
        raise ValueError(f"PA_CL_VS_OUT_CNTL {vs_out_cntl:#x}: point size, edge flag, render-target index, viewport "
                         "index, kill flag and the misc vector are not lowered (point size has no D3D12 equivalent)")
    clip, cull = vs_out_cntl & 0xff, (vs_out_cntl >> 8) & 0xff
    if clip & cull:
        raise ValueError("PA_CL_VS_OUT_CNTL enables a distance as both clip and cull")
    vectors, enabled = {}, 0
    for k in (0, 1):
        if not vs_out_cntl >> (22 + k) & 1:
            continue
        enabled |= 0xf << (4 * k)
        kinds = {("clip" if clip >> d & 1 else "cull") for d in range(4 * k, 4 * k + 4) if (clip | cull) >> d & 1}
        if len(kinds) != 1:
            raise ValueError(f"PA_CL_VS_OUT_CNTL: distance vector {k} must enable clip or cull distances, not "
                             f"{'both' if kinds else 'neither'}")
        on = tuple(bool((clip | cull) >> d & 1) for d in range(4 * k, 4 * k + 4))
        vectors[f"pos{1 + len(vectors)}"] = (kinds.pop(), 4 * k, on)
    if (clip | cull) & ~enabled:
        raise ValueError("PA_CL_VS_OUT_CNTL enables a distance whose vector is not exported")
    return vectors


# --- lowering ----------------------------------------------------------------------------------------------------------

def _vector_reads(line):
    """The VGPRs an instruction reads, as far as the entry-register check needs: every operand after the first, and
    every operand of an export. The destination of v_mac and v_fmac is also a source."""
    head, _, rest = line.partition(" ")
    operands = [token.strip() for token in rest.split(",")]
    if head == "exp":
        sources = operands
    else:
        sources = operands[1:]
        if re.fullmatch(r"v_(?:f?mac)_\w+", head):
            sources = operands
    out = set()
    for token in sources:
        for first, last in re.findall(r"v\[(\d+):(\d+)\]", token):
            out.update(f"v{n}" for n in range(int(first), int(last) + 1))
        out.update(re.findall(r"(?<![\w\[:])v\d+\b", token))
    return out




def lower_with_layout(instructions, user_sgprs, vs_out_cntl=None):
    """Lower a vertex program. Returns (HLSL source, layout) where layout names the hardware stage and the exports:
    {"stage": "legacy" or "ngg", "params": [N, ...] ascending, "positions": [("pos1", kind, first distance), ...],
    "channels": {"pos0": (bool x4), "paramN": (bool x4), "posN": (bool x4)}, "instance_id": bool}; a False channel
    was exported as `off` (or, for a distance vector, has no enabled distance) and is undefined."""
    program = _clean(instructions)
    stage = "ngg" if is_ngg(program) else "legacy"
    order = None
    if stage == "ngg":
        program, order = match_ngg_frame(program)
    entry_scalar, tables, root, has_constants = _role_map(user_sgprs, stage)
    # A label alone is not control flow (the ISA dumps start with BB0:); every branch is refused below.
    program = [line for line in program if not _is_label(line)]
    for line in program:
        for pattern, reason in REFUSALS:
            if re.fullmatch(pattern, line):
                raise ValueError(f"Refused {line!r}: {reason}")
    vectors = position_vectors(vs_out_cntl)

    # The pixel state with no texture, sampler or interpolation binding, so that no pixel-only form can apply. PREAMBLE
    # marks where helper definitions go, as in the pixel lowering; it is replaced by the vertex entry at the end.
    st = Lowering(dict(entry_scalar), {reg: ("uint", name) for reg, name in ENTRY_VGPRS[stage].items()}, [PREAMBLE],
                  {}, (), 0 if has_constants else None, {})
    st.constant_limit = CONSTANT_BYTES
    exports = {}
    ended = False

    def before(i, line):
        if ended:
            raise ValueError(f"Instruction follows program end: {line}")

    def special(i, line):
        nonlocal ended
        if line.startswith("exp "):
            _export(i, line, st, exports, vectors)
        elif line == "s_endpgm":
            _check_positions(exports, vectors)
            ended = True
        else:
            return False
        return True

    uses_instance = run_body(st, program, tables, stage, special, before=before)
    if not ended:
        raise ValueError("Missing s_endpgm")
    # CF-2a lane gate: every lane active (ex "true") and not in whole-quad mode.
    if st.ex != "true" or st.wqm or st.exported or st.flat_attrs or st.quad_position or st.samples:
        raise ValueError("A pixel-stage operation reached the vertex lowering")
    layout = _layout(exports, vectors, stage, uses_instance)
    uses_vsharps = any(len(entry) == 2 for _, entries in tables.values() for entry in entries.values())
    return _assemble(st, exports, vectors, root, has_constants, uses_vsharps, uses_instance), layout


def run_body(st, program, tables, stage, special, entry_vgprs=None, reasons=None, before=None):
    """Lower each line of a vertex-stage body into st. special(i, line) handles a line itself (an export, the end of
    the program, or a line of another stage's contract, tools/geometry_aot.py) and returns True, else False. Returns
    whether the instance id was read. entry_vgprs and reasons default to the stage's ENTRY_VGPRS and
    ENTRY_VGPR_REASONS. before(i, line), if given, runs first for each line."""
    reasons = ENTRY_VGPR_REASONS[stage] if reasons is None else reasons
    entry_vgprs = ENTRY_VGPRS[stage] if entry_vgprs is None else entry_vgprs
    unwritten = set(reasons)
    instance = next((reg for reg, name in entry_vgprs.items() if name == "iid"), None)
    uses_instance = False
    for i, line in enumerate(program):
        if before is not None:
            before(i, line)
        reads = _vector_reads(line)
        for register in sorted(reads & unwritten):
            raise ValueError(f"Refused {line!r}: {reasons[register]}")
        if instance in reads and st.vector.get(instance) == ("uint", "iid"):
            uses_instance = True
        try:
            if special(i, line):
                pass
            elif re.match(r"s_load_dword", line):
                _descriptor_load(line, st, tables)
            elif (m := re.match(r"s_buffer_load_dword\w* [^,]+, s\[(\d+):(\d+)\]", line)) and \
                    getattr(st, "cbv_vsharp", None):
                # The constant buffer's V# is also data here: give the pixel form the binding it reads (cbv words).
                base = [f"s{n}" for n in range(int(m[1]), int(m[2]) + 1)]
                saved = {r: st.scalar.get(r) for r in base}
                if list(saved.values()) == st.cbv_vsharp and not st.pending.intersection(base):
                    st.scalar.update({r: ("cbv", j) for j, r in enumerate(base)})
                    dispatch(st, i, line)
                    for r, value in saved.items():
                        if st.scalar.get(r) == ("cbv", base.index(r)):
                            st.scalar[r] = value
                else:
                    dispatch(st, i, line)
            elif m := re.fullmatch(r"s_waitcnt((?: (?:vmcnt|expcnt|lgkmcnt)\(\d+\))+)", line):
                # The pixel forms accept only a zero count in a combined wait; a vertex shader waits for the older
                # loads only (vmcnt(1) to vmcnt(7) in the corpus). The vmcnt part goes to Lowering.vm_wait, which
                # keeps the newest N loads outstanding (the pixel stage's s_waitcnt vmcnt(N) form), and the rest to
                # the pixel forms.
                fields = re.findall(r"(\w+)\((\d+)\)", m[1])
                if len({name for name, _ in fields}) != len(fields):
                    raise ValueError("Only wait counts without repeats are supported")
                others = [f"{name}({n})" for name, n in fields if name != "vmcnt"]
                for name, n in fields:
                    if name == "vmcnt":
                        st.vm_wait(int(n))
                if others:
                    dispatch(st, i, f"s_waitcnt {' '.join(others)}")
            else:
                dispatch(st, i, line)
        except KeyError as error:
            raise ValueError(f"Read of an unset register {error} in {line!r}") from None
        unwritten -= set(st.vector)
    return uses_instance


def lower(instructions, user_sgprs, vs_out_cntl=None):
    return lower_with_layout(instructions, user_sgprs, vs_out_cntl)[0]


def _descriptor_load(line, st, tables):
    """s_load_dword{,x2,x4,x8,x16} of descriptor-list words through a user-SGPR pointer. Each loaded word must belong
    to an entry of that pointer's list: a V# entry gives its four runtime words (constant words of b0, as the pixel
    path's buffer_descriptors), the constant-buffer entry gives the binding provenance that s_buffer_load needs."""
    m = re.fullmatch(r"s_load_dword(x2|x4|x8|x16)? (s\d+|s\[\d+:\d+\]), (s\[\d+:\d+\]), (null|0x[0-9a-f]+|\d+)"
                     r"((?: glc| dlc)*)", line)
    if not m:
        raise ValueError(f"Unsupported descriptor load {line!r}: the offset must be an immediate or null")
    width, dst_token, base_token, offset_token, flags = m.groups()
    if len(set(flags.split())) != len(flags.split()):
        raise ValueError(f"Repeated scalar load modifier in {line!r}")
    count = int(width[1:]) if width else 1
    if count == 1:
        dst = [sgpr_name(dst_token)]
    else:
        first, last = map(int, re.fullmatch(r"s\[(\d+):(\d+)\]", dst_token).groups())
        if last - first + 1 != count or first % (2 if count == 2 else 4) or last > 105:
            raise ValueError("Invalid scalar load destination registers")
        dst = [f"s{n}" for n in range(first, last + 1)]
    scalar, pending = st.scalar, st.pending
    low, high = sgpr_pair(base_token)
    pointer = scalar.get(low)
    if low not in pending and high not in pending and all(
            isinstance(scalar.get(r), int) or (isinstance(scalar.get(r), tuple) and scalar[r][0] == "uint")
            for r in (low, high)):
        # A 64-bit address in data words (a buffer device address): s_load reads title memory at address + offset,
        # with the address's two low bits ignored (RDNA ISA, SMEM). No range check applies.
        words = [vector_u32(r, scalar, st.vector, pending, st.sample_pending) for r in (low, high)]
        offset = 0 if offset_token == "null" else int(offset_token, 0)
        if offset % 4 or offset > 0xfffff:
            raise ValueError("Scalar load offset is misaligned or out of range")
        st.uses_memory = True
        for j, n in enumerate(dst):
            if n in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            name = f"smem{len(st.lines)}_{j}"
            st.lines.append(f"    uint {name} = global_load32(uint2(({words[0]}) & ~3u, {words[1]}), 0u, "
                            f"uint2({offset}u, 0u), {j}u);")
            scalar[n] = ("uint", name)
            pending.add(n)
        return
    if (low in pending or high in pending or not isinstance(pointer, tuple) or len(pointer) != 2
            or pointer[0] != "vdesc"):
        raise ValueError(f"{line!r} does not read through a descriptor-list user SGPR of the role map")
    table_high, entries = tables[pointer[1]]
    if scalar.get(high) != table_high:
        raise ValueError(f"The high word in {high} is not the {table_high:#x} that the role map gives the descriptor "
                         f"list in s{pointer[1]}")
    offset = 0 if offset_token == "null" else int(offset_token, 0)
    if offset % 4 or offset > 0xfffff:
        raise ValueError("Scalar load offset is misaligned or out of range")
    words = []
    for j in range(count):
        at = offset + 4 * j
        start = next((s for s in entries if s <= at < s + 16), None)
        if start is None:
            raise ValueError(f"Descriptor word at byte {at:#x} of the list in s{pointer[1]} is not in the role map")
        entry = entries[start]
        if entry == ("constants",):
            words.append(("cbv", (at - start) // 4))
        elif entry[0] == "constants":
            word = entry[1] + (at - start) // 4
            words.append(("uint", f"vsharp_words[{word // 4}].{'xyzw'[word % 4]}"))
            st.cbv_vsharp = [("uint", f"vsharp_words[{w // 4}].{'xyzw'[w % 4]}") for w in range(entry[1], entry[1] + 4)]
        else:
            word = entry[1] + (at - start) // 4
            words.append(("uint", f"vsharp_words[{word // 4}].{'xyzw'[word % 4]}"))
    for n, value in zip(dst, words):
        if n in pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        scalar[n] = value
        pending.add(n)




def _export(i, line, st, exports, vectors):
    m = re.fullmatch(r"exp (pos\d+|param\d+|mrt\d+|mrtz|null),? ([^,\s]+), ([^,\s]+), ([^,\s]+), ([^,\s]+)"
                     r"((?: done| compr| vm| row_en)*)", line)
    if not m:
        raise ValueError(f"Unsupported export {line!r}")
    target, *sources, flags = m.groups()
    flags = flags.split()
    if len(set(flags)) != len(flags):
        raise ValueError(f"Repeated export modifier in {line!r}")
    if not target.startswith(("pos", "param")):
        raise ValueError(f"Refused {line!r}: {target} is not a vertex-shader export")
    if target.startswith("pos") and target != "pos0" and target not in vectors:
        if not vectors:
            raise ValueError(f"Refused {line!r}: pos1 to pos3 need PA_CL_VS_OUT_CNTL state (--vs-out-cntl)")
        raise ValueError(f"Refused {line!r}: PA_CL_VS_OUT_CNTL enables no {target} distance vector")
    if target.startswith("param") and int(target[5:]) >= MAX_PARAMS:
        raise ValueError(f"Refused {line!r}: parameter index out of range")
    if "compr" in flags or "row_en" in flags:
        raise ValueError(f"Refused {line!r}: compressed or row exports are not vertex exports")
    if target.startswith("param") and ("done" in flags or "vm" in flags):
        raise ValueError(f"Refused {line!r}: done and vm belong to the position exports")
    if target in exports:
        raise ValueError(f"Refused {line!r}: {target} is exported more than once")
    if st.ex != "true" or st.wqm:
        raise ValueError("Export under a changed execution mask")
    words = []
    for token in sources:
        if token == "off":
            words.append("0u")
        elif re.fullmatch(r"v\d+", token):
            words.append(vector_u32(token, st.scalar, st.vector, st.pending, st.sample_pending))
        else:
            raise ValueError(f"Unsupported export source {token}")
    channels = [token != "off" for token in sources]
    if target in vectors:
        # A channel whose distance PA_CL_VS_OUT_CNTL does not enable is not read by the hardware: it is undefined, and
        # the translation writes 0 there, which neither clips nor culls.
        enabled = vectors[target][2]
        words = [word if on else "0u" for word, on in zip(words, enabled)]
        channels = [exported and on for exported, on in zip(channels, enabled)]
    st.lines.append(f"    uint4 export{i} = uint4({', '.join(words)});")
    exports[target] = (f"export{i}", tuple(channels), "done" in flags)


def _check_positions(exports, vectors):
    """pos0 exactly once, every enabled distance vector exported, and done on the last position export."""
    if "pos0" not in exports:
        raise ValueError("A vertex shader must export pos0 exactly once before s_endpgm")
    missing = sorted(set(vectors) - set(exports))
    if missing:
        raise ValueError(f"PA_CL_VS_OUT_CNTL enables {', '.join(missing)}, which the shader does not export")
    positions = sorted((name for name in exports if name.startswith("pos")), key=lambda n: int(n[3:]))
    done = [name for name in positions if exports[name][2]]
    if done != positions[-1:]:
        raise ValueError(f"Refused: the last position export ({positions[-1]}) must have done, and no other")


def _layout(exports, vectors, stage, uses_instance):
    params = sorted(int(name[5:]) for name in exports if name.startswith("param"))
    positions = [(name, *vectors[name][:2]) for name in sorted(vectors, key=lambda n: int(n[3:]))]
    return {"stage": stage, "params": params, "positions": positions, "instance_id": uses_instance,
            "channels": {name: channels for name, (_, channels, _) in exports.items()}}


def _assemble(st, exports, vectors, root, uses_params, uses_vsharps, uses_instance):
    place_fma_mix(st)
    lines = st.lines
    params = sorted(int(name[5:]) for name in exports if name.startswith("param"))
    # Output order matches what pixel_aot declares for its inputs: TEXCOORD0, SV_Position, then TEXCOORD1..N, so D3D12
    # links a translated vertex shader with a translated pixel shader register by register. Clip and cull distances,
    # system values the pixel shader does not read, come last.
    members = []
    if 0 in params:
        members.append("    float4 param0 : TEXCOORD0;")
    members.append("    float4 pos0 : SV_Position;")
    members.extend(f"    float4 param{n} : TEXCOORD{n};" for n in params if n)
    counters = {"clip": 0, "cull": 0}
    for name in sorted(vectors, key=lambda n: int(n[3:])):
        kind = vectors[name][0]
        semantic = "SV_ClipDistance" if kind == "clip" else "SV_CullDistance"
        members.append(f"    float4 {name} : {semantic}{counters[kind]};")
        counters[kind] += 1
    inputs = "uint vid : SV_VertexID" + (", uint iid : SV_InstanceID" if uses_instance else "")
    entry = "\n".join([HELPERS, "struct VertexOutput {", *members, "};", f"VertexOutput main({inputs}) {{"])
    lines[lines.index(PREAMBLE)] = entry
    head = declarations(st, root, uses_params, uses_vsharps)
    # Each output word is stored through asfloat: a bit cast, so the draw check sees whether a NaN payload survives.
    stores = ["    VertexOutput vertex_out;"]
    stores.extend(f"    vertex_out.{name} = asfloat({variable});"
                  for name, (variable, _, _) in sorted(exports.items()))
    return "\n".join([*head, *lines, *stores, "    return vertex_out;", "}", ""])


def declarations(st, root, uses_params, uses_vsharps):
    """The bindings and helpers a lowered vertex-stage body needs, before its entry point: b0 constants, b4 V# words,
    b2 base vertex and start instance, b3 push words, title memory and the SALU helpers it used."""
    head = []
    if uses_params:
        # uint4, not float4: constant and V# words are raw data (see docs/experiments.md).
        # 16 uint4 (64 words) unless the program reads further; then the highest word read, rounded up to a uint4.
        head.append(f"cbuffer Constants : register(b0) {{ uint4 params[{max(16, -(-st.constant_words // 4))}]; }};")
    if uses_vsharps:
        # The runtime V# words of the descriptor lists, apart from the constant buffer's data.
        head.append("cbuffer Descriptors : register(b4) { uint4 vsharp_words[16]; };")
    if root & {"base_vertex", "start_instance"}:
        # The console's base-vertex and start-instance user SGPRs, passed as root constants; the desktop draw uses 0
        # for both, so the program's own v_add_nc_u32 of the base computes what it computes on the console.
        head.append("cbuffer VertexRoot : register(b2) { uint base_vertex; uint start_instance; };")
    if "push" in root:
        # Inline user-data words (push constants RADV passes in user SGPRs), as root constants.
        head.append(f"cbuffer PushWords : register(b3) {{ uint4 push_words[{PUSH_WORDS // 4}]; }};")
    if st.uses_memory:
        head.extend([TITLE_LOOKUP.read_text(encoding="utf-8"), TITLE_DECLARATIONS, MEMORY_HELPERS])
    head.extend(body for name, body in SALU_HELPERS.items() if name in st.helpers)
    return head


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("program", type=Path)
    parser.add_argument("--llvm", help="libLLVM with the AMDGPU disassembler: PROGRAM is raw code")
    parser.add_argument("--user-sgprs", type=Path, required=True)
    parser.add_argument("--vs-out-cntl", type=lambda text: int(text, 0))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--layout", type=Path)
    args = parser.parse_args()
    try:
        if args.llvm:
            import pixel_aot  # the LLVM disassembler binding of the pixel tool
            code = args.program.read_bytes()
            instructions = pixel_aot.name_branch_targets(pixel_aot.disassemble(code, args.llvm, offsets=True),
                                                         len(code))
        else:
            instructions = args.program.read_text(encoding="utf-8").splitlines()
        roles = parse_role_map(json.loads(args.user_sgprs.read_text(encoding="utf-8")))
        source, layout = lower_with_layout(instructions, roles, args.vs_out_cntl)
    except ValueError as error:
        print(f"vertex_aot: {error}", file=sys.stderr)
        return 1
    args.output.write_text(source, encoding="ascii")
    summary = {"stage": layout["stage"], "params": layout["params"], "positions": layout["positions"],
               "instance_id": layout["instance_id"]}
    if args.layout:
        args.layout.write_text(json.dumps({**summary, "channels": {k: list(v) for k, v in layout["channels"].items()}},
                                          indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
