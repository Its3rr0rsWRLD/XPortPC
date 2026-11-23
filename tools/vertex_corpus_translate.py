"""Translate every vertex shader of the open-source corpus with tools/vertex_aot.py and record what happens.

Usage:
    python tools/vertex_corpus_translate.py --isa DIR [--isa DIR ...] [--summary FILE] [--hlsl-dir DIR]

Each DIR holds one RADV dump per shader in DIR/vertex/*.s (tools/shader_corpus_build/build_corpus.py; the legacy
"nongg" build or the NGG build of the same sources). vertex_corpus_report.py counts the card a shader needs from its
structure and forms; this tool runs the whole program through vertex_aot.lower_with_layout(), which also generates the
HLSL, and records translated or the first refusal reason.

Binding contract. lower_with_layout() takes the user-SGPR role map and the PA_CL_VS_OUT_CNTL value, which a title's
shader metadata and pipeline state supply. For a RADV dump they are read off the program, as RADV's user-data layout
would give them:
- an entry SGPR that is (directly or through s_mov_b32 copies) the low half of an s_load address pair is a 32-bit
  descriptor-list pointer with RADV's high word 0xffff8000. Each 16-byte entry an s_load reads through it is the
  constant buffer if its four loaded words are the V# of an s_buffer_load before they are overwritten (the first
  such entry only; lower() binds one constant buffer; with descriptor words too if a buffer load also reads through
  it), else a V# whose runtime words get the next four descriptor words. A pair whose high half is itself an entry
  SGPR is a 64-bit address in inline words (buffer device address);
- an entry SGPR added to the vertex-id (instance-id) VGPR by v_add_nc_u32 is the base vertex (start instance);
- every other entry SGPR read before it is written is an inline push-constant word, numbered in SGPR order;
- PA_CL_VS_OUT_CNTL: none, unless the program exports pos1..3; then the clip distances of the exported channels
  (the corpus's one such shader writes gl_ClipDistance), as RADV sets them for that shader.
Python standard library only. Reads no game files.
"""
import argparse
from collections import Counter
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import corpus_translate  # noqa: E402
import vertex_aot  # noqa: E402
from vertex_corpus_report import features  # noqa: E402


def _span(token):
    if m := re.fullmatch(r"s\[(\d+):(\d+)\]", token):
        return list(range(int(m[1]), int(m[2]) + 1))
    if m := re.fullmatch(r"s(\d+)", token):
        return [int(m[1])]
    return []


def _uses(lines, at, quad):
    """How the four SGPRs `quad` that lines[at] loads are used before they are written: the set of "constants" (the V#
    of an s_buffer_load) and "data" (the V# of a buffer load)."""
    out = set()
    if len(quad) != 4:
        return out
    for line in lines[at + 1:]:
        mnemonic, _, rest = line.partition(" ")
        ops = [o.strip() for o in rest.split(",")]
        if mnemonic.startswith("s_buffer_load") and len(ops) > 1 and _span(ops[1]) == quad:
            out.add("constants")
        elif mnemonic.startswith("buffer_load") and len(ops) > 2 and _span(ops[2]) == quad:
            out.add("data")
        if mnemonic.startswith("s_") and ops and set(_span(ops[0])) & set(quad):
            break
    return out


def binding_contract(program, stage=None):
    """(user-SGPR role map, PA_CL_VS_OUT_CNTL or None) for a program (see the module docstring). With a stage
    ("legacy" or "ngg"), program is a body without a frame (tools/geometry_aot.py passes the two halves of an ES+GS
    wave) and its entry registers are that stage's."""
    lines = vertex_aot._clean(program)
    if stage is None:
        stage = "ngg" if vertex_aot.is_ngg(lines) else "legacy"
        if stage == "ngg":
            lines, _ = vertex_aot.match_ngg_frame(lines)
    lines = [line for line in lines if not vertex_aot._is_label(line)]
    roles_of = {name: reg for reg, name in vertex_aot.ENTRY_VGPRS[stage].items()}
    inputs = [int(r[1:]) for r in features(lines)["inputs_sgpr"]]
    alias = {}  # SGPR -> entry SGPR it holds a copy of
    written = set()
    pointers = {}  # entry SGPR -> [(offset, destination registers)]
    roles = {}
    for index, line in enumerate(lines):
        mnemonic, _, rest = line.partition(" ")
        ops = [o.strip() for o in rest.split(",")]
        entry_of = lambda reg: alias.get(reg, reg if reg not in written else None)  # noqa: E731
        if mnemonic == "s_mov_b32" and re.fullmatch(r"s\d+", ops[1]) and (source := entry_of(ops[1])):
            alias[ops[0]] = source
            written.add(ops[0])
            continue
        if mnemonic.startswith("s_load_dword") and len(ops) >= 3 and (pair := _span(ops[1])):
            entry = entry_of(f"s{pair[0]}")
            offset = 0 if ops[2] == "null" else int(ops[2], 0) if re.fullmatch(r"0x[0-9a-f]+|\d+", ops[2]) else None
            high = entry_of(f"s{pair[1]}")  # an entry high half: a 64-bit address in inline words, not a list
            if entry is not None and offset is not None and high is None:
                pointers.setdefault(int(entry[1:]), []).append((index, offset, _span(ops[0])))
        if re.fullmatch(r"v_add(?:_nc|_lshl)?_u32(?:_e32|_e64)?", mnemonic) and len(ops) >= 3 \
                and re.fullmatch(r"s\d+", ops[1]) and (entry := entry_of(ops[1])):
            for role, register in roles_of.items():
                if ops[2] == register and register not in written:
                    roles[int(entry[1:])] = ("base_vertex",) if role == "vid" else ("start_instance",)
        if mnemonic == "exp" or not ops or not ops[0]:
            continue
        for reg in re.findall(r"\b[sv]\d+\b", ops[0]) + [f"s{n}" for n in _span(ops[0]) if "[" in ops[0]] + \
                [f"v{n}" for a, b in re.findall(r"v\[(\d+):(\d+)\]", ops[0]) for n in range(int(a), int(b) + 1)]:
            written.add(reg)
            alias.pop(reg, None)
    next_word = 0
    has_constants = False
    for number, loads in sorted(pointers.items()):
        entries = {}
        for at, offset, dst in loads:
            for k in range(0, 4 * len(dst), 16):
                start = (offset + k) // 16 * 16
                quad = dst[k // 4:k // 4 + 4]
                if start in entries:
                    continue
                uses = _uses(lines, at, quad)
                if not has_constants and uses == {"constants"}:
                    entries[start], has_constants = ("constants",), True
                elif not has_constants and "constants" in uses:
                    entries[start], has_constants = ("constants", min(next_word, 61)), True
                    next_word += 4
                else:
                    entries[start] = ("vsharp", min(next_word, 61))
                    next_word += 4
        roles[number] = ("descriptors", vertex_aot.RADV_ADDRESS_HIGH, entries)
    push = 0
    for number in sorted(inputs):
        if number not in roles and not (stage in ("ngg", "ls") and number < vertex_aot.NGG_FIRST_USER_SGPR):
            roles[number] = ("inline", push)
            push += 1
    cntl = None
    distances = [line for line in lines if re.match(r"exp pos[123]\b", line)]
    if distances:
        cntl = 0
        for k, line in enumerate(distances):
            sources = line.split(None, 2)[2].split(",")
            cntl |= 1 << (22 + k)
            for c, token in enumerate(sources[:4]):
                if token.split()[0] != "off":
                    cntl |= 1 << (4 * k + c)
    return roles, cntl


def translate(path):
    program = corpus_translate.read_dump(path)
    try:
        roles, cntl = binding_contract(program)
        source, layout = vertex_aot.lower_with_layout(program, roles, cntl)
        return "translated", source, layout["stage"]
    except Exception as exc:  # noqa: BLE001 - a non-ValueError is a translator crash and is marked so
        reason = str(exc) if isinstance(exc, ValueError) else f"crash {type(exc).__name__}: {exc}"
        return "refused", None, re.sub(r"'[^']*'", "'...'", reason)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--isa", type=Path, action="append", required=True)
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--hlsl-dir", type=Path)
    args = ap.parse_args(argv)
    rows = []
    for isa in args.isa:
        paths = sorted((isa / "vertex").glob("*.s"))
        if not paths:
            print(f"vertex_corpus_translate: {isa}/vertex has no .s files", file=sys.stderr)
            return 2
        reasons = Counter()
        done = 0
        for path in paths:
            status, source, detail = translate(path)
            rows.append((isa.name, path.name, status, detail))
            if source is not None:
                done += 1
                if args.hlsl_dir:
                    out = args.hlsl_dir / isa.name
                    out.mkdir(parents=True, exist_ok=True)
                    (out / (path.name[:-2] + ".hlsl")).write_text(source, encoding="ascii")
            else:
                reasons[detail] += 1
        print(f"{isa}: {done} of {len(paths)} vertex shaders translate")
        for reason, count in reasons.most_common():
            print(f"  {count:3d}  {reason[:160]}")
    if args.summary:
        args.summary.write_text("".join("\t".join(map(str, row)) + "\n" for row in rows), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
