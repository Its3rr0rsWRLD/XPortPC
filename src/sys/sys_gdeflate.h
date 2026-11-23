// GDeflate (DirectStorage compression format 1) CPU decoder over Microsoft's public reference implementation,
// vendored under third_party/gdeflate (Apache-2.0 GDeflate sources over NVIDIA's libdeflate fork, MIT with
// Apache-2.0 additions; notices in third_party/gdeflate/NOTICE.md). No platform headers here.
#pragma once

#include <cstddef>

namespace x2w_sys::ds {

// Decodes one GDeflate stream (8-byte tile-stream header, tile offset table, tiles of 64 KiB) of `in_size` bytes
// into exactly `out_size` bytes. The header and offsets are validated against both sizes before the reference
// decoder runs, so a damaged or mismatched stream fails instead of reading or writing outside the buffers.
// Matches ds::Decompressor.
bool gdeflate_decompress(const void* in, size_t in_size, void* out, size_t out_size);

}  // namespace x2w_sys::ds
