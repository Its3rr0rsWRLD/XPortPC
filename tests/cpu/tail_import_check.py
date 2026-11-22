"""Differential checks and rejection controls for tail jumps through the import address table.

Three callers are built from tail_import.asm, each linked against one provider: named exports, the same
with a return value one higher, and ordinal-only exports. Each caller is translated twice, as listed in
CMakeLists.txt: tail_mix (three arguments) with a binding of mix3 that takes three, and tail_choose (three
arguments, writes R9 before its jump) and tail_pass4 (four arguments) with a binding of mix4 that takes
four. Both bindings state 8 guaranteed low RAX bytes."""

import ctypes
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory

import pefile
from iced_x86 import Decoder, FlowControl, Mnemonic, Register

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_switch_aot import Binding, parse_entry, translate
from cpu_leaf_aot import export_rva
from direct_check import GUARDS, MASK, SENTINELS, input_pairs, observe, register_probe
from fourth_arg_check import observe4, register_probe4

VARIANTS = ("named", "altered", "ordinal")
# The export lists of the two translations of each caller, and the import each list is bound to.
TRANSLATIONS = {"mix3": ("tail_mix",), "mix4": ("tail_choose", "tail_pass4:4")}
# The import each export jumps to, and the integer arguments a binding of it states.
JUMPS = {"tail_mix": ("mix3", 3), "tail_choose": ("mix4", 4), "tail_pass4": ("mix4", 4), "tail_guest_arg": ("mix3", 3)}
ORDINALS = {"mix3": 3, "mix4": 4}
# Return widths with 8 guaranteed bytes from the binding: the RET of tail_choose defines only AX.
WIDTHS = {"tail_mix": 8, "tail_choose": 2, "tail_pass4": 8}
# The opcode bytes of each tail jump: tail_pass4's carries a REX.W prefix.
OPCODES = {"tail_pass4": b"\x48\xff\x25"}
# Fourth arguments passed to tail_pass4, the only four-argument entry.
FOURTHS = (0, 1, 1 << 32, 1 << 63, 0x5555aaaa5555aaaa, MASK)


def merge(register, value, width):
    low = (1 << width * 8) - 1
    return (register & ~low | value & low) & MASK


def mix4(first, second, fourth):
    return ((first - second) * 3) ^ fourth, (first, second, fourth)


def reference(name, x, y, z, entry_rax, altered):
    """RAX and the guarded trace after name(x, y, trace[, z]), entered with RAX = entry_rax."""
    if name == "tail_mix":
        first, second = (x + 5) & MASK, (y + y) & MASK
        stored = (first - second + 11) & MASK
        rax, words = stored * 3 + (first >> 5), (first, second, stored)
    elif name == "tail_pass4":
        rax, words = mix4(x, (y - x) & MASK, z)
    elif x < y:
        rax, words = mix4(x, y, x ^ y)
    else:
        return merge(entry_rax, x + y, 2), (GUARDS[0], MASK, y, MASK, GUARDS[1])
    return (rax + altered) & MASK, (GUARDS[0], *words, GUARDS[1])


def binding(provider, variant, symbol, return_bytes=8):
    arguments = 3 if symbol == "mix3" else 4
    if variant == "ordinal":
        return Binding(provider, f"#{ORDINALS[symbol]}", symbol, arguments, return_bytes)
    return Binding(provider, symbol, None, arguments, return_bytes)


def tail_sites(caller, provider, variant):
    """Check that each export's tail jump is FF 25 disp32 (48 FF 25 for tail_pass4) addressing its import's slot.

    Returns the RVA of each jump, the RVA of each import's slot and the RVA of the IAT terminator."""
    with pefile.PE(str(caller), fast_load=True) as pe:
        pe.parse_data_directories(directories=[1])
        desc, = [d for d in pe.DIRECTORY_ENTRY_IMPORT if d.dll.decode("ascii").casefold() == provider.name.casefold()]
        lookup = desc.struct.OriginalFirstThunk or desc.struct.FirstThunk
        slots = {}
        for number, imp in enumerate(desc.imports):
            if variant == "ordinal":
                symbol = {v: k for k, v in ORDINALS.items()}[imp.ordinal]
                if imp.name is not None or pe.get_qword_at_rva(lookup + 8 * number) != (1 << 63) | imp.ordinal:
                    raise AssertionError(f"{caller.name}: {imp.name} is not imported by ordinal")
            else:
                symbol = imp.name.decode("ascii")
            slots[symbol] = desc.struct.FirstThunk + 8 * number
        terminator = desc.struct.FirstThunk + 8 * len(desc.imports)
        if sorted(slots) != ["mix3", "mix4"] or pe.get_qword_at_rva(terminator) != 0:
            raise AssertionError(f"{caller.name}: unexpected import table {slots}")
        sites = {}
        for name, (symbol, _) in JUMPS.items():
            entry = export_rva(pe, name)
            jump = next(i for i in Decoder(64, pe.get_data(entry, 0x40), ip=entry)
                        if i.flow_control == FlowControl.INDIRECT_BRANCH)
            raw, opcode = pe.get_data(jump.ip, jump.len), OPCODES.get(name, b"\xff\x25")
            target = jump.next_ip + struct.unpack_from("<i", raw, len(opcode))[0]
            if (raw[:len(opcode)] != opcode or jump.len != len(opcode) + 4 or jump.memory_base != Register.RIP
                    or target != slots[symbol]):
                raise AssertionError(f"{caller.name} {name}: {raw.hex()} ({jump}) does not address {symbol}")
            sites[name] = jump.ip
    print(f"{caller.name}: each export's tail jump is FF 25 disp32 (48 FF 25 in tail_pass4) to its own IAT slot "
          f"({'ordinal' if variant == 'ordinal' else 'named'} imports)")
    return sites, slots, terminator


def check_sources(variant, caller, built, provider):
    """The built sources are the translations of the listed entries; the declaration and each call carry the
    binding's number of arguments, and each signature the entry's own number."""
    for symbol, entries in TRANSLATIONS.items():
        bound = binding(provider, variant, symbol)
        source, functions = translate(caller, list(entries), import_binding=bound)
        if Path(built[symbol]).read_text(encoding="utf-8") != source:
            raise AssertionError(f"{built[symbol]} is not the translation of {','.join(entries)} bound to {symbol}")
        words = ", ".join(["word"] * bound.arguments)
        call = f"return {symbol}({', '.join(('rcx', 'rdx', 'r8', 'r9')[:bound.arguments])});"
        lines = [line.strip() for line in source.splitlines()]
        if lines.count(f'extern "C" __declspec(dllimport) word {symbol}({words});') != 1:
            raise AssertionError(f"{variant} {symbol}: declaration missing or repeated:\n{source}")
        for entry, function in zip(entries, functions):
            name, count = parse_entry(entry)
            body = source.split(f"word lifted_{name}(")[1].split("\n}")[0]
            parameters = ", ".join(("word rcx", "word rdx", "word r8", "word r9")[:count])
            r9 = "a parameter" if count == 4 else "a local" if "    word r9 = 0;" in body else "not used"
            if (len(function.arguments) != count or not body.startswith(parameters + ")") or call not in body
                    or function.return_width != WIDTHS[name] or r9 == ("not used" if bound.arguments == 4 else "a local")):
                raise AssertionError(f"{variant} {entry}: {len(function.arguments)} entry arguments, width "
                                     f"{function.return_width}, source:\n{source}")
            print(f"{variant} {entry}: {count} entry arguments, binding of {bound.symbol} with {bound.arguments}; "
                  f"{call} r9 is {r9}; return width {function.return_width}")


def check_return_widths(caller, provider):
    """A tail jump contributes the binding's number to the lower bound, as a RET contributes its own."""
    for name, stated, width in (("tail_choose", 8, 2), ("tail_choose", 1, 1), ("tail_choose", 0, 0),
                                ("tail_mix", 8, 8), ("tail_mix", 2, 2), ("tail_mix", 0, 0)):
        symbol = JUMPS[name][0]
        rets = "2 defined at every reachable RET" if name == "tail_choose" else "no RET is reachable"
        note = (f"{width} low byte(s) at every reachable normal return: {rets}, {stated} guaranteed after "
                f"every tail jump to {symbol} as the binding states")
        source, (function,) = translate(caller, [name], import_binding=binding(provider, "named", symbol, stated))
        comments = [line for line in source.splitlines() if line.startswith("// RAX: ")]
        if function.return_width != width or comments != ["// RAX: " + note]:
            raise AssertionError(f"{name} with {stated} stated bytes: width {function.return_width}, {comments}")
        print(f"inspected {name} with {stated} stated byte(s): return_width {width}, source says: {note}")


def check_execution(probe_path, builds):
    probe, probe4 = register_probe(probe_path), register_probe4(probe_path)
    sampled = observe4(probe4, ctypes.CDLL(probe_path).clobber_control, 1, 2, 3)[2]
    if sampled != (0, 0):
        raise AssertionError(f"probe4 missed the register clobber: {sampled}")
    print("control clobber_control through probe4: RBX and RSI sampled as 0 and 0")
    inputs = input_pairs()
    results = {}
    for variant, (caller, mix3, _, mix4_dll, _, _) in builds.items():
        native, lifted3, lifted4 = ctypes.CDLL(str(caller)), ctypes.CDLL(str(mix3)), ctypes.CDLL(str(mix4_dll))
        lifted = {"tail_mix": lifted3.lifted_tail_mix, "tail_choose": lifted4.lifted_tail_choose,
                  "tail_pass4": lifted4.lifted_tail_pass4}
        for name, width in WIDTHS.items():
            source = getattr(native, name)
            entry_rax = ctypes.cast(source, ctypes.c_void_p).value  # both probes call through RAX
            # The host passes as many arguments as the entry was translated with.
            fourths = FOURTHS if name == "tail_pass4" else (None,)
            rows, tails, varied = [], 0, 0
            for x, y in inputs:
                # A tail jump returns the import's RAX whole; the RET of tail_choose defines only AX.
                tail = name != "tail_choose" or x < y
                mask = MASK if tail else (1 << width * 8) - 1
                seen = set()
                for z in fourths:
                    want, trace = reference(name, x, y, z, entry_rax, variant == "altered")
                    if z is None:
                        original, actual = observe(probe, source, x, y), observe(probe, lifted[name], x, y)
                    else:
                        original, actual = observe4(probe4, source, x, y, z), observe4(probe4, lifted[name], x, y, z)
                    if original != (want, trace, SENTINELS):
                        raise AssertionError(f"{variant} native {name}({x:#x}, {y:#x}, {z}): {original}")
                    if (actual[0] & mask, *actual[1:]) != (want & mask, trace, SENTINELS):
                        raise AssertionError(f"{variant} lifted_{name}({x:#x}, {y:#x}, {z}): {actual}")
                    rows.append((actual[0] & mask, *actual[1:]))
                    seen.add(rows[-1])
                    tails += tail
                varied += len(seen) > 1
            results[variant, name] = rows
            if name == "tail_pass4" and varied != len(inputs):
                raise AssertionError(f"{variant} tail_pass4: the fourth argument changed only {varied} pairs")
            through = (f"probe4, the fourth argument changes the result on {varied} of {len(inputs)} pairs"
                       if name == "tail_pass4" else "probe")
            print(f"{variant} {name}: {len(rows)} calls ({tails} through the tail jump; {through}) match the "
                  "reference natively and translated on return, guarded trace, RBX and RSI")
    for name in WIDTHS:
        pairs = list(zip(results["named", name], results["altered", name]))
        changed = sum(a[0] != b[0] for a, b in pairs)
        if any(a[1:] != b[1:] for a, b in pairs) or not changed:
            raise AssertionError(f"altered provider: {name} differs in more than the return, or not at all")
        print(f"altered provider: translated {name} returns differ on {changed} of {len(pairs)} calls; "
              "guarded trace, RBX and RSI identical")


def check_rejections(builds, sites, slots, terminator):
    """Bindings and equal-length patches of the named caller that the translator must reject."""
    named, provider = builds["named"][0], builds["named"][5]
    ordinal, ordinal_provider = builds["ordinal"][0], builds["ordinal"][5]
    data = named.read_bytes()
    with pefile.PE(data=data, fast_load=True) as pe:
        offset = pe.get_offset_from_rva
        choose_rva, guest_rva = export_rva(pe, "tail_choose"), export_rva(pe, "tail_guest_arg")
        choose = list(Decoder(64, pe.get_data(choose_rva, 0x20), ip=choose_rva))
        lea = Decoder(64, pe.get_data(guest_rva, 0x10), ip=guest_rva).decode()
    branch = next(i for i in choose if i.mnemonic == Mnemonic.JAE)
    word = next(i for i in choose if i.mnemonic == Mnemonic.MOV and i.op0_register == Register.AX)
    add = choose[choose.index(word) + 1]
    r9 = next(i for i in choose if i.mnemonic == Mnemonic.MOV and i.op0_register == Register.R9)
    xor = choose[choose.index(r9) + 1]
    jump = sites["tail_mix"]
    rel32 = lambda target, end: struct.pack("<i", target - end)
    patches = {
        # (RVA, replacement, length of the instruction bytes it replaces)
        "terminator": (jump + 2, rel32(terminator, jump + 6), 4),
        "far": (jump + 1, bytes([0x2d]), 1),  # ModRM 25h -> 2Dh: jmp far through the slot
        "eip": (lea.ip, b"\x67\xff\x25" + rel32(slots["mix3"], lea.next_ip), lea.len),
        "fs": (lea.ip, b"\x64\xff\x25" + rel32(slots["mix3"], lea.next_ip), lea.len),
        "second": (word.ip, b"\xff\x25" + rel32(slots["mix3"], word.ip + 6), word.len + add.len),
        "partial": (r9.ip, b"\x41\x88\xc9\x90\x90\x90", r9.len + xor.len),  # mov r9b, cl; nop; nop; nop
        "jmp": (branch.ip, b"\xeb" + data[offset(branch.ip) + 1:offset(branch.ip) + 2], branch.len),
    }
    for key, (rva, patch, length) in patches.items():
        if len(patch) != length:
            raise AssertionError(f"patch {key} is {len(patch)} bytes for {length}")
    named_dll = provider.name
    mix3, mix4 = binding(provider, "named", "mix3"), binding(provider, "named", "mix4")
    controls = [
        ("no binding", named, "tail_mix", None, "no binding for the tail jump"),
        ("wrong symbol mix4", named, "tail_mix", Binding(provider, "mix4", None, 3, 8),
         f"unbound import {named_dll}!mix3"),
        ("wrong provider file", named, "tail_mix", Binding(builds["altered"][5], "mix3", None, 3, 8),
         f"unbound import {named_dll}!mix3"),
        ("named binding for an ordinal-only import", ordinal, "tail_mix",
         Binding(ordinal_provider, "mix3", None, 3, 8), f"unbound import {ordinal_provider.name}!#3"),
        ("disp32 patched to the IAT terminator", "terminator", "tail_mix", mix3,
         f"no unique ordinary import at IAT slot RVA {terminator:#x}"),
        ("FF 25 patched to FF 2D, jmp far through the slot", "far", "tail_mix", mix3, "unsupported control flow"),
        ("LEA patched to 67 FF 25, an EIP-relative tail jump", "eip", "tail_guest_arg", mix3,
         "unsupported control flow"),
        ("LEA patched to 64 FF 25, an FS-relative tail jump", "fs", "tail_guest_arg", mix3, "unsupported control flow"),
        ("guest address in RCX", named, "tail_guest_arg", mix3, "undefined register rcx"),
        ("three-argument entry, four-argument binding, R9 not written", named, "tail_pass4", mix4,
         "undefined register r9"),
        ("mov r9, rcx; xor r9, rdx patched to mov r9b, cl and NOPs: R9 partly written", "partial", "tail_choose",
         mix4, f"undefined register r9 at RVA {xor.next_ip:#x}"),
        ("AX writes patched to a tail jump through the slot of mix3", "second", "tail_choose", mix4,
         f"tail jump through a second IAT slot RVA {slots['mix3']:#x}"),
        ("JAE patched to JMP, no reachable tail jump", "jmp", "tail_choose", mix4,
         f"binding {named_dll}!mix4 supplied but no tail jump uses it"),
    ]
    with TemporaryDirectory() as folder:
        for label, image, name, bound, reason in controls:
            if image in patches:
                rva, patch, _ = patches[image]
                damaged = bytearray(data)
                damaged[offset(rva):offset(rva) + len(patch)] = patch
                image = Path(folder) / "control.dll"
                image.write_bytes(damaged)
            try:
                translate(image, [name], import_binding=bound)
            except ValueError as exc:
                if reason not in str(exc):
                    raise AssertionError(f"{name} ({label}): expected {reason!r}, got {exc}") from exc
                print(f"rejected {name} ({label}): {exc}")
            else:
                raise AssertionError(f"accepted control {name} ({label})")
    print(f"{len(controls)} rejection controls passed")


if __name__ == "__main__":
    probe_path, *paths = sys.argv[1:]
    paths = [Path(path) for path in paths]
    # Per variant: caller, mix3 translation (DLL, source), mix4 translation (DLL, source), provider.
    builds = {variant: paths[6 * n:6 * n + 6] for n, variant in enumerate(VARIANTS)}
    sites = {}
    for variant, (caller, _, mix3_source, _, mix4_source, provider) in builds.items():
        sites[variant] = tail_sites(caller, provider, variant)
        check_sources(variant, caller, {"mix3": mix3_source, "mix4": mix4_source}, provider)
    check_return_widths(builds["named"][0], builds["named"][5])
    check_execution(probe_path, builds)
    check_rejections(builds, *sites["named"])
