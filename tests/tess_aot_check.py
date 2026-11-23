"""Exercise offline tessellation translation (cards T-1 and T-2, docs/design/stages.md).

Modes:
    tess_aot_check.py --list-families
    tess_aot_check.py controls                                               no DXC, no GPU
    tess_aot_check.py tessellator <dxc> <offscreen_check> warp|hardware <tess_reference>
    tess_aot_check.py draw <dxc> <offscreen_check> warp|hardware <tess_reference> [--family NAME ...]
    tess_aot_check.py binary <llvm-mc> <llvm-objcopy>                        assemble, disassemble (wave64), lower again

"tessellator" measures the desktop tessellator against the D3D11 reference (tests/tess_tessellator.py) for every
domain, partitioning and winding and fails unless each partitioning tools/tess_aot.py accepts is exact.
"""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import tess_tessellator as tt  # noqa: E402

DRAW_FAMILIES = {}
ACCEPTED = set()


def write_record(path):
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("".join(f"{word}\n" for word in sorted(ACCEPTED)), encoding="utf-8")


def check_tessellator(directory, compiler, renderer, backend, tool):
    results, skipped = tt.check(directory, compiler, renderer, backend, tool)
    if skipped:
        return 77
    bad = sorted(config for config, exact in results.items() if not exact)
    print(f"tessellator {backend}: {len(results) - len(bad)} of {len(results)} configurations exact")
    return 1 if bad else 0


def main():
    mode, *args = sys.argv[1:]
    if mode == "--list-families":
        print("\n".join(DRAW_FAMILIES))
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        if mode == "tessellator":
            return check_tessellator(directory, *args)
        raise ValueError("Expected tessellator mode")


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        write_record(os.environ.get("FORM_COVERAGE_RECORD"))
