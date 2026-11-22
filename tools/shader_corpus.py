"""Count which gfx1013 instruction forms a corpus of compiled shaders uses.

Usage:
    python tools/shader_corpus.py ISA_DIR [--out docs/coverage/corpus-gfx1013.tsv] [--covered FILE]

ISA_DIR holds one ISA dump per shader in a stage subdirectory (vertex, pixel, compute, other), for example
RADV_DEBUG=shaders output reduced to the "disasm:" body (LLVM-style text: v_add_f32_e32, v_mad_f32, ...).
Each mnemonic is mapped to reference forms exactly as tools/form_coverage.py does (gfx_forms: _e32 is the plain
encoding, _e64 is VOP3, _dpp/_sdwa names are kept), so one mnemonic can select several forms (DPP8 and DPP16
share a name). A mnemonic with no reference form is reported under encoding UNMAPPED.

Output columns: form, encoding, shaders_using, total_uses, then shaders and uses per stage, then covered_now
(yes/no, or empty when --covered is not given). --covered FILE is whitespace-separated mnemonics, such as a
form_coverage record file (<build>/form_coverage/<test>.txt); several files may be given.

The header comments carry the corpus summary: shader counts per stage, the share of shaders with a branch
(s_cbranch_*, s_branch), a loop (a branch to a block at or before itself), or an exec-mask write, and the
share of instruction uses whose form is covered. Per-shader measures follow, one stable line per stage:
"# Stage pixel: shaders 250; all_covered 39; translatable_bound 16." all_covered counts shaders whose every form is
covered (needs --covered); translatable_bound counts those that also have no branch and no exec-mask change (an
instruction writing exec other than "s_wqm_b64 exec, exec"). "# Blocking form <name>: <n> shaders" lines list the
forms that are the only uncovered form in a pixel shader, most shaders first (top 10). Python standard library only.
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import form_coverage  # noqa: E402

STAGES = ("pixel", "vertex", "compute", "other")
LABEL = re.compile(r"^BB(\d+):")


def parse(path):
    """(mnemonics, branch, loop, exec) of one ISA dump. Lines: '\\tmnemonic operands ; hex', 'BBn:' labels."""
    mnemonics, branch, loop, execw = [], False, False, False
    block = 0
    parse.exec_change = False
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = LABEL.match(raw)
        if m:
            block = int(m.group(1))
            continue
        if not raw.startswith(("\t", " ")):
            continue
        text = raw.split(";", 1)[0].strip()
        if not text:
            continue
        rep = re.match(r"\(then repeated (\d+) times?\)$", text)  # RADV collapses identical consecutive lines
        if rep:
            mnemonics.extend([mnemonics[-1]] * int(rep.group(1)))
            continue
        mnemonic, _, operands = text.partition(" ")
        mnemonics.append(mnemonic)
        if mnemonic.startswith("s_cbranch") or mnemonic == "s_branch":
            branch = True
            t = re.search(r"BB(\d+)", operands)
            if t and int(t.group(1)) <= block:
                loop = True
        first = operands.split(",", 1)[0].strip()
        if mnemonic.startswith("v_cmpx"):
            execw = True
            parse.exec_change = True
        if mnemonic.startswith("s_") and (first in ("exec", "exec_lo", "exec_hi") or "saveexec" in mnemonic
                                          or "wrexec" in mnemonic):
            execw = True
            if not (mnemonic == "s_wqm_b64" and [o.strip() for o in operands.split(",")[:2]] == ["exec", "exec"]):
                parse.exec_change = True
    return mnemonics, branch, loop, execw


parse.exec_change = False  # set by the last parse(): any exec write except "s_wqm_b64 exec, exec"


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("isa_dir", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "coverage" / "corpus-gfx1013.tsv")
    ap.add_argument("--covered", type=Path, nargs="*", default=[])
    args = ap.parse_args(argv)

    reference = form_coverage.load_reference("gfx1013.tsv")
    by_name = defaultdict(set)
    for form in reference:
        by_name[form[1]].add(form)
    covered = None
    if args.covered:
        words = set()
        for p in args.covered:
            words |= set(p.read_text(encoding="utf-8").split())
        covered = form_coverage.gfx_forms(words, reference)

    shaders = Counter()
    flags = defaultdict(Counter)
    all_covered, bound, blocking = Counter(), Counter(), Counter()
    uses = defaultdict(Counter)       # form -> Counter of "uses:stage"
    users = defaultdict(Counter)      # form -> Counter of "shaders:stage"
    for stage in STAGES:
        for path in sorted((args.isa_dir / stage).glob("*.s")):
            mnemonics, branch, loop, execw = parse(path)
            exec_change = parse.exec_change
            shaders[stage] += 1
            for key, on in (("branch", branch), ("loop", loop), ("exec", execw)):
                flags[stage][key] += on
            seen = set()
            for mn in mnemonics:
                wanted = mn if mn.endswith("_e64") else mn.removesuffix("_e32")
                forms = by_name.get(wanted) or {("UNMAPPED", mn)}
                for form in forms:
                    uses[form][stage] += 1
                    seen.add(form)
            for form in seen:
                users[form][stage] += 1
            if covered is not None:
                missing = [f for f in seen if f not in covered]
                if not missing:
                    all_covered[stage] += 1
                    if not branch and not exec_change:
                        bound[stage] += 1
                elif len(missing) == 1 and stage == "pixel":
                    blocking[missing[0][1]] += 1

    total_uses = sum(sum(c.values()) for c in uses.values())
    covered_uses = sum(sum(c.values()) for f, c in uses.items() if covered is not None and f in covered)
    n = sum(shaders.values()) or 1
    lines = [f"# Corpus: {sum(shaders.values())} shaders (" + ", ".join(f"{s} {shaders[s]}" for s in STAGES) + ")."]
    for key in ("branch", "loop", "exec"):
        k = sum(flags[s][key] for s in STAGES)
        per = ", ".join(f"{s} {flags[s][key]}/{shaders[s]}" for s in STAGES if shaders[s])
        lines.append(f"# Shaders with {key}: {k} of {sum(shaders.values())} ({100 * k / n:.1f}%); {per}.")
    lines.append(f"# Instruction uses: {total_uses}; forms seen {len(uses)}; forms in reference {len(reference)}.")
    if covered is not None:
        lines.append(f"# Uses of covered forms: {covered_uses} of {total_uses} ({100 * covered_uses / max(total_uses, 1):.1f}%)"
                     f"; reference forms covered: {len(covered)}.")
    if covered is not None:
        for stage in STAGES:
            lines.append(f"# Stage {stage}: shaders {shaders[stage]}; all_covered {all_covered[stage]}; "
                         f"translatable_bound {bound[stage]}.")
        for name, k in sorted(blocking.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
            lines.append(f"# Blocking form {name}: {k} shaders")
    header = ["form", "encoding", "shaders_using", "total_uses"]
    for s in STAGES:
        header += [f"{s}_shaders", f"{s}_uses"]
    header.append("covered_now")
    rows = []
    for form, c in uses.items():
        enc, name = form
        row = [name, enc, sum(users[form].values()), sum(c.values())]
        for s in STAGES:
            row += [users[form][s], c[s]]
        row.append("" if covered is None else ("yes" if form in covered else "no"))
        rows.append(row)
    rows.sort(key=lambda r: (-r[2], -r[3], r[0], r[1]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n" + "\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(map(str, r)) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
