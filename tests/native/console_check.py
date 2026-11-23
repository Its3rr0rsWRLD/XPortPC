"""Run tests/native/console_title.cpp's program under x2w_launch and check the console-library shims.

Usage: console_check.py x2w_launch.exe x2w_console_title.exe SHIMS_DIR

The title imports every name of xcrdapi.dll, chad.dll, xapu.dll, acphal.dll, xg_xs.dll and the xmem.dll additions
(XMemVirtualAlloc, XMemTransferMemory, XMemMapPhysicalPagesScatter, XMemIsToolsMemAvailable) by DLL name. The launcher
must route each to a shim (no "stub", no "missing"), the program exits 0 after every step passes, and the shims log
their first calls. Run twice: DirectStorage forced off (X2W_DSTORAGE_DLL=off: xcrdapi's DStorageGetFactory must
return x2w_sys.dll's own factory, proving the forward) and with the machine's own DirectStorage.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

NAMES = {
    "xcrdapi.dll": ["DStorageGetFactory"],
    "chad.dll": ["XDspActivate", "XDspConnectWithMaximumStreamLimit", "XDspDeactivate", "XDspDisconnect",
                 "XDspSubmitCommand"],
    "xapu.dll": ["XApuConnect", "XApuDequeueResult", "XApuDisconnect", "XApuEnqueueCommand", "XApuGetResultCount"],
    "acphal.dll": ["AcpHalAllocateShapeContexts", "AcpHalCreate", "AcpHalReleaseShapeContexts", "ApuAlloc",
                   "ApuCreateHeap", "ApuFree", "ApuIsVirtualAddressValid", "ApuMapApuAddress", "ApuMapVirtualAddress"],
    "xg_xs.dll": ["XGCreateTextureComputer", "XGSuggestSwizzleMode"],
    "xmem.dll": ["XMemVirtualAlloc", "XMemTransferMemory", "XMemMapPhysicalPagesScatter", "XMemIsToolsMemAvailable",
                 "XMemAllocatePhysicalPages", "XMemFreePhysicalPages"],
}
STEPS = 29


def run(launcher, title, shims, env):
    result = subprocess.run([str(launcher), "--shims", str(shims), str(title)], capture_output=True, text=True,
                            timeout=90, env=env)
    return result.returncode & 0xffffffff, result.stdout, result.stderr


def check(label, launcher, title, shims, extra):
    env = dict(os.environ, **extra)
    code, out, err = run(launcher, title, shims, env)
    print(f"{label}: exit {code}\n{out}", end="")
    if code != 0:
        raise AssertionError(f"{label}: exit {code} (the failed step number)\n{out}\n{err}")
    steps = re.findall(r"^step=(\d+)(!?)$", out, re.M)
    if len(steps) != STEPS or any(bang for _, bang in steps):
        raise AssertionError(f"{label}: expected {STEPS} passing steps\n{out}")
    lines = err.splitlines()
    for dll, names in NAMES.items():
        for name in names:
            line = f"[x2w] import {dll}!{name} -> shim"
            if line not in lines:
                raise AssertionError(f"{label}: missing route line {line!r}\n{err}")
    for line in lines:
        if line.startswith("[x2w] import ") and (line.endswith("-> stub") or line.endswith("-> missing")):
            raise AssertionError(f"{label}: unrouted import: {line}")
    if "[x2w] call stub" in err:
        raise AssertionError(f"{label}: a launcher stub was called\n{err}")
    for needle in ("chad!XDspConnectWithMaximumStreamLimit", "acphal!ApuAlloc", "xg_xs!XGCreateTextureComputer"):
        if needle not in err:
            raise AssertionError(f"{label}: no log line for {needle}\n{err}")
    return err


def main():
    launcher, title, shims = (Path(a).resolve() for a in sys.argv[1:4])
    with tempfile.TemporaryDirectory() as folder:
        exe = Path(folder) / "x2w_console_title.exe"
        exe.write_bytes(title.read_bytes())
        err = check("dstorage off", launcher, exe, shims, {"X2W_DSTORAGE_DLL": "off"})
        if "directstorage" not in err:
            raise AssertionError(f"the DirectStorage forward left no log line\n{err}")
        check("host dstorage", launcher, exe, shims, {})
    print("console shims: PASS")


if __name__ == "__main__":
    main()
