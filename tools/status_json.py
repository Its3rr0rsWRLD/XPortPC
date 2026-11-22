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
Schema 4 adds x64.forms: one {name, covered} entry per form of docs/coverage/x64_zen2.tsv, covered
when a tests/cpu/*.asm fixture whose mapped test (form_coverage.CPU_FIXTURES) passed uses it.
Next to --out the tool also keeps history.json (override with --history): a JSON array of
{"t": ISO UTC time, "covered": gfx+x64 covered forms, "total": gfx+x64 total}, the same combined number
the page's figure shows, at most one point per UTC hour (the latest run in an hour replaces earlier ones),
capped at HISTORY_MAX points. A malformed history file is reset rather than trusted.
The per-group (gfx) and overall (x64) totals must match the coverage file, so the lists and the counts
never disagree.
"""

import argparse
from datetime import datetime, timezone
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
CORPUS_SHADERS = Path("docs/coverage/corpus-shaders.tsv")  # per shader: stage, name, branches (0/1), forms
PARTS = Path("docs/status-parts.json")
STATES = ("done", "partial", "not_started")
ADAPTERS = ["NVIDIA GeForce RTX 4070 Ti", "WARP"]
STAGES = ("pixel", "vertex", "compute", "other")
STAGES_SUPPORTED = ["pixel"]  # shader stages the converter handles today; edit by hand when another lands


HISTORY_MAX = 2000


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


def read_run(junit):
    """form_coverage's per-test status merged over the JUnit files (later files override earlier ones),
    and the window spanning all of them, since records may come from any of the runs."""
    results, start, end = {}, None, None
    for path in junit_paths(junit):
        more, (lo, hi) = form_coverage.read_results(path)
        results.update(more)
        start, end = (lo, hi) if start is None else (min(start, lo), max(end, hi))
    return results, (start, end)


def read_x64_forms(junit, root=ROOT, records=None):
    """[{name, covered}] for every x64 reference form, covered exactly as tools/form_coverage.py counts
    it: the forms of a tests/cpu/*.asm fixture (its source, or its translation record) whose test passed."""
    path = root / "docs" / "coverage" / "x64_zen2.tsv"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        results, window = read_run(junit)
        accepted = form_coverage.read_records(records, window) if records and Path(records).is_dir() else {}
        cpu, _ = form_coverage.x64_fixtures(results, root, accepted)
    except (OSError, ValueError, TypeError, ET.ParseError) as error:
        raise InputError(f"cannot read x64 coverage inputs: {error}")
    reference = [tuple(line.split("\t")) for line in lines if line and not line.startswith("#")]
    if not reference or any(len(form) != 2 for form in reference):
        raise InputError(f"{path} is not a two-column form list")
    covered = set()
    for forms, status in cpu.values():
        if status == "pass":
            covered |= form_coverage.x64_forms(forms, set(reference))
    return [{"name": name, "covered": (group, name) in covered} for group, name in reference]


def read_forms(junit, records, root=ROOT):
    """[{name, group, covered}] for every gfx1013 reference form, in reference-file order."""
    records = Path(records)
    if not records.is_dir() or not any(records.glob("*.txt")):
        raise InputError(f"no form-coverage records in {records} (run the CTest suite first, or pass --records)")
    path = root / "docs" / "coverage" / "gfx1013.tsv"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        results, window = read_run(junit)
        accepted = form_coverage.read_records(records, window)
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


def recount_corpus(root, covered):
    """Stage counts and blocking forms from the per-shader corpus file and the forms covered by this run, so they
    never lag behind the coverage. Returns None when the file is absent (the TSV header values then stand).
    A form written with a leading '!' is a mnemonic outside the reference list, which no test can cover."""
    path = root / CORPUS_SHADERS
    if not path.exists():
        return None
    stages = {s: {"shaders": 0, "all_covered": 0, "translatable_bound": 0} for s in STAGES}
    blocking = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 4 or parts[0] not in stages or parts[2] not in ("0", "1"):
            raise InputError(f"{path}:{number}: expected stage, name, 0 or 1, forms")
        missing = [f for f in parts[3].split() if f.startswith("!") or f not in covered]
        row = stages[parts[0]]
        row["shaders"] += 1
        if not missing:
            row["all_covered"] += 1
            row["translatable_bound"] += parts[2] == "0"
        elif parts[0] == "pixel" and len(missing) == 1 and not missing[0].startswith("!"):
            blocking[missing[0]] = blocking.get(missing[0], 0) + 1
    top = sorted(blocking.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return stages, [{"form": f, "shaders": n} for f, n in top]


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
    cpu["forms"] = read_x64_forms(junit, root, records)
    if [sum(f["covered"] for f in cpu["forms"]), len(cpu["forms"])] != [cpu["covered"], cpu["total"]]:
        raise InputError("x64 fixtures disagree with the coverage file (were both written by the same test run?)")
    legacy, corpus = read_corpus(root)  # legacy fields stay in gfx1013 so a schema-1 page still works
    recount = recount_corpus(root, {f["name"] for f in forms["forms"] if f["covered"]})
    if recount:
        corpus["stages"], corpus["blocking_forms"] = recount
    return {
        "schema": 4,
        "commit": read_git(root),
        "tests": tests,
        "gfx1013": {**forms, **legacy},
        "corpus": corpus,
        "stages_supported": list(STAGES_SUPPORTED),
        "x64": cpu,
        "parts": read_parts(root),
    }


def history_point(data, now=None):
    """The combined gfx+x64 number the page's figure shows, stamped with now (UTC)."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {"t": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "covered": data["gfx1013"]["forms_covered"] + data["x64"]["covered"],
            "total": data["gfx1013"]["forms_total"] + data["x64"]["total"]}


def _valid_point(p):
    if not isinstance(p, dict) or not isinstance(p.get("t"), str):
        return False
    try:
        datetime.strptime(p["t"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    c, t = p.get("covered"), p.get("total")
    return all(isinstance(v, int) and not isinstance(v, bool) for v in (c, t)) and 0 <= c <= t and t > 0


def read_history(path):
    """Points from an existing history file; [] when it is absent, and also when it is not a list of valid
    points, so one bad write never blocks the next status update."""
    try:
        points = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        print(f"status_json: {path} is unreadable; starting a new history", file=sys.stderr)
        return []
    if not isinstance(points, list) or not all(_valid_point(p) for p in points):
        print(f"status_json: {path} is malformed; starting a new history", file=sys.stderr)
        return []
    return points


def update_history(path, point):
    """Append point, or replace the earlier point of the same UTC hour; keep the newest HISTORY_MAX."""
    points = [p for p in read_history(path) if p["t"][:13] != point["t"][:13]]
    points.append(point)
    points.sort(key=lambda p: p["t"])
    points = points[-HISTORY_MAX:]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{k: p[k] for k in ("t", "covered", "total")} for p in points],
                               separators=(",", ":")).replace("},{", "},\n{") + "\n", encoding="utf-8")
    return points


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--junit", type=Path, required=True, action="append",
                        help="CTest JUnit file; repeat it to merge reruns (later files override earlier ones by test name)")
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--records", type=Path, default=form_coverage.RECORDS,
                        help="directory of shader translation records (default: %(default)s)")
    parser.add_argument("--history", type=Path,
                        help="progress history file (default: history.json next to --out)")
    args = parser.parse_args(argv)
    try:
        data = build(args.junit, args.coverage, ROOT, args.records)
    except InputError as error:
        print(f"status_json: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    update_history(args.history or args.out.with_name("history.json"), history_point(data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
