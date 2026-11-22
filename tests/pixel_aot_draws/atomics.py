"""Draw family `atomics`: pixel_aot_check.py draw --family atomics.

buffer_atomic_* and global_atomic_* from pixel shaders, on the harness and key scheme of the `stores` family
(tests/pixel_aot_draws/stores.py). Each pixel owns the 128-byte record at k * 128 of slot 1: dword j (0..12) is the
target of operation j of OPS, with glc, and dword 16 + j receives the returned pre-operation value through a plain
store after vmcnt(0). Owning its words makes swap, cmpswap, inc, dec and every returned value exact. Dwords 13 and 14 take
atomics without glc, and dword 14 of the buffer program goes through a V# with 4000 records, so keys 4000 and up change
nothing there and get 0 back (stored in dword 30). The words at SHARED (A0 + 0x80000) are shared by all 4096 pixels and
take only order-independent atomics without a returned value: add, sub, the four min/max, and, or and xor. The initial
memory is chosen per key so that cmpswap matches on even keys, inc meets its wrap on a third of the keys and dec its
zero and above-data cases. A "flaw" is a plausible wrong rule; each must change the expected memory and fail the draw."""
from pixel_aot_ops.forms.atomics import OPS

from .common import M32, must_reject
from .stores import A0, C1, C2, KEYS, R0, SHARED, Memory, data, program, refused_for, run_programs, separated, translate, vsharp

ORDER = sorted(OPS, key=OPS.get)  # operation j targets dword j
K = [(0x01000193 * (j + 1)) & M32 for j in range(len(ORDER))]  # operation j's data is d1 + K[j]
CMP_K = 0x0BADF00D  # cmpswap compares with d0 ^ CMP_K
VS_D = vsharp(A0, 128, KEYS, 1)
VS_E = vsharp(SHARED, 0, 0x100, 3)
VS_F = vsharp(A0, 128, 4000, 1)
# Words 3 to 6: C1, C2 and the global base A0; words 8 to 19: V# D (the records), E (the shared words), F (4000 records).
CONSTANTS = [0, 0, 0, C1, C2, A0 & M32, A0 >> 32, 0, *VS_D, *VS_E, *VS_F] + [0] * 44
SHARED_OPS = (("add", "v31"), ("sub", "v30"), ("umax", "v31"), ("umin", "v31"), ("smax", "v30"), ("smin", "v30"),
              ("or", "v34"), ("and", "v35"), ("xor", "v31"))


def operand(j):
    return f"v{50 + j}" if ORDER[j] != "cmpswap" else "v64"


def setup():
    lines = ["v_lshlrev_b32_e32 v24, 7, v22", "v_lshlrev_b32_e64 v34, v22, 1", "v_not_b32_e32 v35, v34",
             "v_mov_b32_e32 v25, 0x80000"]
    for j, op in enumerate(ORDER):
        lines.append(f"v_add_nc_u32_e32 {operand(j)}, 0x{K[j]:x}, v31")
    lines.append(f"v_xor_b32_e32 v65, 0x{CMP_K:x}, v30")
    return lines


def data_operand(j):
    return "v[64:65]" if ORDER[j] == "cmpswap" else operand(j)


BUFFER_BODY = [
    *setup(),
    *(f"buffer_atomic_{op} {data_operand(j)}, v22, s[52:55], 0 idxen offset:{4 * j} glc" for j, op in enumerate(ORDER)),
    "buffer_atomic_xor v31, v22, s[52:55], 0 idxen offset:52",
    "v_mov_b32_e32 v66, v32", "buffer_atomic_add v66, v22, s[60:63], 0 idxen offset:56 glc",
    *(f"buffer_atomic_{op} {reg}, off, s[56:59], 0 offset:{4 * n}" for n, (op, reg) in enumerate(SHARED_OPS)),
    "s_waitcnt vmcnt(0)",
    *(f"buffer_store_dword {operand(j)}, v22, s[52:55], 0 idxen offset:{64 + 4 * j}" for j in range(len(ORDER))),
    "buffer_store_dword v66, v22, s[52:55], 0 idxen offset:120",
]

GLOBAL_BODY = [
    *setup(),
    *(f"global_atomic_{op} {operand(j)}, v24, {data_operand(j)}, s[46:47] offset:{4 * j} glc" for j, op in enumerate(ORDER)),
    "global_atomic_xor v24, v31, s[46:47] offset:52",
    "v_add_nc_u32_e32 v40, s46, v24", "v_mov_b32_e32 v41, s47",
    "global_atomic_or v[40:41], v34, off offset:56",
    "global_atomic_umax v66, v[40:41], v32, off offset:60 glc",
    *(f"global_atomic_{op} v25, {reg}, s[46:47] offset:{4 * n}" for n, (op, reg) in enumerate(SHARED_OPS)),
    "s_waitcnt vmcnt(0)",
    *(f"global_store_dword v24, {operand(j)}, s[46:47] offset:{64 + 4 * j}" for j in range(len(ORDER))),
    "global_store_dword v24, v66, s[46:47] offset:120",
]


def signed(x):
    return x - (1 << 32) if x & 0x80000000 else x


def apply(op, old, value, cmp, flaws):
    """The new memory word of one atomic."""
    smaller = (lambda a, b: a < b) if "unsigned" in flaws else (lambda a, b: signed(a) < signed(b))
    if op == "swap":
        return value
    if op == "cmpswap":
        src, cmp = (cmp, value) if "cmp_swapped" in flaws else (value, cmp)
        return src if old == cmp else old
    if op == "add":
        return (old + value) & M32
    if op == "sub":
        return ((value - old) if "sub_rev" in flaws else (old - value)) & M32
    if op in ("smin", "umin"):
        less = smaller if op == "smin" else (lambda a, b: a < b)
        return old if less(old, value) else value
    if op in ("smax", "umax"):
        less = smaller if op == "smax" else (lambda a, b: a < b)
        return value if less(old, value) else old
    if op == "and":
        return old & value
    if op == "or":
        return old | value
    if op == "xor":
        return old ^ value
    if op == "inc":
        return 0 if (old > value if "inc_gt" in flaws else old >= value) else (old + 1) & M32
    if op == "dec":
        return value if ((old == 0 and "dec_nozero" not in flaws) or old > value) else (old - 1) & M32
    raise AssertionError(op)


def operands(k):
    d0, d1, d2, _ = data(k)
    values = [(d1 + K[j]) & M32 for j in range(len(ORDER))]
    return d0, d1, d2, values, d0 ^ CMP_K


def initial():
    """Slot 1 with the targets of every key set up so that each operation meets its interesting cases."""
    memory = Memory()
    for k in range(KEYS):
        _, _, _, values, cmp = operands(k)
        base = A0 + 128 * k
        for j, op in enumerate(ORDER):
            value = values[j]
            if op == "cmpswap" and k % 2 == 0:
                memory.store(base + 4 * j, cmp)
            elif op == "inc":
                memory.store(base + 4 * j, (value, (value - 1) & M32, value >> 3)[k % 3])
            elif op == "dec":
                memory.store(base + 4 * j, (0, (value + 1 + (k & 0xff)) & M32 if value < M32 - 0x100 else 0, value)[k % 3])
    return memory


def reference(kind):
    def model(flaws=()):
        memory = initial()
        for k in range(KEYS):
            d0, d1, d2, values, cmp = operands(k)
            bit = 1 << (k & 31)
            regs = {"v30": d0, "v31": d1, "v34": bit, "v35": ~bit & M32}
            base = A0 + 128 * k
            inst = (lambda n: 0) if "no_imm" in flaws else (lambda n: n)

            def atomic(op, address, value, compare=0):
                old = memory.load(address)
                if old is None:
                    return 0
                new = apply(op, old, value, compare, flaws)
                memory.store(address, new)
                return new if "post" in flaws else old

            returns = [atomic(op, base + inst(4 * j), values[j], cmp) for j, op in enumerate(ORDER)]
            atomic("xor", base + inst(52), d1)
            if kind == "buffer":
                in_range = k < 4000 or "nocheck" in flaws
                last = atomic("add", base + 56, d2) if in_range else (memory.load(base + 56) if "oob_value" in flaws else 0)
            else:
                atomic("or", base + inst(56), bit)
                last = atomic("umax", base + inst(60), d2)
            for n, (op, reg) in enumerate(SHARED_OPS):
                atomic(op, SHARED + inst(4 * n), regs[reg])
            for j, value in enumerate(returns):
                memory.store(base + 64 + 4 * j, value)
            memory.store(base + 120, last)
        return memory
    return model


PROGRAMS = (
    (BUFFER_BODY, reference("buffer"), ["post", "unsigned", "inc_gt", "dec_nozero", "cmp_swapped", "sub_rev", "nocheck",
                                        "oob_value"]),
    (GLOBAL_BODY, reference("global"), ["post", "unsigned", "inc_gt", "dec_nozero", "cmp_swapped", "sub_rev", "no_imm"]),
)
assert R0 not in (A0, SHARED)


def atomic_controls():
    for body, _, _ in PROGRAMS:
        assert "RWByteAddressBuffer title_memory" in translate(program(*body))
    separated(PROGRAMS)
    ready = setup()
    own = "buffer_atomic_add v50, v22, s[52:55], 0 idxen glc"
    translate(program(*ready, own, "s_waitcnt vmcnt(0)", "v_mov_b32_e32 v26, v50"))
    # The returned value is a load result: not readable before vmcnt(0).
    must_reject(translate, program(*ready, own, "v_mov_b32_e32 v26, v50"))
    must_reject(translate, program(*ready, own, "buffer_atomic_add v50, v22, s[52:55], 0 idxen glc"))
    narrowed = ["v_cmp_lt_f32_e64 s[80:81], v12, v13", "s_and_b64 exec, exec, s[80:81]"]
    refused_for("CF-2a", translate, program(*ready, *narrowed, own))
    refused_for("CF-2a", translate, program(*ready, *narrowed, "global_atomic_add v24, v31, s[46:47]"))
    # Floats and 64-bit words are refused everywhere; order-dependent operations and returned values on an address
    # every lane shares (no VGPR address), which the same operation on the lane's own word next to it is not.
    for op in ("fcmpswap", "fmin", "fmax"):
        reg = "v[64:65]" if op == "fcmpswap" else "v31"
        refused_for("not lowered", translate, program(*ready, f"buffer_atomic_{op} {reg}, v22, s[52:55], 0 idxen"))
        refused_for("not lowered", translate, program(*ready, f"global_atomic_{op} v24, {reg}, s[46:47]"))
    for op in ("add", "swap", "cmpswap", "umax"):
        reg = "v[64:65]" if op == "cmpswap" else "v[50:51]"
        refused_for("not lowered", translate, program(*ready, f"buffer_atomic_{op}_x2 {reg}, v22, s[52:55], 0 idxen"))
        refused_for("not lowered", translate, program(*ready, f"global_atomic_{op}_x2 v24, {reg}, s[46:47]"))
    for op in ("swap", "cmpswap", "inc", "dec"):
        reg = "v[64:65]" if op == "cmpswap" else "v50"
        translate(program(*ready, f"buffer_atomic_{op} {reg}, v22, s[52:55], 0 idxen"))
        refused_for("shares", translate, program(*ready, f"buffer_atomic_{op} {reg}, off, s[56:59], 0"))
    translate(program(*ready, "buffer_atomic_add v50, off, s[56:59], 0"))
    refused_for("shares", translate, program(*ready, "buffer_atomic_add v50, off, s[56:59], 0 glc"))
    for bad in ("buffer_atomic_cmpswap v64, v22, s[52:55], 0 idxen", "buffer_atomic_add v[50:51], v22, s[52:55], 0 idxen",
                "buffer_atomic_add v50, v22, s[52:55], 0 idxen tfe", "buffer_atomic_add v50, v22, s[52:55], 0 idxen lds",
                "buffer_atomic_add v50, v22, s[52:55], 0", "buffer_atomic_csub v50, v22, s[52:55], 0 idxen",
                "global_atomic_cmpswap v24, v64, s[46:47]", "global_atomic_add v24, v50, s[46:47] offset:2048",
                "global_atomic_add v24, v50, off", "global_atomic_add v24, v50, s[46:47] tfe",
                "global_atomic_add v[50:51], v24, v50, s[46:47] glc", "global_atomic_csub v50, v24, v50, s[46:47] glc",
                "flat_atomic_add v[40:41], v50"):
        must_reject(translate, program(*ready, bad))


def controls(directory):
    atomic_controls()


def binary_fixtures():
    return [(program(*body), translate) for body, _, _ in PROGRAMS]


def draw(directory, compiler, renderer, backend):
    run_programs(directory, compiler, renderer, backend, "atomics", PROGRAMS, CONSTANTS)
