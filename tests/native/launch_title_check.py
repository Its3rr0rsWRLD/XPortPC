"""Run source-built titles natively and through x2w_launch and compare what they observe.

Usage: launch_title_check.py tls|tls-crt|identity|throw x2w_launch.exe TITLE.exe

tls       tests/native/tls_title.cpp: implicit TLS data (template, zero fill, a relocated pointer) read and
          written on the main thread and two workers, gs:[0x58][_tls_index], and the TLS callback on
          process attach, thread attach and detach and process detach. Expected exit code 0x13f and the
          line "process-detach main=0000600d" under both loaders.
          Control: a copy whose template value is changed gives exit code 0x108 under both (only the
          check that the main thread kept its own writes holds), so the checks read the template.
tls-crt   tests/native/tls_crt_title.cpp: the static C runtime's startup and thread_local machinery
          (dynamic initializer, destructor on thread exit) in the mapped image. Expected 0x13f and the same
          output line under both loaders.
identity  tests/native/identity_title.cpp: GetModuleHandle(NULL), GetModuleHandleEx, GetModuleFileName(NULL),
          the PEB image base and a resource found through the null module name the title. Expected 0x1ff
          under both loaders. Controls: x2w_launch --host-identity gives 0x180 (every identity answer names
          the launcher; only the short-buffer behavior still holds), and a renamed copy run natively gives
          0x1e3 (its name lookup and file-name checks fail).
throw     tests/native/throw_title.cpp: C++ exceptions of three types thrown and caught in the mapped image (the
          static runtime's _CxxThrowException finds no image base for a mapped ThrowInfo; x2w_launch supplies
          it). Expected 0x107 and the same output under both loaders. With --log, exactly one
          "cpp-throw TYPE at SITE from CALLER" line per type (.?AVruntime_error@std@@, .?AUbad_probe@probe@@,
          .H) and one "cpp-throw rethrow" line at the same _CxxThrowException site, each CALLER inside the
          throwing function's .pdata entry (the runtime's re-raise of the rethrown bad_probe may add one more
          line at its own site), and every log line within the run log grammar.
"""
import ctypes
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pefile

TIMEOUT = 60


def quiet_errors():
    # The child inherits the error mode, so a crash returns instead of opening a dialog.
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)


def run(command):
    result = subprocess.run([str(part) for part in command], capture_output=True, text=True, timeout=TIMEOUT)
    return result.returncode & 0xffffffff, result.stdout, result.stderr


def compare(launcher, title, expected_code, expected_stdout=None, label=""):
    native_code, native_out, native_err = run([title])
    launch_code, launch_out, launch_err = run([launcher, title])
    print(f"{label}native: exit {native_code:#x} stdout {native_out.strip()!r}")
    print(f"{label}x2w_launch: exit {launch_code:#x} stdout {launch_out.strip()!r}")
    if native_code != expected_code:
        raise AssertionError(f"{label}native exit {native_code:#x} != {expected_code:#x}: {native_err}")
    if launch_code != expected_code:
        raise AssertionError(f"{label}x2w_launch exit {launch_code:#x} != {expected_code:#x}:\n{launch_err}")
    if native_out != launch_out:
        raise AssertionError(f"{label}stdout differs: native {native_out!r} x2w_launch {launch_out!r}")
    if expected_stdout is not None and native_out.strip() != expected_stdout:
        raise AssertionError(f"{label}stdout {native_out!r} != {expected_stdout!r}")
    if Path(title).name.lower() in launch_err.lower():
        raise AssertionError(f"{label}stderr holds the program's real file name:\n{launch_err}")
    if "-> stub" in launch_err:
        raise AssertionError(f"{label}an import fell back to a stub:\n{launch_err}")
    return launch_err


def template_copy(title, folder, old, new):
    """A copy of title whose TLS template holds new in place of old (each a 32-bit value)."""
    data = bytearray(Path(title).read_bytes())
    with pefile.PE(str(title)) as pe:
        tls = pe.DIRECTORY_ENTRY_TLS.struct
        base = pe.OPTIONAL_HEADER.ImageBase
        start = pe.get_offset_from_rva(tls.StartAddressOfRawData - base)
        size = tls.EndAddressOfRawData - tls.StartAddressOfRawData
        zero_fill = tls.SizeOfZeroFill
    if size <= 0 or zero_fill != 256:
        raise AssertionError(f"unexpected TLS directory: template {size} bytes, zero fill {zero_fill}")
    template = bytes(data[start:start + size])
    needle = struct.pack("<I", old)
    if template.count(needle) != 1:
        raise AssertionError(f"template holds {template.count(needle)} copies of {old:#x}")
    offset = start + template.index(needle)
    data[offset:offset + 4] = struct.pack("<I", new)
    copy = Path(folder) / Path(title).name
    copy.write_bytes(data)
    return copy


def check_tls(launcher, title):
    err = compare(launcher, title, 0x13f, "process-detach main=0000600d")
    if "[x2w] cannot map" in err:
        raise AssertionError(err)

    with tempfile.TemporaryDirectory() as folder:
        changed = template_copy(title, folder, 0x5eed1234, 0x0bad1234)
        compare(launcher, changed, 0x108, "process-detach main=0000600d", "changed template: ")
    print("native_launch_tls: template, zero fill, relocated pointer, gs:[0x58] and TLS callbacks match Windows")


def check_tls_crt(launcher, title):
    compare(launcher, title, 0x13f, "tls-crt code=0x13f constructed=3 destroyed=2")
    print("native_launch_tls_crt: C runtime thread_local initializers and destructors match Windows")


def check_identity(launcher, title):
    err = compare(launcher, title, 0x1ff)
    for symbol in ("GetModuleHandleW", "GetModuleHandleA", "GetModuleHandleExW", "GetModuleFileNameW",
                   "GetModuleFileNameA"):
        line = f"[x2w] import kernel32.dll!{symbol} -> windows (title identity)"
        if line not in err.splitlines():
            raise AssertionError(f"missing report line: {line}\n{err}")
    host_code, _, host_err = run([launcher, "--host-identity", title])
    print(f"--host-identity: exit {host_code:#x}")
    if host_code != 0x180:
        raise AssertionError(f"--host-identity exit {host_code:#x} != 0x180:\n{host_err}")
    if "(title identity)" in host_err:
        raise AssertionError(f"--host-identity still bound the identity functions:\n{host_err}")
    with tempfile.TemporaryDirectory() as folder:
        renamed = Path(folder) / "x2w_identity_renamed.exe"
        shutil.copy(title, renamed)
        renamed_code, _, _ = run([renamed])
        print(f"renamed copy, native: exit {renamed_code:#x}")
        if renamed_code != 0x1e3:
            raise AssertionError(f"renamed copy exit {renamed_code:#x} != 0x1e3")
    print("native_launch_identity: module handle, file name, PEB image base and resources name the title")


def function_range(title, rva):
    """The .pdata entry (begin, end) that starts at rva."""
    with pefile.PE(str(title)) as pe:
        for entry in pe.DIRECTORY_ENTRY_EXCEPTION:
            if entry.struct.BeginAddress == rva:
                return entry.struct.BeginAddress, entry.struct.EndAddress
    raise AssertionError(f"no .pdata entry starts at {rva:#x}")


def check_throw(launcher, title):
    expected = "cpp-throw code=0x107 main=3/3/3 worker=3/3/3"
    native_code, native_out, _ = run([title])
    if native_code != 0x107 or not native_out.startswith(expected + "\n"):
        raise AssertionError(f"native: exit {native_code:#x} stdout {native_out!r}")
    sites = dict(re.findall(r"(\w+)=0x([0-9a-f]+)", native_out.splitlines()[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from run_log_check import check_grammar  # noqa: E402

    name = "title.exe"  # the launcher's default name for the program
    with tempfile.TemporaryDirectory() as folder:
        log = Path(folder) / "run.log"
        code, out, err = run([launcher, "--log", log, "--timeout", "60", title])
        lines = log.read_text(encoding="utf-8").splitlines()
    print(f"--log: exit {code:#x}")
    print("\n".join(line for line in lines if line.startswith(("cpp-throw", "crash", "exit"))))
    if code != 0x107 or out != native_out:
        raise AssertionError(f"--log: exit {code:#x} stdout {out!r}\n{err}")
    check_grammar(lines, title)
    assert Path(title).name.lower() not in "\n".join(lines).lower() + err.lower(), lines
    compare(launcher, title, 0x107)
    where = rf"{re.escape(name)}\+0x([0-9a-f]+)"
    throws = []
    for line in lines:
        # The line may end with the caller chain (" callers A from B from C"), which makes otherwise equal lines
        # distinct (the same throw reached from two call sites); those count once here.
        match = re.fullmatch(rf"cpp-throw (\S+) at {where} from {where}(?: callers {where}(?: from {where}){{0,2}})?", line)
        if line.startswith("cpp-throw") and not match:
            raise AssertionError(f"cpp-throw line without two title frames: {line!r}")
        if match:
            throw = (match[1], int(match[2], 16), int(match[3], 16))
            if throw not in throws or " callers " not in line:
                throws.append(throw)
    if len(set(throws)) != len(throws):
        raise AssertionError("a cpp-throw line is repeated:\n" + "\n".join(lines))
    # Every throw statement goes through the title's _CxxThrowException, the site of the first throw. The
    # runtime raises a rethrown object once more from its catch-block helper, under its own type and site.
    site = throws[0][1] if throws else None
    found = {}
    for type_name, at, caller in throws:
        if at == site:
            if type_name in found:
                raise AssertionError(f"{type_name} logged twice at the throw site:\n" + "\n".join(lines))
            found[type_name] = caller
        elif type_name != ".?AUbad_probe@probe@@":
            raise AssertionError(f"{type_name} raised outside the throw site:\n" + "\n".join(lines))
    types = {".?AVruntime_error@std@@": "runtime", ".?AUbad_probe@probe@@": "probe", ".H": "int"}
    if set(found) != set(types) | {"rethrow"}:
        raise AssertionError(f"thrown types {sorted(found)} != {sorted(set(types) | {'rethrow'})}")
    for type_name, function in types.items():
        begin, end = function_range(title, int(sites[function], 16))
        caller = found[type_name]
        if not begin < caller <= end:
            raise AssertionError(f"{type_name}: caller {caller:#x} outside {function} [{begin:#x}, {end:#x}]")
    for line in err.splitlines():
        if line.startswith("[x2w] cpp-throw") and line[6:] not in lines:
            raise AssertionError(f"stderr line not in the log: {line!r}")
    print("native_launch_throw: C++ exceptions caught in the mapped image; types and throw sites logged")


def main():
    mode, launcher, title = sys.argv[1:4]
    quiet_errors()
    {"tls": check_tls, "tls-crt": check_tls_crt, "identity": check_identity, "throw": check_throw}[mode](Path(launcher), Path(title))
    return 0


if __name__ == "__main__":
    sys.exit(main())
