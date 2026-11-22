"""Translate every pixel shader of the open-source corpus end to end and record what happens.

Usage:
    python tools/corpus_translate.py [--isa DIR] [--summary FILE] [--hlsl-dir DIR] [--status site/status.json]

docs/coverage/corpus-shaders.tsv says a shader is "all covered" when every instruction form it uses is covered by some
test. That does not mean the shader translates: a form can be covered in one operand shape and refuse another, and the
binding contract of lower() (descriptor table, interpolation base, sampler words, sample count) has to fit the
program as a whole. This tool runs each whole program through tools/pixel_aot_ops lower(), which also generates the
HLSL, and records the result: translated, or refused with the first refusal reason and the place that raised it.

Input. ISA_DIR (default tests/corpus/isa/pixel, the committed RADV dumps; see tests/corpus/README.md) holds one dump
per shader: "BBn:" labels and tab-indented "mnemonic operands ; hex words" lines, as RADV_DEBUG=shaders prints them
(tools/shader_corpus_build/build_corpus.py). The text is the LLVM AMDGPU disassembly of the hex words in wave64 mode,
which is how RADV compiles pixel shaders. The instruction text, with runs of spaces collapsed to one (RADV pads NSA
image mnemonics) and "(then repeated N times)" expanded, is what lower() receives; labels stay as "BBn:" lines and
branch operands name them, as name_branch_targets() would produce for a native program.
tools/pixel_aot.disassemble() is not used: it decodes as wave32, which prints a VOP3 lane-mask destination s[0:1] as
s0 and vcc as vcc_lo, so it would not be the program RADV compiled.

Binding contract. lower() takes the entry SGPR of the descriptor-table address, the entry SGPR that holds the
interpolation base, the four sampler words and the offsets of the constant and second texture descriptors. They are
read off the program, the way a caller with the title's pipeline layout would supply them:
- interp_sgpr: the entry SGPR copied (through s_mov_b32) into m0;
- texture_sgpr: the low SGPR of the address pair of the first s_load_dwordx8 (the descriptor table);
- sampler: None for a program without image_sample (bound with no texture or sampler); else the words of the
  first image_sample's sampler registers if s_mov_b32 / s_movk_i32 set them all to constants, else zeros (a sampler
  loaded from memory then refuses as an unknown binding);
- constant_descriptor: the offset of the first s_load_dwordx4 from the descriptor table, if any;
- second_texture_offset: with exactly two image_sample instructions, the offset of a second, different
  s_load_dwordx8 from the table.
Unused registers get distinct free SGPRs. Nothing in the program is rewritten.

Output. --summary writes a TSV: header comments with the counts (all, all-covered, translated, translated among all
covered) and the refusal reasons ranked by shader count, then one row per shader. A reason is the refusal message
with instruction numbers removed; its place is family.form for a form, or the module.function of lower() and the
control-flow walk that raised it. A refusal that is not a ValueError (KeyError, TypeError, ...) is marked crash:
lower() is meant to refuse with ValueError, so a crash is a translator bug. A refusal from the binding contract (see
CONTRACT) is marked contract; any other ValueError from a form is refused, and an instruction no form matches no_form.
--hlsl-dir writes <shader>.hlsl for every translated shader (tests/corpus_translate_check.py compiles them).
--status (default site/status.json) gives the covered forms used for the all-covered column, with the rule of
tools/status_json.py recount_corpus(). Python standard library only.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from pixel_aot_ops import lowering  # noqa: E402
from pixel_aot_ops.dispatch import FORMS  # noqa: E402

ISA = ROOT / "tests" / "corpus" / "isa" / "pixel"
SHADERS = ROOT / "docs" / "coverage" / "corpus-shaders.tsv"
STATUS = ROOT / "site" / "status.json"
SUMMARY = ROOT / "docs" / "coverage" / "corpus-translate.tsv"


def read_dump(path):
    """The instruction text of one RADV dump, as lower() takes it."""
    program = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if re.fullmatch(r"BB\d+:", raw.strip()):
            program.append(raw.strip())
            continue
        if not raw.startswith(("\t", " ")):
            continue
        text = " ".join(raw.split(";", 1)[0].split())
        if not text:
            continue
        if rep := re.fullmatch(r"\(then repeated (\d+) times?\)", text):
            if not program or program[-1].endswith(":"):
                raise ValueError(f"{path}: repeat marker without an instruction")
            program.extend([program[-1]] * int(rep[1]))
            continue
        program.append(text)
    return program


def _pair(token):
    m = re.fullmatch(r"s\[(\d+):(\d+)\]", token)
    return (int(m[1]), int(m[2])) if m else None


def _offset(token):
    return 0 if token == "null" else int(token, 16) if token.startswith("0x") else None


def binding_contract(program):
    """lower()'s positional and keyword inputs for this program (see the module docstring)."""
    written = set()
    alias = {}  # SGPR -> entry SGPR it still holds a copy of
    interp = table = constant = None
    loads8 = []
    constants = {}  # SGPR -> constant word
    sampler = None
    samples = 0
    for line in program:
        if line.endswith(":"):
            continue
        mnemonic, _, operands = line.partition(" ")
        ops = [o.strip() for o in operands.split(",")]
        if mnemonic in ("s_mov_b32", "s_movk_i32") and len(ops) == 2:
            dst, src = ops
            if re.fullmatch(r"s\d+", src):
                entry = alias.get(src, src if src not in written else None)
                if dst == "m0" and interp is None and entry is not None:
                    interp = int(entry[1:])
                if entry is not None:
                    alias[dst] = entry
            elif re.fullmatch(r"0x[0-9a-f]+|-?\d+", src):
                value = int(src, 0) & 0xffffffff
                if mnemonic == "s_movk_i32":
                    value = (value - 0x10000 if value & 0x8000 else value) & 0xffffffff
                constants[dst] = value
                alias.pop(dst, None)
            written.add(dst)
            continue
        if mnemonic in ("s_load_dwordx8", "s_load_dwordx4") and len(ops) >= 3:
            base = _pair(ops[1])
            offset = _offset(ops[2].split()[0])
            if base and offset is not None:
                low = f"s{base[0]}"
                entry = alias.get(low, low if low not in written else None)
                if mnemonic == "s_load_dwordx8":
                    if table is None and entry is not None:
                        table = int(entry[1:])
                    if entry is not None and table == int(entry[1:]):
                        loads8.append(offset)
                elif constant is None and entry is not None and (table is None or table == int(entry[1:])):
                    constant = offset
        if mnemonic == "image_sample":
            samples += 1
            if sampler is None and len(ops) >= 4:
                state = _pair(ops[-1].split()[0])
                if state and state[1] - state[0] == 3:
                    sampler = [constants.get(f"s{n}") for n in range(state[0], state[1] + 1)]
        # Any other write to an SGPR ends what it held (the first operand of a scalar instruction is its destination).
        if mnemonic.startswith("s_") and ops and ops[0]:
            for reg in re.findall(r"s\d+", ops[0]) + [f"s{n}" for a, b in [_pair(ops[0]) or (1, 0)]
                                                      for n in range(a, b + 1)]:
                written.add(reg)
                alias.pop(reg, None)
                if mnemonic not in ("s_mov_b32", "s_movk_i32"):
                    constants.pop(reg, None)
    used = {int(n) for line in program for n in re.findall(r"\bs(\d+)\b", line)}
    free = (n for n in range(105, -1, -1) if n not in used)
    if table is None:
        table = next(free)
    if interp is None or interp == table:
        interp = next(n for n in free if n != table)
    if samples == 0:
        sampler = None  # no image_sample: bound without a texture or sampler (lower(sampler=None))
    elif sampler is None or None in sampler:
        sampler = [0, 0, 0, 0]
    second = None
    if samples == 2:
        second = next((o for o in loads8 if o != loads8[0]), None)
    if constant is not None and (constant % 4 or constant < 0):
        constant = None
    return (table, interp, sampler), {"constant_descriptor": constant, "second_texture_offset": second}


# Refusals that come from lower()'s binding contract (the inputs a caller supplies and the program shape lower()
# requires: one T# at descriptor-table offset 0, a table address whose high word is 0, sampler words set by moves,
# one or two samples, no read of an SGPR the contract does not name) rather than from the lowering of a form.
CONTRACT = ("Texture address differs from binding contract", "Unresolved constant buffer binding",
            "Texture and constant descriptors overlap", "Second texture descriptor must have a distinct aligned offset",
            "Unexpected sample count or missing color export", "Unsupported image or sampler binding",
            "Descriptor table word is not a tracked descriptor", "Read of unset scalar register",
            "Second texture requires a sampler")


class _Dispatch:
    """Records the instruction being lowered and the form that claims it, around lowering.dispatch."""

    def __init__(self, inner):
        self.inner = inner
        self.current = None

    def __call__(self, st, i, line):
        self.current = (i, line)
        self.inner(st, i, line)
        self.current = None


HANDLERS = {(handler.__code__.co_filename, handler.__name__): f"{family}.{handler.__name__}"
            for family, _, _, handler in FORMS}


def _place(exc):
    """family.form of the form that raised exc (the outermost frame that is a registered form), else the
    module.function of the innermost pixel_aot_ops frame."""
    frames = traceback.extract_tb(exc.__traceback__)
    for frame in frames:
        if (name := HANDLERS.get((frame.filename, frame.name))) is not None:
            return name
    for frame in reversed(frames):
        path = Path(frame.filename)
        if "pixel_aot_ops" in path.parts:
            return f"{path.stem}.{frame.name}"
    return "unknown"


def translate(program):
    """('translated', hlsl, None) or ('refused', None, {reason, place, kind, instruction})."""
    args, kwargs = binding_contract(program)
    recorder = _Dispatch(lowering.dispatch)
    lowering.dispatch = recorder
    try:
        return "translated", lowering.lower(program, *args, **kwargs), None
    except Exception as exc:  # noqa: BLE001 - every refusal is classified, a non-ValueError one as a crash
        message = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"
        reason = re.sub(r"\binstruction \d+", "instruction", message)
        current = recorder.current
        if current is not None and reason.startswith("Unsupported instruction"):
            kind, place = "no_form", "dispatch"
            reason = f"no form matches {current[1].split()[0]}"
        else:
            kind = ("crash" if not isinstance(exc, ValueError)
                    else "contract" if reason.startswith(CONTRACT) else "refused")
            place = _place(exc)
        return "refused", None, {"reason": reason, "place": place, "kind": kind,
                                 "instruction": "" if current is None else f"{current[0]}: {current[1]}"}
    finally:
        lowering.dispatch = recorder.inner


def all_covered(shaders_tsv, status_json):
    """Names of the pixel shaders whose every form is covered, by tools/status_json.py recount_corpus()'s rule."""
    covered = {f["name"] for f in json.loads(Path(status_json).read_text(encoding="utf-8"))["gfx1013"]["forms"]
               if f["covered"]}
    names = set()
    for line in Path(shaders_tsv).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        stage, name, _branches, forms = line.split("\t")
        if stage == "pixel" and all(not f.startswith("!") and f in covered for f in forms.split()):
            names.add(name)
    return names


def run(isa_dir, covered_names, hlsl_dir=None):
    rows = []
    for path in sorted(Path(isa_dir).glob("*.s")):
        status, source, refusal = translate(read_dump(path))
        if hlsl_dir is not None and source is not None:
            Path(hlsl_dir).mkdir(parents=True, exist_ok=True)
            (Path(hlsl_dir) / (path.name[:-2] + ".hlsl")).write_text(source, encoding="utf-8")
        rows.append({"shader": path.name, "covered": path.name in covered_names, "status": status,
                     **(refusal or {"reason": "", "place": "", "kind": "", "instruction": ""})})
    return rows


def summary(rows):
    total = len(rows)
    covered = [r for r in rows if r["covered"]]
    translated = [r for r in rows if r["status"] == "translated"]
    reasons = Counter((r["kind"], r["place"], r["reason"]) for r in rows if r["status"] == "refused")
    reasons_covered = Counter((r["kind"], r["place"], r["reason"]) for r in covered if r["status"] == "refused")
    out = [
        "# End-to-end translation of the corpus pixel shaders (tools/corpus_translate.py; inputs",
        "# tests/corpus/isa/pixel, sources and licenses tests/corpus/README.md). all_covered is the site's measure",
        "# (every form covered by a test); translated means lower() accepted the whole program and produced HLSL.",
        f"# Pixel: shaders {total}; translated {len(translated)}; all_covered {len(covered)}; "
        f"all_covered_translated {sum(r['status'] == 'translated' for r in covered)}.",
        "# Refusal reasons, most shaders first: shaders (all_covered shaders), kind, place, reason.",
    ]
    for (kind, place, reason), n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append(f"# Reason {n} ({reasons_covered.get((kind, place, reason), 0)})\t{kind}\t{place}\t{reason}")
    out.append("# Columns: shader, all_covered (0/1), status, kind, place, reason, first refused instruction.")
    for r in rows:
        out.append("\t".join([r["shader"], str(int(r["covered"])), r["status"], r["kind"], r["place"],
                              r["reason"], r["instruction"]]))
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--isa", type=Path, default=ISA)
    ap.add_argument("--shaders", type=Path, default=SHADERS)
    ap.add_argument("--status", type=Path, default=STATUS)
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--hlsl-dir", type=Path)
    args = ap.parse_args(argv)
    if not any(args.isa.glob("*.s")):
        ap.error(f"no ISA dumps in {args.isa}")
    rows = run(args.isa, all_covered(args.shaders, args.status), args.hlsl_dir)
    text = summary(rows)
    if args.summary:
        args.summary.write_text(text, encoding="utf-8", newline="\n")
    print("\n".join(line for line in text.splitlines() if line.startswith("# Pixel") or line.startswith("# Reason"))
          if args.summary else text, end="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
