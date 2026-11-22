struct Vertex { float2 uv : TEXCOORD0; float4 position : SV_Position; };
[RootSignature("DescriptorTable(SRV(t0,numDescriptors=2),visibility=SHADER_VISIBILITY_PIXEL),CBV(b0,visibility=SHADER_VISIBILITY_PIXEL),"
               "SRV(t2,visibility=SHADER_VISIBILITY_PIXEL),DescriptorTable(SRV(t0,space=1,numDescriptors=8),visibility=SHADER_VISIBILITY_PIXEL),"
               "RootConstants(num32BitConstants=1,b1,visibility=SHADER_VISIBILITY_PIXEL),StaticSampler(s0,filter=FILTER_MIN_MAG_MIP_POINT,"
               "addressU=TEXTURE_ADDRESS_CLAMP,addressV=TEXTURE_ADDRESS_CLAMP,addressW=TEXTURE_ADDRESS_CLAMP)")]
Vertex main(uint id : SV_VertexID)
{
    Vertex v;
    v.uv = float2((id << 1) & 2, id & 2);
    v.position = float4(v.uv * float2(2,-2) + float2(-1,1), 0, 1);
    return v;
}
