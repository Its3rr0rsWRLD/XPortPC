// x2w_cpu_trap.h: software execution of Zen 2 instructions that a host CPU lacks, for x2w_launch.
//
// Scarlett titles are x64 code for an AMD Zen 2 CPU and run natively. On a host without one of the
// instructions below the instruction raises #UD (STATUS_ILLEGAL_INSTRUCTION). x2w_launch's vectored handler
// passes the faulting thread's CONTEXT and the instruction's bytes to emulate(), which performs the operation
// on the CONTEXT (registers and memory), advances RIP and reports which instruction it was. Anything else is
// left alone, so it crashes as it would without the launcher, and name() gives a mnemonic for the run log.
//
// Handled: SHA-NI (sha1rnds4, sha1nexte, sha1msg1, sha1msg2, sha256rnds2, sha256msg1, sha256msg2), CLZERO,
// RDPID, MONITORX and MWAITX (no wait: MONITORX arms nothing and MWAITX returns at once, like a PAUSE),
// SSE4a (extrq, insertq, movntsd, movntss), RDPRU (MPERF and APERF both read the TSC, so their ratio is 1) and
// CLWB (performed as CLFLUSH, which also writes the line back). Only the legacy encodings exist for these.
// The operations follow the Intel SDM and AMD APM pseudocode. The upper 64 bits of an EXTRQ or INSERTQ
// destination are undefined on hardware and are left unchanged here.
//
// Memory operands are read and written under __try (MSVC); an operand that faults leaves the instruction unhandled.
#pragma once

#include <windows.h>
#include <intrin.h>

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace x2w_cpu {

enum Op : int {
    kSha1rnds4,
    kSha1nexte,
    kSha1msg1,
    kSha1msg2,
    kSha256rnds2,
    kSha256msg1,
    kSha256msg2,
    kClzero,
    kRdpid,
    kMonitorx,
    kMwaitx,
    kExtrq,
    kInsertq,
    kMovntsd,
    kMovntss,
    kRdpru,
    kClwb,
    kOpCount,
    kUnhandled = -1,
};

inline const char* op_name(int op) {
    static const char* const names[kOpCount] = {
        "sha1rnds4", "sha1nexte", "sha1msg1", "sha1msg2", "sha256rnds2", "sha256msg1", "sha256msg2",
        "clzero", "rdpid", "monitorx", "mwaitx", "extrq", "insertq", "movntsd", "movntss", "rdpru", "clwb"};
    return op >= 0 && op < kOpCount ? names[op] : "unknown";
}

constexpr std::size_t kMaxLength = 15;

// MSVC and clang-cl have __try; the GNU-target compile check used on Linux does not, and gets copies that
// fault instead of failing.
#if defined(_MSC_VER)
#define X2W_TRY __try
#define X2W_EXCEPT __except (EXCEPTION_EXECUTE_HANDLER)
#else
#define X2W_TRY if (true)
#define X2W_EXCEPT else
#endif

inline void cpuidex(int* regs, unsigned leaf, unsigned subleaf) {
#if defined(_MSC_VER)
    __cpuidex(regs, static_cast<int>(leaf), static_cast<int>(subleaf));
#else
    unsigned a, b, c, d;
    __asm__ volatile("cpuid" : "=a"(a), "=b"(b), "=c"(c), "=d"(d) : "a"(leaf), "c"(subleaf));
    regs[0] = static_cast<int>(a);
    regs[1] = static_cast<int>(b);
    regs[2] = static_cast<int>(c);
    regs[3] = static_cast<int>(d);
#endif
}

inline std::uint64_t xcr0() {
#if defined(_MSC_VER)
    return _xgetbv(0);
#else
    unsigned low, high;
    __asm__ volatile("xgetbv" : "=a"(low), "=d"(high) : "c"(0));
    return (static_cast<std::uint64_t>(high) << 32) | low;
#endif
}

// Copies that report a fault instead of raising it. Kept free of C++ objects for __try.
inline bool safe_copy(void* destination, const void* source, std::size_t bytes) {
    X2W_TRY {
        auto* d = static_cast<volatile std::uint8_t*>(destination);
        const auto* s = static_cast<const volatile std::uint8_t*>(source);
        for (std::size_t i = 0; i < bytes; ++i) d[i] = s[i];
        return true;
    }
    X2W_EXCEPT {
        return false;
    }
}

// Reads up to kMaxLength bytes at an instruction pointer, stopping at the first unreadable byte.
inline std::size_t read_code(const void* at, std::uint8_t* out) {
    std::size_t n = 0;
    for (; n < kMaxLength; ++n)
        if (!safe_copy(out + n, static_cast<const std::uint8_t*>(at) + n, 1)) break;
    return n;
}

inline bool safe_clflush(const void* at) {
    X2W_TRY {
        _mm_clflush(at);
        return true;
    }
    X2W_EXCEPT {
        return false;
    }
}

struct Decoded {
    bool p66 = false;
    std::uint8_t rep = 0;   // the last F2 or F3 prefix
    std::uint8_t seg = 0;   // 0x64 or 0x65 when given
    bool addr32 = false;
    bool lock = false;
    std::uint8_t rex = 0;
    bool vex = false, evex = false, xop = false;
    std::uint8_t vex_map = 0, vex_pp = 0, vex_l = 0;
    int map = 0;            // 0: one byte, 1: 0F, 2: 0F 38, 3: 0F 3A
    std::uint8_t opcode = 0;
    std::size_t modrm_at = 0;  // offset of the ModRM byte
    bool has_modrm = false;
    std::uint8_t mod = 0, reg = 0, rm = 0;  // reg and rm include REX.R and REX.B
    bool rip_relative = false;
    int base = -1, index = -1;
    std::uint8_t scale = 0;
    std::int64_t disp = 0;
    std::size_t after_modrm = 0;  // offset just past ModRM, SIB and displacement
};

inline std::uint64_t& gpr(CONTEXT* context, int n) { return (&context->Rax)[n]; }

inline M128A& xmm(CONTEXT* context, int n) { return context->FltSave.XmmRegisters[n]; }

// Prefixes, the opcode and, for the maps that always have one, ModRM, SIB and displacement. Returns false
// for bytes that end before the instruction does.
inline bool decode(const std::uint8_t* code, std::size_t available, Decoded& d) {
    std::size_t p = 0;
    for (;; ++p) {
        if (p >= available) return false;
        const std::uint8_t b = code[p];
        if (b == 0x66) d.p66 = true;
        else if (b == 0xf2 || b == 0xf3) d.rep = b;
        else if (b == 0x64 || b == 0x65) d.seg = b;
        else if (b == 0x2e || b == 0x36 || b == 0x3e || b == 0x26) {
        } else if (b == 0x67) d.addr32 = true;
        else if (b == 0xf0) d.lock = true;
        else break;
    }
    if ((code[p] & 0xf0) == 0x40) {
        d.rex = code[p++];
        if (p >= available) return false;
    }
    const std::uint8_t lead = code[p];
    if ((lead == 0xc4 || lead == 0xc5 || lead == 0x62 || lead == 0x8f) && !d.rex) {
        // VEX, EVEX and XOP are only named for the log, never performed.
        if (p + 2 >= available) return false;
        if (lead == 0x8f && (code[p + 1] & 0x1f) < 8) goto legacy;  // POP r/m
        if (lead == 0xc5) {
            d.vex = true;
            d.vex_map = 1;
            d.vex_pp = code[p + 1] & 3;
            d.vex_l = (code[p + 1] >> 2) & 1;
            d.opcode = code[p + 2];
        } else {
            if (p + 3 >= available) return false;
            if (lead == 0x62) d.evex = true;
            else if (lead == 0x8f) d.xop = true;
            else d.vex = true;
            d.vex_map = code[p + 1] & (lead == 0x62 ? 0x07 : 0x1f);
            d.vex_pp = code[p + 2] & 3;
            d.vex_l = (code[p + 2] >> 2) & 1;
            d.opcode = code[p + (lead == 0x62 ? 4 : 3)];
        }
        return true;
    }
legacy:
    if (code[p] != 0x0f) {
        d.map = 0;
        d.opcode = code[p];
        return true;
    }
    if (++p >= available) return false;
    d.map = 1;
    if (code[p] == 0x38 || code[p] == 0x3a) {
        d.map = code[p] == 0x38 ? 2 : 3;
        if (++p >= available) return false;
    }
    d.opcode = code[p++];
    // Every 0F-map opcode handled here has a ModRM byte, as do the 0F 38 and 0F 3A maps. A 0F opcode at the
    // end of the bytes (UD2 at the end of a page) is still named.
    if (p >= available) return d.map == 1;
    d.has_modrm = true;
    d.modrm_at = p;
    const std::uint8_t modrm = code[p++];
    d.mod = modrm >> 6;
    d.reg = static_cast<std::uint8_t>(((modrm >> 3) & 7) | ((d.rex & 4) << 1));
    d.rm = static_cast<std::uint8_t>((modrm & 7) | ((d.rex & 1) << 3));
    if (d.mod != 3) {
        if ((modrm & 7) == 4) {
            if (p >= available) return false;
            const std::uint8_t sib = code[p++];
            d.scale = sib >> 6;
            const int index = ((sib >> 3) & 7) | ((d.rex & 2) << 2);
            d.index = index == 4 ? -1 : index;
            if ((sib & 7) == 5 && d.mod == 0) {
                d.base = -1;
                if (p + 4 > available) return false;
                std::int32_t v;
                std::memcpy(&v, code + p, 4);
                d.disp = v;
                p += 4;
            } else {
                d.base = (sib & 7) | ((d.rex & 1) << 3);
            }
        } else if ((modrm & 7) == 5 && d.mod == 0) {
            d.rip_relative = true;
            if (p + 4 > available) return false;
            std::int32_t v;
            std::memcpy(&v, code + p, 4);
            d.disp = v;
            p += 4;
        } else {
            d.base = d.rm;
        }
        if (d.mod == 1) {
            if (p + 1 > available) return false;
            d.disp = static_cast<std::int8_t>(code[p++]);
        } else if (d.mod == 2) {
            if (p + 4 > available) return false;
            std::int32_t v;
            std::memcpy(&v, code + p, 4);
            d.disp = v;
            p += 4;
        }
    }
    d.after_modrm = p;
    return true;
}

// The effective address of a memory operand; next_rip is the address of the following instruction.
inline bool effective_address(CONTEXT* context, const Decoded& d, std::uint64_t next_rip, std::uint64_t& out) {
    std::uint64_t address = static_cast<std::uint64_t>(d.disp);
    if (d.rip_relative) address += next_rip;
    if (d.base >= 0) address += gpr(context, d.base);
    if (d.index >= 0) address += gpr(context, d.index) << d.scale;
    if (d.addr32) address &= 0xffffffffu;
    if (d.seg == 0x65) address += reinterpret_cast<std::uint64_t>(NtCurrentTeb());
    else if (d.seg == 0x64) return false;  // FS has no defined base for 64-bit Windows programs
    out = address;
    return true;
}

// --- Operations on 32-bit lanes; lane 0 is bits 31:0. ---

struct Lanes {
    std::uint32_t w[4];
};

inline Lanes lanes(const M128A& v) {
    Lanes out;
    std::memcpy(out.w, &v, 16);
    return out;
}

inline void store(M128A& v, const Lanes& in) { std::memcpy(&v, in.w, 16); }

inline std::uint32_t rol(std::uint32_t x, int n) { return (x << n) | (x >> (32 - n)); }
inline std::uint32_t ror(std::uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

inline Lanes sha1rnds4(const Lanes& s1, const Lanes& s2, int function) {
    static const std::uint32_t k[4] = {0x5a827999u, 0x6ed9eba1u, 0x8f1bbcdcu, 0xca62c1d6u};
    std::uint32_t a = s1.w[3], b = s1.w[2], c = s1.w[1], d = s1.w[0], e = 0;
    const std::uint32_t w[4] = {s2.w[3], s2.w[2], s2.w[1], s2.w[0]};
    for (int i = 0; i < 4; ++i) {
        std::uint32_t f;
        switch (function & 3) {
        case 0: f = (b & c) ^ (~b & d); break;
        case 2: f = (b & c) ^ (b & d) ^ (c & d); break;
        default: f = b ^ c ^ d; break;
        }
        // In round 0 the first message word already holds E (W0E).
        const std::uint32_t t = f + rol(a, 5) + w[i] + e + k[function & 3];
        e = d;
        d = c;
        c = rol(b, 30);
        b = a;
        a = t;
    }
    return Lanes{{d, c, b, a}};
}

inline Lanes sha1nexte(const Lanes& s1, const Lanes& s2) {
    return Lanes{{s2.w[0], s2.w[1], s2.w[2], s2.w[3] + rol(s1.w[3], 30)}};
}

inline Lanes sha1msg1(const Lanes& s1, const Lanes& s2) {
    const std::uint32_t w0 = s1.w[3], w1 = s1.w[2], w2 = s1.w[1], w3 = s1.w[0], w4 = s2.w[3], w5 = s2.w[2];
    return Lanes{{w5 ^ w3, w4 ^ w2, w3 ^ w1, w2 ^ w0}};
}

inline Lanes sha1msg2(const Lanes& s1, const Lanes& s2) {
    const std::uint32_t w13 = s2.w[2], w14 = s2.w[1], w15 = s2.w[0];
    const std::uint32_t w16 = rol(s1.w[3] ^ w13, 1);
    const std::uint32_t w17 = rol(s1.w[2] ^ w14, 1);
    const std::uint32_t w18 = rol(s1.w[1] ^ w15, 1);
    const std::uint32_t w19 = rol(s1.w[0] ^ w16, 1);
    return Lanes{{w19, w18, w17, w16}};
}

inline Lanes sha256rnds2(const Lanes& s1, const Lanes& s2, const Lanes& wk) {
    std::uint32_t a = s2.w[3], b = s2.w[2], c = s1.w[3], d = s1.w[2];
    std::uint32_t e = s2.w[1], f = s2.w[0], g = s1.w[1], h = s1.w[0];
    for (int i = 0; i < 2; ++i) {
        const std::uint32_t ch = (e & f) ^ (~e & g);
        const std::uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        const std::uint32_t sigma1 = ror(e, 6) ^ ror(e, 11) ^ ror(e, 25);
        const std::uint32_t sigma0 = ror(a, 2) ^ ror(a, 13) ^ ror(a, 22);
        const std::uint32_t t = ch + sigma1 + wk.w[i] + h;
        h = g;
        g = f;
        f = e;
        e = t + d;
        d = c;
        c = b;
        b = a;
        a = t + maj + sigma0;
    }
    return Lanes{{f, e, b, a}};
}

inline std::uint32_t small_sigma0(std::uint32_t w) { return ror(w, 7) ^ ror(w, 18) ^ (w >> 3); }
inline std::uint32_t small_sigma1(std::uint32_t w) { return ror(w, 17) ^ ror(w, 19) ^ (w >> 10); }

inline Lanes sha256msg1(const Lanes& s1, const Lanes& s2) {
    return Lanes{{s1.w[0] + small_sigma0(s1.w[1]), s1.w[1] + small_sigma0(s1.w[2]),
                  s1.w[2] + small_sigma0(s1.w[3]), s1.w[3] + small_sigma0(s2.w[0])}};
}

inline Lanes sha256msg2(const Lanes& s1, const Lanes& s2) {
    const std::uint32_t w16 = s1.w[0] + small_sigma1(s2.w[2]);
    const std::uint32_t w17 = s1.w[1] + small_sigma1(s2.w[3]);
    const std::uint32_t w18 = s1.w[2] + small_sigma1(w16);
    const std::uint32_t w19 = s1.w[3] + small_sigma1(w17);
    return Lanes{{w16, w17, w18, w19}};
}

// SSE4a bit fields: a length of 0 means 64. Fields that run past bit 63 are undefined on hardware; here
// the bits past 63 are dropped.
inline std::uint64_t field_mask(unsigned length) { return length >= 64 ? ~0ull : (1ull << length) - 1; }

inline std::uint64_t extrq(std::uint64_t source, unsigned length, unsigned index) {
    length &= 63;
    index &= 63;
    if (!length) length = 64;
    return (source >> index) & field_mask(length);
}

inline std::uint64_t insertq(std::uint64_t destination, std::uint64_t source, unsigned length, unsigned index) {
    length &= 63;
    index &= 63;
    if (!length) length = 64;
    const std::uint64_t mask = field_mask(length) << index;
    return (destination & ~mask) | ((source << index) & mask);
}

// TSC_AUX, which RDPID returns: RDTSCP's ECX when the host has RDTSCP, else the processor number.
inline bool host_rdtscp() {
    int regs[4];
    cpuidex(regs, 0x80000000u, 0);
    if (static_cast<unsigned>(regs[0]) < 0x80000001u) return false;
    cpuidex(regs, 0x80000001u, 0);
    return (regs[3] & (1 << 27)) != 0;
}

inline std::uint64_t tsc_aux() {
    static const bool rdtscp = host_rdtscp();
    if (rdtscp) {
        unsigned aux = 0;
        __rdtscp(&aux);
        return aux;
    }
    return GetCurrentProcessorNumber();
}

struct Result {
    int op = kUnhandled;
    std::size_t length = 0;
};

// Performs the instruction at context->Rip, whose bytes are code[0, available), and advances RIP.
// On kUnhandled the CONTEXT is unchanged.
inline Result emulate(CONTEXT* context, const std::uint8_t* code, std::size_t available) {
    Result result;
    Decoded d;
    if (!decode(code, available, d) || d.lock || d.vex || d.evex || d.xop || d.map == 0 || !d.has_modrm)
        return result;
    const std::uint64_t rip = context->Rip;

    // 0F 01 with a fixed ModRM byte: MONITORX, MWAITX, CLZERO, RDPRU.
    if (d.map == 1 && d.opcode == 0x01 && !d.rep) {
        const std::uint8_t modrm = code[d.modrm_at];
        const std::size_t length = d.modrm_at + 1;
        if (modrm == 0xfa) {
            result.op = kMonitorx;
        } else if (modrm == 0xfb) {
            YieldProcessor();
            result.op = kMwaitx;
        } else if (modrm == 0xfc) {
            std::uint64_t address = d.addr32 ? (context->Rax & 0xffffffffu) : context->Rax;
            if (d.seg == 0x65) address += reinterpret_cast<std::uint64_t>(NtCurrentTeb());
            else if (d.seg == 0x64) return result;
            address &= ~63ull;
            static const std::uint8_t zero[64] = {};
            if (!safe_copy(reinterpret_cast<void*>(address), zero, 64)) return result;
            result.op = kClzero;
        } else if (modrm == 0xfd) {
            const std::uint32_t id = static_cast<std::uint32_t>(context->Rcx);
            std::uint64_t value = 0;
            DWORD flags = context->EFlags & ~0x8d5u;  // clear CF PF AF ZF SF OF
            if (id == 0 || id == 1) {  // MPERF, APERF
                value = __rdtsc();
                flags |= 1;
            }
            context->EFlags = flags;
            context->Rax = value & 0xffffffffu;
            context->Rdx = value >> 32;
            result.op = kRdpru;
        } else {
            return result;
        }
        result.length = length;
        context->Rip = rip + length;
        return result;
    }

    // RDPID r64: F3 0F C7 /7 with a register operand.
    if (d.map == 1 && d.opcode == 0xc7 && d.rep == 0xf3 && d.mod == 3 && (d.reg & 7) == 7) {
        gpr(context, d.rm) = tsc_aux();
        result.op = kRdpid;
        result.length = d.after_modrm;
        context->Rip = rip + result.length;
        return result;
    }

    // CLWB m8: 66 0F AE /6 with a memory operand.
    if (d.map == 1 && d.opcode == 0xae && d.p66 && !d.rep && d.mod != 3 && (d.reg & 7) == 6) {
        const std::size_t length = d.after_modrm;
        std::uint64_t address;
        if (!effective_address(context, d, rip + length, address)) return result;
        if (!safe_clflush(reinterpret_cast<const void*>(address))) return result;
        result.op = kClwb;
        result.length = length;
        context->Rip = rip + length;
        return result;
    }

    // SSE4a.
    if (d.map == 1 && (d.opcode == 0x78 || d.opcode == 0x79 || d.opcode == 0x2b)) {
        std::size_t length = d.after_modrm;
        if (d.opcode == 0x2b) {
            if (d.mod == 3 || (d.rep != 0xf2 && d.rep != 0xf3)) return result;
            const bool sd = d.rep == 0xf2;
            std::uint64_t address;
            if (!effective_address(context, d, rip + length, address)) return result;
            if (!safe_copy(reinterpret_cast<void*>(address), &xmm(context, d.reg), sd ? 8 : 4)) return result;
            result.op = sd ? kMovntsd : kMovntss;
        } else {
            if (d.mod != 3) return result;
            M128A& dest = xmm(context, d.opcode == 0x78 && d.rep != 0xf2 ? d.rm : d.reg);
            if (d.opcode == 0x78) {
                // EXTRQ xmm, imm8, imm8 (66, /0) and INSERTQ xmm, xmm, imm8, imm8 (F2).
                if (length + 2 > available) return result;
                const unsigned field = code[length], index = code[length + 1];
                length += 2;
                if (d.rep == 0xf2 && !d.p66) {
                    dest.Low = insertq(dest.Low, xmm(context, d.rm).Low, field, index);
                    result.op = kInsertq;
                } else if (d.p66 && !d.rep && (d.reg & 7) == 0) {
                    dest.Low = extrq(dest.Low, field, index);
                    result.op = kExtrq;
                } else {
                    return result;
                }
            } else {
                // EXTRQ xmm, xmm (66) and INSERTQ xmm, xmm (F2); the field comes from the source.
                const M128A source = xmm(context, d.rm);
                if (d.rep == 0xf2 && !d.p66) {
                    const unsigned field = static_cast<unsigned>(source.High & 0x3f);
                    const unsigned index = static_cast<unsigned>((source.High >> 8) & 0x3f);
                    dest.Low = insertq(dest.Low, source.Low, field, index);
                    result.op = kInsertq;
                } else if (d.p66 && !d.rep) {
                    const unsigned field = static_cast<unsigned>(source.Low & 0x3f);
                    const unsigned index = static_cast<unsigned>((source.Low >> 8) & 0x3f);
                    dest.Low = extrq(dest.Low, field, index);
                    result.op = kExtrq;
                } else {
                    return result;
                }
            }
        }
        result.length = length;
        context->Rip = rip + length;
        return result;
    }

    // SHA-NI: NP 0F 38 C8-CD and NP 0F 3A CC.
    const bool sha38 = d.map == 2 && d.opcode >= 0xc8 && d.opcode <= 0xcd;
    const bool sha3a = d.map == 3 && d.opcode == 0xcc;
    if ((sha38 || sha3a) && !d.p66 && !d.rep) {
        std::size_t length = d.after_modrm + (sha3a ? 1 : 0);
        if (length > available) return result;
        Lanes source;
        if (d.mod == 3) {
            source = lanes(xmm(context, d.rm));
        } else {
            std::uint64_t address;
            if (!effective_address(context, d, rip + length, address)) return result;
            if (!safe_copy(source.w, reinterpret_cast<const void*>(address), 16)) return result;
        }
        const Lanes dest = lanes(xmm(context, d.reg));
        Lanes out;
        if (sha3a) {
            out = sha1rnds4(dest, source, code[d.after_modrm] & 3);
            result.op = kSha1rnds4;
        } else {
            switch (d.opcode) {
            case 0xc8: out = sha1nexte(dest, source); result.op = kSha1nexte; break;
            case 0xc9: out = sha1msg1(dest, source); result.op = kSha1msg1; break;
            case 0xca: out = sha1msg2(dest, source); result.op = kSha1msg2; break;
            case 0xcb: out = sha256rnds2(dest, source, lanes(xmm(context, 0))); result.op = kSha256rnds2; break;
            case 0xcc: out = sha256msg1(dest, source); result.op = kSha256msg1; break;
            default: out = sha256msg2(dest, source); result.op = kSha256msg2; break;
            }
        }
        store(xmm(context, d.reg), out);
        result.length = length;
        context->Rip = rip + length;
        return result;
    }
    return result;
}

// A mnemonic, or an instruction family, for an instruction emulate() does not handle. Names only: the run
// log never holds the program's bytes.
inline const char* name(const std::uint8_t* code, std::size_t available) {
    Decoded d;
    if (!decode(code, available, d)) return "truncated";
    if (d.evex) return "avx512";
    if (d.xop) return "xop";
    if (d.vex) {
        if (d.vex_map == 2) {
            switch (d.opcode) {
            case 0xf2: return "andn";
            case 0xf3: return "bmi1-group17";
            case 0xf5: return d.vex_pp == 0 ? "bzhi" : d.vex_pp == 2 ? "pext" : d.vex_pp == 3 ? "pdep" : "vex";
            case 0xf6: return "mulx";
            case 0xf7: return d.vex_pp == 0 ? "bextr" : d.vex_pp == 1 ? "shlx" : d.vex_pp == 2 ? "sarx" : "shrx";
            case 0x13: return "vcvtph2ps";
            default: break;
            }
            if (d.opcode >= 0x96 && d.opcode <= 0xbf) return "fma3";
        }
        if (d.vex_map == 3 && d.opcode == 0xf0) return "rorx";
        if (d.vex_map == 3 && d.opcode == 0x1d) return "vcvtps2ph";
        return d.vex_l ? "avx-256" : "avx-128";
    }
    if (d.map == 1) {
        switch (d.opcode) {
        case 0x0b: return "ud2";
        case 0xb9: return "ud1";
        case 0xff: return "ud0";
        case 0x0f: return "3dnow";
        case 0x01: return "group7";
        case 0xc7: return (d.reg & 7) == 7 ? "rdseed" : (d.reg & 7) == 6 ? "rdrand" : "group9";
        case 0xae: return "group15";
        case 0x78: case 0x79: return "sse4a";
        default: return "unknown";
        }
    }
    if (d.map == 2) {
        if (d.opcode == 0xf0 || d.opcode == 0xf1) return "movbe";
        if (d.opcode == 0xf6) return d.rep == 0xf3 ? "adox" : "adcx";
        if (d.opcode >= 0xdb && d.opcode <= 0xdf) return "aes";
        return "sse-0f38";
    }
    if (d.map == 3) {
        if (d.opcode == 0x44) return "pclmulqdq";
        if (d.opcode == 0xdf) return "aeskeygenassist";
        return "sse-0f3a";
    }
    return "unknown";
}

// --- Host check: which Zen 2 features the host CPU lacks. ---

enum Handling { kEmulated, kUnhandledFeature, kSilent };

struct Feature {
    const char* name;
    unsigned leaf, subleaf;
    int reg;  // 0 EAX, 1 EBX, 2 ECX, 3 EDX
    int bit;
    Handling handling;
};

// The Zen 2 user-mode instruction set beyond x86-64 baseline. kSilent marks encodings that an older CPU runs
// as a different instruction instead of faulting (LZCNT runs as BSR), so no handler sees them.
inline const Feature* zen2_features(std::size_t& count) {
    static const Feature features[] = {
        {"sse3", 1, 0, 2, 0, kUnhandledFeature},        {"pclmulqdq", 1, 0, 2, 1, kUnhandledFeature},
        {"ssse3", 1, 0, 2, 9, kUnhandledFeature},       {"fma", 1, 0, 2, 12, kUnhandledFeature},
        {"cx16", 1, 0, 2, 13, kUnhandledFeature},       {"sse4.1", 1, 0, 2, 19, kUnhandledFeature},
        {"sse4.2", 1, 0, 2, 20, kUnhandledFeature},     {"movbe", 1, 0, 2, 22, kUnhandledFeature},
        {"popcnt", 1, 0, 2, 23, kUnhandledFeature},     {"aes", 1, 0, 2, 25, kUnhandledFeature},
        {"xsave", 1, 0, 2, 26, kUnhandledFeature},      {"avx", 1, 0, 2, 28, kUnhandledFeature},
        {"f16c", 1, 0, 2, 29, kUnhandledFeature},       {"rdrand", 1, 0, 2, 30, kUnhandledFeature},
        {"bmi1", 7, 0, 1, 3, kUnhandledFeature},        {"avx2", 7, 0, 1, 5, kUnhandledFeature},
        {"bmi2", 7, 0, 1, 8, kUnhandledFeature},        {"rdseed", 7, 0, 1, 18, kUnhandledFeature},
        {"adx", 7, 0, 1, 19, kUnhandledFeature},        {"clflushopt", 7, 0, 1, 23, kUnhandledFeature},
        {"clwb", 7, 0, 1, 24, kEmulated},               {"sha", 7, 0, 1, 29, kEmulated},
        {"rdpid", 7, 0, 2, 22, kEmulated},              {"xsaveopt", 0xd, 1, 0, 0, kUnhandledFeature},
        {"xsavec", 0xd, 1, 0, 1, kUnhandledFeature},    {"lahf-lm", 0x80000001u, 0, 2, 0, kUnhandledFeature},
        {"lzcnt", 0x80000001u, 0, 2, 5, kSilent},       {"sse4a", 0x80000001u, 0, 2, 6, kEmulated},
        {"prefetchw", 0x80000001u, 0, 2, 8, kUnhandledFeature}, {"mwaitx", 0x80000001u, 0, 2, 29, kEmulated},
        {"rdtscp", 0x80000001u, 0, 3, 27, kUnhandledFeature},   {"clzero", 0x80000008u, 0, 1, 0, kEmulated},
        {"rdpru", 0x80000008u, 0, 1, 4, kEmulated},
    };
    count = sizeof features / sizeof features[0];
    return features;
}

inline bool host_has(const Feature& feature) {
    int regs[4];
    cpuidex(regs, feature.leaf & 0x80000000u, 0);
    if (static_cast<unsigned>(regs[0]) < feature.leaf) return false;
    cpuidex(regs, feature.leaf, feature.subleaf);
    if (!(static_cast<unsigned>(regs[feature.reg]) & (1u << feature.bit))) return false;
    // AVX, AVX2, FMA and F16C also need the OS to save the YMM state.
    const bool ymm = !std::strcmp(feature.name, "avx") || !std::strcmp(feature.name, "avx2")
                     || !std::strcmp(feature.name, "fma") || !std::strcmp(feature.name, "f16c");
    if (ymm) {
        cpuidex(regs, 1, 0);
        if (!(regs[2] & (1 << 27))) return false;
        if ((xcr0() & 6) != 6) return false;
    }
    return true;
}

}  // namespace x2w_cpu
