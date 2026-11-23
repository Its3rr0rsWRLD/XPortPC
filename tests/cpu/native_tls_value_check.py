"""Compare implicit TLS values seen in TLS callbacks on the main and worker threads.

The tls_value fixture keeps one __declspec(thread) int (7) and reports it in
the sink's reserved slot from both its TLS callback (caller 1) and its entry
point (caller 2). Each case runs in a fresh child process: load or map the
image, read the value on the main thread, set it to 11 there, run one worker
thread whose start routine returns its own TLS value, join it with a timeout,
read the main value again, restore it, release, and report the sink events
with raw thread IDs translated to semantic identities ("main"/"worker") so two
processes can be compared without comparing raw OS thread IDs.

Expected (Refs #165): the Windows loader initializes implicit TLS and runs the
callbacks on both threads with value 7, the worker starts from the template
(7) while the main thread keeps 11. pe_map gives the image its TLS data through
a carrier DLL (tools/pe_map.cpp, attach_tls_data) and must report exactly the
same values and events. The empty-template control (tls_route) must map under
both loaders. Wrong-result control: a copy whose template value is 9 must read
9 everywhere under both loaders, so the comparison follows the template. A
worker that times out, a missing callback, or an unexpected value fails the
test.
"""

import argparse
from collections import Counter
import ctypes
import json
import shutil
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

import pefile

from native_map_check import Mapper
from native_tls_check import Call, load_sink

TLS, ENTRY = 1, 2
ATTACH, DETACH, THREAD_ATTACH, THREAD_DETACH = 1, 0, 2, 3
TLS_VALUE = 7
MAIN_VALUE = 11
CHANGED_VALUE = 9
WAIT_MS = 10000  # shorter than the harness timeout so the exit path is observed
TIMEOUT = 60


def translate(calls, module, main_id, worker_id):
    """(caller, reason, semantic thread, value) for this module's events only."""
    out = []
    for call in calls:
        if call.module != module:
            continue
        if call.thread == main_id:
            who = "main"
        elif call.thread == worker_id:
            who = "worker"
        else:
            continue  # unrelated pool threads; same rule as native_tls_check
        out.append([call.caller, call.reason, who, call.reserved])
    return out


def run(target, image, sink_path, mapper_path):
    """Child process: one load, one main read, one worker probe, release."""
    sink = load_sink(sink_path)
    sink.sink_clear()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentThreadId.argtypes = []
    kernel.GetCurrentThreadId.restype = ctypes.c_uint32
    main_id = kernel.GetCurrentThreadId()
    worker_id = ctypes.c_uint32(0)

    module, status, detail = None, None, None
    if target == "native":
        kernel.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
        kernel.LoadLibraryW.restype = ctypes.c_void_p
        kernel.FreeLibrary.argtypes = [ctypes.c_void_p]
        module = kernel.LoadLibraryW(str(image))
        if not module:
            print(json.dumps({"failure": ctypes.get_last_error(), "events": [], "main": None}))
            return
        release = lambda: kernel.FreeLibrary(module)  # noqa: E731
    else:
        mapper = Mapper(mapper_path)
        # The fixture is built with the static C runtime, which imports kernel32.
        bindings = {Path(sink_path).name.casefold(): sink, "kernel32.dll": ctypes.WinDLL("kernel32")}
        module, status, detail, _ = mapper(Path(image), bindings)
        if not module:
            print(json.dumps({"failure": [status, detail], "events": [], "main": None}))
            return
        release = lambda: mapper.release(module)  # noqa: E731

    # Resolve the probe exports from the loaded/mapped image itself.
    if target == "native":
        kernel.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        kernel.GetProcAddress.restype = ctypes.c_void_p
        read_addr = kernel.GetProcAddress(module, b"tls_value_read")
        probe_addr = kernel.GetProcAddress(module, b"tls_value_probe")
    else:
        mapper = Mapper(mapper_path)
        read_addr = mapper.export(module, b"tls_value_read")
        probe_addr = mapper.export(module, b"tls_value_probe")
    if not read_addr or not probe_addr:
        print(json.dumps({"failure": "missing export", "events": [], "main": None}))
        release()
        return
    if target == "native":
        set_addr = kernel.GetProcAddress(module, b"tls_value_set")
    else:
        set_addr = mapper.export(module, b"tls_value_set")
    read_value = ctypes.CFUNCTYPE(ctypes.c_int)(read_addr)
    set_value = ctypes.CFUNCTYPE(None, ctypes.c_int)(set_addr)
    main_value = read_value()
    # The worker must start from the template, not from this thread's value.
    set_value(MAIN_VALUE)

    kernel.CreateThread.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_uint32,
                                    ctypes.POINTER(ctypes.c_uint32)]
    kernel.CreateThread.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.GetExitCodeThread.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel.GetExitCodeThread.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateThread(None, 0, probe_addr, None, 0, ctypes.byref(worker_id))
    if not handle:
        print(json.dumps({"failure": "create-thread", "events": [], "main": main_value}))
        release()
        return
    waited = kernel.WaitForSingleObject(handle, WAIT_MS)
    worker_value = ctypes.c_uint32(0xDEAD)
    ok = waited == 0 and bool(kernel.GetExitCodeThread(handle, ctypes.byref(worker_value)))
    kernel.CloseHandle(handle)
    if not ok:
        # The worker may still be executing code from this module.
        print(json.dumps({"failure": "worker-wait", "events": [], "main": main_value,
                          "worker": None}))
        return
    main_after = read_value()
    set_value(main_value)  # the process detach below reads the template value again
    buffer = (Call * 64)()
    count = sink.sink_read(buffer, len(buffer))
    events = translate(buffer[:count], module, main_id, worker_id.value)
    sink.sink_clear()
    release()
    # Detach events stay in the sink after release (the sink outlives the image).
    buffer = (Call * 64)()
    count = sink.sink_read(buffer, len(buffer))
    detach = translate(buffer[:count], module, main_id, worker_id.value)
    print(json.dumps({"failure": None,
                      "events": events, "detach": detach,
                      "main": main_value, "main_after": main_after, "worker": worker_value.value}))


def run_control(target, image, sink_path, mapper_path):
    """Child process for the empty-template control: load, observe attach, release.

    The control fixture (tls_route) exports no tls_value_* symbols, so the
    value-probe run() above cannot be reused here. Success is a clean load
    with the TLS callback and entry point each observed once with
    DLL_PROCESS_ATTACH; any load failure is reported, never masked."""
    sink = load_sink(sink_path)
    sink.sink_clear()
    module = None
    if target == "native":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
        kernel.LoadLibraryW.restype = ctypes.c_void_p
        kernel.FreeLibrary.argtypes = [ctypes.c_void_p]
        module = kernel.LoadLibraryW(str(image))
        if not module:
            print(json.dumps({"failure": ctypes.get_last_error()}))
            return
        release = lambda: kernel.FreeLibrary(module)  # noqa: E731
    else:
        mapper = Mapper(mapper_path)
        module, status, detail, _ = mapper(Path(image), {Path(sink_path).name.casefold(): sink})
        if not module:
            print(json.dumps({"failure": [status, detail]}))
            return
        release = lambda: mapper.release(module)  # noqa: E731
    buffer = (Call * 64)()
    count = sink.sink_read(buffer, len(buffer))
    attach = [[c.caller, c.reason, "module" if c.module == module else hex(c.module), c.reserved]
              for c in buffer[:count] if c.reason == ATTACH]
    release()
    print(json.dumps({"failure": None, "attach": attach}))


def child(target, image, sink, mapper, control=False):
    args = ["--run-control" if control else "--run", target,
            str(image), str(sink), str(mapper)]
    result = subprocess.run([sys.executable, "-B", __file__] + args,
                            capture_output=True, text=True, timeout=TIMEOUT)
    if result.returncode:
        raise AssertionError(f"{target} {Path(image).name}: child exited "
                             f"{result.returncode:#x}: {result.stderr}")
    return json.loads(result.stdout)


def expect_values(label, observed, value):
    """Every callback and entry-point event on both threads, and the worker, read value."""
    if observed["failure"] is not None:
        raise AssertionError(f"{label} failed: {observed}")
    if observed["main"] != value or observed["worker"] != value or observed["main_after"] != MAIN_VALUE:
        raise AssertionError(f"{label}: thread-local values differ from {value} (main after {MAIN_VALUE}): "
                             f"{observed}")
    expected_events = Counter(
        (caller, reason, thread, value)
        for caller in (TLS, ENTRY)
        for reason, thread in ((ATTACH, "main"), (THREAD_ATTACH, "worker"),
                               (THREAD_DETACH, "worker"))
    )
    expected_detach = Counter((caller, DETACH, "main", value) for caller in (TLS, ENTRY))
    for seen, expected in ((observed["events"], expected_events), (observed["detach"], expected_detach)):
        if Counter(map(tuple, seen)) != expected:
            raise AssertionError(f"{label}: expected {expected}, got {seen}")


def changed_template(image, folder):
    """A copy of image whose TLS template holds CHANGED_VALUE where it held TLS_VALUE."""
    data = bytearray(Path(image).read_bytes())
    with pefile.PE(str(image)) as pe:
        tls = pe.DIRECTORY_ENTRY_TLS.struct
        start = pe.get_offset_from_rva(tls.StartAddressOfRawData - pe.OPTIONAL_HEADER.ImageBase)
        size = tls.EndAddressOfRawData - tls.StartAddressOfRawData
    template = bytes(data[start:start + size])
    needle = struct.pack("<i", TLS_VALUE)
    offsets = [i for i in range(0, size - 3, 4) if template[i:i + 4] == needle]
    if len(offsets) != 1:
        raise AssertionError(f"template of {size} bytes holds {len(offsets)} aligned copies of {TLS_VALUE}")
    data[start + offsets[0]:start + offsets[0] + 4] = struct.pack("<i", CHANGED_VALUE)
    copy = Path(folder) / Path(image).name
    copy.write_bytes(data)
    return copy


def check(value_image, control_image, sink, mapper):
    # Control first: the empty-template fixture must load under both loaders,
    # proving the harness itself can map and observe thread notifications.
    for target in ("native", "mapped"):
        observed = child(target, control_image, sink, mapper, control=True)
        if observed["failure"] is not None:
            raise AssertionError(f"control {target}: failed to load: {observed}")
        callers = [c for c, _, _, _ in observed["attach"]]
        if TLS not in callers or ENTRY not in callers:
            raise AssertionError(f"control {target}: missing attach callback: {observed}")
    print("control: empty-template TLS fixture loads under Windows and pe_map")

    native = child("native", value_image, sink, mapper)
    mapped = child("mapped", value_image, sink, mapper)
    for label, observed in (("native", native), ("mapped", mapped)):
        print(f"{label}: main={observed['main']} main_after={observed.get('main_after')} "
              f"worker={observed.get('worker')} events={observed['events']} detach={observed.get('detach')}")
    expect_values("native", native, TLS_VALUE)
    expect_values("mapped", mapped, TLS_VALUE)
    if Counter(map(tuple, native["events"])) != Counter(map(tuple, mapped["events"])):
        raise AssertionError(f"events differ: native {native} mapped {mapped}")

    # Determinism: a second mapping in a fresh process gives the same observations.
    again = child("mapped", value_image, sink, mapper)
    expect_values("mapped repeat", again, TLS_VALUE)

    # Wrong-result control: the values follow the template under both loaders.
    with TemporaryDirectory() as folder:
        changed = changed_template(value_image, folder)
        shutil.copy(sink, Path(folder) / Path(sink).name)
        for target in ("native", "mapped"):
            observed = child(target, changed, sink, mapper)
            expect_values(f"changed template {target}", observed, CHANGED_VALUE)
            try:
                expect_values("changed template against the original", observed, TLS_VALUE)
            except AssertionError:
                pass
            else:
                raise AssertionError(f"changed template {target}: the check accepted {observed}")
    print(f"TLS callbacks and entry points on main and worker threads read {TLS_VALUE} under Windows and "
          f"pe_map, the worker starts from the template while main keeps {MAIN_VALUE}, and a template of "
          f"{CHANGED_VALUE} reads {CHANGED_VALUE} under both")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--run", "--run-control"):
        (run_control if sys.argv[1] == "--run-control" else run)(*sys.argv[2:6])
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        for arg in ("value", "control", "sink", "mapper"):
            parser.add_argument(arg, type=Path)
        args = parser.parse_args()
        check(args.value, args.control, args.sink, args.mapper)
