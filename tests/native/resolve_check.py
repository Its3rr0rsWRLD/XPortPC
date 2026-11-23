"""Dynamic module lookups, and the run log's ends, under x2w_launch.

Usage: resolve_check.py x2w_launch.exe x2w_resolve_title.exe x2w_resolve_pkg.dll SHIM_DIR

The title (tests/native/resolve_title.cpp) and its package DLL (tests/native/resolve_pkg.cpp) are copied into
one scratch folder, the title's package folder. Both look up kernel32's condition-variable functions through
GetModuleHandleW + GetProcAddress, as a C++ runtime does; the title also asks for the package DLL by name and
for an API set by name. Checked:
  - the clean run exits 0x3f and logs those lookups as "-> windows" with kernel32's name (never "?"), the
    package DLL's own lookups as "-> mapped", and ends with "summary exit";
  - fault mode: lstrlenA's handled access violation inside Windows (ntdll, kernel32 or kernelbase) is logged with the frames in the mapped
    images that led there (package DLL, then title), a provisional "summary first-fault" follows it, and the
    program's ExitProcess still writes the exit line and "summary exit";
  - crash mode: the crash line and "summary crash" are written before the program's own unhandled-exception
    filter runs, which ends the process with 0x66;
  - control: the Windows loader runs the same folder with every bit but the API set one (0x10) agreeing.
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

TITLE = "x2w_resolve_title.exe"
PKG = "x2w_resolve_pkg.dll"


def run(launcher, folder, shims, mode, extra=()):
    log = Path(folder) / f"run-{mode or 'clean'}.log"
    env = dict(os.environ)
    env.pop("X2W_RESOLVE_MODE", None)
    if mode:
        env["X2W_RESOLVE_MODE"] = mode
    result = subprocess.run([launcher, "--shims", shims, "--log", str(log), "--timeout", "60", *extra,
                             str(Path(folder) / TITLE)], capture_output=True, text=True, timeout=120, env=env)
    lines = log.read_text(encoding="utf-8").splitlines()
    print(f"--- run.log ({mode or 'clean'}), exit {result.returncode & 0xffffffff:#x}")
    print("\n".join(lines))
    for line in lines:
        assert any(re.fullmatch(rule, line) for rule in GRAMMAR), f"log line outside the grammar: {line!r}"
    if "--show-program-name" in extra:
        assert any(TITLE in line for line in lines), lines
    else:
        # The program is title.exe in every log line and on stderr; package and Windows DLL names stay.
        assert_hidden(TITLE, "\n".join(lines), result.stderr)
        assert_hidden(Path(TITLE).stem + ".", "\n".join(lines), result.stderr)
    return result.returncode & 0xFFFFFFFF, lines


def index_of(lines, pattern):
    for i, line in enumerate(lines):
        if re.fullmatch(pattern, line):
            return i
    raise AssertionError(f"no log line matches {pattern!r}")


def main():
    launcher, title, pkg, shims = sys.argv[1:5]
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    with tempfile.TemporaryDirectory() as folder:
        shutil.copy2(title, Path(folder) / TITLE)
        shutil.copy2(pkg, Path(folder) / PKG)

        code, lines = run(launcher, folder, shims, None)
        assert code == 0x3F, f"exit {code:#x}, expected 0x3f"
        for symbol in ("SleepConditionVariableCS", "WakeAllConditionVariable"):
            index_of(lines, rf"dynamic-resolve kernel32\.dll!{symbol} -> windows")
        index_of(lines, rf"dynamic-resolve {re.escape(PKG)}!ResolvePkgProbe -> mapped")
        index_of(lines, rf"dynamic-load {re.escape(PKG)} -> mapped")
        index_of(lines, r"dynamic-resolve kernel32\.dll!X2wNoSuchFunction -> missing")
        assert not any(line.startswith("dynamic-resolve ?") for line in lines), lines
        assert lines[-1].startswith("summary exit: "), lines[-1]
        assert not any(line.startswith("crash ") for line in lines), lines

        code, lines = run(launcher, folder, shims, "fault")
        assert code == 0x7F, f"fault mode exit {code:#x}, expected 0x7f"
        first = index_of(lines, rf"first-chance exception 0xc0000005 at (?:ntdll|kernel32|kernelbase)\.dll\+0x[0-9a-f]+ "
                                rf"thread program(?: thread-name \S+)? reading 0x10 last-stub none callers {re.escape(PKG)}\+0x[0-9a-f]+ "
                                rf"from {re.escape(HIDDEN)}\+0x[0-9a-f]+(?: from \S+)?")
        provisional = index_of(lines, r"summary first-fault: .* entry=reached .* crash=no last-stub=none")
        exit_line = index_of(lines, r"exit code 0x7f \(127\); stubs \d+ \(missing \d+\), stub calls \d+")
        final = index_of(lines, r"summary exit: .* crash=no last-stub=none")
        assert first < provisional < exit_line < final, (first, provisional, exit_line, final)
        assert final == len(lines) - 1, lines[-1]

        code, lines = run(launcher, folder, shims, "crash")
        assert code == 0x66, f"crash mode exit {code:#x}, expected 0x66 from the program's own filter"
        index_of(lines, r"unhandled-filter program filter kept behind the launcher's")
        crash = index_of(lines, rf"crash exception 0xc0000005 at {re.escape(HIDDEN)}\+0x[0-9a-f]+ thread program"
                                r"(?: thread-name \S+)? writing 0x0 last-stub none(?: regs(?: [a-z0-9]+=0x[0-9a-f]+){16})?")
        final = index_of(lines, r"summary crash: .* crash=yes last-stub=none")
        assert crash < final, (crash, final)
        assert sum(line.startswith(("summary crash", "summary exit", "summary terminate")) for line in lines) == 1, lines

        # --show-program-name: the callers chain names the real file again.
        code, lines = run(launcher, folder, shims, "fault", extra=("--show-program-name",))
        index_of(lines, rf"first-chance exception .* callers {re.escape(PKG)}\+0x[0-9a-f]+ from {re.escape(TITLE)}\+0x[0-9a-f]+(?: from \S+)?")

        # Control: the Windows loader runs the same folder; every bit but the API set one agrees.
        native = subprocess.run([str(Path(folder) / TITLE)], capture_output=True, timeout=30)
        assert native.returncode & ~0x10 == 0x2F, f"native exit {native.returncode:#x}"
    print("native_launch_resolve: dynamic lookups and every run log ending behaved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
