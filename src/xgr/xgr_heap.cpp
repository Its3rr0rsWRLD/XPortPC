// The gateway's own heap. Every operator new/delete in x2w_xgr.dll (its State, maps, strings, Objects) uses a private
// heap made with HeapCreate, so a title that damages the process heap cannot take the gateway's bookkeeping down with
// it, and the gateway's blocks are not in the process heap the launcher's heap guard validates.
// Each block carries a 16-byte header (magic, payload offset): a delete of a pointer without it (memory this module did
// not allocate) is ignored and logged once on stderr rather than handed to HeapFree.
#include <windows.h>

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <new>

namespace {
constexpr std::uint64_t kMagic = 0x58475248454150ull;  // "XGRHEAP"
struct Header {
    std::uint64_t magic;
    std::uint64_t offset;  // payload - block start
};
static_assert(sizeof(Header) == 16);

HANDLE volatile private_heap;
volatile long foreign_logged;

HANDLE heap() {
    HANDLE h = private_heap;
    if (h) return h;
    HANDLE made = HeapCreate(0, 0, 0);
    if (!made) return GetProcessHeap();
    if (InterlockedCompareExchangePointer(&private_heap, made, nullptr) != nullptr) HeapDestroy(made);
    return private_heap;
}

void* allocate(std::size_t bytes, std::size_t alignment) noexcept {
    if (alignment < 16) alignment = 16;
    if (bytes > SIZE_MAX - alignment - sizeof(Header)) return nullptr;
    auto* block = static_cast<std::uint8_t*>(HeapAlloc(heap(), 0, bytes + alignment + sizeof(Header)));
    if (!block) return nullptr;
    auto payload = (reinterpret_cast<std::uintptr_t>(block) + sizeof(Header) + alignment - 1) & ~(alignment - 1);
    auto* header = reinterpret_cast<Header*>(payload - sizeof(Header));
    header->magic = kMagic;
    header->offset = payload - reinterpret_cast<std::uintptr_t>(block);
    return reinterpret_cast<void*>(payload);
}

void release(void* p) noexcept {
    if (!p) return;
    auto* header = reinterpret_cast<Header*>(static_cast<std::uint8_t*>(p) - sizeof(Header));
    if (header->magic != kMagic || header->offset < sizeof(Header) || header->offset > 0x10000) {
        if (InterlockedExchange(&foreign_logged, 1) == 0) {
            std::fprintf(stderr, "[x2w] xgr-heap delete of 0x%llx, which the gateway did not allocate; ignored\n",
                         static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(p)));
            std::fflush(stderr);
        }
        return;
    }
    header->magic = 0;
    HeapFree(heap(), 0, static_cast<std::uint8_t*>(p) - header->offset);
}

void* allocate_or_throw(std::size_t bytes, std::size_t alignment) {
    if (void* p = allocate(bytes ? bytes : 1, alignment)) return p;
    throw std::bad_alloc();
}
}  // namespace

void* operator new(std::size_t bytes) { return allocate_or_throw(bytes, 16); }
void* operator new[](std::size_t bytes) { return allocate_or_throw(bytes, 16); }
void* operator new(std::size_t bytes, const std::nothrow_t&) noexcept { return allocate(bytes ? bytes : 1, 16); }
void* operator new[](std::size_t bytes, const std::nothrow_t&) noexcept { return allocate(bytes ? bytes : 1, 16); }
void* operator new(std::size_t bytes, std::align_val_t a) { return allocate_or_throw(bytes, static_cast<std::size_t>(a)); }
void* operator new[](std::size_t bytes, std::align_val_t a) { return allocate_or_throw(bytes, static_cast<std::size_t>(a)); }
void* operator new(std::size_t bytes, std::align_val_t a, const std::nothrow_t&) noexcept {
    return allocate(bytes ? bytes : 1, static_cast<std::size_t>(a));
}
void* operator new[](std::size_t bytes, std::align_val_t a, const std::nothrow_t&) noexcept {
    return allocate(bytes ? bytes : 1, static_cast<std::size_t>(a));
}
void operator delete(void* p) noexcept { release(p); }
void operator delete[](void* p) noexcept { release(p); }
void operator delete(void* p, std::size_t) noexcept { release(p); }
void operator delete[](void* p, std::size_t) noexcept { release(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { release(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { release(p); }
void operator delete(void* p, std::align_val_t) noexcept { release(p); }
void operator delete[](void* p, std::align_val_t) noexcept { release(p); }
void operator delete(void* p, std::size_t, std::align_val_t) noexcept { release(p); }
void operator delete[](void* p, std::size_t, std::align_val_t) noexcept { release(p); }
void operator delete(void* p, std::align_val_t, const std::nothrow_t&) noexcept { release(p); }
void operator delete[](void* p, std::align_val_t, const std::nothrow_t&) noexcept { release(p); }
