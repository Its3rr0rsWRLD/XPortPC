"""Offline lowering for a gfx1013 compute shader to an HLSL compute shader (design: docs/design/compute-stage.md).

Card C-1: a straight-line program (no label, branch or LDS, no barrier, no cross-lane operation) that reads the thread
ids, loads through buffer V#s and scalar constants and stores whole dwords with buffer_store_dword{,x2,x3,x4}. The
instruction forms are the pixel stage's (tools/pixel_aot_ops/forms); this module supplies the compute entry contract
(what each entry register holds), the stage's refusals and the HLSL around the body:

    one HLSL thread = one console lane = one invocation, [numthreads] = the workgroup size, SV_GroupID = the workgroup
    id SGPRs, SV_GroupThreadID = the local id VGPRs v0, v1, v2 (gfx10 passes them unpacked).

Title memory is the pixel stage's (src/title_va_lookup.hlsli), declared read-write: RWByteAddressBuffer title_memory[8]
at u0..u7 in space 1. The root signature is embedded in the HLSL (COMPUTE_ROOT) and matches tests/compute_aot_render.cpp.

Usage:
    python tools/compute_aot.py translate PROGRAM.s --numthreads X Y Z --wave 64 --sgpr s2=descriptors
        --sgpr s3=group_id.x [--local-ids N] [--constant-descriptor OFFSET] [--buffer-descriptor OFFSET=WORD]...
        --output OUT.hlsl
    python tools/compute_aot.py survey --isa DIR [--status site/status.json] [--json OUT]

PROGRAM.s is instruction text, one per line, as llvm-mc prints it or as a RADV dump writes it (a leading "BB0:" label and
"; encoding" comments are dropped). Python standard library only.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from pixel_aot_ops.dispatch import dispatch  # noqa: E402
from pixel_aot_ops.hlsl import MEMORY_HELPERS, PREAMBLE, SALU_HELPERS, TITLE_LOOKUP  # noqa: E402
from pixel_aot_ops.lowering import Lowering, masked_writes  # noqa: E402

# RADV completes a 32-bit descriptor-list pointer with s_movk_i32 s(n+1), 0x8000, which sign-extends to 0xffff8000
# (its address32_hi on gfx10).
RADV_DESCRIPTOR_HIGH = 0xffff8000
# Parameter order: 0 the constant words (params, b0), 1 the title ranges (t2), 2 the eight title-memory UAVs (u0..u7,
# space 1), 3 the range count (b1).
COMPUTE_ROOT = ("CBV(b0), SRV(t2), DescriptorTable(UAV(u0, space=1, numDescriptors=8)), "
                "RootConstants(num32BitConstants=1, b1)")
TITLE_DECLARATIONS_RW = """StructuredBuffer<TitleRange> title_ranges : register(t2);
RWByteAddressBuffer title_memory[8] : register(u0, space1);
cbuffer TitleCount : register(b1) { uint title_range_count; };
"""
PIXEL_HEAD = "Texture2D<float4> tex : register(t0);\nSamplerState samp : register(s0);\n"
PIXEL_MAIN = "float4 main(float2 uv : TEXCOORD0) : SV_Target0 {"
assert PREAMBLE.startswith(PIXEL_HEAD) and PREAMBLE.endswith(PIXEL_MAIN)
NUMERIC_HELPERS = PREAMBLE[len(PIXEL_HEAD):-len(PIXEL_MAIN)]  # class32, ftz32, mad32, widen16, ... without the pixel I/O

GROUP_ROLES = ("group_id.x", "group_id.y", "group_id.z")
LOCAL_IDS = ("local_id.x", "local_id.y", "local_id.z")

# Instructions this card refuses, with the card that lowers them (docs/design/compute-stage.md). The forms would
# refuse most of them anyway; naming the reason makes the refusal controls and the survey read the same.
LATER = (
    (r"ds_\w+.*", "LDS (groupshared) access is card C-6"),
    (r"s_barrier", "s_barrier is card C-6"),
    (r"(v_readfirstlane_b32|v_readlane_b32|v_writelane_b32)\b.*",
     "a cross-lane read or write needs a proof of wave uniformity (card C-7)"),
    (r"(v_mbcnt_\w+|s_bcnt[01]_i32_b(32|64)|s_ff[01]_i32_b(32|64)|s_flbit_i32\w*|s_bitreplicate_b64_b32)\b.*exec.*",
     "a lane count or lane index of EXEC depends on the wave size (card C-8)"),
    (r"v_mbcnt_\w+.*", "v_mbcnt depends on the wave size and the lane order (card C-8)"),
    (r"(v_permlane\w*|v_swap_rel\w*|v_movrel\w*)\b.*", "a cross-lane permutation is refused (no card)"),
    (r"(buffer|global|flat|image)_atomic\w*.*", "atomics are card C-8"),
    (r"image_\w+.*", "image access in the compute stage is card C-2"),
    (r"(global|flat|scratch)_store\w*.*", "global stores are card C-5"),
    (r"(buffer|tbuffer)_store_(byte|short|format)\w*.*", "sub-dword and typed stores are not planned in C-1"),
    (r"(s_branch|s_cbranch_\w+|s_setpc_b64|s_swappc_b64|s_getpc_b64)\b.*", "control flow is card C-3"),
    (r"s_sendmsg\w*.*|s_ttracedata.*", "messages are refused in the compute stage"),
)
WAVE64_ONLY = re.compile(r"(?<![\w])(exec|vcc)(?![\w])")
WAVE32_ONLY = re.compile(r"(?<![\w])(exec_lo|exec_hi|vcc_lo|vcc_hi)(?![\w])")
MEMORY_LOAD = re.compile(r"(buffer_load|tbuffer_load|global_load|flat_load|scratch_load)\w*\b.*")


def parse_role(token):
    """An entry-SGPR role: 'descriptors' (the 32-bit descriptor-list pointer), 'group_id.x|y|z' or 'user:N' (the
    inline user-data word N of params, such as a push constant)."""
    if token in ("descriptors", *GROUP_ROLES):
        return token
    if m := re.fullmatch(r"user:(\d+)", token):
        if int(m[1]) < 64:
            return token
    raise ValueError(f"Unknown entry SGPR role {token}")


def lower_compute(instructions, *, numthreads, wave, sgprs, local_ids=3, packed_ids=False, constant_descriptor=None,
                  buffer_descriptors=None):
    """Lower a straight-line gfx1013 compute program to HLSL source (card C-1).

    numthreads: the workgroup size (x, y, z). wave: 32 or 64, the console wave size the program was compiled for; it
    only decides which lane-mask spellings are legal, since no accepted program depends on it. sgprs: {"sN": role}
    (parse_role). local_ids: how many of v0, v1, v2 hold the local ids (COMPUTE_PGM_RSRC2.TIDIG_COMP_CNT + 1).
    constant_descriptor: the descriptor-table byte offset of the constant-buffer V# (its words are params[]).
    buffer_descriptors: {descriptor-table byte offset of a buffer V#: index of its first word in params}."""
    if (len(numthreads) != 3 or any(not isinstance(n, int) or n < 1 for n in numthreads) or numthreads[0] > 1024
            or numthreads[1] > 1024 or numthreads[2] > 64 or numthreads[0] * numthreads[1] * numthreads[2] > 1024):
        raise ValueError("Invalid workgroup size: D3D12 allows x, y <= 1024, z <= 64 and at most 1024 threads")
    if wave not in (32, 64):
        raise ValueError("gfx1013 waves have 32 or 64 lanes")
    if packed_ids:
        raise ValueError("gfx1013 passes the local ids unpacked in v0, v1 and v2 (packed ids are gfx11 and gfx90a)")
    if local_ids not in (1, 2, 3):
        raise ValueError("One to three local-id VGPRs")
    scalar, roles = {}, Counter()
    for reg, token in sgprs.items():
        if not re.fullmatch(r"s(\d+)", reg) or int(reg[1:]) > 105:
            raise ValueError(f"Invalid entry SGPR {reg}")
        role = parse_role(token)
        roles[role] += 1
        if role == "descriptors":
            scalar[reg] = "texture_ptr"  # the provenance smem.scalar_load expects of a descriptor-table base
        elif role.startswith("user:"):
            word = int(role[5:])
            scalar[reg] = ("uint", f"params[{word // 4}].{'xyzw'[word % 4]}")
        else:
            scalar[reg] = ("uint", role)
    if any(count > 1 for count in roles.values()):
        raise ValueError("An entry SGPR role is given twice")
    vsharp_words = dict(buffer_descriptors or {})
    for offset, word in vsharp_words.items():
        if offset < 0 or offset % 16 or not 0 <= word <= 60:
            raise ValueError("Invalid buffer descriptor offset or constant word")
    starts = sorted([*vsharp_words, *([constant_descriptor] if constant_descriptor is not None else [])])
    if len(set(starts)) != len(starts) or any(b < a + 16 for a, b in zip(starts, starts[1:])):
        raise ValueError("Descriptor-table entries overlap")
    if constant_descriptor is not None and (constant_descriptor < 0 or constant_descriptor % 16):
        raise ValueError("Invalid constant descriptor offset")
    users = {int(r[5:]) for r in roles if r.startswith("user:")}
    if any(w <= u < w + 4 for u in users for w in vsharp_words.values()):
        raise ValueError("A user-data word overlaps the words of a buffer V#")
    vector = {f"v{n}": ("uint", LOCAL_IDS[n]) for n in range(local_ids)}
    lines = [PREAMBLE]
    # Without a constant buffer, its offset lies below the table (-16), where no descriptor load can reach.
    st = Lowering(scalar, vector, lines, {}, [0, 0, 0, 0], -16 if constant_descriptor is None else constant_descriptor,
                  vsharp_words)
    st.stage = "compute"
    st.descriptor_high = RADV_DESCRIPTOR_HIGH
    stored = False
    for i, line in enumerate(instructions):
        if st.ended:
            raise ValueError(f"Instruction {i} follows program end: {line}")
        if line.endswith(":"):
            raise ValueError(f"Labels mean control flow, card C-3: {line}")
        for pattern, reason in LATER:
            if re.fullmatch(pattern, line):
                raise ValueError(f"Instruction {i}: {reason}: {line}")
        if (WAVE64_ONLY if wave == 32 else WAVE32_ONLY).search(line):
            raise ValueError(f"Instruction {i} names a lane mask of the other wave size (wave{wave}): {line}")
        if wave == 32 and re.fullmatch(r"v_cmpx?_\w+_e64 s\[\d+:\d+\],.*", line):
            raise ValueError(f"Instruction {i} writes a 64-bit lane mask in a wave32 program: {line}")
        if wave == 64 and re.fullmatch(r"v_cmpx?_\w+_e64 s\d+,.*", line):
            raise ValueError(f"Instruction {i} writes a 32-bit lane mask in a wave64 program: {line}")
        if stored and MEMORY_LOAD.fullmatch(line):
            # A load after a store in the same program is ordered through vscnt, which C-1 does not model.
            raise ValueError(f"Instruction {i}: a memory load after a store is not lowered in C-1: {line}")
        if line == "s_endpgm":
            st.ended = True
            continue
        if st.ex == "true":
            dispatch(st, i, line)
        else:
            ex, before = st.ex, dict(st.vector)
            dispatch(st, i, line)
            masked_writes(st, i, ex, before)
        stored = stored or line.startswith("buffer_store")
    if not st.ended:
        raise ValueError("Missing s_endpgm")
    return emit(st, numthreads)


def emit(st, numthreads):
    lines = list(st.lines)
    pos = lines.index(PREAMBLE)
    head = ["// gfx1013 compute program translated by tools/compute_aot.py (docs/design/compute-stage.md).",
            "cbuffer Constants : register(b0) { uint4 params[16]; };"]
    defs = [body for name, body in SALU_HELPERS.items() if name in st.helpers]
    if st.uses_memory:
        defs = [TITLE_LOOKUP.read_text(encoding="utf-8"), TITLE_DECLARATIONS_RW, MEMORY_HELPERS,
                *st.memory_helpers.values(), *defs]
    entry = (NUMERIC_HELPERS + f'[RootSignature("{COMPUTE_ROOT}")]\n'
             f"[numthreads({numthreads[0]}, {numthreads[1]}, {numthreads[2]})]\n"
             "void main(uint3 group_id : SV_GroupID, uint3 local_id : SV_GroupThreadID) {")
    lines[pos] = entry
    return "\n".join([*head, *lines[:pos], *defs, *lines[pos:], "}", ""])


def read_program(path):
    """Instruction text from a file: comments after ';' and a leading label with no branch to it are dropped."""
    out = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if raw.startswith("#"):
            continue
        text = " ".join(raw.split(";", 1)[0].split())
        if text and not text.startswith("("):
            out.append(text)
    if out and re.fullmatch(r"\w+:", out[0]) and not any(out[0][:-1] in t.split() for t in out[1:]):
        out = out[1:]
    return out


# Survey of a corpus compile (docs/design/compute-stage.md, "What the corpus shows").
CARD_ORDER = ("C-1", "C-2", "C-3", "C-4", "C-5", "C-6", "C-7", "C-8")
NEW_IN_C1 = {"buffer_store_dword", "buffer_store_dwordx2", "buffer_store_dwordx3", "buffer_store_dwordx4"}
FORM_CARD = (
    (r"image_\w+", "C-2"),
    (r"s_cbranch_\w+|s_branch|s_and_saveexec_\w+|s_or_saveexec_\w+|s_andn2_saveexec_\w+|v_cmpx_\w+", "C-3"),
    (r"ds_\w+|s_barrier", "C-6"),
    (r"v_readfirstlane_b32|v_readlane_b32", "C-7"),
    (r"buffer_atomic_\w+|s_bcnt1_i32_b(32|64)|s_ff1_i32_b(32|64)|v_mbcnt_\w+", "C-8"),
    (r"global_store_\w+|global_atomic_\w+", "C-5"),
)  # any other missing form is a stage-neutral form: C-4


def survey_shader(path, covered=None):
    import vertex_corpus_report as vcr  # forms and register reads, shared with the vertex survey
    header, items = vcr.read_isa(path)
    insns = [t for k, t in items if k == "insn"]
    feat = vcr.features(insns)
    mnemonics = [t.split()[0] for t in insns]
    lane32 = any(WAVE32_ONLY.search(t) for t in insns)
    lane64 = any(WAVE64_ONLY.search(t) or re.fullmatch(r"v_cmpx?_\w+_e64 s\[\d+:\d+\],.*", t) for t in insns)
    count = Counter()
    for m in mnemonics:
        for key, pattern in (("lds", r"ds_\w+"), ("barrier", r"s_barrier"), ("buffer_store", r"buffer_store_\w+"),
                             ("global_store", r"global_store_\w+"), ("image_store", r"image_store\w*"),
                             ("image_read", r"image_(load|sample)\w*"), ("atomic", r"\w+_atomic_\w+"),
                             ("readlane", r"v_read(first)?lane_b32"), ("lane_count", r"s_bcnt1\w+|s_ff1\w+|v_mbcnt\w+"),
                             ("branch", r"s_branch|s_cbranch_\w+"), ("exec_write", r"\w+saveexec\w+|v_cmpx_\w+")):
            if re.fullmatch(pattern, m):
                count[key] += 1
    out = {"instructions": len(insns), "wave": 32 if lane32 and not lane64 else 64 if lane64 and not lane32 else
           "mixed" if lane32 else "no lane-mask operand",
           "entry_vgprs": feat["inputs_vgpr"], "entry_sgprs": feat["inputs_sgpr"], "features": dict(sorted(count.items()))}
    if covered is not None:
        forms = vcr.isa_forms(insns, covered | NEW_IN_C1)
        missing = sorted(f.lstrip("!") for f in forms if f.startswith("!") or f not in covered)
        out["missing_forms"] = missing
        needs = set()
        for f in missing:
            if f in NEW_IN_C1:
                continue
            needs.add(next((card for pattern, card in FORM_CARD if re.fullmatch(pattern, f)), "C-4"))
        for key, card in (("image_store", "C-2"), ("image_read", "C-2"), ("branch", "C-3"), ("exec_write", "C-3"),
                          ("lds", "C-6"), ("barrier", "C-6"), ("readlane", "C-7"), ("atomic", "C-8"),
                          ("lane_count", "C-8"), ("global_store", "C-5")):
            if count[key]:
                needs.add(card)
        if any(v not in ("v0", "v1", "v2") for v in feat["inputs_vgpr"]):
            needs.add("refused")
        out["cards"] = sorted(needs, key=lambda c: CARD_ORDER.index(c) if c in CARD_ORDER else 99)
        out["first_card"] = max(needs, key=lambda c: CARD_ORDER.index(c) if c in CARD_ORDER else 99, default="C-1")
    return out


def survey(isa_dir, status=None):
    paths = sorted((Path(isa_dir) / "compute").glob("*.s"))
    if not paths:
        raise ValueError(f"{isa_dir}/compute has no .s files")
    covered = None
    if status is not None:
        data = json.loads(Path(status).read_text(encoding="utf-8"))
        covered = {f["name"] for f in data["gfx1013"]["forms"] if f["covered"]}
    shaders = {p.name.removesuffix(".comp.s").removesuffix(".s"): survey_shader(p, covered) for p in paths}
    report = {"shaders": len(shaders), "per_shader": shaders,
              "wave": dict(Counter(str(s["wave"]) for s in shaders.values())),
              "entry_vgprs": dict(Counter(",".join(s["entry_vgprs"]) or "none" for s in shaders.values()))}
    if covered is not None:
        first = Counter(s["first_card"] for s in shaders.values())
        total, cumulative = 0, {}
        for card in (*CARD_ORDER, "refused"):
            total += first.get(card, 0)
            cumulative[card] = {"first": first.get(card, 0), "total": total}
        report["cards"] = cumulative
        report["missing_forms"] = dict(Counter(f for s in shaders.values() for f in s["missing_forms"]).most_common())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    tr = sub.add_parser("translate")
    tr.add_argument("program", type=Path)
    tr.add_argument("--numthreads", type=int, nargs=3, required=True)
    tr.add_argument("--wave", type=int, choices=(32, 64), required=True)
    tr.add_argument("--sgpr", action="append", default=[], help="sN=ROLE: descriptors, group_id.x|y|z or user:N")
    tr.add_argument("--local-ids", type=int, default=3)
    tr.add_argument("--constant-descriptor", type=lambda s: int(s, 0))
    tr.add_argument("--buffer-descriptor", action="append", default=[], help="OFFSET=WORD")
    tr.add_argument("--output", type=Path, required=True)
    sv = sub.add_parser("survey")
    sv.add_argument("--isa", type=Path, required=True)
    sv.add_argument("--status", type=Path, default=ROOT / "site" / "status.json")
    sv.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.mode == "survey":
        report = survey(args.isa, args.status)
        text = json.dumps(report, indent=1, sort_keys=True)
        if args.json:
            args.json.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0
    dest = args.output.resolve()
    if dest.suffix.lower() != ".hlsl" or dest == args.program.resolve():
        parser.error("Choose an HLSL destination distinct from the input")
    try:
        sgprs = dict(item.split("=", 1) for item in args.sgpr)
        buffers = {int(k, 0): int(v, 0) for k, v in (item.split("=", 1) for item in args.buffer_descriptor)}
        source = lower_compute(read_program(args.program), numthreads=tuple(args.numthreads), wave=args.wave,
                               sgprs=sgprs, local_ids=args.local_ids, constant_descriptor=args.constant_descriptor,
                               buffer_descriptors=buffers)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"Translation failed: {exc}\n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
