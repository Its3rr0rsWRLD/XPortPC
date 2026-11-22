"""RIP-relative data translated against an explicitly bound mapping of the input image (--image-data).

The original exports run in one pe_map mapping of the fixture and the translated DLL is bound to a second
one; both start from the image's initial data. After every call the test compares the return value, the
guarded trace, RBX/RSI and the writable sections of the two mappings byte for byte. An address inside the
image is compared by its RVA (address - mapping base): the exports that return one and the slots that hold
one are known from the fixture, not guessed from values.
"""

import ctypes
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

import pefile
from iced_x86 import Decoder, OpKind, Register

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_switch_aot import extent, relocated, translate
from cpu_leaf_aot import export_rva
from direct_check import GUARDS, MASK, SENTINELS, observe, register_probe
from native_map_check import Mapper

EXPORTS = ("read_counter", "bump_counter", "counter_address", "load_counter_ptr", "is_counter", "set_vtable",
           "vtable_entry", "swap_scratch", "load_through", "switch_count", "switch_only")
# RIP-relative operands of each export (LEA included) and the exports whose translation needs no mapping.
RIP_OPERANDS = {"read_counter": 1, "bump_counter": 2, "counter_address": 1, "load_counter_ptr": 1,
                "is_counter": 1, "set_vtable": 1, "vtable_entry": 1, "swap_scratch": 2, "load_through": 0,
                "switch_count": 7, "switch_only": 1}
UNBOUND = {"load_through", "switch_only"}
# Exports whose RAX is an address inside the image, or the object passed in RCX.
RETURNS = {"counter_address": "rva", "load_counter_ptr": "rva", "vtable_entry": "rva", "set_vtable": "object"}
UNBOUND_CODE = 0xE0494D47  # the structured exception the generated source documents
BIND = {0: "accepted", 1: "null base", 2: "headers differ", 3: "read-only contents differ"}
WRITE = 0x80000000
# "&counter" and "&counter+8" stand for image addresses, "object" for an 8-byte buffer of each side.
STEPS = [("read_counter", 0, 0), ("bump_counter", 5, 0),
         ("read_counter", 0, 0),  # written through one RIP-relative operand, read through another
         ("counter_address", 0, 0),
         ("load_through", "&counter", 0),  # the address from a LEA, dereferenced by another export
         ("is_counter", "&counter", 0), ("is_counter", "&counter+8", 0), ("is_counter", 0, 0),
         ("load_counter_ptr", 0, 0), ("set_vtable", "object", 0), ("vtable_entry", 0, 0),
         ("swap_scratch", 0x1234, 0), ("swap_scratch", 7, 0),
         *(("switch_count", x, y) for x, y in ((0, 3), (1, 1), (2, 0x55), (3, 0xff), (4, 9), (0x180000000, 1),
                                               (0xdeadbeef00000000, 2))),
         ("swap_scratch", 0, 0),
         *(("switch_only", x, 0x123456789abcdef0) for x in (0, 1, 2, 3, 4, 1 << 32)),
         ("bump_counter", MASK, 0), ("read_counter", 0, 0)]


class Layout:
    """RVAs that the fixture's code addresses, read from its disassembly."""

    def __init__(self, path):
        _, functions = translate(path, EXPORTS, image_data=True)
        self.functions = dict(zip(EXPORTS, functions))
        target = lambda name: next(i.ip_rel_memory_address for i in self.code(name) if i.memory_base == Register.RIP)
        self.counter, self.counter_ptr = target("read_counter"), target("load_counter_ptr")
        self.vtable, self.scratch, self.only_table = target("set_vtable"), target("swap_scratch"), target("switch_only")
        with pefile.PE(str(path), fast_load=True) as pe:
            self.bump = export_rva(pe, "bump_counter")
            self.size = pe.OPTIONAL_HEADER.SizeOfImage
            self.sections = {s.Name.rstrip(b"\0").decode(): s for s in pe.sections}
            self.writable = [(s.VirtualAddress, extent(s)) for s in pe.sections if s.Characteristics & WRITE]
            # Slots that hold an address at load time; no export stores another address into image data.
            self.slots = [slot for slot in relocated(pe) if any(b <= slot < b + n for b, n in self.writable)]
            self.offset = pe.get_offset_from_rva

    def code(self, name):
        return [ins for _, ins in sorted(self.functions[name].instructions.items())]


def check_encodings(layout):
    """Every data reference of the fixture is RIP-relative, and the layout is the one the test relies on."""
    for name in EXPORTS:
        code = layout.code(name)
        rip = sum(i.memory_base == Register.RIP for i in code if OpKind.MEMORY in (i.op0_kind, i.op1_kind))
        absolute = [str(i) for i in code if OpKind.MEMORY in (i.op0_kind, i.op1_kind) and i.memory_base == Register.NONE]
        if rip != RIP_OPERANDS[name] or absolute:
            raise AssertionError(f"{name}: {rip} RIP-relative operands, absolute operands {absolute}")
        if layout.functions[name].image_data == (name in UNBOUND):
            raise AssertionError(f"{name}: translation needs the mapping: {layout.functions[name].image_data}")
    data, rdata = layout.sections[".data"], layout.sections[".rdata"]
    end = data.VirtualAddress + extent(data)
    if (not data.Characteristics & WRITE or rdata.Characteristics & WRITE or layout.scratch + 8 != end
            or layout.scratch < data.VirtualAddress + data.SizeOfRawData or layout.slots != [layout.counter_ptr]):
        raise AssertionError(f"unexpected layout: scratch {layout.scratch:#x}, .data ends {end:#x}, slots {layout.slots}")
    print(f"encodings: {sum(RIP_OPERANDS.values())} RIP-relative operands in {len(EXPORTS)} exports, no absolute "
          f"memory operand; {', '.join(sorted(UNBOUND))} translate without the mapping")
    print(f"layout: counter {layout.counter:#x} and counter_ptr {layout.counter_ptr:#x} (DIR64) in .data, scratch "
          f"{layout.scratch:#x} past its file-backed bytes at the end of its virtual extent, vtable {layout.vtable:#x} "
          "in read-only .rdata")


def run_control(name, change, image, reason, image_data=True):
    try:
        translate(image, [name], image_data=image_data)
    except ValueError as exc:
        if reason not in str(exc):
            raise AssertionError(f"{name} ({change}): expected {reason!r}, got {exc}") from exc
        print(f"rejected {name} ({change}): {exc}")
    else:
        raise AssertionError(f"accepted control {name} ({change})")


def check_rejections(path, layout):
    data = Path(path).read_bytes()
    end = layout.sections[".data"].VirtualAddress + extent(layout.sections[".data"])
    patches = [("read_counter", 0, layout.size + 0x10, "outside the image"),
               ("counter_address", 0, layout.size + 0x10, "outside the image"),
               ("read_counter", 0, 0x40, "outside every section"),
               ("read_counter", 0, end - 4, "crosses the end of section .data"),
               ("bump_counter", 1, layout.vtable + 16, "write to read-only section .rdata")]
    with TemporaryDirectory() as folder:
        copy = Path(folder) / "control.dll"
        for name, number, target, reason in patches:
            ins = [i for i in layout.code(name) if i.memory_base == Register.RIP][number]
            offsets = Decoder(64, data[layout.offset(ins.ip):layout.offset(ins.ip) + ins.len], ip=ins.ip)
            displacement = offsets.get_constant_offsets(offsets.decode()).displacement_offset
            damaged = bytearray(data)
            struct.pack_into("<i", damaged, layout.offset(ins.ip) + displacement, target - ins.next_ip)
            copy.write_bytes(damaged)
            run_control(name, f"{ins} -> target {target:#x}", copy, reason)
    for name, reason in (("read_counter", "unsupported register 70"),
                         ("counter_address", "return value may hold a guest address"),
                         ("is_counter", "undefined register rax"), ("set_vtable", "undefined register rax")):
        run_control(name, "without --image-data", path, reason, image_data=False)
    run_control("bind_image", "export name", path, "collides with the image binding functions")


class Lifted:
    def __init__(self, path):
        self.dll = ctypes.CDLL(str(path))
        self.bind = self.dll.lifted_bind_image
        self.bind.argtypes, self.bind.restype = [ctypes.c_uint64], ctypes.c_int
        self.unbind = self.dll.lifted_unbind_image

    def __getitem__(self, name):
        return getattr(self.dll, "lifted_" + name)


def reference(state, layout, name, x, y):
    """RAX (an RVA for addresses) and the first trace word after name(x, y) in the original; updates state."""
    counter, scratch, trace = state["counter"], state["scratch"], MASK
    rax = layout.counter if name in ("counter_address", "load_counter_ptr") else None
    if name == "read_counter":
        rax = counter
    elif name == "bump_counter":
        rax, state["counter"] = counter, (counter + x) & MASK
    elif name == "is_counter":
        rax = int(x == "&counter")
    elif name == "set_vtable":
        rax = "object"
    elif name == "vtable_entry":
        rax = layout.bump
    elif name == "swap_scratch":
        rax, state["scratch"] = scratch, x
    elif name == "load_through":
        rax = counter
    elif name == "switch_count":
        case = x & 0xffffffff
        if case == 0:
            state["counter"] = (counter + y) & MASK
        elif case == 1:
            state["counter"] = (counter - y) & MASK
        elif case == 2:
            state["scratch"] = y
        elif case == 3:
            state["counter"] = counter ^ y
        else:
            state["scratch"] = (scratch + 1) & MASK
        rax = trace = state["counter"]
    elif name == "switch_only":
        case, low = x & 0xffffffff, y & 0xffffffff
        rax = ((low + 1, 3 * low, ~low, ~low)[case] if case < 4 else low) & 0xffffffff
    return rax, (GUARDS[0], trace, MASK, MASK, GUARDS[1])


def data_view(layout, base):
    """The writable sections at base, with each slot that holds an image address replaced by its RVA."""
    view = bytearray()
    for rva, size in layout.writable:
        chunk = bytearray(ctypes.string_at(base + rva, size))
        for slot in layout.slots:
            if rva <= slot < rva + size:
                struct.pack_into("<Q", chunk, slot - rva, (struct.unpack_from("<Q", chunk, slot - rva)[0] - base) & MASK)
        view += chunk
    return bytes(view)


def check_lockstep(mapper, probe, lifted, layout, native, bound):
    """Each step on the original in mapping native and on the translation bound to mapping bound."""
    if data_view(layout, native) != data_view(layout, bound):
        raise AssertionError("the two mappings start from different writable data")
    state = {"counter": 0x1000, "scratch": 0}
    for number, (name, x, y) in enumerate(STEPS):
        want, trace = reference(state, layout, name, x, y)
        rows = []
        for label, base, fn in (("original", native, mapper.export(native, name.encode())),
                                ("translation", bound, lifted[name])):
            buffer = (ctypes.c_uint64 * 1)(MASK)
            arg = lambda v: (base + layout.counter + 8 * v.endswith("+8") if v.startswith("&")
                             else ctypes.addressof(buffer)) if isinstance(v, str) else v
            rax, words, registers = observe(probe, fn, arg(x), arg(y))
            kind = RETURNS.get(name, "value")
            if kind == "rva":
                rax = (rax - base) & MASK
            elif kind == "object" and rax == ctypes.addressof(buffer):
                rax = "object"
            stored = (buffer[0] - base) & MASK if name == "set_vtable" else None
            rows.append((rax, words, registers, stored, data_view(layout, base)))
            if (rax, words, registers) != (want, trace, SENTINELS) or (stored is not None and stored != layout.vtable):
                raise AssertionError(f"step {number} {label} {name}({x}, {y}): {rax} {words} {registers} {stored}")
        if rows[0] != rows[1]:
            raise AssertionError(f"step {number} {name}({x}, {y}): original {rows[0][:4]} != translation {rows[1][:4]}"
                                 " or the writable data differ")
        held = [ctypes.c_uint64.from_address(native + rva).value for rva in (layout.counter, layout.scratch)]
        if held != [state["counter"], state["scratch"]]:
            raise AssertionError(f"step {number} {name}: counter and scratch {held} differ from the reference")
    print(f"{len(STEPS)} steps: return values (addresses as RVAs), guarded traces, RBX/RSI and the writable data of "
          f"the two mappings ({sum(n for _, n in layout.writable)} bytes, counter_ptr as an RVA) match each other "
          "and the reference after every call")
    # The test writes through the address that each side returned, then each side reads it back.
    for base, fn in ((native, mapper.export(native, b"counter_address")), (bound, lifted["counter_address"])):
        ctypes.c_uint64.from_address(observe(probe, fn, 0, 0)[0]).value = 0xfeedface
    reads = [observe(probe, fn, 0, 0)[0] for fn in (mapper.export(native, b"read_counter"), lifted["read_counter"])]
    if reads != [0xfeedface] * 2 or data_view(layout, native) != data_view(layout, bound):
        raise AssertionError(f"write through the returned address: read_counter returned {reads}")
    print("the test wrote 0xfeedface through the counter address each side returned; read_counter on each side "
          "returned it and the writable data still match")


def check_shared(mapper, probe, lifted, base):
    """Original and translated code on one mapping write and read the same counter."""
    read, bump = (mapper.export(base, name) for name in (b"read_counter", b"bump_counter"))
    before = observe(probe, read, 0, 0)[0]
    observe(probe, bump, 0x10, 0)
    seen = observe(probe, lifted["read_counter"], 0, 0)[0]
    observe(probe, lifted["bump_counter"], 0x20, 0)
    after = observe(probe, read, 0, 0)[0]
    if (seen, after) != ((before + 0x10) & MASK, (before + 0x30) & MASK):
        raise AssertionError(f"shared mapping: {before:#x} {seen:#x} {after:#x}")
    print("one mapping: the translation read the original's write and the original read the translation's")


def check_binds(mapper, probe, probe_path, lifted, layout, path, bound):
    """Bind refusals and acceptances with the documented statuses; a refused bind keeps the current binding."""
    data = Path(path).read_bytes()
    with pefile.PE(data=data, fast_load=True) as pe:
        stamp = pe.FILE_HEADER.get_field_absolute_offset("TimeDateStamp")
    patches = [("TimeDateStamp in the file header", stamp, 2),
               ("constant in the read-only table", layout.offset(layout.vtable + 16), 3),
               ("jump-table entry in .text", layout.offset(layout.only_table + 12), 3),
               ("initial counter in writable .data", layout.offset(layout.counter), 0)]

    def attempt(label, base, want):
        got = lifted.bind(base)
        # The bound mapping, read back through a translated LEA.
        using = (observe(probe, lifted["counter_address"], 0, 0)[0] - layout.counter) & MASK
        if got != want or using != (base if want == 0 else bound):
            raise AssertionError(f"bind {label}: status {got}, expected {want}; translation uses {using:#x}")
        note = "writable data is not part of the identity" if want == 0 else "the binding is unchanged"
        print(f"bind {label}: status {got} ({BIND[got]}); {note}")

    if lifted.bind(bound) != 0:
        raise AssertionError("bind refused the fixture mapping")
    attempt("null base", 0, 1)
    attempt("another DLL (register probe, LoadLibrary)", ctypes.CDLL(str(probe_path))._handle, 2)
    with TemporaryDirectory() as folder:
        for label, offset, want in patches:
            copy = Path(folder) / f"altered{offset:x}.dll"
            damaged = bytearray(data)
            damaged[offset] ^= 0x01
            copy.write_bytes(damaged)
            base, status, detail, _ = mapper(copy, {})
            if status or not base:
                raise AssertionError(f"{label}: pe_map failed with {status}: {detail}")
            try:
                attempt(f"copy with one altered byte, {label}", base, want)
            finally:
                if lifted.bind(bound) != 0:
                    raise AssertionError("bind refused the fixture mapping again")
                mapper.release(base)


def check_rebind(mapper, probe, lifted, layout, path, first):
    lifted.unbind()
    module = ctypes.CDLL(str(path))
    if lifted.bind(module._handle) != 0:
        raise AssertionError("bind refused the system loader's mapping of the fixture")
    if observe(probe, lifted["read_counter"], 0, 0)[0] != observe(probe, module.read_counter, 0, 0)[0]:
        raise AssertionError("read_counter differs on the system loader's mapping")
    print("bind accepted the system loader's mapping (LoadLibrary); read_counter matches the original there")
    lifted.unbind()
    third, status, detail, _ = mapper(path, {})
    if status or not third:
        raise AssertionError(f"pe_map failed with {status}: {detail}")
    try:
        held = ctypes.c_uint64.from_address(first + layout.counter).value
        if lifted.bind(third) != 0:
            raise AssertionError("bind refused a third mapping")
        results = [observe(probe, lifted[name], x, 0)[0] for name, x in
                   (("read_counter", 0), ("counter_address", 0), ("bump_counter", 1))]
        counters = [ctypes.c_uint64.from_address(base + layout.counter).value for base in (third, first)]
        if results != [0x1000, third + layout.counter, 0x1000] or counters != [0x1001, held] or held == 0x1000:
            raise AssertionError(f"after rebind: {results} {counters} {held:#x}")
        print(f"after unbind and a bind to a third mapping: read_counter returned its initial 0x1000 (the first holds "
              f"{held:#x}), counter_address its base + {layout.counter:#x}, and bump_counter changed only it")
    finally:
        lifted.unbind()
        mapper.release(third)


def child(mapper_path, lifted_path, original):
    """Calls while nothing is bound; reports each outcome on one line."""
    lifted = Lifted(lifted_path)
    mapper = Mapper(mapper_path)

    def outcome(name, *args):
        fn = lifted[name]
        fn.argtypes, fn.restype = [ctypes.c_uint64] * 3, ctypes.c_uint64
        try:
            return f"{fn(*args):#x}"
        except OSError as error:
            return f"exception {(error.winerror or 0) & 0xffffffff:#x}"

    word = (ctypes.c_uint64 * 1)(0x5a5a)
    print(f"before bind: read_counter {outcome('read_counter', 0, 0, 0)}")
    print(f"before bind: set_vtable {outcome('set_vtable', ctypes.addressof(word), 0, 0)}, object {word[0]:#x}")
    print(f"before bind: switch_only {outcome('switch_only', 1, 5, 0)}, load_through "
          f"{outcome('load_through', ctypes.addressof(word), 0, 0)}")
    base, status, detail, _ = mapper(original, {})
    print(f"bind {lifted.bind(base)}: read_counter {outcome('read_counter', 0, 0, 0)}")
    lifted.unbind()
    print(f"after unbind: read_counter {outcome('read_counter', 0, 0, 0)}")
    mapper.release(base)


def check_unbound(mapper_path, lifted_path, original):
    run = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--child", str(mapper_path),
                          str(lifted_path), str(original)], capture_output=True, text=True, timeout=60)
    raised = f"exception {UNBOUND_CODE:#x}"
    expected = [f"before bind: read_counter {raised}", f"before bind: set_vtable {raised}, object 0x5a5a",
                "before bind: switch_only 0xf, load_through 0x5a5a", "bind 0: read_counter 0x1000",
                f"after unbind: read_counter {raised}"]
    if run.returncode or run.stdout.splitlines() != expected:
        raise AssertionError(f"unbound child exited {run.returncode:#x}:\n{run.stdout}{run.stderr}")
    for line in expected:
        print(f"child process: {line}")


def main(mapper_path, probe_path, original, lifted_path):
    layout = Layout(original)
    check_encodings(layout)
    check_rejections(original, layout)
    mapper, probe, lifted = Mapper(mapper_path), register_probe(probe_path), Lifted(lifted_path)
    native, *_ = mapper(original, {})
    bound, *_ = mapper(original, {})
    if not native or not bound:
        raise AssertionError("pe_map could not map the fixture twice")
    try:
        check_binds(mapper, probe, probe_path, lifted, layout, original, bound)
        check_lockstep(mapper, probe, lifted, layout, native, bound)
        check_shared(mapper, probe, lifted, bound)
        check_rebind(mapper, probe, lifted, layout, original, bound)
    finally:
        lifted.unbind()
        mapper.release(native)
        mapper.release(bound)
    check_unbound(mapper_path, lifted_path, original)


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        child(*sys.argv[2:])
    else:
        main(*sys.argv[1:])
