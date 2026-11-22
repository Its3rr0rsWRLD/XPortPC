"""Offline C++ lowering for the null-context FidelityFX version-query path."""
import argparse
import hashlib
from pathlib import Path

import pefile
from iced_x86 import Code as C, Decoder, EncodingKind, MemorySizeExt, Mnemonic as M, OpKind as K, Register as R, RegisterExt

from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges, image_bytes
import x87_lower


LOADER = "431bdd2e26c0c8214fd7601140eb9fe6d8a249f5000539453a9a9b6a0b7c0ee8"
UPSCALER = "faff02f294a7e9149ce079dffe3dedbcabe99b1f180ab14222aa8689e00a75fa"
REGS = {getattr(R, n.upper()): n for n in "rax rbx rcx rdx rsi rdi rbp rsp r8 r9 r10 r11 r12 r13 r14 r15".split()}
HIGH_BYTE = {R.AH, R.BH, R.CH, R.DH}
UINT = {1: "uint8_t", 2: "uint16_t", 4: "uint32_t", 8: "uint64_t"}
# String instructions by Code: the SSE2 scalar MOVSD and CMPSD share their mnemonics.
STRING_OPS = {
    C.MOVSB_M8_M8: ("movs", 1), C.MOVSW_M16_M16: ("movs", 2), C.MOVSD_M32_M32: ("movs", 4), C.MOVSQ_M64_M64: ("movs", 8),
    C.STOSB_M8_AL: ("stos", 1), C.STOSW_M16_AX: ("stos", 2), C.STOSD_M32_EAX: ("stos", 4), C.STOSQ_M64_RAX: ("stos", 8),
    C.LODSB_AL_M8: ("lods", 1), C.LODSW_AX_M16: ("lods", 2), C.LODSD_EAX_M32: ("lods", 4), C.LODSQ_RAX_M64: ("lods", 8),
    C.SCASB_AL_M8: ("scas", 1), C.SCASW_AX_M16: ("scas", 2), C.SCASD_EAX_M32: ("scas", 4), C.SCASQ_RAX_M64: ("scas", 8),
    C.CMPSB_M8_M8: ("cmps", 1), C.CMPSW_M16_M16: ("cmps", 2), C.CMPSD_M32_M32: ("cmps", 4), C.CMPSQ_M64_M64: ("cmps", 8),
}

INTEGER_HEADER = """#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <intrin.h>
#include <emmintrin.h>
using std::memcpy;
using std::memset;
using word = uint64_t;
static_assert(sizeof(void*) == sizeof(word));
template<class T> T load(word address) {
    T v; memcpy(&v, reinterpret_cast<const void*>(address), sizeof v); return v;
}
template<class T> T load_always(word address) {
    T v;
    const volatile auto* p = reinterpret_cast<const volatile uint8_t*>(address);
    auto* q = reinterpret_cast<uint8_t*>(&v);
    for (size_t i = 0; i < sizeof v; ++i) q[i] = p[i];
    return v;
}
template<class T> void store(word address, T v) {
    memcpy(reinterpret_cast<void*>(address), &v, sizeof v);
}
[[noreturn]] static void raise_de() {
    volatile uint32_t zero_divisor = 0;
    volatile uint32_t sink = 1u / zero_divisor;
    (void)sink;
    for (;;) {}
template<class F, class U> static F quiet_nan(F x) {
    U bits; memcpy(&bits, &x, sizeof bits);
    bits |= (sizeof(U) == 4) ? static_cast<U>(0x00400000u) : static_cast<U>(0x0008000000000000ull);
    memcpy(&x, &bits, sizeof bits);
    return x;
}
template<class F, class U> static F fma_x86(F s0, F s1, F s2, int order, bool neg_p, bool neg_c) {
    if (std::isnan(s0)) return quiet_nan<F, U>(s0);
    if (std::isnan(s1)) return quiet_nan<F, U>(s1);
    if (std::isnan(s2)) return quiet_nan<F, U>(s2);
    const F a = order == 132 ? s0 : s1;
    const F b = order == 213 ? s0 : s2;
    const F c = order == 231 ? s0 : (order == 132 ? s1 : s2);
    return std::fma(neg_p ? -a : a, b, neg_c ? -c : c);
static inline uint8_t aes_gf_mul(uint8_t a, uint8_t b) {
    uint8_t p = 0;
    for (int i = 0; i < 8; ++i) {
        if (b & 1u) p ^= a;
        a = static_cast<uint8_t>((a << 1) ^ ((a & 0x80u) ? 0x1bu : 0u));
        b >>= 1;
    }
    return p;
}
static inline uint8_t aes_gf_inv(uint8_t x) {
    uint8_t r = 1, b = x;
    for (int e = 254; e > 0; e >>= 1) {
        if (e & 1) r = aes_gf_mul(r, b);
        b = aes_gf_mul(b, b);
    }
    return x == 0 ? 0 : r;
}
static inline uint8_t aes_rotl8(uint8_t x, unsigned n) {
    return static_cast<uint8_t>((x << n) | (x >> (8u - n)));
}
static inline uint8_t aes_sbox(uint8_t x) {
    const uint8_t s = aes_gf_inv(x);
    return static_cast<uint8_t>(s ^ aes_rotl8(s, 1) ^ aes_rotl8(s, 2) ^ aes_rotl8(s, 3) ^ aes_rotl8(s, 4) ^ 0x63u);
}
static inline uint8_t aes_inv_sbox(uint8_t x) {
    return aes_gf_inv(static_cast<uint8_t>(aes_rotl8(x, 1) ^ aes_rotl8(x, 3) ^ aes_rotl8(x, 6) ^ 0x05u));
}
static inline void aes_mix_columns(uint8_t s[16], bool inv) {
    for (size_t c = 0; c < 16; c += 4) {
        const uint8_t a0 = s[c], a1 = s[c+1], a2 = s[c+2], a3 = s[c+3];
        if (!inv) {
            s[c]   = static_cast<uint8_t>(aes_gf_mul(a0, 2) ^ aes_gf_mul(a1, 3) ^ a2 ^ a3);
            s[c+1] = static_cast<uint8_t>(a0 ^ aes_gf_mul(a1, 2) ^ aes_gf_mul(a2, 3) ^ a3);
            s[c+2] = static_cast<uint8_t>(a0 ^ a1 ^ aes_gf_mul(a2, 2) ^ aes_gf_mul(a3, 3));
            s[c+3] = static_cast<uint8_t>(aes_gf_mul(a0, 3) ^ a1 ^ a2 ^ aes_gf_mul(a3, 2));
        } else {
            s[c]   = static_cast<uint8_t>(aes_gf_mul(a0, 14) ^ aes_gf_mul(a1, 11) ^ aes_gf_mul(a2, 13) ^ aes_gf_mul(a3, 9));
            s[c+1] = static_cast<uint8_t>(aes_gf_mul(a0, 9)  ^ aes_gf_mul(a1, 14) ^ aes_gf_mul(a2, 11) ^ aes_gf_mul(a3, 13));
            s[c+2] = static_cast<uint8_t>(aes_gf_mul(a0, 13) ^ aes_gf_mul(a1, 9)  ^ aes_gf_mul(a2, 14) ^ aes_gf_mul(a3, 11));
            s[c+3] = static_cast<uint8_t>(aes_gf_mul(a0, 11) ^ aes_gf_mul(a1, 13) ^ aes_gf_mul(a2, 9)  ^ aes_gf_mul(a3, 14));
        }
    }
}
static inline void aes_round(uint8_t out[16], const uint8_t state[16], const uint8_t key[16], bool dec, bool last) {
    static constexpr uint8_t sr[16]  = {0,5,10,15, 4,9,14,3, 8,13,2,7, 12,1,6,11};
    static constexpr uint8_t isr[16] = {0,13,10,7, 4,1,14,11, 8,5,2,15, 12,9,6,3};
    for (size_t i = 0; i < 16; ++i) out[i] = dec ? aes_inv_sbox(state[isr[i]]) : aes_sbox(state[sr[i]]);
    if (!last) aes_mix_columns(out, dec);
    for (size_t i = 0; i < 16; ++i) out[i] ^= key[i];
}
static inline void aes_keygen(uint8_t out[16], const uint8_t src[16], uint8_t rcon) {
    auto subw = [](const uint8_t p[4]) -> uint32_t {
        return uint32_t(aes_sbox(p[0])) | (uint32_t(aes_sbox(p[1])) << 8)
             | (uint32_t(aes_sbox(p[2])) << 16) | (uint32_t(aes_sbox(p[3])) << 24);
    };
    const uint32_t w1 = subw(src + 4), w3 = subw(src + 12);
    const uint32_t r[4] = {w1, ((w1 >> 8) | (w1 << 24)) ^ rcon, w3, ((w3 >> 8) | (w3 << 24)) ^ rcon};
    memcpy(out, r, 16);
}
static inline void pclmul_x86(uint8_t out[16], const uint8_t lhs[16], const uint8_t rhs[16], uint8_t imm) {
    uint64_t a, b, lo = 0, hi = 0;
    memcpy(&a, lhs + ((imm & 0x01u) ? 8 : 0), 8);
    memcpy(&b, rhs + ((imm & 0x10u) ? 8 : 0), 8);
    for (unsigned k = 0; k < 64u; ++k) {
        if ((b >> k) & 1ull) { lo ^= (a << k); if (k > 0u) hi ^= (a >> (64u - k)); }
    }
    memcpy(out, &lo, 8); memcpy(out + 8, &hi, 8);
static inline uint32_t sha_rol32(uint32_t x, unsigned n) { return (x << n) | (x >> (32u - n)); }
static inline uint32_t sha_ror32(uint32_t x, unsigned n) { return (x >> n) | (x << (32u - n)); }
static inline void sha1_rnds4(uint32_t d[4], const uint32_t s[4], unsigned func) {
    uint32_t a = d[3], b = d[2], c = d[1], dv = d[0], e = 0;
    const uint32_t w[4] = {s[3], s[2], s[1], s[0]};
    const uint32_t k = func == 0 ? 0x5a827999u : (func == 1 ? 0x6ed9eba1u : (func == 2 ? 0x8f1bbcdcu : 0xca62c1d6u));
    for (int i = 0; i < 4; ++i) {
        const uint32_t f = func == 0 ? ((b & c) ^ (~b & dv))
                         : (func == 2 ? ((b & c) ^ (b & dv) ^ (c & dv)) : (b ^ c ^ dv));
        const uint32_t t = f + sha_rol32(a, 5) + w[i] + k + e;
        e = dv; dv = c; c = sha_rol32(b, 30); b = a; a = t;
    }
    d[3] = a; d[2] = b; d[1] = c; d[0] = dv;
}
static inline void sha256_rnds2(uint32_t d[4], const uint32_t s[4], const uint32_t wk[4]) {
    uint32_t a = s[3], b = s[2], c = d[3], dv = d[2], e = s[1], f = s[0], g = d[1], h = d[0];
    for (int i = 0; i < 2; ++i) {
        const uint32_t ch = (e & f) ^ (~e & g);
        const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        const uint32_t s0 = sha_ror32(a, 2) ^ sha_ror32(a, 13) ^ sha_ror32(a, 22);
        const uint32_t s1 = sha_ror32(e, 6) ^ sha_ror32(e, 11) ^ sha_ror32(e, 25);
        const uint32_t t1 = ch + s1 + wk[i] + h;
        const uint32_t na = t1 + maj + s0, ne = t1 + dv;
        h = g; g = f; f = e; e = ne; dv = c; c = b; b = a; a = na;
    }
    d[3] = a; d[2] = b; d[1] = e; d[0] = f;
}
"""
HEADER = INTEGER_HEADER + "struct Query { word type, next, effect, device, count, ids, names; };\n"


def reg(number):
    return REGS[RegisterExt.full_register(number)]


def region(pe, start, end):
    ins = list(Decoder(64, image_bytes(pe, start, end-start, executable=True), ip=start))
    if not ins or ins[-1].next_ip != end or any(i.is_invalid for i in ins):
        raise ValueError("query interval does not end on an instruction boundary")
    return ins


def string_op(i):
    """One element per iteration in program order, so overlapping copies replicate as on the hardware."""
    kind, size = STRING_OPS[i.code]
    if any(i.op_kind(n) not in (K.REGISTER, K.MEMORY_ESRDI, K.MEMORY_SEG_RSI) for n in range(i.op_count)):
        # A 67h prefix walks ESI, EDI and ECX instead of the full registers.
        raise ValueError(f"unsupported string address size at {i.ip:#x}: {i}")
    if kind in ("scas", "cmps"):
        repeat = "repe" if i.has_repe_prefix else "repne" if i.has_repne_prefix else None
    elif i.has_repne_prefix:
        raise ValueError(f"unsupported REPNE string prefix at {i.ip:#x}: {i}")
    else:
        repeat = "rep" if i.has_rep_prefix else None
    t = UINT[size]
    if kind == "movs":
        step = f"store<{t}>(rdi, load<{t}>(rsi)); rsi += step; rdi += step;"
    elif kind == "stos":
        step = f"store<{t}>(rdi, static_cast<{t}>(rax)); rdi += step;"
    elif kind == "lods":
        # AL and AX merge into RAX; a 32-bit load zero-extends.
        value = f"(rax & ~{(1 << (8*size)) - 1}ull) | load<{t}>(rsi)" if size < 4 else f"load<{t}>(rsi)"
        step = f"rax = {value}; rsi += step;"
    else:
        lhs = f"static_cast<{t}>(rax)" if kind == "scas" else f"load<{t}>(rsi)"
        advance = "rdi += step;" if kind == "scas" else "rsi += step; rdi += step;"
        step = f"{{ const {t} a = {lhs}, b = load<{t}>(rdi); zero = a == b; carry = a < b; }} {advance}"
    stop = {"repe": " if (!zero) break;", "repne": " if (zero) break;"}.get(repeat, "")
    # A zero count performs no iteration and leaves the pointers and flags unchanged.
    body = f"while (rcx != 0) {{ {step} --rcx;{stop} }}" if repeat else step
    return f"{{ const word step = direction ? 0ull - {size}ull : {size}ull; {body} }}"


def lower(body, initial, globals_, calls, exits, *, host_ops=None, x87=False):
    """Emit only query integer operations. All external edges and calls need named bindings."""
    lines = ["word frame[16]{};", "word " + ", ".join(r + "=0" for r in REGS.values()) + ";",
             "bool zero=false, carry=false, overflow=false;", "rsp = reinterpret_cast<word>(frame);", *initial]
    allowed = {i.ip for i in body} | set(exits)
    # The x87 profile checks every x87 instruction of the body before any of it is lowered.
    x87_depth = x87_lower.depths(body, exits) if x87 and any(map(x87_lower.is_x87, body)) else None
    xmm = {R.XMM0: "xmm0", R.XMM1: "xmm1", R.XMM2: "xmm2"}
    has_xmm_math = any(i.mnemonic in (M.VMOVDQU, M.VPSRLDQ, M.VMOVD)
                       or (i.mnemonic == M.VPADDD and i.op2_kind != K.MEMORY) for i in body)
    if has_xmm_math:
        lines.append("__m128i xmm0{}, xmm1{}, xmm2{};")
    # Unaligned YMM copies and VEX zeroing in the descriptor builder need
    # only byte storage on the desktop host.
    wide = {R.YMM0: "wide0", R.YMM1: "wide1", R.YMM2: "wide2"}
    has_wide = any(i.mnemonic == M.VMOVUPS for i in body)
    if any(i.code in STRING_OPS or i.mnemonic in (M.CLD, M.STD) for i in body):
        # The x64 software conventions expect DF clear on function exit and before calls, so it starts clear.
        lines.append("bool direction=false;")
    wide_any = {**wide, R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
    avx2_wide_ops = (M.VPBROADCASTB, M.VPBROADCASTW, M.VPBROADCASTD, M.VPBROADCASTQ,
                     M.VPSLLVD, M.VPSRLVD, M.VPSRAVD, M.VPSLLVQ, M.VPSRLVQ)
    has_wide = has_wide or any(i.mnemonic == M.VMOVUPS or i.mnemonic in avx2_wide_ops for i in body)
    avx2_perm_ops = (M.VBROADCASTI128, M.VEXTRACTI128, M.VINSERTI128, M.VPBLENDD,
                     M.VPERM2I128, M.VPERMD, M.VPERMPS, M.VPERMQ, M.VPERMPD)
    has_wide = has_wide or any(i.mnemonic == M.VMOVUPS or i.mnemonic in avx2_perm_ops for i in body)
    fma_scalar = {
        getattr(M, f"VF{k.upper()}{o}{s.upper()}"): (k, o, s == "sd")
        for k in ("madd", "msub", "nmadd", "nmsub") for o in ("132", "213", "231") for s in ("ss", "sd")
    }
    has_wide = has_wide or any(i.mnemonic == M.VMOVUPS or i.mnemonic in fma_scalar for i in body)
    fma_packed = {
        getattr(M, f"VF{k.upper()}{o}{s.upper()}"): (k, o, s == "pd")
        for k in ("madd", "msub", "nmadd", "nmsub", "maddsub", "msubadd") for o in ("132", "213", "231") for s in ("ps", "pd")
    }
    has_wide = has_wide or any(i.mnemonic == M.VMOVUPS or i.mnemonic in fma_packed for i in body)
    wide_xmm = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
    ssse3_ops = (M.MOVDQU, M.PABSB, M.PABSW, M.PABSD, M.PSIGNB, M.PSIGNW, M.PSIGND,
                 M.PSHUFB, M.PALIGNR, M.PHADDW, M.PHADDD, M.PHSUBW, M.PHSUBD, M.PHADDSW, M.PHSUBSW)
    has_wide = has_wide or any(i.mnemonic == M.VMOVUPS or i.mnemonic in ssse3_ops for i in body)
    wide_xmm = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
    sse2_int_ops = {
        M.PADDB, M.PADDW, M.PADDD, M.PADDQ, M.PSUBB, M.PSUBW, M.PSUBD, M.PSUBQ,
        M.PAND, M.PANDN, M.POR, M.PXOR,
        M.PCMPEQB, M.PCMPEQW, M.PCMPEQD, M.PCMPGTB, M.PCMPGTW, M.PCMPGTD,
    }
    has_wide = has_wide or any(i.mnemonic == M.VMOVUPS or i.mnemonic == M.MOVDQU or i.mnemonic in sse2_int_ops for i in body)
    wide_xmm = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
    sse2_shift_pack_ops = {
        M.PSLLW, M.PSLLD, M.PSLLQ, M.PSRLW, M.PSRLD, M.PSRLQ, M.PSRAW, M.PSRAD, M.PSLLDQ, M.PSRLDQ,
        M.PACKSSWB, M.PACKSSDW, M.PACKUSWB,
        M.PUNPCKLBW, M.PUNPCKLWD, M.PUNPCKLDQ, M.PUNPCKLQDQ,
        M.PUNPCKHBW, M.PUNPCKHWD, M.PUNPCKHDQ, M.PUNPCKHQDQ,
        M.PSHUFD, M.PSHUFLW, M.PSHUFHW, M.PMOVMSKB,
    }
    has_wide = has_wide or any(i.mnemonic == M.VMOVUPS or i.mnemonic == M.MOVDQU or i.mnemonic in sse2_shift_pack_ops for i in body)
    wide_xmm = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
    crypto_legacy_ops = {M.AESENC, M.AESENCLAST, M.AESDEC, M.AESDECLAST, M.AESIMC, M.AESKEYGENASSIST, M.PCLMULQDQ}
    crypto_vex_ops = {M.VAESENC, M.VAESENCLAST, M.VAESDEC, M.VAESDECLAST, M.VAESIMC, M.VAESKEYGENASSIST, M.VPCLMULQDQ}
    has_wide = has_wide or any(i.mnemonic in (M.VMOVUPS, M.MOVDQU) or i.mnemonic in crypto_legacy_ops or i.mnemonic in crypto_vex_ops for i in body)
    wide_xmm = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
    sha_ops = {M.SHA1MSG1, M.SHA1MSG2, M.SHA1NEXTE, M.SHA1RNDS4, M.SHA256MSG1, M.SHA256MSG2, M.SHA256RNDS2}
    has_wide = has_wide or any(i.mnemonic in (M.VMOVUPS, M.MOVDQU) or i.mnemonic in sha_ops for i in body)
    wide_xmm = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
    wide_any = {**wide, **wide_xmm}
    avx_fp_ops = {
        M.VMOVUPD,
        M.VADDPS, M.VSUBPS, M.VMULPS, M.VDIVPS, M.VSQRTPS, M.VMINPS, M.VMAXPS,
        M.VANDPS, M.VANDNPS, M.VORPS, M.VXORPS, M.VADDSUBPS, M.VHADDPS, M.VHSUBPS, M.VMOVMSKPS,
        M.VADDPD, M.VSUBPD, M.VMULPD, M.VDIVPD, M.VSQRTPD, M.VMINPD, M.VMAXPD,
        M.VANDPD, M.VANDNPD, M.VORPD, M.VXORPD, M.VADDSUBPD, M.VHADDPD, M.VHSUBPD, M.VMOVMSKPD,
    }
    has_wide = has_wide or any(i.mnemonic == M.VMOVUPS or i.mnemonic in avx_fp_ops for i in body)
    wide_xmm = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
    sse41_ops = (M.MOVDQU, M.PMINSB, M.PMAXSB, M.PMINUW, M.PMAXUW, M.PMINSD, M.PMAXSD,
                 M.PMINUD, M.PMAXUD, M.PMULLD, M.PMULDQ, M.PCMPEQQ, M.PACKUSDW, M.PBLENDW, M.PBLENDVB)
    has_wide = has_wide or any(i.mnemonic == M.VMOVUPS or i.mnemonic in sse41_ops for i in body)
    if has_wide:
        if has_xmm_math:
            raise ValueError("mixed vector arithmetic and wide descriptor copies are unsupported")
        lines.append("std::array<uint8_t,32> wide0{}, wide1{}, wide2{};")
    for index, i in enumerate(body):
        op = i.mnemonic

        def address():
            if i.is_ip_rel_memory_operand:
                if i.memory_base == R.EIP:
                    # The hardware adds the low 32 bits of the runtime RIP; an RVA binding cannot model that.
                    raise ValueError(f"unsupported EIP-relative operand at {i.ip:#x}: {i}")
                return globals_[i.ip_rel_memory_address]
            terms = []
            addr32 = False
            if i.memory_base != R.NONE:
                addr32 |= RegisterExt.size(i.memory_base) == 4
                terms.append(reg(i.memory_base))
            if i.memory_index != R.NONE:
                addr32 |= RegisterExt.size(i.memory_index) == 4
                terms.append(f"{reg(i.memory_index)} * {i.memory_index_scale}ull")
            terms.append(f"{i.memory_displacement}ull")
            expr = " + ".join(terms)
            return f"static_cast<uint32_t>({expr})" if addr32 else expr

        def operand(n):
            kind = i.op_kind(n)
            if kind == K.REGISTER:
                register = i.op_register(n)
                if register in HIGH_BYTE:
                    return f"static_cast<uint8_t>({reg(register)} >> 8)"
                return f"static_cast<{UINT[RegisterExt.size(register)]}>({reg(register)})"
            if kind == K.MEMORY:
                return f"load<{UINT[MemorySizeExt.size(i.memory_size)]}>({address()})"
            return f"{i.immediate(n)}ull"

        def write(expr):
            if i.op0_kind == K.MEMORY:
                return f"store<{UINT[MemorySizeExt.size(i.memory_size)]}>({address()}, {expr});"
            return write_register(i.op0_register, expr)

        def write_register(dest, expr):
            if dest in HIGH_BYTE:
                return f"{reg(dest)} = ({reg(dest)} & ~0xff00ull) | (static_cast<word>(static_cast<uint8_t>({expr})) << 8);"
            size = RegisterExt.size(dest)
            value = f"static_cast<{UINT[size]}>({expr})"
            if size < 4:
                value = f"({reg(dest)} & ~{(1 << (8*size))-1}ull) | {value}"
            return f"{reg(dest)} = {value};"

        if host_ops and i.ip in host_ops:
            stmt = host_ops[i.ip]
        elif i.segment_prefix in (R.FS, R.GS) or i.has_lock_prefix:
            # FS/GS select a thread block base and LOCK makes the access atomic;
            # the flat loads and stores below would silently drop both.
            raise ValueError(f"unsupported instruction prefix at {i.ip:#x}: {i}")
        elif i.code in STRING_OPS:
            stmt = string_op(i)
        elif op == M.CLD:
            stmt = "direction = false;"
        elif op == M.STD:
            stmt = "direction = true;"
        elif op in (M.JE, M.JNE, M.JAE, M.JA, M.JB, M.JBE, M.JMP):
            target = i.near_branch_target
            if target not in allowed:
                raise ValueError(f"unbound branch at {i.ip:#x}")
            cond = {M.JE: "if (zero) ", M.JNE: "if (!zero) ", M.JAE: "if (!carry) ",
                    M.JA: "if (!carry && !zero) ", M.JB: "if (carry) ", M.JBE: "if (carry || zero) ", M.JMP: ""}[op]
            stmt = f"{cond}goto block_{target:x};"
        elif op in (M.LOOP, M.LOOPE, M.LOOPNE, M.JRCXZ, M.JECXZ):
            # RCX-counted branches. A 67h prefix selects ECX (loopd, jecxz). None of them changes a flag;
            # LOOPE and LOOPNE test ZF after the decrement.
            target = i.near_branch_target
            if target not in allowed:
                raise ValueError(f"unbound branch at {i.ip:#x}")
            ecx = i.code in (C.LOOP_REL8_64_ECX, C.LOOPE_REL8_64_ECX, C.LOOPNE_REL8_64_ECX, C.JECXZ_REL8_64)
            count = "static_cast<uint32_t>(rcx)" if ecx else "rcx"
            if op in (M.JRCXZ, M.JECXZ):
                stmt = f"if ({count} == 0) goto block_{target:x};"
            else:
                decrement = "rcx = static_cast<uint32_t>(rcx - 1);" if ecx else "--rcx;"
                condition = {M.LOOP: "", M.LOOPE: " && zero", M.LOOPNE: " && !zero"}[op]
                stmt = f"{decrement} if ({count} != 0{condition}) goto block_{target:x};"
        elif op in (M.MOV, M.MOVZX):
            stmt = write(operand(1))
        elif op == M.MOVSXD:
            stmt = write(f"int64_t(int32_t({operand(1)}))")
        elif op == M.MOVSX:
            src_bits = 8 * (MemorySizeExt.size(i.memory_size) if i.op1_kind == K.MEMORY else RegisterExt.size(i.op1_register))
            dst_bits = 8 * RegisterExt.size(i.op0_register)
            stmt = write(f"static_cast<int{dst_bits}_t>(static_cast<int{src_bits}_t>({operand(1)}))")
        elif op == M.CMOVNE:
            stmt = write(f"zero ? {operand(0)} : {operand(1)}")
        elif op == M.CMOVE:
            stmt = write(f"zero ? {operand(1)} : {operand(0)}")
        elif op == M.CMOVBE:
            stmt = write(f"(carry || zero) ? {operand(1)} : {operand(0)}")
        elif op in (M.CMOVE, M.CMOVNE, M.CMOVA, M.CMOVAE, M.CMOVB, M.CMOVBE):
            cond = {M.CMOVE: "zero", M.CMOVNE: "!zero", M.CMOVA: "!carry && !zero",
                    M.CMOVAE: "!carry", M.CMOVB: "carry", M.CMOVBE: "carry || zero"}[op]
            if i.op1_kind == K.MEMORY:
                width = UINT[MemorySizeExt.size(i.memory_size)]
                stmt = f"{{ const {width} src = load_always<{width}>({address()}); {write(f'({cond}) ? src : {operand(0)}')} }}"
            else:
                stmt = write(f"({cond}) ? {operand(1)} : {operand(0)}")
        elif op == M.LEA:
            stmt = write(address())
        elif op == M.MOVBE:
            # One operand is memory and the other a register of the same width; the bytes are reversed in
            # either direction, no flag changes, and a 16-bit register destination keeps its upper bits.
            width = UINT[MemorySizeExt.size(i.memory_size)]
            stmt = (f"{{ const {width} a = {operand(1)}; {width} v = 0; "
                    f"for (unsigned k = 0; k < sizeof v; ++k) v = static_cast<{width}>((v << 8) | ((a >> (8 * k)) & 0xffu)); "
                    f"{write('v')} }}")
        elif op == M.CMP:
            # Sign-extended immediates arrive as 64-bit values; compare at the destination width.
            size = MemorySizeExt.size(i.memory_size) if i.op0_kind == K.MEMORY else RegisterExt.size(i.op0_register)
            width = UINT[size]
            stmt = (f"{{ const {width} a = {operand(0)}, b = static_cast<{width}>({operand(1)}), "
                    f"d = static_cast<{width}>(a - b); "
                    f"zero = a == b; carry = a < b; overflow = (((a ^ b) & (a ^ d)) >> {8 * size - 1}) != 0; }}")
        elif op == M.TEST:
            stmt = f"zero = (({operand(0)} & {operand(1)}) == 0); carry = false; overflow = false;"
        elif op == M.IMUL and i.op_count in (2, 3) and RegisterExt.size(i.op0_register) == 4:
            lhs, rhs = operand(i.op_count - 2), operand(i.op_count - 1)
            stmt = (f"{{ const int64_t product = int64_t(int32_t({lhs})) * int32_t({rhs}); "
                    f"carry = product != int32_t(product); overflow = carry; {write('product')} }}")
        elif op == M.CDQ:
            stmt = "rdx = uint32_t(int32_t(rax) >> 31);"
        elif op == M.CBW:
            stmt = "rax = (rax & ~0xffffull) | static_cast<uint16_t>(static_cast<int16_t>(static_cast<int8_t>(rax)));"
        elif op == M.CWDE:
            stmt = "rax = static_cast<uint32_t>(static_cast<int32_t>(static_cast<int16_t>(rax)));"
        elif op == M.CDQE:
            stmt = "rax = static_cast<uint64_t>(static_cast<int64_t>(static_cast<int32_t>(rax)));"
        elif op == M.CQO:
            stmt = "rdx = static_cast<uint64_t>(static_cast<int64_t>(rax) >> 63);"
        elif op in (M.SHL, M.SHR, M.SAR) and i.op1_kind == K.IMMEDIATE8 and RegisterExt.size(i.op0_register) in (4, 8):
            size = RegisterExt.size(i.op0_register)
            bits = 8 * size
            count = i.immediate(1) & (bits - 1)
            shift, last = ("<<", bits-count) if op == M.SHL else (">>", count-1)
            lhs = f"int{bits}_t(a)" if op == M.SAR else "a"
            of_update = ""
            if count == 1:
                if op == M.SHL:
                    of_update = f" overflow = (((v >> {bits - 1}) & 1) != 0) != carry;"
                elif op == M.SHR:
                    of_update = f" overflow = ((a >> {bits - 1}) & 1) != 0;"
                else:
                    of_update = " overflow = false;"
            stmt = (f"{{ const {UINT[size]} a = {operand(0)}, v = {lhs} {shift} {count}; "
                    f"carry = ((a >> {last}) & 1) != 0;{of_update} zero = v == 0; {write('v')} }}") if count else \
                write(operand(0))  # A masked zero count keeps the flags but still zero-extends a 32-bit destination.
        elif op in (M.RCL, M.RCR):
            # The 9-, 17-, 33- or 65-bit rotation through CF, one bit per step as in the SDM pseudocode.
            # Counts mask to five bits (six for 64-bit). Reducing 8- and 16-bit counts modulo 9 and 17 only
            # bounds the loop, since those rotations repeat with that period.
            # A zero step count keeps CF; ZF is never affected. OF (count 1) is not modelled here.
            size = MemorySizeExt.size(i.memory_size) if i.op0_kind == K.MEMORY else RegisterExt.size(i.op0_register)
            width, bits = UINT[size], 8 * size
            count = f"(static_cast<unsigned>({operand(1)}) & {0x3f if size == 8 else 0x1f}u)"
            if size < 4:
                count = f"({count} % {bits + 1}u)"
            if op == M.RCL:
                step = (f"const bool out = ((v >> {bits - 1}) & 1) != 0; "
                        f"v = static_cast<{width}>((v << 1) | {width}(c));")
            else:
                step = (f"const bool out = (v & 1) != 0; "
                        f"v = static_cast<{width}>((v >> 1) | ({width}(c) << {bits - 1}));")
            stmt = (f"{{ {width} v = {operand(0)}; bool c = carry; "
                    f"for (unsigned n = {count}; n != 0; --n) {{ {step} c = out; }} carry = c; {write('v')} }}")
        elif op == M.CLC:
            stmt = "carry = false;"
        elif op == M.STC:
            stmt = "carry = true;"
        elif op == M.CMC:
            stmt = "carry = !carry;"
        elif op in (M.ADD, M.ADC, M.AND, M.OR, M.XOR, M.INC, M.DEC, M.SUB, M.SBB):
            operator = {M.ADD: "+", M.ADC: "+", M.INC: "+", M.DEC: "-", M.AND: "&", M.OR: "|", M.XOR: "^", M.SUB: "-", M.SBB: "-"}[op]
            rhs = "1" if op in (M.INC, M.DEC) else operand(1)
            width = UINT[MemorySizeExt.size(i.memory_size) if i.op0_kind == K.MEMORY else RegisterExt.size(i.op0_register)]
            expr = f"a {operator} b" + (" + word(carry)" if op == M.ADC else " - word(carry)" if op == M.SBB else "")
            update = {M.ADD: "carry = v < a;", M.ADC: "carry = v < a || (carry && v == a);",
                      M.SUB: "carry = a < b;", M.SBB: "carry = a < b || (carry && a == b);",
                      M.INC: "", M.DEC: "", M.XOR: "carry = false;", M.AND: "carry = false;", M.OR: "carry = false;"}[op]
            size = MemorySizeExt.size(i.memory_size) if i.op0_kind == K.MEMORY else RegisterExt.size(i.op0_register)
            width = UINT[size]
            sign_shift = 8 * size - 1
            expr = f"a {operator} b" + (" - word(carry)" if op == M.SBB else "")
            update = {
                M.ADD: f"carry = v < a; overflow = (((~(a ^ b)) & (a ^ v)) >> {sign_shift}) != 0;",
                M.SUB: f"carry = a < b; overflow = (((a ^ b) & (a ^ v)) >> {sign_shift}) != 0;",
                M.SBB: f"carry = a < b || (carry && a == b); overflow = (((a ^ b) & (a ^ v)) >> {sign_shift}) != 0;",
                M.INC: f"overflow = (((~(a ^ b)) & (a ^ v)) >> {sign_shift}) != 0;",
                M.DEC: f"overflow = (((a ^ b) & (a ^ v)) >> {sign_shift}) != 0;",
                M.XOR: "carry = false; overflow = false;",
                M.AND: "carry = false; overflow = false;",
                M.OR: "carry = false; overflow = false;",
            }[op]
            stmt = (f"{{ const {width} a = {operand(0)}, b = static_cast<{width}>({rhs}); "
                    f"const {width} v = static_cast<{width}>({expr}); {update} zero = v == 0; {write('v')} }}")
        elif op in (M.ADCX, M.ADOX) and RegisterExt.size(i.op0_register) in (4, 8):
            width = UINT[RegisterExt.size(i.op0_register)]
            flag = "carry" if op == M.ADCX else "overflow"
            stmt = (f"{{ const {width} a = {operand(0)}, b = {operand(1)}, "
                    f"v = static_cast<{width}>(a + b + static_cast<{width}>({flag})); "
                    f"{flag} = v < a || ({flag} && v == a); {write('v')} }}")
        elif op in (M.ANDN, M.BEXTR, M.BLSI, M.BLSMSK, M.BLSR, M.TZCNT) and RegisterExt.size(i.op0_register) in (4, 8):
            size = RegisterExt.size(i.op0_register)
            width, bits = UINT[size], 8 * size
            if op == M.ANDN:
                stmt = (f"{{ const {width} v = static_cast<{width}>(~static_cast<{width}>({operand(1)}) "
                        f"& static_cast<{width}>({operand(2)})); carry = false; overflow = false; zero = v == 0; {write('v')} }}")
            elif op == M.BEXTR:
                stmt = (f"{{ const {width} a = {operand(1)}, ctrl = {operand(2)}; "
                        f"const unsigned start = static_cast<unsigned>(ctrl & 0xffu), "
                        f"len = static_cast<unsigned>((ctrl >> 8) & 0xffu); "
                        f"{width} v = 0; if (start < {bits}u && len > 0u) {{ "
                        f"const {width} s = a >> start; "
                        f"v = len >= {bits}u ? s : static_cast<{width}>(s & ((static_cast<{width}>(1) << len) - 1)); }} "
                        f"carry = false; overflow = false; zero = v == 0; {write('v')} }}")
            elif op == M.BLSI:
                stmt = (f"{{ const {width} a = {operand(1)}, v = static_cast<{width}>(a & (static_cast<{width}>(0) - a)); "
                        f"carry = a != 0; overflow = false; zero = v == 0; {write('v')} }}")
            elif op == M.BLSMSK:
                stmt = (f"{{ const {width} a = {operand(1)}, v = static_cast<{width}>(a ^ (a - 1)); "
                        f"carry = a == 0; overflow = false; zero = false; {write('v')} }}")
            elif op == M.BLSR:
                stmt = (f"{{ const {width} a = {operand(1)}, v = static_cast<{width}>(a & (a - 1)); "
                        f"carry = a == 0; overflow = false; zero = v == 0; {write('v')} }}")
            else:  # M.TZCNT
                stmt = (f"{{ const {width} a = {operand(1)}; {width} v = 0; "
                        f"if (a == 0) {{ v = {bits}; }} else {{ while (((a >> v) & 1) == 0) ++v; }} "
                        f"carry = a == 0; zero = v == 0; {write('v')} }}")
        elif (op in (M.ROL, M.ROR) and i.op0_kind == K.REGISTER and RegisterExt.size(i.op0_register) in (4, 8)
              and (i.op1_kind == K.IMMEDIATE8 or i.op1_register == R.CL)):
            size = RegisterExt.size(i.op0_register)
            width, bits = UINT[size], 8 * size
            if i.op1_kind == K.IMMEDIATE8 and (i.immediate(1) & (bits - 1)) == 0:
                stmt = write(operand(0))
            else:
                count_expr = f"{i.immediate(1) & (bits - 1)}u" if i.op1_kind == K.IMMEDIATE8 else f"static_cast<unsigned>(rcx) & {bits - 1}u"
                if op == M.ROL:
                    stmt = (f"{{ const {width} a = {operand(0)}; const unsigned c = {count_expr}; "
                            f"{width} v = a; if (c != 0u) {{ v = static_cast<{width}>((a << c) | (a >> ({bits}u - c))); "
                            f"carry = (v & 1u) != 0; }} {write('v')} }}")
                else:  # M.ROR
                    stmt = (f"{{ const {width} a = {operand(0)}; const unsigned c = {count_expr}; "
                            f"{width} v = a; if (c != 0u) {{ v = static_cast<{width}>((a >> c) | (a << ({bits}u - c))); "
                            f"carry = ((v >> {bits - 1}u) & 1u) != 0; }} {write('v')} }}")
        elif (op in (M.SHLD, M.SHRD) and i.op0_kind == K.REGISTER and RegisterExt.size(i.op0_register) in (4, 8)
              and (i.op2_kind == K.IMMEDIATE8 or i.op2_register == R.CL)):
            size = RegisterExt.size(i.op0_register)
            width, bits = UINT[size], 8 * size
            if i.op2_kind == K.IMMEDIATE8 and (i.immediate(2) & (bits - 1)) == 0:
                stmt = write(operand(0))
            else:
                count_expr = f"{i.immediate(2) & (bits - 1)}u" if i.op2_kind == K.IMMEDIATE8 else f"static_cast<unsigned>(rcx) & {bits - 1}u"
                if op == M.SHLD:
                    stmt = (f"{{ const {width} a = {operand(0)}, b = {operand(1)}; const unsigned c = {count_expr}; "
                            f"{width} v = a; if (c != 0u) {{ v = static_cast<{width}>((a << c) | (b >> ({bits}u - c))); "
                            f"carry = ((a >> ({bits}u - c)) & 1u) != 0; zero = v == 0; }} {write('v')} }}")
                else:  # M.SHRD
                    stmt = (f"{{ const {width} a = {operand(0)}, b = {operand(1)}; const unsigned c = {count_expr}; "
                            f"{width} v = a; if (c != 0u) {{ v = static_cast<{width}>((a >> c) | (b << ({bits}u - c))); "
                            f"carry = ((a >> (c - 1u)) & 1u) != 0; zero = v == 0; }} {write('v')} }}")
        elif op in (M.BSF, M.BSR, M.POPCNT, M.LZCNT) and RegisterExt.size(i.op0_register) in (4, 8):
            size = RegisterExt.size(i.op0_register)
            width, bits = UINT[size], 8 * size
            if op == M.BSF:
                stmt = (f"{{ const {width} a = {operand(1)}; zero = a == 0; if (a != 0) {{ "
                        f"{width} v = 0; while (((a >> v) & 1) == 0) ++v; {write('v')} }} }}")
            elif op == M.BSR:
                stmt = (f"{{ const {width} a = {operand(1)}; zero = a == 0; if (a != 0) {{ "
                        f"{width} v = {bits - 1}; while (((a >> v) & 1) == 0) --v; {write('v')} }} }}")
            elif op == M.POPCNT:
                stmt = (f"{{ {width} a = {operand(1)}, v = 0; while (a != 0) {{ a &= a - 1; ++v; }} "
                        f"carry = false; zero = v == 0; {write('v')} }}")
            else:  # M.LZCNT
                stmt = (f"{{ const {width} a = {operand(1)}; {width} v = 0; "
                        f"if (a == 0) {{ v = {bits}; }} else {{ while (((a >> ({bits - 1} - v)) & 1) == 0) ++v; }} "
                        f"carry = a == 0; zero = v == 0; {write('v')} }}")
        elif op == M.BSWAP and RegisterExt.size(i.op0_register) in (4, 8):
            size = RegisterExt.size(i.op0_register)
            width = UINT[size]
            stmt = (f"{{ const {width} a = {operand(0)}; {width} v = 0; "
                    f"for (unsigned b = 0; b < {size}u; ++b) {{ v = (v << 8) | ((a >> (b * 8u)) & 0xffu); }} "
                    f"{write('v')} }}")
        elif op in (M.BT, M.BTS, M.BTR, M.BTC) and i.op0_kind == K.REGISTER and RegisterExt.size(i.op0_register) in (4, 8):
            size = RegisterExt.size(i.op0_register)
            width, bits = UINT[size], 8 * size
            bit_expr = f"static_cast<unsigned>({operand(1)}) & {bits - 1}u"
            if op == M.BT:
                stmt = f"{{ const {width} a = {operand(0)}; carry = ((a >> ({bit_expr})) & 1u) != 0; }}"
            else:
                mut = {M.BTS: "a | m", M.BTR: "a & static_cast<" + width + ">(~m)", M.BTC: "a ^ m"}[op]
                stmt = (f"{{ const {width} a = {operand(0)}; const unsigned b = {bit_expr}; "
                        f"const {width} m = static_cast<{width}>(1) << b; carry = (a & m) != 0; "
                        f"const {width} v = static_cast<{width}>({mut}); {write('v')} }}")
        elif op in (M.MUL, M.DIV, M.IDIV):
            size = MemorySizeExt.size(i.memory_size) if i.op0_kind == K.MEMORY else RegisterExt.size(i.op0_register)
            if size not in (4, 8):
                raise ValueError(f"unsupported query operation at {i.ip:#x}: {i}")
            if op == M.MUL:
                if size == 4:
                    stmt = (f"{{ const uint64_t p = static_cast<uint64_t>(static_cast<uint32_t>(rax)) * static_cast<uint32_t>({operand(0)}); "
                            f"rax = static_cast<uint32_t>(p); rdx = static_cast<uint32_t>(p >> 32); carry = rdx != 0; }}")
                else:
                    stmt = (f"{{ const uint64_t a = rax, b = {operand(0)}; "
                            f"const uint64_t a0 = static_cast<uint32_t>(a), a1 = a >> 32, b0 = static_cast<uint32_t>(b), b1 = b >> 32; "
                            f"const uint64_t p0 = a0 * b0, p1 = a0 * b1, p2 = a1 * b0, p3 = a1 * b1; "
                            f"const uint64_t mid = (p0 >> 32) + static_cast<uint32_t>(p1) + static_cast<uint32_t>(p2); "
                            f"rax = (p0 & 0xffffffffull) | (mid << 32); rdx = p3 + (p1 >> 32) + (p2 >> 32) + (mid >> 32); carry = rdx != 0; }}")
            elif op == M.DIV:
                if size == 4:
                    stmt = (f"{{ const uint32_t hi = static_cast<uint32_t>(rdx), den = {operand(0)}; "
                            f"if (den == 0u || hi >= den) raise_de(); "
                            f"const uint64_t num = (static_cast<uint64_t>(hi) << 32) | static_cast<uint32_t>(rax); "
                            f"rax = static_cast<uint32_t>(num / den); rdx = static_cast<uint32_t>(num % den); }}")
                else:
                    stmt = (f"{{ uint64_t hi = rdx, lo = rax, den = {operand(0)}, q = 0; "
                            f"if (den == 0ull || hi >= den) raise_de(); "
                            f"for (int b = 63; b >= 0; --b) {{ const bool top = (hi >> 63) != 0; "
                            f"hi = (hi << 1) | ((lo >> b) & 1u); if (top || hi >= den) {{ hi -= den; q |= 1ull << b; }} }} "
                            f"rax = q; rdx = hi; }}")
            else:  # M.IDIV
                if size == 4:
                    stmt = (f"{{ const int64_t num = static_cast<int64_t>((static_cast<uint64_t>(static_cast<uint32_t>(rdx)) << 32) | static_cast<uint32_t>(rax)); "
                            f"const int32_t den = static_cast<int32_t>({operand(0)}); "
                            f"if (den == 0 || (num == (-9223372036854775807ll - 1) && den == -1)) raise_de(); "
                            f"const int64_t q = num / den, r = num % den; "
                            f"if (q < -2147483648ll || q > 2147483647ll) raise_de(); "
                            f"rax = static_cast<uint32_t>(static_cast<int32_t>(q)); rdx = static_cast<uint32_t>(static_cast<int32_t>(r)); }}")
                else:
                    stmt = (f"{{ uint64_t hi = rdx, lo = rax, d = {operand(0)}; "
                            f"if (d == 0ull) raise_de(); "
                            f"const bool neg_n = (hi >> 63) != 0, neg_d = (d >> 63) != 0; "
                            f"if (neg_n) {{ lo = 0ull - lo; hi = ~hi + (lo == 0ull ? 1ull : 0ull); }} "
                            f"if (neg_d) {{ d = 0ull - d; }} "
                            f"if (hi >= d) raise_de(); "
                            f"uint64_t q = 0; "
                            f"for (int b = 63; b >= 0; --b) {{ const bool top = (hi >> 63) != 0; "
                            f"hi = (hi << 1) | ((lo >> b) & 1u); if (top || hi >= d) {{ hi -= d; q |= 1ull << b; }} }} "
                            f"const bool neg_q = neg_n != neg_d; "
                            f"if ((!neg_q && q > 0x7fffffffffffffffull) || (neg_q && q > 0x8000000000000000ull)) raise_de(); "
                            f"rax = neg_q ? (0ull - q) : q; rdx = neg_n ? (0ull - hi) : hi; }}")
        elif op in (M.XADD, M.CMPXCHG):
            size = MemorySizeExt.size(i.memory_size) if i.op0_kind == K.MEMORY else RegisterExt.size(i.op0_register)
            if size not in (4, 8):
                raise ValueError(f"unsupported query operation at {i.ip:#x}: {i}")
            width = UINT[size]
            if op == M.XADD:
                src_dst = reg(i.op1_register)
                if i.op0_kind == K.MEMORY:
                    stmt = (f"{{ const word addr = {address()}; const {width} a = load<{width}>(addr), b = {operand(1)}, "
                            f"v = static_cast<{width}>(a + b); carry = v < a; zero = v == 0; "
                            f"{src_dst} = a; store<{width}>(addr, v); }}")
                else:
                    stmt = (f"{{ const {width} a = {operand(0)}, b = {operand(1)}, v = static_cast<{width}>(a + b); "
                            f"carry = v < a; zero = v == 0; {src_dst} = a; {write('v')} }}")
            else:  # M.CMPXCHG
                if i.op0_kind == K.MEMORY:
                    stmt = (f"{{ const word addr = {address()}; const {width} acc = static_cast<{width}>(rax), "
                            f"d = load<{width}>(addr), s = {operand(1)}; zero = acc == d; carry = acc < d; "
                            f"if (zero) {{ store<{width}>(addr, s); }} else {{ rax = d; }} }}")
                else:
                    stmt = (f"{{ const {width} acc = static_cast<{width}>(rax), d = {operand(0)}, s = {operand(1)}; "
                            f"zero = acc == d; carry = acc < d; if (zero) {{ {write('s')} }} else {{ rax = d; }} }}")
        elif op in (M.BZHI, M.MULX, M.PDEP, M.PEXT, M.RORX, M.SARX, M.SHLX, M.SHRX) and RegisterExt.size(i.op0_register) in (4, 8):
            size = RegisterExt.size(i.op0_register)
            width, bits = UINT[size], 8 * size
            if op == M.BZHI:
                stmt = (f"{{ const {width} a = {operand(1)}; const unsigned n = static_cast<unsigned>({operand(2)} & 0xffu); "
                        f"const {width} v = n >= {bits}u ? a : static_cast<{width}>(a & ((static_cast<{width}>(1) << n) - 1)); "
                        f"carry = n >= {bits}u; zero = v == 0; {write('v')} }}")
            elif op == M.RORX:
                count = i.immediate(2) & (bits - 1)
                expr = "a" if count == 0 else f"static_cast<{width}>((a >> {count}) | (a << {bits - count}))"
                stmt = f"{{ const {width} a = {operand(1)}, v = {expr}; {write('v')} }}"
            elif op in (M.SHLX, M.SHRX, M.SARX):
                lhs = f"static_cast<int{bits}_t>(a)" if op == M.SARX else "a"
                shift = "<<" if op == M.SHLX else ">>"
                stmt = (f"{{ const {width} a = {operand(1)}; const unsigned c = static_cast<unsigned>({operand(2)}) & {bits - 1}u; "
                        f"const {width} v = static_cast<{width}>({lhs} {shift} c); {write('v')} }}")
            elif op == M.PDEP:
                stmt = (f"{{ const {width} src = {operand(1)}, mask = {operand(2)}; {width} v = 0; unsigned k = 0; "
                        f"for (unsigned b = 0; b < {bits}u; ++b) {{ if ((mask >> b) & 1u) {{ "
                        f"if ((src >> k) & 1u) v |= static_cast<{width}>(1) << b; ++k; }} }} {write('v')} }}")
            elif op == M.PEXT:
                stmt = (f"{{ const {width} src = {operand(1)}, mask = {operand(2)}; {width} v = 0; unsigned k = 0; "
                        f"for (unsigned b = 0; b < {bits}u; ++b) {{ if ((mask >> b) & 1u) {{ "
                        f"if ((src >> b) & 1u) v |= static_cast<{width}>(1) << k; ++k; }} }} {write('v')} }}")
            else:  # M.MULX
                lo_dst = reg(i.op1_register)
                if size == 4:
                    stmt = (f"{{ const uint64_t p = static_cast<uint64_t>(static_cast<uint32_t>(rdx)) * static_cast<uint32_t>({operand(2)}); "
                            f"const uint32_t lo = static_cast<uint32_t>(p), hi = static_cast<uint32_t>(p >> 32); "
                            f"{lo_dst} = lo; {write('hi')} }}")
                else:
                    stmt = (f"{{ const uint64_t a = rdx, b = {operand(2)}; "
                            f"const uint64_t a0 = static_cast<uint32_t>(a), a1 = a >> 32, b0 = static_cast<uint32_t>(b), b1 = b >> 32; "
                            f"const uint64_t p0 = a0 * b0, p1 = a0 * b1, p2 = a1 * b0, p3 = a1 * b1; "
                            f"const uint64_t mid = (p0 >> 32) + static_cast<uint32_t>(p1) + static_cast<uint32_t>(p2); "
                            f"const uint64_t lo = (p0 & 0xffffffffull) | (mid << 32), hi = p3 + (p1 >> 32) + (p2 >> 32) + (mid >> 32); "
                            f"{lo_dst} = lo; {write('hi')} }}")
        elif op in (M.VMOVQ, M.VMOVSD, M.VMOVHPD) and has_wide:
            lanes = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
            if i.op1_kind == K.MEMORY and op != M.VMOVHPD:
                dst = lanes[i.op0_register]
                stmt = f"{dst} = {{}}; memcpy({dst}.data(), reinterpret_cast<const void*>({address()}), 8);"
            elif i.op0_kind == K.MEMORY:
                start = 8 if op == M.VMOVHPD else 0
                stmt = f"memcpy(reinterpret_cast<void*>({address()}), {lanes[i.op1_register]}.data()+{start}, 8);"
            else:
                raise ValueError(f"unsupported vector move at {i.ip:#x}")
        elif has_wide and op in (M.VPADDD, M.VPSRLD):
            lanes = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}
            src, dst = lanes[i.op1_register], lanes[i.op0_register]
            operation = (f"+ load<uint32_t>(({address()}) + n)" if op == M.VPADDD
                         else f">> {i.immediate(2)}")
            if op == M.VPSRLD and i.immediate(2) >= 32:
                raise ValueError("unsupported packed shift count")
            stmt = (f"{{ auto input = {src}; {dst} = {{}}; for (size_t n=0; n<16; n+=4) {{ "
                    f"auto v = load<uint32_t>(reinterpret_cast<word>(input.data()+n)) {operation}; "
                    f"memcpy({dst}.data()+n, &v, 4); }} }}")
        elif has_wide and i.encoding == EncodingKind.VEX and op in (M.VPBROADCASTB, M.VPBROADCASTW, M.VPBROADCASTD, M.VPBROADCASTQ):
            elem_size = {M.VPBROADCASTB: 1, M.VPBROADCASTW: 2, M.VPBROADCASTD: 4, M.VPBROADCASTQ: 8}[op]
            vec_size = RegisterExt.size(i.op0_register)
            w = UINT[elem_size]
            dst = wide_any[i.op0_register]
            src_expr = (f"load<{w}>({address()})" if i.op1_kind == K.MEMORY
                        else f"load<{w}>(reinterpret_cast<word>({wide_any[i.op1_register]}.data()))")
            stmt = (f"{{ const {w} elem = {src_expr}; {dst} = {{}}; "
                    f"for (size_t n = 0; n < {vec_size}; n += {elem_size}) memcpy({dst}.data() + n, &elem, {elem_size}); }}")
        elif has_wide and i.encoding == EncodingKind.VEX and op in (M.VPSLLVD, M.VPSRLVD, M.VPSRAVD, M.VPSLLVQ, M.VPSRLVQ):
            elem_size = 8 if op in (M.VPSLLVQ, M.VPSRLVQ) else 4
            bits, w = 8 * elem_size, UINT[elem_size]
            vec_size = RegisterExt.size(i.op0_register)
            dst, src1 = wide_any[i.op0_register], wide_any[i.op1_register]
            if i.op2_kind == K.MEMORY:
                cnt_init = f"const word caddr = {address()};"
                cnt_expr = f"load<{w}>(caddr + n)"
            else:
                cnt_init = f"const auto in2 = {wide_any[i.op2_register]};"
                cnt_expr = f"load<{w}>(reinterpret_cast<word>(in2.data() + n))"
            if op in (M.VPSLLVD, M.VPSLLVQ):
                op_expr = f"c >= {bits}u ? static_cast<{w}>(0) : static_cast<{w}>(a << c)"
            elif op in (M.VPSRLVD, M.VPSRLVQ):
                op_expr = f"c >= {bits}u ? static_cast<{w}>(0) : static_cast<{w}>(a >> c)"
            else:
                op_expr = "static_cast<uint32_t>(static_cast<int32_t>(a) >> (c >= 32u ? 31u : c))"
            stmt = (f"{{ const auto in1 = {src1}; {cnt_init} {dst} = {{}}; "
                    f"for (size_t n = 0; n < {vec_size}; n += {elem_size}) {{ "
                    f"const {w} a = load<{w}>(reinterpret_cast<word>(in1.data() + n)), c = {cnt_expr}; "
                    f"const {w} v = {op_expr}; memcpy({dst}.data() + n, &v, {elem_size}); }} }}")
        elif has_wide and i.encoding == EncodingKind.VEX and op == M.VBROADCASTI128 and i.op1_kind == K.MEMORY:
            dst = wide[i.op0_register]
            stmt = (f"{{ const auto lane = load<std::array<uint8_t,16>>({address()}); "
                    f"memcpy({dst}.data(), lane.data(), 16); memcpy({dst}.data() + 16, lane.data(), 16); }}")
        elif has_wide and i.encoding == EncodingKind.VEX and op == M.VEXTRACTI128:
            src = wide[i.op1_register]
            off = 16 if (i.immediate(2) & 1) else 0
            if i.op0_kind == K.MEMORY:
                stmt = f"memcpy(reinterpret_cast<void*>({address()}), {src}.data() + {off}, 16);"
            else:
                dst = wide_any[i.op0_register]
                stmt = f"{{ const auto in1 = {src}; {dst} = {{}}; memcpy({dst}.data(), in1.data() + {off}, 16); }}"
        elif has_wide and i.encoding == EncodingKind.VEX and op == M.VINSERTI128:
            dst, src1 = wide[i.op0_register], wide[i.op1_register]
            off = 16 if (i.immediate(3) & 1) else 0
            src2_expr = (f"load<std::array<uint8_t,16>>({address()})" if i.op2_kind == K.MEMORY
                         else f"load<std::array<uint8_t,16>>(reinterpret_cast<word>({wide_any[i.op2_register]}.data()))")
            stmt = f"{{ auto out = {src1}; const auto lane = {src2_expr}; memcpy(out.data() + {off}, lane.data(), 16); {dst} = out; }}"
        elif has_wide and i.encoding == EncodingKind.VEX and op == M.VPBLENDD:
            vec_size = RegisterExt.size(i.op0_register)
            dst, src1 = wide_any[i.op0_register], wide_any[i.op1_register]
            imm = i.immediate(3)
            if i.op2_kind == K.MEMORY:
                s2_init, s2_ptr = f"const word s2addr = {address()};", "load<uint32_t>(s2addr + n)"
            else:
                s2_init, s2_ptr = f"const auto in2 = {wide_any[i.op2_register]};", "load<uint32_t>(reinterpret_cast<word>(in2.data() + n))"
            stmt = (f"{{ const auto in1 = {src1}; {s2_init} {dst} = {{}}; "
                    f"for (size_t lane = 0; lane < {vec_size // 4}; ++lane) {{ const size_t n = lane * 4; "
                    f"const uint32_t v = (({imm}u >> lane) & 1u) ? {s2_ptr} : load<uint32_t>(reinterpret_cast<word>(in1.data() + n)); "
                    f"memcpy({dst}.data() + n, &v, 4); }} }}")
        elif has_wide and i.encoding == EncodingKind.VEX and op == M.VPERM2I128:
            dst, src1 = wide[i.op0_register], wide[i.op1_register]
            imm = i.immediate(3)
            s2_init = (f"const auto in2 = load<std::array<uint8_t,32>>({address()});" if i.op2_kind == K.MEMORY
                       else f"const auto in2 = {wide[i.op2_register]};")
            def _lane_copy(sel, out_off):
                if sel & 8:
                    return f"memset({dst}.data() + {out_off}, 0, 16);"
                src_arr, src_off = ("in1", 0) if (sel & 3) == 0 else ("in1", 16) if (sel & 3) == 1 else ("in2", 0) if (sel & 3) == 2 else ("in2", 16)
                return f"memcpy({dst}.data() + {out_off}, {src_arr}.data() + {src_off}, 16);"
            stmt = f"{{ const auto in1 = {src1}; {s2_init} {_lane_copy(imm & 0xf, 0)} {_lane_copy((imm >> 4) & 0xf, 16)} }}"
        elif has_wide and i.encoding == EncodingKind.VEX and op in (M.VPERMD, M.VPERMPS):
            dst, idx_reg = wide[i.op0_register], wide[i.op1_register]
            s2_init = (f"const auto src = load<std::array<uint8_t,32>>({address()});" if i.op2_kind == K.MEMORY
                       else f"const auto src = {wide[i.op2_register]};")
            stmt = (f"{{ const auto idx = {idx_reg}; {s2_init} {dst} = {{}}; "
                    f"for (size_t lane = 0; lane < 8; ++lane) {{ "
                    f"const size_t pick = load<uint32_t>(reinterpret_cast<word>(idx.data() + lane * 4)) & 7u; "
                    f"memcpy({dst}.data() + lane * 4, src.data() + pick * 4, 4); }} }}")
        elif has_wide and i.encoding == EncodingKind.VEX and op in (M.VPERMQ, M.VPERMPD):
            dst = wide[i.op0_register]
            imm = i.immediate(2)
            s1_init = (f"const auto src = load<std::array<uint8_t,32>>({address()});" if i.op1_kind == K.MEMORY
                       else f"const auto src = {wide[i.op1_register]};")
            stmt = (f"{{ {s1_init} {dst} = {{}}; "
                    f"for (size_t lane = 0; lane < 4; ++lane) {{ "
                    f"const size_t pick = ({imm}u >> (lane * 2u)) & 3u; "
                    f"memcpy({dst}.data() + lane * 8, src.data() + pick * 8, 8); }} }}")
        elif has_wide and i.encoding == EncodingKind.VEX and op in fma_scalar:
            kind, order, is_f64 = fma_scalar[op]
            ftype, utype, sz = ("double", "uint64_t", 8) if is_f64 else ("float", "uint32_t", 4)
            dst, src1 = wide_any[i.op0_register], wide_any[i.op1_register]
            s0 = f"load<{ftype}>(reinterpret_cast<word>({dst}.data()))"
            s1 = f"load<{ftype}>(reinterpret_cast<word>({src1}.data()))"
            s2 = (f"load<{ftype}>({address()})" if i.op2_kind == K.MEMORY
                  else f"load<{ftype}>(reinterpret_cast<word>({wide_any[i.op2_register]}.data()))")
            neg_p = "true" if kind in ("nmadd", "nmsub") else "false"
            neg_c = "true" if kind in ("msub", "nmsub") else "false"
            stmt = (f"{{ const {ftype} r = fma_x86<{ftype}, {utype}>({s0}, {s1}, {s2}, {order}, {neg_p}, {neg_c}); "
                    f"auto keep = {dst}; {dst} = {{}}; memcpy({dst}.data(), keep.data(), 16); memcpy({dst}.data(), &r, {sz}); }}")
        elif has_wide and i.encoding == EncodingKind.VEX and op in fma_packed:
            kind, order, is_f64 = fma_packed[op]
            ftype, utype, sz = ("double", "uint64_t", 8) if is_f64 else ("float", "uint32_t", 4)
            vec_size = RegisterExt.size(i.op0_register)
            dst, src1 = wide_any[i.op0_register], wide_any[i.op1_register]
            if i.op2_kind == K.MEMORY:
                s2_init, s2_expr = f"const word s2addr = {address()};", f"load<{ftype}>(s2addr + n)"
            else:
                s2_init, s2_expr = f"const auto in2 = {wide_any[i.op2_register]};", f"load<{ftype}>(reinterpret_cast<word>(in2.data() + n))"
            s0 = f"load<{ftype}>(reinterpret_cast<word>(in0.data() + n))"
            s1 = f"load<{ftype}>(reinterpret_cast<word>(in1.data() + n))"
            neg_p = "true" if kind in ("nmadd", "nmsub") else "false"
            if kind in ("msub", "nmsub"):
                neg_c = "true"
            elif kind == "maddsub":
                neg_c = "(lane & 1u) == 0u"
            elif kind == "msubadd":
                neg_c = "(lane & 1u) != 0u"
            else:
                neg_c = "false"
            stmt = (f"{{ const auto in0 = {dst}, in1 = {src1}; {s2_init} {dst} = {{}}; "
                    f"for (size_t lane = 0; lane < {vec_size // sz}; ++lane) {{ const size_t n = lane * {sz}; "
                    f"const {ftype} r = fma_x86<{ftype}, {utype}>({s0}, {s1}, {s2_expr}, {order}, {neg_p}, {neg_c}); "
                    f"memcpy({dst}.data() + n, &r, {sz}); }} }}")
        elif has_wide and i.encoding == EncodingKind.LEGACY and op == M.MOVDQU:
            if i.op1_kind == K.MEMORY and i.op0_register in wide_xmm:
                stmt = f"memcpy({wide_xmm[i.op0_register]}.data(), reinterpret_cast<const void*>({address()}), 16);"
            elif i.op0_kind == K.MEMORY and i.op1_register in wide_xmm:
                stmt = f"memcpy(reinterpret_cast<void*>({address()}), {wide_xmm[i.op1_register]}.data(), 16);"
            elif i.op0_register in wide_xmm and i.op1_register in wide_xmm:
                stmt = f"memcpy({wide_xmm[i.op0_register]}.data(), {wide_xmm[i.op1_register]}.data(), 16);"
            else:
                raise ValueError(f"unsupported query operation at {i.ip:#x}: {i}")
        elif has_wide and i.encoding == EncodingKind.LEGACY and i.op0_register in wide_xmm and op in (
                M.PABSB, M.PABSW, M.PABSD, M.PSIGNB, M.PSIGNW, M.PSIGND, M.PSHUFB, M.PALIGNR,
                M.PHADDW, M.PHADDD, M.PHSUBW, M.PHSUBD, M.PHADDSW, M.PHSUBSW):
            dst = wide_xmm[i.op0_register]
            s2_init = (f"const auto in2 = load<std::array<uint8_t,16>>({address()});" if i.op1_kind == K.MEMORY
                       else f"const auto in2 = load<std::array<uint8_t,16>>(reinterpret_cast<word>({wide_xmm[i.op1_register]}.data()));")
            if op in (M.PABSB, M.PABSW, M.PABSD):
                sz = {M.PABSB: 1, M.PABSW: 2, M.PABSD: 4}[op]
                ut, st = UINT[sz], f"int{8 * sz}_t"
                stmt = (f"{{ {s2_init} for (size_t n = 0; n < 16; n += {sz}) {{ "
                        f"const {st} s = load<{st}>(reinterpret_cast<word>(in2.data() + n)); "
                        f"const {ut} v = s < 0 ? static_cast<{ut}>(0u - static_cast<{ut}>(s)) : static_cast<{ut}>(s); "
                        f"memcpy({dst}.data() + n, &v, {sz}); }} }}")
            elif op in (M.PSIGNB, M.PSIGNW, M.PSIGND):
                sz = {M.PSIGNB: 1, M.PSIGNW: 2, M.PSIGND: 4}[op]
                ut, st = UINT[sz], f"int{8 * sz}_t"
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} for (size_t n = 0; n < 16; n += {sz}) {{ "
                        f"const {ut} a = load<{ut}>(reinterpret_cast<word>(in1.data() + n)); "
                        f"const {st} b = load<{st}>(reinterpret_cast<word>(in2.data() + n)); "
                        f"const {ut} v = b < 0 ? static_cast<{ut}>(0u - a) : (b == 0 ? static_cast<{ut}>(0) : a); "
                        f"memcpy({dst}.data() + n, &v, {sz}); }} }}")
            elif op == M.PSHUFB:
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} for (size_t n = 0; n < 16; ++n) {{ "
                        f"const uint8_t c = in2[n]; {dst}[n] = (c & 0x80u) ? 0u : in1[c & 0x0fu]; }} }}")
            elif op == M.PALIGNR:
                imm = i.immediate(2)
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} std::array<uint8_t,32> cat{{}}; "
                        f"memcpy(cat.data(), in2.data(), 16); memcpy(cat.data() + 16, in1.data(), 16); "
                        f"for (size_t n = 0; n < 16; ++n) {{ {dst}[n] = (n + {imm}u < 32u) ? cat[n + {imm}u] : 0u; }} }}")
            else:  # PHADDW/D, PHSUBW/D, PHADDSW, PHSUBSW
                sz = 4 if op in (M.PHADDD, M.PHSUBD) else 2
                lanes = 16 // sz
                half = lanes // 2
                ut = UINT[sz]
                sub = op in (M.PHSUBW, M.PHSUBD, M.PHSUBSW)
                sat = op in (M.PHADDSW, M.PHSUBSW)
                if sat:
                    calc = (f"int32_t s = static_cast<int32_t>(static_cast<int16_t>(a)) {'-' if sub else '+'} "
                            f"static_cast<int32_t>(static_cast<int16_t>(b)); "
                            f"const uint16_t v = static_cast<uint16_t>(static_cast<int16_t>(s > 32767 ? 32767 : (s < -32768 ? -32768 : s)));")
                else:
                    calc = f"const {ut} v = static_cast<{ut}>(a {'-' if sub else '+'} b);"
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} for (size_t k = 0; k < {lanes}; ++k) {{ "
                        f"const uint8_t* src = k < {half} ? in1.data() : in2.data(); "
                        f"const size_t base = (k % {half}) * {2 * sz}; "
                        f"const {ut} a = load<{ut}>(reinterpret_cast<word>(src + base)), "
                        f"b = load<{ut}>(reinterpret_cast<word>(src + base + {sz})); "
                        f"{calc} memcpy({dst}.data() + k * {sz}, &v, {sz}); }} }}")
        elif op == M.MOVDQU and i.encoding == EncodingKind.LEGACY and has_wide:
            if i.op0_kind == K.REGISTER and i.op0_register in wide_xmm and i.op1_kind == K.MEMORY:
                stmt = f"memcpy({wide_xmm[i.op0_register]}.data(), reinterpret_cast<const void*>({address()}), 16);"
            elif i.op0_kind == K.MEMORY and i.op1_kind == K.REGISTER and i.op1_register in wide_xmm:
                stmt = f"memcpy(reinterpret_cast<void*>({address()}), {wide_xmm[i.op1_register]}.data(), 16);"
            elif (i.op0_kind == K.REGISTER and i.op0_register in wide_xmm
                  and i.op1_kind == K.REGISTER and i.op1_register in wide_xmm):
                stmt = f"memcpy({wide_xmm[i.op0_register]}.data(), {wide_xmm[i.op1_register]}.data(), 16);"
            else:
                raise ValueError(f"unsupported MOVDQU form at {i.ip:#x}: {i}")
        elif op in sse2_int_ops and i.encoding == EncodingKind.LEGACY and i.op0_kind == K.REGISTER and i.op0_register in wide_xmm and has_wide:
            dst = wide_xmm[i.op0_register]
            if i.op1_kind == K.REGISTER and i.op1_register in wide_xmm:
                src_init = f"std::array<uint8_t,16> rhs; memcpy(rhs.data(), {wide_xmm[i.op1_register]}.data(), 16);"
            elif i.op1_kind == K.MEMORY:
                src_init = f"std::array<uint8_t,16> rhs; memcpy(rhs.data(), reinterpret_cast<const void*>({address()}), 16);"
            else:
                raise ValueError(f"unsupported SSE2 integer source at {i.ip:#x}: {i}")
            if op in (M.PADDB, M.PADDW, M.PADDD, M.PADDQ, M.PSUBB, M.PSUBW, M.PSUBD, M.PSUBQ):
                lane_size = {M.PADDB: 1, M.PSUBB: 1, M.PADDW: 2, M.PSUBW: 2,
                             M.PADDD: 4, M.PSUBD: 4, M.PADDQ: 8, M.PSUBQ: 8}[op]
                utype = UINT[lane_size]
                sign = "+" if op in (M.PADDB, M.PADDW, M.PADDD, M.PADDQ) else "-"
                stmt = (f"{{ {src_init} for (size_t n=0; n<16; n+={lane_size}) {{ "
                        f"{utype} a, b; memcpy(&a, {dst}.data()+n, {lane_size}); memcpy(&b, rhs.data()+n, {lane_size}); "
                        f"const {utype} v = static_cast<{utype}>(a {sign} b); memcpy({dst}.data()+n, &v, {lane_size}); }} }}")
            elif op in (M.PAND, M.PANDN, M.POR, M.PXOR):
                expr = {M.PAND: "a & b", M.PANDN: "(~a) & b", M.POR: "a | b", M.PXOR: "a ^ b"}[op]
                stmt = (f"{{ {src_init} for (size_t n=0; n<16; ++n) {{ "
                        f"const uint8_t a = {dst}[n], b = rhs[n]; {dst}[n] = static_cast<uint8_t>({expr}); }} }}")
            elif op in (M.PCMPEQB, M.PCMPEQW, M.PCMPEQD):
                lane_size = {M.PCMPEQB: 1, M.PCMPEQW: 2, M.PCMPEQD: 4}[op]
                utype = UINT[lane_size]
                stmt = (f"{{ {src_init} for (size_t n=0; n<16; n+={lane_size}) {{ "
                        f"{utype} a, b; memcpy(&a, {dst}.data()+n, {lane_size}); memcpy(&b, rhs.data()+n, {lane_size}); "
                        f"const {utype} v = a == b ? static_cast<{utype}>(~{utype}(0)) : {utype}(0); "
                        f"memcpy({dst}.data()+n, &v, {lane_size}); }} }}")
            else:  # M.PCMPGTB, M.PCMPGTW, M.PCMPGTD
                lane_size = {M.PCMPGTB: 1, M.PCMPGTW: 2, M.PCMPGTD: 4}[op]
                stype = {1: "int8_t", 2: "int16_t", 4: "int32_t"}[lane_size]
                utype = UINT[lane_size]
                stmt = (f"{{ {src_init} for (size_t n=0; n<16; n+={lane_size}) {{ "
                        f"{stype} a, b; memcpy(&a, {dst}.data()+n, {lane_size}); memcpy(&b, rhs.data()+n, {lane_size}); "
                        f"const {utype} v = a > b ? static_cast<{utype}>(~{utype}(0)) : {utype}(0); "
                        f"memcpy({dst}.data()+n, &v, {lane_size}); }} }}")
        elif (op == M.PMOVMSKB and i.encoding == EncodingKind.LEGACY and has_wide
              and i.op0_kind == K.REGISTER and RegisterExt.size(i.op0_register) in (4, 8)
              and i.op1_kind == K.REGISTER and i.op1_register in wide_xmm):
            src = wide_xmm[i.op1_register]
            stmt = (f"{{ uint32_t m = 0; for (size_t k=0; k<16; ++k) {{ "
                    f"if ({src}[k] & 0x80u) m |= (1u << k); }} {write('m')} }}")
        elif (op in sse2_shift_pack_ops and op != M.PMOVMSKB and i.encoding == EncodingKind.LEGACY
              and i.op0_kind == K.REGISTER and i.op0_register in wide_xmm and has_wide):
            dst = wide_xmm[i.op0_register]
            if op in (M.PSLLDQ, M.PSRLDQ):
                if i.op1_kind != K.IMMEDIATE8:
                    raise ValueError(f"unsupported byte shift form at {i.ip:#x}: {i}")
                cnt = i.immediate(1)
                if cnt >= 16:
                    stmt = f"memset({dst}.data(), 0, 16);"
                elif op == M.PSLLDQ:
                    stmt = (f"{{ std::array<uint8_t,16> tmp; memcpy(tmp.data(), {dst}.data(), 16); "
                            f"memset({dst}.data(), 0, 16); memcpy({dst}.data()+{cnt}, tmp.data(), {16 - cnt}); }}")
                else:
                    stmt = (f"{{ std::array<uint8_t,16> tmp; memcpy(tmp.data(), {dst}.data(), 16); "
                            f"memset({dst}.data(), 0, 16); memcpy({dst}.data(), tmp.data()+{cnt}, {16 - cnt}); }}")
            elif op in (M.PSLLW, M.PSLLD, M.PSLLQ, M.PSRLW, M.PSRLD, M.PSRLQ, M.PSRAW, M.PSRAD):
                if i.op1_kind == K.IMMEDIATE8:
                    cnt_init = f"const uint64_t cnt = {i.immediate(1)}ull;"
                elif i.op1_kind == K.REGISTER and i.op1_register in wide_xmm:
                    cnt_init = f"uint64_t cnt; memcpy(&cnt, {wide_xmm[i.op1_register]}.data(), 8);"
                elif i.op1_kind == K.MEMORY:
                    cnt_init = f"const uint64_t cnt = load<uint64_t>({address()});"
                else:
                    raise ValueError(f"unsupported SSE2 shift source at {i.ip:#x}: {i}")
                lane_size = {M.PSLLW: 2, M.PSRLW: 2, M.PSRAW: 2,
                             M.PSLLD: 4, M.PSRLD: 4, M.PSRAD: 4,
                             M.PSLLQ: 8, M.PSRLQ: 8}[op]
                bits = 8 * lane_size
                if op in (M.PSRAW, M.PSRAD):
                    stype = "int16_t" if lane_size == 2 else "int32_t"
                    stmt = (f"{{ {cnt_init} const unsigned c = cnt >= {bits - 1}ull ? {bits - 1}u : static_cast<unsigned>(cnt); "
                            f"for (size_t n=0; n<16; n+={lane_size}) {{ {stype} a; memcpy(&a, {dst}.data()+n, {lane_size}); "
                            f"const {stype} v = static_cast<{stype}>(a >> c); memcpy({dst}.data()+n, &v, {lane_size}); }} }}")
                else:
                    utype = UINT[lane_size]
                    shift_op = "<<" if op in (M.PSLLW, M.PSLLD, M.PSLLQ) else ">>"
                    stmt = (f"{{ {cnt_init} for (size_t n=0; n<16; n+={lane_size}) {{ "
                            f"{utype} a; memcpy(&a, {dst}.data()+n, {lane_size}); "
                            f"const {utype} v = cnt >= {bits}ull ? {utype}(0) : static_cast<{utype}>(a {shift_op} cnt); "
                            f"memcpy({dst}.data()+n, &v, {lane_size}); }} }}")
            else:
                if i.op1_kind == K.REGISTER and i.op1_register in wide_xmm:
                    src_init = f"std::array<uint8_t,16> rhs; memcpy(rhs.data(), {wide_xmm[i.op1_register]}.data(), 16);"
                elif i.op1_kind == K.MEMORY:
                    src_init = f"std::array<uint8_t,16> rhs; memcpy(rhs.data(), reinterpret_cast<const void*>({address()}), 16);"
                else:
                    raise ValueError(f"unsupported SSE2 source operand at {i.ip:#x}: {i}")
                if op in (M.PACKSSWB, M.PACKUSWB):
                    out_type, lo, hi = ("int8_t", -128, 127) if op == M.PACKSSWB else ("uint8_t", 0, 255)
                    stmt = (f"{{ std::array<uint8_t,16> lhs; memcpy(lhs.data(), {dst}.data(), 16); {src_init} "
                            f"for (size_t k=0; k<8; ++k) {{ int16_t a, b; memcpy(&a, lhs.data()+2*k, 2); memcpy(&b, rhs.data()+2*k, 2); "
                            f"const {out_type} va = static_cast<{out_type}>(a < {lo} ? {lo} : (a > {hi} ? {hi} : a)); "
                            f"const {out_type} vb = static_cast<{out_type}>(b < {lo} ? {lo} : (b > {hi} ? {hi} : b)); "
                            f"memcpy({dst}.data()+k, &va, 1); memcpy({dst}.data()+8+k, &vb, 1); }} }}")
                elif op == M.PACKSSDW:
                    stmt = (f"{{ std::array<uint8_t,16> lhs; memcpy(lhs.data(), {dst}.data(), 16); {src_init} "
                            f"for (size_t k=0; k<4; ++k) {{ int32_t a, b; memcpy(&a, lhs.data()+4*k, 4); memcpy(&b, rhs.data()+4*k, 4); "
                            f"const int16_t va = static_cast<int16_t>(a < -32768 ? -32768 : (a > 32767 ? 32767 : a)); "
                            f"const int16_t vb = static_cast<int16_t>(b < -32768 ? -32768 : (b > 32767 ? 32767 : b)); "
                            f"memcpy({dst}.data()+2*k, &va, 2); memcpy({dst}.data()+8+2*k, &vb, 2); }} }}")
                elif op in (M.PUNPCKLBW, M.PUNPCKLWD, M.PUNPCKLDQ, M.PUNPCKLQDQ,
                            M.PUNPCKHBW, M.PUNPCKHWD, M.PUNPCKHDQ, M.PUNPCKHQDQ):
                    lane_size = {M.PUNPCKLBW: 1, M.PUNPCKHBW: 1, M.PUNPCKLWD: 2, M.PUNPCKHWD: 2,
                                 M.PUNPCKLDQ: 4, M.PUNPCKHDQ: 4, M.PUNPCKLQDQ: 8, M.PUNPCKHQDQ: 8}[op]
                    base = 0 if op in (M.PUNPCKLBW, M.PUNPCKLWD, M.PUNPCKLDQ, M.PUNPCKLQDQ) else 8
                    pairs = 8 // lane_size
                    stmt = (f"{{ std::array<uint8_t,16> lhs; memcpy(lhs.data(), {dst}.data(), 16); {src_init} "
                            f"for (size_t k=0; k<{pairs}; ++k) {{ "
                            f"memcpy({dst}.data()+2*k*{lane_size}, lhs.data()+{base}+k*{lane_size}, {lane_size}); "
                            f"memcpy({dst}.data()+(2*k+1)*{lane_size}, rhs.data()+{base}+k*{lane_size}, {lane_size}); }} }}")
                elif op == M.PSHUFD:
                    imm = i.immediate(2)
                    copies = " ".join(f"memcpy({dst}.data()+{4*k}, rhs.data()+{4*((imm >> (2*k)) & 3)}, 4);" for k in range(4))
                    stmt = f"{{ {src_init} {copies} }}"
                elif op == M.PSHUFLW:
                    imm = i.immediate(2)
                    copies = " ".join(f"memcpy({dst}.data()+{2*k}, rhs.data()+{2*((imm >> (2*k)) & 3)}, 2);" for k in range(4))
                    stmt = f"{{ {src_init} memcpy({dst}.data()+8, rhs.data()+8, 8); {copies} }}"
                else:  # M.PSHUFHW
                    imm = i.immediate(2)
                    copies = " ".join(f"memcpy({dst}.data()+{8+2*k}, rhs.data()+{8+2*((imm >> (2*k)) & 3)}, 2);" for k in range(4))
                    stmt = f"{{ {src_init} memcpy({dst}.data(), rhs.data(), 8); {copies} }}"
        elif ((op in crypto_legacy_ops and i.encoding == EncodingKind.LEGACY)
              or (op in crypto_vex_ops and i.encoding == EncodingKind.VEX)) and has_wide:
            if i.op0_kind != K.REGISTER or i.op0_register not in wide_xmm:
                raise ValueError(f"unsupported crypto destination at {i.ip:#x}: {i}")
            dst = wide_xmm[i.op0_register]
            is_vex = op in crypto_vex_ops
            zero_hi = f" memset({dst}.data()+16, 0, 16);" if is_vex else ""
            if op in (M.AESIMC, M.VAESIMC, M.AESKEYGENASSIST, M.VAESKEYGENASSIST):
                if i.op1_kind == K.REGISTER and i.op1_register in wide_xmm:
                    s_init = f"uint8_t s[16]; memcpy(s, {wide_xmm[i.op1_register]}.data(), 16);"
                elif i.op1_kind == K.MEMORY:
                    s_init = f"uint8_t s[16]; memcpy(s, reinterpret_cast<const void*>({address()}), 16);"
                else:
                    raise ValueError(f"unsupported crypto source at {i.ip:#x}: {i}")
                if op in (M.AESIMC, M.VAESIMC):
                    stmt = f"{{ {s_init} aes_mix_columns(s, true); memcpy({dst}.data(), s, 16);{zero_hi} }}"
                else:
                    rcon = i.immediate(2) & 0xff
                    stmt = f"{{ {s_init} uint8_t o[16]; aes_keygen(o, s, {rcon}u); memcpy({dst}.data(), o, 16);{zero_hi} }}"
            else:
                src1 = wide_xmm[i.op1_register] if is_vex else dst
                src2_idx = 2 if is_vex else 1
                if i.op_kind(src2_idx) == K.REGISTER and i.op_register(src2_idx) in wide_xmm:
                    s2_init = f"uint8_t s2[16]; memcpy(s2, {wide_xmm[i.op_register(src2_idx)]}.data(), 16);"
                elif i.op_kind(src2_idx) == K.MEMORY:
                    s2_init = f"uint8_t s2[16]; memcpy(s2, reinterpret_cast<const void*>({address()}), 16);"
                else:
                    raise ValueError(f"unsupported crypto source2 at {i.ip:#x}: {i}")
                if op in (M.PCLMULQDQ, M.VPCLMULQDQ):
                    imm = i.immediate(3 if is_vex else 2) & 0xff
                    stmt = (f"{{ uint8_t s1[16], o[16]; memcpy(s1, {src1}.data(), 16); {s2_init} "
                            f"pclmul_x86(o, s1, s2, {imm}u); memcpy({dst}.data(), o, 16);{zero_hi} }}")
                else:
                    dec = "true" if op in (M.AESDEC, M.AESDECLAST, M.VAESDEC, M.VAESDECLAST) else "false"
                    last = "true" if op in (M.AESENCLAST, M.AESDECLAST, M.VAESENCLAST, M.VAESDECLAST) else "false"
                    stmt = (f"{{ uint8_t s1[16], o[16]; memcpy(s1, {src1}.data(), 16); {s2_init} "
                            f"aes_round(o, s1, s2, {dec}, {last}); memcpy({dst}.data(), o, 16);{zero_hi} }}")
        elif op in sha_ops and i.encoding == EncodingKind.LEGACY and i.op0_kind == K.REGISTER and i.op0_register in wide_xmm and has_wide:
            dst = wide_xmm[i.op0_register]
            if i.op1_kind == K.REGISTER and i.op1_register in wide_xmm:
                src_init = f"uint32_t s[4]; memcpy(s, {wide_xmm[i.op1_register]}.data(), 16);"
            elif i.op1_kind == K.MEMORY:
                src_init = f"uint32_t s[4]; memcpy(s, reinterpret_cast<const void*>({address()}), 16);"
            else:
                raise ValueError(f"unsupported SHA source at {i.ip:#x}: {i}")
            if op == M.SHA1MSG1:
                stmt = (f"{{ uint32_t d[4]; memcpy(d, {dst}.data(), 16); {src_init} "
                        f"const uint32_t r[4] = {{d[0] ^ s[2], d[1] ^ s[3], d[2] ^ d[0], d[3] ^ d[1]}}; "
                        f"memcpy({dst}.data(), r, 16); }}")
            elif op == M.SHA1MSG2:
                stmt = (f"{{ uint32_t d[4]; memcpy(d, {dst}.data(), 16); {src_init} "
                        f"const uint32_t w16 = sha_rol32(d[3] ^ s[2], 1), w17 = sha_rol32(d[2] ^ s[1], 1), "
                        f"w18 = sha_rol32(d[1] ^ s[0], 1), w19 = sha_rol32(d[0] ^ w16, 1); "
                        f"const uint32_t r[4] = {{w19, w18, w17, w16}}; memcpy({dst}.data(), r, 16); }}")
            elif op == M.SHA1NEXTE:
                stmt = (f"{{ uint32_t d[4]; memcpy(d, {dst}.data(), 16); {src_init} "
                        f"const uint32_t r[4] = {{s[0], s[1], s[2], s[3] + sha_rol32(d[3], 30)}}; "
                        f"memcpy({dst}.data(), r, 16); }}")
            elif op == M.SHA1RNDS4:
                func = i.immediate(2) & 3
                stmt = f"{{ uint32_t d[4]; memcpy(d, {dst}.data(), 16); {src_init} sha1_rnds4(d, s, {func}u); memcpy({dst}.data(), d, 16); }}"
            elif op == M.SHA256MSG1:
                stmt = (f"{{ uint32_t d[4]; memcpy(d, {dst}.data(), 16); {src_init} "
                        f"auto sig0 = [](uint32_t x) {{ return sha_ror32(x, 7) ^ sha_ror32(x, 18) ^ (x >> 3); }}; "
                        f"const uint32_t r[4] = {{d[0] + sig0(d[1]), d[1] + sig0(d[2]), d[2] + sig0(d[3]), d[3] + sig0(s[0])}}; "
                        f"memcpy({dst}.data(), r, 16); }}")
            elif op == M.SHA256MSG2:
                stmt = (f"{{ uint32_t d[4]; memcpy(d, {dst}.data(), 16); {src_init} "
                        f"auto sig1 = [](uint32_t x) {{ return sha_ror32(x, 17) ^ sha_ror32(x, 19) ^ (x >> 10); }}; "
                        f"const uint32_t w16 = d[0] + sig1(s[2]), w17 = d[1] + sig1(s[3]), "
                        f"w18 = d[2] + sig1(w16), w19 = d[3] + sig1(w17); "
                        f"const uint32_t r[4] = {{w16, w17, w18, w19}}; memcpy({dst}.data(), r, 16); }}")
            else:  # M.SHA256RNDS2
                stmt = (f"{{ uint32_t d[4], wk[4]; memcpy(d, {dst}.data(), 16); {src_init} "
                        f"memcpy(wk, wide0.data(), 16); sha256_rnds2(d, s, wk); memcpy({dst}.data(), d, 16); }}")
        elif op == M.VMOVUPD and i.encoding == EncodingKind.VEX and has_wide:
            if i.op0_kind == K.REGISTER and i.op0_register in wide_any and i.op1_kind == K.MEMORY:
                dst = wide_any[i.op0_register]
                nbytes = 32 if i.op0_register in wide else 16
                stmt = f"{dst} = {{}}; memcpy({dst}.data(), reinterpret_cast<const void*>({address()}), {nbytes});"
            elif i.op0_kind == K.MEMORY and i.op1_kind == K.REGISTER and i.op1_register in wide_any:
                src = wide_any[i.op1_register]
                nbytes = 32 if i.op1_register in wide else 16
                stmt = f"memcpy(reinterpret_cast<void*>({address()}), {src}.data(), {nbytes});"
            elif i.op0_kind == K.REGISTER and i.op0_register in wide_any and i.op1_kind == K.REGISTER and i.op1_register in wide_any:
                dst, src = wide_any[i.op0_register], wide_any[i.op1_register]
                nbytes = 32 if i.op0_register in wide else 16
                stmt = f"{{ auto t = {src}; {dst} = {{}}; memcpy({dst}.data(), t.data(), {nbytes}); }}"
            else:
                raise ValueError(f"unsupported VMOVUPD form at {i.ip:#x}: {i}")
        elif (op in (M.VMOVMSKPS, M.VMOVMSKPD) and i.encoding == EncodingKind.VEX and has_wide
              and i.op0_kind == K.REGISTER and RegisterExt.size(i.op0_register) in (4, 8)
              and i.op1_kind == K.REGISTER and i.op1_register in wide_any):
            src = wide_any[i.op1_register]
            nbytes = 32 if i.op1_register in wide else 16
            lane_size = 4 if op == M.VMOVMSKPS else 8
            lanes = nbytes // lane_size
            stmt = (f"{{ uint32_t m = 0; for (size_t k=0; k<{lanes}; ++k) {{ "
                    f"if ({src}[(k + 1) * {lane_size} - 1] & 0x80u) m |= (1u << k); }} {write('m')} }}")
        elif (op in avx_fp_ops and op not in (M.VMOVUPD, M.VMOVMSKPS, M.VMOVMSKPD)
              and i.encoding == EncodingKind.VEX and has_wide
              and i.op0_kind == K.REGISTER and i.op0_register in wide_any):
            dst = wide_any[i.op0_register]
            nbytes = 32 if i.op0_register in wide else 16
            zero_hi = f" memset({dst}.data()+16, 0, 16);" if nbytes == 16 else ""
            if op in (M.VSQRTPS, M.VSQRTPD):
                if i.op1_kind == K.REGISTER and i.op1_register in wide_any:
                    s_init = f"std::array<uint8_t,32> rhs = {wide_any[i.op1_register]};"
                elif i.op1_kind == K.MEMORY:
                    s_init = f"std::array<uint8_t,32> rhs{{}}; memcpy(rhs.data(), reinterpret_cast<const void*>({address()}), {nbytes});"
                else:
                    raise ValueError(f"unsupported AVX sqrt source at {i.ip:#x}: {i}")
                ftype, lane_size = ("float", 4) if op == M.VSQRTPS else ("double", 8)
                stmt = (f"{{ {s_init} for (size_t n=0; n<{nbytes}; n+={lane_size}) {{ "
                        f"{ftype} b; memcpy(&b, rhs.data()+n, {lane_size}); "
                        f"const {ftype} v = std::sqrt(b); memcpy({dst}.data()+n, &v, {lane_size}); }}{zero_hi} }}")
            else:
                if i.op1_kind != K.REGISTER or i.op1_register not in wide_any:
                    raise ValueError(f"unsupported AVX src1 at {i.ip:#x}: {i}")
                src1 = wide_any[i.op1_register]
                if i.op2_kind == K.REGISTER and i.op2_register in wide_any:
                    s2_init = f"std::array<uint8_t,32> rhs = {wide_any[i.op2_register]};"
                elif i.op2_kind == K.MEMORY:
                    s2_init = f"std::array<uint8_t,32> rhs{{}}; memcpy(rhs.data(), reinterpret_cast<const void*>({address()}), {nbytes});"
                else:
                    raise ValueError(f"unsupported AVX src2 at {i.ip:#x}: {i}")
                if op in (M.VANDPS, M.VANDPD, M.VANDNPS, M.VANDNPD, M.VORPS, M.VORPD, M.VXORPS, M.VXORPD):
                    expr = {M.VANDPS: "a & b", M.VANDPD: "a & b", M.VANDNPS: "(~a) & b", M.VANDNPD: "(~a) & b",
                            M.VORPS: "a | b", M.VORPD: "a | b", M.VXORPS: "a ^ b", M.VXORPD: "a ^ b"}[op]
                    stmt = (f"{{ auto lhs = {src1}; {s2_init} for (size_t n=0; n<{nbytes}; ++n) {{ "
                            f"const uint8_t a = lhs[n], b = rhs[n]; {dst}[n] = static_cast<uint8_t>({expr}); }}{zero_hi} }}")
                elif op in (M.VADDSUBPS, M.VADDSUBPD):
                    ftype, lane_size = ("float", 4) if op == M.VADDSUBPS else ("double", 8)
                    lanes = nbytes // lane_size
                    stmt = (f"{{ auto lhs = {src1}; {s2_init} for (size_t k=0; k<{lanes}; ++k) {{ "
                            f"{ftype} a, b; memcpy(&a, lhs.data()+k*{lane_size}, {lane_size}); memcpy(&b, rhs.data()+k*{lane_size}, {lane_size}); "
                            f"const {ftype} v = (k & 1u) ? (a + b) : (a - b); memcpy({dst}.data()+k*{lane_size}, &v, {lane_size}); }}{zero_hi} }}")
                elif op in (M.VHADDPS, M.VHSUBPS):
                    sign = "+" if op == M.VHADDPS else "-"
                    stmt = (f"{{ auto lhs = {src1}; {s2_init} for (size_t lane=0; lane<{nbytes}; lane+=16) {{ "
                            f"float a[4], b[4]; memcpy(a, lhs.data()+lane, 16); memcpy(b, rhs.data()+lane, 16); "
                            f"const float r[4] = {{a[0] {sign} a[1], a[2] {sign} a[3], b[0] {sign} b[1], b[2] {sign} b[3]}}; "
                            f"memcpy({dst}.data()+lane, r, 16); }}{zero_hi} }}")
                elif op in (M.VHADDPD, M.VHSUBPD):
                    sign = "+" if op == M.VHADDPD else "-"
                    stmt = (f"{{ auto lhs = {src1}; {s2_init} for (size_t lane=0; lane<{nbytes}; lane+=16) {{ "
                            f"double a[2], b[2]; memcpy(a, lhs.data()+lane, 16); memcpy(b, rhs.data()+lane, 16); "
                            f"const double r[2] = {{a[0] {sign} a[1], b[0] {sign} b[1]}}; "
                            f"memcpy({dst}.data()+lane, r, 16); }}{zero_hi} }}")
                else:  # VADD/VSUB/VMUL/VDIV/VMIN/VMAX PS/PD
                    is_ps = op in (M.VADDPS, M.VSUBPS, M.VMULPS, M.VDIVPS, M.VMINPS, M.VMAXPS)
                    ftype, lane_size = ("float", 4) if is_ps else ("double", 8)
                    expr = {
                        M.VADDPS: "a + b", M.VADDPD: "a + b", M.VSUBPS: "a - b", M.VSUBPD: "a - b",
                        M.VMULPS: "a * b", M.VMULPD: "a * b", M.VDIVPS: "a / b", M.VDIVPD: "a / b",
                        M.VMINPS: "(a < b) ? a : b", M.VMINPD: "(a < b) ? a : b",
                        M.VMAXPS: "(a > b) ? a : b", M.VMAXPD: "(a > b) ? a : b",
                    }[op]
                    stmt = (f"{{ auto lhs = {src1}; {s2_init} for (size_t n=0; n<{nbytes}; n+={lane_size}) {{ "
                            f"{ftype} a, b; memcpy(&a, lhs.data()+n, {lane_size}); memcpy(&b, rhs.data()+n, {lane_size}); "
                            f"const {ftype} v = {expr}; memcpy({dst}.data()+n, &v, {lane_size}); }}{zero_hi} }}")
        elif has_wide and i.encoding == EncodingKind.LEGACY and i.op0_register in wide_xmm and op in (
                M.PMINSB, M.PMAXSB, M.PMINUW, M.PMAXUW, M.PMINSD, M.PMAXSD, M.PMINUD, M.PMAXUD,
                M.PMULLD, M.PMULDQ, M.PCMPEQQ, M.PACKUSDW, M.PBLENDW, M.PBLENDVB):
            dst = wide_xmm[i.op0_register]
            s2_init = (f"const auto in2 = load<std::array<uint8_t,16>>({address()});" if i.op1_kind == K.MEMORY
                       else f"const auto in2 = load<std::array<uint8_t,16>>(reinterpret_cast<word>({wide_xmm[i.op1_register]}.data()));")
            minmax = {
                M.PMINSB: ("int8_t", 1, "<"), M.PMAXSB: ("int8_t", 1, ">"),
                M.PMINUW: ("uint16_t", 2, "<"), M.PMAXUW: ("uint16_t", 2, ">"),
                M.PMINSD: ("int32_t", 4, "<"), M.PMAXSD: ("int32_t", 4, ">"),
                M.PMINUD: ("uint32_t", 4, "<"), M.PMAXUD: ("uint32_t", 4, ">"),
            }
            if op in minmax:
                ct, sz, cmp_op = minmax[op]
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} for (size_t n = 0; n < 16; n += {sz}) {{ "
                        f"const {ct} a = load<{ct}>(reinterpret_cast<word>(in1.data() + n)), "
                        f"b = load<{ct}>(reinterpret_cast<word>(in2.data() + n)); "
                        f"const {ct} v = (a {cmp_op} b) ? a : b; memcpy({dst}.data() + n, &v, {sz}); }} }}")
            elif op == M.PMULLD:
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} for (size_t n = 0; n < 16; n += 4) {{ "
                        f"const uint32_t v = load<uint32_t>(reinterpret_cast<word>(in1.data() + n)) * "
                        f"load<uint32_t>(reinterpret_cast<word>(in2.data() + n)); memcpy({dst}.data() + n, &v, 4); }} }}")
            elif op == M.PMULDQ:
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} for (size_t n = 0; n < 16; n += 8) {{ "
                        f"const int64_t v = static_cast<int64_t>(load<int32_t>(reinterpret_cast<word>(in1.data() + n))) * "
                        f"static_cast<int64_t>(load<int32_t>(reinterpret_cast<word>(in2.data() + n))); "
                        f"memcpy({dst}.data() + n, &v, 8); }} }}")
            elif op == M.PCMPEQQ:
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} for (size_t n = 0; n < 16; n += 8) {{ "
                        f"const uint64_t v = load<uint64_t>(reinterpret_cast<word>(in1.data() + n)) == "
                        f"load<uint64_t>(reinterpret_cast<word>(in2.data() + n)) ? ~0ull : 0ull; "
                        f"memcpy({dst}.data() + n, &v, 8); }} }}")
            elif op == M.PACKUSDW:
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} for (size_t k = 0; k < 8; ++k) {{ "
                        f"const uint8_t* src = k < 4 ? in1.data() : in2.data(); "
                        f"const int32_t s = load<int32_t>(reinterpret_cast<word>(src + (k % 4) * 4)); "
                        f"const uint16_t v = s < 0 ? 0u : (s > 65535 ? 65535u : static_cast<uint16_t>(s)); "
                        f"memcpy({dst}.data() + k * 2, &v, 2); }} }}")
            elif op == M.PBLENDW:
                imm = i.immediate(2)
                stmt = (f"{{ const auto in1 = {dst}; {s2_init} for (size_t k = 0; k < 8; ++k) {{ "
                        f"const uint8_t* src = (({imm}u >> k) & 1u) ? in2.data() : in1.data(); "
                        f"memcpy({dst}.data() + k * 2, src + k * 2, 2); }} }}")
            else:  # M.PBLENDVB (implicit XMM0 mask)
                stmt = (f"{{ const auto in1 = {dst}, m = wide0; {s2_init} for (size_t n = 0; n < 16; ++n) {{ "
                        f"{dst}[n] = (m[n] & 0x80u) ? in2[n] : in1[n]; }} }}")
        elif op == M.VMOVUPS and i.op1_kind == K.MEMORY:
            stmt = f"{wide[i.op0_register]} = load<std::array<uint8_t,32>>({address()});"
        elif op == M.VMOVUPS and i.op0_kind == K.MEMORY:
            if i.op1_register in wide:
                stmt = f"store({address()}, {wide[i.op1_register]});"
            else:
                source = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}[i.op1_register]
                stmt = f"memcpy(reinterpret_cast<void*>({address()}), {source}.data(), 16);"
        elif op == M.VPXOR and i.op0_register == i.op1_register == i.op2_register and has_wide:
            stmt = {R.XMM0: "wide0", R.XMM1: "wide1", R.XMM2: "wide2"}[i.op0_register] + " = {};"
        elif op == M.VZEROUPPER:
            stmt = " ".join(f"memset({v}.data()+16, 0, 16);" for v in wide.values()) if has_wide else ";"
        elif op == M.VMOVDQU and i.op1_kind == K.MEMORY:
            stmt = f"{xmm[i.op0_register]} = load<__m128i>({address()});"
        elif op == M.VPSRLDQ:
            stmt = f"{xmm[i.op0_register]} = _mm_srli_si128({xmm[i.op1_register]}, {i.immediate(2)});"
        elif op == M.VPADDD:
            stmt = f"{xmm[i.op0_register]} = _mm_add_epi32({xmm[i.op1_register]}, {xmm[i.op2_register]});"
        elif op == M.VMOVD and i.op1_register in xmm:
            stmt = write(f"_mm_cvtsi128_si32({xmm[i.op1_register]})")
        elif op == M.XCHG and i.op_count == 2 and i.op0_kind == i.op1_kind == K.REGISTER:
            # Both values are read before either write; 32-bit forms zero-extend both registers, so
            # 87 C0 (xchg eax, eax) clears the upper half of RAX where the one-byte 90 is a NOP.
            stmt = (f"{{ const word x = {operand(0)}, y = {operand(1)}; "
                    f"{write_register(i.op0_register, 'y')} {write_register(i.op1_register, 'x')} }}")
        elif op == M.XCHG and i.op_count == 2:
            # XCHG with memory is atomic without a LOCK prefix, so it lowers to the host's interlocked
            # exchange instead of a flat load and store. Ordering of the surrounding flat accesses is
            # not modelled.
            n = 1 if i.op0_kind == K.MEMORY else 0
            register = i.op_register(n)
            size = RegisterExt.size(register)
            suffix, host = {1: ("8", "char"), 2: ("16", "short"), 4: ("", "long"), 8: ("64", "__int64")}[size]
            stmt = write_register(register, f"_InterlockedExchange{suffix}(reinterpret_cast<{host} volatile*>({address()}), "
                                            f"static_cast<{host}>({operand(n)}))")
        elif op == M.NOP or (op == M.XCHG and i.op0_register == i.op1_register == R.AX):
            stmt = ";"
        elif op in (M.SETE, M.SETNE, M.SETA, M.SETAE, M.SETB, M.SETBE):
            cond = {M.SETE: "zero", M.SETNE: "!zero", M.SETA: "!carry && !zero",
                    M.SETAE: "!carry", M.SETB: "carry", M.SETBE: "carry || zero"}[op]
            stmt = write(f"({cond})")
        elif op == M.SETE:
            stmt = write("zero")
        elif op == M.SETO:
            stmt = write("overflow")
        elif op == M.CALL:
            stmt = calls[i.ip]
        elif op == M.XLATB:
            # AL = [RBX + AL]: iced names AL as the index, and address() would add all of RAX. The sum
            # wraps at 32 bits under 67h (base EBX). The flags and bits 8 to 63 of RAX are unchanged.
            table = f"{reg(i.memory_base)} + static_cast<uint8_t>(rax)"
            if RegisterExt.size(i.memory_base) == 4:
                table = f"static_cast<uint32_t>({table})"
            stmt = f"rax = (rax & ~0xffull) | load<uint8_t>({table});"
        elif op == M.RET:
            stmt = "return rax;"
        elif x87_depth is not None and op in x87_lower.X87_OPS:
            stmt = x87_lower.statement(i, x87_depth[i.ip], address)
        else:
            raise ValueError(f"unsupported query operation at {i.ip:#x}: {i}")
        lines.append(f"block_{i.ip:x}: {stmt}")
        if (op not in (M.RET, M.JMP) and
                (index + 1 == len(body) or body[index + 1].ip != i.next_ip)):
            if i.next_ip not in allowed:
                raise ValueError(f"unbound fallthrough at {i.ip:#x}")
            lines.append(f"goto block_{i.next_ip:x};")
    if x87_depth is not None:
        lines.insert(3, x87_lower.DECLARATION)
    lines.extend(f"block_{target:x}: {statement}" for target, statement in exits.items())
    return "\n".join("    " + line for line in lines)


def leaf(pe, address):
    for i in Decoder(64, image_bytes(pe, address, 32, executable=True), ip=address):
        if i.mnemonic == M.RET:
            return region(pe, address, i.next_ip)
    raise ValueError("unsupported provider predicate")


def checked_image(path, digest):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"unrecognized {path.name} version-query profile")
    return pefile.PE(data=data, fast_load=True)


def export_body(pe, name, slices):
    owned = function_ranges(pe, export_rva(pe, name))
    if not all(any(lo <= a < b <= hi for lo, hi in owned) for a, b in slices):
        raise ValueError(f"slice outside exported function {name}")
    return [ins for a, b in slices for ins in region(pe, a, b)]


def generate(loader, upscaler):
    # These two build-specific profiles specialize the entry guards to (nullptr, type 4).
    # Recover the record from initializer stores; the on-disk registry is zero-filled.
    with checked_image(upscaler, UPSCALER) as pe:
        init = {i.ip: i for i in region(pe, 0x10bb, 0x1144)}
        record = init[0x1130].ip_rel_memory_address
        fields = {init[addr].ip_rel_memory_address-record: value for addr, value in [
            (0x10d0, init[0x10bb].immediate(1)), (0x10e5, init[0x10e5].immediate(1)),
            (0x10f0, init[0x10de].ip_rel_memory_address)]}
        name = pe.get_string_at_rva(fields[32], 128)
        if not name or not all(32 <= c < 127 for c in name):
            raise ValueError("invalid provider version name")
        vtable = init[0x1105].ip_rel_memory_address
        predicates = []
        for slot, symbol in ((1, "supports_effect"), (2, "supports_device")):
            addr = pe.get_qword_at_rva(vtable + 8*slot) - pe.OPTIONAL_HEADER.ImageBase
            code = lower(leaf(pe, addr), ["rcx = self; rdx = input;"], {}, {}, {})
            predicates.append(f"static word {symbol}(word self, word input) {{\n{code}\n}}")
        globals_ = {init[0x1137].ip_rel_memory_address: "reinterpret_cast<word>(registry)",
                    record: "reinterpret_cast<word>(registry + 1)"}
        # The actual registry occupies one pointer between the decoded start and end.
        if record - init[0x1137].ip_rel_memory_address != 8:
            raise ValueError("unexpected provider registry size")
        calls = {site: f"rax = {fn}(rcx, rdx);" for site, fn in [
            (0x1595, "supports_effect"), (0x15a5, "supports_device"),
            (0x161a, "supports_effect"), (0x162a, "supports_device")]}
        provider = lower(export_body(pe, "ffxQuery", [(0x152b, 0x164a)]),
                         ["r15 = reinterpret_cast<word>(query); rdi = 0;"], globals_, calls,
                         {0x1999: "return static_cast<uint32_t>(rax);", 0x164a: "return 6;"})
    with checked_image(loader, LOADER) as pe:
        # The desktop binding supplies the translated upscaler; frame generation is absent.
        slots = {0x4088: "reinterpret_cast<word>(&present)", 0x40c0: "reinterpret_cast<word>(&absent)",
                 0x40a8: "reinterpret_cast<word>(&present)", 0x40e0: "reinterpret_cast<word>(&absent)"}
        caller = lower(export_body(pe, "ffxQuery", [(0x144b, 0x14b2), (0x14c2, 0x14d5)]),
                       ["rbx = reinterpret_cast<word>(query); rdi = reinterpret_cast<word>(&query->effect);"],
                       slots, {0x1456: "/* selected modules are bound offline */",
                               0x14ac: "rax = provider_versions(reinterpret_cast<Query*>(rdx));"},
                       {0x14b2: "return static_cast<uint32_t>(rax);", 0x150f: "return static_cast<uint32_t>(rax);",
                        0x14e5: "return 6;", 0x14d5: "return static_cast<uint32_t>(rax);"})
    chars = ", ".join(str(b) for b in name + b"\0")
    return HEADER + "\n".join(predicates) + f"""
static const char version_name[] = {{{chars}}};
static const word present = 1, absent = 0;
static const word entry[] = {{0, 0, {fields[16]}ull, {fields[24]}ull, reinterpret_cast<word>(version_name)}};
static const word registry[] = {{reinterpret_cast<word>(entry)}};
static uint32_t provider_versions(Query* query) {{
{provider}
}}
extern "C" __declspec(dllexport) uint32_t query_versions(Query* query) {{
    if (!query || query->type != 4) return 6;
{caller}
}}
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("loader", "upscaler", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".cpp" or args.output.resolve() in (args.loader.resolve(), args.upscaler.resolve()):
        parser.error("choose a distinct .cpp output")
    args.output.write_text(generate(args.loader, args.upscaler), encoding="ascii")
