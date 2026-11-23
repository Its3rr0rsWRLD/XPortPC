"""Survey the corpus programs of the stages after vertex, pixel and compute (docs/design/stages.md), and translate the
NGG geometry shaders with tools/geometry_aot.py.

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
s_pack_ll_b32_b16 and the NGG state in the GS body's s_bfe_u32 of bit field 0x30006). Python standard library only.
Reads no game files.
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
import vertex_corpus_translate  # noqa: E402

STAGE_REASONS = {
    "lshs": "LS+HS (tessellation control): card T-1 in docs/design/stages.md, not lowered",
    "hs": "HS without LS (tessellation control): card T-1 in docs/design/stages.md, not lowered",
    "tes": "TES (tessellation evaluation): card T-2 in docs/design/stages.md, not lowered",
    "gs_legacy": "legacy (GSVS ring) geometry shader: card G-3 in docs/design/stages.md, not lowered",
    "mesh": "mesh shader: card M-1 in docs/design/stages.md, not lowered",
    "task": "task shader: card M-2 in docs/design/stages.md, not lowered",
}


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
    if stage != "esgs":
        return stage, ngg, feats, "refused", None, STAGE_REASONS.get(stage, f"unknown stage {header!r}")
    try:
        roles = geometry_contract(program)
        vs, gs, layout = geometry_aot.lower(program, roles)
        return stage, ngg, feats, "translated", (vs, gs), f"{len(layout['primitives'])} triangles"
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
                    (out / (path.name[:-2] + ".vs.hlsl")).write_text(sources[0], encoding="ascii")
                    (out / (path.name[:-2] + ".gs.hlsl")).write_text(sources[1], encoding="ascii")
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
