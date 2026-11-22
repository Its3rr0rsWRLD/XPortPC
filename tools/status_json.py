"""Build site/status.json for the public status page.

Usage:
    python tools/status_json.py --junit out/test-results.xml --coverage out/coverage.json --out site/status.json

Inputs: a CTest JUnit file, the JSON written by `tools/form_coverage.py --json`, the corpus header in
docs/coverage/corpus-gfx1013.tsv, docs/status-parts.json and the Git HEAD of this repository.
Exits with 2 and writes nothing when any input is missing or unreadable, so a stale file is never
half-updated. Python standard library only.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
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


def read_junit(path):
    try:
        suite = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise InputError(f"cannot read {path}: {error}")
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for case in suite.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            counts["failed"] += 1
        elif case.get("status") == "notrun" or case.find("skipped") is not None:
            counts["skipped"] += 1
        elif case.get("status") == "run":
            counts["passed"] += 1
        else:
            counts["failed"] += 1
    counts["total"] = sum(counts.values())
    counts["run_at"] = suite.get("timestamp")
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


def build(junit, coverage, root=ROOT):
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
    legacy, corpus = read_corpus(root)  # legacy fields stay in gfx1013 so a schema-1 page still works
    return {
        "schema": 2,
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
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        data = build(args.junit, args.coverage)
    except InputError as error:
        print(f"status_json: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
