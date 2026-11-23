"""The launcher's heap guard (tools/x2w_launch.cpp, "heap guard") with a source-built title.

Usage: heap_guard_check.py x2w_launch.exe x2w_heap_title.exe SHIM_DIR

The title (tests/native/heap_title.cpp) frees an XMemAlloc pointer with the C runtime's free(), hands a stack
buffer to HeapFree (imported and through GetProcAddress), HeapSize and HeapReAlloc, and gives a HeapAlloc block
to XMemFree. Checked:
  - under the guard (the default) the title exits 0: every one of those is refused, nothing is corrupted;
  - the run log has "heap-guard on", one "heap-guard invalid" line per refused call, with the owner (xmem-alloc
    for the XMemAlloc pointer, stack for the stack buffer) and callers in the mapped title, no
    "heap-guard corrupted-before" line, and "heap-guard summary invalid=5 corrupted=no" before "summary exit";
  - xmem.dll logs the foreign XMemFree as ignored;
  - control: with --no-heap-guard the stack HeapFree alone ends the process with a failure code.
Every log line must match tests/native/run_log_check.py's grammar.
"""
import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_log_check import GRAMMAR, HIDDEN, assert_hidden  # noqa: E402

TITLE = "x2w_heap_title.exe"


def run(launcher, folder, shims, extra=(), mode=None):
    log = Path(folder) / f"run-{mode or 'guard'}.log"
    env = dict(os.environ)
    env.pop("X2W_HEAP_MODE", None)
    if mode:
        env["X2W_HEAP_MODE"] = mode
    result = subprocess.run([launcher, "--shims", shims, "--log", str(log), "--timeout", "60", *extra,
                             str(Path(folder) / TITLE)], capture_output=True, text=True, timeout=150, env=env)
    lines = log.read_text(encoding="utf-8").splitlines()
    print(f"--- run.log ({mode or 'guard'}), exit {result.returncode & 0xffffffff:#x}")
    print("\n".join(lines))
    print("--- stderr")
    print(result.stderr)
    for line in lines:
        assert any(re.fullmatch(rule, line) for rule in GRAMMAR), f"log line outside the grammar: {line!r}"
    assert_hidden(TITLE, "\n".join(lines), result.stderr)
    return result.returncode & 0xFFFFFFFF, lines, result.stderr


def main():
    launcher, title, shims = sys.argv[1:4]
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    with tempfile.TemporaryDirectory() as folder:
        shutil.copy2(title, Path(folder) / TITLE)

        code, lines, stderr = run(launcher, folder, shims)
        assert code == 0, f"exit {code:#x}, expected 0"
        assert "heap-guard on" in lines, lines
        invalid = [line for line in lines if line.startswith("heap-guard invalid ")]
        callers = rf" callers {re.escape(HIDDEN)}\+0x[0-9a-f]+.* not-forwarded"
        expected = [rf"heap-guard invalid free ptr=0x[0-9a-f]+ heap=0x[0-9a-f]+ owner=xmem-alloc{callers}",
                    rf"heap-guard invalid HeapFree ptr=0x[0-9a-f]+ heap=0x[0-9a-f]+ owner=stack{callers}",
                    rf"heap-guard invalid HeapFree ptr=0x[0-9a-f]+ heap=0x[0-9a-f]+ owner=stack{callers}",
                    rf"heap-guard invalid HeapSize ptr=0x[0-9a-f]+ heap=0x[0-9a-f]+ owner=stack{callers}",
                    rf"heap-guard invalid HeapReAlloc ptr=0x[0-9a-f]+ heap=0x[0-9a-f]+ owner=stack{callers}"]
        assert len(invalid) == len(expected), invalid
        for line, pattern in zip(invalid, expected):
            assert re.fullmatch(pattern, line), (line, pattern)
        assert not any(line.startswith("heap-guard corrupted-before") for line in lines), lines
        summary = next(i for i, line in enumerate(lines) if line.startswith("heap-guard summary "))
        assert re.fullmatch(r"heap-guard summary invalid=5 corrupted=no last-check=.+", lines[summary]), lines[summary]
        assert lines[-1].startswith("summary exit: ") and summary < len(lines) - 1, lines[-3:]
        assert "which XMemAlloc did not return; ignored" in stderr, stderr

        code, lines, _ = run(launcher, folder, shims, ("--no-heap-guard",), mode="control")
        assert "heap-guard on" not in lines, lines
        assert not any(line.startswith("heap-guard ") for line in lines), lines
        assert code != 0, "the stack HeapFree without the guard was expected to fail"
    print("heap guard: ok")


if __name__ == "__main__":
    main()
