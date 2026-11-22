"""Translate a title's recorded shaders ahead of time, in parallel, so its next launch finds every one in the cache.

    python tools/precompile_cache.py <title> [--jobs N] [--cache-root DIR]
    python tools/precompile_cache.py --cache DIR [--jobs N]

d3d12_xs.dll records every console shader it sees in the title's cache directory (tools/pso_cache.py: manifest.txt and
inputs\\), and its translator configuration in translator.json. This tool reads them, recomputes each shader's key with
the converter's current fingerprint (so a converter or DXC update is handled by running it again), and translates every
shader whose <key>.dxil is missing, one process per core, each with the converter imported once and DXC loaded in
process. The DXIL is what the shim would write itself, byte for byte. Refused shaders are listed; they are refused at
pipeline creation too.

<title> is the title's cache directory name (X2W_TITLE, by default the executable's base name) under
X2W_CACHE_DIR or %LOCALAPPDATA%\\XPortPC\\cache. Exit status: 0 done (refusals included), 1 a translator failure
(DXC, disassembler library), 2 usage.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import sys
import time

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import pso_cache  # noqa: E402

_translator = None


def _start(dxc, llvm, compiler, scratch):
    global _translator
    _translator = pso_cache.Translator(dxc, llvm, compiler, scratch)


def _translate(task):
    """One task: (key, stage, code, roles, instructions or None, output directory, keep HLSL)."""
    key, stage, code, roles, instructions, directory, keep_hlsl = task
    started = time.perf_counter()
    status, message, dxil, hlsl, _ = _translator.translate(stage, code, roles, instructions)
    if status == 0:
        pso_cache.store(Path(directory) / f"{key}.dxil", dxil)
        if keep_hlsl:
            pso_cache.store(Path(directory) / f"{key}.hlsl", pso_cache.pso_translate.source_bytes(hlsl))
    return key, status, message, time.perf_counter() - started, _translator.compiler


def precompile(tasks, dxc, llvm=None, jobs=None, compiler="library", scratch=None):
    """Translate `tasks` (see _translate) on `jobs` processes. Returns [(key, status, message, seconds, compiler)]."""
    jobs = max(1, min(jobs or os.cpu_count() or 1, len(tasks) or 1))
    with ProcessPoolExecutor(max_workers=jobs, initializer=_start, initargs=(dxc, llvm, compiler, scratch)) as pool:
        return list(pool.map(_translate, tasks, chunksize=1))


def cache_directory(args):
    if args.cache:
        return Path(args.cache)
    root = args.cache_root or os.environ.get("X2W_CACHE_DIR") or \
        str(Path(os.environ.get("LOCALAPPDATA", ".")) / "XPortPC" / "cache")
    return Path(root) / args.title


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("title", nargs="?")
    parser.add_argument("--cache", help="The title's cache directory itself")
    parser.add_argument("--cache-root", help="Replaces X2W_CACHE_DIR / %%LOCALAPPDATA%%\\XPortPC\\cache")
    parser.add_argument("--jobs", type=int, help="Translator processes (default: one per core)")
    parser.add_argument("--dxc", help="Replaces translator.json's DXC (the key changes with it)")
    parser.add_argument("--keep-hlsl", action="store_true", help="Also write <key>.hlsl (local debugging)")
    args = parser.parse_args(argv)
    if bool(args.title) == bool(args.cache):
        parser.print_usage(sys.stderr)
        print("precompile: give a title or --cache", file=sys.stderr)
        return 2
    cache = cache_directory(args)
    entries = pso_cache.read_manifest(cache)
    config_path = cache / "translator.json"
    if not entries or not config_path.exists():
        print(f"precompile: no recorded shaders in {cache} (run the title once with d3d12_xs.dll)", file=sys.stderr)
        return 2
    config = json.loads(config_path.read_text(encoding="utf-8"))
    tools = config.get("tools", str(TOOLS))
    if Path(tools).resolve() != TOOLS:
        print(f"precompile: the shim's converter is {tools}; run that directory's precompile_cache.py", file=sys.stderr)
        return 2
    dxc, llvm = args.dxc or config.get("dxc", "dxc.exe"), config.get("llvm", "")
    fingerprint = pso_cache.fingerprint(tools, dxc, llvm)
    if fingerprint.hex() != config.get("fingerprint"):
        print("precompile: the converter or DXC changed since the title last ran; keys recomputed for this one")
    started = time.perf_counter()
    tasks, cached, missing = [], 0, 0
    for ident, stage in entries:
        try:
            code, roles = pso_cache.read_input(cache, ident)
        except OSError:
            missing += 1
            continue
        key = pso_cache.shader_key(fingerprint, stage, roles, code)
        if (cache / f"{key}.dxil").exists():
            cached += 1
            continue
        tasks.append((key, stage, code, roles, None, str(cache), args.keep_hlsl))
    results = precompile(tasks, dxc, llvm or None, args.jobs) if tasks else []
    seconds = time.perf_counter() - started
    counts = [sum(1 for r in results if r[1] == status) for status in range(3)]
    compilers = sorted({r[4] for r in results})
    print(f"precompile: {len(entries)} shaders recorded, {cached} already cached, {counts[0]} translated, "
          f"{counts[1]} refused, {counts[2]} failed, {missing} without inputs, in {seconds:.1f} s "
          f"({args.jobs or os.cpu_count()} processes, DXC {'/'.join(compilers) or '-'})")
    for key, status, message, _, _ in results:
        if status:
            print(f"  {key[:16]} {'refused' if status == 1 else 'failed'}: {message.splitlines()[-1] if message else ''}")
    return 1 if counts[2] else 0


if __name__ == "__main__":
    sys.exit(main())
