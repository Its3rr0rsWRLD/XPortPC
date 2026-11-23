#include "sys_gdeflate.h"

#include <cstdint>
#include <cstring>
#include <vector>

#include "GDeflate.h"
#include "TileStream.h"

namespace x2w_sys::ds {

bool gdeflate_decompress(const void* in, size_t in_size, void* out, size_t out_size) {
    constexpr size_t kTile = GDeflate::kDefaultTileSize;
    if (!in || !out || !out_size || in_size < sizeof(GDeflate::TileStream)) return false;
    GDeflate::TileStream header(0);
    std::memcpy(&header, in, sizeof header);
    if (!header.IsValid() || header.id != GDeflate::kGDeflateId || header.tileSizeIdx != 1 || header.numTiles == 0)
        return false;
    const size_t tiles = header.numTiles;
    if (header.GetUncompressedSize() != out_size) return false;
    const size_t table = tiles * sizeof(uint32_t);
    if (in_size - sizeof header < table) return false;
    const size_t data_size = in_size - sizeof header - table;
    // Offsets: entry 0 is the size of the last tile, entry i >= 1 the start of tile i; tile 0 starts at 0.
    std::vector<uint32_t> offsets(tiles);
    std::memcpy(offsets.data(), static_cast<const uint8_t*>(in) + sizeof header, table);
    uint64_t previous = 0;
    for (size_t i = 1; i < tiles; ++i) {
        if (offsets[i] < previous || offsets[i] > data_size) return false;
        previous = offsets[i];
    }
    if (previous + offsets[0] > data_size) return false;

    // The reference decoder always writes whole 64 KiB tiles, so a short final tile needs a scratch buffer.
    if (out_size == tiles * kTile)
        return GDeflate::Decompress(static_cast<uint8_t*>(out), out_size, static_cast<const uint8_t*>(in), in_size, 2);
    std::vector<uint8_t> scratch(tiles * kTile);
    if (!GDeflate::Decompress(scratch.data(), scratch.size(), static_cast<const uint8_t*>(in), in_size, 2)) return false;
    std::memcpy(out, scratch.data(), out_size);
    return true;
}

}  // namespace x2w_sys::ds
