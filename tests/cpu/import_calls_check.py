"""Differential checks, fault checks and rejection controls for ordinary calls of a bound import.

Two callers are built from import_calls.asm, linked against the named and the altered provider of
cpu_aot_import_tail_jump (tail_provider.cpp; the altered one returns one more). Each caller is translated three
times, as listed in CMakeLists.txt and in TRANSLATIONS below, and every export takes three arguments. The named
caller's three translations are also built with a separate cl /O2 command."""

import ctypes
import hashlib
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory

import pefile
from iced_x86 import Decoder, FlowControl, Mnemonic, Register

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_switch_aot import Binding, runtime_functions, translate
from direct_check import GUARDS, MASK, SENTINELS, Word, input_pairs, observe, register_probe

VARIANTS = ("named", "altered")
# Each translation of a caller: the import, its argument count, the guaranteed bytes and the export list.
TRANSLATIONS = {"mix3": ("mix3", 3, 8, ("call_keep", "call_twice", "outer_call", "pass_result", "read_then_call",
                                        "call_then_read")),
                "low": ("mix3", 3, 1, ("low_result",)),
                "mix4": ("mix4", 4, 8, ("thunk_call", "thunk_tail", "outer_tail"))}
# Exports that read memory at x: only the fault check calls them.
ADDRESSED = ("read_then_call", "call_then_read")
# Import calls ("rax = ...") and tail jumps ("return ...") of the import in each translation, internal callees
# included, and the number of internal callees.
SITES = {"mix3": (7, 0, 1), "low": (1, 0, 0), "mix4": (1, 2, 1)}
CALLS_THROUGH_SLOT = ("call_keep", "call_twice", "pass_result", "read_then_call", "call_then_read", "low_result",
                      "clobber_read", "table_after_call", "call_guest_arg")
PAGE = 0x1000
VALUE = 0xfedcba9876543210
ACCESS_VIOLATION = 0xC0000005
SCN_READ = 0x40000000


def mix3(first, second, altered):
    first, second = first & MASK, second & MASK
    stored = (first - second + 11) & MASK
    return (stored * 3 + (first >> 5) + altered) & MASK, (first, second, stored)


def mix4(first, second, fourth, altered):
    first, second, fourth = first & MASK, second & MASK, fourth & MASK
    return ((((first - second) * 3) ^ fourth) + altered) & MASK, (first, second, fourth)


def reference(name, x, y, altered):
    """RAX and the guarded trace after name(x, y, trace)."""
    if name == "call_keep":
        value, words = mix3(x + 3, y, altered)
        rax = (value ^ x) + y
    elif name == "call_twice":
        first, _ = mix3(x, y, altered)
        value, words = mix3(first, y, altered)
        rax = value + y
    elif name == "outer_call":
        value, words = mix3(x, y + 7, altered)
        rax = value + 1 + x
    elif name == "pass_result":
        rax, words = mix3(x, y, altered)
    elif name == "low_result":
        value, words = mix3(x, y, altered)
        rax = (value & 0xff) + x
    elif name == "thunk_call":
        value, words = mix4(x, y, x ^ y, altered)
        rax = value - x
    elif name == "thunk_tail":
        rax, words = mix4(x, y, x + y, altered)
    else:  # outer_tail
        value, words = mix4(x + 1, y, y - (x + 1), altered)
        rax = value + y
    return rax & MASK, (GUARDS[0], *words, GUARDS[1])


def code(pe, rva):
    """The instructions from rva up to the first RET or unconditional jump."""
    out = []
    for ins in Decoder(64, pe.get_data(rva, 0x60), ip=rva):
        out.append(ins)
        if ins.flow_control in (FlowControl.RETURN, FlowControl.UNCONDITIONAL_BRANCH, FlowControl.INDIRECT_BRANCH):
            return out
    raise AssertionError(f"no end of function at RVA {rva:#x}")


def layout(caller, provider):
    """RVAs of the exports, the two internal callees, embed_site, the import thunk of mix4 and the IAT slots,
    after checking each call or jump of the import by its encoding."""
    with pefile.PE(str(caller), fast_load=True) as pe:
        pe.parse_data_directories(directories=[0, 1])
        desc, = [d for d in pe.DIRECTORY_ENTRY_IMPORT if d.dll.decode("ascii").casefold() == provider.name.casefold()]
        slots = {imp.name.decode("ascii"): desc.struct.FirstThunk + 8 * n for n, imp in enumerate(desc.imports)}
        rvas = {"terminator": desc.struct.FirstThunk + 8 * len(desc.imports)}
        if sorted(slots) != ["mix3", "mix4"] or pe.get_qword_at_rva(rvas["terminator"]) != 0:
            raise AssertionError(f"{caller.name}: unexpected import table {slots}")
        exports = {e.name.decode("ascii"): e.address for e in pe.DIRECTORY_ENTRY_EXPORT.symbols}
        rvas.update(exports)
        records = runtime_functions(pe)

        def raw(ins):
            return pe.get_data(ins.ip, ins.len)

        def slot(ins):
            return ins.next_ip + struct.unpack_from("<i", raw(ins), 2)[0]

        for name in CALLS_THROUGH_SLOT:
            for ins in (i for i in code(pe, rvas[name]) if i.flow_control == FlowControl.INDIRECT_CALL):
                if raw(ins)[:2] != b"\xff\x15" or ins.len != 6 or slot(ins) != slots["mix3"]:
                    raise AssertionError(f"{name}: {raw(ins).hex()} ({ins}) is not FF 15 to the slot of mix3")
        body = {name: code(pe, rvas[name]) for name in ("thunk_call", "thunk_tail", "outer_call", "outer_tail")}
        call = next(i for i in body["thunk_call"] if i.flow_control == FlowControl.CALL)
        jump = body["thunk_tail"][-1]
        rvas["thunk"] = call.near_branch_target
        thunk = code(pe, rvas["thunk"])
        if (raw(call)[0] != 0xe8 or raw(jump)[0] not in (0xe9, 0xeb) or jump.near_branch_target != rvas["thunk"]
                or len(thunk) != 1 or raw(thunk[0])[:2] != b"\xff\x25" or thunk[0].len != 6
                or slot(thunk[0]) != slots["mix4"] or rvas["thunk"] in exports.values()
                or any(begin < rvas["thunk"] + 6 and rvas["thunk"] < end for begin, end in records)):
            raise AssertionError(f"{caller.name}: thunk_call and thunk_tail do not reach an import thunk of mix4")
        for caller_name, callee in (("outer_call", "inner_call"), ("outer_tail", "inner_tail")):
            rvas[callee] = next(i for i in body[caller_name] if i.flow_control == FlowControl.CALL).near_branch_target
        inner = code(pe, rvas["inner_tail"])[-1]
        if raw(inner)[:2] != b"\xff\x25" or slot(inner) != slots["mix4"]:
            raise AssertionError(f"{caller.name}: inner_tail does not jump through the slot of mix4")
        rvas["inner_jump"] = inner.ip
        rvas["embed_site"] = code(pe, rvas["call_guest_arg"])[-1].next_ip
        mov = code(pe, rvas["embed_site"])[0]
        site = rvas["embed_site"]
        if (any(begin < site + 11 and site < end for begin, end in records) or raw(mov)[:2] != b"\x48\xb8"
                or mov.len != 10 or site in exports.values() or max(end for _, end in records if end <= site) != site):
            raise AssertionError(f"{caller.name}: embed_site is not a 10-byte MOV right after an unwind interval")
    print(f"{caller.name}: {', '.join(CALLS_THROUGH_SLOT)} call FF 15 disp32 through the IAT slot of mix3; "
          f"thunk_call calls (E8) and thunk_tail jumps to the thunk at RVA {rvas['thunk']:#x}, FF 25 disp32 through "
          "the slot of mix4, outside every unwind interval and not exported; inner_tail jumps FF 25 through the "
          "same slot")
    return rvas, slots


def binding(provider, symbol, arguments=None, return_bytes=8):
    return Binding(provider, symbol, None, arguments or (3 if symbol == "mix3" else 4), return_bytes)


def check_sources(variant, caller, built, provider):
    """The built sources are the translations of the listed entries, with the import declared once, each call
    and tail jump passing the binding's number of arguments, each internal callee defined once."""
    for key, (symbol, arguments, stated, entries) in TRANSLATIONS.items():
        source, functions = translate(caller, list(entries), binding=binding(provider, symbol, arguments, stated))
        if Path(built[key]).read_text(encoding="utf-8") != source:
            raise AssertionError(f"{built[key]} is not the translation of {','.join(entries)} bound to {symbol}")
        passed = ", ".join(("rcx", "rdx", "r8", "r9")[:arguments])
        lines = [line.strip() for line in source.splitlines()]
        counts = (lines.count(f"rax = {symbol}({passed});"), lines.count(f"return {symbol}({passed});"),
                  source.count("static word fn_"))
        declaration = f'extern "C" __declspec(dllimport) word {symbol}({", ".join(["word"] * arguments)});'
        widths = [function.return_width for function in functions]
        if lines.count(declaration) != 1 or counts != SITES[key] or widths != [8] * len(entries):
            raise AssertionError(f"{variant} {key}: {counts} calls, tail jumps and callees, widths {widths}:\n{source}")
        print(f"{variant} {','.join(entries)} bound to {symbol} with {arguments} arguments and {stated} guaranteed "
              f"byte(s): {counts[0]} x rax = {symbol}({passed}); {counts[1]} x return {symbol}({passed}); "
              f"{counts[2]} internal callee(s); return widths {widths}")


def check_return_widths(caller, provider):
    """A call contributes to the return width only through the RAX bytes defined at a later RET; a tail jump to
    the thunk contributes the binding's number, as one through the IAT does."""
    tail = ("{} low byte(s) at every reachable normal return: no RET is reachable, {} guaranteed after every tail "
            "jump to mix4 as the binding states")
    for name, stated, width in (("pass_result", 8, 8), ("pass_result", 2, 2), ("pass_result", 1, 1),
                                ("pass_result", 0, 0), ("low_result", 1, 8), ("thunk_tail", 8, 8),
                                ("thunk_tail", 0, 0)):
        symbol = "mix4" if name == "thunk_tail" else "mix3"
        if name == "thunk_tail":
            comments = ["// RAX: " + tail.format(width, stated)]
        else:
            comments = [f"// RAX: {width} low byte(s) are defined at every reachable RET"] if width < 8 else []
        source, (function,) = translate(caller, [name], binding=binding(provider, symbol, return_bytes=stated))
        found = [line for line in source.splitlines() if line.startswith("// RAX: ")]
        if function.return_width != width or found != comments:
            raise AssertionError(f"{name} with {stated} stated bytes: width {function.return_width}, {found}")
        print(f"inspected {name} with {stated} stated byte(s): return_width {width}, "
              f"comment {comments[0] if comments else 'none (8 bytes)'}")


def check_execution(probe_path, builds, optimized):
    probe = register_probe(probe_path)
    if observe(probe, ctypes.CDLL(probe_path).clobber_control, 0, 0)[2] != (0, 0):
        raise AssertionError("physical register probe missed the clobber control")
    print("control clobber_control through probe: RBX and RSI sampled as 0 and 0")
    inputs = input_pairs()
    results = {}
    sides = [(variant, variant, paths) for variant, paths in builds.items()]
    sides.append(("named /O2", "named", (builds["named"][0], optimized["mix3"], None, optimized["low"], None,
                                         optimized["mix4"], None, None)))
    for label, variant, (caller, mix3_dll, _, low_dll, _, mix4_dll, _, _) in sides:
        native = ctypes.CDLL(str(caller))
        libraries = {"mix3": ctypes.CDLL(str(mix3_dll)), "low": ctypes.CDLL(str(low_dll)),
                     "mix4": ctypes.CDLL(str(mix4_dll))}
        for key, (_, _, _, entries) in TRANSLATIONS.items():
            for name in entries:
                if name in ADDRESSED:
                    continue
                source = ctypes.cast(getattr(native, name), ctypes.c_void_p).value
                lifted = ctypes.cast(getattr(libraries[key], f"lifted_{name}"), ctypes.c_void_p).value
                rows = []
                for x, y in inputs:
                    want, trace = reference(name, x, y, variant == "altered")
                    original, actual = observe(probe, source, x, y), observe(probe, lifted, x, y)
                    if original != (want, trace, SENTINELS):
                        raise AssertionError(f"{label} native {name}({x:#x}, {y:#x}): {original}")
                    if actual != (want, trace, SENTINELS):
                        raise AssertionError(f"{label} lifted_{name}({x:#x}, {y:#x}): {actual}")
                    rows.append(actual)
                results[label, name] = rows
                print(f"{label} {name}: {len(rows)} calls match the reference natively and translated on the "
                      "whole return value, guarded trace, RBX and RSI")
    for name in (name for _, _, _, entries in TRANSLATIONS.values() for name in entries if name not in ADDRESSED):
        changed = sum(a[0] != b[0] for a, b in zip(results["named", name], results["altered", name]))
        if not changed:
            raise AssertionError(f"altered provider: translated {name} returns never differ")
        print(f"altered provider: translated {name} returns differ on {changed} of {len(inputs)} calls")


def check_faults(guard_path, builds, optimized):
    """Guest reads before and after the import call, and a fault inside the import: each original call and its
    two translations (project build and /O2) give the same exception code, return value and trace."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
    kernel32.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_void_p]
    base = kernel32.VirtualAlloc(None, 2 * PAGE, 0x3000, 0x04)  # MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    old = ctypes.c_uint32()
    if not base or not kernel32.VirtualProtect(base + PAGE, PAGE, 0x01, ctypes.byref(old)):  # PAGE_NOACCESS
        raise ctypes.WinError(ctypes.get_last_error())
    ctypes.c_uint64.from_address(base).value = VALUE
    guarded = ctypes.CDLL(guard_path).guarded_call
    guarded.argtypes = [ctypes.c_void_p, Word, Word, ctypes.POINTER(Word), ctypes.POINTER(Word)]
    guarded.restype = ctypes.c_uint32
    native = ctypes.CDLL(str(builds["named"][0]))
    sides = [("original", lambda name: getattr(native, name))]
    for label, path in (("translation", builds["named"][1]), ("/O2 translation", optimized["mix3"])):
        library = ctypes.CDLL(str(path))
        sides.append((label, lambda name, library=library: getattr(library, "lifted_" + name)))

    def run(function, x, y, traced=True):
        """(exception code or 0, RAX or None, the three trace words) after a fresh trace."""
        trace = (Word * 5)(GUARDS[0], MASK, MASK, MASK, GUARDS[1])
        output = ctypes.cast(ctypes.byref(trace, ctypes.sizeof(Word)), ctypes.POINTER(Word)) if traced else None
        result = Word(0)
        code = guarded(ctypes.cast(function, ctypes.c_void_p), x, y, output, ctypes.byref(result))
        if tuple(trace)[0::4] != GUARDS:
            raise AssertionError("trace guards overwritten")
        return code, (None if code else result.value), tuple(trace)[1:4]

    untouched = (MASK, MASK, MASK)
    cases = []
    for y in (5, MASK - 6):
        value, words = mix3(VALUE, y, False)
        cases.append(("read_then_call", base, y, f"readable x, y = {y:#x}", (0, value, words)))
        value, words = mix3(base, y, False)
        cases.append(("call_then_read", base, y, f"readable x, y = {y:#x}", (0, (value + VALUE) & MASK, words)))
    for x, where in ((0, "null x"), (base + PAGE, "x in an inaccessible page")):
        cases.append(("read_then_call", x, 5, f"{where}: the read faults before the call",
                      (ACCESS_VIOLATION, None, untouched)))
        cases.append(("call_then_read", x, 5, f"{where}: the read faults after the call has written the trace",
                      (ACCESS_VIOLATION, None, mix3(x, 5, False)[1])))
    cases.append(("pass_result", 1, 2, "null trace: the import faults on its first store", None))
    for name, x, y, case, wanted in cases:
        traced = wanted is not None
        wanted = wanted or (ACCESS_VIOLATION, None, untouched)
        original = run(sides[0][1](name), x, y, traced)
        if original != wanted:
            raise AssertionError(f"original {name}, {case}: {original}, expected {wanted}")
        for label, function in sides[1:]:
            got = run(function(name), x, y, traced)
            if got != original:
                raise AssertionError(f"{label} {name}, {case}: {got}; original {original}")
        outcome = (f"raise {original[0]:#010x} with trace {tuple(hex(w) for w in original[2]) if traced else 'none'}"
                   if original[0] else f"return {original[1]:#x} with trace {tuple(hex(w) for w in original[2])}")
        print(f"{name}, {case}: the original and both translations {outcome}")


def check_rejections(builds, rvas, slots):
    """Bindings and equal-length patches of the named caller that the translator must reject."""
    named, provider = builds["named"][0], builds["named"][7]
    data = named.read_bytes()
    with pefile.PE(data=data, fast_load=True) as pe:
        at = pe.get_offset_from_rva
        body = {name: code(pe, rvas[name]) for name in ("call_keep", "call_twice", "clobber_read", "low_result",
                                                         "thunk_call", "thunk_tail", "outer_call",
                                                         "table_after_call", "call_guest_arg")}
        holder, = [s for s in pe.sections if s.VirtualAddress <= slots["mix3"] < s.VirtualAddress + s.Misc_VirtualSize]
        header, characteristics = holder.get_file_offset() + 36, holder.Characteristics
        holder_name = holder.Name.rstrip(b"\0").decode("ascii")

    def find(name, test, number=0):
        return [ins for ins in body[name] if test(ins)][number]

    def is_call(ins):
        return ins.flow_control in (FlowControl.CALL, FlowControl.INDIRECT_CALL)

    def rel32(target, end):
        return struct.pack("<i", target - end).hex()

    keep_call = find("call_keep", is_call)
    keep_add = find("call_keep", lambda i: i.mnemonic == Mnemonic.ADD and i.op0_register == Register.RCX)
    keep_spill = find("call_keep", lambda i: i.mnemonic == Mnemonic.MOV and i.memory_base == Register.RSP)
    keep_reload = find("call_keep", lambda i: i.mnemonic == Mnemonic.ADD and i.memory_base == Register.RSP)
    keep_sub = find("call_keep", lambda i: i.mnemonic == Mnemonic.SUB and i.op0_register == Register.RSP)
    keep_free = find("call_keep", lambda i: i.mnemonic == Mnemonic.ADD and i.op0_register == Register.RSP)
    second = find("call_twice", is_call, 1)
    rdx_write = find("call_twice", lambda i: i.mnemonic == Mnemonic.MOV and i.op0_register == Register.RDX)
    read = find("clobber_read", lambda i: i.mnemonic == Mnemonic.ADD and i.op0_register == Register.RAX)
    clobber_call = find("clobber_read", is_call)
    movzx = find("low_result", lambda i: i.mnemonic == Mnemonic.MOVZX)
    r9_write = find("thunk_call", lambda i: i.op0_register == Register.R9)
    thunk_call = find("thunk_call", is_call)
    inner_call = find("outer_call", is_call)
    guest_call = find("call_guest_arg", is_call)
    tail_jump = body["thunk_tail"][-1]
    table_load = find("table_after_call", lambda i: i.mnemonic == Mnemonic.MOV and i.memory_base == Register.R10)
    site, slot3, slot4, thunk = rvas["embed_site"], slots["mix3"], slots["mix4"], rvas["thunk"]
    # Each patch: (file offset, number of bytes replaced, their expected leading bytes, replacement of that length).
    patches = {
        **{f"read {register}": [(at(read.ip), read.len, "4803c3", code)] for register, code in (
            ("rcx", "4803c1"), ("rdx", "4803c2"), ("r8", "4903c0"), ("r9", "4903c1"), ("r10", "4903c2"),
            ("r11", "4903c3"))},
        "flags": [(at(read.ip), read.len, "4803c3", "0f94c0")],  # sete al
        "rdx": [(at(rdx_write.ip), rdx_write.len, "488bd3", "909090")],
        "r9": [(at(r9_write.ip), 6, "4c8bc94c33ca", "909090909090")],  # mov r9, rcx; xor r9, rdx
        "home": [(at(keep_spill.ip), keep_spill.len, "4889542428", "4889542418"),
                 (at(keep_reload.ip), keep_reload.len, "4803442428", "4803442418")],
        "align": [(at(keep_sub.ip), keep_sub.len, "4883ec30", "4883ec38"),
                  (at(keep_free.ip), keep_free.len, "4883c430", "4883c438")],
        "second": [(at(second.ip + 2), 4, None, rel32(slot4, second.next_ip))],
        "terminator": [(at(keep_call.ip + 2), 4, None, rel32(rvas["terminator"], keep_call.next_ip))],
        "unused": [(at(keep_call.ip), keep_call.len, "ff15", "b80100000090")],  # mov eax, 1; nop
        "thunk+1": [(at(thunk_call.ip), thunk_call.len, "e8", "e8" + rel32(thunk + 1, thunk_call.next_ip))],
        "inside": [(at(thunk_call.ip), thunk_call.len, "e8", "e8" + rel32(rvas["inner_jump"], thunk_call.next_ip))],
        "fake": [(at(site), 10, "48b8", "ff25" + rel32(rvas["terminator"], site + 6) + "90909090"),
                 (at(thunk_call.ip), thunk_call.len, "e8", "e8" + rel32(site, thunk_call.next_ip))],
        "bare": [(at(site), 10, "48b8", "ff15" + rel32(slot3, site + 6) + "90909090"),
                 (at(inner_call.ip), inner_call.len, "e8", "e8" + rel32(site, inner_call.next_ip))],
        "[rax]": [(at(keep_call.ip), keep_call.len, "ff15", "ff1090909090")],
        "rax": [(at(keep_call.ip), keep_call.len, "ff15", "ffd090909090")],
        "far": [(at(keep_call.ip), 2, "ff15", "ff1d")],
        # add rcx, 3 and the call, replaced with the prefixed call through the same slot and three NOPs.
        "67": [(at(keep_add.ip), keep_add.len + keep_call.len, "4883c103ff15",
                "67ff15" + rel32(slot3, keep_add.ip + 7) + "909090")],
        "fs": [(at(keep_add.ip), keep_add.len + keep_call.len, "4883c103ff15",
                "64ff15" + rel32(slot3, keep_add.ip + 7) + "909090")],
        "noread": [(header, 4, struct.pack("<I", characteristics).hex(),
                    struct.pack("<I", characteristics & ~SCN_READ).hex())],
    }
    dll = provider.name
    mix3_bound = binding(provider, "mix3")
    controls = [
        ("no binding", named, "call_keep", None,
         f"no binding for the call through IAT slot RVA {slot3:#x} at RVA {keep_call.ip:#x}"),
        ("no binding for a call of the import thunk", named, "thunk_call", None,
         f"no binding for the call of the thunk at RVA {thunk:#x} through IAT slot RVA {slot4:#x} "
         f"at RVA {thunk_call.ip:#x}"),
        ("no binding for a tail jump to the import thunk", named, "thunk_tail", None,
         f"no binding for the tail jump to the thunk at RVA {thunk:#x} through IAT slot RVA {slot4:#x} "
         f"at RVA {tail_jump.ip:#x}"),
        ("no binding for the call in an internal callee", named, "outer_call", None,
         f"callee at RVA {rvas['inner_call']:#x} refused: no binding for the call through IAT slot RVA {slot3:#x}"),
        ("the slot is another import (mix3 bound as mix4)", named, "call_keep", binding(provider, "mix4", 3),
         f"unbound import {dll}!mix3 at IAT slot RVA {slot3:#x}"),
        ("the thunk's slot is another import (mix4 bound as mix3)", named, "thunk_call", binding(provider, "mix3", 4),
         f"unbound import {dll}!mix4 at IAT slot RVA {slot4:#x}"),
        ("the second call patched to the slot of mix4", "second", "call_twice", mix3_bound,
         f"call or tail jump through a second IAT slot RVA {slot4:#x}"),
        ("the call patched to mov eax, 1: the binding is unused", "unused", "call_keep", mix3_bound,
         f"binding {dll}!mix3 supplied but no call or tail jump uses it"),
        ("the IAT's section " + holder_name + " without IMAGE_SCN_MEM_READ", "noread", "call_keep", mix3_bound,
         f"IAT slot RVA {slot3:#x} is not 8 bytes of one readable section"),
        *((f"{register.upper()} read after the call (add rax, {register})", f"read {register}", "clobber_read",
           mix3_bound, f"undefined register {register} at RVA {read.ip:#x}")
          for register in ("rcx", "rdx", "r8", "r9", "r10", "r11")),
        ("flags read after the call (sete al)", "flags", "clobber_read", mix3_bound,
         f"flags clobbered by the call at RVA {clobber_call.ip:#x} are read at RVA {read.ip:#x}"),
        ("full RAX read, 1 guaranteed byte", named, "clobber_read", binding(provider, "mix3", return_bytes=1),
         f"undefined register rax at RVA {read.ip:#x}"),
        ("AL read, 0 guaranteed bytes", named, "low_result", binding(provider, "mix3", return_bytes=0),
         f"undefined register rax at RVA {movzx.ip:#x}"),
        ("RDX not written again before the second call", "rdx", "call_twice", mix3_bound,
         f"callee argument rdx is undefined at RVA {second.ip:#x}"),
        ("R9 not written before a call of a four-argument import", "r9", "thunk_call", binding(provider, "mix4"),
         f"callee argument r9 is undefined at RVA {thunk_call.ip:#x}"),
        ("guest address in RCX", named, "call_guest_arg", mix3_bound,
         f"callee argument rcx is undefined at RVA {guest_call.ip:#x}"),
        ("value spilled into the import's home space and reloaded", "home", "call_keep", mix3_bound,
         f"undefined stack byte at entry RSP-0x20 at RVA {keep_reload.ip:#x}"),
        ("RSP misaligned at the call (sub rsp, 38h)", "align", "call_keep", mix3_bound,
         f"call without an aligned home space at entry RSP-0x40 at RVA {keep_call.ip:#x}"),
        ("call of the thunk patched to its second byte", "thunk+1", "thunk_call", binding(provider, "mix4"),
         f"call target {thunk + 1:#x} is not a function entry (no runtime-function entry or export"),
        ("call of the thunk patched to the FF 25 tail jump inside inner_tail's unwind interval", "inside",
         "thunk_call", binding(provider, "mix4"),
         f"call target {rvas['inner_jump']:#x} is not a function entry (an address inside the function at "
         f"{rvas['inner_tail']:#x})"),
        ("call of the thunk patched to FF 25 through the IAT terminator, not an import slot", "fake", "thunk_call",
         binding(provider, "mix4"), f"call target {site:#x} is not a function entry (no runtime-function entry"),
        ("range-bound callee without unwind data that calls the import", "bare", "outer_call", mix3_bound,
         f"callee at RVA {site:#x} refused: call in a function without unwind data at RVA {site:#x}",
         [("embed_site", site, site + 11)]),
        ("call through the IAT terminator, not an import slot", "terminator", "call_keep", mix3_bound,
         f"unsupported control flow at RVA {keep_call.ip:#x}"),
        ("call qword ptr [rax]", "[rax]", "call_keep", mix3_bound, f"unsupported control flow at RVA {keep_call.ip:#x}"),
        ("call rax", "rax", "call_keep", mix3_bound, f"unsupported control flow at RVA {keep_call.ip:#x}"),
        ("call far through the slot (FF 1D)", "far", "call_keep", mix3_bound,
         f"unsupported control flow at RVA {keep_call.ip:#x}"),
        ("67h-prefixed (EIP-relative) call through the slot", "67", "call_keep", mix3_bound,
         f"unsupported control flow at RVA {keep_add.ip:#x}"),
        ("FS-prefixed call through the slot", "fs", "call_keep", mix3_bound,
         f"unsupported control flow at RVA {keep_add.ip:#x}"),
        ("jump-table base loaded into R10 before the call and used after it", named, "table_after_call", mix3_bound,
         f"table base r10 is not a RIP-relative address at RVA {table_load.ip:#x}"),
    ]
    for name in ("clobber_read", "outer_call"):
        translate(named, [name], binding=mix3_bound)
    print("accepted clobber_read as built, and outer_call alone, whose only call of mix3 is in its callee, "
          "with mix3 and 8 guaranteed bytes")
    with TemporaryDirectory() as folder:
        for label, image, name, bound, reason, *ranges in controls:
            manifest = None
            if image in patches:
                damaged = bytearray(data)
                for offset, length, before, after in patches[image]:
                    after = bytes.fromhex(after)
                    if len(after) != length or before and data[offset:offset + len(before) // 2].hex() != before:
                        raise AssertionError(f"control {label}: patch at file offset {offset:#x} does not fit")
                    damaged[offset:offset + length] = after
                if ranges:
                    manifest = {"image_sha256": hashlib.sha256(damaged).hexdigest(),
                                "functions": [{"name": n, "start": start, "end": end} for n, start, end in ranges[0]]}
                image = Path(folder) / "control.dll"
                image.write_bytes(damaged)
            try:
                translate(image, [name], manifest, binding=bound)
            except ValueError as exc:
                if reason not in str(exc):
                    raise AssertionError(f"{name} ({label}): expected {reason!r}, got {exc}") from exc
                print(f"rejected {name} ({label}): {exc}")
            else:
                raise AssertionError(f"accepted control {name} ({label})")
    print(f"{len(controls)} rejection controls passed")


if __name__ == "__main__":
    probe_path, guard_path, *paths = sys.argv[1:]
    paths = [Path(path) for path in paths]
    # Per variant: caller, then DLL and source of the mix3, low and mix4 translations, then the provider; then the
    # /O2 builds of the named caller's mix3, low and mix4 translations.
    builds = {variant: paths[8 * n:8 * n + 8] for n, variant in enumerate(VARIANTS)}
    optimized = dict(zip(("mix3", "low", "mix4"), paths[16:19]))
    layouts = {}
    for variant, (caller, _, mix3_source, _, low_source, _, mix4_source, provider) in builds.items():
        layouts[variant] = layout(caller, provider)
        check_sources(variant, caller, {"mix3": mix3_source, "low": low_source, "mix4": mix4_source}, provider)
    check_return_widths(builds["named"][0], builds["named"][7])
    check_execution(probe_path, builds, optimized)
    check_faults(guard_path, builds, optimized)
    check_rejections(builds, *layouts["named"])
