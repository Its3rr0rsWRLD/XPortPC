// Desktop shaders of tests/runtime/d3d12_full.cpp: positions from the input assembler, the colour from a root CBV.
// Both buffers are title memory that ExecuteIndirect records name by title GPU address.
cbuffer Colour : register(b0)
{
    float4 colour;
};

float4 VSMain(float2 position : POSITION) : SV_Position
{
    return float4(position, 0.0f, 1.0f);
}

float4 PSMain() : SV_Target
{
    return colour;
}
