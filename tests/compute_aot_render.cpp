// --check-compute-case <shader.cso> <case>, or --check-compute-batch <shader.cso> <case>... (one device, each case
// reported as "case=N status=pass|mismatch|error", as --check-pixel-batch does): dispatch a compute shader translated by tools/compute_aot.py and compare
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
//   optionally 'X2WT' (0x54573258), a read-image count (1 or 2), then each image as its index (0: t0, 1: t1, ascending),
//     width and height (1 to 1024) and its R8G8B8A8_UNORM texels, rows packed: SRVs of one level (root parameter 4);
//   optionally 'X2WI' (0x49573258), a storage-image count (1 to 4), then each image as its slot (0 to 3, ascending),
//     format (1: R32_UINT, 4: R32G32B32A32_UINT, 8: R8G8B8A8_UNORM), width and height (1 to 1024), its texels before
//     the dispatch and the texels the reference expects after it, rows packed: one-level UAVs at u(8 * slot), space2
//     (root parameter 5; null views elsewhere).
// The first word that differs is printed as "compute_mismatch slot=S byte=B expected=E actual=A" (or "compute_mismatch
// image=S x=X y=Y expected=E actual=A" for a storage-image word) and the check fails.
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

constexpr UINT texture_magic = 0x54573258u;
constexpr UINT image_magic = 0x49573258u;

struct ComputeImage {
    UINT slot = 0, format = 0, width = 0, height = 0;
    std::vector<BYTE> initial, expected;  // rows packed
    UINT texel_bytes() const { return format == 4 ? 16u : 4u; }
    DXGI_FORMAT dxgi() const
    {
        return format == 1 ? DXGI_FORMAT_R32_UINT : format == 4 ? DXGI_FORMAT_R32G32B32A32_UINT : DXGI_FORMAT_R8G8B8A8_UNORM;
    }
};

struct ComputeCase {
    std::array<UINT, 3> groups{};
    std::vector<Word> constants = std::vector<Word>(64);
    std::vector<ComputeRange> ranges;
    std::vector<std::vector<BYTE>> slots, expected;
    std::vector<ComputeImage> textures, images;  // read images (format 8) and storage images
};

D3D12_RESOURCE_DESC image_desc(const ComputeImage& image, bool writable)
{
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = image.width;
    desc.Height = image.height;
    desc.DepthOrArraySize = desc.MipLevels = desc.SampleDesc.Count = 1;
    desc.Format = image.dxgi();
    desc.Flags = writable ? D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS : D3D12_RESOURCE_FLAG_NONE;
    return desc;
}

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
    const auto read_image = [&](ComputeImage& image, bool storage) {
        image.width = reader.word("image width");
        image.height = reader.word("image height");
        if (!image.width || !image.height || image.width > 1024 || image.height > 1024)
            throw BadCase("Image extent is not 1 to 1024");
        const size_t bytes = size_t(image.width) * image.height * image.texel_bytes();
        const char* data = reader.take(bytes, "image texels");
        image.initial.assign(data, data + bytes);
        if (storage) {
            data = reader.take(bytes, "expected image texels");
            image.expected.assign(data, data + bytes);
        }
    };
    UINT magic = reader.done() ? 0u : reader.word("section magic");
    if (magic == texture_magic) {
        const UINT count = reader.word("read-image count");
        if (!count || count > 2) throw BadCase("Read-image section needs 1 or 2 images");
        for (UINT n = 0; n < count; ++n) {
            ComputeImage image;
            image.slot = reader.word("read-image index");
            image.format = 8;
            if (image.slot > 1 || (n && image.slot <= c.textures.back().slot))
                throw BadCase("Read-image indices are out of range or not ascending");
            read_image(image, false);
            c.textures.push_back(std::move(image));
        }
        magic = reader.done() ? 0u : reader.word("section magic");
    }
    if (magic == image_magic) {
        const UINT count = reader.word("storage-image count");
        if (!count || count > 4) throw BadCase("Storage-image section needs 1 to 4 images");
        for (UINT n = 0; n < count; ++n) {
            ComputeImage image;
            image.slot = reader.word("storage-image slot");
            image.format = reader.word("storage-image format");
            if (image.slot > 3 || (n && image.slot <= c.images.back().slot))
                throw BadCase("Storage-image slots are out of range or not ascending");
            if (image.format != 1 && image.format != 4 && image.format != 8)
                throw BadCase("Storage-image format is not 1, 4 or 8");
            read_image(image, true);
            c.images.push_back(std::move(image));
        }
        magic = 0;
    }
    if (magic != 0 || !reader.done()) throw BadCase("Compute case has trailing bytes");
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

    // Heap: 8 title-memory UAVs, then 2 read-image SRVs (root parameter 4), then 32 storage-image UAVs (parameter 5).
    constexpr UINT texture_base = slot_limit, image_base = slot_limit + 2, heap_size = slot_limit + 2 + 32;
    D3D12_DESCRIPTOR_HEAP_DESC heapDesc{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, heap_size,
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

    // Images: a default-heap texture each, filled from an upload buffer through its copyable footprint; storage
    // images are copied back the same way after the dispatch.
    struct ImageResources {
        ComPtr<ID3D12Resource> texture, staging, back;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT layout{};
        UINT rows = 0;
        UINT64 rowBytes = 0, bytes = 0;
    };
    const auto make_image = [&](const ComputeImage& image, bool writable) {
        ImageResources res;
        const auto desc = image_desc(image, writable);
        res.texture = resource(device, desc, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
        device->GetCopyableFootprints(&desc, 0, 1, 0, &res.layout, &res.rows, &res.rowBytes, &res.bytes);
        if (res.rowBytes != UINT64(image.width) * image.texel_bytes() || res.rows != image.height)
            throw std::runtime_error("Unexpected image footprint");
        std::vector<BYTE> staged(static_cast<size_t>(res.bytes));
        for (UINT y = 0; y < image.height; ++y)
            std::memcpy(staged.data() + res.layout.Offset + size_t(y) * res.layout.Footprint.RowPitch,
                        image.initial.data() + size_t(y) * res.rowBytes, static_cast<size_t>(res.rowBytes));
        res.staging = upload(device, staged);
        if (writable)
            res.back = make_buffer(device, res.bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
        return res;
    };
    std::vector<ImageResources> textureResources, imageResources;
    for (const auto& image : c.textures) textureResources.push_back(make_image(image, false));
    for (const auto& image : c.images) imageResources.push_back(make_image(image, true));
    for (UINT t = 0; t < 2; ++t) {
        D3D12_SHADER_RESOURCE_VIEW_DESC view{};
        view.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
        view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        view.Texture2D.MipLevels = 1;
        ID3D12Resource* viewed = nullptr;  // a missing read image gets a null view
        for (size_t n = 0; n < c.textures.size(); ++n)
            if (c.textures[n].slot == t) viewed = textureResources[n].texture.Get();
        auto handle = heap->GetCPUDescriptorHandleForHeapStart();
        handle.ptr += size_t(texture_base + t) * increment;
        device->CreateShaderResourceView(viewed, &view, handle);
    }
    for (UINT d = 0; d < 32; ++d) {
        const UINT slot = d / 8, level = d % 8;
        D3D12_UNORDERED_ACCESS_VIEW_DESC view{};
        view.Format = DXGI_FORMAT_R32_UINT;
        view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
        ID3D12Resource* viewed = nullptr;  // levels past the first and missing slots get null views
        for (size_t n = 0; n < c.images.size(); ++n) {
            if (c.images[n].slot != slot) continue;
            view.Format = c.images[n].dxgi();
            if (level == 0) viewed = imageResources[n].texture.Get();
        }
        auto handle = heap->GetCPUDescriptorHandleForHeapStart();
        handle.ptr += size_t(image_base + d) * increment;
        device->CreateUnorderedAccessView(viewed, nullptr, &view, handle);
    }

    ComputeCommands cmd(device, kernel.pipeline.Get());
    auto* list = cmd.list.Get();
    for (UINT i = 0; i < slot_limit; ++i) {
        if (!slots[i]) continue;
        list->CopyBufferRegion(slots[i].Get(), 0, staging[i].Get(), 0, c.slots[i].size());
        transition(list, slots[i].Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    }
    const auto copy_in = [&](ImageResources& res, D3D12_RESOURCE_STATES after) {
        D3D12_TEXTURE_COPY_LOCATION from{}, to{};
        from.pResource = res.staging.Get();
        from.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        from.PlacedFootprint = res.layout;
        to.pResource = res.texture.Get();
        to.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        to.SubresourceIndex = 0;
        list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
        transition(list, res.texture.Get(), D3D12_RESOURCE_STATE_COPY_DEST, after);
    };
    for (auto& res : textureResources) copy_in(res, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    for (auto& res : imageResources) copy_in(res, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    ID3D12DescriptorHeap* heaps[]{heap.Get()};
    list->SetDescriptorHeaps(1, heaps);
    list->SetComputeRootSignature(kernel.root.Get());
    list->SetComputeRootConstantBufferView(0, cb->GetGPUVirtualAddress());
    list->SetComputeRootShaderResourceView(1, rangeBuffer->GetGPUVirtualAddress());
    list->SetComputeRootDescriptorTable(2, heap->GetGPUDescriptorHandleForHeapStart());
    list->SetComputeRoot32BitConstants(3, 1, &rangeCount, 0);
    auto table = heap->GetGPUDescriptorHandleForHeapStart();
    table.ptr += UINT64(texture_base) * increment;
    list->SetComputeRootDescriptorTable(4, table);
    table = heap->GetGPUDescriptorHandleForHeapStart();
    table.ptr += UINT64(image_base) * increment;
    list->SetComputeRootDescriptorTable(5, table);
    list->Dispatch(c.groups[0], c.groups[1], c.groups[2]);
    for (auto& res : imageResources) {
        transition(list, res.texture.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION from{}, to{};
        from.pResource = res.texture.Get();
        from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        from.SubresourceIndex = 0;
        to.pResource = res.back.Get();
        to.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        to.PlacedFootprint = res.layout;
        list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
    }
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
                    throw ComputeMismatch("Title memory after the translated dispatch differs from the CPU reference");
                }
            }
        }
    }
    for (size_t n = 0; n < c.images.size(); ++n) {
        const auto& image = c.images[n];
        const auto& res = imageResources[n];
        const auto actual = read(res.back.Get(), static_cast<size_t>(res.bytes / 4));
        for (UINT y = 0; y < image.height; ++y) {
            for (UINT64 at = 0; at < res.rowBytes; at += 4, ++words) {
                Word want, got = actual[static_cast<size_t>((res.layout.Offset + UINT64(y) * res.layout.Footprint.RowPitch + at) / 4)];
                std::memcpy(&want, image.expected.data() + size_t(y) * res.rowBytes + at, 4);
                if (want != got) {
                    std::fprintf(stderr, "compute_mismatch image=%u x=%u y=%u expected=%08x actual=%08x\n", image.slot,
                                 static_cast<UINT>(at / image.texel_bytes()), y, want, got);
                    throw ComputeMismatch("A storage image after the translated dispatch differs from the CPU reference");
                }
            }
        }
    }
    std::printf("groups=%u,%u,%u slots=%zu images=%zu words=%zu mismatches=0\n", c.groups[0], c.groups[1], c.groups[2],
                c.slots.size(), c.images.size(), words);
}
