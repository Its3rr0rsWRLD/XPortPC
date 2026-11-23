"""Check the GFX10/GFX10.3 address port (src/gfx10_addr.cpp, src/gfx10_detile.cpp) against AMD's addrlib.

Builds addrlib from a pinned Mesa release (src/amd/addrlib, MIT) on Linux or macOS, links it with
tests/gfx10_addr_oracle/oracle.cpp and our sources, and runs the comparison. Also checks that the swizzle tables in
src/gfx10_swizzle_pattern.h are byte-identical to the pinned addrlib file, and runs the addrlib-free round-trip test
(tests/gfx10_detile_check.cpp).

    python3 -B tests/gfx10_addr_oracle_check.py [--quick] [--tarball PATH]

The tarball is mesa-26.2.6 (sha256 below). Without --tarball (or X2W_MESA_TARBALL) it is downloaded once into
out/gfx10_addr_oracle/. Needs a C++17 compiler (CXX, default c++). Exits 0 on pass, 1 on a mismatch, 77 when the
platform or the tarball is unavailable (a skip, not a pass).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESA_VERSION = "26.2.6"
MESA_SHA256 = "b9436b3e1a8be76fbd4823dc884f90596ab7c6ac5e1867a305e66ffccfb31a92"
MESA_URLS = (
    f"https://archive.mesa3d.org/mesa-{MESA_VERSION}.tar.xz",
    f"https://archive.ubuntu.com/ubuntu/pool/main/m/mesa/mesa_{MESA_VERSION}.orig.tar.xz",
)
PATTERN_FILE = "src/amd/addrlib/src/gfx10/gfx10SwizzlePattern.h"
PATTERN_LINES = (24, 5370)  # 1-based, inclusive: the range copied into src/gfx10_swizzle_pattern.h
SKIP = 77


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(out: Path, given: str | None) -> Path | None:
    if given:
        path = Path(given)
        if sha256(path) != MESA_SHA256:
            print(f"tarball {path} does not have sha256 {MESA_SHA256}")
            return None
        return path
    path = out / f"mesa-{MESA_VERSION}.tar.xz"
    if path.exists() and sha256(path) == MESA_SHA256:
        return path
    for url in MESA_URLS:
        try:
            print(f"downloading {url}")
            with urllib.request.urlopen(url, timeout=120) as response, path.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        except OSError as error:
            print(f"  failed: {error}")
            continue
        if sha256(path) == MESA_SHA256:
            return path
        print("  sha256 mismatch, ignored")
    path.unlink(missing_ok=True)
    return None


def extract(tarball: Path, out: Path) -> Path:
    """Extract only src/amd/addrlib into a fresh directory (data filter: no links or absolute paths)."""
    dest = out / "mesa-src"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    prefix = f"mesa-{MESA_VERSION}/src/amd/addrlib/"
    with tarfile.open(tarball) as archive:
        members = [m for m in archive.getmembers() if m.name.startswith(prefix) and (m.isfile() or m.isdir())]
        archive.extractall(dest, members=members, filter="data")
    return dest / f"mesa-{MESA_VERSION}" / "src" / "amd" / "addrlib"


def check_tables(addrlib: Path) -> bool:
    upstream = (addrlib / PATTERN_FILE.split("src/amd/addrlib/")[1]).read_text().splitlines()
    first, last = PATTERN_LINES
    expected = upstream[first - 1:last]
    ours = (ROOT / "src" / "gfx10_swizzle_pattern.h").read_text().splitlines()
    try:
        start = ours.index(expected[0])
    except ValueError:
        print("tables: first table not found in src/gfx10_swizzle_pattern.h")
        return False
    same = ours[start:start + len(expected)] == expected
    print(f"tables: {len(expected)} lines of {PATTERN_FILE}:{first}-{last} {'identical' if same else 'DIFFER'}")
    return same


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=False, text=True, capture_output=True, **kwargs)


def build_addrlib(addrlib: Path, build: Path, cxx: str) -> Path | None:
    """Static addrlib as Mesa builds it (meson.build defines), DEBUG=0, without the optional SIMD copy paths."""
    build.mkdir(parents=True, exist_ok=True)
    includes = [f"-I{addrlib / d}" for d in ("inc", "src", "src/core", "src/chip/gfx9", "src/chip/r800",
                                               "src/chip/gfx10", "src/chip/gfx11", "src/chip/gfx12")]
    flags = ["-O1", "-std=c++17", "-DADDR_FASTCALL=", "-DLITTLEENDIAN_CPU", "-DDEBUG=0", "-w", *includes]
    sources = sorted(addrlib.rglob("*.cpp"))

    def compile_one(source: Path) -> tuple[Path, subprocess.CompletedProcess]:
        obj = build / (source.stem + ".o")
        return obj, run([cxx, *flags, "-c", str(source), "-o", str(obj)])

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        results = list(pool.map(compile_one, sources))
    for obj, result in results:
        if result.returncode != 0:
            print(f"addrlib compile failed: {obj.name}\n{result.stderr[-2000:]}")
            return None
    library = build / "libaddrlib.a"
    library.unlink(missing_ok=True)
    if run(["ar", "rcs", str(library), *[str(o) for o, _ in results]]).returncode != 0:
        print("ar failed")
        return None
    print(f"addrlib: {len(sources)} files built from Mesa {MESA_VERSION}")
    return library


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--tarball", default=os.environ.get("X2W_MESA_TARBALL"))
    args = parser.parse_args()
    if sys.platform == "win32":
        print("skip: the addrlib oracle builds on Linux/macOS (tests/gfx10_detile_check.cpp runs on Windows)")
        return SKIP
    cxx = os.environ.get("CXX", "c++")
    if shutil.which(cxx) is None or shutil.which("ar") is None:
        print(f"skip: {cxx} or ar not found")
        return SKIP
    out = ROOT / "out" / "gfx10_addr_oracle"
    out.mkdir(parents=True, exist_ok=True)
    tarball = fetch(out, args.tarball)
    if tarball is None:
        print("skip: pinned Mesa tarball unavailable")
        return SKIP
    print(f"mesa: {tarball.name} sha256 {MESA_SHA256}")
    addrlib = extract(tarball, out)
    ok = check_tables(addrlib)
    library = build_addrlib(addrlib, out / "addrlib", cxx)
    if library is None:
        return 1
    ours = [str(ROOT / "src" / "gfx10_addr.cpp"), str(ROOT / "src" / "gfx10_detile.cpp")]
    common = [cxx, "-O2", "-std=c++17", "-Wall", "-DADDR_FASTCALL=", "-DLITTLEENDIAN_CPU", f"-I{ROOT / 'src'}"]
    oracle = out / "oracle"
    built = run([*common, f"-I{addrlib / 'inc'}", str(ROOT / "tests" / "gfx10_addr_oracle" / "oracle.cpp"), *ours,
                 str(library), "-o", str(oracle)])
    roundtrip = out / "gfx10_detile_check"
    built_rt = run([*common, str(ROOT / "tests" / "gfx10_detile_check.cpp"), *ours, "-o", str(roundtrip)])
    for name, result in (("oracle", built), ("gfx10_detile_check", built_rt)):
        if result.returncode != 0:
            print(f"{name} build failed:\n{result.stderr[-4000:]}")
            return 1
    for name, command in (("oracle", [str(oracle)] + (["--quick"] if args.quick else [])),
                          ("roundtrip", [str(roundtrip)])):
        result = run(command)
        print(f"--- {name}")
        print(result.stdout.rstrip())
        ok = ok and result.returncode == 0
    print("gfx10_addr_oracle_check:", "pass" if ok else "fail")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
