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

// Loads from m32 and m64 convert exactly; a signaling NaN is quieted (the masked invalid response). An
// arithmetic memory operand converts the same way but keeps a signaling NaN signaling (quiet = false), so
// the NaN rules of the arithmetic see the operand's own kind.
static inline X87Value x87_from_binary(uint64_t bits, int fraction_bits, int bias, int exponent_max, bool quiet = true) {
    const bool sign = (bits >> (fraction_bits + (fraction_bits == 23 ? 8 : 11))) & 1;
    const uint16_t s = sign ? 0x8000 : 0;
    const uint64_t fraction = bits & ((1ull << fraction_bits) - 1);
    const int exponent = static_cast<int>((bits >> fraction_bits) & static_cast<uint64_t>(exponent_max));
    if (exponent == exponent_max) {
        if (fraction == 0) return {x87_integer_bit, static_cast<uint16_t>(s | 0x7fff)};
        const X87Value nan{x87_integer_bit | (fraction << (63 - fraction_bits)), static_cast<uint16_t>(s | 0x7fff)};
        return quiet ? x87_quiet(nan) : nan;
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
static inline X87Value x87_operand_f32(uint32_t bits) { return x87_from_binary(bits, 23, 127, 0xff, false); }
static inline X87Value x87_operand_f64(uint64_t bits) { return x87_from_binary(bits, 52, 1023, 0x7ff, false); }

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

// FMUL: the exact product rounded to the arithmetic format. The sign is the exclusive or of the operand
// signs, also for zero and infinite results; infinity times zero is invalid and gives the indefinite.
static inline X87Value x87_mul(X87Value a, X87Value b) {
    X87Value out;
    if (x87_special_operands(a, b, &out)) return out;
    const bool sign = x87_sign(a) != x87_sign(b);
    const uint16_t s = sign ? 0x8000 : 0;
    const bool ia = x87_is_inf(a), ib = x87_is_inf(b), za = x87_is_zero(a), zb = x87_is_zero(b);
    if ((ia && zb) || (ib && za)) return x87_indefinite;
    if (ia || ib) return {x87_integer_bit, static_cast<uint16_t>(s | 0x7fff)};
    if (za || zb) return {0, s};
    const X87Unpacked x = x87_unpack(a), y = x87_unpack(b);
    uint64_t hi, lo = _umul128(x.sig, y.sig, &hi);  // x.sig * y.sig in [2^126, 2^128)
    int e = x.e + y.e;
    if (hi & x87_integer_bit) ++e;
    else { hi = (hi << 1) | (lo >> 63); lo <<= 1; }
    const X87Rounded r = x87_round(sign, e, hi, lo, x87_arith, x87_rc);
    return {r.sig, static_cast<uint16_t>(s | r.biased)};
}

// FDIV: the quotient rounded to the arithmetic format. A 64-bit quotient of the significands and a sticky
// bit for a nonzero remainder are enough to round to 53 bits. The sign is the exclusive or of the operand
// signs. Zero by zero and infinity by infinity are invalid and give the indefinite; a finite nonzero value
// by zero gives infinity (the masked divide-by-zero response); a finite value by infinity gives zero.
static inline X87Value x87_div(X87Value a, X87Value b) {
    X87Value out;
    if (x87_special_operands(a, b, &out)) return out;
    const bool sign = x87_sign(a) != x87_sign(b);
    const uint16_t s = sign ? 0x8000 : 0;
    const bool ia = x87_is_inf(a), ib = x87_is_inf(b), za = x87_is_zero(a), zb = x87_is_zero(b);
    if ((ia && ib) || (za && zb)) return x87_indefinite;
    if (ia || zb) return {x87_integer_bit, static_cast<uint16_t>(s | 0x7fff)};
    if (ib || za) return {0, s};
    const X87Unpacked x = x87_unpack(a), y = x87_unpack(b);
    // Divide x.sig * 2^64 (or x.sig * 2^63 when x.sig >= y.sig) by y.sig: the quotient lies in [2^63, 2^64).
    const bool shift = x.sig >= y.sig;
    uint64_t remainder;
    const uint64_t q = _udiv128(shift ? x.sig >> 1 : x.sig, shift ? x.sig << 63 : 0, y.sig, &remainder);
    const uint64_t lo = remainder != 0;  // sticky
    const X87Rounded r = x87_round(sign, x.e - y.e - (shift ? 0 : 1), q, lo, x87_arith, x87_rc);
    return {r.sig, static_cast<uint16_t>(s | r.biased)};
}
// FDIVR: the same division with the operands exchanged.
static inline X87Value x87_divr(X87Value a, X87Value b) { return x87_div(b, a); }

// FSUB: a - b as a + (-b). A NaN or invalid operand is selected before the negation, so a NaN result keeps
// its own sign; x - x is +0, as x + (-x) is.
static inline X87Value x87_sub(X87Value a, X87Value b) {
    X87Value out;
    if (x87_special_operands(a, b, &out)) return out;
    b.se ^= 0x8000;
    return x87_add(a, b);
}
// FSUBR: the same subtraction with the operands exchanged.
static inline X87Value x87_subr(X87Value a, X87Value b) { return x87_sub(b, a); }

// FCHS and FABS change only the sign bit, of every encoding: NaNs stay signaling or quiet, and unnormals
// and pseudo-denormals keep their bits.
static inline X87Value x87_chs(X87Value v) { v.se ^= 0x8000; return v; }
static inline X87Value x87_abs(X87Value v) { v.se &= 0x7fff; return v; }

// FILD: a 16-, 32- or 64-bit two's-complement integer converts exactly, and zero gives +0. The precision
// control does not apply to loads.
static inline X87Value x87_from_integer(int64_t n) {
    if (n == 0) return {0, 0};
    const bool negative = n < 0;
    const uint64_t magnitude = negative ? 0 - static_cast<uint64_t>(n) : static_cast<uint64_t>(n);
    const int shift = x87_clz(magnitude);
    return {magnitude << shift, static_cast<uint16_t>((negative ? 0x8000 : 0) | (16383 + 63 - shift))};
}

// FIST, FISTP and FISTTP: ST(0) rounded to an integer (to nearest-even, or toward zero when chop is set)
// as two's-complement bits in the low `bits` bits. A NaN, an infinity, an unsupported encoding or a
// rounded value outside the destination range gives the integer indefinite (only the sign bit set), the
// masked invalid-operation response. The precision control does not apply.
static inline uint64_t x87_to_integer(X87Value v, int bits, bool chop) {
    const uint64_t indefinite = 1ull << (bits - 1);
    const uint64_t mask = bits == 64 ? ~0ull : (1ull << bits) - 1;
    if (x87_unsupported(v) || x87_exp(v) == 0x7fff) return indefinite;
    if (v.sig == 0) return 0;
    const int shift = 16383 + 63 - (x87_exp(v) == 0 ? 1 : static_cast<int>(x87_exp(v)));  // v = sig * 2^-shift
    if (shift < 0) return indefinite;
    uint64_t magnitude = shift >= 64 ? 0 : v.sig >> shift;
    if (!chop && shift > 0 && shift <= 64) {  // a value below one half (shift > 64) rounds to 0
        const uint64_t rest = shift == 64 ? v.sig : v.sig & ((1ull << shift) - 1);
        const uint64_t half = 1ull << (shift - 1);
        if (rest > half || (rest == half && (magnitude & 1))) ++magnitude;
    }
    if (magnitude > indefinite - (x87_sign(v) ? 0 : 1)) return indefinite;
    return (x87_sign(v) ? 0 - magnitude : magnitude) & mask;
}

// FCOMI, FUCOMI and their P forms: 0 if a < b, 1 if equal, 2 if a > b and 3 if unordered (a NaN or an
// unsupported encoding; with the invalid operation masked, FCOMI and FUCOMI give the same result). The
// comparison uses all 64 significand bits, +0 equals -0, and a pseudo-denormal equals the normal value
// with the same significand at biased exponent 1.
static inline int x87_compare(X87Value a, X87Value b) {
    if (x87_unsupported(a) || x87_unsupported(b) || x87_is_nan(a) || x87_is_nan(b)) return 3;  // unordered
    const bool za = x87_is_zero(a), zb = x87_is_zero(b);
    if (za && zb) return 1;  // signed zeros
    if (za) return x87_sign(b) ? 2 : 0;
    if (zb) return x87_sign(a) ? 0 : 2;
    if (x87_sign(a) != x87_sign(b)) return x87_sign(a) ? 0 : 2;
    const X87Unpacked ua = x87_unpack(a), ub = x87_unpack(b);  // infinities unpack above every finite value
    if (ua.e == ub.e && ua.sig == ub.sig) return 1;
    const bool less = ua.e != ub.e ? ua.e < ub.e : ua.sig < ub.sig;
    return less != x87_sign(a) ? 0 : 2;
}

// FSQRT: the exact square root rounded to the arithmetic format (53 significand bits, to nearest-even).
// sqrt(-0) is -0 and sqrt(+inf) is +inf; a NaN is quieted; any other negative operand, and an unsupported
// encoding, gives the indefinite. The root of sig * 2^(e - 63) is isqrt(sig * 2^t) * 2^((e - 63 - t) / 2)
// with t = 63 or 64 chosen to make the exponent even, which puts the 64-bit root in [2^63, 2^64); a
// nonzero remainder becomes the sticky bit. The result never leaves the extended normal range.
static inline X87Value x87_sqrt(X87Value a) {
    if (x87_unsupported(a)) return x87_indefinite;
    if (x87_is_nan(a)) return x87_quiet(a);
    if (x87_is_zero(a)) return a;
    if (x87_sign(a)) return x87_indefinite;
    if (x87_is_inf(a)) return a;
    const X87Unpacked x = x87_unpack(a);
    const int t = (x.e & 1) ? 64 : 63;
    const uint64_t r_hi = t == 64 ? x.sig : x.sig >> 1, r_lo = t == 64 ? 0 : x.sig << 63;  // R = sig * 2^t
    uint64_t q = 0, sq_hi = 0, sq_lo = 0;
    for (uint64_t bit = x87_integer_bit; bit != 0; bit >>= 1) {
        const uint64_t c = q | bit;
        uint64_t hi;
        const uint64_t lo = _umul128(c, c, &hi);
        if (hi < r_hi || (hi == r_hi && lo <= r_lo)) { q = c; sq_hi = hi; sq_lo = lo; }
    }
    const uint64_t sticky = sq_hi != r_hi || sq_lo != r_lo;  // sqrt sticky
    const X87Rounded r = x87_round(false, (x.e - 63 - t) / 2 + 63, q, sticky, x87_arith, x87_rc);  // sqrt round
    return {r.sig, static_cast<uint16_t>(r.biased)};
}

// FRNDINT: ST(0) rounded to an integral value to nearest-even, kept in the extended format. The precision
// control does not apply. Zeros, infinities and values of 2^63 and above are already integral; a value
// that rounds to zero keeps its sign; a NaN is quieted and an unsupported encoding gives the indefinite.
static inline X87Value x87_rndint(X87Value v) {
    if (x87_unsupported(v)) return x87_indefinite;
    if (x87_is_nan(v)) return x87_quiet(v);
    if (x87_exp(v) == 0x7fff || v.sig == 0) return v;
    const int shift = 16383 + 63 - (x87_exp(v) == 0 ? 1 : static_cast<int>(x87_exp(v)));  // v = sig * 2^-shift
    if (shift <= 0) return v;
    uint64_t magnitude = shift >= 64 ? 0 : v.sig >> shift;
    if (shift <= 64) {  // a value below one half (shift > 64) rounds to 0
        const uint64_t rest = shift == 64 ? v.sig : v.sig & ((1ull << shift) - 1);
        const uint64_t half = 1ull << (shift - 1);
        if (rest > half || (rest == half && (magnitude & 1))) ++magnitude;  // rndint round
    }
    const uint16_t sign = v.se & 0x8000;
    if (magnitude == 0) return {0, sign};
    const int lead = x87_clz(magnitude);
    return {magnitude << lead, static_cast<uint16_t>(sign | (16383 + 63 - lead))};
}

// FXTRACT: the significand of v, with v's sign and biased exponent 16383 (a value in [1, 2)), and in
// `exponent` the unbiased exponent as an exact value. A denormal is normalized first. A zero keeps its
// sign and gives an exponent of -inf (the masked divide-by-zero response); an infinity keeps its sign
// and gives +inf. A NaN is quieted into both results, and an unsupported encoding gives the indefinite
// in both. The precision control does not apply.
static inline X87Value x87_xtract(X87Value v, X87Value& exponent) {
    if (x87_unsupported(v)) { exponent = x87_indefinite; return x87_indefinite; }
    if (x87_is_nan(v)) { exponent = x87_quiet(v); return exponent; }
    if (x87_is_inf(v)) { exponent = {x87_integer_bit, 0x7fff}; return v; }
    if (x87_is_zero(v)) { exponent = {x87_integer_bit, 0xffff}; return v; }  // xtract zero
    const X87Unpacked u = x87_unpack(v);
    exponent = x87_from_integer(u.e);
    return {u.sig, static_cast<uint16_t>((u.sign ? 0x8000 : 0) | 16383)};
}

// FSCALE: ST(0) * 2^n with n = ST(1) truncated toward zero. The precision control does not apply: the
// result keeps 64 significand bits and rounds only below the normal range (denormalized at the same
// bit positions) or overflows to infinity. ST(1) = -inf gives a zero and +inf an infinity, both with
// the sign of ST(0); an infinite ST(0) scaled by -inf and a zero scaled by +inf are invalid. A zero or
// infinite ST(0) is otherwise unchanged. NaN and unsupported operands follow x87_special_operands. n is
// clamped to +-2^20, far beyond the exponent range, before it is added to the exponent.
static const X87Format x87_scale_format{64, 16383, 0x7ffe};
static inline X87Value x87_scale(X87Value a, X87Value b) {
    X87Value out;
    if (x87_special_operands(a, b, &out)) return out;
    const uint16_t s = a.se & 0x8000;
    if (x87_is_inf(b)) {
        if (x87_sign(b)) return x87_is_inf(a) ? x87_indefinite : X87Value{0, s};
        return x87_is_zero(a) ? x87_indefinite : X87Value{x87_integer_bit, static_cast<uint16_t>(s | 0x7fff)};
    }
    if (x87_is_zero(a) || x87_is_inf(a)) return a;
    int n = 0;
    if (!x87_is_zero(b)) {
        const X87Unpacked y = x87_unpack(b);
        const int magnitude = y.e >= 20 ? 1 << 20 : y.e >= 0 ? static_cast<int>(y.sig >> (63 - y.e)) : 0;
        n = x87_sign(b) ? -magnitude : magnitude;  // scale truncate
    }
    const X87Unpacked x = x87_unpack(a);
    const X87Rounded r = x87_round(x.sign, x.e + n, x.sig, 0, x87_scale_format, x87_rc);  // scale round
    return {r.sig, static_cast<uint16_t>(s | r.biased)};
}
