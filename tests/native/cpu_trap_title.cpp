// Source-built program for the #UD handler in x2w_launch (tools/x2w_cpu_trap.h), without a C runtime. It
// runs each Zen 2 instruction the handler knows through tests/native/cpu_trap_ops.asm and compares the
// result with a software reference written here from FIPS 180-4 and the AMD APM: SHA-1 and SHA-256 digests
// computed with the SHA-NI instructions against the scalar algorithm and the published digests, random
// vectors per SHA-NI and SSE4a instruction, three memory-operand forms (SIB with REX, RIP-relative with an
// imm8, disp32), and the effects of CLZERO, MOVNTSD/MOVNTSS, RDPID, RDPRU, MONITORX/MWAITX and CLWB.
//
// stdout gets one "case NAME ok|FAIL" line per comparison and "count MNEMONIC N", the number of times each
// instruction ran, for the check to hold against the launcher's trap counts. The exit code is 0x5f when every
// case passed, 0x10 otherwise. X2W_CPUTRAP_WRONG=1 flips a bit of every expected value (every case must then
// fail); X2W_CPUTRAP_UD2=1 ends with a UD2 that no handler performs.
#include <windows.h>
#include <intrin.h>
#include <stddef.h>
#include <stdint.h>

#pragma runtime_checks("", off)

extern "C" void* __cdecl memset(void*, int, size_t);
extern "C" void* __cdecl memcpy(void*, const void*, size_t);
#pragma function(memset, memcpy)
extern "C" void* __cdecl memset(void* destination, int value, size_t bytes) {
    auto* d = static_cast<volatile unsigned char*>(destination);
    while (bytes--) *d++ = static_cast<unsigned char>(value);
    return destination;
}
extern "C" void* __cdecl memcpy(void* destination, const void* source, size_t bytes) {
    auto* d = static_cast<volatile unsigned char*>(destination);
    const auto* s = static_cast<const unsigned char*>(source);
    while (bytes--) *d++ = *s++;
    return destination;
}

extern "C" {
void op_sha1rnds4_0(const void*, const void*, void*);
void op_sha1rnds4_1(const void*, const void*, void*);
void op_sha1rnds4_2(const void*, const void*, void*);
void op_sha1rnds4_3(const void*, const void*, void*);
void op_sha1nexte(const void*, const void*, void*);
void op_sha1msg1(const void*, const void*, void*);
void op_sha1msg2(const void*, const void*, void*);
void op_sha256rnds2(const void*, const void*, void*, const void*);
void op_sha256msg1(const void*, const void*, void*);
void op_sha256msg2(const void*, const void*, void*);
void op_sha256msg1_sib(const void*, const void*, void*, uint64_t);
void op_sha1rnds4_rip(const void*, const void*, void*);
void op_sha1nexte_disp(const void*, const void*, void*);
void op_extrq_16_8(const void*, const void*, void*);
void op_extrq_64_0(const void*, const void*, void*);
void op_extrq_5_59(const void*, const void*, void*);
void op_extrq_reg(const void*, const void*, void*);
void op_insertq_12_20(const void*, const void*, void*);
void op_insertq_64_0(const void*, const void*, void*);
void op_insertq_1_63(const void*, const void*, void*);
void op_insertq_reg(const void*, const void*, void*);
void op_movntsd(const void*, void*);
void op_movntss(const void*, void*);
void op_clzero(void*);
void op_rdpid_rax(uint64_t*);
void op_rdpid_r10(uint64_t*);
void op_rdpru(uint32_t, uint64_t*);
void op_monitorx_mwaitx(const void*, uint64_t*);
void op_clwb(const void*);
void op_ud2();
}

namespace {

// --- Output and bookkeeping ---

HANDLE out_handle;
bool wrong;
unsigned failures;

void put(const char* text) {
    DWORD written = 0;
    DWORD length = 0;
    while (text[length]) ++length;
    WriteFile(out_handle, text, length, &written, nullptr);
}

void put_decimal(uint64_t value) {
    char digits[24];
    int n = 0;
    do {
        digits[n++] = static_cast<char>('0' + value % 10);
        value /= 10;
    } while (value);
    char text[24];
    for (int i = 0; i < n; ++i) text[i] = digits[n - 1 - i];
    text[n] = 0;
    put(text);
}

// Compares got with expected (expected's first bit flipped under X2W_CPUTRAP_WRONG).
void check(const char* name, const void* got, const void* expected, size_t bytes) {
    bool same = true;
    for (size_t i = 0; i < bytes; ++i) {
        unsigned char want = static_cast<const unsigned char*>(expected)[i];
        if (wrong && i == 0) want ^= 1;
        same &= static_cast<const unsigned char*>(got)[i] == want;
    }
    if (!same) ++failures;
    put("case ");
    put(name);
    put(same ? " ok\n" : " FAIL\n");
}

enum Mnemonic {
    kSha1rnds4, kSha1nexte, kSha1msg1, kSha1msg2, kSha256rnds2, kSha256msg1, kSha256msg2, kClzero, kRdpid,
    kMonitorx, kMwaitx, kExtrq, kInsertq, kMovntsd, kMovntss, kRdpru, kClwb, kMnemonics
};
const char* const kNames[kMnemonics] = {"sha1rnds4", "sha1nexte", "sha1msg1", "sha1msg2", "sha256rnds2",
                                        "sha256msg1", "sha256msg2", "clzero", "rdpid", "monitorx", "mwaitx",
                                        "extrq", "insertq", "movntsd", "movntss", "rdpru", "clwb"};
uint64_t counts[kMnemonics];

uint64_t random_state = 0x9e3779b97f4a7c15ull;
uint64_t next_random() {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 7;
    random_state ^= random_state << 17;
    return random_state;
}

struct alignas(16) V {
    uint32_t w[4];  // w[0] is bits 31:0
};

V random_vector() {
    V v;
    for (auto& word : v.w) word = static_cast<uint32_t>(next_random());
    return v;
}

uint32_t rotl(uint32_t x, int n) { return (x << n) | (x >> (32 - n)); }
uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

V add(const V& a, const V& b) {
    V r;
    for (int i = 0; i < 4; ++i) r.w[i] = a.w[i] + b.w[i];
    return r;
}

V xor_(const V& a, const V& b) {
    V r;
    for (int i = 0; i < 4; ++i) r.w[i] = a.w[i] ^ b.w[i];
    return r;
}

// --- Instruction wrappers, counted ---

V sha1rnds4(const V& a, const V& b, int function) {
    V r;
    switch (function) {
    case 0: op_sha1rnds4_0(&a, &b, &r); break;
    case 1: op_sha1rnds4_1(&a, &b, &r); break;
    case 2: op_sha1rnds4_2(&a, &b, &r); break;
    default: op_sha1rnds4_3(&a, &b, &r); break;
    }
    ++counts[kSha1rnds4];
    return r;
}
V sha1nexte(const V& a, const V& b) { V r; op_sha1nexte(&a, &b, &r); ++counts[kSha1nexte]; return r; }
V sha1msg1(const V& a, const V& b) { V r; op_sha1msg1(&a, &b, &r); ++counts[kSha1msg1]; return r; }
V sha1msg2(const V& a, const V& b) { V r; op_sha1msg2(&a, &b, &r); ++counts[kSha1msg2]; return r; }
V sha256rnds2(const V& a, const V& b, const V& wk) {
    V r;
    op_sha256rnds2(&a, &b, &r, &wk);
    ++counts[kSha256rnds2];
    return r;
}
V sha256msg1(const V& a, const V& b) { V r; op_sha256msg1(&a, &b, &r); ++counts[kSha256msg1]; return r; }
V sha256msg2(const V& a, const V& b) { V r; op_sha256msg2(&a, &b, &r); ++counts[kSha256msg2]; return r; }

// --- FIPS 180-4 scalar reference ---

const uint32_t kSha256K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
const uint32_t kSha1K[4] = {0x5a827999, 0x6ed9eba1, 0x8f1bbcdc, 0xca62c1d6};

uint32_t big_sigma0(uint32_t x) { return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22); }
uint32_t big_sigma1(uint32_t x) { return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25); }
uint32_t small_sigma0(uint32_t x) { return rotr(x, 7) ^ rotr(x, 18) ^ (x >> 3); }
uint32_t small_sigma1(uint32_t x) { return rotr(x, 17) ^ rotr(x, 19) ^ (x >> 10); }

uint32_t sha1_f(int t, uint32_t b, uint32_t c, uint32_t d) {
    if (t < 20) return (b & c) ^ (~b & d);
    if (t < 40 || t >= 60) return b ^ c ^ d;
    return (b & c) ^ (b & d) ^ (c & d);
}

// One SHA-1 round on s[0..4] = a..e.
void sha1_round(uint32_t* s, int t, uint32_t w) {
    const uint32_t temp = rotl(s[0], 5) + sha1_f(t, s[1], s[2], s[3]) + s[4] + kSha1K[t / 20] + w;
    s[4] = s[3];
    s[3] = s[2];
    s[2] = rotl(s[1], 30);
    s[1] = s[0];
    s[0] = temp;
}

// One SHA-256 round on s[0..7] = a..h, with kw = K[t] + W[t].
void sha256_round(uint32_t* s, uint32_t kw) {
    const uint32_t t1 = s[7] + big_sigma1(s[4]) + ((s[4] & s[5]) ^ (~s[4] & s[6])) + kw;
    const uint32_t t2 = big_sigma0(s[0]) + ((s[0] & s[1]) ^ (s[0] & s[2]) ^ (s[1] & s[2]));
    for (int i = 7; i > 0; --i) s[i] = s[i - 1];
    s[4] += t1;
    s[0] = t1 + t2;
}

void sha1_scalar(uint32_t* h, const uint32_t* block) {
    uint32_t w[80];
    for (int t = 0; t < 16; ++t) w[t] = block[t];
    for (int t = 16; t < 80; ++t) w[t] = rotl(w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16], 1);
    uint32_t s[5];
    for (int i = 0; i < 5; ++i) s[i] = h[i];
    for (int t = 0; t < 80; ++t) sha1_round(s, t, w[t]);
    for (int i = 0; i < 5; ++i) h[i] += s[i];
}

void sha256_scalar(uint32_t* h, const uint32_t* block) {
    uint32_t w[64];
    for (int t = 0; t < 16; ++t) w[t] = block[t];
    for (int t = 16; t < 64; ++t)
        w[t] = small_sigma1(w[t - 2]) + w[t - 7] + small_sigma0(w[t - 15]) + w[t - 16];
    uint32_t s[8];
    for (int i = 0; i < 8; ++i) s[i] = h[i];
    for (int t = 0; t < 64; ++t) sha256_round(s, kSha256K[t] + w[t]);
    for (int i = 0; i < 8; ++i) h[i] += s[i];
}

// --- The same compressions with SHA-NI (Intel's SHA extensions paper, in lane form) ---

void sha1_ni(uint32_t* h, const uint32_t* block) {
    // M[j] holds W[4j] in lane 3 down to W[4j+3] in lane 0.
    V m[20];
    for (int j = 0; j < 4; ++j)
        for (int k = 0; k < 4; ++k) m[j].w[3 - k] = block[4 * j + k];
    for (int j = 4; j < 20; ++j) m[j] = sha1msg2(xor_(sha1msg1(m[j - 4], m[j - 3]), m[j - 2]), m[j - 1]);
    const V abcd0 = {{h[3], h[2], h[1], h[0]}};
    const V e0 = {{0, 0, 0, h[4]}};
    V abcd = abcd0, previous = abcd0, e = add(e0, m[0]);
    for (int g = 0; g < 20; ++g) {
        if (g) e = sha1nexte(previous, m[g]);
        previous = abcd;
        abcd = sha1rnds4(abcd, e, g / 5);
    }
    const V e_end = sha1nexte(previous, e0);
    abcd = add(abcd, abcd0);
    h[0] = abcd.w[3];
    h[1] = abcd.w[2];
    h[2] = abcd.w[1];
    h[3] = abcd.w[0];
    h[4] = e_end.w[3];
}

void sha256_ni(uint32_t* h, const uint32_t* block) {
    // M[j] holds W[4j] in lane 0 up to W[4j+3] in lane 3.
    V m[16];
    for (int j = 0; j < 4; ++j)
        for (int k = 0; k < 4; ++k) m[j].w[k] = block[4 * j + k];
    for (int j = 4; j < 16; ++j) {
        V t = sha256msg1(m[j - 4], m[j - 3]);
        const V aligned = {{m[j - 2].w[1], m[j - 2].w[2], m[j - 2].w[3], m[j - 1].w[0]}};  // W[4j-7..4j-4]
        m[j] = sha256msg2(add(t, aligned), m[j - 1]);
    }
    const V abef0 = {{h[5], h[4], h[1], h[0]}}, cdgh0 = {{h[7], h[6], h[3], h[2]}};
    V abef = abef0, cdgh = cdgh0;
    for (int j = 0; j < 16; ++j) {
        const V k = {{kSha256K[4 * j], kSha256K[4 * j + 1], kSha256K[4 * j + 2], kSha256K[4 * j + 3]}};
        const V wk = add(m[j], k);
        cdgh = sha256rnds2(cdgh, abef, wk);
        const V high = {{wk.w[2], wk.w[3], 0, 0}};
        abef = sha256rnds2(abef, cdgh, high);
    }
    abef = add(abef, abef0);
    cdgh = add(cdgh, cdgh0);
    h[0] = abef.w[3];
    h[1] = abef.w[2];
    h[4] = abef.w[1];
    h[5] = abef.w[0];
    h[2] = cdgh.w[3];
    h[3] = cdgh.w[2];
    h[6] = cdgh.w[1];
    h[7] = cdgh.w[0];
}

// Pads a message (at most 119 bytes) into one or two blocks of big-endian words; returns the block count.
int pad(const char* message, uint32_t* words) {
    unsigned char bytes[128] = {};
    size_t length = 0;
    while (message[length]) ++length;
    memcpy(bytes, message, length);
    bytes[length] = 0x80;
    const int blocks = length + 9 <= 64 ? 1 : 2;
    const uint64_t bits = static_cast<uint64_t>(length) * 8;
    for (int i = 0; i < 8; ++i) bytes[blocks * 64 - 1 - i] = static_cast<unsigned char>(bits >> (8 * i));
    for (int i = 0; i < blocks * 16; ++i)
        words[i] = (uint32_t{bytes[4 * i]} << 24) | (uint32_t{bytes[4 * i + 1]} << 16)
                   | (uint32_t{bytes[4 * i + 2]} << 8) | bytes[4 * i + 3];
    return blocks;
}

void digests() {
    static const char* const messages[2] = {"abc", "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"};
    static const char* const names[2][3] = {{"sha1-digest-abc", "sha1-scalar-abc", "sha256-digest-abc"},
                                            {"sha1-digest-two-blocks", "sha1-scalar-two-blocks",
                                             "sha256-digest-two-blocks"}};
    static const char* const scalar256[2] = {"sha256-scalar-abc", "sha256-scalar-two-blocks"};
    // FIPS 180-2 appendix examples.
    static const uint32_t known1[2][5] = {{0xa9993e36, 0x4706816a, 0xba3e2571, 0x7850c26c, 0x9cd0d89d},
                                          {0x84983e44, 0x1c3bd26e, 0xbaae4aa1, 0xf95129e5, 0xe54670f1}};
    static const uint32_t known256[2][8] = {
        {0xba7816bf, 0x8f01cfea, 0x414140de, 0x5dae2223, 0xb00361a3, 0x96177a9c, 0xb410ff61, 0xf20015ad},
        {0x248d6a61, 0xd20638b8, 0xe5c02693, 0x0c3e6039, 0xa33ce459, 0x64ff2167, 0xf6ecedd4, 0x19db06c1}};
    for (int m = 0; m < 2; ++m) {
        uint32_t words[32];
        const int blocks = pad(messages[m], words);
        uint32_t ni1[5] = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0}, sc1[5];
        memcpy(sc1, ni1, sizeof sc1);
        uint32_t ni256[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                             0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19}, sc256[8];
        memcpy(sc256, ni256, sizeof sc256);
        for (int b = 0; b < blocks; ++b) {
            sha1_ni(ni1, words + 16 * b);
            sha1_scalar(sc1, words + 16 * b);
            sha256_ni(ni256, words + 16 * b);
            sha256_scalar(sc256, words + 16 * b);
        }
        check(names[m][0], ni1, known1[m], sizeof ni1);
        check(names[m][1], sc1, known1[m], sizeof sc1);
        check(names[m][2], ni256, known256[m], sizeof ni256);
        check(scalar256[m], sc256, known256[m], sizeof sc256);
    }
}

// --- Per-instruction references from the round functions above ---

V ref_sha1rnds4(const V& a, const V& b, int function) {
    uint32_t s[5] = {a.w[3], a.w[2], a.w[1], a.w[0], 0};
    for (int i = 0; i < 4; ++i) sha1_round(s, function * 20, b.w[3 - i]);
    return V{{s[3], s[2], s[1], s[0]}};
}

V ref_sha1nexte(const V& a, const V& b) {
    V r = b;
    r.w[3] += rotl(a.w[3], 30);
    return r;
}

V ref_sha1msg1(const V& a, const V& b) {
    const uint32_t w[6] = {a.w[3], a.w[2], a.w[1], a.w[0], b.w[3], b.w[2]};
    V r;
    for (int k = 0; k < 4; ++k) r.w[3 - k] = w[k] ^ w[k + 2];
    return r;
}

V ref_sha1msg2(const V& a, const V& b) {
    uint32_t w[20];
    w[13] = b.w[2];
    w[14] = b.w[1];
    w[15] = b.w[0];
    for (int k = 0; k < 4; ++k) w[16 + k] = rotl(a.w[3 - k] ^ w[13 + k], 1);
    return V{{w[19], w[18], w[17], w[16]}};
}

V ref_sha256rnds2(const V& a, const V& b, const V& wk) {
    uint32_t s[8] = {b.w[3], b.w[2], a.w[3], a.w[2], b.w[1], b.w[0], a.w[1], a.w[0]};
    sha256_round(s, wk.w[0]);
    sha256_round(s, wk.w[1]);
    return V{{s[5], s[4], s[1], s[0]}};
}

V ref_sha256msg1(const V& a, const V& b) {
    const uint32_t w[5] = {a.w[0], a.w[1], a.w[2], a.w[3], b.w[0]};
    V r;
    for (int k = 0; k < 4; ++k) r.w[k] = w[k] + small_sigma0(w[k + 1]);
    return r;
}

V ref_sha256msg2(const V& a, const V& b) {
    uint32_t w[20];
    w[14] = b.w[2];
    w[15] = b.w[3];
    for (int k = 0; k < 4; ++k) w[16 + k] = a.w[k] + small_sigma1(w[14 + k]);
    return V{{w[16], w[17], w[18], w[19]}};
}

void sha_vectors() {
    bool ok[7] = {true, true, true, true, true, true, true};
    V got[7], want[7];
    for (int i = 0; i < 8; ++i) {
        const V a = random_vector(), b = random_vector(), c = random_vector();
        const V r[7] = {sha1rnds4(a, b, i & 3), sha1nexte(a, b), sha1msg1(a, b), sha1msg2(a, b),
                        sha256rnds2(a, b, c), sha256msg1(a, b), sha256msg2(a, b)};
        const V e[7] = {ref_sha1rnds4(a, b, i & 3), ref_sha1nexte(a, b), ref_sha1msg1(a, b), ref_sha1msg2(a, b),
                        ref_sha256rnds2(a, b, c), ref_sha256msg1(a, b), ref_sha256msg2(a, b)};
        for (int k = 0; k < 7; ++k) {
            // The first mismatch is kept, else the last vector, so check() reports it.
            if (ok[k]) {
                got[k] = r[k];
                want[k] = e[k];
                for (int l = 0; l < 4; ++l) ok[k] &= r[k].w[l] == e[k].w[l];
            }
        }
    }
    static const char* const names[7] = {"sha1rnds4-vectors", "sha1nexte-vectors", "sha1msg1-vectors",
                                         "sha1msg2-vectors", "sha256rnds2-vectors", "sha256msg1-vectors",
                                         "sha256msg2-vectors"};
    for (int k = 0; k < 7; ++k) check(names[k], &got[k], &want[k], sizeof(V));

    // Memory operands.
    const V a = random_vector(), b = random_vector();
    V r;
    op_sha256msg1_sib(&a, &b, &r, 3);
    ++counts[kSha256msg1];
    V e = ref_sha256msg1(a, b);
    check("sha256msg1-sib-rex", &r, &e, sizeof r);
    op_sha1rnds4_rip(&a, &b, &r);
    ++counts[kSha1rnds4];
    e = ref_sha1rnds4(a, b, 2);
    check("sha1rnds4-rip-imm", &r, &e, sizeof r);
    op_sha1nexte_disp(&a, &b, &r);
    ++counts[kSha1nexte];
    e = ref_sha1nexte(a, b);
    check("sha1nexte-disp32-rex", &r, &e, sizeof r);
}

// --- SSE4a, from the APM's bit-field definitions, one bit at a time ---

uint64_t ref_extrq(uint64_t source, unsigned length, unsigned index) {
    if (!length) length = 64;
    uint64_t r = 0;
    for (unsigned i = 0; i < length && index + i < 64; ++i) r |= ((source >> (index + i)) & 1) << i;
    return r;
}

uint64_t ref_insertq(uint64_t destination, uint64_t source, unsigned length, unsigned index) {
    if (!length) length = 64;
    for (unsigned i = 0; i < length && index + i < 64; ++i) {
        const uint64_t bit = 1ull << (index + i);
        destination = (destination & ~bit) | (((source >> i) & 1) << (index + i));
    }
    return destination;
}

struct alignas(16) Q {
    uint64_t low, high;
};

Q random_q() { return Q{next_random(), next_random()}; }

void sse4a() {
    using Op = void (*)(const void*, const void*, void*);
    struct Fixed {
        const char* name;
        Op op;
        bool insert;
        unsigned length, index;
    };
    static const Fixed fixed[6] = {{"extrq-imm-16-8", op_extrq_16_8, false, 16, 8},
                                   {"extrq-imm-64-0", op_extrq_64_0, false, 0, 0},
                                   {"extrq-imm-5-59", op_extrq_5_59, false, 5, 59},
                                   {"insertq-imm-12-20", op_insertq_12_20, true, 12, 20},
                                   {"insertq-imm-64-0", op_insertq_64_0, true, 0, 0},
                                   {"insertq-imm-1-63", op_insertq_1_63, true, 1, 63}};
    for (const auto& f : fixed) {
        uint64_t got[4], want[4];
        for (int i = 0; i < 4; ++i) {
            const Q a = random_q(), b = random_q();
            Q r;
            f.op(&a, &b, &r);
            ++counts[f.insert ? kInsertq : kExtrq];
            // Bits 127:64 of the destination are undefined, so only the low half is compared.
            got[i] = r.low;
            want[i] = f.insert ? ref_insertq(a.low, b.low, f.length, f.index) : ref_extrq(a.low, f.length, f.index);
        }
        check(f.name, got, want, sizeof got);
    }
    uint64_t got[2][16], want[2][16];
    for (int i = 0; i < 16; ++i) {
        const unsigned length = 1 + static_cast<unsigned>(next_random() % 64);  // 1..64
        const unsigned index = static_cast<unsigned>(next_random() % (65 - length));
        const unsigned field = length & 63;  // 64 is encoded as 0
        const Q a = random_q();
        Q control = {field | (uint64_t{index} << 8), 0};
        Q r;
        op_extrq_reg(&a, &control, &r);
        ++counts[kExtrq];
        got[0][i] = r.low;
        want[0][i] = ref_extrq(a.low, field, index);
        const Q source = {next_random(), field | (uint64_t{index} << 8)};
        op_insertq_reg(&a, &source, &r);
        ++counts[kInsertq];
        got[1][i] = r.low;
        want[1][i] = ref_insertq(a.low, source.low, field, index);
    }
    check("extrq-reg-vectors", got[0], want[0], sizeof got[0]);
    check("insertq-reg-vectors", got[1], want[1], sizeof got[1]);

    // MOVNTSD and MOVNTSS store 8 and 4 bytes and nothing around them.
    alignas(16) unsigned char buffer[48], expected[48];
    const Q value = random_q();
    for (int sd = 1; sd >= 0; --sd) {
        memset(buffer, 0xcc, sizeof buffer);
        memset(expected, 0xcc, sizeof expected);
        memcpy(expected + 16, &value, sd ? 8 : 4);
        if (sd) op_movntsd(&value, buffer + 16);
        else op_movntss(&value, buffer + 16);
        ++counts[sd ? kMovntsd : kMovntss];
        check(sd ? "movntsd-store" : "movntss-store", buffer, expected, sizeof buffer);
    }
}

// --- CLZERO, RDPID, RDPRU, MONITORX/MWAITX, CLWB ---

alignas(64) unsigned char line_buffer[4096];
alignas(64) unsigned char line_expected[4096];

bool host_rdtscp() {
    int regs[4];
    __cpuid(regs, static_cast<int>(0x80000000u));
    if (static_cast<unsigned>(regs[0]) < 0x80000001u) return false;
    __cpuid(regs, static_cast<int>(0x80000001u));
    return (regs[3] & (1 << 27)) != 0;
}

void system_ops() {
    // CLZERO: an unaligned address inside the second line, then the third line's start.
    for (int i = 0; i < 256; ++i) line_buffer[i] = line_expected[i] = static_cast<unsigned char>(0xa5 ^ i);
    op_clzero(line_buffer + 64 + 13);
    op_clzero(line_buffer + 128);
    counts[kClzero] += 2;
    memset(line_expected + 64, 0, 128);
    check("clzero-lines", line_buffer, line_expected, 256);

    // RDPID returns TSC_AUX, which RDTSCP also returns; the thread stays on one processor meanwhile.
    const HANDLE thread = GetCurrentThread();
    const DWORD_PTR previous = SetThreadAffinityMask(thread, DWORD_PTR{1} << (GetCurrentProcessorNumber() % 64));
    Sleep(0);
    uint64_t pid[2], aux[2];
    op_rdpid_rax(&pid[0]);
    op_rdpid_r10(&pid[1]);
    counts[kRdpid] += 2;
    for (auto& value : aux) {
        if (host_rdtscp()) {
            unsigned a = 0;
            __rdtscp(&a);
            value = a;
        } else {
            value = GetCurrentProcessorNumber();
        }
    }
    if (previous) SetThreadAffinityMask(thread, previous);
    check("rdpid-tsc-aux", pid, aux, sizeof pid);

    // RDPRU: MPERF (0) and APERF (1) set CF, zero-extend into RAX and RDX and do not go backwards; an
    // unsupported register returns 0 with CF clear.
    uint64_t got[6], want[6] = {1, 1, 1, 1, 0, 0};
    for (uint32_t id = 0; id < 2; ++id) {
        uint64_t first[3], second[3];
        op_rdpru(id, first);
        op_rdpru(id, second);
        counts[kRdpru] += 2;
        const uint64_t a = first[0] | (first[1] << 32), b = second[0] | (second[1] << 32);
        got[2 * id] = first[2] == 1 && second[2] == 1;
        got[2 * id + 1] = (first[0] >> 32) == 0 && (first[1] >> 32) == 0 && b >= a;
    }
    uint64_t other[3];
    op_rdpru(7, other);
    ++counts[kRdpru];
    got[4] = other[0] | other[1];
    got[5] = other[2];
    check("rdpru-mperf-aperf", got, want, sizeof got);

    // MONITORX and MWAITX leave the registers as they were.
    uint64_t regs[4];
    const uint64_t regs_want[4] = {0, 2, 0, 1000};
    op_monitorx_mwaitx(line_buffer + 512, regs);
    ++counts[kMonitorx];
    ++counts[kMwaitx];
    check("monitorx-mwaitx", regs, regs_want, sizeof regs);

    // CLWB changes no memory (a CPU that ran it as XSAVEOPT would write its state into the buffer).
    for (int i = 0; i < 4096; ++i) line_buffer[i] = line_expected[i] = static_cast<unsigned char>(0x3c ^ (i * 7));
    op_clwb(line_buffer + 1024);
    ++counts[kClwb];
    check("clwb-no-write", line_buffer, line_expected, 4096);
}

bool env_set(const char* name) {
    char value[8] = {};
    return GetEnvironmentVariableA(name, value, sizeof value) > 0 && value[0] == '1';
}

}  // namespace

extern "C" DWORD cpu_trap_entry(void*) {
    out_handle = GetStdHandle(STD_OUTPUT_HANDLE);
    wrong = env_set("X2W_CPUTRAP_WRONG");
    digests();
    sha_vectors();
    sse4a();
    system_ops();
    for (int i = 0; i < kMnemonics; ++i) {
        put("count ");
        put(kNames[i]);
        put(" ");
        put_decimal(counts[i]);
        put("\n");
    }
    if (env_set("X2W_CPUTRAP_UD2")) {
        put("control ud2\n");
        op_ud2();
    }
    return failures ? 0x10 : 0x5f;
}
