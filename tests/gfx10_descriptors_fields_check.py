"""Check the GFX10.3 descriptor decoder's bit positions and numbers against Mesa's register database.

src/gfx10_descriptors.cpp reads T#, S# and V# words through one field table (kFields) and maps hardware format and
enumeration numbers to desktop ones. This script builds tests/gfx10_descriptors_check.cpp (C++17), runs it with
--dump, and compares, against the pinned Mesa release's src/amd/registers/gfx10-rsrc.json and gfx6.json (MIT):

- every field (register, name, low and high bit) with the register type of that name in gfx10-rsrc.json;
- every image format's GFX10_FORMAT number with the GFX10_FORMAT enumeration;
- every enumeration value the decoder relies on with gfx6.json.

It then runs the CPU cases (the binary without arguments).

    python3 -B tests/gfx10_descriptors_fields_check.py [--tarball PATH]

The tarball is the one tests/gfx10_addr_oracle_check.py pins (mesa-26.2.6, same sha256, same download). Needs a C++17
compiler (CXX, default c++). Exits 0 on pass, 1 on a mismatch, 77 when the platform or the tarball is unavailable (a
skip, not a pass).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import gfx10_addr_oracle_check as oracle  # noqa: E402

SKIP = 77


def registers(tarball: Path) -> dict[str, dict]:
    prefix = f"mesa-{oracle.MESA_VERSION}/src/amd/registers/"
    out = {}
    with tarfile.open(tarball) as archive:
        for name in ("gfx10-rsrc.json", "gfx6.json"):
            member = archive.getmember(prefix + name)
            out[name] = json.load(archive.extractfile(member))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tarball", default=os.environ.get("X2W_MESA_TARBALL"))
    args = parser.parse_args()
    cxx = os.environ.get("CXX", "c++")
    if sys.platform == "win32" or shutil.which(cxx) is None:
        print("skip: needs a POSIX C++17 compiler (the CPU cases also run on Windows as gfx10_descriptors_check)")
        return SKIP
    out = ROOT / "out" / "gfx10_addr_oracle"
    out.mkdir(parents=True, exist_ok=True)
    tarball = oracle.fetch(out, args.tarball)
    if tarball is None:
        print("skip: the pinned Mesa tarball is unavailable")
        return SKIP
    db = registers(tarball)
    rsrc, gfx6 = db["gfx10-rsrc.json"], db["gfx6.json"]
    binary = out / "gfx10_descriptors_check"
    build = subprocess.run([cxx, "-std=c++17", "-O1", "-Wall", f"-I{ROOT / 'src'}",
                            str(HERE / "gfx10_descriptors_check.cpp"), str(ROOT / "src" / "gfx10_descriptors.cpp"),
                            str(ROOT / "src" / "gfx10_addr.cpp"), str(ROOT / "src" / "gfx10_detile.cpp"),
                            "-o", str(binary)], capture_output=True, text=True)
    if build.returncode:
        print(build.stderr[-3000:])
        return 1
    dump = subprocess.run([str(binary), "--dump"], capture_output=True, text=True, check=True).stdout.splitlines()
    failures = 0
    types = rsrc["register_types"]
    formats = {e["name"]: e["value"] for e in rsrc["enums"]["GFX10_FORMAT"]["entries"]}
    fields = image_formats = enums = 0
    for line in dump:
        kind, *rest = line.split()
        if kind == "field":
            reg, name, lo, hi = rest[0], rest[1], int(rest[2]), int(rest[3])
            fields += 1
            known = {f["name"]: f["bits"] for f in types.get(reg, {}).get("fields", [])}
            if known.get(name) != [lo, hi]:
                print(f"MISMATCH field {reg}.{name} [{lo}, {hi}]: Mesa has {known.get(name)}")
                failures += 1
        elif kind == "format":
            name, value = rest[0], int(rest[1])
            image_formats += 1
            if formats.get(f"GFX10_FORMAT_{name}") != value:
                print(f"MISMATCH format {name} = {value}: Mesa has {formats.get('GFX10_FORMAT_' + name)}")
                failures += 1
        elif kind == "enum":
            enum, entry, value = rest[0], rest[1], int(rest[2])
            enums += 1
            entries = {e["name"]: e["value"] for e in gfx6["enums"].get(enum, {}).get("entries", [])}
            if entries.get(entry) != value:
                print(f"MISMATCH enum {enum}.{entry} = {value}: Mesa has {entries.get(entry)}")
                failures += 1
    print(f"compared {fields} fields, {image_formats} formats, {enums} enumeration values with Mesa "
          f"{oracle.MESA_VERSION}: {failures} mismatches")
    cases = subprocess.run([str(binary)], capture_output=True, text=True)
    print(cases.stdout.strip())
    return 1 if failures or cases.returncode else 0


if __name__ == "__main__":
    sys.exit(main())
