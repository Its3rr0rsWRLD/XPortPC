"""Lower the CRT-free x64 comparison EXE from its PE entry point (bounded fixture ABI)."""
import argparse
from pathlib import Path

import pefile
from iced_x86 import MemorySizeExt, Mnemonic as M, OpKind as K, Register as R, RegisterExt

from cpu_call_aot import lift_body, resolve_import
from cpu_leaf_aot import bounded_code, export_rva
from ffx_version_query import INTEGER_HEADER, lower, region


def require_local_pointer(previous, register, call, jump_targets):
    # No path may jump past the LEA that supplies the three-word buffer.
    if (previous.mnemonic != M.LEA or previous.op0_register != register
            or call.ip in jump_targets or previous.memory_displacement % 8):
        raise ValueError(f"expected aligned local trace pointer before call at {call.ip:#x}")


def translate(image, io_provider, mix_provider, *, entry_export=None):
    with pefile.PE(str(image), fast_load=True) as pe:
        if (pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20b
                or not pe.FILE_HEADER.Characteristics & 2
                or pe.FILE_HEADER.Characteristics & 0x2000):
            raise ValueError("expected an AMD64 PE32+ executable")
        directories = pe.OPTIONAL_HEADER.DATA_DIRECTORY
        if len(directories) > 9 and directories[9].VirtualAddress:
            raise ValueError("TLS startup is outside this entry profile")
        entry = (export_rva(pe, entry_export) if entry_export
                 else pe.OPTIONAL_HEADER.AddressOfEntryPoint)
        body = region(pe, entry, entry + len(bounded_code(pe, entry)))
        if len(body) < 3:
            raise ValueError("incomplete entry stack frame")
        # The virtual frame in lower() supplies the native caller's shadow space
        # and locals. Keep the epilogue as a label for the shared return path.
        prologue, epilogue, ret = body[0], body[-2], body[-1]
        for ins, op in ((prologue, M.SUB), (epilogue, M.ADD)):
            if (ins.mnemonic != op or ins.op0_register != R.RSP
                    or ins.op1_kind != K.IMMEDIATE8TO64 or ins.immediate(1) != 72):
                raise ValueError("unsupported entry stack frame")
        if ret.mnemonic != M.RET or ret.op_count:
            raise ValueError("expected return from process entry")
        pe.parse_data_directories(directories=[1])
        imports = {imp.address - pe.OPTIONAL_HEADER.ImageBase: imp.name
                   for module in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) for imp in module.imports}
        io_calls = {b"read_selector": "rax = read_selector();",
                    b"emit_trace": "rax = emit_trace(reinterpret_cast<const word*>(rcx));"}
        bindings = {}
        callee = None
        jump_targets = {ins.near_branch_target for ins in body if ins.op0_kind == K.NEAR_BRANCH64
                        and ins.mnemonic != M.CALL}
        for index, ins in enumerate(body[1:-2], start=1):
            if ins.mnemonic == M.CALL:
                if ins.op0_kind == K.NEAR_BRANCH64:
                    require_local_pointer(body[index - 1], R.R8, ins, jump_targets)
                    target = ins.near_branch_target
                    if callee is not None or entry <= target < ret.next_ip:
                        raise ValueError("expected a single separate internal callee")
                    native = bounded_code(pe, target)
                    if target < entry < target + len(native):
                        raise ValueError("overlapping entry and internal callee")
                    callee, edge = lift_body(target, native, caller=True,
                                             bind_import=lambda slot: resolve_import(
                                                 pe, slot, mix_provider, "mix_args"))
                    if edge[0] != "import" or edge[-1] != "mix_args":
                        raise ValueError("internal callee must reach the named provider")
                    bindings[ins.ip] = "rax = lifted(rcx, rdx, reinterpret_cast<word*>(r8));"
                elif ins.is_ip_rel_memory_operand:
                    slot = ins.ip_rel_memory_address
                    name = imports.get(slot)
                    if name not in io_calls:
                        raise ValueError("unsupported entry import")
                    if name == b"emit_trace":
                        require_local_pointer(body[index - 1], R.RCX, ins, jump_targets)
                    resolve_import(pe, slot, io_provider, name.decode("ascii"))
                    bindings[ins.ip] = io_calls[name]
                else:
                    raise ValueError("unsupported indirect entry call")
            elif ins.mnemonic not in (M.MOV, M.LEA, M.CMP, M.TEST, M.JE, M.JNE, M.JMP):
                raise ValueError(f"unsupported entry instruction at {ins.ip:#x}")
            elif (ins.mnemonic in (M.MOV, M.LEA) and ins.op0_kind == K.REGISTER
                    and RegisterExt.full_register(ins.op0_register) == R.RSP):
                raise ValueError("unsupported change to entry stack pointer")
            elif any(ins.op_kind(n) == K.MEMORY for n in range(ins.op_count)):
                offset = ins.memory_displacement
                width = 24 if ins.mnemonic == M.LEA else MemorySizeExt.size(ins.memory_size)
                if (ins.memory_base != R.RSP or ins.memory_index != R.NONE
                        or offset < 32 or offset + width > 72):
                    raise ValueError("entry operand outside local frame")
        if callee is None:
            raise ValueError("expected an internal call in the entry profile")
        code = lower(body, [], {}, bindings, {}, host_ops={prologue.ip: ";", epilogue.ip: ";"})
    return INTEGER_HEADER + """
extern "C" __declspec(dllimport) uint32_t read_selector();
extern "C" __declspec(dllimport) uint32_t emit_trace(const word*);
extern "C" __declspec(dllimport) word mix_args(word, word, word*);
""" + callee + '\nint main() {\n' + code + '\n}\n'


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("image", "io_provider", "mix_provider", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--entry-export", help="translate this return-based export instead of the PE startup")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".cpp":
        parser.error("choose a .cpp output")
    source = translate(args.image, args.io_provider, args.mix_provider, entry_export=args.entry_export)
    args.output.write_text(source, encoding="ascii")
