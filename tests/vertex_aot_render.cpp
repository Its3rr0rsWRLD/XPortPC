// Draw check for translated vertex shaders (cards V-1 to V-3, docs/design/vertex-stage.md "Testing bit-exactly"), and
// for translated vertex and geometry shader pairs (card G-1, docs/design/stages.md): the same case file with a GS
// output count in header word 20, drawn as a triangle list whose GS output stream output captures.
// The translated VS runs over a point list with no pixel shader. Stream output captures SV_Position and every
// TEXCOORDn of each vertex in draw order, and every captured dword is compared bit for bit with the case's reference.
// The draw is issued with base vertex and start instance 0; the console's base-vertex and start-instance user SGPRs
// reach the shader as root constants (b2), its inline push-constant words as 32 more (b3).
#include "bvh_fixture.h"
#include <algorithm>
#include <climits>
#include <fstream>
#include <iterator>
#include <string>

using namespace bvh_fixture;

namespace {
// Case file, little-endian 32-bit words:
//   header[32]: magic 'X2WV', vertices per instance V, indexed (0 or 1), base vertex (b2 word 0), param count P
//               (0..8), the P TEXCOORD indices (ascending, below 32) in words 5..12, instance count I (1..),
//               start instance (b2 word 1), push-word count W (0..32), distance-vector count D (0..2), the D
//               distance codes in words 17..18 (kind << 8 | semantic index; kind 1 SV_ClipDistance, 2
//               SV_CullDistance; index 0 or 1), the constant word count C in word 19 (0 for 64, else a multiple of 4
//               from 64 to 16384: at most 4096 uint4, a D3D12 constant buffer), the geometry output count G in word
//               20 (0: a vertex case; else V is a multiple of 3 drawn as a triangle list through the GS, with I 1,
//               not indexed, no distance vectors, and G records captured, at most 4096), then zero words; V * I is at
//               most 4096
//   constants[C]: the b0 words (constant-buffer data)
//   descriptors[64]: the b4 words (runtime V# words)
//   push[W]: the b3 words (the rest of the 32 are zero)
//   indices[V] if indexed: the R32 index buffer, one index per vertex of an instance
//   expected[V * I * 4 * (1 + D + P)] (G * 4 * (1 + P) for a geometry case): per record (instance-major, or in GS
//               append order) SV_Position.xyzw, each distance vector's xyzw,
//               then each TEXCOORD's xyzw, in header order
//   mask[same count]: the bits of each dword that are compared (0 for a channel the shader exported as `off`)
//   then optionally the 'X2WM' title-memory section of tests/pixel_aot_render.cpp.
constexpr UINT magic = 0x56573258u;
constexpr UINT maxRecords = 4096;
constexpr UINT maxParams = 8;
constexpr UINT headerWords = 32;
constexpr UINT pushWords = 32;
constexpr UINT maxConstantWords = 4096 * 4;

struct TitleRangeRecord {
    UINT64 begin, end;
    UINT slot, reserved;
};
static_assert(sizeof(TitleRangeRecord) == 24);

struct VertexCase {
    UINT records = 0, baseVertex = 0, instances = 1, startInstance = 0, geometryRecords = 0;
    bool indexed = false;
    std::vector<UINT> params, distances;
    std::vector<Word> constants = std::vector<Word>(64), descriptors = std::vector<Word>(64);
    std::vector<Word> push = std::vector<Word>(pushWords);
    std::vector<UINT> indices;
    std::vector<Word> expected, mask;
    std::vector<TitleRangeRecord> ranges;
    std::vector<std::vector<BYTE>> slots;
};

// The memory section of the pixel harness (tests/pixel_aot_render.cpp, parse_memory_section), with the same rules:
// magic 'X2WM', range count and slot count (0..8 each), a zero word, the ranges, then each slot as a size and bytes.
void parse_memory(const char* data, size_t size, VertexCase& out)
{
    size_t at = 0;
    const auto word = [&](const char* what) {
        if (size - at < 4) throw BadCase(std::string("Memory section is truncated at ") + what);
        UINT value;
        std::memcpy(&value, data + at, 4);
        at += 4;
        return value;
    };
    if (word("magic") != 0x4d573258u) throw BadCase("Memory section has the wrong magic");
    const UINT rangeCount = word("range count"), slotCount = word("slot count");
    if (rangeCount > 8 || slotCount > 8) throw BadCase("Memory section has more than 8 ranges or slots");
    if (word("reserved") != 0) throw BadCase("Memory section reserved word is not zero");
    for (UINT i = 0; i < rangeCount; ++i) {
        if (size - at < sizeof(TitleRangeRecord)) throw BadCase("Memory section is truncated in the ranges");
        TitleRangeRecord range;
        std::memcpy(&range, data + at, sizeof(range));
        at += sizeof(range);
        out.ranges.push_back(range);
    }
    for (UINT i = 0; i < slotCount; ++i) {
        const UINT bytes = word("slot size");
        if (bytes % 4 || bytes > (1u << 20)) throw BadCase("Memory slot size is not a multiple of 4 or exceeds 1 MiB");
        if (size - at < bytes) throw BadCase("Memory section is truncated in a slot");
        out.slots.emplace_back(data + at, data + at + bytes);
        at += bytes;
    }
    if (at != size) throw BadCase("Memory section has trailing bytes");
    for (size_t i = 0; i < out.ranges.size(); ++i) {
        const auto& range = out.ranges[i];
        if (range.reserved != 0) throw BadCase("Memory range reserved word is not zero");
        if (range.begin % 4 || range.begin >= range.end)
            throw BadCase("Memory range is empty, reversed or not 4-byte aligned");
        if (range.end - range.begin >= (UINT64(1) << 32)) throw BadCase("Memory range is 4 GiB or larger");
        if (range.slot >= slotCount) throw BadCase("Memory range names a slot that does not exist");
        if (range.end - range.begin > out.slots[range.slot].size())
            throw BadCase("Memory range is larger than its slot");
        if (i && out.ranges[i - 1].end > range.begin) throw BadCase("Memory ranges are unsorted or overlap");
    }
}

VertexCase read_case(const char* path)
{
    std::ifstream file(path, std::ios::binary);
    const std::vector<char> bytes{std::istreambuf_iterator<char>(file), {}};
    if (file.bad()) throw BadCase("Cannot read the vertex case");
    size_t at = 0;
    const auto words = [&](size_t count, const char* what) {
        if ((bytes.size() - at) / 4 < count) throw BadCase(std::string("Vertex case is truncated in ") + what);
        std::vector<UINT> out(count);
        if (count) std::memcpy(out.data(), bytes.data() + at, count * 4);
        at += count * 4;
        return out;
    };
    const auto header = words(headerWords, "the header");
    if (header[0] != magic) throw BadCase("Vertex case has the wrong magic");
    VertexCase c;
    c.records = header[1];
    if (!c.records || c.records > maxRecords) throw BadCase("Vertex case record count is 0 or above 4096");
    if (header[2] > 1) throw BadCase("Vertex case indexed flag is not 0 or 1");
    c.indexed = header[2] == 1;
    c.baseVertex = header[3];
    const UINT params = header[4];
    if (params > maxParams) throw BadCase("Vertex case has more than 8 parameters");
    for (UINT i = 0; i < maxParams; ++i) {
        if (i < params) {
            if (header[5 + i] >= 32 || (i && header[5 + i] <= header[4 + i]))
                throw BadCase("Vertex case parameter indices are not ascending below 32");
            c.params.push_back(header[5 + i]);
        } else if (header[5 + i]) {
            throw BadCase("Vertex case unused parameter index is not zero");
        }
    }
    c.instances = header[13];
    if (!c.instances || c.instances > maxRecords || size_t(c.records) * c.instances > maxRecords)
        throw BadCase("Vertex case instance count is 0 or the draw exceeds 4096 records");
    c.startInstance = header[14];
    const UINT push = header[15], distances = header[16];
    if (push > pushWords) throw BadCase("Vertex case has more than 32 push words");
    if (distances > 2) throw BadCase("Vertex case has more than 2 distance vectors");
    for (UINT i = 0; i < 2; ++i) {
        const UINT code = header[17 + i];
        if (i < distances) {
            if ((code >> 8 != 1 && code >> 8 != 2) || (code & 0xff) > 1)
                throw BadCase("Vertex case distance code is not clip or cull 0 or 1");
            for (UINT seen : c.distances)
                if (seen == code) throw BadCase("Vertex case distance codes repeat");
            c.distances.push_back(code);
        } else if (code) {
            throw BadCase("Vertex case unused distance code is not zero");
        }
    }
    c.geometryRecords = header[20];
    if (c.geometryRecords) {
        if (c.geometryRecords > maxRecords) throw BadCase("Geometry case output count is above 4096");
        if (c.records % 3 || c.instances != 1 || c.indexed || distances)
            throw BadCase("Geometry case is not one non-indexed triangle list without distance vectors");
    }
    for (UINT i = 21; i < headerWords; ++i)
        if (header[i]) throw BadCase("Vertex case reserved header words are not zero");
    const UINT constantWords = header[19] ? header[19] : 64;
    if (constantWords < 64 || constantWords > maxConstantWords || constantWords % 4)
        throw BadCase("Vertex case constant word count is not a multiple of 4 from 64 to 16384");
    c.constants = words(constantWords, "the constants");
    c.descriptors = words(64, "the descriptors");
    const auto pushed = words(push, "the push words");
    std::copy(pushed.begin(), pushed.end(), c.push.begin());
    if (c.indexed) c.indices = words(c.records, "the indices");
    const size_t dwords = size_t(c.geometryRecords ? c.geometryRecords : c.records * c.instances) * 4 *
                          (1 + distances + params);
    c.expected = words(dwords, "the expected outputs");
    c.mask = words(dwords, "the compare mask");
    if (at != bytes.size()) parse_memory(bytes.data() + at, bytes.size() - at, c);
    return c;
}

ComPtr<ID3D12RootSignature> vertex_root(ID3D12Device* device, D3D12_SHADER_VISIBILITY visibility)
{
    // b0 constants, t2 title ranges, t0..t7 space1 title memory, b1 range count, b2 base vertex and start instance,
    // b3 push words, b4 V# words; visible to the VS.
    D3D12_DESCRIPTOR_RANGE memory{D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 8, 0, 1, 0};
    D3D12_ROOT_PARAMETER params[7]{};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    params[0].Descriptor = {0, 0};
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
    params[1].Descriptor = {2, 0};
    params[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[2].DescriptorTable = {1, &memory};
    params[3].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[3].Constants = {1, 0, 1};
    params[4].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[4].Constants = {2, 0, 2};
    params[5].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[5].Constants = {3, 0, pushWords};
    params[6].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    params[6].Descriptor = {4, 0};
    for (auto& param : params) param.ShaderVisibility = visibility;
    D3D12_ROOT_SIGNATURE_DESC desc{7, params, 0, nullptr, D3D12_ROOT_SIGNATURE_FLAG_ALLOW_STREAM_OUTPUT};
    ComPtr<ID3DBlob> blob, error;
    if (FAILED(D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &error))) {
        if (error) std::fprintf(stderr, "%.*s\n", int(error->GetBufferSize()),
                                static_cast<const char*>(error->GetBufferPointer()));
        throw std::runtime_error("Serialize vertex root signature");
    }
    ComPtr<ID3D12RootSignature> root;
    check(device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&root)),
          "Vertex root");
    return root;
}
}

namespace {
std::vector<char> read_shader(const char* path, const char* what)
{
    std::ifstream file(path, std::ios::binary);
    std::vector<char> bytes{std::istreambuf_iterator<char>(file), {}};
    if (bytes.empty() || file.bad()) throw std::runtime_error(std::string("Cannot read compiled ") + what);
    return bytes;
}

void draw_case(ID3D12Device* device, const char* shader, const char* geometry, const char* casePath)
{
    const VertexCase c = read_case(casePath);
    const std::vector<char> vs = read_shader(shader, "vertex shader");
    std::vector<char> gs;
    if (geometry) gs = read_shader(geometry, "geometry shader");
    if (bool(geometry) != bool(c.geometryRecords))
        throw BadCase("A geometry case needs a geometry shader, and a vertex case none");

    // A geometry case binds the same parameters for both stages (the ES and GS halves read the same user data).
    auto root = vertex_root(device, geometry ? D3D12_SHADER_VISIBILITY_ALL : D3D12_SHADER_VISIBILITY_VERTEX);
    std::vector<D3D12_SO_DECLARATION_ENTRY> entries;
    entries.push_back({0, "SV_Position", 0, 0, 4, 0});
    for (UINT code : c.distances)
        entries.push_back({0, code >> 8 == 1 ? "SV_ClipDistance" : "SV_CullDistance", code & 0xff, 0, 4, 0});
    for (UINT index : c.params) entries.push_back({0, "TEXCOORD", index, 0, 4, 0});
    const UINT stride = static_cast<UINT>(16 * entries.size());
    D3D12_GRAPHICS_PIPELINE_STATE_DESC desc{};
    desc.pRootSignature = root.Get();
    desc.VS = {vs.data(), vs.size()};
    if (geometry) desc.GS = {gs.data(), gs.size()};
    desc.StreamOutput = {entries.data(), static_cast<UINT>(entries.size()), &stride, 1, D3D12_SO_NO_RASTERIZED_STREAM};
    desc.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    desc.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    desc.RasterizerState.DepthClipEnable = TRUE;
    desc.SampleMask = UINT_MAX;
    desc.PrimitiveTopologyType = geometry ? D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE : D3D12_PRIMITIVE_TOPOLOGY_TYPE_POINT;
    desc.SampleDesc.Count = 1;
    ComPtr<ID3D12PipelineState> pso;
    check(device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&pso)),
          geometry ? "Translated geometry pipeline" : "Translated vertex pipeline");

    // Title memory, bound as in the pixel harness: without a section every slot views one small zero buffer.
    std::vector<TitleRangeRecord> rangeRecords = c.ranges;
    const UINT rangeCount = static_cast<UINT>(rangeRecords.size());
    if (rangeRecords.empty()) rangeRecords.push_back({});
    auto rangeBuffer = upload(device, rangeRecords);
    auto cb = upload(device, c.constants);
    auto descriptorCb = upload(device, c.descriptors);
    const std::vector<BYTE> zeroBytes(16);
    auto zeroBuffer = upload(device, zeroBytes);
    D3D12_DESCRIPTOR_HEAP_DESC heapDesc{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, 8,
                                        D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    ComPtr<ID3D12DescriptorHeap> srvs;
    check(device->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&srvs)), "Vertex memory heap");
    const UINT increment = device->GetDescriptorHandleIncrementSize(heapDesc.Type);
    std::vector<ComPtr<ID3D12Resource>> slotBuffers;
    for (UINT i = 0; i < 8; ++i) {
        const bool present = i < c.slots.size() && !c.slots[i].empty();
        slotBuffers.push_back(present ? upload(device, c.slots[i]) : zeroBuffer);
        D3D12_SHADER_RESOURCE_VIEW_DESC raw{};
        raw.Format = DXGI_FORMAT_R32_TYPELESS;
        raw.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        raw.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        raw.Buffer.NumElements = present ? static_cast<UINT>(c.slots[i].size() / 4) : 4;
        raw.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
        auto handle = srvs->GetCPUDescriptorHandleForHeapStart();
        handle.ptr += size_t(i) * increment;
        device->CreateShaderResourceView(slotBuffers.back().Get(), &raw, handle);
    }

    // Stream-output target: the filled-size counter in the first 256 bytes, then the records. The records start as a
    // pattern no output reproduces by accident, so a record the draw did not write cannot match a reference.
    constexpr UINT64 counterBytes = 256;
    const UINT64 dataBytes = UINT64(c.geometryRecords ? c.geometryRecords : c.records * c.instances) * stride;
    std::vector<Word> initial((counterBytes + dataBytes) / 4, 0xa5a5a5a5u);
    std::fill(initial.begin(), initial.begin() + counterBytes / 4, 0u);
    auto initialUpload = upload(device, initial);
    auto so = make_buffer(device, counterBytes + dataBytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COMMON);
    auto back = make_buffer(device, counterBytes + dataBytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    ComPtr<ID3D12Resource> indexBuffer;
    if (c.indexed) indexBuffer = upload(device, c.indices);

    ComputeCommands cmd(device, pso.Get(), D3D12_COMMAND_LIST_TYPE_DIRECT);
    auto* list = cmd.list.Get();
    transition(list, so.Get(), D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
    list->CopyBufferRegion(so.Get(), 0, initialUpload.Get(), 0, counterBytes + dataBytes);
    transition(list, so.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_STREAM_OUT);
    ID3D12DescriptorHeap* heaps[]{srvs.Get()};
    list->SetDescriptorHeaps(1, heaps);
    list->SetGraphicsRootSignature(root.Get());
    list->SetGraphicsRootConstantBufferView(0, cb->GetGPUVirtualAddress());
    list->SetGraphicsRootShaderResourceView(1, rangeBuffer->GetGPUVirtualAddress());
    list->SetGraphicsRootDescriptorTable(2, srvs->GetGPUDescriptorHandleForHeapStart());
    list->SetGraphicsRoot32BitConstants(3, 1, &rangeCount, 0);
    const UINT vertexRoot[2]{c.baseVertex, c.startInstance};
    list->SetGraphicsRoot32BitConstants(4, 2, vertexRoot, 0);
    list->SetGraphicsRoot32BitConstants(5, pushWords, c.push.data(), 0);
    list->SetGraphicsRootConstantBufferView(6, descriptorCb->GetGPUVirtualAddress());
    const D3D12_STREAM_OUTPUT_BUFFER_VIEW view{so->GetGPUVirtualAddress() + counterBytes, dataBytes,
                                               so->GetGPUVirtualAddress()};
    list->SOSetTargets(0, 1, &view);
    const D3D12_VIEWPORT viewport{0, 0, 1, 1, 0, 1};
    const D3D12_RECT scissor{0, 0, 1, 1};
    list->RSSetViewports(1, &viewport);
    list->RSSetScissorRects(1, &scissor);
    list->IASetPrimitiveTopology(geometry ? D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST : D3D_PRIMITIVE_TOPOLOGY_POINTLIST);
    if (c.indexed) {
        const D3D12_INDEX_BUFFER_VIEW ibv{indexBuffer->GetGPUVirtualAddress(), c.records * 4u, DXGI_FORMAT_R32_UINT};
        list->IASetIndexBuffer(&ibv);
        list->DrawIndexedInstanced(c.records, c.instances, 0, 0, 0);
    } else {
        list->DrawInstanced(c.records, c.instances, 0, 0);
    }
    transition(list, so.Get(), D3D12_RESOURCE_STATE_STREAM_OUT, D3D12_RESOURCE_STATE_COPY_SOURCE);
    list->CopyBufferRegion(back.Get(), 0, so.Get(), 0, counterBytes + dataBytes);
    cmd.submit_and_wait(device);

    const auto words = read(back.Get(), (counterBytes + dataBytes) / 4);
    if (words[0] != dataBytes) {
        std::fprintf(stderr, "vertex_count_mismatch filled_bytes=%u expected_bytes=%llu\n", words[0],
                     static_cast<unsigned long long>(dataBytes));
        throw std::runtime_error(geometry ? "Stream output did not capture the expected GS records"
                                          : "Stream output did not capture one record per vertex");
    }
    const UINT perRecord = stride / 4;
    unsigned mismatches = 0;
    for (size_t k = 0; k < c.expected.size(); ++k) {
        const Word actual = words[counterBytes / 4 + k];
        if ((actual & c.mask[k]) == (c.expected[k] & c.mask[k])) continue;
        if (mismatches++ < 16)
            std::fprintf(stderr, "vertex_mismatch record=%zu dword=%zu expected=%08x actual=%08x mask=%08x\n",
                         k / perRecord, k % perRecord, c.expected[k], actual, c.mask[k]);
    }
    if (mismatches) {
        std::fprintf(stderr, "vertex_mismatches=%u\n", mismatches);
        throw std::runtime_error("Translated vertex outputs differ from the reference");
    }
    if (geometry)
        std::printf("input_vertices=%u gs_records=%u dwords=%zu mismatches=0\n", c.records, c.geometryRecords,
                    c.expected.size());
    else
        std::printf("records=%u instances=%u dwords=%zu mismatches=0\n", c.records, c.instances, c.expected.size());
}
}

void check_translated_vertex(ID3D12Device* device, const char* shader, const char* casePath)
{
    draw_case(device, shader, nullptr, casePath);
}

void check_translated_geometry(ID3D12Device* device, const char* shader, const char* geometry, const char* casePath)
{
    draw_case(device, shader, geometry, casePath);
}
