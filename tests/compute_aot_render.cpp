// --check-compute-case <shader.cso> <case>: dispatch a compute shader translated by tools/compute_aot.py and compare
// title memory, read back after the dispatch, with a CPU reference (docs/design/compute-stage.md, "Testing
// bit-exactly"). Mirrors the title-memory setup of pixel_aot_render.cpp, with the slots bound as raw UAVs so that the
// shader can store into them. The root signature is the one the HLSL embeds (compute_aot.COMPUTE_ROOT):
//   0 CBV b0 (the 64 constant words), 1 SRV t2 (title ranges), 2 table of 8 raw UAVs u0..u7 in space 1 (title memory),
//   3 one root constant b1 (the range count).
//
// Case file, little-endian:
//   'X2WC' (0x43573258), groups x, y, z (each 1 to 65535), a zero word;
//   64 constant words;
//   the memory section of pixel_aot_render.cpp: 'X2WM', range count (0..8), slot count (0..8), a zero word, the ranges
//     (begin and end as u64, slot, zero word), then each slot as a byte size and its bytes (the memory before the
//     dispatch);
//   'X2WE' (0x45573258), the same slot count, then each slot as a byte size and its bytes: the memory the reference
//     expects after the dispatch. Each size must equal the slot's size before the dispatch.
// The first word that differs is printed as "compute_mismatch slot=S byte=B expected=E actual=A" and the check fails.
#include "bvh_fixture.h"
#include <fstream>
#include <iterator>
#include <string>

using namespace bvh_fixture;

namespace {
constexpr UINT case_magic = 0x43573258u;
constexpr UINT memory_magic = 0x4d573258u;
constexpr UINT expected_magic = 0x45573258u;
constexpr UINT slot_limit = 8;

struct ComputeRange {
    UINT64 begin, end;
    UINT slot, reserved;
};
static_assert(sizeof(ComputeRange) == 24);

struct ComputeCase {
    std::array<UINT, 3> groups{};
    std::vector<Word> constants = std::vector<Word>(64);
    std::vector<ComputeRange> ranges;
    std::vector<std::vector<BYTE>> slots, expected;
};

class CaseReader {
public:
    explicit CaseReader(const std::vector<char>& bytes) : bytes_(bytes) {}
    UINT word(const char* what)
    {
        UINT value;
        std::memcpy(&value, take(4, what), 4);
        return value;
    }
    const char* take(size_t count, const char* what)
    {
        if (bytes_.size() - at_ < count) throw BadCase(std::string("Compute case is truncated at ") + what);
        const char* data = bytes_.data() + at_;
        at_ += count;
        return data;
    }
    bool done() const { return at_ == bytes_.size(); }

private:
    const std::vector<char>& bytes_;
    size_t at_ = 0;
};

std::vector<BYTE> read_slot(CaseReader& reader)
{
    const UINT bytes = reader.word("slot size");
    if (bytes % 4 || bytes > (1u << 20)) throw BadCase("Memory slot size is not a multiple of 4 or exceeds 1 MiB");
    const char* data = reader.take(bytes, "slot bytes");
    return std::vector<BYTE>(data, data + bytes);
}

ComputeCase parse_compute_case(const std::vector<char>& bytes)
{
    CaseReader reader(bytes);
    ComputeCase c;
    if (reader.word("magic") != case_magic) throw BadCase("Compute case has the wrong magic");
    for (auto& count : c.groups) {
        count = reader.word("group count");
        if (count < 1 || count > 65535) throw BadCase("Group counts must be 1 to 65535");
    }
    if (reader.word("reserved") != 0) throw BadCase("Compute case reserved word is not zero");
    std::memcpy(c.constants.data(), reader.take(64 * sizeof(Word), "constants"), 64 * sizeof(Word));
    if (reader.word("memory magic") != memory_magic) throw BadCase("Memory section has the wrong magic");
    const UINT rangeCount = reader.word("range count"), slotCount = reader.word("slot count");
    if (rangeCount > slot_limit || slotCount > slot_limit) throw BadCase("Memory section has more than 8 ranges or slots");
    if (reader.word("memory reserved") != 0) throw BadCase("Memory section reserved word is not zero");
    for (UINT i = 0; i < rangeCount; ++i) {
        ComputeRange range;
        std::memcpy(&range, reader.take(sizeof(range), "ranges"), sizeof(range));
        c.ranges.push_back(range);
    }
    for (UINT i = 0; i < slotCount; ++i) c.slots.push_back(read_slot(reader));
    if (reader.word("expected magic") != expected_magic) throw BadCase("Expected section has the wrong magic");
    if (reader.word("expected slot count") != slotCount) throw BadCase("Expected section has another slot count");
    for (UINT i = 0; i < slotCount; ++i) {
        c.expected.push_back(read_slot(reader));
        if (c.expected.back().size() != c.slots[i].size()) throw BadCase("Expected slot size differs from the slot");
    }
    if (!reader.done()) throw BadCase("Compute case has trailing bytes");
    for (size_t i = 0; i < c.ranges.size(); ++i) {
        const auto& range = c.ranges[i];
        if (range.reserved != 0) throw BadCase("Memory range reserved word is not zero");
        if (range.begin % 4 || range.begin >= range.end)
            throw BadCase("Memory range is empty, reversed or not 4-byte aligned");
        if (range.end - range.begin >= (UINT64(1) << 32)) throw BadCase("Memory range is 4 GiB or larger");
        if (range.slot >= slotCount) throw BadCase("Memory range names a slot that does not exist");
        if (range.end - range.begin > c.slots[range.slot].size()) throw BadCase("Memory range is larger than its slot");
        if (i && c.ranges[i - 1].end > range.begin) throw BadCase("Memory ranges are unsorted or overlap");
    }
    return c;
}
}

void check_translated_compute(ID3D12Device* device, const char* shaderPath, const char* casePath)
{
    std::ifstream caseFile(casePath, std::ios::binary);
    const std::vector<char> caseBytes{std::istreambuf_iterator<char>(caseFile), {}};
    if (caseFile.bad() || caseBytes.empty()) throw BadCase("Cannot read the compute case");
    const auto c = parse_compute_case(caseBytes);
    std::ifstream shaderFile(shaderPath, std::ios::binary);
    std::vector<char> cs{std::istreambuf_iterator<char>(shaderFile), {}};
    if (cs.empty() || shaderFile.bad()) throw std::runtime_error("Cannot read compiled compute shader");
    Kernel kernel(device, {cs.data(), cs.size()});

    auto cb = upload(device, c.constants);
    std::vector<ComputeRange> rangeRecords = c.ranges;
    const UINT rangeCount = static_cast<UINT>(rangeRecords.size());
    if (rangeRecords.empty()) rangeRecords.push_back({});
    auto rangeBuffer = upload(device, rangeRecords);

    D3D12_DESCRIPTOR_HEAP_DESC heapDesc{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, slot_limit,
                                        D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    ComPtr<ID3D12DescriptorHeap> heap;
    check(device->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&heap)), "Compute title memory heap");
    const UINT increment = device->GetDescriptorHandleIncrementSize(heapDesc.Type);
    std::array<ComPtr<ID3D12Resource>, slot_limit> slots, staging;
    std::array<UINT64, slot_limit> readOffset{};
    UINT64 readBytes = 0;
    for (UINT i = 0; i < slot_limit; ++i) {
        D3D12_UNORDERED_ACCESS_VIEW_DESC view{};
        view.Format = DXGI_FORMAT_R32_TYPELESS;
        view.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        view.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
        view.Buffer.NumElements = 1;
        ID3D12Resource* target = nullptr;  // a slot without bytes gets a null view: loads read 0, stores are dropped
        if (i < c.slots.size() && !c.slots[i].empty()) {
            slots[i] = make_buffer(device, c.slots[i].size(), D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COMMON,
                                   D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
            staging[i] = upload(device, c.slots[i]);
            view.Buffer.NumElements = static_cast<UINT>(c.slots[i].size() / 4);
            target = slots[i].Get();
            readOffset[i] = readBytes;
            readBytes += c.slots[i].size();
        }
        auto handle = heap->GetCPUDescriptorHandleForHeapStart();
        handle.ptr += size_t(i) * increment;
        device->CreateUnorderedAccessView(target, nullptr, &view, handle);
    }
    ComPtr<ID3D12Resource> back;
    if (readBytes)
        back = make_buffer(device, readBytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);

    ComputeCommands cmd(device, kernel.pipeline.Get());
    auto* list = cmd.list.Get();
    for (UINT i = 0; i < slot_limit; ++i) {
        if (!slots[i]) continue;
        list->CopyBufferRegion(slots[i].Get(), 0, staging[i].Get(), 0, c.slots[i].size());
        transition(list, slots[i].Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    }
    ID3D12DescriptorHeap* heaps[]{heap.Get()};
    list->SetDescriptorHeaps(1, heaps);
    list->SetComputeRootSignature(kernel.root.Get());
    list->SetComputeRootConstantBufferView(0, cb->GetGPUVirtualAddress());
    list->SetComputeRootShaderResourceView(1, rangeBuffer->GetGPUVirtualAddress());
    list->SetComputeRootDescriptorTable(2, heap->GetGPUDescriptorHandleForHeapStart());
    list->SetComputeRoot32BitConstants(3, 1, &rangeCount, 0);
    list->Dispatch(c.groups[0], c.groups[1], c.groups[2]);
    for (UINT i = 0; i < slot_limit; ++i) {
        if (!slots[i]) continue;
        transition(list, slots[i].Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
        list->CopyBufferRegion(back.Get(), readOffset[i], slots[i].Get(), 0, c.slots[i].size());
    }
    cmd.submit_and_wait(device);

    size_t words = 0;
    if (readBytes) {
        const auto actual = read(back.Get(), readBytes / 4);
        for (UINT i = 0; i < c.slots.size(); ++i) {
            const auto& expected = c.expected[i];
            for (size_t at = 0; at < expected.size(); at += 4, ++words) {
                Word want, got = actual[(readOffset[i] + at) / 4];
                std::memcpy(&want, expected.data() + at, 4);
                if (want != got) {
                    std::fprintf(stderr, "compute_mismatch slot=%u byte=%zu expected=%08x actual=%08x\n", i, at, want, got);
                    throw std::runtime_error("Title memory after the translated dispatch differs from the CPU reference");
                }
            }
        }
    }
    std::printf("groups=%u,%u,%u slots=%zu words=%zu mismatches=0\n", c.groups[0], c.groups[1], c.groups[2],
                c.slots.size(), words);
}
