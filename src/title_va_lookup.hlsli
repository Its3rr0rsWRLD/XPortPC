// Shader-side lookup of title GPU addresses (host side: src/era_title_va.h).
// On the console a shader can load through a 64-bit address read from memory, because a
// graphics allocation's CPU pointer is also its GPU address. On desktop each aliased
// allocation is a separate buffer, so the shader finds the range holding the address and
// loads through that range's buffer at the byte offset. Ranges come from
// era_title_gpu::shader_view: sorted by title address, non-overlapping, each shorter than
// 4 GiB and starting on a 4-byte boundary, with `slot` naming the descriptor of the buffer that
// aliases the range and `base` the byte offset of the range's first byte in that buffer (several
// ranges of one xmem arena or physical page pool share a buffer; base + size never exceeds 4 GiB).
// Raw buffer operations move whole DWORDs, so a lookup is for an access of
// `bytes` bytes (a multiple of 4) at a 4-byte-aligned address, and succeeds only when the whole
// access lies inside one range.
// Addresses are uint2 values: x is the low 32 bits, y the high 32 bits.
#ifndef TITLE_VA_LOOKUP_HLSLI
#define TITLE_VA_LOOKUP_HLSLI

struct TitleRange {
    uint2 begin;
    uint2 end;  // exclusive
    uint slot;
    uint base;  // byte offset of `begin` in the slot's buffer (0 when the buffer aliases only this range)
};

bool TitleAddressLess(uint2 a, uint2 b)
{
    return a.y < b.y || (a.y == b.y && a.x < b.x);
}

// Returns false when the address is not 4-byte aligned, `bytes` is zero or not a multiple of 4,
// or no single range holds all of [address, address + bytes). Otherwise sets the range's slot
// and the byte offset of `address` in the slot's buffer.
bool TitleLookup(StructuredBuffer<TitleRange> ranges, uint count, uint2 address, uint bytes,
                 out uint slot, out uint offset)
{
    slot = 0;
    offset = 0;
    if ((address.x & 3) != 0 || bytes == 0 || (bytes & 3) != 0) {
        return false;
    }
    uint low = 0;
    uint high = count;
    // First range whose begin is above the address.
    while (low < high) {
        const uint middle = (low + high) / 2;
        if (TitleAddressLess(address, ranges[middle].begin)) {
            high = middle;
        } else {
            low = middle + 1;
        }
    }
    if (low == 0) {
        return false;
    }
    const TitleRange range = ranges[low - 1];
    if (!TitleAddressLess(address, range.end)) {
        return false;
    }
    // Both differences are below 4 GiB, so the low words' differences modulo 2^32 are exact.
    const uint size = range.end.x - range.begin.x;
    const uint start = address.x - range.begin.x;
    if (bytes > size || start > size - bytes) {
        return false;
    }
    offset = range.base + start;
    slot = range.slot;
    return true;
}

#endif
