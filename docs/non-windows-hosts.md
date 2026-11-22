# Contributing from macOS and Linux

Xbox2Windows targets x64 Windows for its C++, HLSL, MASM, D3D12, WARP, and GPU test suite. Contributors on macOS and Linux can still edit documentation, run the platform-independent Python checks, and run the LLVM 15 `gfx1013` shader translation checks locally before handing off Windows verification.

## Platform split

| Work or check | macOS / Linux | x64 Windows | Notes |
|---|---|---|---|
| Documentation edits | Yes | Yes | Markdown, diff hygiene, and link checks (`tests/docs_links_check.py`). |
| Platform-independent Python checks | Yes | Yes | The commands below cover the [Linux CI workflow](../.github/workflows/windows.yml), the BC7 block reference and the GPU report formatter. |
| LLVM 15 `gfx1013` translation checks | Yes | No (via CI / separate LLVM) | `tests/pixel_aot_check.py binary`, `tests/ffx_dispatch_aot_check.py`, and `tests/rdna2_tools_check.py` (with `LLVM_LIB`, `LLVM_MC`, `LLVM_OBJCOPY`) verify assembling, disassembling, and lowering only. |
| `cmake --preset dev` build (MSVC `cl` + Ninja) | No | Yes | `CMakePresets.json` selects `cl`. |
| MASM fixtures (`tests/cpu/*.asm`) and `cpu_*` tests | No | Yes | Assembled and built by the Windows toolchain. |
| DXC compilation and rendering (the `pixel_aot_<family>_warp` and `pixel_aot_<family>_hardware` tests) | No | Yes | Requires Windows SDK / DXC (`dxc.exe`, `dxil.dll`) and D3D12. |
| D3D12, WARP, and DXR tests (`*_warp`, `*_hardware`) | No | Yes | Covers software WARP and physical GPU checks. |
| System32 PE export inventory (`tools/pe_inventory.py`) | No | Yes | Uses `ctypes.windll` on Windows. |
| Standalone GPU check packaging (`tools/package-gpu-check.ps1`) | No | Yes | Builds and smoke-tests the Windows x64 ZIP package. |

`tests/pixel_aot_check.py binary`, `tests/ffx_dispatch_aot_check.py`, and `tests/rdna2_tools_check.py` do not invoke DXC or render pixels; desktop HLSL compilation and readback (the `pixel_aot_<family>_warp` and `pixel_aot_<family>_hardware` tests) remain Windows-only.

## Quick start on macOS

Install Python 3.12 and LLVM 15 with Homebrew (both are needed as explicit paths because `llvm@15` is keg-only):

```bash
brew install python@3.12 llvm@15
```

From the repository root, create a virtual environment under `out/pe-env`, install `pefile` at the version pinned in `requirements-dev.txt`, and run the platform-independent checks below:

```bash
"$(brew --prefix python@3.12)/bin/python3.12" -m venv out/pe-env
./out/pe-env/bin/python -m pip install -c requirements-dev.txt pefile
for t in \
  tests/script_state_check.py \
  tests/resource_root_check.py \
  tests/bcpack_check.py \
  tests/bc7_blocks_check.py \
  tests/form_coverage_check.py \
  tests/resource_ranges_check.py \
  tests/awc_metadata_check.py \
  tests/sgd5_effects_check.py \
  tests/dxcontainer_part_offsets_check.py \
  tests/layout_chunks_check.py \
  tests/dependency_paths_check.py \
  tests/intake/paths_check.py \
  tests/shader_probe_check.py \
  tests/dxil_retarget_check.py \
  tests/rdna2_tools_check.py \
  tests/pso_readiness_check.py \
  tests/docs_links_check.py \
  tests/bidi_controls_check.py \
  tests/gpu_report_format_check.py; do
  ./out/pe-env/bin/python -B "$t"
done
```

Then run the three LLVM 15 `gfx1013` checks:

```bash
LLVM_PREFIX="$(brew --prefix llvm@15)"
./out/pe-env/bin/python -B tests/pixel_aot_check.py binary \
  "$LLVM_PREFIX/bin/llvm-mc" "$LLVM_PREFIX/bin/llvm-objcopy" "$LLVM_PREFIX/lib/libLLVM-15.dylib"
./out/pe-env/bin/python -B tests/ffx_dispatch_aot_check.py \
  "$LLVM_PREFIX/bin/llvm-mc" "$LLVM_PREFIX/bin/llvm-objcopy" "$LLVM_PREFIX/lib/libLLVM-15.dylib"
LLVM_LIB="$LLVM_PREFIX/lib/libLLVM-15.dylib" \
  LLVM_MC="$LLVM_PREFIX/bin/llvm-mc" \
  LLVM_OBJCOPY="$LLVM_PREFIX/bin/llvm-objcopy" \
  ./out/pe-env/bin/python -B tests/rdna2_tools_check.py
```

## Quick start on Linux

The [CI workflow](../.github/workflows/windows.yml) runs the platform-independent Python suite on Ubuntu 24.04 with Python 3.12 (`python-linux`) and the `gfx1013` machine-code checks on Ubuntu 22.04 with LLVM 15 (`pixel-binary`).

From the repository root, create `out/pe-env` (Python 3.11 or newer; CI uses 3.12), install dependencies, and run the platform-independent checks below:

```bash
python3 -m venv out/pe-env
./out/pe-env/bin/python -m pip install -r requirements-dev.txt
for t in \
  tests/script_state_check.py \
  tests/resource_root_check.py \
  tests/bcpack_check.py \
  tests/bc7_blocks_check.py \
  tests/form_coverage_check.py \
  tests/resource_ranges_check.py \
  tests/awc_metadata_check.py \
  tests/sgd5_effects_check.py \
  tests/dxcontainer_part_offsets_check.py \
  tests/layout_chunks_check.py \
  tests/dependency_paths_check.py \
  tests/intake/paths_check.py \
  tests/shader_probe_check.py \
  tests/dxil_retarget_check.py \
  tests/rdna2_tools_check.py \
  tests/pso_readiness_check.py \
  tests/xmem_attribute_scan_check.py \
  tests/docs_links_check.py \
  tests/bidi_controls_check.py \
  tests/gpu_report_format_check.py; do
  ./out/pe-env/bin/python -B "$t"
done
```

On Debian/Ubuntu, install LLVM 15 and run the three `gfx1013` checks:

```bash
sudo apt-get update -q
sudo apt-get install -y --no-install-recommends llvm-15
./out/pe-env/bin/python -B tests/pixel_aot_check.py binary \
  llvm-mc-15 llvm-objcopy-15 libLLVM-15.so.1
./out/pe-env/bin/python -B tests/ffx_dispatch_aot_check.py \
  llvm-mc-15 llvm-objcopy-15 libLLVM-15.so.1
LLVM_LIB=libLLVM-15.so.1 LLVM_MC=llvm-mc-15 LLVM_OBJCOPY=llvm-objcopy-15 \
  ./out/pe-env/bin/python -B tests/rdna2_tools_check.py
```

## Expected CMake failure and no-stub policy

`CMakePresets.json` sets `CMAKE_CXX_COMPILER` to `cl` for the `dev` preset. Running `cmake --preset dev` on macOS or Linux is expected to fail:

```text
-- The CXX compiler identification is unknown
CMake Error at CMakeLists.txt:2 (project):
  The CMAKE_CXX_COMPILER:

    cl

  is not a full path and was not found in the PATH.
```

Do not work around this by stubbing `cl`, MASM, D3D12, or WARP to make CMake configure succeed on non-Windows hosts. Full compilation and runtime tests require x64 Windows.

## WSL and Linux translation layers

- **WSL:** You can run the Linux Python and LLVM 15 checks inside WSL, while the CMake, MSVC, DXC, and D3D12 build still runs from Windows PowerShell as documented in [First build](../README.md#first-build).
- **Linux GPU Check via Proton:** A contributor recorded a passing run of the standalone Windows GPU Check on CachyOS with an RTX 3060 through Proton and `vkd3d-proton` in [the hardware coverage thread](https://github.com/R0Y00/Xbox2Windows/issues/1#issuecomment-7064204388). If you report a translation-layer run of the standalone GPU Check in `#1`, include the commit or release tag, GPU model, Mesa or NVIDIA driver version, Proton and `vkd3d-proton` versions, and each subtest's output (including skips).
- A native Linux runtime is outside the scope of this guide and remains a separate request from the x64 Windows target.

## Troubleshooting

- **Homebrew `llvm@15` is keg-only:** Homebrew does not symlink `llvm@15` binaries into `PATH` by default. Pass `"$(brew --prefix llvm@15)"` explicitly instead of calling bare `llvm-mc`.
- **Shared library filename (`libLLVM-15.dylib` vs `libLLVM-15.so.1`):** Pass `libLLVM-15.dylib` from `"$(brew --prefix llvm@15)/lib"` on macOS, and `libLLVM-15.so.1` on Ubuntu/Debian.
- **LLVM versions newer than 15:** CI and the test fixtures target LLVM 15. Newer LLVM versions may print a different `exp` instruction spelling during AMDGPU disassembly.
- **`tests/shader_probe_check.py` and `tests/dxil_retarget_check.py` with vs without arguments:** Running either script with no arguments runs its platform-independent controls (`shader_metadata_controls` and `dxil_retarget_controls`). Passing compiled `.cso` shaders, `root_probe`, and `dxil.dll` (`shader_metadata_probe`, `dxil_retarget_probe`) requires Windows and DXC.
- **`tests/rdna2_tools_check.py` skips one test without `LLVM_LIB`:** Without `LLVM_LIB`, the script runs its pure-Python disassembler, extractor, and scanner checks and skips `test_llvm_comparison`. Setting `LLVM_LIB`, `LLVM_MC`, and `LLVM_OBJCOPY` runs the LLVM 15 comparison check as well.
- **`tools/pe_inventory.py` fails to import `ctypes.windll`:** `pe_inventory.py` inspects System32 exports on x64 Windows and is not supported on macOS or Linux.
- **Keep virtual environments out of Git:** Create the Python environment at `out/pe-env`, which is already ignored via `/out/` in `.gitignore`.

## Evidence and Windows verification handoff

Follow [Share a reproducible finding](../CONTRIBUTING.md#share-a-reproducible-finding) and [AGENTS.md](../AGENTS.md) when preparing a pull request or issue from a non-Windows host:

- Record the exact commit SHA under test, host OS and architecture, Python and LLVM versions, exact commands run, and observed results.
- State clearly that Windows C++, HLSL, WARP, and hardware checks were not run locally when contributing from macOS or Linux, and rely on the `build-and-test` CI job or a Windows contributor to verify Windows behavior.
- Never include game files, dumps, `.exe`/`.dll` binaries, torrents, distribution links, personal paths, or credentials in issues, pull requests, or Git.
