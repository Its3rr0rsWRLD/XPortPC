// Independent, source-built non-uniform WaveReadLaneAt permutation probe.
// Does not use the BVH scan or any title-specific input. One 64-thread group
// contains complete waves for widths 4, 8, 16, 32 and 64.
StructuredBuffer<uint4> inputs : register(t0);
RWByteAddressBuffer output : register(u0);

#ifdef FORCE_WAVE_SIZE
[WaveSize(FORCE_WAVE_SIZE)]
#endif
[RootSignature("SRV(t0),UAV(u0)")]
[numthreads(64, 1, 1)]
void ShuffleProbe(uint t : SV_GroupIndex, uint group : SV_GroupID)
{
    uint4 q = inputs[group * 64 + t];
    uint value = q.x;
    uint lane = WaveGetLaneIndex();
    uint width = WaveGetLaneCount();

    // Affine routing is deliberately not an involution at widths 16/32/64.
    // The inverse must be measured separately to diagnose an inverted shuffle.
    uint affine = (lane * 7u + 3u) % width;
    uint inverse = 0;
    for (uint candidate = 0; candidate < width; ++candidate) {
        if ((candidate * 7u + 3u) % width == lane) {
            inverse = candidate;
            break;
        }
    }
    uint dynamicIndex = q.z % width;
    uint p = (group * 64u + t) * 64u;
    output.Store4(p, uint4(lane, width, WaveReadLaneFirst(t), value));
    output.Store4(p + 16u, uint4(affine, WaveReadLaneAt(value, affine),
                                 inverse, WaveReadLaneAt(value, inverse)));
    output.Store4(p + 32u, uint4(WaveReadLaneAt(value, (lane + 1u) % width),
                                 WaveReadLaneAt(value, width - 1u - lane),
                                 WaveReadLaneAt(value, lane ^ (width / 2u)),
                                 WaveReadLaneAt(value, lane)));
    output.Store4(p + 48u, uint4(dynamicIndex, WaveReadLaneAt(value, dynamicIndex),
                                 WaveReadLaneAt(value, width - 1u),
                                 WaveReadLaneFirst(value)));
}
