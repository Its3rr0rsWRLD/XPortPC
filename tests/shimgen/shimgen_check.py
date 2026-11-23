"""Pure-Python checks of tools/shimgen.py (no Windows needed).

- the checked-in src/gdk/x2w_gdk_impl.h matches the specs;
- a synthetic x2w-report: DLLs the title ships, Windows-named DLLs and hand-written shims are skipped, the
  rest generated; spec'd functions become impl/stub bodies with doc links, others untyped stubs (E_NOTIMPL
  for *Async names), ordinals NONAME exports;
- an override forces a stub with its own return value and declares an unknown function;
- every spec function has a doc URL on learn.microsoft.com, and every impl function is defined in src/gdk.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "shimgen.py"
sys.path.insert(0, str(ROOT / "tools"))
import shimgen  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, "-B", str(TOOL), *map(str, args)], capture_output=True, text=True,
                          check=True).stdout


def report(rows):
    return {"schema": "x2w-report 1", "imports": [
        {"dll": dll, "function": fn, "kind": "import", "class": cls, "route": route} for dll, fn, cls, route in rows]}


def main():
    print(run("--impl-header", "--check"), end="")
    specs = shimgen.Specs([shimgen.SPEC_DIR])
    sources = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "gdk").glob("*.cpp"))
    for spec in specs.functions.values():
        assert spec.doc_url(specs.families).startswith("https://learn.microsoft.com/"), spec.name
        if spec.impl:
            assert re.search(rf"\bx2w_impl_{spec.name}\(", sources), f"no definition of x2w_impl_{spec.name}"
            assert spec.doc_url(specs.families) in sources, f"x2w_impl_{spec.name} does not cite its doc page"

    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        rows = [("consolert.dll", "XTaskQueueCreate", "missing", "none"),
                ("consolert.dll", "XUserGetTokenAndSignatureAsync", "missing", "none"),
                ("consolert.dll", "SomethingPrivate", "missing", "none"),
                ("consolert.dll", "#12", "missing", "none"),
                ("consolert.dll", "XSystemGetAppSpecificDeviceId", "missing", "none"),
                ("consolert.dll", "XUserGetMaxUsers", "missing", "none"),
                ("consolert.dll", "??0Mangled@@QEAA@XZ", "missing", "none"),
                ("libhttpclient.dll", "HCInitialize", "package", "package"),
                ("kernel32.dll", "Sleep", "windows", "windows"),
                ("xmem.dll", "XMemAlloc", "implemented", "shim")]
        (scratch / "report.json").write_text(json.dumps(report(rows)), encoding="utf-8")
        (scratch / "override.toml").write_text(
            'family = "title"\n[[functions]]\nname = "XUserGetMaxUsers"\nmode = "stub"\nstub_return = "S_FALSE"\n'
            '[[functions]]\nname = "SomethingPrivate"\nreturns = "int32_t"\nparams = "int32_t x"\n'
            'stub_return = "7"\n', encoding="utf-8")
        out = scratch / "gen"
        text = run("--report", scratch / "report.json", "--override", scratch / "override.toml", "--out", out)
        assert "skip libhttpclient.dll" in text and "skip kernel32.dll" in text and "skip xmem.dll" in text, text
        summary = json.loads((out / "shimgen.json").read_text(encoding="utf-8"))
        assert list(summary["dlls"]) == ["consolert.dll"], summary["dlls"].keys()
        entry = summary["dlls"]["consolert.dll"]
        bodies = {r["function"]: r["body"] for r in entry["functions"]}
        assert bodies == {"XTaskQueueCreate": "impl", "XUserGetTokenAndSignatureAsync": "unknown",
                          "SomethingPrivate": "stub", "#12": "unknown", "XSystemGetAppSpecificDeviceId": "stub",
                          "XUserGetMaxUsers": "stub"}, bodies
        assert entry["skipped"] == ["??0Mangled@@QEAA@XZ"]
        cpp = (out / "consolert.cpp").read_text(encoding="utf-8")
        definition = (out / "consolert.def").read_text(encoding="utf-8")
        assert "return x2w_impl_XTaskQueueCreate(workDispatchMode, completionDispatchMode, queue);" in cpp
        assert "xtaskqueue/functions/xtaskqueuecreate" in cpp
        assert "untyped stub returns E_NOTIMPL" in cpp and "static_cast<ULONG>(E_NOTIMPL)" in cpp
        assert "if (appSpecificDeviceIdUsed) *appSpecificDeviceIdUsed = {};" in cpp
        assert "memset(appSpecificDeviceId, 0, appSpecificDeviceIdSize);" in cpp
        assert "return S_FALSE;" in cpp and "return 7;" in cpp
        assert "x2w_export_ordinal_12 @12 NONAME" in definition
        assert definition.startswith("LIBRARY consolert\nEXPORTS\n    x2w_shimgen_dll = ")
        assert 'x2w_generated_shim(x2w_shim_consolert "consolert"' in (out / "shims.cmake").read_text(encoding="utf-8")
        # Only --include generates a DLL a route already provides.
        run("--report", scratch / "report.json", "--include", "kernel32.dll", "--dll", "kernel32.dll", "--out", out)
        assert "kernel32.dll" in json.loads((out / "shimgen.json").read_text(encoding="utf-8"))["dlls"]
        # A run log's dynamic resolves of shim or missing names.
        (scratch / "run.log").write_text("dynamic-load xgameruntime.dll -> shim\n"
                                         "dynamic-resolve xgameruntime.dll!XUserAddAsync -> shim\n"
                                         "dynamic-resolve xgameruntime.dll!QueryApiImpl -> missing\n"
                                         "dynamic-resolve kernel32.dll!Sleep -> windows\n", encoding="utf-8")
        run("--run-log", scratch / "run.log", "--out", out)
        summary = json.loads((out / "shimgen.json").read_text(encoding="utf-8"))
        assert list(summary["dlls"]) == ["xgameruntime.dll"]
        assert [r["function"] for r in summary["dlls"]["xgameruntime.dll"]["functions"]] == ["XUserAddAsync", "QueryApiImpl"]
    print("shimgen: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
