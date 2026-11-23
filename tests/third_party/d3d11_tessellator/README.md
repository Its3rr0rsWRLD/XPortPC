# D3D11 reference tessellator

`tessellator.cpp` and `tessellator.hpp` are Microsoft's D3D11 fixed-function tessellator reference (`CHWTessellator`,
"D3D11 Tessellation Fixed Function Hardware Reference"), copied unchanged from Mesa 26.2.6
(`src/gallium/auxiliary/tessellator/`, where llvmpipe uses it; the release tarball `mesa-26.2.6.tar.xz` from
https://archive.mesa3d.org/). Copyright (c) Microsoft Corporation, MIT license: the notice is at the top of each file.
SHA-256 of the two files as copied:

| File | SHA-256 |
|---|---|
| tessellator.cpp | c5c986fe2c31ccb674e6c980895d5adc93cd1d24990d9354b5e63a876355db36 |
| tessellator.hpp | 14fcefcf31d9afbbd894e088f56b0c77f7c235f1fbe8a5043b295f7e05cecb8d |

`util/macros.h` is a one-macro shim for the `UNREACHABLE` the file includes from Mesa. `tests/tess_reference.cpp`
wraps the tessellator as a command-line tool for `tests/tess_aot_check.py` (docs/design/stages.md, card T-1, the
tessellator check).
