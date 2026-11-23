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

Bindings. Each program is lowered under a binding description (tools/pixel_aot_ops/bindings.py PixelBindings,
docs/design/pixel-bindings.md) that derive_bindings() reads off the dump, the way a caller with the title's pipeline
layout would supply it: descriptor-set pointers, the interpolation base and push-constant words among the entry SGPRs,
and each descriptor the program loads (T#, S#, constant-buffer V#, buffer V#) classified by its first use. lower()
then resolves every descriptor word against it and refuses one it does not declare.

Output. --summary writes a TSV: header comments with the counts (all, all-covered, translated, translated among all
covered) and the refusal reasons ranked by shader count, then one row per shader. A reason is the refusal message
with instruction numbers removed; its place is family.form for a form, or the module.function of lower() and the
control-flow walk that raised it. A refusal that is not a ValueError (KeyError, TypeError, ...) is marked crash:
lower() is meant to refuse with ValueError, so a crash is a translator bug. A refusal from the bindings (see
CONTRACT: the description, and the resolution of descriptor loads and samples against it) is marked contract; any
other ValueError from a form is refused, and an instruction no form matches no_form.
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
from pixel_aot_ops import bindings, lowering  # noqa: E402
from pixel_aot_ops.dispatch import FORMS  # noqa: E402

ISA = ROOT / "tests" / "corpus" / "isa" / "pixel"
SHADERS = ROOT / "docs" / "coverage" / "corpus-shaders.tsv"
STATUS = ROOT / "site" / "status.json"
SUMMARY = ROOT / "docs" / "coverage" / "corpus-translate.tsv"
PS_INPUTS = ROOT / "tests" / "corpus" / "ps-inputs.tsv"


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


def _span_regs(token):
    span = _pair(token)
    if span:
        return [f"s{n}" for n in range(span[0], span[1] + 1)]
    return [token] if re.fullmatch(r"s\d+|m0", token) else []


# Scalar instructions whose first operand is read, not written.
_NO_DESTINATION = ("s_cmp", "s_bitcmp", "s_waitcnt", "s_cbranch", "s_branch", "s_clause", "s_endpgm", "s_nop",
                   "s_setprio", "s_sendmsg", "s_inst_prefetch", "s_setpc", "s_ttracedata", "s_wqm_b64 exec")


def _constant_reach(program, start, reg0):
    """One past the highest byte an s_buffer_load at an immediate offset reads through s[reg0:reg0+3], from
    instruction `start` on; 0 when there is none."""
    reach = 0
    for later in program[start:]:
        m = re.fullmatch(rf"s_buffer_load_dword(x\d+)? \S+, s\[{reg0}:{reg0 + 3}\], (0x[0-9a-f]+|null)(?: glc)?(?: dlc)?",
                         later)
        if m:
            reach = max(reach, _offset(m[2]) + 4 * (int(m[1][1:]) if m[1] else 1))
    return reach


def derive_bindings(program, ps_input_ena=None):
    """The binding description of a RADV pixel program (bindings.PixelBindings), read off the program the way the
    pipeline layout would give it. RADV's user SGPRs for a pixel shader are the 32-bit descriptor-set pointers, inline
    push-constant words and the primitive mask, which the program copies into m0:
    - entry SGPRs are the scalar registers read before the program writes them (through s_mov_b32 copies);
    - the one copied into m0 is "interp";
    - one that is the low word of the address pair of an s_load is a descriptor-set pointer: the lowest such SGPR is
      set 0 ("descriptors"), the others descriptors.1, .2, ... in register order; the high word the program writes
      into the pair (s_movk_i32 0x8000 is RADV's 0xffff8000) is descriptor_high;
    - any other entry SGPR the program reads is an inline push-constant word: push:0, push:1, ... in register order,
      in a constant slot of their own;
    - each s_load's destination is classified by its first use: a T# where an image instruction names s[r:r+7] as its
      resource (a storage image for image_store, with the corpus's r8g8b8a8_unorm format), an S# where it names
      s[r:r+3] as its sampler, a constant-buffer V# where s_buffer_load names s[r:r+3], a buffer V# where a buffer or
      tbuffer instruction does (its words at the top of params). A load of x8 or x16 is split into its descriptors
      that way; a word with no use stays undeclared, and lower() refuses a program that loads it;
    - a T#'s dimension is the dim: field of the image instruction that first uses it (2D, 2D array, cube or 3D), as
      the layout's image view type would give it;
    - a sampler whose four registers s_mov_b32/s_movk_i32 set to constants is an inline (immutable) sampler with
      those words;
    - a constant-buffer V# that s_buffer_load reads past its first 256 bytes at immediate offsets gets a window
      (constant_sizes) up to the highest byte read, rounded up to 16 bytes and at most 65536: the dump does not record
      the uniform block's size, so the window is what the program is seen to read, as a title's pipeline layout would
      bind at least that much;
    - ps_input_ena, when given, is the program's SPI_PS_INPUT_ENA (tests/corpus/ps-inputs.tsv); otherwise the
      description's default, persp_center alone.
    Slots are given in order of first use. Nothing in the program is rewritten."""
    written, alias, constants = set(), {}, {}
    entry_reads = []  # entry SGPRs in order of first read
    interp = None
    pointers = {}  # entry SGPR -> descriptor high word written to its pair
    loads = []  # (index, destination registers, entry pointer SGPR, offset)
    inline_samplers = {}  # instruction index -> four words
    for k, line in enumerate(program):
        if line.endswith(":"):
            continue
        mnemonic, _, operands = line.partition(" ")
        ops = [o.strip() for o in operands.split(",")] if operands else []
        has_dst = mnemonic.startswith("s_") and not line.startswith(_NO_DESTINATION) and ops
        sources = ops[1:] if has_dst else ops
        if mnemonic.startswith("s_load_dword"):
            sources = ops[1:2]  # the address pair; its high word is read through the pair below
        for token in sources:
            # A source modifier (-s4, |s4|, neg(s4), abs(s4)) does not hide the register it reads.
            for reg in _span_regs(re.sub(r"^-?(?:\||abs\(|neg\()?|(?:\||\))$", "", token.split()[0])) if token else []:
                if reg not in written and reg != "m0" and reg not in entry_reads:
                    entry_reads.append(reg)
        if mnemonic in ("s_mov_b32", "s_movk_i32") and len(ops) == 2:
            dst, src = ops
            if re.fullmatch(r"s\d+", src):
                origin = alias.get(src, src if src not in written else None)
                if dst == "m0" and interp is None and origin is not None:
                    interp = origin
                alias.pop(dst, None)
                if origin is not None:
                    alias[dst] = origin
                constants.pop(dst, None)
            elif re.fullmatch(r"0x[0-9a-f]+|-?\d+", src):
                value = int(src, 0) & 0xffffffff
                if mnemonic == "s_movk_i32" and value & 0x8000:
                    value = (value | 0xffff0000) & 0xffffffff
                constants[dst] = value
                alias.pop(dst, None)
            written.add(dst)
            continue
        if mnemonic.startswith("s_load_dword") and len(ops) >= 3:
            base, offset = _pair(ops[1]), _offset(ops[2].split()[0])
            low = f"s{base[0]}" if base else None
            origin = alias.get(low, low if low not in written else None) if low else None
            # A descriptor-set pointer is 32 bits: the program writes the pair's high word with a constant. A pair
            # whose high word comes in with it (RADV's 64-bit ring and scratch pointers) is not one.
            high = constants.get(f"s{base[1]}") if base else None
            if origin is not None and high is not None and (offset is not None or re.fullmatch(r"s\d+", ops[2].split()[0])):
                pointers.setdefault(origin, high)
                loads.append((k, _span_regs(ops[0]), origin, offset))
        if mnemonic.startswith("image_") and len(ops) >= 4:
            state = _pair(ops[3].split()[0])
            if state and state[1] - state[0] == 3:
                words = [constants.get(f"s{n}") for n in range(state[0], state[1] + 1)]
                if None not in words:
                    inline_samplers[k] = tuple(words)
        if has_dst:
            for reg in _span_regs(ops[0]):
                written.add(reg)
                alias.pop(reg, None)
                constants.pop(reg, None)
    order = sorted(pointers, key=lambda r: int(r[1:]))
    sets = {reg: n for n, reg in enumerate(order[:8])}
    sgprs = {reg: "descriptors" if n == 0 else f"descriptors.{n}" for reg, n in sets.items()}
    if interp is not None:
        sgprs[interp] = "interp"
    pushed = sorted((r for r in entry_reads if r not in sgprs and re.fullmatch(r"s\d+", r)), key=lambda r: int(r[1:]))
    for n, reg in enumerate(pushed[:64]):
        sgprs[reg] = f"push:{n}"
    highs = {pointers[r] for r in sets if pointers[r] is not None}
    high = highs.pop() if len(highs) == 1 else bindings.RADV_DESCRIPTOR_HIGH
    textures, samplers, cbvs, buffers, images, dims, sizes = {}, {}, {}, {}, {}, {}, {}
    sampler_keys, inline_order = [], []
    spans = []  # (key, size) of the descriptors declared so far

    def declared(at):
        return any(start <= at < start + size for start, size in spans)

    for k, dst, origin, offset in loads:
        if origin not in sets or not dst or offset is None:
            continue  # an SGPR offset: lower() resolves it only if the SGPR holds a constant, and it names no new descriptor
        key = sets[origin] * bindings.SET_STRIDE + offset
        first = int(dst[0][1:])
        for q in range(0, len(dst), 4):
            reg0, at = first + q, key + 4 * q
            if declared(at):
                continue
            use = dim = None
            for later in program[k + 1:]:
                if later.startswith("image_") and f"s[{reg0}:{reg0 + 7}]" in later:
                    use = "image_store" if later.startswith("image_store") else "image"
                    field = re.search(r"\bdim:(SQ_RSRC_IMG_\w+)", later)
                    dim = bindings.INSTRUCTION_DIMS.get(field[1]) if field else None
                    break
                if f"s[{reg0}:{reg0 + 3}]" in later:
                    use = ("sampler" if later.startswith("image_") else "constants" if later.startswith("s_buffer_load")
                           else "buffer" if later.startswith(("buffer_", "tbuffer_")) else None)
                    break
            if use == "image" and len(dst) - q >= 8 and not declared(at + 16):
                if dim not in (None, "2d"):
                    dims[len(textures)] = dim
                textures[at] = len(textures)
                spans.append((at, 32))
            elif use == "image_store" and len(dst) - q >= 8 and not declared(at + 16):
                images[at] = (len(images), "r8g8b8a8_unorm")
                spans.append((at, 32))
            elif use in ("sampler", "constants", "buffer"):
                spans.append((at, 16))
                if use == "sampler":
                    sampler_keys.append(at)
                elif use == "constants":
                    reach = -(-_constant_reach(program, k + 1, reg0) // 16) * 16
                    if reach > bindings.CONSTANT_WINDOW:
                        sizes[len(cbvs)] = min(reach, bindings.MAX_CONSTANT_WINDOW)
                    cbvs[at] = len(cbvs)
                else:
                    buffers[at] = 60 - 4 * len(buffers)
    for k in sorted(inline_samplers):
        if inline_samplers[k] not in inline_order:
            inline_order.append(inline_samplers[k])
    for source in (*sampler_keys, *inline_order):
        if len(samplers) < bindings.SAMPLER_SLOTS:
            samplers[len(samplers)] = source
    push = None
    if pushed or buffers and 0 not in cbvs.values():
        push = next(n for n in range(bindings.CONSTANT_SLOTS) if n not in cbvs.values()) \
            if len(cbvs) < bindings.CONSTANT_SLOTS else None
    if buffers and push != 0 and 0 not in cbvs.values():
        buffers = {}
    return bindings.PixelBindings(
        sgprs=sgprs, textures={k: v for k, v in textures.items() if v < bindings.TEXTURE_SLOTS},
        samplers=samplers, constant_buffers={k: v for k, v in cbvs.items() if v < bindings.CONSTANT_SLOTS},
        push_constants=push, buffers=buffers, storage_images={k: v for k, v in images.items() if v[0] < 4},
        descriptor_high=high, dimensions={k: v for k, v in dims.items() if k < bindings.TEXTURE_SLOTS},
        constant_sizes={k: v for k, v in sizes.items() if k < bindings.CONSTANT_SLOTS},
        **({} if ps_input_ena is None else {"ps_input_ena": ps_input_ena}))


# Refusals that come from the binding description (bindings.PixelBindings.check) or from resolving a program's
# descriptor loads and samples against it, rather than from the lowering of a form.
CONTRACT = ("Unresolved constant buffer binding", "Unresolved descriptor-list pointer",
            "Descriptor table word is not a tracked descriptor", "Descriptor load offset must be an immediate",
            "Unsupported image or sampler binding", "Unsupported image binding", "Unsupported sampler binding",
            "Unsupported storage image binding", "Read of unset scalar register", "Invalid entry SGPR",
            "Unknown entry SGPR role", "Entry SGPR role", "Invalid texture key", "Invalid sampler slot",
            "A sampler is a descriptor key", "Two inline samplers", "Invalid constant-buffer key",
            "Buffer descriptors need", "Invalid buffer descriptor", "Invalid storage image key",
            "Descriptor-table entries overlap", "A push-constant", "Scalar load offset register must hold a known constant",
            "Image dimension", "A texture dimension", "Unsupported T# type")


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


def ps_inputs(path=PS_INPUTS):
    """{shader file name: SPI_PS_INPUT_ENA} of tests/corpus/ps-inputs.tsv."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, ena, _inputs, _builtins = line.split("\t")
            out[name] = int(ena, 16)
    return out


def translate(program, ps_input_ena=None):
    """('translated', hlsl, None) or ('refused', None, {reason, place, kind, instruction})."""
    described = derive_bindings(program, ps_input_ena)
    recorder = _Dispatch(lowering.dispatch)
    lowering.dispatch = recorder
    try:
        return "translated", lowering.lower(program, bindings=described), None
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
    inputs = ps_inputs()
    for path in sorted(Path(isa_dir).glob("*.s")):
        status, source, refusal = translate(read_dump(path), inputs.get(path.name))
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
