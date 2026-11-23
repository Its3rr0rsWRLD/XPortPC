#include "check.h"
#include "sys_dstorage.h"
#include "sys_paths.h"

#include <cstring>
#include <vector>

using namespace x2w_sys;
using namespace x2w_sys::ds;

namespace {
uint8_t pattern(uint64_t i) { return static_cast<uint8_t>((i * 131 + (i >> 8) * 7 + 3) & 0xFF); }
}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: sys_dstorage_check <fake_runtime.dll>\n"); return 2; }
    chk::capture();
    reset_for_test();

    // ---- forwarding to a stand-in runtime ---------------------------------------------------------------
    {
        CHECK(resolve_get_factory(argv[1]) != nullptr);
        void* out = nullptr;
        const IID iid = {0xCAFE0001, 0, 0, {0, 0, 0, 0, 0, 0, 0, 0}};
        CHECK(X2wDStorageGetFactory(iid, &out) == S_OK);
        CHECK_EQ(reinterpret_cast<uintptr_t>(out), 0xCAFE0001u);
        CHECK(X2wDStorageGetFactory(iid, nullptr) == E_POINTER);
    }
    // ---- no runtime: the fallback status ---------------------------------------------------------------
    reset_for_test();
    {
        CHECK(resolve_get_factory("off") == nullptr);
        void* out = reinterpret_cast<void*>(1);
        const IID iid = {};
        CHECK(X2wDStorageGetFactory(iid, &out) == X2W_E_DSTORAGE_FALLBACK);
        CHECK(out == nullptr);
    }

    // ---- fallback queue over a real file -------------------------------------------------------------------
    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    const std::wstring root = std::wstring(tmp) + L"x2w_sys_ds_" + std::to_wstring(GetCurrentProcessId());
    CreateDirectoryW(root.c_str(), nullptr);
    const std::wstring file = root + L"\\big.bin";
    constexpr uint32_t kSize = 1 << 20;
    {
        std::vector<uint8_t> data(kSize);
        for (uint32_t i = 0; i < kSize; ++i) data[i] = pattern(i);
        HANDLE h = CreateFileW(file.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        DWORD n = 0;
        WriteFile(h, data.data(), kSize, &n, nullptr);
        CloseHandle(h);
    }
    // G: resolves to the folder through the path map, the same way title code reaches it.
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
    // Title memory: a region of ordinary virtual memory, addressed by number as a title would.
    auto* region = static_cast<uint8_t*>(VirtualAlloc(nullptr, 1 << 20, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
    CHECK(region != nullptr);
    std::memset(region, 0xEE, 1 << 20);
    std::vector<uint8_t> host_buf(20000, 0xEE);
    std::vector<uint8_t> scratch(20000, 0);

    set_resolver(nullptr);
    register_decompressor(kCustom0, [](const void* in, size_t in_size, void* out, size_t out_size) {
        if (in_size != out_size) return false;
        auto* o = static_cast<uint8_t*>(out);
        auto* i = static_cast<const uint8_t*>(in);
        for (size_t k = 0; k < in_size; ++k) o[k] = i[k] ^ 0x5A;  // stand-in codec
        return true;
    });
    {
        Queue q;
        Request a;  // plain read into host memory
        a.path = L"G:\\big.bin";
        a.offset = 4096;
        a.size = 10000;
        a.dest_memory = host_buf.data() + 100;
        a.user = 1;
        Request b;  // plain read into title memory by address
        b.path = file;
        b.offset = 777;
        b.size = 50000;
        b.dest_title_address = reinterpret_cast<uintptr_t>(region + 64);
        b.user = 2;
        Request c;  // custom-compressed
        c.path = L"G:\\big.bin";
        c.offset = 100000;
        c.size = 3000;
        c.compression = kCustom0;
        c.uncompressed_size = 3000;
        c.dest_title_address = reinterpret_cast<uintptr_t>(region + 100000);
        c.user = 3;
        Request d = c;  // GDeflate with no decoder registered
        d.compression = kGDeflate;
        d.user = 4;
        Request e = a;  // destination does not resolve
        e.dest_memory = nullptr;
        e.dest_title_address = 0x10;
        e.user = 5;
        Request f = a;  // missing file
        f.path = L"G:\\nope.bin";
        f.user = 6;
        Request g = a;  // read past the end of the file
        g.offset = kSize - 10;
        g.dest_memory = scratch.data();
        g.user = 7;
        for (const auto& r : {a, b, c, d, e, f, g}) q.enqueue(r);
        const auto res = q.submit_and_wait();
        CHECK_EQ(res.size(), 7u);
        if (res.size() == 7) {
            for (size_t i = 0; i < 7; ++i) CHECK_EQ(res[i].user, i + 1);  // enqueue order
            CHECK(res[0].hr == S_OK && res[0].bytes == 10000);
            CHECK(res[1].hr == S_OK && res[1].bytes == 50000);
            CHECK(res[2].hr == S_OK && res[2].bytes == 3000);
            CHECK(res[3].hr == X2W_E_DS_UNSUPPORTED_COMPRESSION);
            CHECK(res[4].hr == X2W_E_DS_BAD_DESTINATION);
            CHECK(FAILED(res[5].hr));
            CHECK(FAILED(res[6].hr));
        }
        // Content, and the bytes next to each destination are untouched.
        bool ok = true;
        for (uint32_t i = 0; i < 10000; ++i) ok &= host_buf[100 + i] == pattern(4096 + i);
        CHECK(ok);
        CHECK(host_buf[99] == 0xEE && host_buf[100 + 10000] == 0xEE);
        ok = true;
        for (uint32_t i = 0; i < 50000; ++i) ok &= region[64 + i] == pattern(777 + i);
        CHECK(ok);
        CHECK(region[63] == 0xEE && region[64 + 50000] == 0xEE);
        ok = true;
        for (uint32_t i = 0; i < 3000; ++i) ok &= region[100000 + i] == static_cast<uint8_t>(pattern(100000 + i) ^ 0x5A);
        CHECK(ok);
        // Control: the decoded bytes are not the raw ones.
        CHECK(region[100000] != pattern(100000));
        CHECK_EQ(chk::count("compression format 1 has no decoder"), 1);
        CHECK_EQ(chk::count("path remap <path>\\big.bin")  /* drive paths are redacted (x2w_redact.h) */, 1);
        CHECK_EQ(stats().requests, 7u);
        CHECK_EQ(stats().unsupported, 1u);
        CHECK_EQ(stats().bytes_out, 63000u);
    }
    // A second batch on a fresh queue works and a custom resolver is honored.
    {
        std::vector<uint8_t> stage(512, 0);
        uint64_t asked = 0;
        set_resolver([&](uint64_t addr, uint64_t size) -> void* {
            asked = addr + size;
            return stage.data();
        });
        Queue q;
        Request r;
        r.path = file;
        r.offset = 0;
        r.size = 512;
        r.dest_title_address = 0xDEAD0000;
        q.enqueue(r);
        const auto res = q.submit_and_wait();
        CHECK(res.size() == 1 && res[0].hr == S_OK);
        CHECK_EQ(asked, 0xDEAD0000ull + 512);
        CHECK(stage[5] == pattern(5));
    }
    VirtualFree(region, 0, MEM_RELEASE);
    DeleteFileW(file.c_str());
    RemoveDirectoryW(root.c_str());
    reset_for_test();
    return finish("sys_dstorage");
}
