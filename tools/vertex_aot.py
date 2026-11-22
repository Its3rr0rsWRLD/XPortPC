"""Offline lowering for a straight-line, legacy (non-NGG) gfx1013 vertex shader (card V-1, docs/design/vertex-stage.md).

This module holds the vertex-stage contract: the entry registers (v0 = vertex id, the user-SGPR role map), the
descriptor loads that read V#s through a user-SGPR pointer, the V-1 vertex-fetch rules, partial vmcnt waits, the
exports (pos0 to SV_Position, paramN to TEXCOORDN) and the end of the program. Every other instruction is lowered by
the form registry of tools/pixel_aot_ops (docs/design/module-layout.md), through the same `dispatch` and the same
`Lowering` state as the pixel stage. A form covered once is therefore lowered the same way in both stages, which is
what tools/form_coverage.py assumes when it counts a form.

Usage:
    python tools/vertex_aot.py PROGRAM.s --user-sgprs MAP.json --output OUT.hlsl [--layout OUT.json]
    python tools/vertex_aot.py CODE.bin --llvm LIBLLVM --user-sgprs MAP.json --output OUT.hlsl

PROGRAM.s holds one instruction per line as llvm-mc 15 prints it (text after ';', '#' lines and labels are ignored).
CODE.bin is the raw code of one program, disassembled with the given LLVM library. MAP.json gives the role of each user
SGPR, keyed by its number:
    {"2": {"role": "descriptors", "high": 4294934528, "entries": {"0": {"vsharp": 8}, "16": {"vsharp": 12}}},
     "3": {"role": "base_vertex"},
     "4": {"role": "descriptors", "high": 4294934528, "entries": {"0": "constants"}}}
A "vsharp" entry names the first of the four constant words (b0, `params`) that hold that V# at draw time, as the
pixel path's buffer_descriptors do. The "constants" entry is the constant buffer that s_buffer_load reads (b0).
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
from pixel_aot_ops.registers import sgpr_name, sgpr_pair, vector_u32  # noqa: E402

RADV_ADDRESS_HIGH = 0xffff8000
# Legacy hardware VS entry VGPRs: v0 is the vertex id. v3 is the instance id; v1 and v2 hold values that the V-1
# contract does not define. Reading any of them before writing it is refused with its own reason.
ENTRY_VGPR_REASONS = {
    "v1": "entry VGPR v1 is not part of the V-1 vertex contract (only v0, the vertex id, is)",
    "v2": "entry VGPR v2 is not part of the V-1 vertex contract (only v0, the vertex id, is)",
    "v3": "the instance id (entry VGPR v3) is lowered from card V-3, not V-1",
}
LATER_ROLES = {
    "start_instance": "the start-instance user SGPR is lowered with the instance id, in card V-3",
    "inline": "inline user-data words (push constants) are lowered in card V-3",
    "inline_vsharp": "inline V# words in user SGPRs are lowered in card V-3",
}
MAX_PARAMS = 32

REFUSALS = (
    # Each: a pattern for the first word or the whole line, and the reason. Checked before any lowering.
    (r"(?:s_branch|s_cbranch_\w+|s_setpc_b64|s_swappc_b64|s_call_b64|s_subvector_loop_\w+)\b.*",
     "control flow in the vertex stage is lowered in card V-5 (CF-1 and CF-2 in the vertex stage)"),
    (r"s_getpc_b64\b.*", "embedded constants (s_getpc_b64) are lowered in card V-5"),
    (r"(?:s_sendmsg|s_sendmsghalt|s_barrier)\b.*|exp prim\b.*",
     "an NGG frame operation (s_sendmsg, s_barrier, exp prim): the NGG passthrough frame is matched in card V-2"),
    (r"(?:ds_\w+|v_mbcnt\w*|s_bcnt\w*|v_readlane\w*|v_readfirstlane\w*|v_writelane\w*|v_permlane\w*|s_ff1\w*"
     r"|\w+_dpp)\b.*", "a lane-cooperative operation (LDS, lane counts, cross-lane reads, DPP) cannot be lowered "
     "one vertex per invocation; NGG culling is out of scope (docs/design/vertex-stage.md)"),
    (r"(?:buffer_load_format\w*|tbuffer_\w+)\b.*",
     "typed vertex fetch (buffer_load_format_*, tbuffer_*) is lowered in card V-3 with its own evidence"),
    (r"(?:global_\w+|flat_\w+|scratch_\w+)\b.*", "global, flat and scratch memory in the vertex stage start in card V-3"),
    (r"(?:buffer_store\w*|buffer_atomic\w*|s_store\w*|s_buffer_store\w*|image_store\w*|image_atomic\w*)\b.*",
     "a vertex shader with memory side effects is not lowered"),
    (r"image_\w+\b.*", "image operations in the vertex stage (image_sample_lz) are lowered in card V-5"),
    (r"v_interp_\w+\b.*", "interpolation is a pixel-stage operation"),
    (r".*\bexec(?:_lo|_hi)?\b.*", "execution mask reads and writes are not lowered in the vertex stage"),
)


def _role_map(user_sgprs):
    """Validate the user-SGPR map. Returns (scalar entry values, descriptor tables, needs base vertex, constants)."""
    scalar = {}
    tables = {}
    base_vertex = False
    constants = 0
    used_words = {}
    for key, role in sorted((user_sgprs or {}).items()):
        number = int(key)
        if not 0 <= number <= 105:
            raise ValueError(f"User SGPR s{number} is out of range")
        if not isinstance(role, tuple) or not role:
            raise ValueError(f"User SGPR s{number} has a malformed role {role!r}")
        kind = role[0]
        if kind in LATER_ROLES:
            raise ValueError(f"User SGPR s{number}: {LATER_ROLES[kind]}")
        if kind == "base_vertex":
            if len(role) != 1 or base_vertex:
                raise ValueError("At most one base-vertex user SGPR, with no parameters")
            base_vertex = True
            scalar[f"s{number}"] = ("uint", "base_vertex")
        elif kind == "descriptors":
            if len(role) != 3 or not isinstance(role[1], int) or not 0 <= role[1] <= 0xffffffff:
                raise ValueError(f"User SGPR s{number}: a descriptor list needs its 32-bit high word and its entries")
            entries = {}
            for offset, entry in sorted(role[2].items()):
                if not isinstance(offset, int) or offset < 0 or offset % 16 or offset > 0xffff0:
                    raise ValueError(f"Descriptor list in s{number}: entry offset {offset!r} is not 16-byte aligned")
                if entry == ("constants",):
                    constants += 1
                elif len(entry) == 2 and entry[0] == "vsharp" and isinstance(entry[1], int) and 0 <= entry[1] <= 60:
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
        raise ValueError("Only one constant-buffer V# (bound as b0) is lowered in V-1")
    return scalar, tables, base_vertex, constants == 1


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
                elif isinstance(entry, dict) and set(entry) == {"vsharp"}:
                    entries[int(offset, 0)] = ("vsharp", entry["vsharp"])
                else:
                    raise ValueError(f"Malformed descriptor entry {entry!r}")
            out[int(key)] = ("descriptors", value.get("high"), entries)
        else:
            out[int(key)] = (role,)
    return out


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


def lower_with_layout(instructions, user_sgprs):
    """Lower a vertex program. Returns (HLSL source, layout) where layout names the exports: {"params": [N, ...]
    ascending, "channels": {"pos0": (bool x4), "paramN": (bool x4)}}; a False channel was exported as `off`."""
    entry_scalar, tables, base_vertex, has_constants = _role_map(user_sgprs)
    program = [line.split(";")[0].strip() for line in instructions]
    # A label alone is not control flow (the ISA dumps start with BB0:); every branch is refused below.
    program = [line for line in program if line and not line.startswith("#")
               and not re.fullmatch(r"[A-Za-z_.$][\w.$]*:", line)]
    for line in program:
        for pattern, reason in REFUSALS:
            if re.fullmatch(pattern, line):
                raise ValueError(f"Refused {line!r}: {reason}")

    # The pixel state with no texture, sampler or interpolation binding, so that no pixel-only form can apply. PREAMBLE
    # marks where helper definitions go, as in the pixel lowering; it is replaced by the vertex entry at the end.
    st = Lowering(dict(entry_scalar), {"v0": ("uint", "vid")}, [PREAMBLE], {}, (),
                  0 if has_constants else None, {})
    entry_vgprs = set(ENTRY_VGPR_REASONS)
    exports = {}
    ended = False
    loads = []  # buffer loads not yet known complete, oldest first: (instruction index, destination VGPRs)

    for i, line in enumerate(program):
        if ended:
            raise ValueError(f"Instruction follows program end: {line}")
        for register in sorted(_vector_reads(line) & entry_vgprs):
            if register not in st.vector:
                raise ValueError(f"Refused {line!r}: {ENTRY_VGPR_REASONS[register]}")
        try:
            if line.startswith("exp "):
                _export(i, line, st, exports)
            elif line == "s_endpgm":
                if "pos0" not in exports:
                    raise ValueError("A vertex shader must export pos0 exactly once before s_endpgm")
                ended = True
            elif re.match(r"s_load_dword", line):
                _descriptor_load(line, st, tables)
            elif re.match(r"buffer_load_dword", line):
                _check_fetch(line)
                dispatch(st, i, line)
                loads.append((i, [d for d in sorted(st.sample_dest) if st.vector[d][1].startswith(f"mem{i}_")]))
            elif re.fullmatch(r"s_waitcnt(?: (?:vmcnt|expcnt|lgkmcnt)\(\d+\))+|s_waitcnt_vmcnt null, \S+", line):
                line = _wait_loads(line, st, loads)
                if line:
                    dispatch(st, i, line)
            else:
                dispatch(st, i, line)
        except KeyError as error:
            raise ValueError(f"Read of an unset register {error} in {line!r}") from None
        entry_vgprs -= set(st.vector)
    if not ended:
        raise ValueError("Missing s_endpgm")
    # CF-2a lane gate: every lane active (ex "true") and not in whole-quad mode.
    if st.ex != "true" or st.wqm or st.exported or st.flat_attrs or st.quad_position or st.samples:
        raise ValueError("A pixel-stage operation reached the vertex lowering")
    return _assemble(st, exports, base_vertex, has_constants or bool(tables)), _layout(exports)


def lower(instructions, user_sgprs):
    return lower_with_layout(instructions, user_sgprs)[0]


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
        if entry[0] == "constants":
            words.append(("cbv", (at - start) // 4))
        else:
            word = entry[1] + (at - start) // 4
            words.append(("uint", f"params[{word // 4}].{'xyzw'[word % 4]}"))
    for n, value in zip(dst, words):
        if n in pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        scalar[n] = value
        pending.add(n)


def _wait_loads(line, st, loads):
    """Model s_waitcnt vmcnt(N) for N > 0. The pixel lowering accepts only vmcnt(0), which completes every load; RADV's
    vertex shaders wait for the older loads only (vmcnt(1) to vmcnt(7) in the corpus). Buffer loads return their data
    in issue order (AMD RDNA ISA, section 4.4 "Data Dependency Resolution": vector memory loads return in the order
    they were issued, and VM_CNT counts them), so vmcnt(N) completes every load but the newest N. Each completed
    destination that still holds its load's value is copied to a word the pixel read guard accepts (that guard refuses
    every load result while any load is outstanding, which would refuse a completed load's register read after a newer
    load is issued); the newest N stay outstanding. When no load stays outstanding (vmcnt(0), or N at least the number
in flight) the guard is off and the words keep their names. Returns the rest of the line for the pixel lowering
(lgkmcnt, expcnt), or None."""
    if m := re.fullmatch(r"s_waitcnt_vmcnt null, (0x[0-9a-f]+|\d+)", line):
        count, rest = int(m[1], 0), None
        if count > 0x3f:
            raise ValueError("Invalid wait count immediate")
    else:
        fields = re.findall(r"(\w+)\((\d+)\)", line)
        if len({name for name, _ in fields}) != len(fields):
            raise ValueError("Only wait counts without repeats are supported")
        count = next((int(n) for name, n in fields if name == "vmcnt"), None)
        others = [f"{name}({n})" for name, n in fields if name != "vmcnt"]
        rest = f"s_waitcnt {' '.join(others)}" if others else None
        if count is None:
            return line
        if count > 0x3f:
            raise ValueError("Invalid vmcnt")
    done, loads[:] = loads[:max(len(loads) - count, 0)], loads[max(len(loads) - count, 0):]
    vector = st.vector
    for index, dests in (done if loads else ()):
        for register in dests:
            value = vector.get(register)
            if isinstance(value, tuple) and value[0] == "uint" and value[1].startswith(f"mem{index}_"):
                name = "vmc" + value[1][3:]
                st.lines.append(f"    uint {name} = {value[1]};")
                vector[register] = ("uint", name)
    st.sample_dest.clear()
    st.sample_dest.update({d: (index, "mubuf") for index, dests in loads for d in dests})  # sample_pending follows it
    return rest


def _check_fetch(line):
    """V-1 vertex fetch: untyped dword loads indexed by one VGPR (idxen), with no VGPR offset."""
    m = re.fullmatch(r"buffer_load_dword(?:x[234])? \S+, (\S+), \S+, \S+((?: \S+)*)", line)
    if not m:
        raise ValueError(f"Malformed buffer load {line!r}")
    modifiers = m[2].split()
    if "offen" in modifiers or m[1] == "off" or m[1].startswith("v["):
        raise ValueError(f"Refused {line!r}: offset-addressed (offen) buffer loads in the vertex stage start in "
                         "card V-3; V-1 fetches by index (idxen) only")
    if "idxen" not in modifiers:
        raise ValueError(f"Refused {line!r}: a V-1 vertex fetch is indexed (idxen)")


def _export(i, line, st, exports):
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
    if target.startswith("pos") and target != "pos0":
        raise ValueError(f"Refused {line!r}: pos1 to pos3 need PA_CL_VS_OUT_CNTL state, which card V-3 adds")
    if target.startswith("param") and int(target[5:]) >= MAX_PARAMS:
        raise ValueError(f"Refused {line!r}: parameter index out of range")
    if "compr" in flags or "row_en" in flags:
        raise ValueError(f"Refused {line!r}: compressed or row exports are not vertex exports")
    if target == "pos0" and "done" not in flags:
        raise ValueError(f"Refused {line!r}: the last position export must have done")
    if target != "pos0" and ("done" in flags or "vm" in flags):
        raise ValueError(f"Refused {line!r}: done and vm belong to the position export")
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
    st.lines.append(f"    uint4 export{i} = uint4({', '.join(words)});")
    exports[target] = (f"export{i}", tuple(token != "off" for token in sources))


def _layout(exports):
    params = sorted(int(name[5:]) for name in exports if name.startswith("param"))
    return {"params": params, "channels": {name: channels for name, (_, channels) in exports.items()}}


def _assemble(st, exports, base_vertex, uses_params):
    lines = st.lines
    params = sorted(int(name[5:]) for name in exports if name.startswith("param"))
    # Output order matches what pixel_aot declares for its inputs: TEXCOORD0, SV_Position, then TEXCOORD1..N, so D3D12
    # links a translated vertex shader with a translated pixel shader register by register.
    members = []
    if 0 in params:
        members.append("    float4 param0 : TEXCOORD0;")
    members.append("    float4 pos0 : SV_Position;")
    members.extend(f"    float4 param{n} : TEXCOORD{n};" for n in params if n)
    entry = "\n".join([HELPERS, "struct VertexOutput {", *members, "};",
                       "VertexOutput main(uint vid : SV_VertexID) {"])
    lines[lines.index(PREAMBLE)] = entry
    head = []
    if uses_params:
        # uint4, not float4: constant and V# words are raw data (see docs/experiments.md).
        head.append("cbuffer Constants : register(b0) { uint4 params[16]; };")
    if base_vertex:
        # The console's base-vertex user SGPR, passed as a root constant; the desktop draw uses base vertex 0.
        head.append("cbuffer VertexRoot : register(b2) { uint base_vertex; };")
    if st.uses_memory:
        head.extend([TITLE_LOOKUP.read_text(encoding="utf-8"), TITLE_DECLARATIONS, MEMORY_HELPERS])
    head.extend(body for name, body in SALU_HELPERS.items() if name in st.helpers)
    # Each output word is stored through asfloat: a bit cast, so the V-1 draw check sees whether a NaN payload survives.
    stores = ["    VertexOutput vertex_out;"]
    stores.extend(f"    vertex_out.{name} = asfloat({variable});" for name, (variable, _) in sorted(exports.items()))
    return "\n".join([*head, *lines, *stores, "    return vertex_out;", "}", ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("program", type=Path)
    parser.add_argument("--llvm", help="libLLVM with the AMDGPU disassembler: PROGRAM is raw code")
    parser.add_argument("--user-sgprs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--layout", type=Path)
    args = parser.parse_args()
    try:
        if args.llvm:
            import pixel_aot  # the LLVM disassembler binding of the pixel tool
            instructions = pixel_aot.disassemble(args.program.read_bytes(), args.llvm)
        else:
            instructions = args.program.read_text(encoding="utf-8").splitlines()
        roles = parse_role_map(json.loads(args.user_sgprs.read_text(encoding="utf-8")))
        source, layout = lower_with_layout(instructions, roles)
    except ValueError as error:
        print(f"vertex_aot: {error}", file=sys.stderr)
        return 1
    args.output.write_text(source, encoding="ascii")
    if args.layout:
        args.layout.write_text(json.dumps({"params": layout["params"],
                                           "channels": {k: list(v) for k, v in layout["channels"].items()}},
                                          indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"params": layout["params"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
