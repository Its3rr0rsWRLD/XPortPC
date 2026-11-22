"""corpus_translate: translate the committed corpus pixel shaders end to end and compile every translated one with DXC.

Usage: corpus_translate_check.py <dxc> <work-dir>

Runs tools/corpus_translate.py over tests/corpus/isa/pixel, writes the HLSL of each translated shader to
<work-dir>/hlsl and compiles it with the flags the pixel_aot draws use (-Gis -T ps_6_0 -E main; ps_6_1 when the
lowering declares flat inputs, which need GetAttributeAtVertex). Fails if any translated shader does not compile.
Before that, two controls check the compile step itself: the pixel_aot reference program must compile, and the same
source with a syntax error must not. Prints the counts, and a note when docs/coverage/corpus-translate.tsv no longer
matches this run (regenerate it with `python tools/corpus_translate.py --summary docs/coverage/corpus-translate.tsv`).
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tests")]
import corpus_translate  # noqa: E402
from pixel_aot_draws.common import assembly, translate  # noqa: E402


def compile_hlsl(dxc, source, output):
    model = "ps_6_1" if "GetAttributeAtVertex" in source.read_text(encoding="utf-8") else "ps_6_0"
    return subprocess.run([dxc, "-Gis", "-T", model, "-E", "main", "-Fo", output, source],
                          capture_output=True, text=True)


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    dxc, work = argv[1], Path(argv[2])
    hlsl = work / "hlsl"
    hlsl.mkdir(parents=True, exist_ok=True)
    for stale in hlsl.glob("*.hlsl"):
        stale.unlink()

    control = work / "control.hlsl"
    control.write_text(translate(assembly(False)), encoding="utf-8")
    if (result := compile_hlsl(dxc, control, work / "control.cso")).returncode != 0:
        raise AssertionError(f"The pixel_aot reference program does not compile:\n{result.stderr}")
    broken = work / "control_broken.hlsl"
    broken.write_text(control.read_text(encoding="utf-8").replace("return", "return return", 1), encoding="utf-8")
    if compile_hlsl(dxc, broken, work / "control_broken.cso").returncode == 0:
        raise AssertionError("DXC accepted a source with a syntax error; the compile check would prove nothing")

    rows = corpus_translate.run(corpus_translate.ISA, corpus_translate.all_covered(corpus_translate.SHADERS,
                                                                                  corpus_translate.STATUS), hlsl)
    if len(rows) != 250:
        raise AssertionError(f"Expected the 250 corpus pixel shaders in {corpus_translate.ISA}, found {len(rows)}")
    failures = []
    for source in sorted(hlsl.glob("*.hlsl")):
        result = compile_hlsl(dxc, source, source.with_suffix(".cso"))
        if result.returncode != 0:
            failures.append(f"{source.name}:\n{result.stderr.strip()}")
    translated = sum(r["status"] == "translated" for r in rows)
    covered = [r for r in rows if r["covered"]]
    print(f"corpus pixel shaders {len(rows)}; translated {translated}; all_covered {len(covered)}; "
          f"all_covered_translated {sum(r['status'] == 'translated' for r in covered)}; "
          f"compiled {translated - len(failures)} of {translated}")
    summary = ROOT / "docs" / "coverage" / "corpus-translate.tsv"
    if summary.read_text(encoding="utf-8") != corpus_translate.summary(rows):
        print(f"note: {summary.relative_to(ROOT)} differs from this run; regenerate it with "
              "python tools/corpus_translate.py --summary docs/coverage/corpus-translate.tsv")
    if failures:
        print("\n\n".join(failures), file=sys.stderr)
        print(f"{len(failures)} translated corpus shaders failed to compile", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
