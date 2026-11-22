# XPortPC

**Based on Xbox2Windows**

(This version is because I've got agents working on it fast, which does better alone)

XPortPC converts Xbox Series X|S (Scarlett) programs to run on Windows PCs. Scarlett titles are already x64 code, so XPortPC loads them natively and replaces what only exists on the console: the system libraries, the GPU shaders and the GPU memory model. Only the CPU code that needs patching is translated.

The center of the project is the shader converter. It translates gfx1013 (RDNA) shader programs into HLSL and then into desktop DXIL. Every supported instruction form is checked on real hardware and on WARP: each draw is compared bit for bit against an independent CPU reference, and wrong references must fail. The converter is meant to work for any title, so nothing in it is tied to one game.
| Area | Result on Windows | Open question or contribution |
|---|---|---|
| FidelityFX upscaler | The recompiled provider creates 11 resources at 720p → 1080p and a twelfth with the debug flag. On RTX 4060 Laptop and WARP, both the per-resource indices and the returned loader and provider handles passed. Recompiled graph pass 26 wrote the RCAS intermediate and the recompiled RCAS shader read it with five integer texel loads per output. Passes 24 and 25 supplied all 72 scratch reads on the 8×4 tile. Both adapters passed the zero and nonzero input comparisons through the final 256 pixels. [Scratch writers](docs/experiments.md#last-writers-of-the-pass-26-scratch-reads) · [Dispatch trace and replay](docs/experiments.md#fsr4-dispatch-through-the-rcas-input) · [RCAS format test](docs/experiments.md#rcas-intermediate-texel-access) · [Provider loop and desktop mappings](docs/experiments.md#provider-resource-loop-and-returned-handles) · [Recurrent texture pixel readback](docs/experiments.md#recurrent-texture-views-and-pixel-readback) | Exercise the full-wave LDS path of pass 26 with a larger tile using the verified scratch producers. |
| x64 context callbacks | The recompiled FidelityFX loader destroy function calls the bound provider and preserves its 32-bit result across both cleanup paths on Windows. The upscaler slot was identified in the local package. [Provider and Windows comparison](docs/experiments.md#fidelityfx-destroy-provider-and-cleanup) | Verify the upscaler's internal effect teardown with a successfully created graphics context. |
| CPU translation | The [source-built EXE](docs/experiments.md#source-built-exe-entry-to-a-dll-import) matches native import arguments, output bytes and process status on both branches. A [leaf function](docs/experiments.md#offline-cpu-leaf-recompilation), a [direct call](docs/experiments.md#recompiling-a-direct-x64-call), a caller that calls one callee twice or two different callees, and cross-DLL imports [by name](docs/experiments.md#calling-another-dll-through-a-named-pe-import) and [by ordinal](docs/experiments.md#calling-an-ordinal-only-export) match the original fixtures on Windows. [Switch dispatch through jump tables](docs/experiments.md#switch-dispatch-through-jump-tables) in the MSVC and LLVM layouts, including from a loop, matches the original fixture on Windows. The same translator lifts `SETcc` and `CMOVcc` that read the flags of an earlier compare or test in the same straight-line run, and matches the original fixture on Windows. [VEX.128 16-bit packed-integer leaf functions](docs/experiments.md#vex128-16-bit-packed-integer-leaf-functions) match the original fixture bit for bit, including with the output aliasing an input. The import fixtures and a relocated variant also run from an image [mapped without LoadLibrary](docs/experiments.md#mapping-an-image-without-loadlibrary), with imports bound through a host resolver. Mapped images also handle SEH and receive TLS-callback and entry-point notifications in the order Windows uses. The [recompiled Bink allocation and release callers](docs/experiments.md#bink-allocation-and-release-on-the-windows-heap) passed size, alignment, null fallback and release checks on Windows. Blocks allocated through a custom callback retained their release function after callback replacement. A grouped caller rounds a prefix to 32 bytes and places payload pointers inside the allocation or in caller-owned slots. The [frame allocator](docs/experiments.md#frame-buffers-through-the-shared-windows-heap) now reaches the shared Windows heap with success, injected failure and retry checks. | Trace the producer of odd tagged strides. |
| Shader translation | Supported pixel programs sample a texture, read constants, apply arithmetic, and export color. Arithmetic coverage includes absolute-value operands and `v_trunc_f32` rounding toward zero. All 16 floating-point comparison predicates have D3D12 readback coverage, including NaN inputs. D3D12 readback is checked against a CPU reference. [Translation and bindings](docs/experiments.md#offline-pixel-shader-recompilation) | Supply a source-built instruction case with known register inputs and an expected color. |
| BC7 textures | A translated shader samples recovered mip levels on hardware and WARP. Requests for missing high-resolution levels use the first resident level. [Mip fallback tests](docs/experiments.md#drawing-bc7-textures-with-a-recompiled-pixel-shader) | Match a variable BCPack lane against independently known BC7 blocks. [Issue #15](https://github.com/R0Y00/Xbox2Windows/issues/15) |
| Script states | A native x64 probe follows state-tree links and reproduces distinct camera limits for front and rear selections. The replay supplies the selection requests. [State replay](docs/experiments.md#state-linked-settings-in-a-script-archive) | Identify an event or caller that supplies a context and state ID, with a control input that takes a different branch. [Issue #19](https://github.com/R0Y00/Xbox2Windows/issues/19) |
| Windows runtime and GPU | Source-built checks cover PE imports, heap operations, root signatures, compute and ray tracing. 19 Radeon GPU models passed the native wave64 BVH test. [Hardware coverage](#hardware-coverage) · [Experiment notes](docs/experiments.md) | Share a run on a new adapter or a driver retest in [the hardware thread](https://github.com/R0Y00/Xbox2Windows/issues/1). |

[![Instruction-form coverage of source-built fixtures, not a measure of port completion](docs/coverage/dashboard.svg)](tools/coverage_svg.py)

Live status: <https://xportpc.3rr0r.cc>

## What works today

| Part | State |
|---|---|
| Native launcher | `x2w_launch.exe` maps a program with `pe_map` and resolves each import from a shim directory, a DLL beside the program, Windows, or a generated stub that logs its first call. Tested with source-built programs. |
| Console library shims | Desktop `xmem.dll` (graphics and heap memory). |
| Shader converter | Texture sampling, constants, binary32 arithmetic and comparisons, SDWA selections, 32-bit integer bitwise ops, shifts and byte converts, and scalar ALU. Coverage is in the badge above. |
| GPU memory | Pixel draws can bind title memory: 64-bit title addresses resolve at runtime to desktop buffers. Buffer and global loads are in progress. |
| Not yet | Stores, LDS, image stores, the command stream, and a full title start. |

The test suite builds all of its own fixtures. No console, SDK or game files are needed to build or test.

## First build

On x64 Windows, install Visual Studio's **Desktop development with C++** workload, including x64 MSVC, the C++ CMake tools with Ninja, and Windows SDK 10.0.26100 with DXC. From the repository root in PowerShell, run:

```powershell
.\tools\dev.ps1
cmake --preset dev
cmake --build --preset dev
ctest --preset dev --no-tests=error -R 'desktop_root_signature|era_heap_allocation|offscreen_warp'
```

These three tests exercise a D3D12 root signature, heap allocation and software rendering. CMake warns when the Python executable for the remaining fixture tests is missing. To enable the CPU, script, shader, texture and PE fixture tests, install x64 Python 3.11 or newer and configure again. Windows CI uses Python 3.12.

```powershell
python -m venv out/pe-env
.\out\pe-env\Scripts\python.exe -m pip install -r requirements-dev.txt
cmake --preset dev
cmake --build --preset dev
ctest --preset dev --no-tests=error
```

To build and test at /O2 as Windows CI also does, use the `release` preset in place of `dev`. Its build directory is `out/build/release`.

`shader_metadata_probe` also needs a DXC validator that accepts module-only validation. The DXC 1.7.2308 shipped with the original Windows SDK 10.0.26100 refuses it with `call_hr 0x80070057`, as do releases 1.8.2403 through 1.8.2407, and the test then reports a skip. A serviced SDK can include a newer validator: Windows SDK 10.0.26100.8249 installs DXC 1.8.2502.11, which passes without a separate download. [DXC 1.8.2502](https://github.com/microsoft/DirectXShaderCompiler/releases/tag/v1.8.2502) is the first release that passes, and the later 1.8 and 1.9 releases through 1.9.2609 pass too. To use a release, extract its zip and configure with `cmake --preset dev -DDXC_EXECUTABLE=C:/path/to/dxc/bin/x64/dxc.exe`. `root_probe` loads `dxil.dll` from the same directory. [Report](https://github.com/R0Y00/Xbox2Windows/issues/98) · [Results by release](docs/experiments.md#module-only-validation-by-dxc-release)

On Windows 10 the in-box D3D12 runtime and WARP lack SM 6.5 and DXR, so the BVH and DXR WARP checks skip. To run them, configure with the app-local Agility SDK and WARP packages. [Windows 10 setup](docs/experiments.md#windows-10-with-the-app-local-agility-sdk-and-warp)

An independent contributor passed all three smoke tests from a clean checkout of `71bb9f4` on Windows 11 build 26300.9974 with VS Build Tools 2022 17.14 and Windows SDK 10.0.26100. The tests passed again after an incremental rebuild at `2465837`. With Python 3.14.10, the full suite had 66 and 68 tests respectively, with zero failures in either run. Each run skipped forced wave64 on the RTX 5080 and WARP because their reported lane ranges excluded 64. [Original clean-build report](https://github.com/R0Y00/Xbox2Windows/issues/2#issuecomment-7063351821)

Contributing from macOS or Linux? See the [non-Windows host guide](docs/non-windows-hosts.md) for the platform-independent Python and LLVM 15 checks.

## Working on XPortPC

Work is split into small batches of instruction forms. Each batch adds the lowering, draws on hardware and WARP compared against a CPU reference, wrong-reference controls, an LLVM 15 binary round trip, and a paragraph in [docs/experiments.md](docs/experiments.md). Run the GPU checks with:

```powershell
ctest --preset dev --no-tests=error -R '^pixel_' -V
```

The shader-draw checks are one CTest test per draw family and adapter, `pixel_aot_<family>_hardware` and `pixel_aot_<family>_warp`, plus `pixel_aot_controls`. `python tests/pixel_aot_check.py --list-families` prints the families; each family is a module of `tests/pixel_aot_draws/`, found by listing that directory, and CMake picks a new one up when it next configures (see [docs/design/module-layout.md](docs/design/module-layout.md)).

Do not add game files, dumps, distribution links or credentials to the repository, issues or pull requests.

## Hardware reports

Build the suite, run `.\tools\package-gpu-check.ps1` to make the standalone GPU check, run it, and paste the full contents of `gpu-report-hardware.md` as a comment on the [hardware thread](https://github.com/Its3rr0rsWRLD/XPortPC/issues/1). Do not open a new GitHub issue. Reports with a failure or a capability skip are welcome.

On a PC with more than one GPU, use `.\Run-GpuCheck.ps1 -Adapter Radeon` to select a hardware adapter by part of its name. For source builds, set `XBOX2WINDOWS_ADAPTER` before running CTest (the variable keeps its upstream name).

## FAQ

**Is XPortPC an Xbox emulator?** No. An emulator such as Xenia (Xbox 360) runs console code inside a simulated console. Xbox Series X|S titles are already x64 code for an AMD Zen 2 CPU, so XPortPC runs that code natively on Windows and converts only what is console-specific: the GPU shaders (RDNA gfx10 machine code to HLSL and DXIL for DirectX 12), the console's graphics and memory libraries, and the rest of the platform layer.

**Can it run Xbox Series X|S games on PC today?** Not yet. The shader converter, GPU memory loads and the native launcher work and are tested on real GPUs with source-built programs; control flow, the console Direct3D 12 layer and the system libraries are in progress. The coverage badge above shows the current instruction coverage.

**Do I need an Xbox, the GDK or game files to help?** No. Every test builds its own fixtures. A Windows PC with Visual Studio and a DirectX 12 GPU is enough, and hardware reports from any GPU help.

**Does XPortPC include or download games?** No, and it never will. Do not post game files, dumps or links to them.

**Which GPUs are tested?** Each instruction form is drawn on real hardware and on Microsoft WARP and compared bit for bit with a CPU reference. Hardware reports from NVIDIA, AMD and Intel GPUs are collected in issue #1.

## Based on Xbox2Windows

XPortPC started from [Xbox2Windows](https://github.com/R0Y00/Xbox2Windows) by R0Y00 and its contributors, and keeps its full history. We merge upstream changes into XPortPC regularly. Upstream's experiment notes remain in [docs/experiments.md](docs/experiments.md). Names such as `x2w_` in the code come from upstream and are kept so merges stay simple.

## License

MIT, as in upstream. The [LICENSE](LICENSE) keeps the Xbox2Windows contributors' copyright notice and adds XPortPC's. Third-party games, assets, SDKs and trademarks belong to their owners. XPortPC is an independent community project, not affiliated with Microsoft, Xbox or AMD.
