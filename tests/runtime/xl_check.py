"""The graphics shim's translation paths give the same cache files (docs/design/runtime.md, section 3).

    xl_check.py shim <r3_triangle> <dxc> <work-dir> [<r4_scene> [<r5_frames>]]

Runs tests/runtime/r3_triangle.cpp (and r4_scene.cpp, whose shaders read descriptor tables, and r5_frames.cpp, whose
pipelines include a compute shader) on WARP with each path
of d3d12_xs.dll and compares the cache files byte for byte (<key>.dxil, its <key>.bind sidecar, and <key>.hlsl kept
with X2W_KEEP_HLSL=1):
    process     X2W_TRANSLATE=process: one tools/pso_translate.py per shader (the path before the service), cold
    service     the default: the translator service pool (tools/pso_service.py), cold, warm (all cache hits), and
                cold again (the services' Python bytecode now cached)
    fallback    X2W_TRANSLATOR_SERVICES=0: the service unavailable, so the shim falls back to the process path, cold
    precompile  X2W_TRANSLATE=defer records every shader and fails the pipeline without translating; then
                tools/precompile_cache.py translates the manifest, and a warm run finds all in the cache
It also checks the manifest (one line per shader, inputs beside it) and that tools/pso_cache.py computes the shim's
converter fingerprint and keys. Prints each run's pipeline-creation time.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import pso_cache  # noqa: E402

SERVICE_NOTE = "translated by the translator service"
FALLBACK_NOTE = "translator service unavailable"


def r3(exe, dxc, cache, mode, **extra):
    environment = dict(os.environ, X2W_PYTHON=sys.executable, X2W_TOOLS=str(TOOLS), X2W_DXC=dxc,
                       X2W_CACHE_DIR=str(cache), X2W_KEEP_HLSL="1")
    environment.pop("X2W_TRANSLATE", None)
    environment.pop("X2W_TRANSLATOR_SERVICES", None)
    environment.update(extra)
    run = subprocess.run([exe, "warp", mode], capture_output=True, text=True, env=environment, timeout=300)
    output = run.stdout + run.stderr
    # r3_triangle and r4_scene print pso_create_ms, r5_frames compute_pso_ms and graphics_pso_ms: their sum.
    timings = re.findall(r"\bpso_create_ms=([\d.]+)|\b(?:compute|graphics)_pso_ms=([\d.]+)", output)
    return run.returncode, output, sum(float(a or b) for a, b in timings) if timings else None


def files(directory):
    return {p.name: p.read_bytes() for p in Path(directory).glob("*") if p.suffix in (".dxil", ".hlsl", ".bind")}


def check_program(exe, title, dxc, work, expect, shaders=2):
    """Every path for one program (r3_triangle, r4_scene or r5_frames, cache directory `title`, `shaders` console
    shaders); prints the pipeline times."""
    paths = {name: work / name for name in ("process", "service", "fallback", "precompile")}
    rc, out, process_ms = r3(exe, dxc, paths["process"], "cold", X2W_TRANSLATE="process")
    expect(rc == 0 and SERVICE_NOTE not in out, f"{title} process path: cold run", out)
    reference = files(paths["process"] / title)
    expect(sorted(p[-4:] for p in reference) == sorted(["bind", "dxil", "hlsl"] * shaders),
           f"{title} process path: {shaders} DXIL, HLSL and bindings sidecars")

    rc, out, service_ms = r3(exe, dxc, paths["service"], "cold")
    expect(rc == 0 and SERVICE_NOTE in out and FALLBACK_NOTE not in out, f"{title} service path: cold run", out)
    expect(files(paths["service"] / title) == reference, f"{title} service path: cache files equal the process path's")
    rc, out, warm_ms = r3(exe, dxc, paths["service"], "warm")
    expect(rc == 0, f"{title} service path: warm run", out)
    # A second launch with the cache emptied: the services start with Python's bytecode cached (X2W_CACHE_DIR\pycache).
    rc, out, again_ms = r3(exe, dxc, paths["service"], "cold")
    expect(rc == 0 and SERVICE_NOTE in out, f"{title} service path: cold run with bytecode cached", out)
    expect(files(paths["service"] / title) == reference, f"{title} service path: second cold run's cache files")

    rc, out, fallback_ms = r3(exe, dxc, paths["fallback"], "cold", X2W_TRANSLATOR_SERVICES="0")
    expect(rc == 0 and FALLBACK_NOTE in out and SERVICE_NOTE not in out, f"{title} fallback path: cold run", out)
    expect(files(paths["fallback"] / title) == reference, f"{title} fallback path: cache files equal the process path's")

    # The manifest and the keys tools/precompile_cache.py recomputes.
    directory = paths["service"] / title
    entries = pso_cache.read_manifest(directory)
    config = json.loads((directory / "translator.json").read_text(encoding="utf-8"))
    fingerprint = pso_cache.fingerprint(config["tools"], config["dxc"], config["llvm"])
    expect(fingerprint.hex() == config["fingerprint"], f"{title}: pso_cache.fingerprint equals the shim's fingerprint")
    keys = set()
    for ident, stage in entries:
        code, roles = pso_cache.read_input(directory, ident)
        expect(pso_cache.input_id(stage, roles, code) == ident, f"{title} input {ident[:16]}: id")
        keys.add(pso_cache.shader_key(fingerprint, stage, roles, code))
    expect(len(entries) == shaders and {f"{k}.dxil" for k in keys} == {n for n in reference if n.endswith(".dxil")},
           f"{title} manifest: {shaders} shaders whose recomputed keys name the cache files ({len(entries)} entries)")

    rc, out, _ = r3(exe, dxc, paths["precompile"], "cold", X2W_TRANSLATE="defer")
    directory = paths["precompile"] / title
    expect(rc != 0 and "deferred to tools/precompile_cache.py" in out and not list(directory.glob("*.dxil")),
           f"{title} defer: the pipeline is refused untranslated", out)
    expect(len(pso_cache.read_manifest(directory)) == shaders, f"{title} defer: every shader recorded")
    run = subprocess.run([sys.executable, "-B", str(TOOLS / "precompile_cache.py"), "--cache", str(directory),
                          "--keep-hlsl"], capture_output=True, text=True, timeout=300)
    print(f"{title}: {run.stdout.strip()}")
    expect(run.returncode == 0 and f" {shaders} translated" in run.stdout, f"{title} precompile: every shader translated",
           run.stdout + run.stderr)
    rc, out, precompiled_ms = r3(exe, dxc, paths["precompile"], "warm")
    expect(rc == 0, f"{title} precompile: the next launch finds every shader in the cache", out)
    expect(files(directory) == reference, f"{title} precompile: cache files equal the process path's")
    binds = [v for n, v in reference.items() if n.endswith(".bind")]
    print(f"{title}: bindings sidecars of {', '.join(str(len(b.splitlines()) - 1) for b in binds)} reads")

    def shown(ms):
        return "-" if ms is None else f"{ms:.1f}"

    print(f"{title} pipeline creation ms ({shaders} shaders): process cold {shown(process_ms)}, service cold {shown(service_ms)} "
          f"(first start, no bytecode cached) and {shown(again_ms)} (bytecode cached), "
          f"fallback cold {shown(fallback_ms)}, warm {shown(warm_ms)}, after precompile {shown(precompiled_ms)}")


def main(argv):
    if len(argv) not in (5, 6, 7) or argv[1] != "shim":
        print(__doc__, file=sys.stderr)
        return 2
    dxc, work = argv[3], Path(argv[4])
    programs = [(argv[2], "r3_triangle", 2)] + [(exe, title, count) for exe, title, count in
                                                 zip(argv[5:], ("r4_scene", "r5_frames"), (2, 3))]
    if work.exists():
        shutil.rmtree(work)
    failures = []

    def expect(condition, text, output=""):
        if not condition:
            failures.append(text)
            print(f"FAIL {text}\n{output[-3000:]}")

    for exe, title, count in programs:
        check_program(exe, title, dxc, work / title, expect, count)
    print("paths: " + ("identical" if not failures else f"{len(failures)} failures"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
