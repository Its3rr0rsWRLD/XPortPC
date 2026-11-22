"""Measure what vertex-stage support needs from the shader corpus (design: docs/design/vertex-stage.md).

Usage:
    python tools/vertex_corpus_report.py [--shaders docs/coverage/corpus-shaders.tsv] [--status site/status.json]
                                         [--isa DIR ...] [--json OUT]

Two kinds of input:
- Forms (always): the per-shader forms of docs/coverage/corpus-shaders.tsv and the forms that site/status.json marks
  covered. From these: how many vertex shaders use only covered forms, the uncovered forms of the rest (how many shaders
  each blocks, and how many it blocks alone), a greedy order in which covering forms unlocks the most vertex shaders,
  and the forms that vertex shaders use but no pixel shader does. The counts agree with tools/status_json.py, which
  reads the same two files.
- Structure (optional, --isa DIR, repeatable): ISA dumps as tools/shader_corpus.py reads them, one directory per
  compile, with the vertex shaders in DIR/vertex/*.s and the header line "# Vertex Shader as VS" (legacy hardware VS)
  or "# Vertex Shader as ESGS" (NGG). Per directory: hardware stage, vertex fetch (buffer loads indexed by a VGPR with
  idxen, offset-only loads, typed loads, global loads), system-value VGPRs and user SGPRs read before written, exports
  (pos, param, prim), NGG messages, lane-cooperative operations (LDS, mbcnt, bcnt, readlane, permlane, DPP), embedded
  constants (s_getpc_b64), branches and image operations. Give the RADV "nongg" compile and an NGG compile of the same
  sources to compare them.

Python standard library only. Reads no game files; the corpus is the MIT/Apache set of docs/coverage/corpus-sources.md.
"""
import argparse
from collections import Counter, defaultdict
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import form_coverage  # noqa: E402
SHADERS = ROOT / "docs" / "coverage" / "corpus-shaders.tsv"
STATUS = ROOT / "site" / "status.json"

REG = re.compile(r"\b([sv])\[(\d+):(\d+)\]|\b([sv])(\d+)\b|\b(m0|exec|vcc|scc)\b")
# Operations that no single lane can compute for itself: an NGG shader that culls uses them to compact the
# surviving vertices across the wave (LDS, lane counts, cross-lane reads).
COOPERATIVE = re.compile(r"^(ds_|v_mbcnt|s_bcnt|v_readlane|v_readfirstlane|v_writelane|v_permlane|s_ff1|.*_dpp$|.*_sdwa$)")
NO_DEST = re.compile(r"^(exp|s_waitcnt|s_clause|s_endpgm|s_setprio|s_barrier|s_sendmsg|s_nop|s_cbranch|s_branch|"
                     r"s_cmp|s_bitcmp|v_cmp_.*_e32$|v_cmpx|buffer_store|global_store|tbuffer_store|image_store|"
                     r"s_store|s_buffer_store|s_dcache|s_icache|s_inst_prefetch)")


CARRY_OUT = re.compile(r"^v_(add|sub|subrev)_co(_ci)?_u32|^v_div_scale_|^v_mad_[iu]64_[iu]32")


class InputError(Exception):
    pass


def read_forms(shaders_path):
    """{stage: {shader: [forms]}} from corpus-shaders.tsv (stage, shader, branch flag, forms)."""
    stages = defaultdict(dict)
    for number, line in enumerate(Path(shaders_path).read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 4 or parts[2] not in ("0", "1"):
            raise InputError(f"{shaders_path}:{number}: expected stage, name, 0 or 1, forms")
        stages[parts[0]][parts[1]] = {"branch": parts[2] == "1", "forms": parts[3].split()}
    return stages


def read_covered(status_path):
    data = json.loads(Path(status_path).read_text(encoding="utf-8"))
    try:
        return {f["name"] for f in data["gfx1013"]["forms"] if f["covered"]}
    except (KeyError, TypeError) as e:
        raise InputError(f"{status_path} has no gfx1013.forms list") from e


def missing_forms(forms, covered):
    """Forms that block a shader. A leading '!' is a mnemonic outside the reference list, which no test can cover
    (the rule of tools/status_json.py recount_corpus)."""
    return sorted({f for f in forms if f.startswith("!") or f not in covered})


def greedy_unlock(missing, limit=12):
    """Order in which covering forms unlocks the most blocked shaders. Each step covers the form, or failing that the
    smallest remaining set of forms, that completes the most shaders; ties go to the form blocking more shaders, then
    to the name. Returns [(forms added, shaders unlocked by the step, cumulative)]."""
    remaining = {name: set(m) for name, m in missing.items() if m and not any(f.startswith("!") for f in m)}
    chosen, steps, total = set(), [], 0
    while remaining and len(steps) < limit:
        freq = Counter(f for m in remaining.values() for f in m - chosen)
        best, gain = None, 0
        for f, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
            g = sum(1 for m in remaining.values() if m <= chosen | {f})
            if g > gain:
                best, gain = {f}, g
        if best is None:  # no single form completes a shader: take the smallest set that does
            name = min(remaining, key=lambda n: (len(remaining[n] - chosen), n))
            best = remaining[name] - chosen
            gain = sum(1 for m in remaining.values() if m <= chosen | best)
        chosen |= best
        done = [n for n, m in remaining.items() if m <= chosen]
        for n in done:
            del remaining[n]
        total += len(done)
        steps.append((sorted(best), len(done), total))
    return steps


def form_report(stages, covered):
    vertex = stages.get("vertex", {})
    pixel_forms = {f for s in stages.get("pixel", {}).values() for f in s["forms"]}
    missing = {name: missing_forms(s["forms"], covered) for name, s in vertex.items()}
    blocked = {n: m for n, m in missing.items() if m}
    blocks, alone = Counter(), Counter()
    for m in blocked.values():
        blocks.update(m)
        if len(m) == 1:
            alone[m[0]] += 1
    vertex_only = Counter(f for s in vertex.values() for f in set(s["forms"]) if f not in pixel_forms)
    covered_n = len(vertex) - len(blocked)
    return {
        "vertex_shaders": len(vertex),
        "all_covered": covered_n,
        "all_covered_straight_line": sum(1 for n, s in vertex.items() if not missing[n] and not s["branch"]),
        "blocked": len(blocked),
        "blocked_by_count": dict(sorted(Counter(len(m) for m in blocked.values()).items())),
        "blocking_forms": [{"form": f, "shaders": n, "alone": alone[f]}
                           for f, n in sorted(blocks.items(), key=lambda kv: (-kv[1], kv[0]))],
        "greedy_unlock": [{"forms": f, "unlocks": g, "cumulative": c} for f, g, c in greedy_unlock(missing)],
        "vertex_only_forms": [{"form": f, "shaders": n, "covered": f in covered}
                              for f, n in sorted(vertex_only.items(), key=lambda kv: (-kv[1], kv[0]))],
        "blocked_shaders": {n: m for n, m in sorted(blocked.items())},
    }


def registers(operand):
    """Registers an operand string names, as 's12', 'v3', 'm0', 'exec', 'vcc', 'scc'."""
    out = []
    for m in REG.finditer(operand):
        if m.group(1):
            out += [f"{m.group(1)}{n}" for n in range(int(m.group(2)), int(m.group(3)) + 1)]
        elif m.group(4):
            out.append(f"{m.group(4)}{m.group(5)}")
        else:
            out.append(m.group(6))
    return out


def read_isa(path):
    """(header, items) of one dump: items are ("label", "BB3") and ("insn", "mnemonic operands") in program order."""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    header = lines[0][2:].strip() if lines and lines[0].startswith("# ") else ""
    items = []
    for raw in lines[1:]:
        if m := re.match(r"^(BB\d+):", raw):
            items.append(("label", m[1]))
            continue
        if not raw.startswith(("\t", " ")):
            continue
        text = " ".join(raw.split(";", 1)[0].split())
        if text and not text.startswith("("):  # "(then repeated N times)" repeats the previous line
            items.append(("insn", text))
    return header, items


NGG_PATTERNS = {
    "wave_id": r"s_and_b32 (s\d+), (s\d+), 0xf000000",
    "skip_alloc": r"s_cbranch_scc1 (BB\d+)",
    "alloc": [r"s_bfe_u32 (s\d+), (s\d+), 0x90016", r"s_lshl_b32 (s\d+), (s\d+), 12", r"s_bfe_u32 (s\d+), (s\d+), 0x9000c",
              r"s_or_b32 m0, (s\d+), (s\d+)", r"s_sendmsg sendmsg\(MSG_GS_ALLOC_REQ\)"],
    "prim_count": r"s_lshl_b32 (s\d+), (s\d+), 8",
    "vertex_count": r"s_pack_ll_b32_b16 (s\d+), 0, (s\d+)",
    "exec": r"s_bfe_u64 exec, -1, (s\d+)",
    "skip": r"s_cbranch_execz (BB\d+)",
    "prim": r"exp prim (v\d+), off, off, off done",
}


def ngg_passthrough(items):
    """Match the NGG passthrough frame RADV emits around a vertex shader on gfx10 and return its parts, or raise
    InputError naming the first difference. The frame (Mesa ac_nir / ACO NGG lowering, read from the dumps):
      s_barrier; wave_id = merged_wave_info & 0x0f000000; if wave_id == 0 { m0 = prims << 12 | verts from
      gs_tg_info bits [30:22] and [20:12]; s_sendmsg GS_ALLOC_REQ }
      exec = first (merged_wave_info >> 8) & 0x7f lanes: exp prim <payload VGPR>, off, off, off done
      exec = first merged_wave_info & 0x7f lanes: the vertex body (fetch, ALU, exp pos/param)
    The two exec regions come in either order. Passthrough means the primitive payload is the untouched input VGPR,
    so the primitive is the one the hardware assembled: on desktop the input assembler makes the same primitive and
    the frame is dropped. Anything else (culling, LDS, a payload computed by the shader) is refused."""
    insns = [t for k, t in items if k == "insn" and not t.startswith("s_setprio")]
    pos = 0

    def take(pattern, what):
        nonlocal pos
        if pos >= len(insns) or not (m := re.fullmatch(pattern, insns[pos])):
            got = insns[pos] if pos < len(insns) else "end of program"
            raise InputError(f"NGG frame: expected {what}, found {got}")
        pos += 1
        return m.groups()

    def skip_waits():
        nonlocal pos
        while pos < len(insns) and re.fullmatch(r"s_waitcnt expcnt\(0\)", insns[pos]):
            pos += 1

    take(r"s_barrier", "s_barrier")
    _, wave_info = take(NGG_PATTERNS["wave_id"], "the wave-id test")
    take(NGG_PATTERNS["skip_alloc"], "the branch around GS_ALLOC_REQ")
    tg_info = None
    for k, pattern in enumerate(NGG_PATTERNS["alloc"]):
        groups = take(pattern, "the GS_ALLOC_REQ block")
        if k == 0:
            tg_info = groups[1]
    roles = {"merged_wave_info": wave_info, "gs_tg_info": tg_info}
    regions = {}
    body_items = []
    while len(regions) < 2:
        skip_waits()
        if pos < len(insns) and re.fullmatch(NGG_PATTERNS["prim_count"], insns[pos]):
            kind = "prim"
            _, src = take(NGG_PATTERNS["prim_count"], "the primitive count")
        else:
            kind = "vertex"
            _, src = take(NGG_PATTERNS["vertex_count"], "the primitive or vertex count")
        if src != wave_info or kind in regions:
            raise InputError(f"NGG frame: {kind} count not from merged_wave_info or repeated")
        skip_waits()
        take(NGG_PATTERNS["exec"], "the exec mask from the count")
        take(NGG_PATTERNS["skip"], "the branch around the region")
        start = pos
        if kind == "prim":
            (payload,) = take(NGG_PATTERNS["prim"], "a single passthrough primitive export")
            roles["prim_payload"] = payload
        else:
            while pos < len(insns) and not (re.fullmatch(NGG_PATTERNS["prim_count"], insns[pos])
                                             or insns[pos] == "s_endpgm"):
                pos += 1
            body_items = insns[start:pos]
            while body_items and body_items[-1] == "s_waitcnt expcnt(0)":
                body_items.pop()
        regions[kind] = (start, pos)
    order = list(regions)
    if pos >= len(insns) or insns[pos] != "s_endpgm" or pos != len(insns) - 1:
        raise InputError("NGG frame: expected s_endpgm after the two regions")
    for t in body_items:
        mnemonic = t.split()[0]
        if COOPERATIVE.match(mnemonic) or mnemonic in ("s_barrier", "s_sendmsg") or t.startswith("exp prim"):
            raise InputError(f"NGG body: lane-cooperative or frame operation {t}")
    # The body may reuse the frame's registers once it has written them; it must not read their entry values.
    body = features(body_items)
    frame_inputs = set(body["inputs_sgpr"] + body["inputs_special"]) & {wave_info, tg_info, "m0"}
    if frame_inputs:
        raise InputError("NGG body: reads frame register " + ", ".join(sorted(frame_inputs)))
    if order[0] == "vertex" and roles["prim_payload"] in body["written"]:  # the payload must survive the body
        raise InputError(f"NGG body: overwrites the primitive payload {roles['prim_payload']} before its export")
    return {"order": order, "roles": roles, "body": body_items}


def features(insns):
    """Structural features of a list of instruction texts."""
    written, inputs = set(), []
    f = Counter()
    exports = Counter()
    fetch_bases = set()
    for text in insns:
        mnemonic, _, operands = text.partition(" ")
        ops = [o.strip() for o in operands.split(",")] if operands else []
        if mnemonic == "exp":
            target = operands.split()[0]
            kind = re.sub(r"\d+$", "", target)
            exports[target] += 1
            f[f"exp_{kind}"] += 1
            reads = registers(" ".join(operands.split()[1:]))
        elif re.match(r"v_cmp_.*_e32$", mnemonic) and ops and ops[0] == "vcc":  # vcc is printed but only written
            reads = registers(", ".join(ops[1:]))
        elif NO_DEST.match(mnemonic) or not ops:
            reads = registers(operands)
        elif CARRY_OUT.match(mnemonic):  # VOP3b: the second operand is the carry-out mask, also written
            reads = registers(", ".join(ops[2:]))
        else:
            reads = registers(", ".join(ops[1:]))
            if re.match(r"v_(f)?mac_|v_fmac_", mnemonic):
                reads += registers(ops[0])
        if mnemonic == "s_sendmsg":
            reads.append("m0")
            f["sendmsg:" + re.sub(r"^sendmsg\((\w+).*", r"\1", operands.strip()).lower()] += 1
        for r in reads:
            if r not in written and r != "scc" and r not in inputs:
                inputs.append(r)
        # An entry SGPR used as data rather than as a descriptor pointer, a copy or the base of the vertex index
        # (v_add_nc_u32 vD, sBase, vIndex): inline user data, such as push constants that RADV passes in SGPRs.
        data_reads = [r for r in reads if re.fullmatch(r"s\d+", r) and r not in written]
        if data_reads and not (re.match(r"s_(load|buffer_load)_|s_mov_b(32|64)$", mnemonic)
                               or re.fullmatch(r"v_add_nc_u32_e32 v\d+, s\d+, v\d+", text)):
            f["user_data_sgpr"] += 1
        if not (NO_DEST.match(mnemonic) or not ops or mnemonic == "exp"):
            written.update(registers(ops[0]))
            if CARRY_OUT.match(mnemonic) and len(ops) > 1:
                written.update(registers(ops[1]))
        if mnemonic.startswith("v_cmp_") and mnemonic.endswith("_e32"):
            written.add("vcc")
        if re.match(r"^(buffer|tbuffer)_load", mnemonic):
            mods = set(operands.split())
            kind = "typed" if "format" in mnemonic else "raw"
            how = "idxen" if "idxen" in mods else "offen" if "offen" in mods else "none"
            f[f"fetch_{kind}_{how}"] += 1
            if how == "idxen":
                fetch_bases.add(ops[1])
        elif mnemonic.startswith("global_load"):
            f["fetch_global"] += 1
        elif mnemonic.startswith("image_"):
            f["image"] += 1
        if mnemonic == "s_getpc_b64":
            f["getpc"] += 1
        if mnemonic.startswith(("s_cbranch", "s_branch")):
            f["branch"] += 1
        if COOPERATIVE.match(mnemonic):
            f["cooperative"] += 1
        if mnemonic == "s_barrier":
            f["barrier"] += 1
    return {
        "inputs_vgpr": [r for r in inputs if re.fullmatch(r"v\d+", r)],
        "inputs_sgpr": [r for r in inputs if re.fullmatch(r"s\d+", r)],
        "inputs_special": [r for r in inputs if r in ("m0", "exec", "vcc")],
        "written": sorted(written, key=lambda r: (r[0], int(r[1:]) if r[1:].isdigit() else -1)),
        "fetch_index_vgprs": sorted(fetch_bases),
        "exports": dict(sorted(exports.items())),
        "features": dict(sorted(f.items())),
    }


def isa_forms(insns, reference):
    """Form names as corpus-shaders.tsv writes them: _e32 dropped, _e64 kept, '!' before a non-reference mnemonic."""
    out = set()
    for t in insns:
        m = t.split()[0]
        w = m if m.endswith("_e64") else m.removesuffix("_e32")
        out.add(w if w in reference else "!" + w)
    return sorted(out)


def parse_isa(path, reference=None):
    """Structural features of one vertex ISA dump; for an NGG dump, also of the body inside the passthrough frame."""
    header, items = read_isa(path)
    insns = [t for k, t in items if k == "insn"]
    kind = "ngg" if "ESGS" in header else "legacy" if header.endswith("as VS") else header or "unknown"
    out = {"header": header, "kind": kind, **features(insns)}
    body = insns
    if kind == "ngg":
        try:
            frame = ngg_passthrough(items)
            out["ngg"] = {"passthrough": True, "order": frame["order"], "roles": frame["roles"]}
            body = [t for t in insns if t.startswith("s_setprio")] + frame["body"] + ["s_endpgm"]
            out["body"] = features(body)
        except InputError as e:
            out["ngg"] = {"passthrough": False, "reason": str(e)}
    if reference is not None:
        out["forms"] = isa_forms(insns, reference)
        out["body_forms"] = isa_forms(body, reference)
    return out


# Roles of the entry VGPRs of a vertex shader on gfx10, read from the dumps (the index added to a base SGPR before
# the idxen fetch) and from the Mesa VGPR layout: legacy hardware VS v0 = vertex id, v3 = instance id; NGG (ES part of
# a merged ESGS wave) v0..v4 = primitive payload and GS inputs, v5 = vertex id, v8 = instance id.
SYSTEM_VGPRS = {"legacy": {"v0": "vertex_id", "v3": "instance_id"},
                "ngg": {"v5": "vertex_id", "v8": "instance_id"}}
FORM_CARD_V5 = {"s_getpc_b64", "image_sample_lz", "s_cbranch_execz", "s_cbranch_vccz", "v_cmpx_le_f32",
                "v_cmpx_lt_f32_e64", "s_cselect_b64"}


def card(shader, covered):
    """The first card of docs/design/vertex-stage.md after which this shader can be translated, with the reasons
    that push it past V-1. 'refused' is a shader no card in the plan accepts (NGG culling or an unknown frame)."""
    why = []
    if shader["kind"] == "ngg":
        if not shader["ngg"]["passthrough"]:
            return "refused", [shader["ngg"]["reason"]]
        why.append(("V-2", "NGG passthrough frame"))
        body = shader["body"]
    elif shader["kind"] == "legacy":
        body = shader
    else:
        return "refused", [f"hardware stage {shader['kind']}"]
    roles = SYSTEM_VGPRS[shader["kind"]]
    feat = body["features"]
    for v in body["inputs_vgpr"]:
        role = roles.get(v)
        if role == "instance_id":
            why.append(("V-3", "instance id"))
        elif role != "vertex_id" and not (shader["kind"] == "ngg" and v == shader["ngg"]["roles"].get("prim_payload")):
            why.append(("refused", f"entry VGPR {v} with no known role"))
    if feat.get("user_data_sgpr"):
        why.append(("V-3", "inline user-data SGPRs"))
    if feat.get("fetch_raw_offen") or feat.get("fetch_raw_none") or feat.get("fetch_global"):
        why.append(("V-3", "storage-buffer or global loads"))
    if feat.get("fetch_typed_idxen") or feat.get("fetch_typed_offen") or feat.get("fetch_typed_none"):
        why.append(("V-3", "typed vertex fetch"))
    if any(t != "pos0" and not t.startswith("param") for t in body["exports"]):
        why.append(("V-3", "exports beyond pos0 and param"))
    if body["inputs_special"]:
        why.append(("V-5", "reads " + ", ".join(body["inputs_special"]) + " at entry"))
    missing = [f for f in shader.get("body_forms", []) if f.startswith("!") or f not in covered]
    for f in missing:
        why.append(("V-5" if f in FORM_CARD_V5 else "V-4", f"form {f}"))
    if feat.get("branch") and not any(c == "V-5" for c, _ in why):
        why.append(("V-5", "control flow"))
    if feat.get("getpc") or feat.get("image"):
        why.append(("V-5", "embedded constants or image access"))
    order = ["V-1", "V-2", "V-3", "V-4", "V-5", "refused"]
    worst = max((c for c, _ in why), key=order.index, default="V-1")
    return worst, sorted({w for _, w in why})


def isa_report(isa_dir, reference=None, covered=None):
    paths = sorted((Path(isa_dir) / "vertex").glob("*.s"))
    if not paths:
        raise InputError(f"{isa_dir}/vertex has no .s files")
    shaders = {p.name: parse_isa(p, reference) for p in paths}
    kinds = Counter(s["kind"] for s in shaders.values())
    cards, reasons = Counter(), Counter()
    whole_covered = body_covered = 0
    if covered is not None:
        for s in shaders.values():
            s["card"], s["card_reasons"] = card(s, covered)
            cards[s["card"]] += 1
            reasons.update(r for r in s["card_reasons"] if not r.startswith("form "))
            whole_covered += not [f for f in s["forms"] if f.startswith("!") or f not in covered]
            body_covered += not [f for f in s["body_forms"] if f.startswith("!") or f not in covered]
    has = Counter()
    vgprs, sgprs, special, params, pos = Counter(), Counter(), Counter(), Counter(), Counter()
    for s in shaders.values():
        feat = s["features"]
        for key in feat:
            has[key] += 1
        if not any(k.startswith(("fetch_raw", "fetch_typed", "fetch_global")) for k in feat):
            has["no_fetch"] += 1
        if feat.get("fetch_raw_idxen") and not any(k.startswith("fetch") and k != "fetch_raw_idxen" for k in feat):
            has["fetch_only_raw_idxen"] += 1
        vgprs.update(s["inputs_vgpr"])
        sgprs.update(s["inputs_sgpr"])
        special.update(s["inputs_special"])
        params[sum(1 for t in s["exports"] if t.startswith("param"))] += 1
        pos.update(t for t in s["exports"] if t.startswith("pos"))
    return {
        "dir": str(isa_dir),
        "vertex_shaders": len(shaders),
        "kinds": dict(sorted(kinds.items())),
        "shaders_with": dict(sorted(has.items())),
        "input_vgprs": dict(sorted(vgprs.items(), key=lambda kv: int(kv[0][1:]))),
        "input_sgprs": dict(sorted(sgprs.items(), key=lambda kv: int(kv[0][1:]))),
        "input_special": dict(sorted(special.items())),
        "param_exports": dict(sorted(params.items())),
        "pos_exports": dict(sorted(pos.items())),
        "ngg_passthrough": sum(1 for s in shaders.values() if s.get("ngg", {}).get("passthrough")),
        "ngg_refused": sorted({s["ngg"]["reason"] for s in shaders.values() if s.get("ngg", {}).get("passthrough") is False}),
        "only_covered_forms": whole_covered if covered is not None else None,
        "only_covered_forms_without_frame": body_covered if covered is not None else None,
        "cards": {c: cards[c] for c in ["V-1", "V-2", "V-3", "V-4", "V-5", "refused"] if cards[c]},
        "card_reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "shaders": shaders,
    }


def text_report(forms, isas):
    out = [f"Vertex shaders: {forms['vertex_shaders']}; only covered forms: {forms['all_covered']} "
           f"({forms['all_covered_straight_line']} without a branch); blocked: {forms['blocked']}.",
           "Blocked shaders by number of uncovered forms: "
           + ", ".join(f"{k}: {v}" for k, v in forms["blocked_by_count"].items()) + ".",
           "Uncovered forms (shaders blocked; blocked by this form alone):"]
    out += [f"  {b['form']}: {b['shaders']}; {b['alone']}" for b in forms["blocking_forms"]]
    out.append("Greedy unlock order (forms added: shaders unlocked, cumulative):")
    out += [f"  {' '.join(s['forms'])}: +{s['unlocks']}, {forms['all_covered'] + s['cumulative']}"
            for s in forms["greedy_unlock"]]
    out.append("Forms used by vertex shaders and by no pixel shader (shaders; covered):")
    out += [f"  {v['form']}: {v['shaders']}; {'yes' if v['covered'] else 'no'}" for v in forms["vertex_only_forms"]]
    for r in isas:
        out.append(f"ISA {r['dir']}: {r['vertex_shaders']} vertex shaders; kinds "
                   + ", ".join(f"{k} {v}" for k, v in r["kinds"].items()) + ".")
        if r["only_covered_forms"] is not None:
            out.append(f"  Only covered forms: {r['only_covered_forms']}; after removing an NGG passthrough frame: "
                       f"{r['only_covered_forms_without_frame']}. NGG passthrough frames: {r['ngg_passthrough']}.")
            out.append("  First card that translates the shader: " + ", ".join(f"{k} {v}" for k, v in r["cards"].items())
                       + "; structural reasons past V-1: " + ", ".join(f"{k} {v}" for k, v in r["card_reasons"].items())
                       + ".")
        for reason in r["ngg_refused"]:
            out.append(f"  Refused NGG frame: {reason}")
        out.append("  Shaders with: " + ", ".join(f"{k} {v}" for k, v in r["shaders_with"].items()) + ".")
        out.append("  VGPRs read before written: " + ", ".join(f"{k} {v}" for k, v in r["input_vgprs"].items()) + ".")
        out.append("  SGPRs read before written: " + ", ".join(f"{k} {v}" for k, v in r["input_sgprs"].items())
                   + "".join(f", {k} {v}" for k, v in r["input_special"].items()) + ".")
        out.append("  Param exports per shader: " + ", ".join(f"{k}: {v}" for k, v in r["param_exports"].items())
                   + "; pos exports: " + ", ".join(f"{k} {v}" for k, v in r["pos_exports"].items()) + ".")
    return "\n".join(out)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shaders", type=Path, default=SHADERS)
    ap.add_argument("--status", type=Path, default=STATUS)
    ap.add_argument("--isa", type=Path, action="append", default=[])
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    try:
        covered = read_covered(args.status)
        forms = form_report(read_forms(args.shaders), covered)
        reference = {name for _, name in form_coverage.load_reference("gfx1013.tsv")} if args.isa else None
        isas = [isa_report(d, reference, covered) for d in args.isa]
    except (InputError, OSError, json.JSONDecodeError) as e:
        print(f"vertex_corpus_report: {e}", file=sys.stderr)
        return 2
    print(text_report(forms, isas))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"forms": forms, "isa": isas}, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
