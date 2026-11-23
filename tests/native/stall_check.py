"""x2w_sys's synchronous calls on overlapped handles and x2w_launch's stall detector (tests/native/stall_title.cpp).

Usage: stall_check.py x2w_launch.exe x2w_stall_title.exe SHIMS_DIR

  stall    the title (with --shims and --log, no --timeout) exits 0: its ReadFile/WriteFile calls with lpOverlapped null on a
           FILE_FLAG_OVERLAPPED file give the right bytes (stderr: "sync-read-on-async-handle" and
           "sync-write-on-async-handle"); its file-open lines name the file's flags (OVERLAPPED) and type disk, and the
           pipe by its device name with type pipe; the run log has one "stalled thread N(main) in
           kernel32.dll!ReadFile(...)" line with handle-type pipe and overlapped-handle=no, the handle being the one
           the pipe's file-open line gave, and the file offset/size (n/a for a pipe) and the buffer's State/Protect/Type; the writer thread's
           wait (10 s or less) is not also-pending (only main and file/IO calls are).
  workers  X2W_STALL_WORKERS=8: 8 idle threads in WaitForSingleObject(INFINITE) are not reported and not listed as
           also-pending, the main thread's pipe ReadFile still is; with --stall-all they are.
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
                   r"0x[0-9a-f]+\) for (\d+)s( \(still\))? caller=title\.exe\+0x[0-9a-f]+(.*)")


def run(launcher, title, shims, label, stall_ms=None, workers=None, flags=()):
    with tempfile.TemporaryDirectory() as scratch:
        log = Path(scratch) / "run.log"
        env = dict(os.environ)
        env.pop("X2W_STALL_MS", None)
        if stall_ms is not None:
            env["X2W_STALL_MS"] = str(stall_ms)
        env.pop("X2W_STALL_WORKERS", None)
        if workers:
            env["X2W_STALL_WORKERS"] = str(workers)
        env["LOCALAPPDATA"] = scratch
        # No --timeout: the stall detector runs with every --log.
        result = subprocess.run([launcher, "--shims", shims, "--log", str(log), *flags, title],
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
    exit_at = next((i for i, l in enumerate(lines) if l.startswith("exit code")), len(lines))
    expect(any(l.startswith("stalled thread") for l in lines[:exit_at]), "stall: no stalled line before the exit line")
    every = [STALL.fullmatch(l) for l in lines if l.startswith("stalled thread")]
    expect(all(every), "stall: a stalled line outside the pattern")
    stalls = [m for m in every if m and m[3] == "kernel32.dll!ReadFile"]
    expect(len(stalls) == 1, f"stall: expected one stalled ReadFile line, got {len(stalls)}")
    if stalls and stalls[0]:
        m = stalls[0]
        expect(m[2] == "main", f"stall: thread {m[2]}, expected main")
        expect(m[3] == "kernel32.dll!ReadFile", f"stall: stalled in {m[3]}, expected kernel32.dll!ReadFile")
        expect(int(m[5]) >= 2, f"stall: for {m[5]}s")
        if match:
            expect(m[4] == match[1], f"stall: handle {m[4]}, the pipe was opened as {match[1]}")
            expect(f" handle {match[1]} " in m[7], f"stall: no handle field: {m[7]!r}")
        expect(" handle-type pipe " in m[7], f"stall: no handle-type pipe: {m[7]!r}")
        expect("overlapped-handle=no" in m[7] or "overlapped-handle=busy" in m[7],
               f"stall: overlapped-handle: {m[7]!r}")
        expect(" also-pending" not in m[7], f"stall: an idle wait is also-pending: {m[7]!r}")
        expect(not m[6], f"stall: first line marked (still): {m[7]!r}")
        expect(re.search(r" file-offset (?:n/a|busy) file-size (?:n/a|busy)", m[7]) is not None,
               f"stall: no file-offset/file-size fields: {m[7]!r}")
        expect(re.search(r" buffer 0x[0-9a-f]+ State=COMMIT Protect=0x[0-9a-f]+ Type=[A-Z]+", m[7]) is not None,
               f"stall: no buffer fields: {m[7]!r}")
        expect("opened-as \\\\.\\pipe\\x2w_stall_check flags=() type-at-open=pipe" in m[7],
               f"stall: no opened-as fields: {m[7]!r}")

    code, lines, stderr = run(launcher, title, shims, "workers", workers=8)
    expect(code == 0, f"workers: exit {code:#x}, expected 0")
    every = [STALL.fullmatch(l) for l in lines if l.startswith("stalled thread")]
    expect(all(every), "workers: a stalled line outside the pattern")
    expect(sum(1 for m in every if m and m[3] == "kernel32.dll!ReadFile" and m[2] == "main") == 1,
           "workers: expected one stalled main ReadFile line")
    expect(not any(m and m[2] == "program" for m in every), "workers: an idle worker was reported")
    expect(not any("also-pending" in l for l in lines if l.startswith("stalled")),
           "workers: idle waits listed as also-pending")

    code, lines, stderr = run(launcher, title, shims, "workers-all", workers=8, flags=("--stall-all",))
    expect(code == 0, f"workers-all: exit {code:#x}, expected 0")
    every = [STALL.fullmatch(l) for l in lines if l.startswith("stalled thread")]
    expect(sum(1 for m in every if m and m[2] == "program" and m[3].endswith("!WaitForSingleObject")) >= 8,
           "workers-all: --stall-all did not report the 8 idle workers")

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
