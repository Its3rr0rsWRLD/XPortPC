"""x2w_sys's synchronous calls on overlapped handles and x2w_launch's stall detector (tests/native/stall_title.cpp).

Usage: stall_check.py x2w_launch.exe x2w_stall_title.exe SHIMS_DIR

  stall    the title (with --shims, --log, --timeout) exits 0: its ReadFile/WriteFile calls with lpOverlapped null on a
           FILE_FLAG_OVERLAPPED file give the right bytes (stderr: "sync-read-on-async-handle" and
           "sync-write-on-async-handle"); its file-open lines name the file's flags (OVERLAPPED) and type disk, and the
           pipe by its device name with type pipe; the run log has one "stalled thread N(main) in
           kernel32.dll!ReadFile(...)" line with handle-type pipe and overlapped-handle=no, the handle being the one
           the pipe's file-open line gave.
  quick    X2W_STALL_MS=200: the read waits less than 2 s and no stall line is written.
Every log line must match run_log_check.py's grammar.
"""
import ctypes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_log_check import assert_hidden, check_grammar  # noqa: E402

STALL = re.compile(r"stalled thread (\d+)\((main|program)\) in ([^(]+)\((0x[0-9a-f]+),0x[0-9a-f]+,0x[0-9a-f]+,"
                   r"0x[0-9a-f]+\) for (\d+)s caller=title\.exe\+0x[0-9a-f]+(.*)")


def run(launcher, title, shims, label, stall_ms=None):
    with tempfile.TemporaryDirectory() as scratch:
        log = Path(scratch) / "run.log"
        env = dict(os.environ)
        env.pop("X2W_STALL_MS", None)
        if stall_ms is not None:
            env["X2W_STALL_MS"] = str(stall_ms)
        env["LOCALAPPDATA"] = scratch
        result = subprocess.run([launcher, "--shims", shims, "--log", str(log), "--timeout", "60", title],
                                capture_output=True, text=True, timeout=120, env=env)
        text = log.read_text(encoding="utf-8")
    code = result.returncode & 0xFFFFFFFF
    print(f"--- {label}: exit {code:#x}")
    print(result.stderr, end="")
    print("--- run.log")
    print(text, end="")
    lines = text.splitlines()
    check_grammar(lines, title)
    assert_hidden(Path(title).name, text, result.stderr)
    return code, lines, result.stderr


def main():
    launcher, title, shims = sys.argv[1:4]
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    failures = []

    def expect(condition, message):
        if not condition:
            failures.append(message)
            print(f"FAIL: {message}")

    code, lines, stderr = run(launcher, title, shims, "stall")
    expect(code == 0, f"stall: exit {code:#x}, expected 0 (10 + the first wrong step)")
    expect("sync-read-on-async-handle" in stderr, "stall: no sync-read-on-async-handle line")
    expect("sync-write-on-async-handle" in stderr, "stall: no sync-write-on-async-handle line")
    opens = [l for l in stderr.splitlines() if "file-open " in l]
    disk = [l for l in opens if "x2w_stall_overlapped.bin" in l]
    expect(any("flags=(OVERLAPPED|DELETE_ON_CLOSE|0x80)" in l and "type=disk" in l and "<path>\\x2w_stall_overlapped.bin" in l
               for l in disk), f"stall: no overlapped disk file-open line: {disk}")
    pipe = [l for l in opens if "\\\\.\\pipe\\x2w_stall_check" in l]
    match = re.search(r"-> handle (0x[0-9a-f]+) access=0x80000000 share=0x0 disp=OPEN_EXISTING flags=\(\) type=pipe",
                      pipe[0]) if pipe else None
    expect(match is not None, f"stall: no pipe file-open line with type=pipe: {pipe}")
    stalls = [STALL.fullmatch(l) for l in lines if l.startswith("stalled thread")]
    expect(len(stalls) == 1 and stalls[0] is not None, f"stall: expected one stalled line, got {len(stalls)}")
    if stalls and stalls[0]:
        m = stalls[0]
        expect(m[2] == "main", f"stall: thread {m[2]}, expected main")
        expect(m[3] == "kernel32.dll!ReadFile", f"stall: stalled in {m[3]}, expected kernel32.dll!ReadFile")
        expect(int(m[5]) >= 2, f"stall: for {m[5]}s")
        if match:
            expect(m[4] == match[1], f"stall: handle {m[4]}, the pipe was opened as {match[1]}")
            expect(f" handle {match[1]} " in m[6], f"stall: no handle field: {m[6]!r}")
        expect(" handle-type pipe " in m[6], f"stall: no handle-type pipe: {m[6]!r}")
        expect("overlapped-handle=no" in m[6] or "overlapped-handle=busy" in m[6],
               f"stall: overlapped-handle: {m[6]!r}")
        expect("opened-as \\\\.\\pipe\\x2w_stall_check flags=() type-at-open=pipe" in m[6],
               f"stall: no opened-as fields: {m[6]!r}")

    code, lines, stderr = run(launcher, title, shims, "quick", 200)
    expect(code == 0, f"quick: exit {code:#x}, expected 0")
    expect(not any(l.startswith("stalled") for l in lines), "quick: a stall line for a 200 ms read")

    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("stall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
