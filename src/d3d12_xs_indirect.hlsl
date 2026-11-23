// GPU rewrite of title GPU addresses in indirect argument records (d3d12_xs_indirect.h), compiled at build time into
// d3d12_xs.dll. One thread per record: the record is copied from `source` to `dest`, and every 64-bit address field
// is translated through the sorted ranges (title begin, title end, desktop begin) the shim snapshots from xmem.dll at
// record time. An address no range holds is copied unchanged, as the shim does for API addresses
// (pipeline::translate_address): it is a desktop address or invalid. A record that does not fit in the source
// buffer's remaining bytes is written as zeros; desktop D3D12 never reads it (the title's count buffer or maximum
// excludes it, or the title's call is out of bounds).
struct Range {
    uint2 title_begin;
    uint2 title_end;  // exclusive
    uint2 gpu_begin;
};

cbuffer Params : register(b0)
{
    uint command_count;
    uint stride;      // bytes per record, a multiple of 4
    uint limit;       // bytes of `source` that hold records
    uint range_count;
    uint field_count; // at most 16
    uint3 unused;
    uint4 fields[4];  // byte offsets of the address fields in a record, 4-byte aligned
};

ByteAddressBuffer source : register(t0);
StructuredBuffer<Range> ranges : register(t1);
RWByteAddressBuffer dest : register(u0);

bool Below(uint2 a, uint2 b)
{
    return a.y < b.y || (a.y == b.y && a.x < b.x);
}

uint2 Translate(uint2 address)
{
    uint low = 0;
    uint high = range_count;
    while (low < high) {  // first range whose begin is above the address
        const uint middle = (low + high) / 2;
        if (Below(address, ranges[middle].title_begin)) {
            high = middle;
        } else {
            low = middle + 1;
        }
    }
    if (low == 0) {
        return address;
    }
    const Range range = ranges[low - 1];
    if (!Below(address, range.title_end)) {
        return address;
    }
    const uint offset_low = address.x - range.title_begin.x;
    const uint offset_high = address.y - range.title_begin.y - (address.x < range.title_begin.x ? 1u : 0u);
    const uint low_word = range.gpu_begin.x + offset_low;
    const uint carry = low_word < offset_low ? 1u : 0u;
    return uint2(low_word, range.gpu_begin.y + offset_high + carry);
}

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    const uint record = id.x;
    if (record >= command_count) {
        return;
    }
    const uint base = record * stride;
    const bool inside = stride <= limit && record <= (limit - stride) / stride;
    for (uint word = 0; word < stride; word += 4) {
        dest.Store(base + word, inside ? source.Load(base + word) : 0u);
    }
    if (!inside) {
        return;
    }
    for (uint f = 0; f < field_count; ++f) {
        const uint at = base + fields[f / 4][f % 4];
        dest.Store2(at, Translate(source.Load2(at)));
    }
}
