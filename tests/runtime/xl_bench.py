"""Throughput of shader translation for the graphics shim, and identity of its three paths (docs/design/runtime.md,
section 3).

    xl_bench.py run <dxc> <work-dir> [--processes N]
    xl_bench.py corpus [<out.json>]

`run` translates the runtime rung R3 programs (tests/runtime/r3_programs.h) and the batch in xl_batch.json (200
distinct pixel programs of the pixel_aot draw checks) four ways, and requires every shader's status, HLSL and DXIL to
be byte-identical across them (and the .bind sidecar of tools/pso_translate.py --bindings):
    process    one `python -B tools/pso_translate.py` (and dxc.exe) per shader, one after another: the shim's
               per-process path, and its only path before the translator service
    service    one tools/pso_service.py, shaders sent one after another (start-up reported apart, without and with
               Python's bytecode cached, as the shim keeps it under the cache root)
    pool       N services at once, fed from one queue, as the shim's pool runs them
    precompile tools/precompile_cache.py's process pool on N processes (start-up included)
It prints the start-up, the time per shader and the throughput of each. It fails if any output differs, if the
service's DXC is not the in-process library, or if the service is not faster per shader than the process path.

The batch programs are given as instruction text (pso_translate.py --text, the service's text flag): the shim's
LLVM-free decoder (tools/gfx_text.py) reads only the mnemonics of the R3 programs, and the draw checks' programs use
many more. `corpus` regenerates xl_batch.json: it records every program the draw families' controls lower, rewrites
their descriptor loads and samples to register moves (s_mov_b32 constants, v_mov_b32 of the interpolated
coordinates) so they need only the bindings the runtime fills (the interpolation base), keeps those the runtime's
translation accepts with distinct HLSL, and takes 200 spread over the list.
"""
import json
import os
from pathlib import Path
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLS = ROOT / "tools"
sys.path[:0] = [str(TOOLS), str(HERE)]
BATCH = HERE / "xl_batch.json"
R3_ROLES = {"vertex": '{"user_sgprs": {"2": {"role": "inline", "word": 0}, "3": {"role": "inline", "word": 1}, '
                      '"4": {"role": "inline", "word": 2}, "5": {"role": "inline", "word": 3}}}',
            "pixel": '{"sgprs": {"s2": "interp"}}'}


# --- the batch -----------------------------------------------------------------------------------------------------

def _registers(text):
    if m := re.fullmatch(r"([sv])\[(\d+):(\d+)\]", text):
        return m[1], list(range(int(m[2]), int(m[3]) + 1))
    if m := re.fullmatch(r"([sv])(\d+)", text):
        return m[1], [int(m[2])]
    return None, []


def _without_descriptors(program):
    out = []
    for i, line in enumerate(program):
        op = line.split()[0] if line.split() else ""
        if op.startswith(("s_load_", "s_buffer_load_")):
            kind, registers = _registers(line.split()[1].rstrip(","))
            if kind != "s":
                return None
            out += [f"s_mov_b32 s{r}, 0x{0x3e800000 + 0x10000 * j + 0x1000 * (i % 16):08x}"
                    for j, r in enumerate(registers)]
        elif op.startswith(("image_sample", "image_gather", "image_load")):
            kind, registers = _registers(line.split()[1].rstrip(","))
            if kind != "v":
                return None
            out += [f"v_mov_b32_e32 v{r}, v{8 + j % 2}" for j, r in enumerate(registers)]
        elif op == "s_waitcnt":
            continue
        else:
            out.append(line)
    return out


def corpus(path):
    import pso_translate
    from pixel_aot_ops import lowering
    import pixel_aot
    sys.path.insert(0, str(ROOT / "tests"))
    seen_programs, programs = set(), []

    def recorder(original):
        def lower(instructions, *args, **kwargs):
            key = tuple(instructions)
            if key not in seen_programs:
                seen_programs.add(key)
                programs.append(list(instructions))
            return original(instructions, *args, **kwargs)
        return lower

    lowering.lower = recorder(lowering.lower)
    pixel_aot.lower = recorder(pixel_aot.lower)
    import pixel_aot_draws
    from pixel_aot_draws import common
    common.pixel_aot.lower = pixel_aot.lower
    with tempfile.TemporaryDirectory() as tmp:
        for module in pixel_aot_draws.modules():
            if hasattr(module, "controls"):
                try:
                    module.controls(Path(tmp))
                except Exception as error:  # noqa: BLE001 - a family's controls are not under test here
                    print(f"controls of {module.__name__}: {error}", file=sys.stderr)
    accepted, sources = [], set()
    for program in programs:
        m0 = [m[1] for line in program if (m := re.fullmatch(r"s_mov_b32 m0, (s\d+)", line))]
        rewritten = _without_descriptors(program)
        if not m0 or not rewritten:
            continue
        roles = json.dumps({"sgprs": {m0[0]: "interp"}})
        for candidate in (program, rewritten):
            try:
                source = pso_translate.translate("pixel", None, json.loads(roles), instructions=candidate)[0]
            except (ValueError, KeyError):
                continue
            if source not in sources:
                sources.add(source)
                accepted.append({"roles": roles, "text": "\n".join(candidate)})
            break
    step = len(accepted) / 200
    chosen = [accepted[int(i * step)] for i in range(200)] if len(accepted) >= 200 else accepted
    Path(path).write_text(json.dumps({"source": "tests/runtime/xl_bench.py corpus", "programs": chosen}, indent=0)
                          + "\n", encoding="utf-8")
    print(f"{len(programs)} programs recorded, {len(accepted)} accepted with distinct HLSL, {len(chosen)} written")
    return 0


# --- the paths -------------------------------------------------------------------------------------------------------

class Shader:
    def __init__(self, name, stage, roles, code=None, text=None):
        self.name, self.stage, self.roles, self.code, self.text = name, stage, roles, code, text

    @property
    def payload(self):
        return self.code if self.text is None else self.text.encode("utf-8")


def shaders():
    import r3_programs_check
    programs = r3_programs_check.committed()
    out = [Shader("r3_vs", "vertex", R3_ROLES["vertex"], code=programs["r3_vs"]),
           Shader("r3_ps", "pixel", R3_ROLES["pixel"], code=programs["r3_ps"])]
    batch = json.loads(BATCH.read_text(encoding="utf-8"))["programs"]
    out += [Shader(f"batch{i:03d}", "pixel", p["roles"], text=p["text"]) for i, p in enumerate(batch)]
    return out


def by_process(dxc, items, work):
    """[(status, message, dxil, hlsl)] and the seconds of each, from one pso_translate.py process per shader."""
    work.mkdir(parents=True, exist_ok=True)
    results, seconds = [], []
    for i, s in enumerate(items):
        base = work / f"{i:03d}"
        (base.with_suffix(".roles.json")).write_text(s.roles, encoding="utf-8")
        source = base.with_suffix(".code") if s.text is None else base.with_suffix(".txt")
        if s.text is None:
            source.write_bytes(s.code)
        else:
            source.write_text(s.text + "\n", encoding="utf-8")
        output, hlsl, bind = base.with_suffix(".dxil"), base.with_suffix(".hlsl"), base.with_suffix(".bind")
        for stale in (output, hlsl, bind):
            stale.unlink(missing_ok=True)
        command = [sys.executable, "-B", str(TOOLS / "pso_translate.py"), "--stage", s.stage,
                   "--text" if s.text is not None else "--code", str(source), "--roles",
                   str(base.with_suffix(".roles.json")), "--dxc", dxc, "--output", str(output), "--hlsl", str(hlsl),
                   "--bindings", str(bind)]
        started = time.perf_counter()
        run = subprocess.run(command, capture_output=True, text=True)
        seconds.append(time.perf_counter() - started)
        status = run.returncode if run.returncode in (0, 1) else 2
        results.append((status, "", output.read_bytes() if status == 0 else b"",
                        hlsl.read_bytes() if status == 0 else b"", bind.read_bytes() if status == 0 else b""))
    return results, seconds


class Service:
    """One tools/pso_service.py, as the shim drives it (src/d3d12_xs_translator.cpp)."""

    def __init__(self, dxc, pycache):
        self.started = time.perf_counter()
        # As the shim starts it: bytecode cached outside the converter's directory.
        self.process = subprocess.Popen([sys.executable, "-X", f"pycache_prefix={pycache}", str(TOOLS / "pso_service.py"),
                                         "--dxc", dxc],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def frame(self):
        head = self.process.stdout.read(4)
        if len(head) != 4:
            raise RuntimeError("the service closed its output")
        size, = struct.unpack("<I", head)
        return self.process.stdout.read(size)

    def ready(self):
        data = self.frame()
        if data[:4] != b"X2WT":
            raise RuntimeError("no ready frame")
        _, compiler, size = struct.unpack_from("<III", data, 4)
        self.compiler = ("library", "process")[compiler]
        self.why = data[16:16 + size].decode("utf-8")
        self.ready_seconds = time.perf_counter() - self.started
        return self

    def translate(self, s):
        roles, payload = s.roles.encode("utf-8"), s.payload
        flags = 1 | (2 if s.text is not None else 0)
        body = struct.pack("<III", ("vertex", "pixel", "compute").index(s.stage), flags, len(roles)) + roles + \
            struct.pack("<I", len(payload)) + payload
        self.process.stdin.write(struct.pack("<I", len(body)) + body)
        self.process.stdin.flush()
        data, at, fields = self.frame(), 8, []
        status, _ = struct.unpack_from("<II", data, 0)
        for _ in range(4):
            size, = struct.unpack_from("<I", data, at)
            fields.append(data[at + 4:at + 4 + size])
            at += 4 + size
        message, dxil, hlsl, bindings = fields
        return status, message.decode("utf-8", "replace"), dxil, hlsl, bindings

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=60)


def by_service(dxc, items, pycache):
    service = Service(dxc, pycache).ready()
    results, seconds = [], []
    for s in items:
        started = time.perf_counter()
        results.append(service.translate(s))
        seconds.append(time.perf_counter() - started)
    service.close()
    return results, seconds, service


def by_pool(dxc, items, count, pycache):
    started = time.perf_counter()
    services = [Service(dxc, pycache) for _ in range(count)]
    work = queue.Queue()
    for i, s in enumerate(items):
        work.put((i, s))
    results = [None] * len(items)

    def serve(service):
        service.ready()
        while True:
            try:
                i, s = work.get_nowait()
            except queue.Empty:
                return
            results[i] = service.translate(s)

    threads = [threading.Thread(target=serve, args=(service,)) for service in services]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for service in services:
        service.close()
    return results, time.perf_counter() - started, services


def by_precompile(dxc, items, count, work):
    import precompile_cache
    work.mkdir(parents=True, exist_ok=True)
    tasks = [(f"{i:03d}", s.stage, s.code, s.roles, s.text.splitlines() if s.text is not None else None, str(work), True)
             for i, s in enumerate(items)]
    started = time.perf_counter()
    done = precompile_cache.precompile(tasks, dxc, jobs=count)
    seconds = time.perf_counter() - started
    results = []
    for key, status, message, _, _ in done:
        dxil, hlsl, bind = work / f"{key}.dxil", work / f"{key}.hlsl", work / f"{key}.bind"
        results.append((status, message, dxil.read_bytes() if status == 0 else b"",
                        hlsl.read_bytes() if status == 0 else b"", bind.read_bytes() if status == 0 else b""))
    return results, seconds, sorted({d[4] for d in done})


def run(dxc, work, processes):
    work = Path(work)
    items = shaders()
    r3, batch = items[:2], items[2:]
    print(f"shaders: {len(r3)} R3 programs, {len(batch)} batch programs; {processes} processes for pool/precompile")
    process_results, process_seconds = by_process(dxc, items, work / "process")
    pycache = work / "pycache"
    if pycache.exists():
        shutil.rmtree(pycache)
    service_results, service_seconds, service = by_service(dxc, items, pycache)
    again = Service(dxc, pycache).ready()
    again.close()
    pool_results, pool_seconds, pool = by_pool(dxc, items, processes, pycache)
    pre_results, pre_seconds, pre_compilers = by_precompile(dxc, items, processes, work / "precompile")

    failures = []
    for i, s in enumerate(items):
        reference = process_results[i]
        for path, results in (("service", service_results), ("pool", pool_results), ("precompile", pre_results)):
            got = results[i]
            if got[0] != reference[0]:
                failures.append(f"{s.name}: {path} status {got[0]} ({got[1][-200:]}), process {reference[0]}")
            elif got[2] != reference[2]:
                failures.append(f"{s.name}: {path} DXIL differs ({len(got[2])} bytes, process {len(reference[2])})")
            elif got[3] != reference[3]:
                failures.append(f"{s.name}: {path} HLSL differs")
            elif got[4] != reference[4]:
                failures.append(f"{s.name}: {path} bindings sidecar differs")
    statuses = [r[0] for r in process_results]
    print(f"statuses (process path): {statuses.count(0)} translated, {statuses.count(1)} refused, "
          f"{statuses.count(2)} tool failures")

    def ms(values):
        return 1000 * sum(values) / len(values)

    n = len(batch)
    lines = [
        ("process", 0.0, ms(process_seconds[:2]), ms(process_seconds[2:]), sum(process_seconds[2:])),
        ("service", service.ready_seconds, ms(service_seconds[:2]), ms(service_seconds[2:]), sum(service_seconds[2:])),
    ]
    print(f"{'path':<11} {'start-up s':>10} {'R3 ms/shader':>13} {'batch ms/shader':>16} {'batch s':>8} {'shaders/s':>10}")
    for name, startup, r3_ms, batch_ms, total in lines:
        print(f"{name:<11} {startup:>10.3f} {r3_ms:>13.1f} {batch_ms:>16.1f} {total:>8.2f} {n / total:>10.1f}")
    print(f"pool       {processes} services: {len(items)} shaders in {pool_seconds:.2f} s wall, start-up included "
          f"({len(items) / pool_seconds:.1f} shaders/s, {1000 * pool_seconds / len(items):.1f} ms/shader)")
    print(f"precompile {processes} processes: {len(items)} shaders in {pre_seconds:.2f} s wall, start-up included "
          f"({len(items) / pre_seconds:.1f} shaders/s, {1000 * pre_seconds / len(items):.1f} ms/shader), "
          f"DXC {'/'.join(pre_compilers)}")
    print(f"service start-up: {service.ready_seconds:.3f} s with no bytecode cached, {again.ready_seconds:.3f} s with it")
    print(f"service DXC: {service.compiler}" + (f" ({service.why})" if service.why else ""))
    if service.compiler != "library" or any(p.compiler != "library" for p in pool):
        failures.append("the service did not load DXC's library")
    if ms(service_seconds[2:]) >= ms(process_seconds[2:]):
        failures.append("the service is not faster per shader than the process path")
    for failure in failures[:20]:
        print(f"FAIL {failure}")
    print("identical: " + ("yes, every status, HLSL, DXIL and bindings sidecar" if not failures else f"no ({len(failures)} problems)"))
    return 1 if failures else 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "corpus":
        return corpus(argv[2] if len(argv) > 2 else BATCH)
    if len(argv) >= 4 and argv[1] == "run":
        processes = int(argv[argv.index("--processes") + 1]) if "--processes" in argv else \
            max(1, min(8, (os.cpu_count() or 2) - 1))
        return run(argv[2], argv[3], processes)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
