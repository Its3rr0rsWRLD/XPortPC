// Our own DirectStorage (src/sys/sys_dstorage.cpp, "Our own DirectStorage"): the public pc ABI through its vtable
// order, and the console ABI through raw slots, over a temporary file. Requests to memory (uncompressed, GDeflate,
// zlib, memory source), status arrays, a D3D12 fence on a WARP device, a set-event, errors, cancellation, unknown
// slots and interfaces; with a WARP device, buffer, texture-region and multiple-subresource destinations.
#include "check.h"
#include "sys_dstorage.h"
#include "sys_paths.h"
#include "GDeflate.h"
#include "libdeflate.h"

#include <d3d12.h>
#include <dxgi1_4.h>

#include <cstring>
#include <vector>

using namespace x2w_sys;
using namespace x2w_sys::ds;

namespace {
using U = uintptr_t;
uint8_t pattern(uint64_t i) { return static_cast<uint8_t>((i * 131 + (i >> 8) * 7 + 3) & 0xFF); }

std::vector<uint8_t> text_data(size_t n) {
    std::vector<uint8_t> d(n);
    for (size_t i = 0; i < n; ++i) d[i] = static_cast<uint8_t>((i / 5) % 11 == 0 ? 'x' : 'a' + (i * 7) % 13);
    return d;
}
std::vector<uint8_t> gdeflate(const std::vector<uint8_t>& in) {
    std::vector<uint8_t> out(GDeflate::CompressBound(in.size()));
    size_t n = out.size();
    if (!GDeflate::Compress(out.data(), &n, in.data(), in.size(), 9, 0)) return {};
    out.resize(n);
    return out;
}
std::vector<uint8_t> zlib(const std::vector<uint8_t>& in) {
    libdeflate_compressor* c = libdeflate_alloc_compressor(6);
    std::vector<uint8_t> out(libdeflate_zlib_compress_bound(c, in.size()));
    out.resize(libdeflate_zlib_compress(c, in.data(), in.size(), out.data(), out.size()));
    libdeflate_free_compressor(c);
    return out;
}
void append(std::vector<uint8_t>& file, const std::vector<uint8_t>& part, uint64_t* at) {
    while (file.size() % 16) file.push_back(0xCC);
    *at = file.size();
    file.insert(file.end(), part.begin(), part.end());
}

// Raw slot call on one of our objects.
U slot(void* obj, int n, U a1 = 0, U a2 = 0, U a3 = 0, U a4 = 0) {
    using Fn = U(STDMETHODCALLTYPE*)(void*, U, U, U, U);
    return (*reinterpret_cast<Fn* const*>(obj))[n](obj, a1, a2, a3, a4);
}

ID3D12Device* warp_device() {
    IDXGIFactory4* f = nullptr;
    if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&f)))) return nullptr;
    IDXGIAdapter* a = nullptr;
    ID3D12Device* d = nullptr;
    if (SUCCEEDED(f->EnumWarpAdapter(IID_PPV_ARGS(&a)))) {
        D3D12CreateDevice(a, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&d));
        a->Release();
    }
    f->Release();
    return d;
}

bool wait_fence(ID3D12Fence* f, uint64_t v) {
    HANDLE e = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    f->SetEventOnCompletion(v, e);
    const bool ok = WaitForSingleObject(e, 10000) == WAIT_OBJECT_0;
    CloseHandle(e);
    return ok;
}
}  // namespace

void gpu_checks(pc::IFactory* factory, ID3D12Device* dev, pc::IFile* file, uint64_t raw_at, uint64_t gd_at, uint32_t gd_size,
                const std::vector<uint8_t>& text);

int main() {
    chk::capture();
    reset_for_test();
    resolve_get_factory("off");

    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    const std::wstring root = std::wstring(tmp) + L"x2w_sys_dsf_" + std::to_wstring(GetCurrentProcessId());
    CreateDirectoryW(root.c_str(), nullptr);
    const std::wstring path = root + L"\\pack.bin";
    // File: 1 MiB pattern, then a GDeflate stream and a zlib stream of the same text.
    constexpr uint32_t kRaw = 1 << 20;
    const std::vector<uint8_t> text = text_data(300000);
    const std::vector<uint8_t> gd = gdeflate(text), zl = zlib(text);
    CHECK(!gd.empty() && gd.size() < text.size() && !zl.empty() && zl.size() < text.size());
    uint64_t gd_at = 0, zl_at = 0;
    {
        std::vector<uint8_t> file(kRaw);
        for (uint32_t i = 0; i < kRaw; ++i) file[i] = pattern(i);
        append(file, gd, &gd_at);
        append(file, zl, &zl_at);
        HANDLE h = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        DWORD n = 0;
        WriteFile(h, file.data(), static_cast<DWORD>(file.size()), &n, nullptr);
        CloseHandle(h);
    }
    {
        auto& m = paths::global_map();
        m.clear();
        paths::Context c;
        c.title_dir = root;
        c.title_name = L"Foo";
        c.local_app_data = root;
        m.set_context(c);
        m.add_default_rules();
    }
    ID3D12Device* dev = warp_device();
    CHECK(dev != nullptr);
    ID3D12Fence* fence = nullptr;
    if (dev) dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence));
    CHECK(fence != nullptr);

    // ---- pc ABI -----------------------------------------------------------------------------------------------
    {
        pc::IFactory* factory = nullptr;
        CHECK(X2wDStorageGetFactory(pc::IID_Factory, reinterpret_cast<void**>(&factory)) == S_OK && factory);
        CHECK_EQ(chk::count("DStorageGetFactory riid=6924ea0c-c3cd-4826-b10a-f64f4ed927c1"), 1);
        factory->SetDebugFlags(0);
        CHECK(factory->SetStagingBufferSize(1 << 20) == S_OK);
        pc::IFile* file = nullptr;
        CHECK(factory->OpenFile(L"G:\\pack.bin", pc::IID_File, reinterpret_cast<void**>(&file)) == S_OK && file);
        pc::IFile* missing = reinterpret_cast<pc::IFile*>(1);
        CHECK(FAILED(factory->OpenFile(L"G:\\nope.bin", pc::IID_File, reinterpret_cast<void**>(&missing))) && !missing);
        BY_HANDLE_FILE_INFORMATION info{};
        CHECK(file && file->GetFileInformation(&info) == S_OK && info.nFileSizeLow > kRaw);
        pc::IStatusArray* status = nullptr;
        CHECK(factory->CreateStatusArray(4, "st", pc::IID_StatusArray, reinterpret_cast<void**>(&status)) == S_OK && status);
        pc::QueueDesc desc{};
        desc.SourceType = pc::kSourceFile;
        desc.Capacity = 256;
        desc.Name = "q";
        desc.Device = dev;
        pc::IQueue* q = nullptr;
        CHECK(factory->CreateQueue(&desc, pc::IID_Queue, reinterpret_cast<void**>(&q)) == S_OK && q);
        pc::IQueue* q2 = nullptr;
        CHECK(q && q->QueryInterface(pc::IID_Queue2, reinterpret_cast<void**>(&q2)) == S_OK && q2 == q);
        if (q2) q2->Release();
        const IID bogus = {0x12345678, 1, 2, {3, 4, 5, 6, 7, 8, 9, 10}};
        void* none = reinterpret_cast<void*>(1);
        CHECK(q && q->QueryInterface(bogus, &none) == E_NOINTERFACE && !none);
        CHECK_EQ(chk::count("queue QueryInterface 12345678-0001-0002-0304-05060708090a: E_NOINTERFACE"), 1);

        std::vector<uint8_t> raw(20000, 0xEE), dec(text.size() + 16, 0xEE), mem_out(1000, 0xEE);
        pc::Request r{};
        r.Options.SourceType = pc::kSourceFile;
        r.Options.DestinationType = pc::kDestMemory;
        r.Source.File = {file, 4096, 10000};
        r.Destination.Memory = {raw.data() + 100, 10000};
        r.UncompressedSize = 10000;
        q->EnqueueRequest(&r);
        pc::Request g{};
        g.Options.CompressionFormat = kGDeflate;
        g.Options.SourceType = pc::kSourceFile;
        g.Options.DestinationType = pc::kDestMemory;
        g.Source.File = {file, gd_at, static_cast<uint32_t>(gd.size())};
        g.Destination.Memory = {dec.data(), static_cast<uint32_t>(text.size())};
        g.UncompressedSize = static_cast<uint32_t>(text.size());
        q->EnqueueRequest(&g);
        pc::Request mr{};
        mr.Options.SourceType = pc::kSourceMemory;
        mr.Options.DestinationType = pc::kDestMemory;
        mr.Source.Memory = {text.data() + 7, 900};
        mr.Destination.Memory = {mem_out.data(), 900};
        q->EnqueueRequest(&mr);
        q->EnqueueStatus(status, 0);
        CHECK(!status->IsComplete(0));
        q->EnqueueSignal(fence, 1);
        HANDLE ev = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        q->EnqueueSetEvent(ev);
        q->Submit();
        CHECK(fence && wait_fence(fence, 1));
        CHECK(WaitForSingleObject(ev, 10000) == WAIT_OBJECT_0);
        CHECK(status->IsComplete(0) && status->GetHResult(0) == S_OK);
        bool ok = true;
        for (uint32_t i = 0; i < 10000; ++i) ok &= raw[100 + i] == pattern(4096 + i);
        CHECK(ok);
        CHECK(raw[99] == 0xEE && raw[10100] == 0xEE);
        CHECK(std::memcmp(dec.data(), text.data(), text.size()) == 0 && dec[text.size()] == 0xEE);
        CHECK(std::memcmp(mem_out.data(), text.data() + 7, 900) == 0 && mem_out[900] == 0xEE);
        CHECK(q->GetCompressionSupport(kGDeflate) != 0);

        // A failing request (read past the end) sets the segment's status and the error event; the next segment is clean.
        HANDLE err = q->GetErrorEvent();
        CHECK(err && WaitForSingleObject(err, 0) == WAIT_TIMEOUT);
        pc::Request bad = r;
        bad.Source.File.Offset = info.nFileSizeLow - 10;
        q->EnqueueRequest(&bad);
        q->EnqueueStatus(status, 1);
        q->EnqueueRequest(&r);
        q->EnqueueStatus(status, 2);
        // Cancelled before Submit: never runs.
        std::vector<uint8_t> untouched(100, 0x77);
        pc::Request cancel = mr;
        cancel.Destination.Memory = {untouched.data(), 100};
        cancel.Source.Memory.Size = 100;
        cancel.CancellationTag = 0xAB00;
        q->EnqueueRequest(&cancel);
        q->CancelRequestsWithTag(0xFF00, 0xAB00);
        q->EnqueueSignal(fence, 2);
        q->Submit();
        CHECK(wait_fence(fence, 2));
        CHECK(status->IsComplete(1) && FAILED(status->GetHResult(1)));
        CHECK(status->IsComplete(2) && status->GetHResult(2) == S_OK);
        CHECK(untouched[0] == 0x77);
        CHECK(WaitForSingleObject(err, 0) == WAIT_OBJECT_0);
        uint8_t record[64] = {};
        q->RetrieveErrorRecord(record);
        uint32_t failures = 0;
        HRESULT first = S_OK;
        std::memcpy(&failures, record, 4);
        std::memcpy(&first, record + 8, 4);
        CHECK(failures == 1 && FAILED(first));
        pc::QueueInfo qi{};
        q->Query(&qi);
        CHECK(qi.Desc.Capacity == 256 && qi.EmptySlotCount == 256);
        // Unknown slot: logged, E_NOTIMPL.
        CHECK(static_cast<uint32_t>(slot(q, 20, 1, 2, 3, 4)) == static_cast<uint32_t>(E_NOTIMPL));
        CHECK_EQ(chk::count("queue slot 20 not implemented (args 0x1 0x2 0x3 0x4)"), 1);

        if (dev) gpu_checks(factory, dev, file, 0, gd_at, static_cast<uint32_t>(gd.size()), text);

        q->Close();
        CloseHandle(ev);
        CHECK(q->Release() == 0);
        status->Release();
        file->Release();
        factory->Release();
        CHECK_EQ(own_object_count(), 0);
    }

    // ---- console ABI: an unknown factory riid, raw slots in another order ------------------------------------
    {
        const IID console_iid = {0xabcdef01, 0x2345, 0x6789, {1, 2, 3, 4, 5, 6, 7, 8}};
        void* factory = nullptr;
        CHECK(X2wDStorageGetFactory(console_iid, &factory) == S_OK && factory);
        CHECK_EQ(chk::count("dstorage-factory iid=abcdef01-2345-6789-0102-030405060708 served-as IDStorageFactory"), 1);
        void* again = nullptr;
        CHECK(slot(factory, 0, reinterpret_cast<U>(&console_iid), reinterpret_cast<U>(&again)) == S_OK && again == factory);
        const IID queue_iid = {0xabcdef02, 0, 0, {0}}, file_iid = {0xabcdef03, 0, 0, {0}}, status_iid = {0xabcdef04, 0, 0, {0}};
        // Alphabetical order: CreateQueue, CreateStatusArray, OpenFile, SetCpuAffinity, SetDebugFlags, SetStagingBufferSize.
        struct { uint64_t source; uint16_t capacity; int8_t priority; const char* name; } desc{0, 128, 0, "cq"};
        void *q = nullptr, *status = nullptr, *file = nullptr;
        CHECK(slot(factory, 3, reinterpret_cast<U>(&desc), reinterpret_cast<U>(&queue_iid), reinterpret_cast<U>(&q)) == S_OK && q);
        CHECK(slot(factory, 4, 2, reinterpret_cast<U>("cs"), reinterpret_cast<U>(&status_iid), reinterpret_cast<U>(&status)) == S_OK && status);
        CHECK(slot(factory, 5, reinterpret_cast<U>(L"G:\\pack.bin"), reinterpret_cast<U>(&file_iid), reinterpret_cast<U>(&file)) == S_OK && file);
        CHECK(slot(factory, 6, 0xF) == S_OK && slot(factory, 7, 1) == S_OK && slot(factory, 8, 1 << 20) == S_OK);
        CHECK_EQ(chk::count("factory slot 5 served as OpenFile"), 1);
        CHECK_EQ(chk::count("factory slot 4 served as CreateStatusArray"), 1);
        void* qq = nullptr;
        CHECK(q && slot(q, 0, reinterpret_cast<U>(&queue_iid), reinterpret_cast<U>(&qq)) == S_OK && qq == q);
        if (qq) slot(qq, 2);
        // Console DSTORAGE_REQUEST: zlib from the file, and an uncompressed one.
        std::vector<uint8_t> dec(text.size() + 16, 0xEE), raw(5000, 0xEE);
        alignas(8) uint8_t zr[72] = {}, rr[72] = {};
        auto fill = [&](uint8_t* req, uint64_t opt, void* dst, uint32_t dst_size, uint64_t off, uint32_t src_size) {
            void* src = file;
            std::memcpy(req, &opt, 8);
            std::memcpy(req + 8, &dst, 8);
            std::memcpy(req + 24, &dst_size, 4);
            std::memcpy(req + 32, &src, 8);
            std::memcpy(req + 40, &off, 8);
            std::memcpy(req + 48, &src_size, 4);
        };
        fill(zr, 1, dec.data(), static_cast<uint32_t>(text.size()), zl_at, static_cast<uint32_t>(zl.size()));
        fill(rr, 0, raw.data(), 4000, 123, 4000);
        // Queue slots 3..5 told apart by argument: status at 3, fence at 4, request at 5; Submit at 6.
        slot(q, 5, reinterpret_cast<U>(zr));
        slot(q, 5, reinterpret_cast<U>(rr));
        slot(q, 3, reinterpret_cast<U>(status), 1);
        slot(q, 4, reinterpret_cast<U>(fence), 3);
        CHECK(slot(status, 3, 1) == 0 && slot(status, 4, 1) == 0);  // pending
        slot(q, 6);
        CHECK(wait_fence(fence, 3));
        CHECK(slot(status, 3, 1) == 1 && slot(status, 4, 1) == 1);  // complete, succeeded
        CHECK(std::memcmp(dec.data(), text.data(), text.size()) == 0 && dec[text.size()] == 0xEE);
        bool ok = true;
        for (uint32_t i = 0; i < 4000; ++i) ok &= raw[i] == pattern(123 + i);
        CHECK(ok && raw[4000] == 0xEE);
        CHECK_EQ(chk::count("queue slot 3 served as EnqueueStatus"), 1);
        CHECK_EQ(chk::count("queue slot 4 served as EnqueueSignal"), 1);
        CHECK_EQ(chk::count("queue slot 5 served as EnqueueRequest"), 1);
        // Never submitted: completes anyway after 5 ms (a Submit slot we did not recognize must not hang a title).
        std::vector<uint8_t> late(64, 0xEE);
        fill(rr, 0, late.data(), 64, 0, 64);
        slot(q, 5, reinterpret_cast<U>(rr));
        slot(q, 4, reinterpret_cast<U>(fence), 4);
        CHECK(wait_fence(fence, 4) && late[0] == pattern(0));
        // BCPack is refused, logged.
        std::vector<uint8_t> bc(64, 0xEE);
        fill(rr, 1u << 1, bc.data(), 64, 0, 64);
        slot(q, 5, reinterpret_cast<U>(rr));
        slot(q, 3, reinterpret_cast<U>(status), 0);
        slot(q, 6);
        for (int i = 0; i < 1000 && !slot(status, 3, 0); ++i) Sleep(5);
        CHECK(slot(status, 3, 0) != 0 && slot(status, 3, 0) != 1 && bc[0] == 0xEE);
        CHECK_EQ(chk::count("BCPack mode 1 is not implemented"), 1);
        CHECK(static_cast<uint32_t>(slot(file, 9)) == static_cast<uint32_t>(E_NOTIMPL));
        slot(q, 2);
        slot(status, 2);
        slot(file, 2);
        CHECK_EQ(own_object_count(), 0);
    }
    if (fence) fence->Release();
    if (dev) dev->Release();
    DeleteFileW(path.c_str());
    RemoveDirectoryW(root.c_str());
    reset_for_test();
    return finish("sys_dstorage_factory");
}

namespace {
ID3D12Resource* make_resource(ID3D12Device* dev, D3D12_HEAP_TYPE heap, const D3D12_RESOURCE_DESC& d, D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES hp{};
    hp.Type = heap;
    ID3D12Resource* r = nullptr;
    dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, state, nullptr, IID_PPV_ARGS(&r));
    return r;
}
D3D12_RESOURCE_DESC buffer_desc(uint64_t n) {
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width = n;
    d.Height = 1;
    d.DepthOrArraySize = 1;
    d.MipLevels = 1;
    d.SampleDesc.Count = 1;
    d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    return d;
}
D3D12_RESOURCE_DESC tex_desc(UINT w, UINT h, UINT16 mips, DXGI_FORMAT f) {
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = w;
    d.Height = h;
    d.DepthOrArraySize = 1;
    d.MipLevels = mips;
    d.Format = f;
    d.SampleDesc.Count = 1;
    return d;
}
// Copies `src` (a buffer, or every subresource of a texture in its footprint layout) into a readback buffer.
std::vector<uint8_t> read_back(ID3D12Device* dev, ID3D12Resource* src, std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT>* fps) {
    const D3D12_RESOURCE_DESC d = src->GetDesc();
    uint64_t total = d.Width;
    UINT n = 0;
    if (d.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER) {
        n = d.MipLevels;
        fps->resize(n);
        dev->GetCopyableFootprints(&d, 0, n, 0, fps->data(), nullptr, nullptr, &total);
    }
    ID3D12Resource* rb = make_resource(dev, D3D12_HEAP_TYPE_READBACK, buffer_desc(total), D3D12_RESOURCE_STATE_COPY_DEST);
    ID3D12CommandQueue* q = nullptr;
    ID3D12CommandAllocator* a = nullptr;
    ID3D12GraphicsCommandList* l = nullptr;
    ID3D12Fence* f = nullptr;
    D3D12_COMMAND_QUEUE_DESC qd{};
    qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    dev->CreateCommandQueue(&qd, IID_PPV_ARGS(&q));
    dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&a));
    dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, a, nullptr, IID_PPV_ARGS(&l));
    dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&f));
    std::vector<uint8_t> out;
    if (!rb || !q || !a || !l || !f) return out;
    if (!n) {
        l->CopyBufferRegion(rb, 0, src, 0, total);
    } else {
        for (UINT i = 0; i < n; ++i) {
            D3D12_TEXTURE_COPY_LOCATION s{}, t{};
            s.pResource = src;
            s.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            s.SubresourceIndex = i;
            t.pResource = rb;
            t.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            t.PlacedFootprint = (*fps)[i];
            l->CopyTextureRegion(&t, 0, 0, 0, &s, nullptr);
        }
    }
    l->Close();
    ID3D12CommandList* lists[] = {l};
    q->ExecuteCommandLists(1, lists);
    q->Signal(f, 1);
    if (wait_fence(f, 1)) {
        void* p = nullptr;
        if (SUCCEEDED(rb->Map(0, nullptr, &p))) {
            out.assign(static_cast<uint8_t*>(p), static_cast<uint8_t*>(p) + total);
            rb->Unmap(0, nullptr);
        }
    }
    f->Release();
    l->Release();
    a->Release();
    q->Release();
    rb->Release();
    return out;
}
}  // namespace

// Buffer (GDeflate), texture region (tightly packed rows) and multiple subresources (footprint layout) on WARP.
void gpu_checks(pc::IFactory* factory, ID3D12Device* dev, pc::IFile* file, uint64_t raw_at, uint64_t gd_at, uint32_t gd_size,
                const std::vector<uint8_t>& text) {
    pc::QueueDesc desc{};
    desc.SourceType = pc::kSourceFile;
    desc.Capacity = 128;
    desc.Device = dev;
    pc::IQueue* q = nullptr;
    CHECK(factory->CreateQueue(&desc, pc::IID_Queue, reinterpret_cast<void**>(&q)) == S_OK && q);
    ID3D12Fence* fence = nullptr;
    dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence));
    ID3D12Resource* buf = make_resource(dev, D3D12_HEAP_TYPE_DEFAULT, buffer_desc(512 * 1024), D3D12_RESOURCE_STATE_COMMON);
    ID3D12Resource* tex = make_resource(dev, D3D12_HEAP_TYPE_DEFAULT, tex_desc(64, 64, 1, DXGI_FORMAT_R8G8B8A8_UNORM), D3D12_RESOURCE_STATE_COMMON);
    ID3D12Resource* mips = make_resource(dev, D3D12_HEAP_TYPE_DEFAULT, tex_desc(16, 16, 2, DXGI_FORMAT_R8_UNORM), D3D12_RESOURCE_STATE_COMMON);
    CHECK(q && fence && buf && tex && mips);
    if (!q || !fence || !buf || !tex || !mips) return;

    pc::Request b{};
    b.Options.CompressionFormat = kGDeflate;
    b.Options.SourceType = pc::kSourceFile;
    b.Options.DestinationType = pc::kDestBuffer;
    b.Source.File = {file, gd_at, gd_size};
    b.Destination.Buffer = {buf, 256, static_cast<uint32_t>(text.size())};
    b.UncompressedSize = static_cast<uint32_t>(text.size());
    q->EnqueueRequest(&b);
    // Region (8,8)-(40,24): 32x16 texels of 4 bytes, tightly packed: 2048 bytes from file offset 5000.
    pc::Request t{};
    t.Options.SourceType = pc::kSourceFile;
    t.Options.DestinationType = pc::kDestTextureRegion;
    t.Source.File = {file, raw_at + 5000, 2048};
    t.Destination.Texture.Resource = tex;
    t.Destination.Texture.SubresourceIndex = 0;
    t.Destination.Texture.Region = {8, 8, 0, 40, 24, 1};
    t.UncompressedSize = 2048;
    q->EnqueueRequest(&t);
    // Both mips of a 16x16 R8 texture in the footprint layout.
    D3D12_RESOURCE_DESC md = mips->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT mfp[2];
    UINT64 mtotal = 0;
    dev->GetCopyableFootprints(&md, 0, 2, 0, mfp, nullptr, nullptr, &mtotal);
    pc::Request m{};
    m.Options.SourceType = pc::kSourceFile;
    m.Options.DestinationType = pc::kDestMultipleSubresources;
    m.Source.File = {file, raw_at + 70000, static_cast<uint32_t>(mtotal)};
    m.Destination.MultipleSubresources = {mips, 0};
    m.UncompressedSize = static_cast<uint32_t>(mtotal);
    q->EnqueueRequest(&m);
    q->EnqueueSignal(fence, 1);
    q->Submit();
    CHECK(wait_fence(fence, 1));
    HANDLE err = q->GetErrorEvent();
    CHECK(WaitForSingleObject(err, 0) == WAIT_TIMEOUT);

    std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> fps;
    const std::vector<uint8_t> bb = read_back(dev, buf, &fps);
    CHECK(bb.size() == 512 * 1024 && std::memcmp(bb.data() + 256, text.data(), text.size()) == 0 && bb[255] == 0);
    const std::vector<uint8_t> tb = read_back(dev, tex, &fps);
    bool ok = !tb.empty();
    for (uint32_t y = 0; ok && y < 16; ++y)
        for (uint32_t x = 0; x < 128; ++x) ok &= tb[fps[0].Offset + (8 + y) * fps[0].Footprint.RowPitch + 32 + x] == pattern(raw_at + 5000 + y * 128 + x);
    CHECK(ok);
    CHECK(!tb.empty() && tb[fps[0].Offset + 8 * fps[0].Footprint.RowPitch + 28] == 0);  // left of the region
    const std::vector<uint8_t> mb = read_back(dev, mips, &fps);
    ok = !mb.empty();
    for (UINT i = 0; ok && i < 2; ++i) {
        const UINT w = 16 >> i;
        for (UINT y = 0; y < w; ++y)
            for (UINT x = 0; x < w; ++x)
                ok &= mb[fps[i].Offset + y * fps[i].Footprint.RowPitch + x] ==
                      pattern(raw_at + 70000 + mfp[i].Offset + y * mfp[i].Footprint.RowPitch + x);
    }
    CHECK(ok);
    CHECK_EQ(chk::count("texture data taken as tightly packed rows"), 1);
    q->Close();
    q->Release();
    mips->Release();
    tex->Release();
    buf->Release();
    fence->Release();
}
