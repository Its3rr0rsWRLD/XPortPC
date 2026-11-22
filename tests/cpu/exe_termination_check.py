"""Verify process termination and mapped return with a deliberately live worker."""
import hashlib
import os
from pathlib import Path
import platform
import shutil
import struct
import sys
from tempfile import TemporaryDirectory

import pefile

from exe_entry_check import Observation, check, observation
from exe_process import launch
from mapped_exe_chain_check import mapped_child


def compare(mapper, native, lifted, io, mix):
    env = dict(os.environ, CPU_EXE_TEST_LIVE_WORKER="1")
    print(f"Windows {platform.version()}", flush=True)
    for binary in (native, lifted, io, mix):
        print(f"{binary.name} sha256={hashlib.sha256(binary.read_bytes()).hexdigest()}", flush=True)
    cases = [
        (b"\x00", Observation(struct.pack("<QQ", 0x100000303, 0xfffffffd), struct.pack("<Q", 0x311), 0x60d)),
        (b"\x01", Observation(struct.pack("<QQ", 48, 6), struct.pack("<Q", 53), 0x57)),
        (b"", Observation(b"", b"", 2)),
    ]
    host_marker = b"mapped host returned\n"
    for data, expected in cases:
        check("native process with live worker", observation(launch([native], data, env=env)), expected)
        check("AOT process with live worker", observation(launch([lifted], data, env=env)), expected)
        mapped = launch([sys.executable, "-B", __file__, "--mapped", mapper, native, io, mix], data, env=env)
        check("mapped host with live worker", observation(mapped),
              expected._replace(arguments=expected.arguments + host_marker))
        print(f"selector={data.hex() or 'empty'} code={expected.exit_code:#x} native/AOT EOF and mapped return",
              flush=True)

    # Change only the startup RVA in a temporary copy to show why returning
    # directly from the original body is insufficient with a live worker.
    with TemporaryDirectory() as work:
        unwrapped = Path(work) / native.name
        for provider in (io, mix):
            shutil.copyfile(provider, unwrapped.with_name(provider.name))
        with pefile.PE(str(native), fast_load=True) as pe:
            pe.parse_data_directories(directories=[0])
            body, = [item.address for item in pe.DIRECTORY_ENTRY_EXPORT.symbols
                     if item.name == b"native_entry"]
            pe.OPTIONAL_HEADER.AddressOfEntryPoint = body
            pe.write(str(unwrapped))
        data, expected = cases[0]
        row = launch([unwrapped], data, env=env, timeout=5)
    check("unwrapped process signaled", row["process_signaled"], False)
    check("unwrapped entry returned", row["entry_signaled"], True)
    check("unwrapped entry code", row["entry_code"], expected.exit_code)
    check("unwrapped worker remains", any(tid != row["entry_tid"] for tid in row["live_threads"]), True)
    check("unwrapped stdout", row["stdout"], {"bytes": expected.output, "eof": False, "error": None})
    check("unwrapped stderr", row["stderr"], {"bytes": expected.arguments, "eof": False, "error": None})
    print("Unwrapped control returned from entry with a live worker and both pipes open.")


if __name__ == "__main__":
    if sys.argv[1] == "--mapped":
        code = mapped_child(*map(Path, sys.argv[2:]))
        sys.stderr.buffer.write(b"mapped host returned\n")
        sys.exit(code)
    else:
        compare(*map(Path, sys.argv[1:]))
