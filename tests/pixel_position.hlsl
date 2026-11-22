// Match the full-screen vertex fixture's output order for D3D12 linkage.
float4 main(float4 uv : TEXCOORD0, float4 position : SV_Position) : SV_Target0
{
    const float alpha = uv.x >= 0.0f ? 1.0f : 0.0f;
#ifdef SWAP_XY
    return float4(position.yx, 0.25f, alpha);
#else
    return float4(position.xy, 0.25f, alpha);
#endif
}
