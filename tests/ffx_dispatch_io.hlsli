#include "../src/rgb9e5.hlsli"
#include "../src/ffx_float_to_int.hlsli"

#define SCRATCH_ROOT "UAV(u11)"
#define PRODUCER_ROOT "DescriptorTable(UAV(u2), UAV(u1), UAV(u6)), SRV(t3), SRV(t9), UAV(u11), UAV(u12)"
#define CONSUMER_ROOT "DescriptorTable(SRV(t18), UAV(u11))"

// The two read-only producer fixtures use RGB DWORD triples at integer coordinates.
ByteAddressBuffer sceneInput : register(t3);
ByteAddressBuffer historyInput : register(t9);
RWTexture2D<float4> historyOutput : register(u1);
RWTexture2D<float4> recurrent : register(u6);
RWTexture2D<float4> finalOutput : register(u11);
RWByteAddressBuffer work : register(u11);
RWByteAddressBuffer loadTrace : register(u12);
void audit_load(uint2 cell, uint tap, uint address, uint4 value) {
    uint slot = ((cell.y*4 + cell.x)*9 + tap)*20;
    loadTrace.Store(slot,address);
    loadTrace.Store4(slot+4,value);
}
uint mul_high(uint a, uint b) {
    uint middle = (a>>16)*(b&65535u) + (((a&65535u)*(b&65535u))>>16);
    return (a>>16)*(b>>16) + (middle>>16) + (((middle&65535u)+(a&65535u)*(b>>16))>>16);
}
#if STORAGE_Packed
RWTexture2D<uint> target16 : register(u2);
Texture2D<uint> source16 : register(t18);
void write16(uint2 p, float4 value) { target16[p] = pack_rgb9e5(value.rgb); }
float4 load16(uint2 p) { return unpack_rgb9e5(source16.Load(int3(p, 0))); }
#else
RWTexture2D<float4> target16 : register(u2);
Texture2D<float4> source16 : register(t18);
void write16(uint2 p, float4 value) { target16[p] = value; }
float4 load16(uint2 p) { return source16.Load(int3(p, 0)); }
#endif

int median_i(int a, int b, int c) { return max(min(a,b), min(max(a,b),c)); }
float median_f(float a, float b, float c) { return max(min(a,b), min(max(a,b),c)); }
uint insert_byte(uint old, uint lane, uint value) {
    return (old & ~(255u << (8*lane))) | (value << (8*lane));
}
uint bfe_u(uint src, uint offset, uint width) {
    uint count = min(width, 32u);
    return count != 0u ? (src >> (offset & 31u)) & (0xffffffffu >> ((32u - count) & 31u)) : 0u;
}
int bfe_i(uint src, uint offset, uint width) {
    uint count = min(width, 32u);
    uint shift = (32u - count) & 31u;
    int shifted = asint(src) >> (offset & 31u);
    return count != 0u ? (asint(uint(shifted) << shift) >> shift) : 0;
}
uint sadd_u(uint a, uint b, out uint scc) {
    uint r = a + b;
    scc = r < a ? 1u : 0u;
    return r;
}
uint slshl4_add_u(uint a, uint b, out uint scc) {
    uint shifted = a << 4;
    uint r = shifted + b;
    scc = ((a >> 28) != 0u || r < shifted) ? 1u : 0u;
    return r;
}
uint sadd_i(uint a, uint b, out uint scc) {
    uint r = a + b;
    scc = (~(a ^ b) & (a ^ r)) >> 31;
    return r;
}
uint ssub_i(uint a, uint b, out uint scc) {
    uint r = a - b;
    scc = ((a ^ b) & (a ^ r)) >> 31;
    return r;
}
uint smin_u(uint a, uint b, out uint scc) {
    scc = a < b ? 1u : 0u;
    return scc != 0u ? a : b;
}
uint smax_u(uint a, uint b, out uint scc) {
    scc = a > b ? 1u : 0u;
    return scc != 0u ? a : b;
}
uint smin_i(uint a, uint b, out uint scc) {
    scc = asint(a) < asint(b) ? 1u : 0u;
    return scc != 0u ? a : b;
}
uint smax_i(uint a, uint b, out uint scc) {
    scc = asint(a) > asint(b) ? 1u : 0u;
    return scc != 0u ? a : b;
}
uint sabs_i(uint a, out uint scc) {
    uint r = asint(a) < 0 ? 0u - a : a;
    scc = r != 0u ? 1u : 0u;
    return r;
}
int idot(uint a, uint b, int sum) {
    [unroll] for (int i=0; i<4; ++i) {
        sum += (asint(a << (24-8*i)) >> 24) * (asint(b << (24-8*i)) >> 24);
    }
    return sum;
}
