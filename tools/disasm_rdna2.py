#!/usr/bin/env python3
"""
AMD RDNA 2 (GFX1013 / Scarlett) Shader Disassembler & Inspector.

Decodes raw binary machine code (.bin) from Xbox Scarlett shaders,
prints human-readable assembly with byte offsets, raw hex words, register
tracking, and explanations mapped to the AMD RDNA 2 ISA manual.
"""

import argparse
from collections import Counter
import os
from pathlib import Path
import struct
import sys

# Register decode helpers
def decode_s_reg(reg_id: int) -> str:
    """Decode scalar register or scalar constant code."""
    if reg_id <= 105:
        return f"s{reg_id}"
    if reg_id == 106:
        return "vcc_lo"
    if reg_id == 107:
        return "vcc_hi"
    if 108 <= reg_id <= 123:
        return f"ttmp{reg_id - 108}"
    if reg_id == 124:
        return "m0"
    if reg_id == 125:
        return "null"
    if reg_id == 126:
        return "exec_lo"
    if reg_id == 127:
        return "exec_hi"
    if 128 <= reg_id <= 192:
        return str(reg_id - 128)
    if 193 <= reg_id <= 208:
        return str(-(reg_id - 192))
    if reg_id == 240:
        return "0.5"
    if reg_id == 241:
        return "-0.5"
    if reg_id == 242:
        return "1.0"
    if reg_id == 243:
        return "-1.0"
    if reg_id == 244:
        return "2.0"
    if reg_id == 245:
        return "-2.0"
    if reg_id == 246:
        return "4.0"
    if reg_id == 247:
        return "-4.0"
    if reg_id == 255:
        return "literal"
    return f"s{reg_id}"


def decode_s_reg64(reg_id: int) -> str:
    """Decode a 64-bit scalar operand as an SGPR pair or a named 64-bit special."""
    if reg_id <= 105 and reg_id % 2 == 0:
        return f"s[{reg_id}:{reg_id + 1}]"
    if reg_id == 106:
        return "vcc"
    if 108 <= reg_id <= 122 and (reg_id - 108) % 2 == 0:
        n = reg_id - 108
        return f"ttmp[{n}:{n + 1}]"
    if reg_id == 125:
        return "null"
    if reg_id == 126:
        return "exec"
    return decode_s_reg(reg_id)


def decode_v_reg(reg_id: int) -> str:
    """Decode a 9-bit VOP SRC0 operand: 0..255 scalar/constant, 256..511 VGPR."""
    if 256 <= reg_id <= 511:
        return f"v{reg_id - 256}"
    return decode_s_reg(reg_id)


# Instruction Opcode Tables
SOPP_OPS = {
    0x00: ("s_nop", "No operation (wait cycles)"),
    0x01: ("s_endpgm", "Terminate shader execution"),
    0x02: ("s_branch", "Unconditional branch"),
    0x04: ("s_cbranch_scc0", "Branch if SCC == 0"),
    0x05: ("s_cbranch_scc1", "Branch if SCC == 1"),
    0x06: ("s_cbranch_vccz", "Branch if VCC is zero"),
    0x07: ("s_cbranch_vccnz", "Branch if VCC is non-zero"),
    0x08: ("s_cbranch_execz", "Branch if EXEC is zero"),
    0x09: ("s_cbranch_execnz", "Branch if EXEC is non-zero"),
    0x0a: ("s_barrier", "Synchronize wavefronts in workgroup"),
    0x0c: ("s_waitcnt", "Wait for memory operations"),
    0x20: ("s_inst_prefetch", "Instruction cache prefetch"),
    0x21: ("s_clause", "Begin hard clause"),
}

SOP1_OPS = {
    0x03: ("s_mov_b32", "Scalar move 32-bit"),
    0x04: ("s_mov_b64", "Scalar move 64-bit"),
    0x05: ("s_cmov_b32", "Scalar conditional move 32-bit"),
    0x06: ("s_cmov_b64", "Scalar conditional move 64-bit"),
    0x07: ("s_not_b32", "Scalar bitwise NOT 32-bit"),
    0x08: ("s_not_b64", "Scalar bitwise NOT 64-bit"),
    0x09: ("s_wqm_b32", "Scalar whole-quad-mode 32-bit"),
    0x0a: ("s_wqm_b64", "Scalar whole-quad-mode 64-bit"),
    0x20: ("s_setpc_b64", "Set program counter 64-bit"),
    0x21: ("s_swappc_b64", "Swap program counter 64-bit"),
}

SOP2_OPS = {
    0x00: ("s_add_u32", "Scalar add unsigned 32-bit"),
    0x01: ("s_sub_u32", "Scalar sub unsigned 32-bit"),
    0x02: ("s_add_i32", "Scalar add signed 32-bit"),
    0x03: ("s_sub_i32", "Scalar sub signed 32-bit"),
    0x06: ("s_min_i32", "Scalar minimum signed 32-bit"),
    0x07: ("s_min_u32", "Scalar minimum unsigned 32-bit"),
    0x08: ("s_max_i32", "Scalar maximum signed 32-bit"),
    0x09: ("s_max_u32", "Scalar maximum unsigned 32-bit"),
    0x0a: ("s_cselect_b32", "Scalar conditional select 32-bit"),
    0x0e: ("s_and_b32", "Scalar bitwise AND 32-bit"),
    0x0f: ("s_and_b64", "Scalar bitwise AND 64-bit"),
    0x10: ("s_or_b32", "Scalar bitwise OR 32-bit"),
    0x11: ("s_or_b64", "Scalar bitwise OR 64-bit"),
    0x12: ("s_xor_b32", "Scalar bitwise XOR 32-bit"),
    0x13: ("s_xor_b64", "Scalar bitwise XOR 64-bit"),
    0x14: ("s_andn2_b32", "Scalar AND with NOT 32-bit"),
    0x15: ("s_andn2_b64", "Scalar AND with NOT 64-bit"),
    0x1e: ("s_lshl_b32", "Scalar logical shift left 32-bit"),
    0x1f: ("s_lshl_b64", "Scalar logical shift left 64-bit"),
    0x20: ("s_lshr_b32", "Scalar logical shift right 32-bit"),
    0x21: ("s_lshr_b64", "Scalar logical shift right 64-bit"),
    0x22: ("s_ashr_i32", "Scalar arithmetic shift right 32-bit"),
    0x26: ("s_mul_i32", "Scalar multiply signed 32-bit"),
}

SOPK_OPS = {
    0x00: ("s_movk_i32", "Scalar move 16-bit sign-extended immediate"),
    0x02: ("s_cmovk_i32", "Scalar conditional move immediate"),
    0x03: ("s_cmpk_eq_i32", "Scalar compare equal immediate"),
    0x04: ("s_cmpk_lg_i32", "Scalar compare not-equal immediate"),
    0x05: ("s_cmpk_gt_i32", "Scalar compare greater immediate"),
    0x0f: ("s_addk_i32", "Scalar add immediate"),
    0x10: ("s_mulk_i32", "Scalar multiply immediate"),
    0x17: ("s_waitcnt_vscnt", "Wait for vector store counter"),
    0x18: ("s_waitcnt_vmcnt", "Wait for vector memory counter"),
    0x19: ("s_waitcnt_expcnt", "Wait for export counter"),
    0x1a: ("s_waitcnt_lgkmcnt", "Wait for LDS/GDS/K/M counter"),
}

SOPC_OPS = {
    # GFX10 / RDNA 2 opcode numbers, as in LLVM SOPC_Real_gfx10 definitions
    0x00: ("s_cmp_eq_i32", "Scalar compare equal signed 32-bit"),
    0x01: ("s_cmp_lg_i32", "Scalar compare not-equal signed 32-bit"),
    0x02: ("s_cmp_gt_i32", "Scalar compare greater signed 32-bit"),
    0x03: ("s_cmp_ge_i32", "Scalar compare greater-or-equal signed 32-bit"),
    0x04: ("s_cmp_lt_i32", "Scalar compare less signed 32-bit"),
    0x05: ("s_cmp_le_i32", "Scalar compare less-or-equal signed 32-bit"),
    0x06: ("s_cmp_eq_u32", "Scalar compare equal unsigned 32-bit"),
    0x07: ("s_cmp_lg_u32", "Scalar compare not-equal unsigned 32-bit"),
    0x08: ("s_cmp_gt_u32", "Scalar compare greater unsigned 32-bit"),
    0x09: ("s_cmp_ge_u32", "Scalar compare greater-or-equal unsigned 32-bit"),
    0x0a: ("s_cmp_lt_u32", "Scalar compare less unsigned 32-bit"),
    0x0b: ("s_cmp_le_u32", "Scalar compare less-or-equal unsigned 32-bit"),
    0x0c: ("s_bitcmp0_b32", "Scalar test that bit src1 of src0 is zero"),
    0x0d: ("s_bitcmp1_b32", "Scalar test that bit src1 of src0 is one"),
    0x0e: ("s_bitcmp0_b64", "Scalar test that bit src1 of 64-bit src0 is zero"),
    0x0f: ("s_bitcmp1_b64", "Scalar test that bit src1 of 64-bit src0 is one"),
    0x12: ("s_cmp_eq_u64", "Scalar compare equal unsigned 64-bit"),
    0x13: ("s_cmp_lg_u64", "Scalar compare not-equal unsigned 64-bit"),
}

SMEM_OPS = {
    0x00: "s_load_dword",
    0x01: "s_load_dwordx2",
    0x02: "s_load_dwordx4",
    0x03: "s_load_dwordx8",
    0x04: "s_load_dwordx16",
    0x08: "s_buffer_load_dword",
    0x09: "s_buffer_load_dwordx2",
    0x0a: "s_buffer_load_dwordx4",
    0x0b: "s_buffer_load_dwordx8",
    0x0c: "s_buffer_load_dwordx16",
}

VOP1_OPS = {
    0x00: ("v_nop", "Vector no-op"),
    0x01: ("v_mov_b32_e32", "Vector copy 32-bit"),
    0x02: ("v_readfirstlane_b32", "Read first active lane into SGPR"),
    0x05: ("v_cvt_f32_i32_e32", "Convert int32 to float32"),
    0x06: ("v_cvt_f32_u32_e32", "Convert uint32 to float32"),
    0x07: ("v_cvt_u32_f32_e32", "Convert float32 to uint32"),
    0x08: ("v_cvt_i32_f32_e32", "Convert float32 to int32"),
    0x0a: ("v_cvt_f16_f32_e32", "Convert float32 to float16"),
    0x0b: ("v_cvt_f32_f16_e32", "Convert float16 to float32"),
    0x25: ("v_exp_f32_e32", "Exponent 2^x float32"),
    0x27: ("v_log_f32_e32", "Logarithm log2(x) float32"),
    0x2a: ("v_rcp_f32_e32", "Reciprocal 1/x float32"),
    0x2e: ("v_rsq_f32_e32", "Reciprocal square root 1/sqrt(x)"),
    0x33: ("v_sqrt_f32_e32", "Square root sqrt(x) float32"),
    0x35: ("v_sin_f32_e32", "Sine float32"),
    0x36: ("v_cos_f32_e32", "Cosine float32"),
    0x37: ("v_not_b32_e32", "Vector bitwise NOT"),
    0x38: ("v_bfrev_b32_e32", "Vector bit-reverse"),
}

VOP2_OPS = {
    0x01: ("v_cndmask_b32_e32", "Vector conditional mask select"),
    0x03: ("v_add_f32_e32", "Vector add float32"),
    0x04: ("v_sub_f32_e32", "Vector subtract float32"),
    0x05: ("v_subrev_f32_e32", "Vector reverse subtract float32"),
    0x07: ("v_mul_legacy_f32_e32", "Vector multiply zero-preserving float32"),
    0x08: ("v_mul_f32_e32", "Vector multiply float32"),
    0x0f: ("v_min_f32_e32", "Vector minimum float32"),
    0x10: ("v_max_f32_e32", "Vector maximum float32"),
    0x11: ("v_min_i32_e32", "Vector minimum int32"),
    0x12: ("v_max_i32_e32", "Vector maximum int32"),
    0x13: ("v_min_u32_e32", "Vector minimum uint32"),
    0x14: ("v_max_u32_e32", "Vector maximum uint32"),
    0x16: ("v_lshrrev_b32_e32", "Vector shift right logical"),
    0x18: ("v_ashrrev_i32_e32", "Vector shift right arithmetic"),
    0x1a: ("v_lshlrev_b32_e32", "Vector shift left logical"),
    0x1b: ("v_and_b32_e32", "Vector bitwise AND"),
    0x1c: ("v_or_b32_e32", "Vector bitwise OR"),
    0x1d: ("v_xor_b32_e32", "Vector bitwise XOR"),
    0x25: ("v_add_nc_u32_e32", "Vector add uint32 without carry"),
    0x26: ("v_sub_nc_u32_e32", "Vector sub uint32 without carry"),
    0x27: ("v_subrev_nc_u32_e32", "Vector reverse sub uint32 without carry"),
    0x2b: ("v_fmac_f32_e32", "Vector fused multiply-accumulate float32"),
    0x2f: ("v_cvt_pkrtz_f16_f32_e32", "Convert two float32 to packed float16 (round to zero)"),
}

EXP_TARGETS = {
    0: "mrt0", 1: "mrt1", 2: "mrt2", 3: "mrt3",
    4: "mrt4", 5: "mrt5", 6: "mrt6", 7: "mrt7",
    8: "z", 9: "null",
    12: "pos0", 13: "pos1", 14: "pos2", 15: "pos3",
}


def decode_instruction(data: bytes, offset: int) -> tuple[int, str, str, str]:
    """
    Decode one RDNA 2 instruction at given offset.
    Returns: (instruction_byte_length, opcode_name, assembly_string, comment)
    """
    if offset + 4 > len(data):
        return (len(data) - offset, "data", f".byte {data[offset:].hex()}", "Trailing bytes")

    w0, = struct.unpack_from("<I", data, offset)

    # 1. SOPP: [31:23] == 0b101111111 (0xbf800000)
    if (w0 & 0xff800000) == 0xbf800000:
        op = (w0 >> 16) & 0x7f
        simm = w0 & 0xffff
        signed_simm = simm if simm < 0x8000 else simm - 0x10000
        op_info = SOPP_OPS.get(op, (f"s_sopp_{op:02x}", "Unknown SOPP"))
        op_name, comment = op_info

        if op_name == "s_endpgm":
            asm = "s_endpgm"
        elif op_name == "s_nop":
            asm = f"s_nop {simm}"
        elif op_name == "s_waitcnt":
            vm = (simm >> 4) & 0xf
            lgkm = (simm >> 8) & 0x3f
            asm = f"s_waitcnt vmcnt({vm}) lgkmcnt({lgkm})"
        elif op_name.startswith("s_cbranch") or op_name == "s_branch":
            target = offset + 4 + signed_simm * 4
            asm = f"{op_name} label_0x{target:x}"
        else:
            asm = f"{op_name} 0x{simm:x}"
        return (4, op_name, asm, comment)

    # 2. SOP1: [31:23] == 0b101111101 (0xbe800000)
    if (w0 & 0xff800000) == 0xbe800000:
        sdst = (w0 >> 16) & 0x7f
        op = (w0 >> 8) & 0xff
        ssrc0 = w0 & 0xff
        op_info = SOP1_OPS.get(op, (f"s_sop1_{op:02x}", "Unknown SOP1"))
        op_name, comment = op_info
        asm = f"{op_name} {decode_s_reg(sdst)}, {decode_s_reg(ssrc0)}"
        return (4, op_name, asm, comment)

    # SOPC: [31:23] == 0b101111110 (0xbf000000)
    # Must run before the SOPK prefix check, which would otherwise consume these words.
    if (w0 & 0xff800000) == 0xbf000000:
        op = (w0 >> 16) & 0x7f
        ssrc1 = (w0 >> 8) & 0xff
        ssrc0 = w0 & 0xff
        op_info = SOPC_OPS.get(op, (f"s_sopc_{op:02x}", "Unknown SOPC"))
        op_name, comment = op_info
        length = 4
        literal = None
        if ssrc0 == 255 or ssrc1 == 255:
            if offset + 8 > len(data):
                return (4, "sopc_truncated", f"{op_name} <truncated>", "Incomplete SOPC literal")
            literal, = struct.unpack_from("<I", data, offset + 4)
            length = 8

        def sopc_operand(reg_id: int, wide: bool) -> str:
            if reg_id == 255 and literal is not None:
                return f"0x{literal:x}"
            if wide:
                return decode_s_reg64(reg_id)
            return decode_s_reg(reg_id)

        src0_wide = op_name in {"s_cmp_eq_u64", "s_cmp_lg_u64", "s_bitcmp0_b64", "s_bitcmp1_b64"}
        src1_wide = op_name in {"s_cmp_eq_u64", "s_cmp_lg_u64"}
        asm = f"{op_name} {sopc_operand(ssrc0, src0_wide)}, {sopc_operand(ssrc1, src1_wide)}"
        return (length, op_name, asm, comment)

    # 3. SOPK: [31:28] == 0b1011 (0xb0000000)
    if (w0 & 0xf0000000) == 0xb0000000 and (w0 & 0x0f800000) not in (0x0f800000, 0x0e800000, 0x0f000000):
        op = (w0 >> 23) & 0x1f
        sdst = (w0 >> 16) & 0x7f
        simm = w0 & 0xffff
        signed_simm = simm if simm < 0x8000 else simm - 0x10000
        op_info = SOPK_OPS.get(op, (f"s_sopk_{op:02x}", "Unknown SOPK"))
        op_name, comment = op_info
        asm = f"{op_name} {decode_s_reg(sdst)}, 0x{simm:x}"
        return (4, op_name, asm, comment)

    # 4. SOP2: [31:30] == 0b10 (0x80000000)
    if (w0 & 0xc0000000) == 0x80000000 and (w0 & 0x30000000) != 0x30000000:
        op = (w0 >> 23) & 0x7f
        sdst = (w0 >> 16) & 0x7f
        ssrc1 = (w0 >> 8) & 0xff
        ssrc0 = w0 & 0xff
        op_info = SOP2_OPS.get(op, (f"s_sop2_{op:02x}", "Unknown SOP2"))
        op_name, comment = op_info
        asm = f"{op_name} {decode_s_reg(sdst)}, {decode_s_reg(ssrc0)}, {decode_s_reg(ssrc1)}"
        return (4, op_name, asm, comment)

    # 5. VOP1: [31:25] == 0b0111111 (0x7e000000)
    if (w0 & 0xfe000000) == 0x7e000000:
        vdst = (w0 >> 17) & 0xff
        op = (w0 >> 9) & 0xff
        src0 = w0 & 0x1ff
        op_info = VOP1_OPS.get(op, (f"v_vop1_{op:02x}", "Unknown VOP1"))
        op_name, comment = op_info
        if op_name == "v_nop":
            asm = "v_nop"
        else:
            asm = f"{op_name} v{vdst}, {decode_v_reg(src0)}"
        return (4, op_name, asm, comment)

    # 6. VOP2: [31] == 0
    if (w0 & 0x80000000) == 0:
        op = (w0 >> 25) & 0x3f
        vdst = (w0 >> 17) & 0xff
        vsrc1 = (w0 >> 9) & 0xff
        src0 = w0 & 0x1ff
        op_info = VOP2_OPS.get(op, (f"v_vop2_{op:02x}", "Unknown VOP2"))
        op_name, comment = op_info
        if op_name == "v_cndmask_b32_e32":
            asm = f"{op_name} v{vdst}, {decode_v_reg(src0)}, v{vsrc1}, vcc_lo"
        else:
            asm = f"{op_name} v{vdst}, {decode_v_reg(src0)}, v{vsrc1}"
        return (4, op_name, asm, comment)

    # 7. VINTRP: [31:26] == 0b110010 (0xc8000000)
    if (w0 & 0xfc000000) == 0xc8000000:
        vdst = (w0 >> 18) & 0xff
        op = (w0 >> 16) & 0x3
        chan = "xyzw"[(w0 >> 14) & 0x3]
        attr = (w0 >> 8) & 0x3f
        vsrc = w0 & 0xff
        op_names = {0: "v_interp_p1_f32_e32", 1: "v_interp_p2_f32_e32", 2: "v_interp_mov_f32_e32"}
        op_name = op_names.get(op, f"v_interp_{op}")
        asm = f"{op_name} v{vdst}, v{vsrc}, attr{attr}.{chan}"
        comment = f"Parameter interpolation stage {op+1} for attribute {attr}.{chan}"
        return (4, op_name, asm, comment)

    # 8. EXP: 64-bit [31:26] == 0b111110 (0xf8000000)
    if (w0 & 0xfc000000) == 0xf8000000:
        if offset + 8 > len(data):
            return (4, "exp_truncated", "exp <truncated>", "Incomplete 64-bit export instruction")
        w1, = struct.unpack_from("<I", data, offset + 4)
        en = (w0 >> 16) & 0xf
        target = (w0 >> 20) & 0x3f
        compr = (w0 >> 24) & 1
        done = (w0 >> 25) & 1
        vm = (w0 >> 12) & 1
        v0 = w1 & 0xff
        v1 = (w1 >> 8) & 0xff
        v2 = (w1 >> 16) & 0xff
        v3 = (w1 >> 24) & 0xff
        target_name = EXP_TARGETS.get(target, f"target_{target}")
        flags = []
        if done: flags.append("done")
        if compr: flags.append("compr")
        if vm: flags.append("vm")
        flags_str = " ".join(flags)
        asm = f"exp {target_name} v{v0}, v{v1}, v{v2}, v{v3} {flags_str}".strip()
        comment = f"Export output pixels/attributes to {target_name.upper()}"
        return (8, "exp", asm, comment)

    # 9. SMEM: 64-bit [31:26] == 0b111101 (0xf4000000)
    if (w0 & 0xfc000000) == 0xf4000000:
        if offset + 8 > len(data):
            return (4, "smem_truncated", "smem <truncated>", "Incomplete 64-bit SMEM instruction")
        w1, = struct.unpack_from("<I", data, offset + 4)
        op = (w0 >> 18) & 0xff
        sdata = (w0 >> 6) & 0x7f
        sbase = (w0 & 0x3f) * 2
        op_name = SMEM_OPS.get(op, f"s_smem_{op:02x}")
        offset_val = w1 & 0x1fffff
        asm = f"{op_name} s[{sdata}:{sdata+3}], s[{sbase}:{sbase+1}], 0x{offset_val:x}"
        comment = "Scalar memory load from constant buffer/resource descriptor"
        return (8, op_name, asm, comment)

    # Default fallback: unknown 32-bit word
    return (4, f"word_0x{w0:08x}", f".long 0x{w0:08x}", "Unrecognized RDNA 2 instruction encoding")


def disassemble_binary(data: bytes, shader_name: str = "shader") -> list[dict]:
    """Disassemble raw binary RDNA 2 shader into structured instruction records."""
    instructions = []
    offset = 0
    while offset < len(data):
        length, op_name, asm, comment = decode_instruction(data, offset)
        hex_bytes = data[offset:offset + length].hex()
        instructions.append({
            "offset": offset,
            "length": length,
            "hex": hex_bytes,
            "opcode": op_name,
            "assembly": asm,
            "comment": comment,
        })
        offset += length
        if op_name == "s_endpgm":
            # Some shaders have 4 trailing zero padding bytes after endpgm
            break
    return instructions


# Alias for library usage
disasm_rdna2 = disassemble_binary


def print_disassembly(shader_name: str, instructions: list[dict], show_comments: bool = True):
    """Print beautifully formatted disassembly with offsets and annotations."""
    print("=" * 80)
    print(f" RDNA 2 DISASSEMBLY: {shader_name} ")
    print("=" * 80)
    print(f"{'Offset':<8} {'Raw Hex':<18} {'Assembly':<42} {'Notes'}")
    print("-" * 80)

    for item in instructions:
        off_str = f"+0x{item['offset']:04x}"
        hex_str = item["hex"]
        asm_str = item["assembly"]
        comment_str = f"// {item['comment']}" if (show_comments and item["comment"]) else ""
        print(f"{off_str:<8} {hex_str:<18} {asm_str:<42} {comment_str}")

    print("=" * 80)
    total_bytes = sum(i["length"] for i in instructions)
    opcodes = Counter(i["opcode"] for i in instructions)
    print(f"Summary: {len(instructions)} instructions | {total_bytes} bytes | Top opcodes: {', '.join(f'{k}:{v}' for k, v in opcodes.most_common(5))}")
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="*", type=Path, default=[], help="Path to shader binary .bin file(s) or folder")
    parser.add_argument("--hex", default=None, help="Direct hex string to decode (e.g. '0300a0bf8002047e')")
    parser.add_argument("--output", type=Path, default=None, help="Save disassembly listing to output file")

    args = parser.parse_args()

    # Hex decode mode
    if args.hex:
        raw_bytes = bytes.fromhex(args.hex.replace(" ", ""))
        insns = disassemble_binary(raw_bytes, "hex_input")
        print_disassembly("hex_input", insns)
        return 0

    if not args.targets:
        parser.error("Specify targets or provide hex via --hex")

    all_listings = []
    for target in args.targets:
        if target.is_file():
            data = target.read_bytes()
            insns = disassemble_binary(data, target.name)
            print_disassembly(target.name, insns)
            all_listings.append((target.name, insns))
        elif target.is_dir():
            files = sorted(target.glob("*.bin"))
            print(f"[*] Found {len(files)} shader binary files in {target.name}...")
            for f in files[:20]:  # Limit preview to 20 when folder passed
                data = f.read_bytes()
                insns = disassemble_binary(data, f.name)
                print_disassembly(f.name, insns)
                all_listings.append((f.name, insns))

    if args.output and all_listings:
        with args.output.open("w", encoding="utf-8") as out_f:
            for name, insns in all_listings:
                out_f.write(f"; Disassembly: {name}\n")
                for item in insns:
                    out_f.write(f"    {item['assembly']:<40} ; +0x{item['offset']:04x} // {item['comment']}\n")
                out_f.write("\n")
        print(f"[+] Disassembly saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
