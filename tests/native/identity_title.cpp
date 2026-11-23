// Source-built title without a C runtime that asks Windows who it is, as titles do to find their own files and
// resources. Each check compares the answer with the image's own base (__ImageBase) or file. The process exit
// code is 0x1ff when every answer names this image, under Windows and under x2w_launch alike:
//   0x001 GetModuleHandleW(NULL)              0x002 GetModuleHandleA(NULL)
//   0x004 GetModuleHandleExW(0, NULL), GetModuleHandleExW(FROM_ADDRESS, own code), GetModuleHandleW(own name)
//   0x008 GetModuleFileNameW(NULL) and (base): the file is this image (name, header fields)
//   0x010 GetModuleFileNameA(NULL) names the same file
//   0x020 PEB ImageBaseAddress                0x040 RCDATA resource 1 through FindResourceW(NULL) and (base)
//   0x080 GetModuleFileNameW into a 5-character buffer: truncated, returns 5, ERROR_INSUFFICIENT_BUFFER
#include <windows.h>

#pragma runtime_checks("", off)

extern "C" IMAGE_DOS_HEADER __ImageBase;

namespace {
constexpr wchar_t kName[] = L"x2w_identity_title.exe";
constexpr char kResource[] = "x2w-identity-resource";

HMODULE self() { return reinterpret_cast<HMODULE>(&__ImageBase); }

wchar_t lower(wchar_t c) { return c >= L'A' && c <= L'Z' ? static_cast<wchar_t>(c - L'A' + L'a') : c; }

bool names_this_file(const wchar_t* path, DWORD length) {
    DWORD start = length;
    while (start && path[start - 1] != L'\\' && path[start - 1] != L'/') --start;
    DWORD i = 0;
    for (; kName[i]; ++i)
        if (start + i >= length || lower(path[start + i]) != kName[i]) return false;
    return start + i == length;
}

// The file at path has this image's header fields.
bool same_image(const wchar_t* path) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                              OPEN_EXISTING, 0, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    static unsigned char header[4096];
    DWORD read = 0;
    const bool ok = ReadFile(file, header, sizeof header, &read, nullptr) && read == sizeof header;
    CloseHandle(file);
    if (!ok) return false;
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(header);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew < 0 || dos->e_lfanew > 4096 - 0x200) return false;
    const auto* disk = reinterpret_cast<const IMAGE_NT_HEADERS64*>(header + dos->e_lfanew);
    const auto* mine = reinterpret_cast<const IMAGE_NT_HEADERS64*>(
        reinterpret_cast<const unsigned char*>(&__ImageBase) + __ImageBase.e_lfanew);
    return disk->FileHeader.TimeDateStamp == mine->FileHeader.TimeDateStamp
        && disk->OptionalHeader.SizeOfImage == mine->OptionalHeader.SizeOfImage
        && disk->OptionalHeader.AddressOfEntryPoint == mine->OptionalHeader.AddressOfEntryPoint
        && disk->OptionalHeader.CheckSum == mine->OptionalHeader.CheckSum;
}

bool resource_from(HMODULE module) {
    HRSRC found = FindResourceW(module, MAKEINTRESOURCEW(1), MAKEINTRESOURCEW(10) /* RT_RCDATA */);
    if (!found) return false;
    HGLOBAL loaded = LoadResource(module, found);
    const auto* bytes = loaded ? static_cast<const char*>(LockResource(loaded)) : nullptr;
    const DWORD size = SizeofResource(module, found);
    if (!bytes || size < sizeof kResource - 1) return false;
    for (DWORD i = 0; i + 1 < sizeof kResource; ++i)
        if (bytes[i] != kResource[i]) return false;
    return true;
}
}  // namespace

extern "C" DWORD identity_entry(void*) {
    DWORD code = 0x100;
    if (GetModuleHandleW(nullptr) == self()) code |= 0x001;
    if (GetModuleHandleA(nullptr) == self()) code |= 0x002;
    HMODULE by_null = nullptr, by_address = nullptr;
    if (GetModuleHandleExW(0, nullptr, &by_null) && by_null == self()
        && GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                              reinterpret_cast<LPCWSTR>(&identity_entry), &by_address)
        && by_address == self() && GetModuleHandleW(kName) == self())
        code |= 0x004;
    static wchar_t wide[MAX_PATH], wide_base[MAX_PATH];
    const DWORD wide_length = GetModuleFileNameW(nullptr, wide, MAX_PATH);
    const DWORD base_length = GetModuleFileNameW(self(), wide_base, MAX_PATH);
    bool same = wide_length && wide_length < MAX_PATH && wide_length == base_length;
    for (DWORD i = 0; same && i < wide_length; ++i) same = wide[i] == wide_base[i];
    if (same && names_this_file(wide, wide_length) && same_image(wide)) code |= 0x008;
    static char ansi[MAX_PATH];
    const DWORD ansi_length = GetModuleFileNameA(nullptr, ansi, MAX_PATH);
    bool ansi_same = ansi_length == wide_length && names_this_file(wide, wide_length);
    for (DWORD i = 0; ansi_same && i < ansi_length; ++i) ansi_same = static_cast<wchar_t>(ansi[i]) == wide[i];
    if (ansi_same) code |= 0x010;
    const auto* peb = reinterpret_cast<const unsigned char*>(__readgsqword(0x60));
    if (*reinterpret_cast<void* const*>(peb + 0x10) == self()) code |= 0x020;
    if (resource_from(nullptr) && resource_from(self())) code |= 0x040;
    wchar_t short_buffer[5] = {L'x', L'x', L'x', L'x', L'x'};
    SetLastError(0);
    if (GetModuleFileNameW(nullptr, short_buffer, 5) == 5 && GetLastError() == ERROR_INSUFFICIENT_BUFFER
        && short_buffer[4] == 0)
        code |= 0x080;
    ExitProcess(code);
}
