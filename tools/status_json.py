"""Build site/status.json for the public status page.

Usage:
    python tools/status_json.py --junit out/test-results.xml --coverage out/coverage.json --out site/status.json
        [--records out/build/dev/form_coverage] [--junit out/rerun-results.xml ...]

Inputs: one or more CTest JUnit files (repeat --junit: results merge by test name and a later file
overrides an earlier one, so a serial rerun of tests that timed out replaces their first result), the
JSON written by `tools/form_coverage.py --json`, the shader translation records those runs wrote
(--records, default out/build/dev/form_coverage), the corpus header in
docs/coverage/corpus-gfx1013.tsv, docs/status-parts.json and the Git HEAD of this repository.
Exits with 2 and writes nothing when any input is missing or unreadable, so a stale file is never
half-updated. Python standard library only.

Schema 3 adds gfx1013.forms: one {name, group, covered} entry per form of docs/coverage/gfx1013.tsv,
covered exactly as tools/form_coverage.py counts it (a record from these runs whose test passed).
The per-group totals must match the coverage file, so the list and the counts never disagree.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import form_coverage  # noqa: E402

CORPUS = Path("docs/coverage/corpus-gfx1013.tsv")
PARTS = Path("docs/status-parts.json")
STATES = ("done", "partial", "not_started")
ADAPTERS = ["NVIDIA GeForce RTX 4070 Ti", "WARP"]
STAGES = ("pixel", "vertex", "compute", "other")
STAGES_SUPPORTED = ["pixel"]  # shader stages the converter handles today; edit by hand when another lands


class InputError(Exception):
    pass


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InputError(f"cannot read {path}: {error}")


def junit_paths(junit):
    """One path or several; several are merged by test name, later files overriding earlier ones."""
    paths = [junit] if isinstance(junit, (str, Path)) else list(junit)
    if not paths:
        raise InputError("no JUnit file given")
    return paths


def read_junit(junit):
    """Pass/fail/skip counts over the merged results. run_at is the first file's start, the main run."""
    states, run_at = {}, None
    for path in junit_paths(junit):
        try:
            suite = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as error:
            raise InputError(f"cannot read {path}: {error}")
        if run_at is None:
            run_at = suite.get("timestamp")
        for case in suite.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                state = "failed"
            elif case.get("status") == "notrun" or case.find("skipped") is not None:
                state = "skipped"
            elif case.get("status") == "run":
                state = "passed"
            else:
                state = "failed"
            states.pop(case.get("name"), None)  # a rerun replaces the earlier result
            states[case.get("name")] = state
    counts = {k: sum(v == k for v in states.values()) for k in ("passed", "failed", "skipped")}
    counts["total"] = sum(counts.values())
    counts["run_at"] = run_at
    return counts


def read_corpus(root):
    path = root / CORPUS
    try:
        header = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("#")]
    except OSError as error:
        raise InputError(f"cannot read {path}: {error}")
    text = "\n".join(header)
    uses = re.search(r"Uses of covered forms: (\d+) of (\d+)", text)
    shaders = re.search(r"Corpus: (\d+) shaders", text)
    if not uses or not shaders:
        raise InputError(f"{path} has no 'Corpus' and 'Uses of covered forms' header lines")
    covered, total = int(uses[1]), int(uses[2])
    if total == 0:
        raise InputError(f"{path} reports zero instruction uses")
    stages = {}
    for m in re.finditer(r"Stage (\w+): shaders (\d+); all_covered (\d+); translatable_bound (\d+)\.", text):
        stages[m[1]] = {"shaders": int(m[2]), "all_covered": int(m[3]), "translatable_bound": int(m[4])}
    if set(stages) != set(STAGES):
        raise InputError(f"{path} lacks '# Stage <name>: ...' lines for {', '.join(STAGES)}")
    blocking = [{"form": m[1], "shaders": int(m[2])}
                for m in re.finditer(r"Blocking form (\S+): (\d+) shaders", text)][:5]
    return {"corpus_shaders": int(shaders[1]), "uses_covered": covered, "uses_total": total,
            "uses_percent": round(100 * covered / total, 1)}, \
           {"shaders": int(shaders[1]), "stages": {k: stages[k] for k in STAGES},
            "uses_percent": round(100 * covered / total, 1), "blocking_forms": blocking}


def read_parts(root):
    parts = read_json(root / PARTS).get("parts")
    if not isinstance(parts, list) or not parts:
        raise InputError(f"{PARTS} has no parts")
    for part in parts:
        if set(part) != {"name", "state", "note"} or part["state"] not in STATES:
            raise InputError(f"{PARTS}: bad part {part!r}")
    return parts


def read_git(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h%n%H%n%cI"],
                             check=True, capture_output=True, text=True).stdout.split()
    except (OSError, subprocess.CalledProcessError) as error:
        raise InputError(f"cannot read git HEAD: {error}")
    return {"short": out[0], "full": out[1], "time": out[2]}


def read_forms(junit, records, root=ROOT):
    """[{name, group, covered}] for every gfx1013 reference form, in reference-file order."""
    records = Path(records)
    if not records.is_dir() or not any(records.glob("*.txt")):
        raise InputError(f"no form-coverage records in {records} (run the CTest suite first, or pass --records)")
    path = root / "docs" / "coverage" / "gfx1013.tsv"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        results, start, end = {}, None, None
        for path in junit_paths(junit):  # later files override earlier ones; records may come from any run
            more, (lo, hi) = form_coverage.read_results(path)
            results.update(more)
            start, end = (lo, hi) if start is None else (min(start, lo), max(end, hi))
        accepted = form_coverage.read_records(records, (start, end))
    except (OSError, ValueError, TypeError, ET.ParseError) as error:
        raise InputError(f"cannot read form coverage inputs: {error}")
    reference = [tuple(line.split("\t")) for line in lines if line and not line.startswith("#")]
    if not reference or any(len(form) != 2 for form in reference):
        raise InputError(f"{path} is not a two-column form list")
    covered = set()
    for test, mnemonics in accepted.items():
        if form_coverage.fixture_status(results, [test]) == "pass":
            covered |= form_coverage.gfx_forms(mnemonics, set(reference))
    return [{"name": name, "group": group, "covered": (group, name) in covered} for group, name in reference]


def check_forms(forms, groups):
    counts = {}
    for f in forms:
        c = counts.setdefault(f["group"], [0, 0])
        c[0] += f["covered"]
        c[1] += 1
    expected = {g["name"]: [g["covered"], g["total"]] for g in groups}
    if counts != expected:
        diff = sorted(n for n in set(counts) | set(expected) if counts.get(n) != expected.get(n))
        raise InputError("form records disagree with the coverage file for " + ", ".join(diff)
                         + " (were both written by the same test run?)")


def build(junit, coverage, root=ROOT, records=form_coverage.RECORDS):
    cov = read_json(coverage)
    try:
        gfx, x64 = cov["gfx1013"], cov["x64_zen2"]
        groups = [{"name": n, "covered": g["covered"], "total": g["total"]}
                  for n, g in sorted(gfx["groups"].items())]
        forms = {"forms_covered": gfx["covered"], "forms_total": gfx["total"], "groups": groups}
        cpu = {"covered": x64["covered"], "total": x64["total"]}
    except (KeyError, TypeError, AttributeError) as error:
        raise InputError(f"{coverage} lacks gfx1013 or x64_zen2 data: {error}")
    tests = read_junit(junit)
    tests["adapters"] = ADAPTERS
    if forms["forms_total"] <= 0:
        raise InputError(f"{coverage} reports zero gfx1013 forms")
    forms["forms_percent"] = round(100 * forms["forms_covered"] / forms["forms_total"], 1)
    forms["forms"] = read_forms(junit, records, root)
    check_forms(forms["forms"], groups)
    legacy, corpus = read_corpus(root)  # legacy fields stay in gfx1013 so a schema-1 page still works
    return {
        "schema": 3,
        "commit": read_git(root),
        "tests": tests,
        "gfx1013": {**forms, **legacy},
        "corpus": corpus,
        "stages_supported": list(STAGES_SUPPORTED),
        "x64": cpu,
        "parts": read_parts(root),
    }


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--junit", type=Path, required=True, action="append",
                        help="CTest JUnit file; repeat it to merge reruns (later files override earlier ones by test name)")
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--records", type=Path, default=form_coverage.RECORDS,
                        help="directory of shader translation records (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        data = build(args.junit, args.coverage, ROOT, args.records)
    except InputError as error:
        print(f"status_json: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
