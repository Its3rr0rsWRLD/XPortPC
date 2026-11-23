// DirectStorage: forward to the public PC runtime, or read files directly.
//
// Forwarding. The PC runtime is dstorage.dll (with dstorecore.dll beside it), shipped in the NuGet package
// Microsoft.Direct3D.DirectStorage (github.com/microsoft/DirectStorage, MIT). Both DStorageGetFactory and
// DStorageCreateCompressionCodec are exports of dstorage.dll (the repository's developer guidance). When the DLL
// loads, X2wDStorageGetFactory returns its IDStorageFactory and the title talks to it directly: memory
// destinations are ordinary addresses (title memory is real virtual memory), and requests whose destination is a
// GPU resource are rewritten by the graphics wrappers before they reach this layer.
//
// Fallback. With no dstorage.dll, X2wDStorageGetFactory returns X2W_E_DSTORAGE_FALLBACK and the gateway uses the
// Queue below: plain ReadFile on a worker thread, memory or title-address destinations (a resolver turns a title
// address into a host pointer; GPU resources go through the graphics wrappers' staging memory), and a pluggable
// decompressor per compression format. GDeflate decoding is Microsoft's public reference decoder
// (Apache-2.0, over NVIDIA's libdeflate fork) vendored in third_party/gdeflate; X2WSysInit registers it for format 1
// (sys_gdeflate.h). Without X2WSysInit (the library alone) nothing is registered: register_decompressor() takes any
// implementation, and a request for an unregistered format completes with an unsupported-format error, logged once.
#pragma once

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

namespace x2w_sys::ds {

constexpr HRESULT X2W_E_DSTORAGE_FALLBACK = static_cast<HRESULT>(0xA2570002);
constexpr HRESULT X2W_E_DS_UNSUPPORTED_COMPRESSION = static_cast<HRESULT>(0xA2570003);
constexpr HRESULT X2W_E_DS_BAD_DESTINATION = static_cast<HRESULT>(0xA2570004);

// DSTORAGE_COMPRESSION_FORMAT values: 0 none, 1 GDeflate, 0x80 and up are custom formats.
enum : uint32_t { kNone = 0, kGDeflate = 1, kCustom0 = 0x80 };

// Decompress `in` into `out` (capacity out_size, expected output exactly out_size). True on success.
using Decompressor = std::function<bool(const void* in, size_t in_size, void* out, size_t out_size)>;
void register_decompressor(uint32_t format, Decompressor fn);

struct Request {
    std::wstring path;          // console-style paths are remapped (sys_paths)
    uint64_t offset = 0;        // byte offset in the file
    uint32_t size = 0;          // bytes stored in the file
    uint32_t compression = kNone;
    uint32_t uncompressed_size = 0;  // required when compression != kNone
    void* dest_memory = nullptr;     // destination: host memory ...
    uint64_t dest_title_address = 0; // ... or a title address resolved through the resolver (dest_memory null)
    uint64_t user = 0;               // returned in the result
};

struct Result {
    uint64_t user = 0;
    HRESULT hr = S_OK;
    uint32_t bytes = 0;  // bytes written to the destination
};

// Title address -> writable host pointer for `size` bytes, or null. The default accepts an address that lies in
// committed writable memory of this process (title memory from xmem.dll is ordinary virtual memory).
using Resolver = std::function<void*(uint64_t title_address, uint64_t size)>;
void set_resolver(Resolver fn);
void* default_resolve(uint64_t title_address, uint64_t size);

// Performs one request synchronously on the calling thread.
Result run_request(const Request& r);

class Queue {
public:
    Queue();
    ~Queue();
    void enqueue(const Request& r);
    // Waits until every request enqueued so far has completed; returns their results in enqueue order.
    std::vector<Result> submit_and_wait();

private:
    void worker();
    std::mutex m_;
    std::condition_variable cv_, done_cv_;
    std::deque<Request> pending_;
    std::vector<Result> results_;
    size_t outstanding_ = 0;
    bool stop_ = false;
    std::thread thread_;
};

struct Stats {
    uint64_t requests = 0, bytes_read = 0, bytes_out = 0, failed = 0, unsupported = 0;
};
Stats& stats();

// Runtime resolution for forwarding.
using GetFactoryFn = HRESULT(WINAPI*)(REFIID, void**);
GetFactoryFn resolve_get_factory(const char* override_dll = nullptr);
void reset_for_test();
void apply_config_line(const std::string& key, const std::string& value);

}  // namespace x2w_sys::ds

extern "C" {
// Console-facing entry, same signature as the public DStorageGetFactory(REFIID, void**).
HRESULT WINAPI X2wDStorageGetFactory(REFIID iid, void** out);
// Synchronous fallback read (optionally GDeflate-decoded) into host memory; path goes through the path map.
HRESULT WINAPI X2wDStorageFallbackRead(const wchar_t* path, uint64_t offset, uint32_t size, uint32_t compression,
                                       uint32_t uncompressed_size, void* dest);
}
