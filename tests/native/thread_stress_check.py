"""Thread starts under x2w_launch: every new thread gets a valid TLS block for each mapped image and the slot-0 alias
before any mapped TLS callback or DllMain runs on it.

Usage: thread_stress_check.py x2w_launch.exe x2w_thread_stress_title.exe x2w_thread_stress_pkg.dll [RUNS]

The title (tests/native/thread_stress_title.cpp, /GL + /LTCG, static C runtime, its own TLS callback) and its
package DLL (tests/native/thread_stress_pkg.cpp, own TLS and DllMain) are copied into one scratch folder. The title
starts 64 threads (CreateThread, _beginthreadex, std::thread) that check the TLS templates of both images, from its
TLS callback, the package's DllMain and the thread functions. Checked:
  - natively (Windows loader) it exits 0x1c5 with "thread-stress workers=64 bad=0";
  - under x2w_launch, RUNS times (default 20), the same exit code and output, a run log whose lines all match
    tests/native/run_log_check.py's grammar, no first-chance or crash line, and exactly 8 "thread-init tid N
    tls-ok images 2" lines (both images' blocks and entry 0 checked before the first mapped notification).
"""
import ctypes
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_log_check import GRAMMAR  # noqa: E402

TITLE = "x2w_thread_stress_title.exe"
PKG = "x2w_thread_stress_pkg.dll"
EXPECTED = 0x1c5
OUTPUT = "thread-stress workers=64 bad=0"


def main():
    launcher, title, pkg = sys.argv[1:4]
    runs = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        shutil.copy2(title, folder / TITLE)
        shutil.copy2(pkg, folder / PKG)
        native = subprocess.run([str(folder / TITLE)], capture_output=True, text=True, timeout=60)
        print(f"native: exit {native.returncode & 0xffffffff:#x} {native.stdout.strip()!r}")
        assert native.returncode == EXPECTED and native.stdout.strip() == OUTPUT, native
        grammar = [re.compile(pattern) for pattern in GRAMMAR]
        failures = []
        for run in range(runs):
            log = folder / f"run-{run}.log"
            result = subprocess.run([launcher, "--log", str(log), "--timeout", "60", str(folder / TITLE)],
                                    capture_output=True, text=True, timeout=120)
            code = result.returncode & 0xffffffff
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else []
            problems = []
            if code != EXPECTED or result.stdout.strip() != OUTPUT:
                problems.append(f"exit {code:#x} stdout {result.stdout.strip()!r}")
            faults = [line for line in lines if line.startswith(("first-chance ", "crash "))]
            if faults:
                problems.append(f"faults {faults[:3]}")
            inits = [line for line in lines if line.startswith("thread-init ")]
            if len(inits) != 8 or not all(re.fullmatch(r"thread-init tid \d+ tls-ok images 2", line) for line in inits):
                problems.append(f"thread-init lines {inits}")
            stray = [line for line in lines if not any(g.fullmatch(line) for g in grammar)]
            if stray:
                problems.append(f"lines outside the grammar {stray[:3]}")
            print(f"run {run}: exit {code:#x} thread-init {len(inits)} {'ok' if not problems else problems}")
            if problems:
                failures.append((run, problems, [line for line in lines if "tls-slot0" in line]))
        assert not failures, failures
    print(f"native_launch_thread_stress: {runs} runs, every thread had its TLS blocks before its first notification")


if __name__ == "__main__":
    main()
