"""gfx1013 machine code to the instruction text the translators read, without LLVM (runtime rung R3).

The translators (tools/vertex_aot.py, tools/pixel_aot.py) read instructions as llvm-mc 15 prints them. The graphics
shim translates at pipeline-creation time on a machine that may have no LLVM, so this module produces that text from
the pure-Python decoder tools/disasm_rdna2.py, corrected where its text differs from LLVM's:

- s_waitcnt: the gfx10 fields (vmcnt bits 3:0 and 15:14, expcnt 6:4, lgkmcnt 13:8), each printed only when below its
  maximum, in LLVM's order;
- SMEM (s_load, s_buffer_load): an immediate offset of 0 with a null SGPR offset prints as `null`;
- v_interp_mov_f32: the parameter field is p10, p20 or p0 (disasm_rdna2 prints it as a VGPR);
- 64-bit SALU operands (s_mov_b64, s_wqm_b64, s_and_b64): an SGPR pair prints as s[n:n+1] and exec_lo/vcc_lo as
  exec/vcc (disasm_rdna2 prints the low register only).
- s_barrier: no operand (disasm_rdna2 prints its zero immediate).

Only mnemonics whose text was compared with LLVM 15's disassembly (tests/runtime/r3_programs_check.py, which also
re-checks the list against llvm-mc when one is given) are accepted. Any other instruction is refused with its
mnemonic: give the translator libLLVM instead (X2W_LLVM_LIB), or extend VERIFIED with a comparison.
"""
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disasm_rdna2  # noqa: E402

# Mnemonics whose corrected text equals LLVM 15's for every encoding the check covers.
VERIFIED = frozenset({
    # Rung R3 (tests/runtime/r3_programs_check.py).
    "exp", "global_load_dword", "global_load_dwordx2", "global_load_dwordx4", "s_endpgm", "s_load_dword",
    "s_load_dwordx2", "s_load_dwordx4", "s_mov_b32", "s_waitcnt", "v_interp_mov_f32_e32", "v_lshlrev_b32_e32",
    "v_mov_b32_e32",
    # Rung R4 (tests/runtime/r4_programs_check.py).
    "image_sample", "s_and_b64", "s_buffer_load_dword", "s_buffer_load_dwordx2", "s_buffer_load_dwordx4",
    "s_load_dwordx8", "s_mov_b64", "s_movk_i32", "s_wqm_b64", "v_add_f32_e32", "v_add_nc_u32_e32",
    "v_interp_p1_f32_e32", "v_interp_p2_f32_e32", "v_mul_f32_e32",
})
# Added for the compute program of runtime rung R5 (tests/runtime/r5_cs.s), compared by tests/runtime/r5_programs_check.py.
VERIFIED = VERIFIED | frozenset({
    "buffer_load_dwordx4", "buffer_store_dwordx2", "ds_bpermute_b32", "buffer_store_dwordx4", "s_lshl_b32", "s_movk_i32",
    "s_barrier", "v_add_f32_e32", "v_add_nc_u32_e32", "v_subrev_f32_e32",
})
# Added for the programs of runtime rung R6 (tests/runtime/r6_*.s), compared by tests/runtime/r6_programs_check.py.
VERIFIED = VERIFIED | frozenset({"image_load", "image_sample_lz", "v_cvt_f32_u32_e32"})
# 64-bit scalar operations whose operands disasm_rdna2 prints as their low 32-bit register.
PAIR_OPERANDS = frozenset({"s_and_b64", "s_mov_b64", "s_wqm_b64"})


def _pairs(text):
    """The operands of a 64-bit SALU instruction as LLVM prints them: s[n:n+1], exec, vcc."""
    head, _, rest = text.partition(" ")

    def one(token):
        token = token.strip()
        if m := re.fullmatch(r"s(\d+)", token):
            n = int(m[1])
            if n % 2:
                raise ValueError(f"{head}: 64-bit operand s{n} is not an even SGPR")
            return f"s[{n}:{n + 1}]"
        return {"exec_lo": "exec", "vcc_lo": "vcc"}.get(token, token)
    return head + " " + ", ".join(one(token) for token in rest.split(","))


def _waitcnt(word):
    simm = word & 0xffff
    fields = [("vmcnt", (simm & 0xf) | ((simm >> 14) & 3) << 4, 63), ("expcnt", (simm >> 4) & 7, 7),
              ("lgkmcnt", (simm >> 8) & 0x3f, 63)]
    if simm & 0x80:
        raise ValueError(f"s_waitcnt {simm:#06x} sets bit 7, outside the gfx10 counter fields")
    shown = [f"{name}({value})" for name, value, top in fields if value != top]
    if not shown:
        raise ValueError("s_waitcnt with every counter at its maximum is not verified against LLVM")
    return "s_waitcnt " + " ".join(shown)


def decode(code):
    """(byte offset, text) for each instruction of `code`, as pixel_aot.disassemble(offsets=True) returns them.
    Raises ValueError for an instruction outside VERIFIED, a truncated instruction or code after s_endpgm."""
    if len(code) % 4:
        raise ValueError("Code size is not a multiple of 4 bytes")
    out, offset = [], 0
    while offset < len(code):
        length, name, text, _ = disasm_rdna2.decode_instruction(code, offset)
        if name not in VERIFIED or offset + length > len(code):
            raise ValueError(f"Instruction {name} at byte {offset} is not verified against LLVM 15's disassembly "
                             "(tools/gfx_text.py); give the translator libLLVM (X2W_LLVM_LIB)")
        word, = struct.unpack_from("<I", code, offset)
        if name == "s_waitcnt":
            text = _waitcnt(word)
        elif name.startswith(("s_load_dword", "s_buffer_load_dword")):
            text = re.sub(r", 0x0$", ", null", text)
        elif name in PAIR_OPERANDS:
            text = _pairs(text)
        elif name == "v_interp_mov_f32_e32":
            param = {0: "p10", 1: "p20", 2: "p0"}.get(word & 0xff)
            if param is None:
                raise ValueError(f"v_interp_mov_f32 at byte {offset} has an invalid parameter {word & 0xff}")
            text = re.sub(r"^(v_interp_mov_f32_e32 v\d+), v\d+,", rf"\1, {param},", text)
        elif name == "s_barrier":
            if word & 0xffff:
                raise ValueError(f"s_barrier at byte {offset} has a non-zero immediate")
            text = "s_barrier"
        out.append((offset, " ".join(text.split())))
        offset += length
        if name == "s_endpgm" and offset != len(code):
            raise ValueError("Code continues after s_endpgm")
    return out
