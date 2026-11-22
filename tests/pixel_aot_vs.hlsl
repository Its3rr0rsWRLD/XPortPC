// Attributes 1 and 2 are flat data for v_interp_mov_f32: the value at vertex 0, 1 and 2 of the full-screen triangle, so
// that P0, P10 = P1 - P0 and P20 = P2 - P0 are distinct small integers in every channel (see check_pkrtz_draws).
// They follow SV_Position in the struct: a pixel shader that reads SV_Position needs it in the second output register.
struct Vertex { float2 uv : TEXCOORD0; float4 position : SV_Position;
                nointerpolation float4 flat1 : TEXCOORD1; nointerpolation float4 flat2 : TEXCOORD2; };
static const float4 FLAT1[3] = { float4(1, 2, 3, 4), float4(9, 6, 12, 20), float4(5, 17, 11, 2) };
static const float4 FLAT2[3] = { float4(7, 13, 21, 34), float4(10, 29, 3, 55), float4(8, 5, 40, 6) };
[RootSignature("DescriptorTable(SRV(t0,numDescriptors=2),visibility=SHADER_VISIBILITY_PIXEL),CBV(b0,visibility=SHADER_VISIBILITY_PIXEL),"
               "SRV(t2,visibility=SHADER_VISIBILITY_PIXEL),DescriptorTable(SRV(t0,space=1,numDescriptors=8),visibility=SHADER_VISIBILITY_PIXEL),"
               "RootConstants(num32BitConstants=1,b1,visibility=SHADER_VISIBILITY_PIXEL),StaticSampler(s0,filter=FILTER_MIN_MAG_MIP_POINT,"
               "addressU=TEXTURE_ADDRESS_CLAMP,addressV=TEXTURE_ADDRESS_CLAMP,addressW=TEXTURE_ADDRESS_CLAMP)")]
Vertex main(uint id : SV_VertexID)
{
    Vertex v;
    // Vertices 3, 4 and 5 (the --check-pixel-quad-lod draw) are the same corners scaled to a partial triangle.
    const bool partial = id >= 3;
    const uint corner = partial ? id - 3 : id;
    v.uv = float2((corner << 1) & 2, corner & 2) * (partial ? 7.75f / 16.0f : 1.0f);
    v.flat1 = FLAT1[corner];
    v.flat2 = FLAT2[corner];
    v.position = float4(v.uv * float2(2,-2) + float2(-1,1), 0, 1);
    return v;
}
