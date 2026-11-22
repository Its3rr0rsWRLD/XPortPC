"""Offline lowering for a straight-line, texture-sampling gfx1013 pixel shader."""
import argparse
import ctypes as C
import hashlib
import json
import mmap
from pathlib import Path
import re
import struct
import tempfile
import zlib

from resource_inventory import parts


def inflate(data, size, window):
    if not 0 < size <= 16 << 20:
        raise ValueError("Invalid decoded size")
    decoder = zlib.decompressobj(window)
    image = decoder.decompress(data, size + 1)
    if len(image) != size or not decoder.eof:
        raise ValueError("Incomplete or mismatched compressed stream")
    return image


def _read_named_container(data: mmap.mmap, end: int) -> bytes:
    payload = end + 17
    if payload > len(data):
        raise ValueError("Missing or truncated named record")
    stored, _, repeat, size = struct.unpack_from("<4I", data, end + 1)
    if stored != repeat or not 0 < stored <= 8 << 20 or payload + stored > len(data):
        raise ValueError("Invalid record extent")
    return inflate(data[payload:payload + stored], size, -15)


def _select_named_container(data: mmap.mmap, needle: bytes, digest: str) -> bytes:
    selected = None
    cursor = 0
    while (pos := data.find(needle, cursor)) >= 0:
        # Advance past the name, independent of the candidate's claimed payload extent.
        cursor = pos + len(needle)
        try:
            blob = _read_named_container(data, cursor)
        except (ValueError, zlib.error):
            continue
        if hashlib.sha256(blob).hexdigest() == digest:
            if selected is not None:
                raise ValueError("Multiple records match the name and container SHA-256")
            selected = blob
    if selected is None:
        raise ValueError("No record matches the name and container SHA-256")
    return selected


def _bounded_code(image, start):
    """Strip code padding within the FSSM v0x101 section directory."""
    if len(image) < 240 or struct.unpack_from("<I", image, 4)[0] != 0x101:
        raise ValueError("Unknown multi-exit FSSM layout")
    base, size = struct.unpack_from("<QQ", image, 192)
    limit, = struct.unpack_from("<Q", image, 232)
    if limit == 0xdeadbeefdeadbeef:
        limit = base + size
        if image[limit:limit+16] != b"\x00\x00\x9f\xbf" * 4:
            raise ValueError("Unverified FSSM sentinel extent")
    if (base < 240 or base + 40 != start or size % 16 or base + size != limit
            or limit > len(image) or limit <= start):
        raise ValueError("Inconsistent FSSM code extent")
    end = limit
    while end > start and image[end-4:end] == b"\x00\x00\x9f\xbf":
        end -= 4
    if end <= start or end == limit or image[end-4:end] != b"\x00\x00\x81\xbf":
        raise ValueError("Expected termination followed by code padding")
    return image[start:end]


def _check_two_exits(code, llvm):
    """Both decoded exits must be reachable from the single entry (from R0Y00/Xbox2Windows#477 by Royoo)."""
    instructions = dict(disassemble(code, llvm, offsets=True))
    exits = [pc for pc, line in instructions.items() if line == "s_endpgm"]
    if len(exits) != 2 or exits[-1] + 4 != len(code):
        raise ValueError("Expected two decoded exits")
    # An aligned word can be a literal or the second half of an instruction.
    # Follow branches only from decoded PCs and reject unresolved transfers.
    pcs = list(instructions)
    following = dict(zip(pcs, pcs[1:] + [len(code)]))
    pending, visited, targets = [0], set(), set()
    while pending:
        pc = pending.pop()
        if pc in visited:
            continue
        if pc not in instructions:
            raise ValueError("Branch outside decoded instruction boundaries")
        visited.add(pc)
        op = instructions[pc].split()[0]
        if op == "s_endpgm":
            continue
        if op == "s_branch" or op in ("s_cbranch_scc0", "s_cbranch_scc1", "s_cbranch_vccz",
                                      "s_cbranch_vccnz", "s_cbranch_execz", "s_cbranch_execnz"):
            target = pc + 4 + 4 * struct.unpack_from("<h", code, pc)[0]
            targets.add(target)
            pending.append(target)
            if op == "s_branch":
                continue
        elif not (op.startswith(("v_", "image_", "buffer_", "tbuffer_", "ds_", "flat_", "global_",
                                 "scratch_", "exp", "s_load_", "s_buffer_load_", "s_cmp", "s_bitcmp",
                                 "s_mov_", "s_and", "s_or_", "s_xor_", "s_not_", "s_lsh", "s_ash",
                                 "s_add", "s_sub", "s_mul", "s_min_", "s_max_", "s_cselect", "s_bfe",
                                 "s_bfm", "s_brev", "s_ff", "s_bcnt", "s_wqm", "s_quadmask"))
                  or op in ("s_nop", "s_inst_prefetch", "s_waitcnt", "s_clause", "s_delay_alu",
                            "s_setprio", "s_sleep", "s_movk_i32", "s_mulk_i32", "s_flbit_i32_b32",
                            "s_setreg_imm32_b32")):
            raise ValueError(f"Unverified multi-exit control flow: {op}")
        pending.append(following[pc])
    # A direct branch may skip alignment NOPs. Keep them in the original span.
    unreachable = instructions.keys() - visited
    if exits[0] + 4 not in targets or any(instructions[pc].split()[0] != "s_nop" for pc in unreachable):
        raise ValueError("Unreachable code or unverified alternate exit")


def native_program(archive: Path, record: str, *, container_sha256: str | None = None, llvm=None) -> tuple[bytes, bytes]:
    name = record.encode("ascii")
    if not 0 < len(name) < 255 or b"\0" in name:
        raise ValueError("Invalid length-prefixed record name")
    needle = bytes([len(name) + 1]) + name + b"\0"
    if container_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", container_sha256):
        raise ValueError("Invalid decoded container SHA-256")
    with archive.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if container_sha256 is None:
            pos = data.find(needle)
            end = pos + len(needle)
            if pos < 0 or end + 17 > len(data):
                raise ValueError("Missing or truncated named record")
            if data.find(needle, end) >= 0:
                raise ValueError("Multiple records match the name")
            blob = _read_named_container(data, end)
        else:
            blob = _select_named_container(data, needle, container_sha256.lower())
    return blob, container_code(parts(blob)[b"DXIL"], stage=0, llvm=llvm)


def container_code(program, *, stage, llvm=None):
    """Extract the stage-specific instruction stream from a DXIL program part."""
    if len(program) < 24 or struct.unpack_from("<H", program, 2)[0] != stage:
        raise ValueError("Unexpected shader stage")
    table = program.index(b"XDAT", 24)
    if table + 12 > len(program):
        raise ValueError("Truncated XDAT header")
    count, = struct.unpack_from("<I", program, table+4)
    if table + 12 + count*12 > len(program):
        raise ValueError("Truncated XDAT table")
    entries = struct.iter_unpack("<3I", program[table+12:table+12+count*12])
    native_entries = [(o, n) for tag, o, n in entries if tag == 13]
    if len(native_entries) != 1:
        raise ValueError("Expected one native program entry")
    offset, length = native_entries[0]
    if offset < table + 12 + count * 12 or offset+length > len(program) or length < 24 or program[offset:offset+4] != b"XBCH":
        raise ValueError("Invalid native program entry")
    size, = struct.unpack_from("<I", program, offset+16)
    image = inflate(program[offset+24:offset+length], size, 15)
    if len(image) < 196 or image[:4] != b"FSSM":
        raise ValueError("Invalid native program header")
    start = struct.unpack_from("<I", image, 192)[0] + 40
    if start < 196 or start % 4 or start + 4 > len(image):
        raise ValueError("Invalid native code offset")
    if struct.unpack_from("<I", image, 4)[0] == 0x101:
        code = _bounded_code(image, start)
        markers = sum(word == 0xbf810000 for word, in struct.iter_unpack("<I", code))
        if markers == 1:
            return code
        if stage == 0 and markers == 2 and llvm is not None:
            _check_two_exits(code, llvm)
            return code
        raise ValueError("Unverified multi-exit program")
    # Older fixtures lack the section extent; preserve their unique-marker rule.
    if stage != 0:
        raise ValueError("Compute requires a bounded FSSM section")
    ends = [i+4 for i in range(start, len(image)-3, 4) if image[i:i+4] == b"\0\0\x81\xbf"]
    if len(ends) != 1:
        raise ValueError("Expected one aligned, terminated program")
    return image[start:ends[0]]


def disassemble(code, library, *, cpu=b"gfx1013", offsets=False, features=b""):
    llvm = C.CDLL(library)
    for component in ("TargetInfo", "Target", "TargetMC", "AsmPrinter", "Disassembler"):
        getattr(llvm, "LLVMInitializeAMDGPU" + component)()
    pointer, string = C.c_void_p, C.c_char_p
    llvm.LLVMCreateDisasmCPUFeatures.argtypes = [string, string, string, pointer, C.c_int, pointer, pointer]
    llvm.LLVMCreateDisasmCPUFeatures.restype = pointer
    llvm.LLVMDisasmInstruction.argtypes = [pointer, pointer, C.c_uint64, C.c_uint64, pointer, C.c_size_t]
    llvm.LLVMDisasmInstruction.restype = C.c_size_t
    llvm.LLVMDisasmDispose.argtypes = [pointer]
    ctx = llvm.LLVMCreateDisasmCPUFeatures(b"amdgcn--amdpal", cpu, features, None, 0, None, None)
    if not ctx:
        raise ValueError(f"LLVM has no {cpu.decode()} disassembler")
    raw = C.create_string_buffer(code)
    offset = 0
    instructions = []
    try:
        while offset < len(code):
            line = C.create_string_buffer(1024)
            size = llvm.LLVMDisasmInstruction(ctx, C.byref(raw, offset), len(code)-offset,
                                              offset, line, len(line))
            if not size:
                raise ValueError(f"Unknown instruction at byte {offset}")
            decoded = line.value.decode("ascii").strip()
            instructions.append((offset, decoded))
            offset += size
    finally:
        llvm.LLVMDisasmDispose(ctx)
    return instructions if offsets else name_branch_targets(instructions, len(code))


def name_branch_targets(decoded, end):
    """The instruction text of a decoded program with labels for its branches. The disassembler prints a branch
    target as a word offset: the target is the byte after the branch plus four times the signed 16-bit offset.
    Each target gets a label _L<n> in address order, placed before the instruction at that byte (or at the end)."""
    targets = {}
    for offset, text in decoded:
        if m := re.fullmatch(r"(?:s_branch|s_cbranch_\w+) (\d+)", text):
            words = int(m[1])
            target = offset + 4 + 4 * (words - 0x10000 if words >= 0x8000 else words)
            if target not in {at for at, _ in decoded} | {end}:
                raise ValueError(f"Branch at byte {offset} does not land on an instruction")
            targets[target] = None
    names = {target: f"_L{n}" for n, target in enumerate(sorted(targets))}
    program = []
    for offset, text in [*decoded, (end, None)]:
        if offset in names:
            program.append(f"{names[offset]}:")
        if text is None:
            continue
        if m := re.fullmatch(r"(s_branch|s_cbranch_\w+) (\d+)", text):
            words = int(m[2])
            text = f"{m[1]} {names[offset + 4 + 4 * (words - 0x10000 if words >= 0x8000 else words)]}"
        program.append(text)
    return program

# The lowering lives in tools/pixel_aot_ops/, one module per instruction family (docs/design/module-layout.md). These
# are the names this module has always offered; new code imports from the package.
from pixel_aot_ops.control_flow import (LABEL, find_loops, is_condition, plan_join, scope_free,  # noqa: E402,F401
                                        split_blocks, sync_lines, word_expr)
from pixel_aot_ops.compat import INTEGER, SCALAR, VOP3P_F16, VOP3P_INT16  # noqa: E402,F401
from pixel_aot_ops.forms.sdwa import SDWA_ALU, SDWA_SEL, sdwa_dest, sdwa_source  # noqa: E402,F401
from pixel_aot_ops.forms.sop2 import SALU_BIT64  # noqa: E402,F401
from pixel_aot_ops.forms.sopc import SCALAR_COMPARE  # noqa: E402,F401
from pixel_aot_ops.forms.sopp import HINT_LIMITS  # noqa: E402,F401
from pixel_aot_ops.forms.valu_f16 import F16_ALU  # noqa: E402,F401
from pixel_aot_ops.forms.valu_f32 import ALU  # noqa: E402,F401
from pixel_aot_ops.forms.valu_int import (INT_CLAMPED, INT_TERNARY, INT_VOP2, INT_VOP3, int_binary,  # noqa: E402,F401
                                          int_ternary, sext24)
from pixel_aot_ops.forms.vop3p import FMA_MIX_HELPERS, fma_mix_source  # noqa: E402,F401
from pixel_aot_ops.forms.vopc import COMPARE  # noqa: E402,F401
from pixel_aot_ops.hlsl import MEMORY_HELPERS, PREAMBLE, SALU_HELPERS, TITLE_DECLARATIONS, TITLE_LOOKUP  # noqa: E402,F401
from pixel_aot_ops.lowering import lower  # noqa: E402,F401
from pixel_aot_ops.registers import (F16_CONSTANT, LANE_MASK, RAW_WORD_PREFIXES, f16_bits,  # noqa: E402,F401
                                     f16_encoding, f16_exponent, f16_operand, fp_operand, lane_mask, raw_source,
                                     registers, scalar_u32, scalar_u64, sgpr_name, sgpr_pair, tracked_word, vector_u32,
                                     vgprs, word_of)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("record")
    parser.add_argument("--container-sha256", help="SHA-256 of the full decoded DXBC container to select by name")
    parser.add_argument("--llvm", required=True, help="LLVM C library with AMDGPU support")
    parser.add_argument("--texture-sgpr", type=int, required=True, help="Entry register for the low descriptor-table address")
    parser.add_argument("--interp-sgpr", type=int, required=True, help="Entry register for the interpolation base")
    profile = parser.add_mutually_exclusive_group(required=True)
    profile.add_argument("--no-texture", action="store_true", help="Require zero texture samples")
    profile.add_argument("--sampler-words", nargs=4, type=lambda s: int(s, 0),
                         help="Four descriptor words to bind to the supplied desktop sampler at s0")
    parser.add_argument("--output", type=Path, required=True, help="Destination .hlsl in a local output directory")
    parser.add_argument("--constant-descriptor", type=lambda s: int(s, 0),
                        help="Byte offset of a descriptor mapped to the 256-byte desktop buffer b0")
    parser.add_argument("--second-texture-offset", type=lambda s: int(s, 0), help="Byte offset of the t1 descriptor for a two-sample shader")
    args = parser.parse_args()
    dest = args.output.resolve()
    if dest.suffix.lower() != ".hlsl" or dest == args.archive.resolve():
        parser.error("Choose an HLSL destination distinct from the input")
    try:
        blob, code = native_program(args.archive, args.record, container_sha256=args.container_sha256, llvm=args.llvm)
        instructions = disassemble(code, args.llvm)
        source = lower(instructions, args.texture_sgpr, args.interp_sgpr, args.sampler_words, args.constant_descriptor, second_texture_offset=args.second_texture_offset)
    except (ValueError, KeyError, struct.error, OSError, AttributeError, zlib.error) as exc:
        parser.exit(1, f"Translation failed: {exc}\n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, mode="wb") as f:
        f.write(source.encode("utf-8"))
    Path(f.name).replace(dest)
    print(json.dumps({"record":args.record, "container_sha256":hashlib.sha256(blob).hexdigest(),
                      "native_sha256":hashlib.sha256(code).hexdigest(), "instructions":len(instructions),
                      "hlsl_sha256":hashlib.sha256(dest.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
