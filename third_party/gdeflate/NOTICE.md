# GDeflate reference decoder and encoder (vendored)

Used by `src/sys` for the DirectStorage CPU fallback (compression format 1, GDeflate) and by the tests to create
GDeflate fixtures with the same reference encoder. Unmodified copies of public upstream files.

| Directory | Upstream | Revision | Licence |
|---|---|---|---|
| `gdeflate/` | https://github.com/microsoft/DirectStorage, `GDeflate/GDeflate/` (`GDeflate.h`, `GDeflateCompress.cpp`, `GDeflateDecompress.cpp`, `TileStream.h`, `Utils.h`, `config.h`) | default branch as of 2026-11-23; the repository pins libdeflate below | Apache-2.0 (`gdeflate/LICENSE`, as in the upstream directory; copyright NVIDIA CORPORATION & AFFILIATES and Microsoft Corporation, SPDX headers kept in each file) |
| `libdeflate/` | https://github.com/NVIDIA/libdeflate (a fork of https://github.com/ebiggers/libdeflate), `lib/`, `common/`, `libdeflate.h`, `COPYING` | `8ba9502fb30d2bf728592d121f0d402e40c8cb05`, the commit the DirectStorage repository pins as its `GDeflate/3rdparty/libdeflate` submodule | MIT, Copyright 2016 Eric Biggers (`libdeflate/COPYING`); the NVIDIA additions (GDEFLATE support: `lib/gdeflate_*`, parts of `lib/deflate_*`, `lib/decompress_template.h`...) carry SPDX Apache-2.0 headers and are covered by `gdeflate/LICENSE` |

The microsoft/DirectStorage repository's own licence is MIT (Copyright Microsoft Corporation); its `GDeflate/`
directory carries the Apache-2.0 file above. Only the GDeflate sources are copied: none of the DirectStorage
binaries, headers, samples or the repository's NOTICES file (which covers other components, some under LGPL) are
part of this repository.

Built as the static library `x2w_gdeflate` (`cmake/x2w_sys.cmake`) with the compiler-warning suppressions Microsoft's own
CMake build uses. Local code that wraps it is `src/sys/sys_gdeflate.cpp` (stream validation before decoding, a
scratch buffer for a short last tile) and `tests/sys/gdeflate_pack.cpp`. These files are Apache-2.0 / MIT-compatible
with the repository's MIT licence; keep this notice and the two licence files when redistributing.
