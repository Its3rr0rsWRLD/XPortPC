"""Start a source-built EXE with pe_map and compare its exit code with a normal Windows launch."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import pefile

from exe_process import launch, read_module_memory
from native_map_check import Mapper, STATUS, kernel

IMAGE_FILE_DLL = 0x2000
ACCESS_VIOLATION = 0xC0000005
IMPORTED_DLL = "cpu_import_provider.dll"  # what exe_start.asm imports; the altered provider is bound under this name
WRAPPER_DLL = "cpu_exe_io.dll"  # the startup wrapper (exe_startup.asm) imports finish_exe from here
BODY_SENTINEL = 0xFEEDFACE  # exe_start.asm: body_status until the body has returned
# exe_start.asm: base-4 log digits, then mix_args(5, 3, ...) = 13 (14 from the altered provider).
TLS_ATTACH, ENTRY = 1, 2  # a reserved argument other than null would log 3 instead of 1


def exit_code(log, result):
    code = 0
    for digit in log:
        code = code * 4 + digit
    return (code << 8) | result


def mapped(mapper_path, image, bindings):
    """Map and start the EXE in a child process, so a crash in the guest cannot hide the result."""
    result = subprocess.run([sys.executable, "-B", __file__, "--run", str(mapper_path), str(image), *bindings],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError(f"mapped {Path(image).name}: child exited {result.returncode:#x}: {result.stderr}")
    if result.stderr:
        raise AssertionError(f"mapped {Path(image).name}: child wrote to stderr: {result.stderr}")
    return json.loads(result.stdout)


def run(mapper_path, image, provider, *others):
    mapper = Mapper(mapper_path)
    run_entry = ctypes.CDLL(str(mapper_path)).pe_map_run
    run_entry.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    run_entry.restype = ctypes.c_int
    # Load the DLLs the provider imports first, so its import of cpu_exe_io.dll binds to the DLL given here
    # and not to whatever the search path finds.
    bindings = {Path(other).name.casefold(): ctypes.CDLL(other) for other in others}
    bindings[IMPORTED_DLL] = ctypes.CDLL(provider)
    base, status, detail, requests = mapper(Path(image), bindings)
    if not base:
        print(json.dumps({"status": status, "detail": detail}))
        return
    code = ctypes.c_uint32(0xdeadbeef)
    started = run_entry(base, ctypes.byref(code))
    mapper.release(base)
    print(json.dumps({"status": status, "started": started, "exit": code.value, "requests": requests}))


def decode_log(code):
    """The fixture's base-4 TLS/entry digits, most recent last, from an exit code's upper bits."""
    digits, log = [], code >> 8
    while log:
        digits.insert(0, log & 3)
        log >>= 2
    return digits


def check_requests(name, requests):
    """The fixture binds mix_args from the provider and finish_exe from the startup wrapper's DLL."""
    if sorted(requests) != sorted([[IMPORTED_DLL, "mix_args"], [WRAPPER_DLL, "finish_exe"]]):
        raise AssertionError(f"{name}: import requests {requests}")


def export_rva(image, name):
    with pefile.PE(str(image), fast_load=True) as pe:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
        rva, = [item.address for item in pe.DIRECTORY_ENTRY_EXPORT.symbols if item.name == name]
    return rva


def body_status_hook(image, rva, settle):
    """An on_unfinished hook for launch(): poll body_status in the live process until it leaves the sentinel.

    A slow runner gets up to settle seconds, so a late body is not reported as one that never returned.
    Errors are retried too (modules may not be listed yet); the last one is reported at the deadline.
    """
    def hook(pid):
        deadline = time.monotonic() + settle
        while True:
            try:
                status, = struct.unpack("<I", read_module_memory(pid, image, rva, 4))
                result = {"status": status}
            except OSError as error:
                status, result = None, {"error": str(error)}
            if status not in (None, BODY_SENTINEL) or time.monotonic() >= deadline:
                return result
            time.sleep(0.02)
    return hook


def stage(folder, image, *dlls):
    """Copy the EXE and the (name, path) DLLs it needs into folder; returns the EXE's path."""
    folder = Path(folder)
    shutil.copyfile(image, folder / Path(image).name)
    for name, dll in dlls:
        shutil.copyfile(dll, folder / name)
    return folder / Path(image).name


def observe_native(name, image, expected, log, *, timeout=10, settle=10, env=None, status_rva=None):
    """Launch the staged EXE and observe separately: the body's return (body_status, set before finish_exe),
    whether the process handle becomes signaled, and the exit code with its decoded TLS/entry digits."""
    rva = export_rva(image, b"body_status") if status_rva is None else status_rva
    row = launch([image], b"", env=env, timeout=timeout, on_unfinished=body_status_hook(image, rva, settle))
    if not row["process_signaled"]:
        state = row["unfinished"]
        if row["signaled_after_hook"]:
            # The process ended between the deadline and the end of the hook, so the hook's reading is stale.
            raise AssertionError(
                f"{name}: native process handle not signaled at the {timeout} s deadline ({row['elapsed_ms']} ms), "
                f"but signaled after the hook with exit code {row['code_after_hook']:#x} (TLS/entry digits "
                f"{decode_log(row['code_after_hook'])}); a late exit, not a lingering process; expected exit "
                f"{expected:#x} (digits {log})")
        if "error" in state:
            body = f"state unknown ({state['error']})"
        elif state["status"] == BODY_SENTINEL:
            body = "did not return (body_status is still the sentinel)"
        else:
            body = f"returned {state['status']:#x} (TLS/entry digits {decode_log(state['status'])})"
        raise AssertionError(
            f"{name}: body {body}; native process handle not signaled after {row['elapsed_ms']} ms "
            f"(lingering process; entry thread signaled {row['entry_signaled']}, live threads "
            f"{row['live_threads']}); expected exit {expected:#x} (digits {log})")
    if row["code"] != expected:
        raise AssertionError(
            f"{name}: process exited {row['code']:#x} after {row['elapsed_ms']} ms, expected {expected:#x} "
            f"(TLS/entry digits {decode_log(row['code'])}, expected {log})")
    for stream in ("stdout", "stderr"):
        pipe = row[stream]
        if not pipe["eof"] or pipe["error"]:
            raise AssertionError(f"{name}: process exited but {stream} did not reach clean EOF: {pipe!r}")
    if row["stdout"]["bytes"] or row["stderr"]["bytes"]:
        raise AssertionError(f"{name}: wrote output {row['stdout']['bytes']!r} {row['stderr']['bytes']!r}")
    return row


def expect_failure(label, action, *fragments):
    """A negative control: the observation must fail, and the diagnostic must name the cause.
    A fragment may list alternatives separated by "|"."""
    try:
        action()
    except AssertionError as error:
        missing = [fragment for fragment in fragments if not any(part in str(error) for part in fragment.split("|"))]
        if missing:
            raise AssertionError(f"{label}: failed, but the diagnostic lacks {missing}: {error}") from None
        print(f"{label}: rejected as expected: {error}")
        return
    raise AssertionError(f"{label}: expected the observation to fail, but it passed")


def check_live_worker(mapper, fixtures, io, live, hang):
    """A worker is ready, outlives the body's return by about two seconds and then ends by itself.

    The fixture's body imports only mix_args. The live provider starts the worker inside it. A native
    process must end with the body's DWORD as soon as the body returns, not with the worker's exit
    code 0 after the worker ends. On the mapped path the host must regain control with that DWORD.
    """
    for name, image, log in fixtures:
        expected = exit_code(log, 13)
        with TemporaryDirectory() as temp:
            staged = stage(temp, image, (IMPORTED_DLL, live), (Path(io).name, io))
            row = observe_native(name, staged, expected, log)
            result = mapped(mapper, staged, [Path(temp) / IMPORTED_DLL, Path(temp) / Path(io).name])
            if result.get("status") != STATUS["ok"] or result.get("started") != 1 or result["exit"] != expected:
                raise AssertionError(f"mapped {name} with live worker: {result}, expected exit {expected:#x}")
            check_requests(f"mapped {name} with live worker", result["requests"])
        print(f"live worker {name}: process exited {expected:#x} after {row['elapsed_ms']} ms, digits {log}; "
              f"mapped host regained control with {result['exit']:#x}")

    # Negative controls on the original fixture, all with the live worker.
    name, image, log = fixtures[0]
    expected = exit_code(log, 13)
    with TemporaryDirectory() as temp:
        # 1. PE entry point set to the body: nothing ends the process.
        staged = stage(temp, image, (IMPORTED_DLL, live), (WRAPPER_DLL, io))
        unwrapped = staged.with_name("unwrapped.exe")
        with pefile.PE(str(staged), fast_load=True) as pe:
            pe.OPTIONAL_HEADER.AddressOfEntryPoint = export_rva(image, b"native_entry")
            pe.write(str(unwrapped))
        # The process then ends with the worker's code after about 2 s, or (seen in 1 of 25 repeated runs) an
        # idle loader worker keeps it alive past the deadline although the body has returned.
        expect_failure("unwrapped entry control", lambda: observe_native(name, unwrapped, expected, log),
                       f"process exited 0x0|body returned {expected:#x}")
    with TemporaryDirectory() as temp:
        # 2. finish_exe never terminates (the hang build as cpu_exe_io.dll): the body returned but the process
        #    lingers, and the diagnostic must still name the body's return. 3. The same with body_status read
        #    at an unmapped address.
        staged = stage(temp, image, (IMPORTED_DLL, live), (WRAPPER_DLL, hang))
        expect_failure("hanging finish_exe control", lambda: observe_native(name, staged, expected, log, timeout=3),
                       f"body returned {expected:#x}", "lingering process")
        expect_failure("unreadable body_status control",
                       lambda: observe_native(name, staged, expected, log, timeout=3, settle=1, status_rva=0x7fff0000),
                       "state unknown", "lingering process")
    with TemporaryDirectory() as temp:
        # 4. A body that never returns: the sentinel stays and the process lingers.
        staged = stage(temp, image, (IMPORTED_DLL, live), (WRAPPER_DLL, io))
        hung_body = {**os.environ, "CPU_EXE_TEST_BODY_HANG": "1"}
        expect_failure("body never returns control",
                       lambda: observe_native(name, staged, expected, log, timeout=3, settle=1, env=hung_body),
                       "did not return", "lingering process")


def check_late_exit_diagnostic():
    """A process that ends between the deadline and the hook's return is reported with its exit code.

    Synthetic: launch() is replaced by a row as it would return in that case (not signaled at the deadline,
    signaled after the hook)."""
    global launch
    row = {"process_signaled": False, "unfinished": {"error": "process gone"}, "signaled_after_hook": True,
           "code_after_hook": 0x60d, "elapsed_ms": 10000.0, "entry_signaled": True, "live_threads": []}
    real = launch
    launch = lambda *args, **kwargs: row
    try:
        expect_failure("late exit control", lambda: observe_native("original", "x.exe", 0x60d, [1, 2], status_rva=0),
                       "signaled after the hook with exit code 0x60d", "late exit")
        row = {**row, "signaled_after_hook": False, "code_after_hook": None}
        expect_failure("same row without the late exit", lambda: observe_native("original", "x.exe", 0x60d, [1, 2],
                                                                                status_rva=0),
                       "state unknown", "lingering process")
        clean = {"bytes": b"", "eof": True, "error": None}
        for stream in ("stdout", "stderr"):
            row = {"process_signaled": True, "code": 0x60d, "elapsed_ms": 50.0, "stdout": clean, "stderr": clean}
            row[stream] = {**clean, "eof": False}
            expect_failure(f"open {stream} after exit",
                           lambda: observe_native("original", "x.exe", 0x60d, [1, 2], status_rva=0),
                           f"{stream} did not reach clean EOF")

    finally:
        launch = real


def check(mapper, original, no_tls, provider, altered, io, hang):
    # The EXE imports cpu_import_provider.dll by name; Windows finds it next to the staged copy.
    expected, expected_no_tls = exit_code([TLS_ATTACH, ENTRY], 13), exit_code([ENTRY], 13)
    with TemporaryDirectory() as temp:
        staged = stage(temp, original, (IMPORTED_DLL, provider), (WRAPPER_DLL, io))
        reference = observe_native("original", staged, expected, [TLS_ATTACH, ENTRY])["code"]
    with TemporaryDirectory() as temp:
        staged = stage(temp, no_tls, (IMPORTED_DLL, provider), (WRAPPER_DLL, io))
        reference_no_tls = observe_native("without TLS", staged, expected_no_tls, [ENTRY])["code"]
    print(f"native launch: original {reference:#x}, without TLS {reference_no_tls:#x}")
    with TemporaryDirectory() as temp:
        # Negative control without any worker: the hang build of finish_exe must be reported as a lingering
        # process whose body returned, not as a bare timeout.
        staged = stage(temp, original, (IMPORTED_DLL, provider), (WRAPPER_DLL, hang))
        expect_failure("hanging finish_exe control without worker",
                       lambda: observe_native("original", staged, expected, [TLS_ATTACH, ENTRY], timeout=3),
                       f"body returned {expected:#x}", "lingering process")
    results = {}
    for name, image, bound in (("original", original, provider), ("without TLS", no_tls, provider),
                               ("altered provider", original, altered)):
        results[name] = mapped(mapper, image, [bound, io])
        if results[name].get("status") != STATUS["ok"] or results[name].get("started") != 1:
            raise AssertionError(f"mapped {name}: {results[name]}")
    if results["original"]["exit"] != reference:
        raise AssertionError(f"mapped original {results['original']['exit']:#x} != native {reference:#x}")
    if results["without TLS"]["exit"] != reference_no_tls:
        raise AssertionError(f"mapped without TLS {results['without TLS']['exit']:#x} != native {reference_no_tls:#x}")
    if results["altered provider"]["exit"] != reference + 1:
        raise AssertionError(f"altered provider: {results['altered provider']['exit']:#x}")
    for name in ("original", "without TLS"):
        check_requests(f"mapped {name}", results[name]["requests"])
    print(f"mapped: original {results['original']['exit']:#x} = native, without TLS "
          f"{results['without TLS']['exit']:#x} = native, altered provider {results['altered provider']['exit']:#x}")


def check_dll_refused(mapper, original, provider, io):
    """pe_map_run starts a process image only; with IMAGE_FILE_DLL set it must not call the entry point."""
    with pefile.PE(str(original)) as pe:
        field = pe.FILE_HEADER.get_field_absolute_offset("Characteristics")
        flags = pe.FILE_HEADER.Characteristics
    with TemporaryDirectory() as temp:
        copy = bytearray(Path(original).read_bytes())
        struct.pack_into("<H", copy, field, flags | IMAGE_FILE_DLL)
        image = Path(temp) / Path(original).name
        image.write_bytes(copy)
        result = mapped(mapper, image, [provider, io])
    if result.get("started") != 0 or result["exit"] != 0xdeadbeef:
        raise AssertionError(f"DLL-flagged image: {result}")
    print("pe_map_run refuses an image with IMAGE_FILE_DLL set and leaves the exit code untouched")


def check_refusals(mapper_path, original, provider, io):
    """Each refused startup leaves the fixture's writable log and output sentinel intact."""
    mapper = Mapper(mapper_path)
    start = ctypes.CDLL(str(mapper_path)).pe_map_run
    start.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    start.restype = ctypes.c_int
    kernel.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32,
                                      ctypes.POINTER(ctypes.c_uint32)]
    with TemporaryDirectory() as temp, pefile.PE(str(original)) as pe:
        data = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".data")
        table = pe.DIRECTORY_ENTRY_TLS.struct.AddressOfCallBacks - pe.OPTIONAL_HEADER.ImageBase
        no_entry = Path(temp) / "no-entry.exe"
        pe.OPTIONAL_HEADER.AddressOfEntryPoint = 0
        pe.write(str(no_entry))
        for case in ("no entry", "null output", "unreadable callbacks"):
            image = no_entry if case == "no entry" else original
            modules = {IMPORTED_DLL: ctypes.CDLL(str(provider)), WRAPPER_DLL: ctypes.CDLL(str(io))}
            base, status, detail, _ = mapper(image, modules)
            if not base:
                raise AssertionError(f"{case} map failed: {status} {detail}")
            old = ctypes.c_uint32()
            try:
                before = ctypes.string_at(base + data.VirtualAddress, data.Misc_VirtualSize)
                if case == "unreadable callbacks":
                    if not kernel.VirtualProtect(base + table, 8, 1, ctypes.byref(old)):
                        raise ctypes.WinError(ctypes.get_last_error())
                output = ctypes.c_uint32(0xdeadbeef)
                argument = None if case == "null output" else ctypes.byref(output)
                result = start(base, argument)
                after = ctypes.string_at(base + data.VirtualAddress, data.Misc_VirtualSize)
                if result != 0 or output.value != 0xdeadbeef or before != after:
                    raise AssertionError(f"{case}: result={result} output={output.value:#x}")
            finally:
                if old.value:
                    kernel.VirtualProtect(base + table, 8, old.value, ctypes.byref(old))
                mapper.release(base)
            print(f"refused {case} before guest startup")


def check_entry_outside_code(mapper, original, provider, io):
    """An entry point in .data: pe_map rejects the image before running anything; Windows runs it and faults."""
    with pefile.PE(str(original)) as pe:
        field = pe.OPTIONAL_HEADER.get_field_absolute_offset("AddressOfEntryPoint")
        data = next(sec.VirtualAddress for sec in pe.sections if sec.Name.rstrip(b"\x00") == b".data")
    with TemporaryDirectory() as temp:
        copy = bytearray(Path(original).read_bytes())
        struct.pack_into("<I", copy, field, data)
        image = Path(temp) / Path(original).name
        image.write_bytes(copy)
        shutil.copy(provider, Path(temp) / provider.name)
        shutil.copy(io, Path(temp) / io.name)
        launched = subprocess.run([str(image)], capture_output=True, timeout=60)
        refused = mapped(mapper, image, [provider, io])
    if launched.returncode & 0xffffffff != ACCESS_VIOLATION:
        raise AssertionError(f"entry point in .data: launch exited {launched.returncode & 0xffffffff:#x}")
    if refused.get("status") != STATUS["format"] or refused.get("detail") != "entry point outside executable section":
        raise AssertionError(f"entry point in .data: {refused}")
    print(f"entry point in .data: Windows faults ({ACCESS_VIOLATION:#x}), pe_map refuses "
          f"'{refused['detail']}' and runs nothing")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run":
        run(*sys.argv[2:])
    else:
        parser = argparse.ArgumentParser()
        for name in ("mapper", "original", "no_tls", "provider", "altered", "io", "live", "hang"):
            parser.add_argument(name, type=Path)
        args = parser.parse_args()
        check_late_exit_diagnostic()
        check_live_worker(args.mapper, (("original", args.original, [TLS_ATTACH, ENTRY]),
                                        ("without TLS", args.no_tls, [ENTRY])), args.io, args.live, args.hang)
        check(args.mapper, args.original, args.no_tls, args.provider, args.altered, args.io, args.hang)
        check_dll_refused(args.mapper, args.original, args.provider, args.io)
        check_refusals(args.mapper, args.original, args.provider, args.io)
        check_entry_outside_code(args.mapper, args.original, args.provider, args.io)
