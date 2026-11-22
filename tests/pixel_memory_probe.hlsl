// Control shader for the pixel harness's title memory binding. Hand-written, not translated.
// Constant words 0..7 are four title addresses (low word, high word). Each channel loads the
// word at its address through TitleLookup and returns its low byte, or -1 for a miss.
#include "title_va_lookup.hlsli"

cbuffer Constants : register(b0) { uint4 words[16]; };
StructuredBuffer<TitleRange> ranges : register(t2);
ByteAddressBuffer title_memory[8] : register(t0, space1);
cbuffer Memory : register(b1) { uint range_count; };

float Probe(uint2 address)
{
    uint slot;
    uint offset;
    if (!TitleLookup(ranges, range_count, address, 4, slot, offset)) return -1.0;
    return float(title_memory[NonUniformResourceIndex(slot)].Load(offset) & 0xff);
}

// Same inputs as the harness's vertex shader outputs, so the stages link.
float4 main(float2 uv : TEXCOORD0, float4 position : SV_Position) : SV_Target
{
    return float4(Probe(words[0].xy), Probe(words[0].zw), Probe(words[1].xy), Probe(words[1].zw));
}
