"""Differential checks, fault-suppression checks, mutation controls and rejection controls for AVX2 AOT."""

import ctypes
from pathlib import Path
import random
import struct
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pefile
from iced_x86 import Code, Encoder, Instruction, MemoryOperand, Register as R

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_avx2_aot import lift_code, translate, vsib_address
from cpu_leaf_aot import export_rva

MASK32 = 0xffffffff
MASK64 = 0xffffffffffffffff
GUARD_PRE = bytes(range(0xA0, 0xB0))
GUARD_POST = bytes(range(0xC0, 0xD0))
FILL = b"\x5A" * 32

EXPORTS = (
    "op_broadcasti128",
    "op_extracti128_lo",
    "op_extracti128_hi",
    "op_inserti128_lo",
    "op_inserti128_hi",
    "op_perm2i128_mix",
    "op_perm2i128_swap",
    "op_perm2i128_zero_lo",
    "op_perm2i128_zero_hi",
    "op_perm2i128_zero_both",
    "op_perm2i128_ignored",
    "op_pbroadcastb_xmm",
    "op_pbroadcastb_ymm",
    "op_pbroadcastw_xmm",
    "op_pbroadcastw_ymm",
    "op_pbroadcastd_xmm",
    "op_pbroadcastd_ymm",
    "op_pbroadcastq_xmm",
    "op_pbroadcastq_ymm",
    "op_permd",
    "op_permps",
    "op_permq",
    "op_permq_dup",
    "op_permpd",
    "op_pblendd_xmm",
    "op_pblendd_ymm",
    "op_pblendd_ymm_all",
    "op_pblendd_ymm_none",
    "op_psllvd_xmm",
    "op_psllvd_ymm",
    "op_psllvq_xmm",
    "op_psllvq_ymm",
    "op_psravd_xmm",
    "op_psravd_ymm",
    "op_psrlvd_xmm",
    "op_psrlvd_ymm",
    "op_psrlvq_xmm",
    "op_psrlvq_ymm",
    "op_zeroupper",
    "op_pipeline",
    "op_movdqu_store128",
    "op_movdqu_copy128",
)


# --- Independent Python ISA reference model ---

def u32s(buf):
    return struct.unpack("<8I", buf)


def pack_u32s(vals):
    return struct.pack("<8I", *(v & MASK32 for v in vals))


def u64s(buf):
    return struct.unpack("<4Q", buf)


def pack_u64s(vals):
    return struct.pack("<4Q", *(v & MASK64 for v in vals))


def ref_vbroadcasti128(a):
    return a[:16] + a[:16]


def ref_vextracti128(a, imm8):
    lane = a[16:32] if (imm8 & 1) else a[:16]
    return lane + b"\x00" * 16


def ref_vinserti128(a, b, imm8):
    if imm8 & 1:
        return a[:16] + b[:16]
    return b[:16] + a[16:32]


def ref_vperm2i128(a, b, imm8):
    lanes = (a[:16], a[16:32], b[:16], b[16:32])
    def pick(nibble):
        return b"\x00" * 16 if (nibble & 8) else lanes[nibble & 3]
    return pick(imm8 & 0xf) + pick((imm8 >> 4) & 0xf)


def ref_vpbroadcast(a, width, wide):
    elem = a[:width]
    if wide:
        return elem * (32 // width)
    return elem * (16 // width) + b"\x00" * 16


def ref_vpermd(idx_buf, src_buf):
    idx = u32s(idx_buf)
    src = u32s(src_buf)
    return pack_u32s(src[i & 7] for i in idx)


def ref_vpermq(src_buf, imm8):
    q = u64s(src_buf)
    return pack_u64s(q[(imm8 >> (2 * i)) & 3] for i in range(4))


def ref_vpblendd(a, b, imm8, wide):
    da, db = u32s(a), u32s(b)
    lanes = 8 if wide else 4
    out = [db[i] if ((imm8 >> i) & 1) else da[i] for i in range(lanes)]
    if not wide:
        out.extend([0] * 4)
    return pack_u32s(out)


def ref_vpsllvd(a, b, wide):
    da, dc = u32s(a), u32s(b)
    lanes = 8 if wide else 4
    out = [0 if dc[i] >= 32 else ((da[i] << dc[i]) & MASK32) for i in range(lanes)]
    if not wide:
        out.extend([0] * 4)
    return pack_u32s(out)


def ref_vpsrlvd(a, b, wide):
    da, dc = u32s(a), u32s(b)
    lanes = 8 if wide else 4
    out = [0 if dc[i] >= 32 else (da[i] >> dc[i]) for i in range(lanes)]
    if not wide:
        out.extend([0] * 4)
    return pack_u32s(out)


def ref_vpsravd(a, b, wide):
    da, dc = u32s(a), u32s(b)
    lanes = 8 if wide else 4
    out = []
    for i in range(lanes):
        v = da[i]
        s = v - (1 << 32) if (v & 0x80000000) else v
        c = dc[i]
        out.append((-1 if s < 0 else 0) & MASK32 if c >= 32 else ((s >> c) & MASK32))
    if not wide:
        out.extend([0] * 4)
    return pack_u32s(out)


def ref_vpsllvq(a, b, wide):
    qa, qc = u64s(a), u64s(b)
    lanes = 4 if wide else 2
    out = [0 if qc[i] >= 64 else ((qa[i] << qc[i]) & MASK64) for i in range(lanes)]
    if not wide:
        out.extend([0] * 2)
    return pack_u64s(out)


def ref_vpsrlvq(a, b, wide):
    qa, qc = u64s(a), u64s(b)
    lanes = 4 if wide else 2
    out = [0 if qc[i] >= 64 else (qa[i] >> qc[i]) for i in range(lanes)]
    if not wide:
        out.extend([0] * 2)
    return pack_u64s(out)


def ref_pipeline(a, b):
    ymm0 = ref_vbroadcasti128(a)
    ymm1 = b
    ymm2 = ref_vpbroadcast(ymm1, 4, True)
    ymm3 = ref_vperm2i128(ymm0, ymm1, 0x21)
    ymm4 = ref_vpermd(ymm1, ymm3)
    ymm5 = ref_vpblendd(ymm4, ymm2, 0x5A, True)
    ymm5 = ref_vpsravd(ymm5, ymm1, True)
    ymm3 = ref_vextracti128(ymm5, 1)
    ymm5 = ref_vinserti128(ymm5, ymm3, 0)
    ymm5 = ref_vpermq(ymm5, 0xD8)
    return ymm5


def reference(name, a, b, altered=False):
    if name == "op_broadcasti128":
        return ref_vbroadcasti128(a)
    if name == "op_extracti128_lo":
        return ref_vextracti128(a, 0xFE)
    if name == "op_extracti128_hi":
        return ref_vextracti128(a, 0xFF)
    if name == "op_inserti128_lo":
        return ref_vinserti128(a, b, 0xFE)
    if name == "op_inserti128_hi":
        return ref_vinserti128(a, b, 0xFF)
    if name == "op_perm2i128_mix":
        return ref_vperm2i128(a, b, 0x31 if altered else 0x20)
    if name == "op_perm2i128_swap":
        return ref_vperm2i128(a, b, 0x03)
    if name == "op_perm2i128_zero_lo":
        return ref_vperm2i128(a, b, 0x28)
    if name == "op_perm2i128_zero_hi":
        return ref_vperm2i128(a, b, 0x81)
    if name == "op_perm2i128_zero_both":
        return ref_vperm2i128(a, b, 0x88)
    if name == "op_perm2i128_ignored":
        return ref_vperm2i128(a, b, 0x45)
    if name == "op_pbroadcastb_xmm":
        return ref_vpbroadcast(a, 1, False)
    if name == "op_pbroadcastb_ymm":
        return ref_vpbroadcast(a, 1, True)
    if name == "op_pbroadcastw_xmm":
        return ref_vpbroadcast(a, 2, False)
    if name == "op_pbroadcastw_ymm":
        return ref_vpbroadcast(a, 2, True)
    if name == "op_pbroadcastd_xmm":
        return ref_vpbroadcast(a, 4, False)
    if name == "op_pbroadcastd_ymm":
        return ref_vpbroadcast(a, 4, True)
    if name == "op_pbroadcastq_xmm":
        return ref_vpbroadcast(a, 8, False)
    if name == "op_pbroadcastq_ymm":
        return ref_vpbroadcast(a, 8, True)
    if name in ("op_permd", "op_permps"):
        return ref_vpermd(a, b)
    if name == "op_permq":
        return ref_vpermq(a, 0x4E if altered else 0x1B)
    if name == "op_permq_dup":
        return ref_vpermq(a, 0xB1)
    if name == "op_permpd":
        return ref_vpermq(a, 0x93)
    if name == "op_pblendd_xmm":
        return ref_vpblendd(a, b, 0xFA, False)
    if name == "op_pblendd_ymm":
        return ref_vpblendd(a, b, 0x55 if altered else 0xAA, True)
    if name == "op_pblendd_ymm_all":
        return ref_vpblendd(a, b, 0xFF, True)
    if name == "op_pblendd_ymm_none":
        return ref_vpblendd(a, b, 0x00, True)
    if name == "op_psllvd_xmm":
        return ref_vpsllvd(a, b, False)
    if name == "op_psllvd_ymm":
        return ref_vpsllvd(a, b, True)
    if name == "op_psllvq_xmm":
        return ref_vpsllvq(a, b, False)
    if name == "op_psllvq_ymm":
        return ref_vpsllvq(a, b, True)
    if name == "op_psravd_xmm":
        return ref_vpsravd(a, b, False)
    if name == "op_psravd_ymm":
        return ref_vpsravd(a, b, True)
    if name == "op_psrlvd_xmm":
        return ref_vpsrlvd(a, b, False)
    if name == "op_psrlvd_ymm":
        return ref_vpsrlvd(a, b, True)
    if name == "op_psrlvq_xmm":
        return ref_vpsrlvq(a, b, False)
    if name == "op_psrlvq_ymm":
        return ref_vpsrlvq(a, b, True)
    if name == "op_zeroupper":
        return a[:16] + b"\x00" * 16
    if name == "op_pipeline":
        return ref_pipeline(a, b)
    if name == "op_movdqu_store128":
        return a[:16] + FILL[16:]
    if name == "op_movdqu_copy128":
        return a[:16] + b"\x00" * 16
    raise ValueError(f"unknown export {name}")


# --- Input vectors ---

def general_pairs():
    rng = random.Random(2026)
    distinct_a = bytes(range(0x01, 0x21))
    distinct_b = bytes(range(0x81, 0xA1))
    # IEEE-754 float32 special bit patterns: +0, -0, subnormal, +1, -1, +inf, sNaN, qNaN.
    float32_specials = pack_u32s((
        0x00000000, 0x80000000, 0x00000001, 0x3F800000,
        0xBF800000, 0x7F800000, 0x7F800001, 0x7FC00001,
    ))
    # IEEE-754 float64 special bit patterns: -0.0, sNaN, qNaN, subnormal.
    float64_specials = pack_u64s((
        0x8000000000000000, 0x7FF0000000000001, 0x7FF8000000000001, 0x0000000000000001,
    ))
    pairs = [
        (distinct_a, distinct_b),
        (b"\x00" * 32, b"\xFF" * 32),
        (b"\xFF" * 32, b"\x00" * 32),
        (float32_specials, distinct_b),
        (float64_specials, distinct_a),
        (pack_u32s((0x7FFFFFFF, 0x80000000, 0x80000001, 0xFFFFFFFF, 0, 1, 0x12345678, 0xFEDCBA98)),
         pack_u32s((0, 7, 3, 4, 0xFFFFFFF8, 0x80000007, 0x00000005, 0xDEAD0002))),
    ]
    for _ in range(10):
        pairs.append((rng.randbytes(32), rng.randbytes(32)))
    return pairs


def perm32_pairs():
    """Index/data pairs for vpermd/vpermps covering boundary indices 0..7 and high-bit noise."""
    data_tagged = pack_u32s(0x11000000 + i * 0x1111111 for i in range(8))
    data_fp = pack_u32s((
        0x00000000, 0x80000000, 0x00000001, 0x7F7FFFFF,
        0xFF7FFFFF, 0x7F800000, 0x7F800001, 0x7FC00001,
    ))
    index_vecs = [
        pack_u32s((0, 1, 2, 3, 4, 5, 6, 7)),
        pack_u32s((7, 6, 5, 4, 3, 2, 1, 0)),
        pack_u32s((0, 0, 7, 7, 3, 4, 4, 3)),
        pack_u32s((0xFFFFFFF8 | i for i in (7, 0, 5, 2, 6, 1, 4, 3))),
        pack_u32s((0x80000000, 0x80000007, 0x12345678, 0x1234567F, 8, 15, 16, 31)),
    ]
    return [(idx, data) for idx in index_vecs for data in (data_tagged, data_fp)]


def shift32_pairs():
    """Values and boundary shift counts (0, 1, 15, 31, 32, 33, 63, 64, >64, max) for 32-bit shifts."""
    values = [
        pack_u32s((0x80000001, 0x7FFFFFFF, 0xFFFFFFFF, 0x00000001,
                   0x80000000, 0x00000000, 0xA5A55A5A, 0x12345678)),
        pack_u32s((0xFFFFFFFE, 0x7FFFFFFE, 0x8000FFFF, 0x00010000,
                   0xF000000F, 0x0F0000F0, 0x55555555, 0xAAAAAAAA)),
    ]
    counts = [
        pack_u32s((0, 1, 15, 31, 32, 33, 63, 64)),
        pack_u32s((65, 128, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 31, 32, 0)),
        pack_u32s((32, 32, 32, 32, 31, 31, 31, 31)),
        pack_u32s((0, 0, 1, 1, 64, 64, 0x10000001, 0xFFFFFFE0)),
    ]
    return [(v, c) for v in values for c in counts]


def shift64_pairs():
    """Values and boundary shift counts (0, 1, 31, 32, 63, 64, 65, >64, max) for 64-bit shifts."""
    values = [
        pack_u64s((0x8000000000000001, 0x7FFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF, 0x0123456789ABCDEF)),
        pack_u64s((0x0000000000000001, 0x8000000000000000, 0xF0F0F0F00F0F0F0F, 0x0000000000000000)),
    ]
    counts = [
        pack_u64s((0, 1, 31, 32)),
        pack_u64s((63, 64, 65, 128)),
        pack_u64s((0x100000001, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000, 0xFFFFFFFFFFFFFFFF)),
        pack_u64s((64, 63, 0, 0x4000000000000000)),
    ]
    return [(v, c) for v in values for c in counts]


def inputs_for(name):
    if name in ("op_permd", "op_permps"):
        return perm32_pairs() + general_pairs()
    if name in ("op_psllvd_xmm", "op_psllvd_ymm", "op_psravd_xmm", "op_psravd_ymm",
                "op_psrlvd_xmm", "op_psrlvd_ymm"):
        return shift32_pairs() + general_pairs()
    if name in ("op_psllvq_xmm", "op_psllvq_ymm", "op_psrlvq_xmm", "op_psrlvq_ymm"):
        return shift64_pairs() + general_pairs()
    return general_pairs()


# --- Execution & comparison ---

def invoke(fn, a, b):
    buf_a = ctypes.create_string_buffer(a, 32)
    buf_b = ctypes.create_string_buffer(b, 32)
    guarded = ctypes.create_string_buffer(GUARD_PRE + FILL + GUARD_POST, 64)
    out_ptr = ctypes.addressof(guarded) + len(GUARD_PRE)
    fn(ctypes.addressof(buf_a), ctypes.addressof(buf_b), out_ptr)
    raw = guarded.raw
    if raw[:16] != GUARD_PRE or raw[48:] != GUARD_POST:
        raise AssertionError("guard bytes corrupted around output buffer")
    return raw[16:48]


def assert_equal_output(label, name, idx, got, want):
    if got != want:
        raise AssertionError(
            f"{label} {name} case {idx}: got {got.hex()} != expected {want.hex()}")


def bind_exports(dll_path, prefix="", names=None):
    lib = ctypes.CDLL(str(Path(dll_path).resolve()))
    funcs = {}
    for name in (EXPORTS if names is None else names):
        fn = getattr(lib, prefix + name)
        fn.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn.restype = None
        funcs[name] = fn
    return funcs


# --- Memory-domain AVX2 (gathers & vpmaskmov) exports, reference & harness ---

# (export_name, elem_bits, idx_bits, count, scale, disp, alt_disp)
GATHER_SPECS = (
    ("op_gatherdps_xmm", 32, 32, 4, 4, 0, None),
    ("op_gatherdps_ymm", 32, 32, 8, 4, 0, 16),
    ("op_gatherdps_ymm_scale1_disp", 32, 32, 8, 1, -16, None),
    ("op_gatherdpd_xmm", 64, 32, 2, 8, 0, None),
    ("op_gatherdpd_ymm", 64, 32, 4, 8, 16, None),
    ("op_gatherqps_xmm_vm64x", 32, 64, 2, 4, 0, None),
    ("op_gatherqps_xmm_vm64y", 32, 64, 4, 4, 0, None),
    ("op_gatherqpd_xmm", 64, 64, 2, 8, 0, None),
    ("op_gatherqpd_ymm", 64, 64, 4, 8, -24, None),
    ("op_pgatherdd_xmm", 32, 32, 4, 2, 8, None),
    ("op_pgatherdd_ymm", 32, 32, 8, 4, 0, None),
    ("op_pgatherdq_xmm", 64, 32, 2, 1, 0, None),
    ("op_pgatherdq_ymm", 64, 32, 4, 8, 0, None),
    ("op_pgatherqd_xmm_vm64x", 32, 64, 2, 1, -8, None),
    ("op_pgatherqd_xmm_vm64y", 32, 64, 4, 4, 12, None),
    ("op_pgatherqq_xmm", 64, 64, 2, 8, 0, None),
    ("op_pgatherqq_ymm", 64, 64, 4, 8, 0, None),
    ("op_pgatherdd_ymm_rdx", 32, 32, 8, 4, 8, None),
)

RDX_BASE_GATHERS = {"op_pgatherdd_ymm_rdx"}

# (export_name, elem_bits, wide, alt_disp)
MASKMOV_LOAD_SPECS = (
    ("op_pmaskmovd_load_xmm", 32, False, None),
    ("op_pmaskmovd_load_ymm", 32, True, 16),
    ("op_pmaskmovq_load_xmm", 64, False, None),
    ("op_pmaskmovq_load_ymm", 64, True, None),
)

# (export_name, elem_bits, wide)
MASKMOV_STORE_SPECS = (
    ("op_pmaskmovd_store_xmm", 32, False),
    ("op_pmaskmovd_store_ymm", 32, True),
    ("op_pmaskmovq_store_xmm", 64, False),
    ("op_pmaskmovq_store_ymm", 64, True),
)

MEMORY_EXPORTS = (
    tuple(s[0] for s in GATHER_SPECS)
    + tuple(s[0] for s in MASKMOV_LOAD_SPECS)
    + tuple(s[0] for s in MASKMOV_STORE_SPECS)
)

DATA_BUF_SIZE = 512
DATA_BASE_OFFSET = 256
DATA_GUARD_PRE = bytes(0x30 + (i % 64) for i in range(64))
DATA_GUARD_POST = bytes(0x70 + (i % 64) for i in range(64))
OUT_FILL_64 = b"\x5A" * 64
STORE_INIT = bytes(0xD0 + i for i in range(32))


def build_known_data_buffer():
    """512-byte deterministic buffer containing distinct values and IEEE-754 special bit patterns."""
    rng = random.Random(0xA7C2)
    buf = bytearray(rng.randbytes(DATA_BUF_SIZE))
    # Embed IEEE-754 float32 specials at base+0..base+31 and float64 specials at base+32..base+63.
    f32_specials = pack_u32s((
        0x00000000, 0x80000000, 0x00000001, 0x3F800000,
        0xBF800000, 0x7F800000, 0x7F800001, 0x7FC00001,
    ))
    f64_specials = pack_u64s((
        0x8000000000000000, 0x7FF0000000000001, 0x7FF8000000000001, 0x0000000000000001,
    ))
    buf[DATA_BASE_OFFSET:DATA_BASE_OFFSET + 32] = f32_specials
    buf[DATA_BASE_OFFSET + 32:DATA_BASE_OFFSET + 64] = f64_specials
    # Distinct boundary sentinels at the very start and end of the buffer.
    buf[0:8] = struct.pack("<Q", 0x0123456789ABCDEF)
    buf[DATA_BUF_SIZE - 8:DATA_BUF_SIZE] = struct.pack("<Q", 0xFEDCBA9876543210)
    return bytes(buf)


def pack_i32s(vals):
    padded = list(vals) + [0] * (8 - len(vals))
    return struct.pack("<8i", *padded[:8])


def pack_i64s(vals):
    padded = list(vals) + [0] * (4 - len(vals))
    return struct.pack("<4q", *padded[:4])


def pack_mask_bits(elem_bits, active_lanes, non_msb_noise=False):
    if elem_bits == 32:
        vals = []
        for i in range(8):
            if i in active_lanes:
                vals.append(0x80000000 if (i & 1) else 0xFFFFFFFF)
            else:
                vals.append(0x7FFFFFFF if non_msb_noise else 0x00000000)
        return pack_u32s(vals)
    vals = []
    for i in range(4):
        if i in active_lanes:
            vals.append(0x8000000000000000 if (i & 1) else 0xFFFFFFFFFFFFFFFF)
        else:
            vals.append(0x7FFFFFFFFFFFFFFF if non_msb_noise else 0x0000000000000000)
    return pack_u64s(vals)


def ref_gather(data, base_offset, init_dest, vindex_bytes, mask_bytes,
               elem_bits, idx_bits, count, scale, disp):
    elem_bytes = elem_bits // 8
    out = bytearray(32)
    active_bytes = count * elem_bytes
    out[:active_bytes] = init_dest[:active_bytes]
    indices = struct.unpack("<8i", vindex_bytes) if idx_bits == 32 else struct.unpack("<4q", vindex_bytes)
    if elem_bits == 32:
        masks = struct.unpack("<8I", mask_bytes)
        sign_bit = 0x80000000
    else:
        masks = struct.unpack("<4Q", mask_bytes)
        sign_bit = 0x8000000000000000
    for i in range(count):
        if masks[i] & sign_bit:
            off = base_offset + indices[i] * scale + disp
            if off < 0 or off + elem_bytes > len(data):
                raise AssertionError(f"reference gather offset {off} out of bounds [0, {len(data)})")
            out[i * elem_bytes:(i + 1) * elem_bytes] = data[off:off + elem_bytes]
    # Architectural effect: gather clears the entire 256-bit mask register.
    return bytes(out) + b"\x00" * 32


def ref_vpmaskmov_load(src_mem, src_offset, mask_bytes, elem_bits, wide):
    elem_bytes = elem_bits // 8
    lanes = (32 if wide else 16) // elem_bytes
    if elem_bits == 32:
        masks = struct.unpack("<8I", mask_bytes)
        sign_bit = 0x80000000
    else:
        masks = struct.unpack("<4Q", mask_bytes)
        sign_bit = 0x8000000000000000
    out = bytearray(32)
    for i in range(lanes):
        if masks[i] & sign_bit:
            off = src_offset + i * elem_bytes
            out[i * elem_bytes:(i + 1) * elem_bytes] = src_mem[off:off + elem_bytes]
    # Mask register is unchanged by vpmaskmov.
    return bytes(out) + mask_bytes


def ref_vpmaskmov_store(init_mem, src_bytes, mask_bytes, elem_bits, wide):
    elem_bytes = elem_bits // 8
    lanes = (32 if wide else 16) // elem_bytes
    if elem_bits == 32:
        masks = struct.unpack("<8I", mask_bytes)
        sign_bit = 0x80000000
    else:
        masks = struct.unpack("<4Q", mask_bytes)
        sign_bit = 0x8000000000000000
    out = bytearray(init_mem)
    for i in range(lanes):
        if masks[i] & sign_bit:
            out[i * elem_bytes:(i + 1) * elem_bytes] = src_bytes[i * elem_bytes:(i + 1) * elem_bytes]
    return bytes(out)


def gather_cases_for(elem_bits, idx_bits, count, scale, disp, alt_disp=None):
    """Generate (init_dest, vindex, mask, null_base) cases covering full/partial/zero masks and boundaries."""
    elem_bytes = elem_bits // 8
    disps = (disp, alt_disp) if alt_disp is not None else (disp,)
    # Compute inclusive [min_idx, max_idx] safe for both original and altered displacement.
    min_idx = max((-DATA_BASE_OFFSET - d + scale - 1) // scale for d in disps)
    max_idx = min((DATA_BUF_SIZE - elem_bytes - DATA_BASE_OFFSET - d) // scale for d in disps)
    pack_idx = pack_i32s if idx_bits == 32 else pack_i64s
    rng = random.Random(0x6A70 + elem_bits * 31 + idx_bits * 17 + count * 7 + scale * 3 + disp)

    def clamp(v):
        return max(min_idx, min(max_idx, v))

    seed_a = bytes(range(0x11, 0x31))
    seed_b = bytes(range(0x91, 0xB1))
    all_lanes = set(range(count))
    even_lanes = {i for i in range(count) if i % 2 == 0}
    odd_lanes = {i for i in range(count) if i % 2 == 1}
    hi_half = {i for i in range(count // 2, count)}
    lo_half = {i for i in range(count // 2)}

    # Unmapped / bogus index placed strictly in masked-off lanes to exercise fault suppression.
    bogus = 0x60000000 if idx_bits == 32 else 0x0000400000000000

    # 1) Full mask: mixed positive, zero, negative and boundary indices (hits FP specials & buffer ends).
    idx_mix = [clamp(v) for v in (0, 1, -1, 2, -2, max_idx, min_idx, 3)][:count]
    # 2) Full mask: all-negative and duplicate indices.
    idx_neg = [clamp(v) for v in (-1, -1, -2, -4, min_idx, -3, -2, -1)][:count]
    # 3) Full mask: IEEE-754 special region around offset 0..+63.
    idx_fp = [clamp(i) for i in range(count)]
    # 4) Partial mask (even lanes active; odd lanes carry bogus out-of-range index!).
    idx_even_bogus = [clamp(i - 2) if i in even_lanes else bogus for i in range(count)]
    # 5) Partial mask (odd lanes active; even lanes carry negative bogus index!).
    idx_odd_bogus = [clamp(max_idx - i) if i in odd_lanes else -bogus for i in range(count)]
    # 6) Single-lane active (last lane only).
    idx_last = [bogus] * (count - 1) + [clamp(-1)]
    # 7) Upper/lower half masks.
    idx_hi = [bogus if i not in hi_half else clamp(min_idx + i) for i in range(count)]
    idx_lo = [clamp(max_idx - i) if i in lo_half else bogus for i in range(count)]

    # Note: for zero-mask cases we also test non-zero bits in upper mask lanes (which must still zero out)
    # and base_ptr = 0 (NULL!) to prove zero-mask never dereferences memory.
    upper_mask_garbage = set(range(count, 8 if elem_bits == 32 else 4))
    cases = [
        (seed_a, pack_idx(idx_mix), pack_mask_bits(elem_bits, all_lanes), False),
        (seed_b, pack_idx(idx_neg), pack_mask_bits(elem_bits, all_lanes | upper_mask_garbage), False),
        (seed_a, pack_idx(idx_fp), pack_mask_bits(elem_bits, all_lanes), False),
        (seed_b, pack_idx(idx_even_bogus), pack_mask_bits(elem_bits, even_lanes, non_msb_noise=True), False),
        (seed_a, pack_idx(idx_odd_bogus), pack_mask_bits(elem_bits, odd_lanes, non_msb_noise=True), False),
        (seed_b, pack_idx(idx_last), pack_mask_bits(elem_bits, {count - 1}, non_msb_noise=True), False),
        (seed_a, pack_idx(idx_hi), pack_mask_bits(elem_bits, hi_half, non_msb_noise=True), False),
        (seed_b, pack_idx(idx_lo), pack_mask_bits(elem_bits, lo_half, non_msb_noise=True), False),
        # Zero mask (all 0x00) with NULL base pointer!
        (seed_a, pack_idx([bogus] * count), pack_mask_bits(elem_bits, set(), non_msb_noise=False), True),
        # Zero mask (all 0x7FFF... non-MSB noise + MSB set in unused upper lanes!) with NULL base pointer!
        (seed_b, pack_idx([-bogus] * count), pack_mask_bits(elem_bits, upper_mask_garbage, non_msb_noise=True), True),
    ]
    for _ in range(4):
        dest_r = rng.randbytes(32)
        active = {i for i in range(count) if rng.getrandbits(1)}
        idxs = [rng.randint(min_idx, max_idx) if i in active else bogus for i in range(count)]
        # Add random garbage in unused index lanes too (for vm32x with count=2, etc.).
        extra_count = (8 if idx_bits == 32 else 4) - count
        idxs.extend(rng.randint(-1000, 1000) for _ in range(extra_count))
        cases.append((dest_r, pack_idx(idxs), pack_mask_bits(elem_bits, active, non_msb_noise=True), False))
    return cases


def maskmov_cases_for(elem_bits, wide):
    """Generate (init_or_src, mask, null_ptr) cases for vpmaskmov load/store."""
    lanes = (32 if wide else 16) // (elem_bits // 8)
    all_lanes = set(range(lanes))
    even_lanes = {i for i in range(lanes) if i % 2 == 0}
    odd_lanes = {i for i in range(lanes) if i % 2 == 1}
    upper_unused = set(range(lanes, 8 if elem_bits == 32 else 4))
    seed_a = bytes(range(0x21, 0x41))
    seed_b = bytes(range(0x81, 0xA1))
    f32_specials = pack_u32s((
        0x00000000, 0x80000000, 0x00000001, 0x3F800000,
        0xBF800000, 0x7F800000, 0x7F800001, 0x7FC00001,
    ))
    rng = random.Random(0x55A0 + elem_bits * 13 + int(wide))
    cases = [
        (seed_a, pack_mask_bits(elem_bits, all_lanes), False),
        (f32_specials, pack_mask_bits(elem_bits, all_lanes | upper_unused), False),
        (seed_b, pack_mask_bits(elem_bits, even_lanes, non_msb_noise=True), False),
        (seed_a, pack_mask_bits(elem_bits, odd_lanes, non_msb_noise=True), False),
        (seed_b, pack_mask_bits(elem_bits, {lanes - 1}, non_msb_noise=True), False),
        (seed_a, pack_mask_bits(elem_bits, {0}, non_msb_noise=True), False),
        # Zero-mask cases with NULL memory pointer (fault suppression).
        (seed_a, pack_mask_bits(elem_bits, set(), non_msb_noise=False), True),
        (seed_b, pack_mask_bits(elem_bits, upper_unused, non_msb_noise=True), True),
    ]
    for _ in range(4):
        active = {i for i in range(lanes) if rng.getrandbits(1)}
        cases.append((rng.randbytes(32), pack_mask_bits(elem_bits, active, non_msb_noise=True), False))
    return cases


def invoke_gather(fn, data_buf_raw, base_ptr, init_dest, vindex, mask, rdx_base=False):
    ctrl = ctypes.create_string_buffer(init_dest + vindex + mask, 96)
    guarded_out = ctypes.create_string_buffer(GUARD_PRE + OUT_FILL_64 + GUARD_POST, 96)
    out_ptr = ctypes.addressof(guarded_out) + len(GUARD_PRE)
    if rdx_base:
        fn(ctypes.addressof(ctrl), base_ptr, out_ptr)
    else:
        fn(base_ptr, ctypes.addressof(ctrl), out_ptr)
    raw = guarded_out.raw
    if raw[:16] != GUARD_PRE or raw[80:] != GUARD_POST:
        raise AssertionError("guard bytes corrupted around gather output buffer")
    if data_buf_raw is not None:
        raw_d = data_buf_raw.raw
        if raw_d[:64] != DATA_GUARD_PRE or raw_d[64 + DATA_BUF_SIZE:] != DATA_GUARD_POST:
            raise AssertionError("guard bytes corrupted around gather source buffer")
    return raw[16:80]


def invoke_maskmov_load(fn, src_ptr, init_dest, mask):
    ctrl = ctypes.create_string_buffer(init_dest + mask, 64)
    guarded_out = ctypes.create_string_buffer(GUARD_PRE + OUT_FILL_64 + GUARD_POST, 96)
    out_ptr = ctypes.addressof(guarded_out) + len(GUARD_PRE)
    fn(src_ptr, ctypes.addressof(ctrl), out_ptr)
    raw = guarded_out.raw
    if raw[:16] != GUARD_PRE or raw[80:] != GUARD_POST:
        raise AssertionError("guard bytes corrupted around vpmaskmov load output buffer")
    return raw[16:80]


def invoke_maskmov_store(fn, src_vec, mask, init_mem, dst_ptr_override=None):
    buf_src = ctypes.create_string_buffer(src_vec, 32)
    buf_mask = ctypes.create_string_buffer(mask, 32)
    if dst_ptr_override is not None:
        fn(ctypes.addressof(buf_src), ctypes.addressof(buf_mask), dst_ptr_override)
        return init_mem
    guarded = ctypes.create_string_buffer(GUARD_PRE + init_mem + GUARD_POST, 64)
    dst_ptr = ctypes.addressof(guarded) + len(GUARD_PRE)
    fn(ctypes.addressof(buf_src), ctypes.addressof(buf_mask), dst_ptr)
    raw = guarded.raw
    if raw[:16] != GUARD_PRE or raw[48:] != GUARD_POST:
        raise AssertionError("guard bytes corrupted around vpmaskmov store destination buffer")
    return raw[16:48]


def check_guard_page_fault_suppression(native_mem, lifted_mem):
    """Allocate a PAGE_READWRITE page followed by a PAGE_NOACCESS page and verify masked-off lanes never fault."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualProtect.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.VirtualProtect.restype = ctypes.c_int
    kernel32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
    kernel32.VirtualFree.restype = ctypes.c_int

    page_size = 4096
    MEM_COMMIT_RESERVE = 0x3000
    MEM_RELEASE = 0x8000
    PAGE_READWRITE = 0x04
    PAGE_NOACCESS = 0x01

    base = kernel32.VirtualAlloc(None, page_size * 2, MEM_COMMIT_RESERVE, PAGE_READWRITE)
    if not base:
        raise OSError(f"VirtualAlloc failed with error {ctypes.get_last_error()}")
    checked = 0
    try:
        old_prot = ctypes.c_uint32(0)
        if not kernel32.VirtualProtect(base + page_size, page_size, PAGE_NOACCESS, ctypes.byref(old_prot)):
            raise OSError(f"VirtualProtect(PAGE_NOACCESS) failed with error {ctypes.get_last_error()}")
        page0_data = bytes((i * 73 + 19) & 0xFF for i in range(page_size))
        ctypes.memmove(base, page0_data, page_size)
        page1 = base + page_size

        # 1) Every gather export: base at page0 + 512, active lanes read page0, masked-off lanes target page1!
        g_base_off = 512
        g_base = base + g_base_off
        init_dest = bytes(range(0xA1, 0xC1))
        for name, elem_bits, idx_bits, count, scale, disp, _ in GATHER_SPECS:
            pack_idx = pack_i32s if idx_bits == 32 else pack_i64s
            # Offset to hit page1 (PAGE_NOACCESS): (page_size - g_base_off - disp) // scale + 1
            noaccess_idx = (page_size - g_base_off - disp + scale - 1) // scale + 1
            active = {i for i in range(count) if i % 2 == 0}
            idxs = [i - 1 if i in active else noaccess_idx for i in range(count)]
            vindex = pack_idx(idxs)
            mask = pack_mask_bits(elem_bits, active, non_msb_noise=True)
            want = ref_gather(page0_data, g_base_off, init_dest, vindex, mask,
                              elem_bits, idx_bits, count, scale, disp)
            rdx_base = name in RDX_BASE_GATHERS
            got_n = invoke_gather(native_mem[name], None, g_base, init_dest, vindex, mask, rdx_base)
            got_l = invoke_gather(lifted_mem[name], None, g_base, init_dest, vindex, mask, rdx_base)
            assert_equal_output("guard-native", name, 0, got_n, want)
            assert_equal_output("guard-lifted", name, 0, got_l, want)
            checked += 1

        # 2) Every vpmaskmov load: straddle page0/page1 so upper half sits on PAGE_NOACCESS with mask MSB=0.
        for name, elem_bits, wide, _ in MASKMOV_LOAD_SPECS:
            elem_bytes = elem_bits // 8
            total_bytes = 32 if wide else 16
            half_bytes = total_bytes // 2
            lanes = total_bytes // elem_bytes
            active = set(range(lanes // 2))
            mask = pack_mask_bits(elem_bits, active, non_msb_noise=True)
            straddle_off = page_size - half_bytes
            want = ref_vpmaskmov_load(page0_data, straddle_off, mask, elem_bits, wide)
            got_n = invoke_maskmov_load(native_mem[name], base + straddle_off, init_dest, mask)
            got_l = invoke_maskmov_load(lifted_mem[name], base + straddle_off, init_dest, mask)
            assert_equal_output("guard-native", name, 0, got_n, want)
            assert_equal_output("guard-lifted", name, 0, got_l, want)
            # Zero-mask directly on PAGE_NOACCESS base must not fault.
            zero_mask = pack_mask_bits(elem_bits, set(), non_msb_noise=True)
            want_z = b"\x00" * 32 + zero_mask
            got_nz = invoke_maskmov_load(native_mem[name], page1, init_dest, zero_mask)
            got_lz = invoke_maskmov_load(lifted_mem[name], page1, init_dest, zero_mask)
            assert_equal_output("guard-zero-native", name, 1, got_nz, want_z)
            assert_equal_output("guard-zero-lifted", name, 1, got_lz, want_z)
            checked += 2

        # 3) Every vpmaskmov store: straddle page0/page1 so upper half sits on PAGE_NOACCESS with mask MSB=0.
        src_vec = bytes(range(0x10, 0x30))
        for name, elem_bits, wide in MASKMOV_STORE_SPECS:
            elem_bytes = elem_bits // 8
            total_bytes = 32 if wide else 16
            half_bytes = total_bytes // 2
            lanes = total_bytes // elem_bytes
            active = set(range(lanes // 2))
            mask = pack_mask_bits(elem_bits, active, non_msb_noise=True)
            straddle_off = page_size - half_bytes
            init_tail = bytes(0xE0 + i for i in range(half_bytes))
            want_tail = ref_vpmaskmov_store(init_tail + b"\x00" * (32 - half_bytes),
                                            src_vec, mask, elem_bits, wide)[:half_bytes]
            for label, fn in (("guard-native", native_mem[name]), ("guard-lifted", lifted_mem[name])):
                ctypes.memmove(base + straddle_off, init_tail, half_bytes)
                invoke_maskmov_store(fn, src_vec, mask, init_tail, dst_ptr_override=base + straddle_off)
                got_tail = ctypes.string_at(base + straddle_off, half_bytes)
                assert_equal_output(label, name, 0, got_tail, want_tail)
            # Zero-mask directly on PAGE_NOACCESS must not fault.
            zero_mask = pack_mask_bits(elem_bits, set(), non_msb_noise=True)
            invoke_maskmov_store(native_mem[name], src_vec, zero_mask, STORE_INIT, dst_ptr_override=page1)
            invoke_maskmov_store(lifted_mem[name], src_vec, zero_mask, STORE_INIT, dst_ptr_override=page1)
            checked += 2
    finally:
        kernel32.VirtualFree(base, 0, MEM_RELEASE)
    return checked


def check_differential(native_path, lifted_path, altered_path):
    native = bind_exports(native_path)
    lifted = bind_exports(lifted_path, "lifted_")
    altered = bind_exports(altered_path, "lifted_")

    total = 0
    for name in EXPORTS:
        for idx, (a, b) in enumerate(inputs_for(name)):
            want = reference(name, a, b, altered=False)
            got_native = invoke(native[name], a, b)
            got_lifted = invoke(lifted[name], a, b)
            assert_equal_output("native", name, idx, got_native, want)
            assert_equal_output("lifted", name, idx, got_lifted, want)
            total += 1

    # Memory-domain differential checks against dedicated guarded source buffer.
    native_mem = bind_exports(native_path, "", MEMORY_EXPORTS)
    lifted_mem = bind_exports(lifted_path, "lifted_", MEMORY_EXPORTS)
    altered_mem = bind_exports(altered_path, "lifted_", MEMORY_EXPORTS)

    known_data = build_known_data_buffer()
    guarded_data = ctypes.create_string_buffer(
        DATA_GUARD_PRE + known_data + DATA_GUARD_POST, len(DATA_GUARD_PRE) + DATA_BUF_SIZE + len(DATA_GUARD_POST))
    base_ptr = ctypes.addressof(guarded_data) + len(DATA_GUARD_PRE) + DATA_BASE_OFFSET

    mem_total = 0
    for name, elem_bits, idx_bits, count, scale, disp, alt_disp in GATHER_SPECS:
        for idx, (init_dest, vindex, mask, null_base) in enumerate(
                gather_cases_for(elem_bits, idx_bits, count, scale, disp, alt_disp)):
            want = ref_gather(known_data, DATA_BASE_OFFSET, init_dest, vindex, mask,
                              elem_bits, idx_bits, count, scale, disp)
            ptr = 0 if null_base else base_ptr
            rdx_base = name in RDX_BASE_GATHERS
            got_n = invoke_gather(native_mem[name], guarded_data, ptr, init_dest, vindex, mask, rdx_base)
            got_l = invoke_gather(lifted_mem[name], guarded_data, ptr, init_dest, vindex, mask, rdx_base)
            assert_equal_output("native", name, idx, got_n, want)
            assert_equal_output("lifted", name, idx, got_l, want)
            mem_total += 1

    for name, elem_bits, wide, _ in MASKMOV_LOAD_SPECS:
        for idx, (init_dest, mask, null_ptr) in enumerate(maskmov_cases_for(elem_bits, wide)):
            want = ref_vpmaskmov_load(known_data, DATA_BASE_OFFSET, mask, elem_bits, wide)
            ptr = 0 if null_ptr else base_ptr
            got_n = invoke_maskmov_load(native_mem[name], ptr, init_dest, mask)
            got_l = invoke_maskmov_load(lifted_mem[name], ptr, init_dest, mask)
            assert_equal_output("native", name, idx, got_n, want)
            assert_equal_output("lifted", name, idx, got_l, want)
            mem_total += 1

    for name, elem_bits, wide in MASKMOV_STORE_SPECS:
        for idx, (src_vec, mask, null_ptr) in enumerate(maskmov_cases_for(elem_bits, wide)):
            want = ref_vpmaskmov_store(STORE_INIT, src_vec, mask, elem_bits, wide)
            override = 0 if null_ptr else None
            got_n = invoke_maskmov_store(native_mem[name], src_vec, mask, STORE_INIT, dst_ptr_override=override)
            got_l = invoke_maskmov_store(lifted_mem[name], src_vec, mask, STORE_INIT, dst_ptr_override=override)
            assert_equal_output("native", name, idx, got_n, want)
            assert_equal_output("lifted", name, idx, got_l, want)
            mem_total += 1

    guard_total = check_guard_page_fault_suppression(native_mem, lifted_mem)

    # Altered build negative controls (register-domain and memory-domain).
    altered_exports = ("op_perm2i128_mix", "op_permq", "op_pblendd_ymm")
    changed = {}
    for name in altered_exports:
        diffs = 0
        for idx, (a, b) in enumerate(inputs_for(name)):
            want_alt = reference(name, a, b, altered=True)
            want_orig = reference(name, a, b, altered=False)
            got_alt = invoke(altered[name], a, b)
            assert_equal_output("altered", name, idx, got_alt, want_alt)
            if got_alt != want_orig:
                diffs += 1
        if not diffs:
            raise AssertionError(f"altered control {name} did not diverge from original")
        changed[name] = diffs

    # Altered gather control (op_gatherdps_ymm uses +16 displacement in ALTER_IMM).
    g_spec = next(s for s in GATHER_SPECS if s[0] == "op_gatherdps_ymm")
    _, elem_bits, idx_bits, count, scale, disp, alt_disp = g_spec
    g_diffs = 0
    for idx, (init_dest, vindex, mask, null_base) in enumerate(
            gather_cases_for(elem_bits, idx_bits, count, scale, disp, alt_disp)):
        want_alt = ref_gather(known_data, DATA_BASE_OFFSET, init_dest, vindex, mask,
                              elem_bits, idx_bits, count, scale, alt_disp)
        want_orig = ref_gather(known_data, DATA_BASE_OFFSET, init_dest, vindex, mask,
                               elem_bits, idx_bits, count, scale, disp)
        got_alt = invoke_gather(altered_mem["op_gatherdps_ymm"], guarded_data,
                                0 if null_base else base_ptr, init_dest, vindex, mask)
        assert_equal_output("altered", "op_gatherdps_ymm", idx, got_alt, want_alt)
        if got_alt != want_orig:
            g_diffs += 1
    if not g_diffs:
        raise AssertionError("altered control op_gatherdps_ymm did not diverge from original")
    changed["op_gatherdps_ymm"] = g_diffs

    # Altered vpmaskmov load control (op_pmaskmovd_load_ymm uses +16 displacement in ALTER_IMM).
    m_diffs = 0
    for idx, (init_dest, mask, null_ptr) in enumerate(maskmov_cases_for(32, True)):
        want_alt = ref_vpmaskmov_load(known_data, DATA_BASE_OFFSET + 16, mask, 32, True)
        want_orig = ref_vpmaskmov_load(known_data, DATA_BASE_OFFSET, mask, 32, True)
        got_alt = invoke_maskmov_load(altered_mem["op_pmaskmovd_load_ymm"],
                                      0 if null_ptr else base_ptr, init_dest, mask)
        assert_equal_output("altered", "op_pmaskmovd_load_ymm", idx, got_alt, want_alt)
        if got_alt != want_orig:
            m_diffs += 1
    if not m_diffs:
        raise AssertionError("altered control op_pmaskmovd_load_ymm did not diverge from original")
    changed["op_pmaskmovd_load_ymm"] = m_diffs

    # Explicit comparator mutation control: flipping one bit must fail assert_equal_output.
    sample_a, sample_b = general_pairs()[0]
    expected = reference("op_pipeline", sample_a, sample_b)
    mutated = bytearray(expected)
    mutated[17] ^= 0x01
    try:
        assert_equal_output("mutation", "op_pipeline", 0, bytes(mutated), expected)
    except AssertionError:
        pass
    else:
        raise AssertionError("mutated output was not caught by comparator")

    print(f"{total + mem_total} native/lifted/reference AVX2 cases ({total} register-domain across {len(EXPORTS)} "
          f"exports + {mem_total} memory-domain across {len(MEMORY_EXPORTS)} exports) and {guard_total} guard-page "
          f"fault-suppression cases matched bit-for-bit; altered controls diverged on {changed}; "
          f"output mutation control caught")


# --- Translator rejection controls ---

def encode_seq(*instructions):
    enc = Encoder(64)
    ip = 0x1000
    for ins in instructions:
        ip += enc.encode(ins, ip)
    return enc.take_buffer()


def check_rejections(original_path):
    """Verify register-only memory ops, illegal gather/maskmov forms, EVEX, and ABI/state violations reject."""
    ld_ymm0 = Instruction.create_reg_mem(Code.VEX_VMOVDQU_YMM_YMMM256, R.YMM0, MemoryOperand(R.RCX))
    ld_ymm1 = Instruction.create_reg_mem(Code.VEX_VMOVDQU_YMM_YMMM256, R.YMM1, MemoryOperand(R.RCX))
    ld_ymm2 = Instruction.create_reg_mem(Code.VEX_VMOVDQU_YMM_YMMM256, R.YMM2, MemoryOperand(R.RDX))
    ret_ins = Instruction.create(Code.RETNQ)

    # 1) Memory-operand encodings of all 17 register-only AVX2 forms must be rejected explicitly.
    reg_only_mem_cases = [
        ("vextracti128_mem", Instruction.create_mem_reg_u32(
            Code.VEX_VEXTRACTI128_XMMM128_YMM_IMM8, MemoryOperand(R.R8), R.YMM0, 1)),
        ("vinserti128_mem", Instruction.create_reg_reg_mem_u32(
            Code.VEX_VINSERTI128_YMM_YMM_XMMM128_IMM8, R.YMM0, R.YMM1, MemoryOperand(R.RDX), 1)),
        ("vperm2i128_mem", Instruction.create_reg_reg_mem_u32(
            Code.VEX_VPERM2I128_YMM_YMM_YMMM256_IMM8, R.YMM0, R.YMM1, MemoryOperand(R.RDX), 0x20)),
        ("vpbroadcastb_mem", Instruction.create_reg_mem(
            Code.VEX_VPBROADCASTB_YMM_XMMM8, R.YMM0, MemoryOperand(R.RCX))),
        ("vpbroadcastw_mem", Instruction.create_reg_mem(
            Code.VEX_VPBROADCASTW_YMM_XMMM16, R.YMM0, MemoryOperand(R.RCX))),
        ("vpbroadcastd_mem", Instruction.create_reg_mem(
            Code.VEX_VPBROADCASTD_YMM_XMMM32, R.YMM0, MemoryOperand(R.RCX))),
        ("vpbroadcastq_mem", Instruction.create_reg_mem(
            Code.VEX_VPBROADCASTQ_YMM_XMMM64, R.YMM0, MemoryOperand(R.RCX))),
        ("vpermd_mem", Instruction.create_reg_reg_mem(
            Code.VEX_VPERMD_YMM_YMM_YMMM256, R.YMM0, R.YMM1, MemoryOperand(R.RDX))),
        ("vpermpd_mem", Instruction.create_reg_mem_u32(
            Code.VEX_VPERMPD_YMM_YMMM256_IMM8, R.YMM0, MemoryOperand(R.RCX), 0x1B)),
        ("vpermps_mem", Instruction.create_reg_reg_mem(
            Code.VEX_VPERMPS_YMM_YMM_YMMM256, R.YMM0, R.YMM1, MemoryOperand(R.RDX))),
        ("vpermq_mem", Instruction.create_reg_mem_u32(
            Code.VEX_VPERMQ_YMM_YMMM256_IMM8, R.YMM0, MemoryOperand(R.RCX), 0x1B)),
        ("vpblendd_mem", Instruction.create_reg_reg_mem_u32(
            Code.VEX_VPBLENDD_YMM_YMM_YMMM256_IMM8, R.YMM0, R.YMM1, MemoryOperand(R.RDX), 0xAA)),
        ("vpsllvd_mem", Instruction.create_reg_reg_mem(
            Code.VEX_VPSLLVD_YMM_YMM_YMMM256, R.YMM0, R.YMM1, MemoryOperand(R.RDX))),
        ("vpsllvq_mem", Instruction.create_reg_reg_mem(
            Code.VEX_VPSLLVQ_YMM_YMM_YMMM256, R.YMM0, R.YMM1, MemoryOperand(R.RDX))),
        ("vpsravd_mem", Instruction.create_reg_reg_mem(
            Code.VEX_VPSRAVD_YMM_YMM_YMMM256, R.YMM0, R.YMM1, MemoryOperand(R.RDX))),
        ("vpsrlvd_mem", Instruction.create_reg_reg_mem(
            Code.VEX_VPSRLVD_YMM_YMM_YMMM256, R.YMM0, R.YMM1, MemoryOperand(R.RDX))),
        ("vpsrlvq_mem", Instruction.create_reg_reg_mem(
            Code.VEX_VPSRLVQ_YMM_YMM_YMMM256, R.YMM0, R.YMM1, MemoryOperand(R.RDX))),
    ]

    # 2) Out-of-scope instructions.
    out_of_scope_cases = [
        ("vpaddd", Instruction.create_reg_reg_reg(Code.VEX_VPADDD_YMM_YMM_YMMM256, R.YMM0, R.YMM1, R.YMM2)),
        ("vperm2f128", Instruction.create_reg_reg_reg_u32(
            Code.VEX_VPERM2F128_YMM_YMM_YMMM256_IMM8, R.YMM0, R.YMM1, R.YMM2, 0x20)),
        ("vpxor", Instruction.create_reg_reg_reg(Code.VEX_VPXOR_YMM_YMM_YMMM256, R.YMM0, R.YMM1, R.YMM2)),
        ("vmovdqa", Instruction.create_reg_mem(Code.VEX_VMOVDQA_YMM_YMMM256, R.YMM0, MemoryOperand(R.RCX))),
        ("addps", Instruction.create_reg_reg(Code.ADDPS_XMM_XMMM128, R.XMM0, R.XMM1)),
        ("add_gpr", Instruction.create_reg_reg(Code.ADD_R32_RM32, R.EAX, R.ECX)),
        ("ud2", Instruction.create(Code.UD2)),
    ]

    # 3) Gather and vpmaskmov genuine rejection controls (overlaps, invalid addressing, EVEX, state).
    gather_seg = Instruction.create_reg_mem_reg(
        Code.VEX_VGATHERDPS_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RCX, R.YMM1, 4), R.YMM2)
    gather_seg.segment_prefix = R.GS
    maskmov_seg = Instruction.create_reg_reg_mem(
        Code.VEX_VPMASKMOVD_YMM_YMM_M256, R.YMM0, R.YMM1, MemoryOperand(R.RCX))
    maskmov_seg.segment_prefix = R.FS
    evex_gather_dps = Instruction.create_reg_mem(
        Code.EVEX_VGATHERDPS_YMM_K1_VM32Y, R.YMM0, MemoryOperand(R.RCX, R.YMM1, 4))
    evex_gather_dps.op_mask = R.K1
    evex_gather_qq = Instruction.create_reg_mem(
        Code.EVEX_VPGATHERQQ_YMM_K1_VM64Y, R.YMM0, MemoryOperand(R.RCX, R.YMM1, 8))
    evex_gather_qq.op_mask = R.K1

    memory_reject_cases = [
        ("gather_overlap_dst_idx", (ld_ymm0, ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERDPS_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RCX, R.YMM0, 4), R.YMM2), ret_ins),
         "overlapping gather registers"),
        ("gather_overlap_dst_mask", (ld_ymm0, ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERDPS_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RCX, R.YMM1, 4), R.YMM0), ret_ins),
         "overlapping gather registers"),
        ("gather_overlap_idx_mask", (ld_ymm0, ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERDPS_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RCX, R.YMM1, 4), R.YMM1), ret_ins),
         "overlapping gather registers"),
        ("gather_overlap_dpd_xmm_ymm", (ld_ymm0, ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERDPD_YMM_VM32X_YMM, R.YMM0, MemoryOperand(R.RCX, R.XMM0, 8), R.YMM2), ret_ins),
         "overlapping gather registers"),
        ("gather_overlap_qps_xmm_ymm", (ld_ymm0, ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERQPS_XMM_VM64Y_XMM, R.XMM1, MemoryOperand(R.RCX, R.YMM1, 4), R.XMM2), ret_ins),
         "overlapping gather registers"),
        ("gather_no_base", (ld_ymm0, ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VPGATHERDD_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.NONE, R.YMM1, 4, displ=0x100, displ_size=4), R.YMM2), ret_ins),
         "unsupported memory operand"),
        ("gather_rsp_base", (ld_ymm0, ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VPGATHERDD_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RSP, R.YMM1, 4), R.YMM2), ret_ins),
         "unsupported memory operand"),
        ("gather_non_arg_base_rax", (ld_ymm0, ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VPGATHERDD_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RAX, R.YMM1, 4), R.YMM2), ret_ins),
         "unsupported memory operand"),
        ("gather_addr32_base", (ld_ymm0, ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VPGATHERDD_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.ECX, R.YMM1, 4), R.YMM2), ret_ins),
         "unsupported memory operand"),
        ("gather_seg_prefix", (ld_ymm0, ld_ymm1, ld_ymm2, gather_seg, ret_ins),
         "unsupported instruction prefix"),
        ("gather_nonvolatile_index", (ld_ymm0, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERDPS_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RCX, R.YMM6, 4), R.YMM2), ret_ins),
         "nonvolatile vector register"),
        ("gather_nonvolatile_mask", (ld_ymm0, ld_ymm1, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERDPS_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RCX, R.YMM1, 4), R.YMM6), ret_ins),
         "nonvolatile vector register"),
        ("gather_undef_dest", (ld_ymm1, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERDPS_YMM_VM32Y_YMM, R.YMM3, MemoryOperand(R.RCX, R.YMM1, 4), R.YMM2), ret_ins),
         "undefined vector register ymm3"),
        ("gather_undef_index", (ld_ymm0, ld_ymm2, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERDPS_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RCX, R.YMM3, 4), R.YMM2), ret_ins),
         "undefined vector register ymm3"),
        ("gather_undef_mask", (ld_ymm0, ld_ymm1, Instruction.create_reg_mem_reg(
            Code.VEX_VGATHERDPS_YMM_VM32Y_YMM, R.YMM0, MemoryOperand(R.RCX, R.YMM1, 4), R.YMM3), ret_ins),
         "undefined vector register ymm3"),
        ("evex_vgatherdps", (ld_ymm0, ld_ymm1, evex_gather_dps, ret_ins),
         "unsupported EVEX instruction"),
        ("evex_vpgatherqq", (ld_ymm0, ld_ymm1, evex_gather_qq, ret_ins),
         "unsupported EVEX instruction"),
        ("maskmov_rip_rel", (ld_ymm1, Instruction.create_reg_reg_mem(
            Code.VEX_VPMASKMOVD_YMM_YMM_M256, R.YMM0, R.YMM1, MemoryOperand(R.RIP, displ=0x1010, displ_size=1)), ret_ins),
         "unsupported memory operand"),
        ("maskmov_indexed", (ld_ymm1, Instruction.create_reg_reg_mem(
            Code.VEX_VPMASKMOVD_YMM_YMM_M256, R.YMM0, R.YMM1, MemoryOperand(R.RCX, R.RDX, 4)), ret_ins),
         "unsupported memory operand"),
        ("maskmov_non_arg_base", (ld_ymm1, ld_ymm2, Instruction.create_mem_reg_reg(
            Code.VEX_VPMASKMOVQ_M256_YMM_YMM, MemoryOperand(R.RAX), R.YMM1, R.YMM2), ret_ins),
         "unsupported memory operand"),
        ("maskmov_seg_prefix", (ld_ymm1, maskmov_seg, ret_ins),
         "unsupported instruction prefix"),
        ("maskmov_undef_mask", (Instruction.create_reg_reg_mem(
            Code.VEX_VPMASKMOVD_YMM_YMM_M256, R.YMM0, R.YMM3, MemoryOperand(R.RCX)), ret_ins),
         "undefined vector register ymm3"),
        ("maskmov_store_undef_src", (ld_ymm1, Instruction.create_mem_reg_reg(
            Code.VEX_VPMASKMOVQ_M256_YMM_YMM, MemoryOperand(R.R8), R.YMM1, R.YMM3), ret_ins),
         "undefined vector register ymm3"),
    ]

    # 4) ABI, register-state and addressing violations.
    seg_ins = Instruction.create_reg_mem(Code.VEX_VBROADCASTI128_YMM_M128, R.YMM0, MemoryOperand(R.RCX))
    seg_ins.segment_prefix = R.GS
    evex_ins = Instruction.create_reg_reg_reg(
        Code.EVEX_VPERMD_YMM_K1Z_YMM_YMMM256B32, R.YMM0, R.YMM1, R.YMM2)
    evex_ins.op_mask = R.K1
    other_cases = [
        ("evex_masked_vpermd", (ld_ymm0, ld_ymm1, ld_ymm2, evex_ins, ret_ins),
         "unsupported EVEX instruction"),
        ("nonvolatile_ymm6", (Instruction.create_reg_mem(
            Code.VEX_VMOVDQU_YMM_YMMM256, R.YMM6, MemoryOperand(R.RCX)), ret_ins),
         "nonvolatile vector register"),
        ("nonvolatile_xmm6", (ld_ymm0, Instruction.create_reg_reg_u32(
            Code.VEX_VEXTRACTI128_XMMM128_YMM_IMM8, R.XMM6, R.YMM0, 0), ret_ins),
         "nonvolatile vector register"),
        ("undefined_ymm3", (ld_ymm0, Instruction.create_reg_reg_u32(
            Code.VEX_VPERMQ_YMM_YMMM256_IMM8, R.YMM0, R.YMM3, 0x1B), ret_ins),
         "undefined vector register ymm3"),
        ("rip_rel_mem", (Instruction.create_reg_mem(
            Code.VEX_VBROADCASTI128_YMM_M128, R.YMM0, MemoryOperand(R.RIP, displ=0x1010, displ_size=1)), ret_ins),
         "unsupported memory operand"),
        ("rsp_mem", (Instruction.create_reg_mem(
            Code.VEX_VBROADCASTI128_YMM_M128, R.YMM0, MemoryOperand(R.RSP)), ret_ins),
         "unsupported memory operand"),
        ("addr32_mem", (Instruction.create_reg_mem(
            Code.VEX_VBROADCASTI128_YMM_M128, R.YMM0, MemoryOperand(R.ECX)), ret_ins),
         "unsupported memory operand"),
        ("indexed_mem", (Instruction.create_reg_mem(
            Code.VEX_VBROADCASTI128_YMM_M128, R.YMM0, MemoryOperand(R.RCX, R.RDX, 1)), ret_ins),
         "unsupported memory operand"),
        ("non_arg_base_rax", (Instruction.create_reg_mem(
            Code.VEX_VBROADCASTI128_YMM_M128, R.YMM0, MemoryOperand(R.RAX)), ret_ins),
         "unsupported memory operand"),
        ("segment_prefix", (seg_ins, ret_ins), "unsupported instruction prefix"),
        ("missing_ret", (ld_ymm0,), "missing terminal ret"),
        ("after_ret", (ret_ins, ld_ymm0), "unreachable instruction after ret"),
    ]

    all_unit = [
        *((lbl, (ld_ymm0, ld_ymm1, ld_ymm2, ins, ret_ins),
           "unsupported memory operand for register-domain AVX2 instruction")
          for lbl, ins in reg_only_mem_cases),
        *((lbl, (ld_ymm0, ld_ymm1, ld_ymm2, ins, ret_ins), "unsupported instruction")
          for lbl, ins in out_of_scope_cases),
        *memory_reject_cases,
        *other_cases,
    ]

    for label, seq, expected_reason in all_unit:
        raw = encode_seq(*seq)
        try:
            lift_code(label, 0x1000, raw)
        except ValueError as exc:
            if expected_reason not in str(exc):
                raise AssertionError(f"{label}: expected {expected_reason!r}, got {exc!r}") from exc
        else:
            raise AssertionError(f"{label}: translator unexpectedly accepted rejected control")

    # 5) Direct VSIB illegal-scale validator checks (SIB encoding only encodes 1/2/4/8 in hardware).
    scale_checks = 0
    for bad_scale in (0, 3, 5, 16):
        fake_ins = SimpleNamespace(
            ip=0x1000, is_vsib=True, is_vsib32=True, is_vsib64=False,
            is_ip_rel_memory_operand=False, memory_base=R.RCX,
            memory_index_scale=bad_scale, memory_index=R.YMM1, memory_displacement=0)
        try:
            vsib_address(fake_ins, True, 32)
        except ValueError as exc:
            if f"unsupported VSIB scale {bad_scale}" not in str(exc):
                raise AssertionError(f"bad_scale={bad_scale}: unexpected error {exc!r}") from exc
        else:
            raise AssertionError(f"bad_scale={bad_scale}: vsib_address unexpectedly accepted invalid scale")
        scale_checks += 1

    # End-to-end PE patching controls on a copy of the built native DLL.
    # Each patch replaces op_pipeline's bytes and updates its .pdata EndAddress so the entire
    # runtime-function interval is cleanly decoded before hitting the expected rejection.
    pe_bytes = Path(original_path).read_bytes()
    with pefile.PE(data=pe_bytes, fast_load=True) as pe:
        entry = export_rva(pe, "op_pipeline")
        file_off = pe.get_offset_from_rva(entry)
        pdata = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        records = pe.get_data(pdata.VirtualAddress, pdata.Size)
        rec_idx = next(i for i in range(0, len(records), 12)
                       if struct.unpack_from("<I", records, i)[0] == entry)
        pdata_end_off = pe.get_offset_from_rva(pdata.VirtualAddress + rec_idx + 4)
        orig_end = struct.unpack_from("<I", records, rec_idx + 4)[0]
        max_len = orig_end - entry

    pe_patches = [
        ("pe_gather_overlap", encode_seq(*memory_reject_cases[0][1]), "overlapping gather registers"),
        ("pe_evex_vgatherdps", encode_seq(*memory_reject_cases[15][1]), "unsupported EVEX instruction"),
        ("pe_maskmov_indexed", encode_seq(*memory_reject_cases[18][1]), "unsupported memory operand"),
        ("pe_vperm2i128_mem", encode_seq(ld_ymm0, ld_ymm1, reg_only_mem_cases[2][1], ret_ins),
         "unsupported memory operand for register-domain AVX2 instruction"),
        ("pe_vpaddd", encode_seq(ld_ymm0, ld_ymm1, ld_ymm2, out_of_scope_cases[0][1], ret_ins),
         "unsupported instruction"),
        ("pe_nonvolatile_ymm6", encode_seq(other_cases[1][1][0], ret_ins),
         "nonvolatile vector register"),
        ("pe_undef_ymm3", encode_seq(ld_ymm0, other_cases[3][1][1], ret_ins),
         "undefined vector register ymm3"),
        ("pe_missing_ret", encode_seq(ld_ymm0), "missing terminal ret"),
        ("pe_after_ret", encode_seq(ret_ins, ld_ymm0), "unreachable instruction after ret"),
    ]
    with TemporaryDirectory() as folder:
        patched_path = Path(folder) / "patched.dll"
        for label, patch, expected_reason in pe_patches:
            if len(patch) > max_len:
                raise AssertionError(f"{label}: patch ({len(patch)} bytes) exceeds op_pipeline ({max_len})")
            damaged = bytearray(pe_bytes)
            damaged[file_off:file_off + len(patch)] = patch
            struct.pack_into("<I", damaged, pdata_end_off, entry + len(patch))
            patched_path.write_bytes(damaged)
            try:
                translate(patched_path, ["op_pipeline"])
            except ValueError as exc:
                if expected_reason not in str(exc):
                    raise AssertionError(f"{label}: expected {expected_reason!r}, got {exc!r}") from exc
            else:
                raise AssertionError(f"{label}: PE translate accepted rejected patch")

    print(f"{len(all_unit)} unit rejection controls ({len(reg_only_mem_cases)} register-domain memory, "
          f"{len(out_of_scope_cases)} out-of-scope, {len(memory_reject_cases)} gather/maskmov/EVEX, "
          f"{len(other_cases)} ABI/state), {scale_checks} invalid-scale controls, and "
          f"{len(pe_patches)} PE-patched rejection controls passed")


if __name__ == "__main__":
    check_differential(*sys.argv[1:4])
    check_rejections(sys.argv[1])
