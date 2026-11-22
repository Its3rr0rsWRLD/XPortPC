// TEXCOORD1..7 are attributes 1 to 7: ATTRIBUTES[n - 1][k] is attribute n at vertex k of the full-screen triangle,
// small integers whose P10 = P1 - P0 and P20 = P2 - P0 are nonzero and differ in every channel. A pixel shader reads
// them flat (v_interp_mov_f32: P0, P10, P20) or interpolated (v_interp_p1/p2_f32): at the centre of pixel (x, y) of a
// 32 by 32 target the barycentrics of vertices 1 and 2 are (2x + 1) / 128 and (2y + 1) / 128, so every term and partial
// sum of P0 + I * P10 + J * P20 (or of I0 * P0 + I * P1 + J * P2) is exact in binary32 and the rasterizer's value is
// the console's bit for bit. The draws read this table (tests/pixel_aot_draws/interp_attrs.py, attribute_vertices);
// rows 1 and 2 are the flat data of check_pkrtz_draws.
// TEXCOORD0 is float4 (from R0Y00/Xbox2Windows#484): xy is the full-screen coordinate, z = 0.25 + 0.5 x and w = 1 - y, so
// that an unsampled program interpolating all four components sees four distinct ramps. A program reading only uv.xy
// declares float2 and sees the same values as before.
// The outputs carry no interpolation modifier: the pixel shader's input declaration picks linear or nointerpolation.
// They follow SV_Position in the struct: a pixel shader that reads SV_Position needs it in the second output register.
struct Vertex { float4 uv : TEXCOORD0; float4 position : SV_Position;
                float4 attr1 : TEXCOORD1; float4 attr2 : TEXCOORD2; float4 attr3 : TEXCOORD3; float4 attr4 : TEXCOORD4;
                float4 attr5 : TEXCOORD5; float4 attr6 : TEXCOORD6; float4 attr7 : TEXCOORD7; };
static const float4 ATTRIBUTES[7][3] = {
    { float4(1, 2, 3, 4), float4(9, 6, 12, 20), float4(5, 17, 11, 2) },
    { float4(7, 13, 21, 34), float4(10, 29, 3, 55), float4(8, 5, 40, 6) },
    { float4(11, 3, 25, 6), float4(14, 27, 7, 1), float4(2, 8, 30, 19) },
    { float4(19, 23, 9, 15), float4(4, 28, 26, 33), float4(30, 12, 1, 8) },
    { float4(5, 40, 17, 27), float4(22, 31, 2, 9), float4(13, 46, 36, 41) },
    { float4(33, 10, 44, 3), float4(26, 35, 47, 24), float4(39, 1, 20, 10) },
    { float4(16, 21, 38, 50), float4(45, 14, 29, 36), float4(18, 52, 57, 23) },
};
// Root parameters: 0 tex, tex1 (t0, t1) and tex2..tex7 (t3..t8, heap offset 50), 1 params (b0), 2 title ranges (t2),
// 3 title memory, 4 range count (b1), 5 title memory UAVs, 6 storage images, 7..9 params1..params3 (b2..b4); point
// samplers samp..samp3 (s0..s3). The extra textures, buffers and samplers are the bindings draws'
// (tests/pixel_aot_draws/bindings.py, docs/design/pixel-bindings.md).
[RootSignature("DescriptorTable(SRV(t0,numDescriptors=2),SRV(t3,numDescriptors=6,offset=50),visibility=SHADER_VISIBILITY_PIXEL),CBV(b0,visibility=SHADER_VISIBILITY_PIXEL),"
               "SRV(t2,visibility=SHADER_VISIBILITY_PIXEL),DescriptorTable(SRV(t0,space=1,numDescriptors=8),visibility=SHADER_VISIBILITY_PIXEL),"
               "RootConstants(num32BitConstants=1,b1,visibility=SHADER_VISIBILITY_PIXEL),"
               "DescriptorTable(UAV(u0,space=1,numDescriptors=8),visibility=SHADER_VISIBILITY_PIXEL),"
               "DescriptorTable(UAV(u0,space=2,numDescriptors=32),visibility=SHADER_VISIBILITY_PIXEL),"
               "CBV(b2,visibility=SHADER_VISIBILITY_PIXEL),CBV(b3,visibility=SHADER_VISIBILITY_PIXEL),CBV(b4,visibility=SHADER_VISIBILITY_PIXEL),"
               "StaticSampler(s0,filter=FILTER_MIN_MAG_MIP_POINT,"
               "addressU=TEXTURE_ADDRESS_CLAMP,addressV=TEXTURE_ADDRESS_CLAMP,addressW=TEXTURE_ADDRESS_CLAMP),"
               "StaticSampler(s1,filter=FILTER_MIN_MAG_MIP_POINT,"
               "addressU=TEXTURE_ADDRESS_CLAMP,addressV=TEXTURE_ADDRESS_CLAMP,addressW=TEXTURE_ADDRESS_CLAMP),"
               "StaticSampler(s2,filter=FILTER_MIN_MAG_MIP_POINT,"
               "addressU=TEXTURE_ADDRESS_CLAMP,addressV=TEXTURE_ADDRESS_CLAMP,addressW=TEXTURE_ADDRESS_CLAMP),"
               "StaticSampler(s3,filter=FILTER_MIN_MAG_MIP_POINT,"
               "addressU=TEXTURE_ADDRESS_CLAMP,addressV=TEXTURE_ADDRESS_CLAMP,addressW=TEXTURE_ADDRESS_CLAMP)")]
Vertex main(uint id : SV_VertexID)
{
    Vertex v;
    // Vertices 3, 4 and 5 (the --check-pixel-quad-lod draw) are the same corners scaled to a partial triangle.
    const bool partial = id >= 3;
    const uint corner = partial ? id - 3 : id;
    float2 xy = float2((corner << 1) & 2, corner & 2) * (partial ? 7.75f / 16.0f : 1.0f);
    v.uv = float4(xy, 0.25f + 0.5f * xy.x, 1.0f - xy.y);
    v.attr1 = ATTRIBUTES[0][corner];
    v.attr2 = ATTRIBUTES[1][corner];
    v.attr3 = ATTRIBUTES[2][corner];
    v.attr4 = ATTRIBUTES[3][corner];
    v.attr5 = ATTRIBUTES[4][corner];
    v.attr6 = ATTRIBUTES[5][corner];
    v.attr7 = ATTRIBUTES[6][corner];
    v.position = float4(xy * float2(2,-2) + float2(-1,1), 0, 1);
    return v;
}
