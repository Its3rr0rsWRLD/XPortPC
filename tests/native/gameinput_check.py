"""A title importing gameinput.dll!GameInputCreate under x2w_launch gets x2w's GameInput v0 facade.

Usage: gameinput_check.py x2w_launch.exe x2w_gameinput_title.exe SHIM_DIR

tests/native/gameinput_title.cpp calls the v0 vtable slots (src/sys/sys_gameinput_v0.h). Checked:
  - clean run: exit 0 (every step answered as the facade does, whether or not an XInput pad is connected), the import
    routes to the shim ("gameinput.dll!GameInputCreate -> shim"), and the run log holds a "shim-gameinput" line for
    GameInputCreate, GetCurrentTimestamp, GetCurrentReading, RegisterDeviceCallback, the unknown slot 40 (with its
    arguments), UnregisterCallback, CreateDispatcher, Dispatch and QueryInterface, then "summary exit";
  - X2W_GAMEINPUT_PADS=off: no reading ("reading=none", "pads=0"), still exit 0;
  - fastfail mode: RaiseFailFastException is logged with "summary fastfail" as the final summary;
  - thread mode: a thread that starts in ntdll faults there; the crash line ends with "callers none thread-start
    ntdll.dll+0x..." (no mapped frame to report) and "summary crash" follows.
Every log line must match tests/native/run_log_check.py's grammar.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_log_check import GRAMMAR  # noqa: E402

TITLE = "x2w_gameinput_title.exe"


def run(launcher, folder, shims, mode=None, env_extra=None):
    log = Path(folder) / f"run-{mode or 'clean'}-{len(os.listdir(folder))}.log"
    env = dict(os.environ)
    env.pop("X2W_GI_MODE", None)
    env.pop("X2W_GAMEINPUT_PADS", None)
    if mode:
        env["X2W_GI_MODE"] = mode
    env.update(env_extra or {})
    result = subprocess.run([str(launcher), "--shims", str(shims), "--log", str(log), "--timeout", "60",
                             str(Path(folder) / TITLE)], capture_output=True, text=True, timeout=120, env=env)
    lines = log.read_text(encoding="utf-8").splitlines()
    code = result.returncode & 0xFFFFFFFF
    print(f"--- run.log ({mode or 'clean'} {env_extra or ''}), exit {code:#x}\n{result.stdout}", end="")
    print("\n".join(lines))
    for line in lines:
        assert any(re.fullmatch(rule, line) for rule in GRAMMAR), f"log line outside the grammar: {line!r}"
    return code, result.stdout, result.stderr, lines


def has(lines, pattern):
    return any(re.fullmatch(pattern, line) for line in lines)


def main():
    launcher, title, shims = (Path(a).resolve() for a in sys.argv[1:4])
    assert (shims / "gameinput.dll").is_file(), f"no gameinput.dll in {shims}"
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        shutil.copy(title, folder / TITLE)

        code, out, err, lines = run(launcher, folder, shims)
        assert code == 0, f"clean run exit {code:#x}\n{err}"
        assert "[x2w] import gameinput.dll!GameInputCreate -> shim" in err.splitlines(), err
        for method in ("GameInputCreate", "GetCurrentTimestamp", "GetCurrentReading", "RegisterDeviceCallback",
                       "UnregisterCallback", "CreateDispatcher", "Dispatch", "QueryInterface", "SetFocusPolicy"):
            assert has(lines, rf"shim-gameinput {method} .*"), f"no shim-gameinput {method} line"
        assert has(lines, r"shim-gameinput unknown-slot IGameInput\[40\] this=\S+ a=0x1234 b=0x5678 c=0x9abc -> E_NOTIMPL"), \
            "unknown slot not logged with its arguments"
        assert has(lines, r"shim-gameinput GetCurrentReading kind=0x10 device=\S+ -> 0x838a0003"), "keyboard reading"
        assert lines[-1].startswith("summary exit: "), lines[-1]
        print("native_launch_gameinput clean: the v0 facade answered every call, each one logged")

        code, out, err, lines = run(launcher, folder, shims, env_extra={"X2W_GAMEINPUT_PADS": "off"})
        assert code == 0 and "reading=none" in out and "pads=0" in out, f"pads off: exit {code:#x}\n{out}\n{err}"
        assert has(lines, r"shim-gameinput GetCurrentReading kind=0x40000 device=\S+ -> 0x838a0003"), "pads off reading"

        code, out, err, lines = run(launcher, folder, shims, mode="fastfail")
        assert has(lines, r"fastfail RaiseFailFastException code 0xc0000409 at .*"), "no fastfail line"
        assert sum(line.startswith(("summary exit", "summary crash", "summary terminate", "summary fastfail"))
                   for line in lines) == 1, lines
        assert lines[-1].startswith("summary fastfail: "), lines[-1]
        print(f"native_launch_gameinput fastfail: logged with the final summary (exit {code:#x})")

        code, out, err, lines = run(launcher, folder, shims, mode="thread")
        assert has(lines, r"crash exception 0xc0000005 at ntdll\.dll\+0x[0-9a-f]+ .* callers none thread-start ntdll\.dll\+0x[0-9a-f]+"
                   r"(?: thread-init-phase [a-z\-]+(?: fn [a-z0-9_.\-]+\+0x[0-9a-f]+)?)?"), \
            "the crash on a Windows thread does not name the thread's start"
        assert has(lines, r"summary crash: .*"), "no crash summary"
        print("native_launch_gameinput thread: a fault on a thread outside the mapped images names the thread start")


main()
