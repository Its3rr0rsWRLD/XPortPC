"""Compile shader sources to gfx1013 ISA through RADV's null winsys; one ISA dump per shader.
Usage: build_corpus.py <source-name> <shader-root> <work-dir> <isa-out-dir> [--ext e1,e2] [--inc dir]...
Layout of the output: <isa-out-dir>/<stage>/<id>.s (stage = vertex|pixel|compute|other)."""
import hashlib, json, os, re, subprocess, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reflect as R

PIPE = os.path.join(HERE, "pipe")
ENV = dict(os.environ, XDG_RUNTIME_DIR="/tmp/xdg", RADV_FORCE_FAMILY="GFX1013", RADV_DEBUG="shaders,nocache",
           VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/radeon_icd.json")
if os.environ.get("NONGG"): ENV["RADV_DEBUG"] += ",nongg"
STAGES = {"vert": "vertex", "frag": "pixel", "comp": "compute", "geom": "other", "tesc": "other", "tese": "other"}
HDR = {"Vertex Shader": "vertex", "Pixel Shader": "pixel", "Compute Shader": "compute", "Geometry Shader": "other",
       "Tessellation Control Shader": "other", "Tessellation Evaluation Shader": "other", "Vertex Shader as ES": "other",
       "Vertex Shader as LS": "other", "Vertex Shader as VS": "vertex", "NGG Shader": "ngg"}

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop("timeout", 120), **kw)

def split_sections(text):
    """[(header, isa-lines)] from RADV_DEBUG=shaders stderr: header line then 'disasm:' then body until blank."""
    lines = text.splitlines(); out = []; i = 0
    while i < len(lines):
        if lines[i].strip() == "disasm:" and i > 0:
            hdr = lines[i - 1].strip(); i += 1; body = []
            while i < len(lines) and lines[i].strip():
                body.append(lines[i]); i += 1
            out.append((hdr, body))
        i += 1
    return out

def main():
    name, root, work, isa_out = sys.argv[1:5]
    exts = ["vert", "frag", "comp", "geom", "tesc", "tese"]; incs = []; skipdirs = []
    a = sys.argv[5:]
    while a:
        k = a.pop(0)
        if k == "--ext": exts = a.pop(0).split(",")
        elif k == "--inc": incs += ["-I" + a.pop(0)]
        elif k == "--skip": skipdirs.append(a.pop(0))
    work = os.path.abspath(work); isa_out = os.path.abspath(isa_out); root = os.path.abspath(root)
    os.makedirs(work, exist_ok=True)
    files = []
    for d, _, fs in os.walk(root):
        if any(s in d for s in skipdirs): continue
        for f in fs:
            e = f.rsplit(".", 1)[-1]
            if e in exts: files.append(os.path.join(d, f))
    files.sort()
    log = open(os.path.join(work, "log.jsonl"), "w")
    spv = {}  # path -> (spvpath, reflection)
    st = defaultdict(int)
    for p in files:
        e = p.rsplit(".", 1)[-1]
        rel = os.path.relpath(p, root)
        out = os.path.join(work, hashlib.md5(rel.encode()).hexdigest() + "." + e + ".spv")
        r = run(["glslangValidator", "-V", "--target-env", "vulkan1.3", *incs, p, "-o", out], cwd=work)
        if r.returncode:
            st["glslang_fail"] += 1; log.write(json.dumps({"f": rel, "err": "glslang", "msg": (r.stdout + r.stderr)[:300]}) + "\n"); continue
        try: ref = R.reflect(out)
        except Exception as ex:
            st["reflect_fail"] += 1; continue
        if ref["bad"] or any(m not in (0, 1, 2, 3, 4, 5) for m in ref["models"]):
            st["unsupported"] += 1; log.write(json.dumps({"f": rel, "err": "unsupported", "msg": str(ref["bad"] or ref["models"])}) + "\n"); continue
        spv[p] = (out, ref)
    # group into programs by (dir, stem)
    groups = defaultdict(dict)
    for p in spv:
        stem = p.rsplit(".", 1)[0]
        groups[stem][p.rsplit(".", 1)[-1]] = p
    for stem in list(groups):
        g = groups[stem]
        if "comp" in g and len(g) > 1:
            groups[stem + "#c"] = {"comp": g.pop("comp")}
    # frag-only: pair with a vertex shader of the same dir whose outputs cover its inputs
    vert_by_dir = defaultdict(list)
    for p in spv:
        if p.endswith(".vert"): vert_by_dir[os.path.dirname(p)].append(p)
    programs = []
    for stem, g in sorted(groups.items()):
        if "frag" in g and "vert" not in g and "comp" not in g:
            need = set(spv[g["frag"]][1]["vin"])
            cand = [v for v in vert_by_dir[os.path.dirname(stem)] if need <= set(spv[v][1]["fout"])]
            if cand: g = dict(g, vert=cand[0], _borrowed=cand[0])
            else: st["frag_unpaired"] += 1; log.write(json.dumps({"f": os.path.relpath(g["frag"], root), "err": "unpaired"}) + "\n"); continue
        programs.append(g)
    programs.sort(key=lambda g: 0 if "frag" in g else 1)  # paired first, so vertex ISA comes from the paired build
    done = set()
    for g in programs:
        members = [(e, p) for e, p in g.items() if e != "_borrowed"]
        spec = []; binds = {}; push = 0; vin = {}; fout = {}; depth = False
        order = ["vert", "tesc", "tese", "geom", "frag", "comp"]
        for e in order:
            if e in g:
                p = g[e]; out, ref = spv[p]; spec.append("stage %s %s" % (e, out))
                for s, b, t, c in ref["binds"]:
                    o = binds.get((s, b)); binds[(s, b)] = (t, max(c, o[1] if o else 0))
                push = max(push, ref["push"]); depth |= ref["depth"]
                if e == "vert": vin = ref["vin"]
                if e == "frag": fout = ref["fout"]
        if "tesc" in g and "tese" not in g or "tese" in g and "tesc" not in g:
            st["tess_incomplete"] += 1; continue
        for (s, b), (t, c) in sorted(binds.items()): spec.append("bind %d %d %d %d" % (s, b, t, c))
        if push: spec.append("push %d" % push)
        for l, t in vin.items(): spec.append("vin %s %s" % (l, t))
        for l, t in fout.items(): spec.append("fout %s %s" % (l, t))
        if depth or "frag" in g: spec.append("depth 1")
        if "frag" not in g and "comp" not in g: spec.append("rastdisc 1")
        stem = next(iter(members))[1].rsplit(".", 1)[0]
        specf = os.path.join(work, hashlib.md5(stem.encode()).hexdigest() + ".spec")
        open(specf, "w").write("\n".join(spec) + "\n")
        r = run([PIPE, specf], env=ENV)
        salvage = False
        if (r.returncode or "OK" not in r.stdout) and r.returncode == -11 and "s_endpgm" in r.stderr:
            salvage = True; st["salvaged_after_crash"] += 1
        if (r.returncode or "OK" not in r.stdout) and not salvage:
            st["pipeline_fail"] += 1
            log.write(json.dumps({"f": os.path.relpath(stem, root), "err": "pipeline", "rc": r.returncode, "msg": r.stderr[-300:]}) + "\n"); continue
        secs = split_sections(r.stderr)
        # attribute sections to member shaders by the header's stage prefix
        pre = [("Vertex Shader", "vert"), ("Tessellation Control", "tesc"), ("Tessellation Evaluation", "tese"),
               ("Geometry", "geom"), ("Pixel", "frag"), ("Compute", "comp")]
        exts_in = {e for e, _ in members}
        merged = bool(exts_in & {"tesc", "tese", "geom"})
        for hdr, body in secs:
            e = next((x for pfx, x in pre if hdr.startswith(pfx)), None)
            if e is None or e not in g:
                st["unknown_header"] += 1; log.write(json.dumps({"f": os.path.relpath(stem, root), "err": "hdr", "msg": hdr}) + "\n"); continue
            p = g[e]
            if p in done or (salvage and not body[-1].strip().startswith('s_endpgm')): continue
            done.add(p)
            k = "other" if (e == "vert" and merged) else STAGES[e]
            rel = os.path.relpath(p, root)
            dest = os.path.join(isa_out, k, name + "__" + rel.replace("/", "__") + ".s")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "w").write("# " + hdr + "\n" + "\n".join(body) + "\n")
            st["isa_" + k] += 1
        st["pipelines_ok"] += 0 if salvage else 1
    log.write(json.dumps({"summary": st}) + "\n")
    print(name, dict(st))

main()
