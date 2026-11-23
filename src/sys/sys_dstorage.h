// DirectStorage: forward to the public PC runtime, or read files directly.
//
// Forwarding. The PC runtime is dstorage.dll (with dstorecore.dll beside it), shipped in the NuGet package
// Microsoft.Direct3D.DirectStorage (github.com/microsoft/DirectStorage, MIT). Both DStorageGetFactory and
// DStorageCreateCompressionCodec are exports of dstorage.dll (the repository's developer guidance). When the DLL
// loads, X2wDStorageGetFactory returns its IDStorageFactory and the title talks to it directly: memory
// destinations are ordinary addresses (title memory is real virtual memory), and requests whose destination is a
// GPU resource are rewritten by the graphics wrappers before they reach this layer.
//
// Our own implementation. When X2wDStorageGetFactory does not forward (no dstorage.dll, the runtime disabled, or an
// riid other than the public IDStorageFactory: the console's xcrdapi.dll entry), it returns our factory ("Our own
// DirectStorage" below). The flat Queue/run_request path remains for gateways and stand-ins: plain ReadFile on a
// worker thread, memory or title-address destinations (a resolver turns a title address into a host pointer), and a
// pluggable decompressor per compression format. GDeflate decoding is Microsoft's public reference decoder
// (Apache-2.0, over NVIDIA's libdeflate fork) vendored in third_party/gdeflate; X2WSysInit registers it for format 1
// (sys_gdeflate.h). Without X2WSysInit (the library alone) the flat path has nothing registered: register_decompressor()
// takes any implementation, and a request for an unregistered format completes with an unsupported-format error,
// logged once. Our factory's queues fall back to the built-in GDeflate and zlib decoders.
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
#include <d3d12.h>

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

// ---- Our own DirectStorage ------------------------------------------------------------------------------------
// X2wDStorageGetFactory serves it whenever it does not forward (no dstorage.dll, X2W_DSTORAGE_DLL=off, or an riid
// other than the public IDStorageFactory, which is what the console's xcrdapi.dll entry asks for). Two ABIs:
//  pc       the public dstorage.h 1.x layout (riid == pc::IID_Factory): vtables and structures below.
//  console  the GDK dstorage_xs.h layout (IDStorageFactoryX..X2, IDStorageQueueX..X2, IDStorageFileX,
//           IDStorageStatusArrayX, learn.microsoft.com/gaming/gdk/docs/reference/system/dstorage). The public
//           reference lists each interface's methods alphabetically, not in vtable order, so console calls are
//           classified by their argument shapes where the public order is ambiguous (sys_dstorage.cpp, "console
//           slots"), and every first use of a slot is logged with its arguments and what it was served as.
// Requests run on one worker thread per queue (memory destinations of one batch on the thread pool); GPU
// destinations (pc only: buffer, texture region, multiple subresources) go through an upload heap and a copy queue
// on the queue's device (a d3d12_xs wrapper is unwrapped through d3d12_xs.dll's X2WGfxUnwrap). Compression: none,
// GDeflate (pc format 1), zlib (console ZlibDecompress), or a register_decompressor() format.
enum class Abi : uint32_t { pc = 0, console = 1 };
HRESULT get_own_factory(Abi abi, REFIID iid, void** out);
std::string guid_string(const GUID& g);
// Live objects of our implementation (factories excluded), for leak checks.
long own_object_count();

namespace pc {
// GUIDs from the public dstorage.h (Microsoft.Direct3D.DirectStorage 1.x).
inline constexpr GUID IID_Factory = {0x6924ea0c, 0xc3cd, 0x4826, {0xb1, 0x0a, 0xf6, 0x4f, 0x4e, 0xd9, 0x27, 0xc1}};
inline constexpr GUID IID_File = {0x5de95e7b, 0x955a, 0x4868, {0xa7, 0x3c, 0x24, 0x3b, 0x29, 0xf4, 0xb8, 0xda}};
inline constexpr GUID IID_Queue = {0xcfdbd83f, 0x9e06, 0x4fda, {0x8e, 0xa5, 0x69, 0x04, 0x21, 0x37, 0xf4, 0x9b}};
inline constexpr GUID IID_Queue1 = {0xdd2f482c, 0x5eff, 0x41e8, {0x9c, 0x9e, 0xd2, 0x37, 0x4b, 0x27, 0x81, 0x28}};
inline constexpr GUID IID_Queue2 = {0xb1c9d643, 0x3a49, 0x44a2, {0xb4, 0x6f, 0x65, 0x36, 0x49, 0x47, 0x0d, 0x18}};
inline constexpr GUID IID_StatusArray = {0x82397587, 0x7cd5, 0x453b, {0xa0, 0x2e, 0x31, 0x37, 0x9b, 0xd6, 0x46, 0x56}};

enum : uint8_t { kDestMemory = 0, kDestBuffer = 1, kDestTextureRegion = 2, kDestMultipleSubresources = 3, kDestTiles = 4 };
enum : uint8_t { kSourceFile = 0, kSourceMemory = 1 };

struct QueueDesc {
    uint64_t SourceType;
    uint16_t Capacity;
    int8_t Priority;
    const char* Name;
    ID3D12Device* Device;
};
struct RequestOptions {
    uint8_t CompressionFormat;
    uint8_t Reserved1[7];
    uint64_t SourceType : 1;
    uint64_t DestinationType : 7;
    uint64_t Reserved : 56;
};
struct SourceFile { IUnknown* Source; uint64_t Offset; uint32_t Size; };
struct SourceMemory { const void* Source; uint32_t Size; };
struct DestMemory { void* Buffer; uint32_t Size; };
struct DestBuffer { ID3D12Resource* Resource; uint64_t Offset; uint32_t Size; };
struct DestTexture { ID3D12Resource* Resource; UINT SubresourceIndex; D3D12_BOX Region; };
struct DestMultiple { ID3D12Resource* Resource; UINT FirstSubresource; };
struct DestTiles { ID3D12Resource* Resource; D3D12_TILED_RESOURCE_COORDINATE Coordinate; D3D12_TILE_REGION_SIZE Size; };
struct Request {
    RequestOptions Options;
    union { SourceMemory Memory; SourceFile File; } Source;
    union { DestMemory Memory; DestBuffer Buffer; DestTexture Texture; DestMultiple MultipleSubresources; DestTiles Tiles; } Destination;
    uint32_t UncompressedSize;
    uint64_t CancellationTag;
    const char* Name;
};
static_assert(sizeof(RequestOptions) == 16 && sizeof(Request) == 104, "public DSTORAGE_REQUEST layout");
struct QueueInfo { QueueDesc Desc; uint16_t EmptySlotCount; uint16_t RequestCountUntilAutoSubmit; };

// The public vtable orders (IUnknown first).
struct IFile : IUnknown {
    virtual void STDMETHODCALLTYPE Close() = 0;
    virtual HRESULT STDMETHODCALLTYPE GetFileInformation(BY_HANDLE_FILE_INFORMATION* info) = 0;
};
struct IStatusArray : IUnknown {
    virtual bool STDMETHODCALLTYPE IsComplete(UINT32 index) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetHResult(UINT32 index) = 0;
};
struct IQueue : IUnknown {
    virtual void STDMETHODCALLTYPE EnqueueRequest(const Request* request) = 0;
    virtual void STDMETHODCALLTYPE EnqueueStatus(IStatusArray* array, UINT32 index) = 0;
    virtual void STDMETHODCALLTYPE EnqueueSignal(ID3D12Fence* fence, UINT64 value) = 0;
    virtual void STDMETHODCALLTYPE Submit() = 0;
    virtual void STDMETHODCALLTYPE CancelRequestsWithTag(UINT64 mask, UINT64 value) = 0;
    virtual void STDMETHODCALLTYPE Close() = 0;
    virtual HANDLE STDMETHODCALLTYPE GetErrorEvent() = 0;
    virtual void STDMETHODCALLTYPE RetrieveErrorRecord(void* record) = 0;  // DSTORAGE_ERROR_RECORD
    virtual void STDMETHODCALLTYPE Query(QueueInfo* info) = 0;
    virtual void STDMETHODCALLTYPE EnqueueSetEvent(HANDLE event) = 0;     // IDStorageQueue1
    virtual uint32_t STDMETHODCALLTYPE GetCompressionSupport(uint8_t format) = 0;  // IDStorageQueue2
};
struct IFactory : IUnknown {
    virtual HRESULT STDMETHODCALLTYPE CreateQueue(const QueueDesc* desc, REFIID riid, void** ppv) = 0;
    virtual HRESULT STDMETHODCALLTYPE OpenFile(const WCHAR* path, REFIID riid, void** ppv) = 0;
    virtual HRESULT STDMETHODCALLTYPE CreateStatusArray(UINT32 capacity, const char* name, REFIID riid, void** ppv) = 0;
    virtual void STDMETHODCALLTYPE SetDebugFlags(UINT32 flags) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetStagingBufferSize(UINT32 size) = 0;
};
}  // namespace pc

}  // namespace x2w_sys::ds

extern "C" {
// Console-facing entry, same signature as the public DStorageGetFactory(REFIID, void**).
HRESULT WINAPI X2wDStorageGetFactory(REFIID iid, void** out);
// Synchronous fallback read (optionally GDeflate-decoded) into host memory; path goes through the path map.
HRESULT WINAPI X2wDStorageFallbackRead(const wchar_t* path, uint64_t offset, uint32_t size, uint32_t compression,
                                       uint32_t uncompressed_size, void* dest);
}
