#pragma once
#include <stdexcept>
#include <d3d12.h>
#include <stdexcept>
#include <wrl/client.h>

void check(HRESULT hr, const char* stage);
// CheckFeatureSupport, routed through ID3D12Device16::CheckFeatureSupport1 with the app-local Agility
// SDK version when one is configured. The debug layer reports D3D12 989 for the unversioned call there.
HRESULT check_feature(ID3D12Device* device, D3D12_FEATURE feature, void* data, UINT size);
Microsoft::WRL::ComPtr<ID3D12Resource> resource(ID3D12Device* device, const D3D12_RESOURCE_DESC& desc,
    D3D12_HEAP_TYPE heap, D3D12_RESOURCE_STATES state, const D3D12_CLEAR_VALUE* clear = nullptr);
void check_compute(ID3D12Device* device, bool tables);
void check_sampler_views(ID3D12Device* device, const char* shader_path);
void check_spirv_window(ID3D12Device* device, const char* shader_path);
void check_compute_file(ID3D12Device* device, const char* path, bool conversion_pair, const char* reference = nullptr);
void check_ffx_device_init(ID3D12Device* device);
void check_ffx_recurrent(ID3D12Device* device);
void check_dual_uav(ID3D12Device* device);
enum class MeshConstantBinding { root, root_pair, swapped_root_pair, table, swapped_table };
enum class MeshDrawMode { color, textured, depth_pair };
struct MeshTextureProducers {
    const char* first;
    const char* second;
    bool bind_first;
};
bool check_mesh_entry_draw(ID3D12Device*, const char*, const char*, const char*, bool,
                           MeshConstantBinding = MeshConstantBinding::root,
                           MeshDrawMode = MeshDrawMode::color,
                           const MeshTextureProducers* = nullptr);
bool check_mesh_fallback_draw(ID3D12Device* device, const char* compute, const char* vertex,
                              const char* pixel, const char* fixture);
void check_texture_mips(ID3D12Device* device);
void check_depth_mask_draw(ID3D12Device*, const char*, const char*, const char*, bool);
void check_sampled_coverage(ID3D12Device*, const char*, const char*);
void check_dual_pixel(ID3D12Device*, const char*, const char*, bool);
// A malformed case file: the checker exits 2, like other bad arguments.
struct BadCase : std::runtime_error { using std::runtime_error::runtime_error; };
struct PixelMismatch : std::runtime_error {
    PixelMismatch() : std::runtime_error("AOT color export differs from CPU reference") {}
};
// A translated dispatch whose memory or storage images differ from the reference (--check-compute-batch reports it
// as status=mismatch; the single-case path exits 1 as for any failure).
struct ComputeMismatch : std::runtime_error { using std::runtime_error::runtime_error; };

void check_translated_pixel(ID3D12Device* device, const char* path, bool swapRB, const char* reference = nullptr,
                            UINT8 writeMask = D3D12_COLOR_WRITE_ENABLE_ALL);
void check_translated_compute(ID3D12Device* device, const char* shader, const char* reference);
void check_translated_pixel_mips(ID3D12Device* device, const char* path, const char* reference);
void check_attribute_pixel(ID3D12Device* device, const char* shader, const char* reference, bool rg);
void check_compute_to_pixel(ID3D12Device* device, const char* compute, const char* pixel,
                            const char* reference, const char* previous);
void check_pixel_quad_lod(ID3D12Device* device, const char* shader);
void check_pixel_outputs(ID3D12Device* device, const char* path, const char* reference);
// A translated vertex shader drawn as a point list, its stream output compared with a case (tests/vertex_aot_render.cpp).
void check_translated_vertex(ID3D12Device* device, const char* shader, const char* reference);
void check_translated_geometry(ID3D12Device* device, const char* shader, const char* geometry, const char* reference);
// Translated vertex, hull and domain shaders drawn as a patch list; the domain shader's stream output written to a file.
void capture_translated_tess(ID3D12Device* device, const char* vertex, const char* hull, const char* domain,
                             const char* reference, const char* output);
void check_bc7_pixel(ID3D12Device* device, const char* shader, const char* input,
                     const char* capture, const char* mip1 = nullptr);
void check_bc7_tail(ID3D12Device* device, const char* shader, const char* firstMip, int count, char** paths);
void check_bvh_root_roundtrip(ID3D12Device* device);
void check_buffer_ops(ID3D12Device* device);
void check_bvh_reads(ID3D12Device* device);
void check_bvh_atomics(ID3D12Device* device);
void check_bvh_numeric(ID3D12Device* device);
void check_bvh_packed(ID3D12Device* device);
void check_bvh_hits(ID3D12Device* device);
bool check_bvh_differential(ID3D12Device* device, bool forcePipeline);
bool check_bvh_waves(ID3D12Device* device, bool force64);
bool check_gpu_alias(ID3D12Device* device);
bool check_gpu_alias_lookup(ID3D12Device* device);
bool check_gpu_alias_lookup_writes(ID3D12Device* device);
bool check_gpu_alias_registry(ID3D12Device* device);
bool check_wave_shuffle(ID3D12Device* device);
bool check_dxr_rays(ID3D12Device* device, bool usePipeline);
bool check_bvh_shuffle(ID3D12Device* device, unsigned forced_width);
bool check_dxr_update(ID3D12Device* device);
bool check_dxr_facing(ID3D12Device* device);
bool check_dxr_opacity(ID3D12Device* device, bool warp);

Microsoft::WRL::ComPtr<ID3D12Resource> make_buffer(ID3D12Device* device, UINT64 length, D3D12_HEAP_TYPE heap,
    D3D12_RESOURCE_STATES state, D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE);
void transition(ID3D12GraphicsCommandList* list, ID3D12Resource* buffer,
                D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after);

struct ComputeCommands {
    ComputeCommands(ID3D12Device* device, ID3D12PipelineState* pipeline,
                    D3D12_COMMAND_LIST_TYPE type = D3D12_COMMAND_LIST_TYPE_COMPUTE);
    void submit_and_wait(ID3D12Device* device);
    Microsoft::WRL::ComPtr<ID3D12CommandQueue> queue;
    Microsoft::WRL::ComPtr<ID3D12CommandAllocator> allocator;
    Microsoft::WRL::ComPtr<ID3D12GraphicsCommandList> list;
};
