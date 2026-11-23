"""The launcher's recent-calls trace (tools/x2w_launch.cpp, "recent-calls trace"; tests/native/trace_title.cpp).

Usage: trace_check.py x2w_launch.exe x2w_trace_title.exe

  exit     the title's calls give the right results through the thunks (LastError included): exit 0,
           "trace-calls on" in the log.
  crash    a null write on the main thread: the crash line is followed by "recent-calls thread main" and the title's
           calls oldest first, each with its arguments, its return value and a caller in the title's .text.
  break    __debugbreak() continued: the breakpoint line is followed by the main thread's recent calls; exit 0.
  thread   a null write on a second thread: its ring (MulDiv(2,3,1) -> 0x6) follows the crash line, then the main
           thread's, whose last call, WaitForSingleObject, is still pending.
  off      --no-trace-calls: no trace lines, the same crash line.
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
from run_log_check import assert_hidden, check_grammar, text_range  # noqa: E402

RECENT = re.compile(r"recent (\d+): ([^(]+)\((0x[0-9a-f]+),(0x[0-9a-f]+),(0x[0-9a-f]+),(0x[0-9a-f]+)\) -> "
                    r"(0x[0-9a-f]+|pending) caller=title\.exe\+0x([0-9a-f]+)")


def run(launcher, title, label, mode, extra=()):
    with tempfile.TemporaryDirectory() as scratch:
        log = Path(scratch) / "run.log"
        env = dict(os.environ)
        env.pop("X2W_TRACE_MODE", None)
        if mode:
            env["X2W_TRACE_MODE"] = mode
        result = subprocess.run([launcher, "--log", str(log), "--timeout", "60", *extra, title],
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
    return code, lines


def block(lines, start):
    """The recent lines after lines[start] (a "recent-calls thread ..." header), parsed."""
    out = []
    for line in lines[start + 1:]:
        if not line.startswith("recent "):
            break
        match = RECENT.fullmatch(line)
        out.append(match if match else line)
    return out


def main():
    launcher, title = sys.argv[1:3]
    _, text_start, text_end = text_range(title)
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    failures = []

    def expect(condition, message):
        if not condition:
            failures.append(message)
            print(f"FAIL: {message}")

    def header(lines, who, after=-1):
        for i, line in enumerate(lines):
            if i > after and re.fullmatch(rf"recent-calls thread {who} calls \d+", line):
                return i
        return None

    # (name, first args or None, return value or None) in call order, as the main thread makes them.
    main_calls = [("kernel32.dll!MulDiv", (6, 7, 1), 42), ("kernel32.dll!SetLastError", (1234,), None),
                  ("kernel32.dll!GetLastError", None, 1234), ("kernel32.dll!lstrlenA", None, 5),
                  ("kernel32.dll!MultiByteToWideChar", (65001, 0), 3), ("kernel32.dll!GetModuleHandleW", None, None),
                  ("kernel32.dll!GetProcAddress", None, None), ("kernel32.dll!MulDiv", (3, 5, 1), 15)]

    def check_calls(label, entries, calls):
        parsed = [e for e in entries if not isinstance(e, str)]
        expect(len(parsed) == len(entries), f"{label}: unparsed recent lines {[e for e in entries if isinstance(e, str)]}")
        names = [m[2] for m in parsed]
        # The wanted calls appear in order, as a subsequence ending the ring (the env lookup comes first).
        position = 0
        for name, args, value in calls:
            while position < len(parsed) and names[position] != name:
                position += 1
            if position == len(parsed):
                expect(False, f"{label}: {name} not in the recent calls {names}")
                return parsed
            m = parsed[position]
            if args is not None:
                got = tuple(int(m[3 + i], 16) for i in range(len(args)))
                expect(got == args, f"{label}: {name} args {got}, expected {args}")
            if value is not None:
                expect(m[7] == f"{value:#x}", f"{label}: {name} returned {m[7]}, expected {value:#x}")
            expect(text_start <= int(m[8], 16) < text_end, f"{label}: {name} caller outside .text")
            position += 1
        seqs = [int(m[1]) for m in parsed]
        expect(seqs == sorted(seqs) and len(set(seqs)) == len(seqs), f"{label}: sequence numbers not increasing {seqs}")
        return parsed

    code, lines = run(launcher, title, "exit", None)
    expect(code == 0, f"exit: exit {code:#x}, expected 0")
    expect("trace-calls on" in lines, "exit: no 'trace-calls on'")
    if not any(l.startswith("first-chance") for l in lines):
        expect(not any(l.startswith("recent") for l in lines), "exit: recent lines without a fault")

    code, lines = run(launcher, title, "crash", "crash")
    expect(code == 0xC0000005, f"crash: exit {code:#x}")
    crash = next((i for i, l in enumerate(lines) if l.startswith("crash exception 0xc0000005")), None)
    expect(crash is not None, "crash: no crash line")
    if crash is not None:
        at = header(lines, "main", crash)
        expect(at == crash + 1, f"crash: the main thread's ring does not follow the crash line ({at}, {crash})")
        if at is not None:
            entries = block(lines, at)
            expect(0 < len(entries) <= 32, f"crash: {len(entries)} recent lines")
            parsed = check_calls("crash", entries, main_calls)
            expect(bool(parsed) and parsed[-1][2] == "kernel32.dll!MulDiv", "crash: the last call is not MulDiv")
        expect(sum(1 for l in lines if l.startswith("recent-calls thread")) >= 2,
               "crash: the first-chance line has no ring")
        summary = next((i for i, l in enumerate(lines) if l.startswith("summary crash:")), None)
        expect(summary is not None and (at or 0) < summary, "crash: the ring is not before the crash summary")

    code, lines = run(launcher, title, "break", "break")
    expect(code == 0, f"break: exit {code:#x}, expected 0")
    hit = next((i for i, l in enumerate(lines) if l.startswith("breakpoint continued at title.exe+")), None)
    expect(hit is not None and header(lines, "main", hit) == hit + 1, "break: no main thread ring after the breakpoint line")
    if hit is not None:
        check_calls("break", block(lines, hit + 1), main_calls)

    code, lines = run(launcher, title, "thread", "thread")
    expect(code == 0xC0000005, f"thread: exit {code:#x}")
    crash = next((i for i, l in enumerate(lines) if l.startswith("crash exception 0xc0000005")), None)
    expect(crash is not None, "thread: no crash line")
    if crash is not None:
        worker = lines[crash + 1] if crash + 1 < len(lines) else ""
        expect(re.fullmatch(r"recent-calls thread \d+ calls \d+", worker) is not None,
               f"thread: the crash line is not followed by the worker's ring: {worker!r}")
        entries = block(lines, crash + 1)
        check_calls("thread worker", entries, [("kernel32.dll!MulDiv", (2, 3, 1), 6)])
        later = [i for i, l in enumerate(lines) if i > crash and re.fullmatch(r"recent-calls thread main calls \d+", l)]
        expect(bool(later), "thread: no main thread ring after the crash")
        if later:
            parsed = check_calls("thread main", block(lines, later[0]),
                                 main_calls + [("kernel32.dll!CreateThread", None, None)])
            last = parsed[-1] if parsed else None
            expect(last is not None and last[2] == "kernel32.dll!WaitForSingleObject" and last[7] == "pending",
                   f"thread: the main thread's last call is not a pending WaitForSingleObject: {last and last[0]}")

    code, lines = run(launcher, title, "off", "crash", ["--no-trace-calls"])
    expect(code == 0xC0000005, f"off: exit {code:#x}")
    expect(any(l.startswith("crash exception 0xc0000005") for l in lines), "off: no crash line")
    expect(not any(l.startswith(("recent", "trace-calls")) for l in lines), "off: trace lines with --no-trace-calls")

    # Control: the pattern must not accept a line without a return value.
    expect(not RECENT.fullmatch("recent 1: kernel32.dll!MulDiv(0x6,0x7,0x1,0x0) caller=title.exe+0x10"),
           "control: the recent pattern matched a line without a return value")
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("recent-calls trace checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
