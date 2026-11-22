"""Compare the same nested RIP-relative EXE chain with two initial writable-image states."""
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

import pefile

from exe_entry_check import Observation, check, observation, run
from exe_process import launch
import mapped_exe_chain_check as mapped


def compare(mapper, original, lifted, io, mix):
    wide = Observation(struct.pack("<QQ", 0x100000303, 0xfffffffd), struct.pack("<Q", 0x311), 0x60d)
    narrow = Observation(struct.pack("<QQ", 48, 6), struct.pack("<Q", 0x35), 0x57)
    with pefile.PE(str(original)) as pe:
        preferred = hex(pe.OPTIONAL_HEADER.ImageBase)
        bias, = [s for s in pe.DIRECTORY_ENTRY_EXPORT.symbols if s.name == b"selector_bias"]
        offset = pe.get_offset_from_rva(bias.address)
    data = bytearray(original.read_bytes())
    check("linked bias", struct.unpack_from("<Q", data, offset), (5,))
    with TemporaryDirectory() as folder:
        changed = Path(folder) / original.name
        struct.pack_into("<Q", data, offset, 0)
        changed.write_bytes(data)
        for provider in (io, mix):
            shutil.copy2(provider, folder)
        for image, bias, expected in ((original, 5, (wide, narrow)), (changed, 0, (narrow, wide))):
            for selector, reference in enumerate(expected):
                payload = bytes([selector])
                check("Windows loader", run(image, payload), reference)
                child = subprocess.run([sys.executable, "-B", mapped.__file__, "--child", mapper,
                                        image, io, mix], input=payload, capture_output=True, timeout=15)
                check("pe_map", Observation(child.stderr, child.stdout, child.returncode), reference)
                expected_slot = (5 * selector - 5 + bias) % (1 << 64)
                command = [lifted, image, preferred, hex(expected_slot)]
                check("recompiled EXE", observation(launch(command, payload)), reference)
                print(f"bias={bias} selector={selector} args={reference.arguments.hex()} "
                      f"output={reference.output.hex()} exit={reference.exit_code:#x}")


if __name__ == "__main__":
    compare(*map(Path, sys.argv[1:]))
