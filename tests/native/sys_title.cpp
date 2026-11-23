// Source-built title without a C runtime that uses the system layer through x2w_launch: console-style G:, T: and D:
// paths, DirectStorage fallback reads of a plain file and of a GDeflate file, and the processor and timing queries
// that stay at their host answers unless the launcher's system config sets them. Run only under x2w_launch (G:, T:
// and D: do not exist for Windows); tests/native/sys_title_check.py builds the title folder.
//
// Files under G:\data (the title folder): hello.txt ("hello from G:\n"), blob.bin (BLOB_BYTES bytes) and blob.gds
// (the same bytes as one GDeflate stream made by the reference encoder). Standard output, one line each:
//   files=<n>        hello.txt through CreateFileW and GetFileAttributesExW (size n)
//   factory=<hex>    X2wDStorageGetFactory for a console riid: x2w_sys's own factory (status 0)
//   raw=<n> fnv=<h>  X2wDStorageFallbackRead of blob.bin: size and FNV-1a 32 of the bytes
//   gdeflate=<n> fnv=<h> same=<0|1>  the same through blob.gds with compression format 1, and whether it equals raw
//   temp=<0|1> scratch=<0|1>  a write and read back under T:\ and D:\
//   name=<0|1>       GetModuleFileNameW(NULL) still names this title
//   procs=<n> active=<n> qpf=<n>  GetSystemInfo, GetActiveProcessorCount and QueryPerformanceFrequency answers
// Exit code bits: 1 files, 2 the own factory is returned (S_OK, non-null, released), 4 raw read, 8 GDeflate read equals the raw one,
// 0x10 T: round trip, 0x20 D: round trip, 0x40 module file name. 0x7f when everything works.
#include <windows.h>

#pragma runtime_checks("", off)

extern "C" HRESULT WINAPI X2wDStorageGetFactory(const IID& iid, void** out);
extern "C" HRESULT WINAPI X2wDStorageFallbackRead(const wchar_t* path, unsigned long long offset, unsigned size,
                                                  unsigned compression, unsigned uncompressed_size, void* dest);

namespace {

constexpr unsigned kMaxBlob = 1u << 20;
unsigned char raw_buffer[kMaxBlob];
unsigned char gds_buffer[kMaxBlob];
unsigned char stored_buffer[kMaxBlob + 4096];

HANDLE out_handle;

void put(const char* text) {
    DWORD written = 0;
    DWORD length = 0;
    while (text[length]) ++length;
    WriteFile(out_handle, text, length, &written, nullptr);
}

void put_number(unsigned long long value, int base = 10) {
    char digits[24];
    int count = 0;
    do {
        digits[count++] = "0123456789abcdef"[value % base];
        value /= base;
    } while (value);
    char text[25];
    for (int i = 0; i < count; ++i) text[i] = digits[count - 1 - i];
    text[count] = 0;
    put(text);
}

unsigned fnv(const unsigned char* bytes, unsigned size) {
    unsigned hash = 2166136261u;
    for (unsigned i = 0; i < size; ++i) hash = (hash ^ bytes[i]) * 16777619u;
    return hash;
}

bool same(const void* a, const void* b, unsigned size) {
    const auto* x = static_cast<const unsigned char*>(a);
    const auto* y = static_cast<const unsigned char*>(b);
    for (unsigned i = 0; i < size; ++i)
        if (x[i] != y[i]) return false;
    return true;
}

bool file_size(const wchar_t* path, unsigned* size) {
    WIN32_FILE_ATTRIBUTE_DATA data;
    if (!GetFileAttributesExW(path, GetFileExInfoStandard, &data) || data.nFileSizeHigh) return false;
    *size = data.nFileSizeLow;
    return true;
}

// Writes `text` to the file, reads it back, and compares.
bool round_trip(const wchar_t* directory, const wchar_t* file) {
    CreateDirectoryW(directory, nullptr);
    HANDLE h = CreateFileW(file, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD n = 0;
    const bool wrote = WriteFile(h, "round-trip", 10, &n, nullptr) && n == 10;
    CloseHandle(h);
    if (!wrote) return false;
    h = CreateFileW(file, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    char text[16] = {};
    const bool read = ReadFile(h, text, 10, &n, nullptr) && n == 10;
    CloseHandle(h);
    return read && same(text, "round-trip", 10);
}

bool ends_with(const wchar_t* text, DWORD length, const wchar_t* suffix) {
    DWORD s = 0;
    while (suffix[s]) ++s;
    if (length < s) return false;
    for (DWORD i = 0; i < s; ++i) {
        wchar_t c = text[length - s + i];
        if (c >= L'A' && c <= L'Z') c = static_cast<wchar_t>(c - L'A' + L'a');
        if (c != suffix[i]) return false;
    }
    return true;
}

}  // namespace

extern "C" DWORD sys_entry(void*) {
    out_handle = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD code = 0;

    // 1: a G: file through CreateFileW and GetFileAttributesExW.
    {
        unsigned size = 0;
        char text[64] = {};
        DWORD n = 0;
        HANDLE h = CreateFileW(L"G:\\data\\hello.txt", GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                               FILE_ATTRIBUTE_NORMAL, nullptr);
        bool ok = h != INVALID_HANDLE_VALUE;
        if (ok) {
            ok = ReadFile(h, text, sizeof text - 1, &n, nullptr) && n == 14 && same(text, "hello from G:\n", 14);
            CloseHandle(h);
        }
        ok = ok && file_size(L"G:\\data\\hello.txt", &size) && size == 14;
        ok = ok && GetFileAttributesW(L"G:\\data") != INVALID_FILE_ATTRIBUTES;
        put("files=");
        put_number(ok ? size : 0);
        put("\n");
        if (ok) code |= 1;
    }
    // 2: a console riid is served by x2w_sys's own factory.
    {
        IID iid = {};
        void* factory = reinterpret_cast<void*>(1);
        const HRESULT hr = X2wDStorageGetFactory(iid, &factory);
        put("factory=");
        put_number(static_cast<unsigned>(hr), 16);
        put("\n");
        if (hr == 0 && factory) {
            using Release = unsigned long(__stdcall*)(void*);
            (*reinterpret_cast<Release* const*>(factory))[2](factory);
            code |= 2;
        }
    }
    // 3, 4: plain and GDeflate fallback reads.
    unsigned raw_size = 0, gds_size = 0;
    const bool sizes = file_size(L"G:\\data\\blob.bin", &raw_size) && file_size(L"G:\\data\\blob.gds", &gds_size)
                       && raw_size && raw_size <= kMaxBlob && gds_size && gds_size <= sizeof stored_buffer;
    bool raw_ok = false;
    if (sizes) {
        raw_ok = X2wDStorageFallbackRead(L"G:\\data\\blob.bin", 0, raw_size, 0, 0, raw_buffer) == S_OK;
        put("raw=");
        put_number(raw_ok ? raw_size : 0);
        put(" fnv=");
        put_number(raw_ok ? fnv(raw_buffer, raw_size) : 0, 16);
        put("\n");
        if (raw_ok) code |= 4;
        const bool gds_ok = X2wDStorageFallbackRead(L"G:\\data\\blob.gds", 0, gds_size, 1, raw_size, gds_buffer) == S_OK;
        const bool equal = gds_ok && raw_ok && same(raw_buffer, gds_buffer, raw_size);
        put("gdeflate=");
        put_number(gds_ok ? raw_size : 0);
        put(" fnv=");
        put_number(gds_ok ? fnv(gds_buffer, raw_size) : 0, 16);
        put(" same=");
        put(equal ? "1" : "0");
        put("\n");
        if (equal) code |= 8;
    } else {
        put("raw=0 fnv=0\ngdeflate=0 fnv=0 same=0\n");
    }
    // 5, 6: T: and D:.
    {
        const bool temp = round_trip(L"T:\\sys", L"T:\\sys\\temp.txt");
        const bool scratch = round_trip(L"D:\\sys", L"D:\\sys\\scratch.txt");
        put("temp=");
        put(temp ? "1" : "0");
        put(" scratch=");
        put(scratch ? "1" : "0");
        put("\n");
        if (temp) code |= 0x10;
        if (scratch) code |= 0x20;
    }
    // 7: the module identity answers still come first.
    {
        wchar_t path[MAX_PATH];
        const DWORD length = GetModuleFileNameW(nullptr, path, MAX_PATH);
        const bool named = length && ends_with(path, length, L"x2w_sys_title.exe");
        put("name=");
        put(named ? "1" : "0");
        put("\n");
        if (named) code |= 0x40;
    }
    // Host answers unless configured.
    {
        SYSTEM_INFO info;
        GetSystemInfo(&info);
        LARGE_INTEGER frequency;
        QueryPerformanceFrequency(&frequency);
        put("procs=");
        put_number(info.dwNumberOfProcessors);
        put(" active=");
        put_number(GetActiveProcessorCount(ALL_PROCESSOR_GROUPS));
        put(" qpf=");
        put_number(static_cast<unsigned long long>(frequency.QuadPart));
        put("\n");
    }
    return code;
}
