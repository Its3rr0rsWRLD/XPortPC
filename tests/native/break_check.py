"""Breakpoints in a mapped image under x2w_launch (tests/native/break_title.cpp, break_ops.asm).

Usage: break_check.py x2w_launch.exe x2w_break_title.exe

  default   --continue-breakpoints is the default without a debugger: the one-byte int3, the two-byte CD 03 and
            __debugbreak() are each logged ("breakpoint continued at title.exe+0x.. count N regs ...", RAX
            0x1122334455667788 at the first two) and skipped; the program exits 0 and the log counts 3.
  explicit  --continue-breakpoints given: the same.
  stop      --stop-on-breakpoints: the first int3 crashes the run with 0x80000003, and the crash line carries the
            general registers (RAX the known value).
Every log line must match run_log_check.py's grammar, which admits no program bytes.
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

RAX = "rax=0x1122334455667788"
REGS = r" regs rax=0x[0-9a-f]+ rbx=0x[0-9a-f]+ rcx=0x[0-9a-f]+ rdx=0x[0-9a-f]+ rsi=0x[0-9a-f]+ rdi=0x[0-9a-f]+" \
       r"(?: r(?:8|9|1[0-5])=0x[0-9a-f]+){8} rbp=0x[0-9a-f]+ rsp=0x[0-9a-f]+"


def run(launcher, title, label, extra):
    with tempfile.TemporaryDirectory() as scratch:
        log = Path(scratch) / "run.log"
        result = subprocess.run([launcher, "--log", str(log), "--timeout", "60", *extra, title],
                                capture_output=True, text=True, timeout=120, env=dict(os.environ))
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


def main():
    launcher, title = sys.argv[1:3]
    _, text_start, text_end = text_range(title)
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    failures = []

    def expect(condition, message):
        if not condition:
            failures.append(message)
            print(f"FAIL: {message}")

    for label, extra in (("default", []), ("explicit", ["--continue-breakpoints"])):
        code, lines = run(launcher, title, label, extra)
        expect(code == 0, f"{label}: exit {code:#x}, expected 0")
        hits = [re.fullmatch(rf"breakpoint continued at title\.exe\+0x([0-9a-f]+) count (\d+)({REGS})", l)
                for l in lines]
        hits = [m for m in hits if m]
        expect(len(hits) == 3 and [int(m[2]) for m in hits] == [1, 2, 3], f"{label}: breakpoint lines {hits}")
        expect(all(text_start <= int(m[1], 16) < text_end for m in hits), f"{label}: a breakpoint outside .text")
        expect(len(hits) >= 2 and all(f" {RAX} " in m[3] for m in hits[:2]), f"{label}: RAX not in the first two")
        expect(len(hits) == 3 and int(hits[1][1], 16) - int(hits[0][1], 16) in (1, 2),
               f"{label}: the two-byte int3 is not right after the one-byte one")
        expect("breakpoints continued 3" in lines, f"{label}: no 'breakpoints continued 3' line")
        expect(any(l.startswith("summary exit:") for l in lines), f"{label}: no exit summary")
        expect(not any(l.startswith("crash ") for l in lines), f"{label}: a crash line")

    code, lines = run(launcher, title, "stop", ["--stop-on-breakpoints"])
    expect(code == 0x80000003, f"stop: exit {code:#x}, expected 0x80000003")
    crash = [re.fullmatch(rf"crash exception 0x80000003 at title\.exe\+0x([0-9a-f]+) thread program last-stub none"
                          rf"({REGS})", l) for l in lines]
    crash = [m for m in crash if m]
    expect(len(crash) == 1 and f" {RAX} " in crash[0][2] and text_start <= int(crash[0][1], 16) < text_end,
           "stop: no crash line in .text with the registers and the known RAX")
    expect(not any(l.startswith("breakpoint") for l in lines), "stop: a breakpoint was continued")
    # Control: the register pattern must not match a line without registers.
    expect(not re.search(REGS, "crash exception 0x80000003 at title.exe+0x10 thread program last-stub none"),
           "control: the register pattern matched a line without registers")

    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("breakpoint checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
