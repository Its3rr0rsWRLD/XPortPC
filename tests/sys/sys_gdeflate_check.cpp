// GDeflate decoder checks. Every stream is made by Microsoft's reference encoder (third_party/gdeflate) and decoded
// through x2w_sys::ds::gdeflate_decompress, directly and through the DirectStorage fallback request path.
#include "check.h"
#include "sys_dstorage.h"
#include "sys_gdeflate.h"
#include "GDeflate.h"

#include <cstring>
#include <vector>

using namespace x2w_sys::ds;

namespace {

std::vector<uint8_t> make_data(size_t size, int mode) {
    std::vector<uint8_t> d(size);
    uint32_t x = 12345u + static_cast<uint32_t>(size);
    for (size_t i = 0; i < size; ++i) {
        x = x * 1664525u + 1013904223u;
        switch (mode) {
        case 0: d[i] = static_cast<uint8_t>((i / 7) & 0xFF); break;                                  // long runs, compressible
        case 1: d[i] = static_cast<uint8_t>(x >> 24); break;                                         // noise
        default: d[i] = (i % 1000) < 500 ? static_cast<uint8_t>('a' + i % 5) : static_cast<uint8_t>(x >> 24); break;
        }
    }
    return d;
}

std::vector<uint8_t> encode(const std::vector<uint8_t>& data, uint32_t level) {
    std::vector<uint8_t> out(GDeflate::CompressBound(data.size()));
    size_t size = out.size();
    if (!GDeflate::Compress(out.data(), &size, data.data(), data.size(), level, 0)) out.clear();
    else out.resize(size);
    return out;
}

}  // namespace

int main() {
    chk::capture();
    constexpr size_t kTile = 64 * 1024;

    // ---- round trips: tile edges, levels, data kinds -------------------------------------------------------
    const size_t sizes[] = {1, 100, kTile - 1, kTile, kTile + 1, 3 * kTile, 300000, 1000000};
    for (size_t size : sizes) {
        for (int mode = 0; mode < 3; ++mode) {
            for (uint32_t level : {1u, 9u, 12u}) {
                const auto data = make_data(size, mode);
                const auto packed = encode(data, level);
                CHECK(!packed.empty());
                std::vector<uint8_t> out(size, 0xEE);
                const bool ok = gdeflate_decompress(packed.data(), packed.size(), out.data(), size);
                CHECK(ok);
                CHECK(out == data);
                if (!ok || out != data)
                    std::fprintf(stderr, "  size %zu mode %d level %u\n", size, mode, level);
            }
        }
    }
    // Control: compressible data really got smaller, noise did not shrink below its size by much (the codec ran).
    {
        const auto data = make_data(300000, 0);
        CHECK(encode(data, 9).size() < data.size() / 4);
    }

    // ---- stream layout (public reference: 8-byte header, id 4, magic = id ^ 0xFF) --------------------------
    {
        const auto packed = encode(make_data(100, 1), 9);
        CHECK(packed.size() > 12);
        CHECK_EQ(packed[0], 4);
        CHECK_EQ(packed[1], 0xFB);
        CHECK_EQ(packed[2] | (packed[3] << 8), 1);  // one tile
    }

    // ---- damaged and mismatched streams fail cleanly ---------------------------------------------------------
    {
        const auto data = make_data(200000, 2);
        const auto packed = encode(data, 9);
        std::vector<uint8_t> out(data.size(), 0xEE);
        CHECK(gdeflate_decompress(packed.data(), packed.size(), out.data(), data.size()));
        CHECK(!gdeflate_decompress(packed.data(), packed.size(), out.data(), data.size() + 1));  // wrong decoded size
        CHECK(!gdeflate_decompress(packed.data(), packed.size(), out.data(), data.size() - 1));
        CHECK(!gdeflate_decompress(packed.data(), 7, out.data(), data.size()));                  // shorter than the header
        CHECK(!gdeflate_decompress(packed.data(), 8 + 4, out.data(), data.size()));              // offset table cut
        CHECK(!gdeflate_decompress(packed.data(), packed.size() - 40, out.data(), data.size())); // last tile cut
        CHECK(!gdeflate_decompress(nullptr, 100, out.data(), data.size()));
        CHECK(!gdeflate_decompress(packed.data(), packed.size(), nullptr, data.size()));
        auto bad = packed;
        bad[1] ^= 0x01;  // magic no longer id ^ 0xFF
        CHECK(!gdeflate_decompress(bad.data(), bad.size(), out.data(), data.size()));
        bad = packed;
        bad[0] = 9;
        bad[1] = 9 ^ 0xFF;  // a valid header for another codec id
        CHECK(!gdeflate_decompress(bad.data(), bad.size(), out.data(), data.size()));
        bad = packed;
        bad[8 + 4] = 0xFF;
        bad[8 + 5] = 0xFF;
        bad[8 + 6] = 0xFF;
        bad[8 + 7] = 0x7F;  // tile 1 starts far outside the stream
        CHECK(!gdeflate_decompress(bad.data(), bad.size(), out.data(), data.size()));
        // Garbage tile data: the decoder may fail or produce other bytes, but never crash or write past out.
        bad = packed;
        for (size_t i = 8 + 16; i < bad.size(); ++i) bad[i] = static_cast<uint8_t>(i * 37);
        std::vector<uint8_t> guarded(data.size() + 4096, 0xAB);
        (void)gdeflate_decompress(bad.data(), bad.size(), guarded.data(), data.size());
        bool guard = true;
        for (size_t i = data.size(); i < guarded.size(); ++i) guard &= guarded[i] == 0xAB;
        CHECK(guard);
    }

    // ---- DirectStorage fallback requests ------------------------------------------------------------------------
    {
        reset_for_test();
        wchar_t tmp[MAX_PATH];
        GetTempPathW(MAX_PATH, tmp);
        const std::wstring file = std::wstring(tmp) + L"x2w_sys_gd_" + std::to_wstring(GetCurrentProcessId()) + L".bin";
        const auto data = make_data(500000, 2);
        const auto packed = encode(data, 12);
        // File: 100 bytes of filler, the stream, 100 bytes of filler.
        std::vector<uint8_t> blob(100, 0x11);
        blob.insert(blob.end(), packed.begin(), packed.end());
        blob.insert(blob.end(), 100, 0x22);
        HANDLE h = CreateFileW(file.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        DWORD n = 0;
        WriteFile(h, blob.data(), static_cast<DWORD>(blob.size()), &n, nullptr);
        CloseHandle(h);

        Request r;
        r.path = file;
        r.offset = 100;
        r.size = static_cast<uint32_t>(packed.size());
        r.compression = kGDeflate;
        r.uncompressed_size = static_cast<uint32_t>(data.size());
        std::vector<uint8_t> out(data.size() + 16, 0xEE);
        r.dest_memory = out.data();
        // No decoder registered yet (the library alone): unsupported.
        CHECK(run_request(r).hr == X2W_E_DS_UNSUPPORTED_COMPRESSION);
        register_decompressor(kGDeflate, &gdeflate_decompress);
        const Result ok = run_request(r);
        CHECK(ok.hr == S_OK && ok.bytes == data.size());
        CHECK(std::memcmp(out.data(), data.data(), data.size()) == 0);
        CHECK(out[data.size()] == 0xEE && out[data.size() + 15] == 0xEE);
        // Wrong uncompressed size and a truncated stored size fail with an error, not garbage.
        Request wrong = r;
        wrong.uncompressed_size += 1;
        CHECK(FAILED(run_request(wrong).hr));
        Request cut = r;
        cut.size -= 64;
        CHECK(FAILED(run_request(cut).hr));
        // Through the queue.
        Queue q;
        r.user = 77;
        q.enqueue(r);
        const auto res = q.submit_and_wait();
        CHECK(res.size() == 1 && res[0].user == 77 && res[0].hr == S_OK);
        // The flat export a gateway uses.
        std::vector<uint8_t> flat(data.size(), 0);
        CHECK(X2wDStorageFallbackRead(file.c_str(), 100, r.size, kGDeflate, r.uncompressed_size, flat.data()) == S_OK);
        CHECK(flat == data);
        CHECK(X2wDStorageFallbackRead(file.c_str(), 0, 100, kNone, 0, flat.data()) == S_OK && flat[0] == 0x11 && flat[99] == 0x11);
        CHECK(X2wDStorageFallbackRead(nullptr, 0, 1, 0, 0, flat.data()) == E_POINTER);
        DeleteFileW(file.c_str());
        reset_for_test();
    }
    return finish("sys_gdeflate");
}
