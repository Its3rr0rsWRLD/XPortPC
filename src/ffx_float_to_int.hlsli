// The highest binary32 values below the positive endpoints are 2^32-256
// and 2^31-128. Keep even speculatively evaluated casts in range.
uint cvt_u32_f32(uint bits) {
    float x = asfloat((bits & 0x7fffffffu) > 0x7f800000u ? 0u : bits);
    float finite = clamp(x, 0.0f, 4294967040.0f);
    return x >= 4294967296.0f ? 0xffffffffu : uint(finite);
}

uint cvt_i32_f32(uint bits) {
    float x = asfloat((bits & 0x7fffffffu) > 0x7f800000u ? 0u : bits);
    float finite = clamp(x, -2147483648.0f, 2147483520.0f);
    return x >= 2147483648.0f ? 0x7fffffffu : asuint(int(finite));
}
