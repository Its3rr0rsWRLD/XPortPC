"""Translate one gfx1013 shader for the graphics shim at pipeline-creation time (docs/design/runtime.md, section 3).

d3d12_xs.dll runs this out of process on a cache miss:

    python -B tools/pso_translate.py --stage vertex|pixel|compute --code CODE.bin --roles ROLES.json --dxc DXC
                                     --output OUT.dxil [--llvm LIBLLVM] [--hlsl OUT.hlsl]

CODE.bin is the raw code of one program (the shim cut it out of the console bytecode container). It is disassembled
with libLLVM when --llvm is given, otherwise with tools/gfx_text.py. ROLES.json is the entry contract the shim derived
from the container and the pipeline:
    vertex: {"user_sgprs": {"2": {"role": "inline", "word": 0}, ...}}    (tools/vertex_aot.py's user-SGPR map)
    pixel:  {"sgprs": {"s2": "interp"}}                                   (bindings.PixelBindings.sgprs)
    compute: {"sgprs": {"s2": "user:0", "s7": "group_id.x"}, "numthreads": [4, 1, 1], "wave": 32, "local_ids": 1}
            (tools/compute_aot.py's entry-SGPR roles; user:N is push word N)

The translated HLSL may declare only the bindings the shim fills at draw time, all in the runtime's register spaces
(RUNTIME_SPACES below; the title's own root parameters keep spaces 0 and 1 for its own registers):
    b1 title_range_count, t2 title_ranges, t0..t7 space1 title_memory, b3 push_words  (converter space 0 -> 1000,
    converter space 1 -> 1001)
    u0..u7 space1 title_memory (read-write, compute stage: the UAV half of the same table)
Any other declaration (a texture, a sampler, the b0 constant window, the b4 descriptor words, ...) is refused with the
register it needs; those bindings come with later rungs. The compute stage's constant words (params) are the push
words: its b0 window becomes b3 with the 32 push words, and a program that reads a word past them is refused.

Exit status: 0 translated (one JSON line on stdout), 1 refused (the reason on stderr, one line starting "refused:"),
2 a tool failure (disassembler library, DXC).
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

# Converter register space -> the runtime's space in the desktop root signature (src/d3d12_xs_pipeline.cpp).
RUNTIME_SPACES = {0: 1000, 1: 1001}
# The bindings the shim fills at draw time, as (register, converter space).
BOUND = {("b1", 0), ("t2", 0), ("t0", 1), ("b3", 0), ("u0", 1)}
PUSH_WORDS = 32
REGISTER = re.compile(r"register\(\s*([btsu])(\d+)\s*(?:,\s*space(\d+)\s*)?\)")


def disassemble(code, llvm):
    if llvm:
        import pixel_aot
        return pixel_aot.name_branch_targets(pixel_aot.disassemble(code, llvm, offsets=True), len(code))
    import gfx_text
    import pixel_aot
    return pixel_aot.name_branch_targets(gfx_text.decode(code), len(code))


def lower_compute(instructions, roles):
    import compute_aot
    numthreads = roles.get("numthreads")
    if not isinstance(numthreads, list) or len(numthreads) != 3:
        raise ValueError("the compute entry contract has no workgroup size")
    source = compute_aot.lower_compute(instructions, numthreads=tuple(numthreads), wave=roles.get("wave"),
                                       sgprs=dict(roles.get("sgprs", {})), local_ids=roles.get("local_ids", 3))
    # The root signature is the title's (with the converter's parameters), not the offline harness's.
    source, embedded = re.subn(r'^\[RootSignature\("[^"]*"\)\]\n', "", source, flags=re.M)
    constants = "cbuffer Constants : register(b0) { uint4 params[16]; };"
    if embedded != 1 or source.count(constants) != 1:
        raise ValueError("compute_aot output without its root signature or constant window")
    reads = re.findall(r"\bparams\[([^\]]*)\]", source.replace(constants, ""))
    if any(not re.fullmatch(r"\d+", index) or int(index) >= PUSH_WORDS // 4 for index in reads):
        raise ValueError("the program reads a constant word past the 32 push words (a descriptor-set or constant-buffer "
                         "window is not bound by the runtime yet)")
    source = source.replace(constants, f"cbuffer PushWords : register(b3) {{ uint4 params[{PUSH_WORDS // 4}]; }};")
    return source, {"numthreads": numthreads}


def lower(stage, instructions, roles):
    if stage == "compute":
        return lower_compute(instructions, roles)
    if stage == "vertex":
        import vertex_aot
        source, layout = vertex_aot.lower_with_layout(instructions,
                                                      vertex_aot.parse_role_map(roles.get("user_sgprs", {})))
        return source, {"params": layout["params"], "instance_id": layout["instance_id"]}
    from pixel_aot_ops.bindings import PixelBindings
    from pixel_aot_ops.lowering import lower as lower_pixel
    sgprs = roles.get("sgprs", {})
    if any(role != "interp" for role in sgprs.values()):
        raise ValueError("pixel entry SGPR roles other than interp (descriptor sets, push words) are not bound by the "
                         "runtime yet")
    return lower_pixel(instructions, bindings=PixelBindings(sgprs=dict(sgprs))), {}


def place_in_runtime_spaces(source):
    """Move every register the translation declares into the runtime's spaces, refusing the unbound ones."""
    def move(m):
        kind, number, space = m[1], int(m[2]), int(m[3] or 0)
        if (f"{kind}{number}", space) not in BOUND:
            raise ValueError(f"the translation declares {kind}{number}" + (f", space{space}" if space else "")
                             + ", a binding the runtime does not fill yet")
        return f"register({kind}{number}, space{RUNTIME_SPACES[space]})"
    return REGISTER.sub(move, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=("vertex", "pixel", "compute"), required=True)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--roles", type=Path, required=True)
    parser.add_argument("--dxc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--llvm")
    parser.add_argument("--hlsl", type=Path, help="Also keep the HLSL here (local debugging only)")
    args = parser.parse_args()
    try:
        code = args.code.read_bytes()
        roles = json.loads(args.roles.read_text(encoding="utf-8"))
        instructions = disassemble(code, args.llvm)
        source, layout = lower(args.stage, instructions, roles)
        source = place_in_runtime_spaces(source)
    except (ValueError, KeyError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"tool failure: {error}", file=sys.stderr)
        return 2
    if args.hlsl:
        args.hlsl.write_text(source, encoding="utf-8")
    # The compile flags of the draw checks: IEEE strictness, and for the pixel stage binary32 denormals preserved at
    # ps_6_2 (tests/pixel_aot_draws/common.py), which also covers GetAttributeAtVertex (shader model 6.1).
    # The compute stage compiles as tests/compute_aot_check.py's draws do (cs_6_0).
    profile = {"vertex": ["-T", "vs_6_0"], "compute": ["-T", "cs_6_0"]}.get(args.stage,
                                                                         ["-denorm", "preserve", "-T", "ps_6_2"])
    with tempfile.TemporaryDirectory(dir=args.output.parent) as tmp:
        hlsl = Path(tmp) / "shader.hlsl"
        hlsl.write_text(source, encoding="utf-8")
        dxil = Path(tmp) / "shader.dxil"
        result = subprocess.run([args.dxc, "-Gis", *profile, "-E", "main", "-Fo", str(dxil), str(hlsl)],
                                capture_output=True, text=True)
        if result.returncode or not dxil.exists():
            print(f"tool failure: DXC exit {result.returncode}: {result.stderr.strip()[-2000:]}", file=sys.stderr)
            return 2
        os.replace(dxil, args.output)
    print(json.dumps({"stage": args.stage, "instructions": len(instructions), **layout}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
