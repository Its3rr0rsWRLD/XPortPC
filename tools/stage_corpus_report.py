"""Survey the corpus programs of the stages after vertex, pixel and compute (docs/design/stages.md), and translate the
NGG geometry shaders with tools/geometry_aot.py and the tessellation programs with tools/tess_aot.py.

Usage:
    python tools/stage_corpus_report.py [--isa DIR ...] [--summary FILE] [--hlsl-dir DIR]

Each DIR holds RADV dumps in DIR/other/*.s or DIR/*.s (tools/shader_corpus_build/build_corpus.py; the default,
tests/corpus/isa/stages, holds the committed NGG build). The first line of a dump names the hardware stage RADV compiled the API stage as:
"Vertex Shader as ES + Geometry Shader" (an ES+GS wave), "Geometry Shader" (the GS half of a pipeline the builder
made without a vertex shader), "Vertex Shader as LS + Tessellation Control Shader" (an LS+HS wave),
"Tessellation Control Shader" (the HS half alone), "Tessellation Evaluation Shader as ESGS" or "as VS", and
"Mesh Shader" / "Task Shader". For each program the report prints the hardware stage, whether it runs as NGG, the
cross-stage I/O it does (LDS reads and writes, ring stores, s_sendmsg kinds, exports) and the translation result:
translated by geometry_aot, or the first refusal reason. Stages with no lowering get the reason their card gives.

Binding contract for an ES+GS wave: the user-SGPR role map tools/vertex_corpus_translate.py reads off a vertex
program, applied to the two halves, plus the two NGG SGPRs the frame names (the LDS layout in the GS head's
s_pack_ll_b32_b16 and the NGG state in the GS body's s_bfe_u32 of bit field 0x30006). Binding contract and pipeline state for the tessellation programs: the role map read off the LS/HS or TES body the
same way (the LS half's vertex id in v2, RADV's tcs_offchip_layout SGPR where the HS reads the LS output count from it
with s_bfe_u32 ..., 0x60011), and the pipeline state of TESS_PIPELINES: domain, spacing and winding from each
pipeline's public GLSL (the evaluation shader's input layout qualifier; Vulkan's defaults, equal spacing and ccw, where
it names none), the patch sizes from the control shader, the ring attribute stride the dumps' offsets show (1024 bytes:
RADV's align(patch count * vertices * 16, 256) for the patch count it chose), and the ring and LDS slot counts the two
halves use. Vulkan's cw with the default upper-left domain origin is the hardware's OUTPUT_TRIANGLE_CW
(radv_cmd_buffer.c radv_emit_tess_domain_origin_state), which tools/tess_aot.py lowers to triangle_cw. Python
standard library only. Reads no game files.
"""
import argparse
from collections import Counter
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import corpus_translate  # noqa: E402
import geometry_aot  # noqa: E402
import tess_aot  # noqa: E402
import vertex_aot  # noqa: E402
import vertex_corpus_translate  # noqa: E402

STAGE_REASONS = {
    "gs_legacy": "legacy (GSVS ring) geometry shader: card G-3 in docs/design/stages.md, not lowered",
    "mesh": "mesh shader: card M-1 in docs/design/stages.md, not lowered",
    "task": "task shader: card M-2 in docs/design/stages.md, not lowered",
}


# Pipeline state of the corpus's tessellation pipelines, by the file-name stem the control and evaluation programs share
# (the GLSL layout qualifier is quoted from each source at the commit tests/corpus/README.md names).
TESS_PIPELINES = {
    # "layout (triangles) in;": equal spacing and ccw by default.
    "sascha__pipelinestatistics__scene": {"domain": "tri", "partitioning": "integer", "topology": "triangle_ccw",
                                          "output_control_points": 3, "vertex_slots": 10},
    # "layout (triangles, fractional_odd_spacing, cw) in;"
    "sascha__tessellation__passthrough": {"domain": "tri", "partitioning": "fractional_odd", "topology": "triangle_cw",
                                          "output_control_points": 3, "vertex_slots": 1, "ls_slots": 1},
    "sascha__tessellation__pntriangles": {"domain": "tri", "partitioning": "fractional_odd", "topology": "triangle_cw",
                                          "output_control_points": 3, "vertex_slots": 7, "ls_slots": 6},
    # "layout(triangles, equal_spacing, cw) in;"
    "sascha__displacement__displacement": {"domain": "tri", "partitioning": "integer", "topology": "triangle_cw",
                                           "output_control_points": 3, "vertex_slots": 7, "ls_slots": 6},
    "vksamples__extended_dynamic_state2__glsl__tess": {"domain": "tri", "partitioning": "integer",
                                                       "topology": "triangle_cw", "output_control_points": 3,
                                                       "vertex_slots": 1},
    "vksamples__patch_control_points__glsl__tess": {"domain": "tri", "partitioning": "integer",
                                                    "topology": "triangle_cw", "output_control_points": 3,
                                                    "vertex_slots": 4},
    # "layout(quads, equal_spacing, cw) in;"
    "sascha__terraintessellation__terrain": {"domain": "quad", "partitioning": "integer", "topology": "triangle_cw",
                                             "output_control_points": 4, "vertex_slots": 4},
    "vksamples__terrain_tessellation__glsl__terrain": {"domain": "quad", "partitioning": "integer",
                                                       "topology": "triangle_cw", "output_control_points": 4,
                                                       "vertex_slots": 4},
}
CORPUS_ATTR_STRIDE = 1024


def tess_state(name):
    stem = re.sub(r"\.(tesc|tese|vert)\.s$", "", name)
    state = dict(TESS_PIPELINES[stem])
    state.setdefault("input_control_points", state["output_control_points"])
    state["attr_stride"] = CORPUS_ATTR_STRIDE
    return state


def tess_contract(program, stage):
    """The role map of a tessellation program (see the module docstring)."""
    lines = [line for line in vertex_aot._clean(program) if not vertex_aot._is_label(line)]
    if stage == "tes":
        roles, _ = vertex_corpus_translate.binding_contract(program)
    else:
        roles, _ = vertex_corpus_translate.binding_contract(["s_setprio 3", *lines], stage="ls")
    roles = {n: r for n, r in roles.items() if n >= vertex_aot.NGG_FIRST_USER_SGPR}
    for line in lines:
        if m := re.fullmatch(r"s_bfe_u32 s\d+, s(\d+), 0x60011", line):
            roles[int(m[1])] = ("tcs_offchip_layout",)
    return roles


def classify(header, lines):
    """(hardware stage, ngg) from the dump header and its code."""
    ngg = any("MSG_GS_ALLOC_REQ" in line for line in lines)
    if header.startswith("Vertex Shader as ES + Geometry Shader"):
        return ("esgs" if ngg else "gs_legacy"), ngg
    if header.startswith("Geometry Shader"):
        return ("esgs" if ngg else "gs_legacy"), ngg
    if header.startswith("Vertex Shader as LS"):
        return "lshs", ngg
    if header.startswith("Tessellation Control"):
        return "hs", ngg
    if header.startswith("Tessellation Evaluation"):
        return "tes", ngg
    if header.startswith("Mesh"):
        return "mesh", ngg
    if header.startswith("Task"):
        return "task", ngg
    return "unknown", ngg


def io_features(lines):
    counts = Counter()
    for line in lines:
        head = line.split()[0] if line.split() else ""
        if head.startswith("ds_") and " gds" in line:
            counts["gds"] += 1
        elif head.startswith("ds_read"):
            counts["lds_read"] += 1
        elif head.startswith("ds_write"):
            counts["lds_write"] += 1
        elif head.startswith(("buffer_store", "tbuffer_store", "global_store")):
            counts["store"] += 1
        elif head == "s_sendmsg":
            counts["msg_" + re.sub(r"\W+", "_", line.split(None, 1)[1]).strip("_")] += 1
        elif head == "exp":
            counts["exp_" + line.split()[1].rstrip(",")] += 1
        elif head.startswith(("v_readlane", "v_permlane", "v_mbcnt", "s_bcnt")):
            counts["lane"] += 1
    return counts


def geometry_contract(program):
    """The role map for an NGG ES+GS program (see the module docstring)."""
    es, gs, frame = geometry_aot.split_frame(program)
    query = next((m[1] for line in gs if (m := re.fullmatch(r"s_bfe_u32 (s\d+), \1, 0x30006", line))), None)
    drop = {frame["lds"]} | ({query} if query else set())
    body = [line for line in es + gs if not any(re.search(rf"\b{r}\b", line) for r in drop)]
    roles, _ = vertex_corpus_translate.binding_contract(["s_setprio 3", *body, "s_endpgm"], stage="ngg")
    roles = {n: r for n, r in roles.items() if f"s{n}" not in drop}
    roles[int(frame["lds"][1:])] = ("ngg_lds_layout",)
    if query:
        roles[int(query[1:])] = ("ngg_query_state",)
    return roles


def translate(path):
    program = corpus_translate.read_dump(path)
    header = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
    lines = [line for line in program if line and not line.endswith(":")]
    stage, ngg = classify(header, lines)
    feats = io_features(lines)
    if stage in ("tes", "lshs", "hs"):
        try:
            state = tess_state(path.name)
            roles = tess_contract(program, stage)
            if stage == "tes":
                ds, layout = tess_aot.lower_tes(program, roles, state)
                return stage, ngg, feats, "translated", {"ds": ds}, f"domain shader, params {layout['params']}"
            vs, hs, layout = tess_aot.lower_lshs(program, roles, state)
            sources = {"hs": hs, **({"vs": vs} if vs else {})}
            detail = f"{'vertex and ' if vs else ''}hull shader, inputs {layout['inputs']}" + \
                (", vote folded" if layout["vote"] else "")
            return stage, ngg, feats, "translated", sources, detail
        except Exception as exc:  # noqa: BLE001 - a non-ValueError is a translator crash and is marked so
            reason = str(exc) if isinstance(exc, ValueError) else f"crash {type(exc).__name__}: {exc}"
            return stage, ngg, feats, "refused", None, re.sub(r"'[^']*'", "'...'", reason)
    if stage != "esgs":
        return stage, ngg, feats, "refused", None, STAGE_REASONS.get(stage, f"unknown stage {header!r}")
    try:
        roles = geometry_contract(program)
        vs, gs, layout = geometry_aot.lower(program, roles)
        return stage, ngg, feats, "translated", {"vs": vs, "gs": gs}, f"{len(layout['primitives'])} triangles"
    except Exception as exc:  # noqa: BLE001 - a non-ValueError is a translator crash and is marked so
        reason = str(exc) if isinstance(exc, ValueError) else f"crash {type(exc).__name__}: {exc}"
        return stage, ngg, feats, "refused", None, re.sub(r"'[^']*'", "'...'", reason)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--isa", type=Path, action="append")
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--hlsl-dir", type=Path)
    args = ap.parse_args(argv)
    rows = []
    for isa in args.isa or [ROOT / "tests" / "corpus" / "isa" / "stages"]:
        paths = sorted((isa / "other").glob("*.s")) or sorted(isa.glob("*.s"))
        if not paths:
            print(f"stage_corpus_report: {isa} has no .s files", file=sys.stderr)
            return 2
        stages, reasons = Counter(), Counter()
        done = 0
        for path in paths:
            stage, ngg, feats, status, sources, detail = translate(path)
            stages[(stage, ngg)] += 1
            io = " ".join(f"{k}={v}" for k, v in sorted(feats.items()))
            rows.append((isa.name, path.name, stage, "ngg" if ngg else "legacy", status, detail, io))
            if sources:
                done += 1
                if args.hlsl_dir:
                    out = args.hlsl_dir / isa.name
                    out.mkdir(parents=True, exist_ok=True)
                    for kind, source in sources.items():
                        (out / (path.name[:-2] + f".{kind}.hlsl")).write_text(source, encoding="ascii")
            else:
                reasons[detail] += 1
        print(f"{isa}: {done} of {len(paths)} programs translate")
        for (stage, ngg), count in sorted(stages.items()):
            print(f"  stage {stage:9s} {'ngg' if ngg else 'legacy':6s} {count:3d}")
        for reason, count in reasons.most_common():
            print(f"  {count:3d}  {reason[:160]}")
    if args.summary:
        args.summary.write_text("".join("\t".join(map(str, row)) + "\n" for row in rows), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
