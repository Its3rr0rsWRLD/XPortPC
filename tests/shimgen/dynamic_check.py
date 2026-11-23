"""Run tests/shimgen/dynamic_title.cpp through x2w_launch and check the loader hooks.

Usage: dynamic_check.py x2w_launch.exe x2w_shimgen_dynamic_title.exe SHIM_DIR

The program loads xgameruntime.dll at run time and resolves names with GetProcAddress, as PC GDK builds do.
With --shims SHIM_DIR (holding the generated xgameruntime.dll and x2w_gdk.dll) every check in the program
must pass (exit 0x1ff), and the run log must name each dynamic load and resolve with its route. The run
log's dynamic-resolve lines must then feed tools/shimgen.py --run-log.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main(launcher, title, shims):
    with tempfile.TemporaryDirectory() as scratch:
        log = Path(scratch) / "run.log"
        result = subprocess.run([launcher, "--shims", shims, "--log", str(log), "--timeout", "60", title],
                                capture_output=True, text=True, timeout=120)
        text = log.read_text(encoding="utf-8")
        print(text, end="")
        print(result.stderr[-4000:], end="")
        code = result.returncode & 0xffffffff
        assert code == 0x1ff, f"exit {code:#x}: a check in dynamic_title.cpp failed"
        lines = text.splitlines()
        for expected in ("dynamic-load xgameruntime.dll -> shim",
                         "dynamic-resolve xgameruntime.dll!XGameRuntimeInitialize -> shim",
                         "dynamic-resolve xgameruntime.dll!XSystemGetDeviceType -> shim",
                         "dynamic-resolve xgameruntime.dll!X2WNotExported -> missing",
                         "dynamic-resolve kernel32.dll!LoadLibraryExW -> windows",
                         "dynamic-load x2w_no_such_dll_for_dynamic_title.dll -> failed"):
            assert expected in lines, f"missing run-log line: {expected}"
        assert any(line.startswith("shim-note x2w_gdk!XGameRuntimeInitialize ") for line in lines), \
            "x2w_gdk did not log through x2w_launch_log_shim"
        assert sum(line == "dynamic-load xgameruntime.dll -> shim" for line in lines) == 1, "loads are logged once"
        # The run log becomes a shim manifest.
        out = Path(scratch) / "gen"
        subprocess.run([sys.executable, "-B", str(ROOT / "tools" / "shimgen.py"), "--run-log", str(log),
                        "--out", str(out)], check=True)
        summary = json.loads((out / "shimgen.json").read_text(encoding="utf-8"))
        rows = {r["function"]: r["body"] for r in summary["dlls"]["xgameruntime.dll"]["functions"]}
        assert rows.get("XSystemGetDeviceType") == "impl" and rows.get("X2WNotExported") == "unknown", rows
        assert "kernel32.dll" not in summary["dlls"], "Windows resolves are not shim input"
    print("dynamic load hooks: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
