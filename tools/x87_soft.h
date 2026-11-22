// Extended-precision helpers for the opt-in x87 profile of tools/ffx_version_query.lower().
//
// A value is exact: a sign, a 15-bit biased exponent and a 64-bit significand with an explicit integer
// bit. The profile fixes the control word at 0x027F: 53-bit precision, round to nearest-even, every
// exception masked. Arithmetic results round to 53 significand bits within the extended exponent range;
// stores round again into the destination format. The status word is not modelled.
#include <intrin.h>

struct X87Value { uint64_t sig; uint16_t se; };  // se = sign << 15 | biased exponent

static const X87Value x87_indefinite{0xc000000000000000ull, 0xffff};
static const uint64_t x87_integer_bit = 0x8000000000000000ull;
static const unsigned x87_rc = 0;  // control word 0x027F: round to nearest-even

static inline unsigned x87_exp(X87Value v) { return v.se & 0x7fffu; }
static inline bool x87_sign(X87Value v) { return (v.se >> 15) != 0; }
// A nonzero exponent with a clear integer bit (unnormal, pseudo-infinity, pseudo-NaN) is an invalid operand.
static inline bool x87_unsupported(X87Value v) { return x87_exp(v) != 0 && (v.sig & x87_integer_bit) == 0; }
static inline bool x87_is_nan(X87Value v) { return x87_exp(v) == 0x7fff && (v.sig & x87_integer_bit) && (v.sig << 1) != 0; }
static inline bool x87_is_inf(X87Value v) { return x87_exp(v) == 0x7fff && v.sig == x87_integer_bit; }
static inline bool x87_is_zero(X87Value v) { return x87_exp(v) == 0 && v.sig == 0; }
static inline bool x87_is_quiet(X87Value v) { return (v.sig & 0x4000000000000000ull) != 0; }
static inline X87Value x87_quiet(X87Value v) { v.sig |= 0x4000000000000000ull; return v; }

static inline int x87_clz(uint64_t v) {
    unsigned long index;
    return _BitScanReverse64(&index, v) ? 63 - static_cast<int>(index) : 64;
}

// A finite nonzero value as sig * 2^(e - 63) with the integer bit of sig set. A denormal or
// pseudo-denormal has the exponent of biased exponent 1.
struct X87Unpacked { bool sign; int e; uint64_t sig; };
static inline X87Unpacked x87_unpack(X87Value v) {
    if (x87_exp(v) != 0) return {x87_sign(v), static_cast<int>(x87_exp(v)) - 16383, v.sig};
    const int shift = x87_clz(v.sig);
    return {x87_sign(v), 1 - 16383 - shift, v.sig << shift};
}

// Shift the 128-bit hi:lo right by n, folding every bit shifted out into bit 0 (the sticky bit).
static inline void x87_shr_sticky(uint64_t& hi, uint64_t& lo, int n) {
    if (n <= 0) return;
    if (n >= 128) { lo = (hi | lo) != 0; hi = 0; return; }
    uint64_t sticky;
    if (n >= 64) {
        const int m = n - 64;
        sticky = lo != 0 || (m != 0 && (hi << (64 - m)) != 0);
        lo = m != 0 ? hi >> m : hi;
        hi = 0;
    } else {
        sticky = (lo << (64 - n)) != 0;
        lo = (lo >> n) | (hi << (64 - n));
        hi >>= n;
    }
    lo |= sticky;
}

// A rounding target: significand bits, exponent bias and the largest biased exponent of a finite value.
struct X87Format { int precision, bias, emax; };
static const X87Format x87_f32{24, 127, 0xfe};
static const X87Format x87_f64{53, 1023, 0x7fe};
static const X87Format x87_arith{53, 16383, 0x7ffe};  // precision control 53 bits, extended exponent range

// Round sign * (hi:lo / 2^127) * 2^e, with hi:lo normalized (bit 127 set) and the sticky bit in bit 0 of
// lo. The result significand keeps its precision bits at the top of a 64-bit word. A result below the
// normal range is denormalized first and then rounded at the same bit positions. A result above it
// becomes infinity or the largest finite value, as the masked overflow response gives for the rounding
// direction.
struct X87Rounded { uint64_t sig; int biased; };
static inline X87Rounded x87_round(bool sign, int e, uint64_t hi, uint64_t lo, X87Format format, unsigned rc) {
    int biased = e + format.bias;
    if (biased <= 0) {
        x87_shr_sticky(hi, lo, 1 - biased);
        biased = 0;
    }
    const int drop = 64 - format.precision;
    const uint64_t unit = 1ull << drop, mask = unit - 1;
    bool above, half, inexact;
    if (drop == 0) {
        above = lo > x87_integer_bit;
        half = lo == x87_integer_bit;
        inexact = lo != 0;
    } else {
        const uint64_t rest = hi & mask, middle = unit >> 1;
        above = rest > middle || (rest == middle && lo != 0);
        half = rest == middle && lo == 0;
        inexact = rest != 0 || lo != 0;
    }
    hi &= ~mask;
    bool up = false;
    switch (rc) {
    case 0: up = above || (half && (hi & unit) != 0); break;   // to nearest, ties to even
    case 1: up = sign && inexact; break;                       // toward negative infinity
    case 2: up = !sign && inexact; break;                      // toward positive infinity
    default: break;                                            // toward zero
    }
    if (up) {
        hi += unit;
        if (hi == 0) { hi = x87_integer_bit; ++biased; }
    }
    if (biased == 0 && (hi & x87_integer_bit) != 0) biased = 1;  // a denormal rounded up to the normal range
    if (biased > format.emax) {
        const bool to_infinity = rc == 0 || (rc == 1 && sign) || (rc == 2 && !sign);
        return to_infinity ? X87Rounded{x87_integer_bit, format.emax + 1} : X87Rounded{~0ull << drop, format.emax};
    }
    return {hi, biased};
}

// Loads from m32 and m64 convert exactly; a signaling NaN is quieted (the masked invalid response).
static inline X87Value x87_from_binary(uint64_t bits, int fraction_bits, int bias, int exponent_max) {
    const bool sign = (bits >> (fraction_bits + (fraction_bits == 23 ? 8 : 11))) & 1;
    const uint16_t s = sign ? 0x8000 : 0;
    const uint64_t fraction = bits & ((1ull << fraction_bits) - 1);
    const int exponent = static_cast<int>((bits >> fraction_bits) & static_cast<uint64_t>(exponent_max));
    if (exponent == exponent_max) {
        if (fraction == 0) return {x87_integer_bit, static_cast<uint16_t>(s | 0x7fff)};
        return x87_quiet({x87_integer_bit | (fraction << (63 - fraction_bits)), static_cast<uint16_t>(s | 0x7fff)});
    }
    if (exponent == 0) {
        if (fraction == 0) return {0, s};
        const int shift = x87_clz(fraction);  // value = fraction * 2^(1 - bias - fraction_bits)
        const int e = 1 - bias - fraction_bits + (63 - shift);
        return {fraction << shift, static_cast<uint16_t>(s | (e + 16383))};
    }
    return {x87_integer_bit | (fraction << (63 - fraction_bits)), static_cast<uint16_t>(s | (exponent - bias + 16383))};
}
static inline X87Value x87_from_f32(uint32_t bits) { return x87_from_binary(bits, 23, 127, 0xff); }
static inline X87Value x87_from_f64(uint64_t bits) { return x87_from_binary(bits, 52, 1023, 0x7ff); }

// Stores to m32 and m64 round into the destination's precision and range. A NaN is quieted and its
// significand truncated; an invalid operand stores the destination's indefinite.
static inline uint64_t x87_to_binary(X87Value v, X87Format format, int fraction_bits) {
    const int sign_bit = fraction_bits == 23 ? 31 : 63;
    const uint64_t sign = static_cast<uint64_t>(x87_sign(v)) << sign_bit;
    const uint64_t exponent_all = static_cast<uint64_t>(format.emax + 1) << fraction_bits;
    const uint64_t quiet_bit = 1ull << (fraction_bits - 1);
    const uint64_t fraction_mask = (1ull << fraction_bits) - 1;
    if (x87_unsupported(v)) return (1ull << sign_bit) | exponent_all | quiet_bit;
    if (x87_is_nan(v)) return sign | exponent_all | quiet_bit | ((v.sig >> (63 - fraction_bits)) & fraction_mask);
    if (x87_is_inf(v)) return sign | exponent_all;
    if (x87_is_zero(v)) return sign;
    const X87Unpacked u = x87_unpack(v);
    const X87Rounded r = x87_round(u.sign, u.e, u.sig, 0, format, x87_rc);
    return sign | (static_cast<uint64_t>(r.biased) << fraction_bits) | ((r.sig >> (63 - fraction_bits)) & fraction_mask);
}
static inline uint32_t x87_to_f32(X87Value v) { return static_cast<uint32_t>(x87_to_binary(v, x87_f32, 23)); }
static inline uint64_t x87_to_f64(X87Value v) { return x87_to_binary(v, x87_f64, 52); }

// m80 loads and stores copy all 80 bits, including NaNs and unnormals.
static inline X87Value x87_from_m80(uint64_t sig, uint16_t se) { return {sig, se}; }

// NaN operands of an arithmetic instruction (Intel SDM Vol. 1, Table 4-7, x87 column): a QNaN wins over
// an SNaN, otherwise the larger significand wins, and the result is quieted. Of two NaNs with equal
// significands the positive one wins in either operand order (measured; the table does not say). An
// invalid operand gives the indefinite. Returns false when neither operand is a NaN or invalid.
static inline bool x87_special_operands(X87Value a, X87Value b, X87Value* out) {
    if (x87_unsupported(a) || x87_unsupported(b)) { *out = x87_indefinite; return true; }
    const bool na = x87_is_nan(a), nb = x87_is_nan(b);
    if (!na && !nb) return false;
    if (na && nb) {
        if (x87_is_quiet(a) != x87_is_quiet(b)) *out = x87_is_quiet(a) ? a : b;
        else *out = b.sig > a.sig || (b.sig == a.sig && !x87_sign(b)) ? b : a;
    } else {
        *out = na ? a : b;
    }
    *out = x87_quiet(*out);
    return true;
}

// FADD: the exact sum rounded to the arithmetic format. Addends far apart keep their low bits in the
// sticky bit; an exact zero sum is +0 unless both addends are -0.
static inline X87Value x87_add(X87Value a, X87Value b) {
    X87Value out;
    if (x87_special_operands(a, b, &out)) return out;
    const bool ia = x87_is_inf(a), ib = x87_is_inf(b);
    if (ia || ib) {
        if (ia && ib && x87_sign(a) != x87_sign(b)) return x87_indefinite;
        return ia ? a : b;
    }
    const bool za = x87_is_zero(a), zb = x87_is_zero(b);
    if (za && zb) return {0, static_cast<uint16_t>(x87_sign(a) && x87_sign(b) ? 0x8000 : 0)};
    X87Unpacked x = x87_unpack(za ? b : a), y = x87_unpack(zb ? a : b);
    if (za || zb) {  // x + 0 still rounds to the arithmetic precision
        const X87Rounded r = x87_round(x.sign, x.e, x.sig, 0, x87_arith, x87_rc);
        return {r.sig, static_cast<uint16_t>((x.sign ? 0x8000 : 0) | r.biased)};
    }
    if (x.e < y.e || (x.e == y.e && x.sig < y.sig)) { const X87Unpacked t = x; x = y; y = t; }
    uint64_t hi = x.sig, lo = 0, yhi = y.sig, ylo = 0;
    x87_shr_sticky(yhi, ylo, x.e - y.e);
    int e = x.e;
    if (x.sign == y.sign) {
        unsigned char carry = _addcarry_u64(0, lo, ylo, &lo);
        carry = _addcarry_u64(carry, hi, yhi, &hi);
        if (carry) {
            const uint64_t sticky = lo & 1;
            lo = (lo >> 1) | (hi << 63) | sticky;
            hi = (hi >> 1) | x87_integer_bit;
            ++e;
        }
    } else {
        const unsigned char borrow = _subborrow_u64(0, lo, ylo, &lo);
        _subborrow_u64(borrow, hi, yhi, &hi);
        if (hi == 0 && lo == 0) return {0, 0};  // x + (-x) is +0 when rounding to nearest
        const int shift = hi != 0 ? x87_clz(hi) : 64 + x87_clz(lo);
        if (shift >= 64) { hi = lo << (shift - 64); lo = 0; }
        else if (shift != 0) { hi = (hi << shift) | (lo >> (64 - shift)); lo <<= shift; }
        e -= shift;
    }
    const X87Rounded r = x87_round(x.sign, e, hi, lo, x87_arith, x87_rc);
    return {r.sig, static_cast<uint16_t>((x.sign ? 0x8000 : 0) | r.biased)};
}
