// Pipeline translation, root signatures and draw-time bindings of the graphics shim (d3d12_xs_pipeline.h).
//
// Like the rest of the shim, nothing here has a dynamic initializer or thread-local storage: process-wide state is
// constant-initialized and filled once through INIT_ONCE, so the DLL keeps an empty TLS template.
#include "d3d12_xs_pipeline.h"
#include "d3d12_xs_api.h"
#include "d3d12_xs_descriptors.h"
#include "d3d12_xs_translator.h"
#include "d3d12_xs_wrap.h"
#include "era_title_gpu_api.h"

#include <wrl/client.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <map>
#include <new>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace d3d12_xs {
namespace pipeline {
namespace {

constexpr std::uint32_t root_magic = 0x52573258u;  // "X2WR"
constexpr std::uint32_t pso_magic = 0x50573258u;   // "X2WP"
constexpr std::uint32_t compute_pso_magic = 0x43573258u;  // "X2WC": a translated compute pipeline
// {6b1a3c52-0f6e-4f0e-9a5d-58325752e001} and ...02: private-data keys of RootInfo and PsoInfo.
constexpr GUID root_info_guid = {0x6b1a3c52, 0x0f6e, 0x4f0e, {0x9a, 0x5d, 0x58, 0x32, 0x57, 0x52, 0xe0, 0x01}};
constexpr GUID pso_info_guid = {0x6b1a3c52, 0x0f6e, 0x4f0e, {0x9a, 0x5d, 0x58, 0x32, 0x57, 0x52, 0xe0, 0x02}};
constexpr UINT runtime_space = 1000;
constexpr UINT runtime_memory_space = 1001;
constexpr UINT runtime_texture_space = 1002;
constexpr UINT runtime_pixel_constant_space = 1003;
constexpr UINT placeholder_space = 1004;
// Console-only root-signature flag bits (d3d12_xs_shim.cpp) and the DENY_*_SHADER_ROOT_ACCESS flags, which would
// hide the converter's parameters from the stages that read them.
constexpr std::uint32_t dropped_root_flags = 0x03000000u | 0x2u | 0x4u | 0x8u | 0x10u | 0x20u | 0x100u | 0x200u;

const char* const create_graphics = "d3d12_xs!ID3D12Device::CreateGraphicsPipelineState";

// --- SHA-256 (FIPS 180-4) ---------------------------------------------------------------------------------------

class Sha256 {
public:
    Sha256() { std::memcpy(h_, initial, sizeof(h_)); }
    void update(const void* data, std::size_t size)
    {
        const auto* p = static_cast<const std::uint8_t*>(data);
        total_ += size;
        while (size) {
            const std::size_t take = size < 64 - used_ ? size : 64 - used_;
            std::memcpy(block_ + used_, p, take);
            used_ += take;
            p += take;
            size -= take;
            if (used_ == 64) {
                compress();
                used_ = 0;
            }
        }
    }
    void update_u32(std::uint32_t value) { update(&value, 4); }
    void update_text(const std::string& text)
    {
        update_u32(static_cast<std::uint32_t>(text.size()));
        update(text.data(), text.size());
    }
    void finish(std::uint8_t out[32])
    {
        const std::uint64_t bits = total_ * 8;
        const std::uint8_t pad = 0x80;
        update(&pad, 1);
        const std::uint8_t zero = 0;
        while (used_ != 56) update(&zero, 1);
        for (int i = 7; i >= 0; --i) {
            const std::uint8_t byte = static_cast<std::uint8_t>(bits >> (8 * i));
            update(&byte, 1);
        }
        for (int i = 0; i < 8; ++i)
            for (int j = 0; j < 4; ++j) out[4 * i + j] = static_cast<std::uint8_t>(h_[i] >> (24 - 8 * j));
    }

private:
    static constexpr std::uint32_t initial[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                                 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    static std::uint32_t rotr(std::uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
    void compress()
    {
        static constexpr std::uint32_t k[64] = {
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
        std::uint32_t w[64];
        for (int i = 0; i < 16; ++i)
            w[i] = std::uint32_t(block_[4 * i]) << 24 | std::uint32_t(block_[4 * i + 1]) << 16 |
                   std::uint32_t(block_[4 * i + 2]) << 8 | block_[4 * i + 3];
        for (int i = 16; i < 64; ++i) {
            const std::uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
            const std::uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        std::uint32_t a = h_[0], b = h_[1], c = h_[2], d = h_[3], e = h_[4], f = h_[5], g = h_[6], h = h_[7];
        for (int i = 0; i < 64; ++i) {
            const std::uint32_t t1 = h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + k[i] + w[i];
            const std::uint32_t t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
            h = g;
            g = f;
            f = e;
            e = d + t1;
            d = c;
            c = b;
            b = a;
            a = t1 + t2;
        }
        h_[0] += a;
        h_[1] += b;
        h_[2] += c;
        h_[3] += d;
        h_[4] += e;
        h_[5] += f;
        h_[6] += g;
        h_[7] += h;
    }
    std::uint32_t h_[8];
    std::uint8_t block_[64]{};
    std::size_t used_ = 0;
    std::uint64_t total_ = 0;
};

std::string hex(const std::uint8_t* bytes, std::size_t count)
{
    static const char digits[] = "0123456789abcdef";
    std::string out;
    for (std::size_t i = 0; i < count; ++i) {
        out += digits[bytes[i] >> 4];
        out += digits[bytes[i] & 15];
    }
    return out;
}

// --- configuration ----------------------------------------------------------------------------------------------

std::wstring env(const wchar_t* name)
{
    wchar_t buffer[2048];
    const DWORD n = GetEnvironmentVariableW(name, buffer, 2048);
    return n && n < 2048 ? std::wstring(buffer, n) : std::wstring();
}

std::wstring module_directory()
{
    HMODULE self = nullptr;
    wchar_t path[MAX_PATH];
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            reinterpret_cast<LPCWSTR>(&module_directory), &self) ||
        !GetModuleFileNameW(self, path, MAX_PATH)) {
        return L".";
    }
    std::wstring dir = path;
    return dir.substr(0, dir.find_last_of(L"\\/"));
}

std::wstring title_name()
{
    std::wstring title = env(L"X2W_TITLE");
    if (!title.empty()) return title;
    wchar_t path[MAX_PATH];
    if (!GetModuleFileNameW(nullptr, path, MAX_PATH)) return L"unknown";
    title = path;
    title = title.substr(title.find_last_of(L"\\/") + 1);
    const auto dot = title.find_last_of(L'.');
    return dot == std::wstring::npos ? title : title.substr(0, dot);
}

std::string narrow(const std::wstring& text)
{
    std::string out;
    for (wchar_t c : text) out += c < 128 ? static_cast<char>(c) : '?';
    return out;
}

bool make_directories(const std::wstring& path)
{
    for (std::size_t at = path.find_first_of(L"\\/", 3); ; at = path.find_first_of(L"\\/", at + 1)) {
        const std::wstring part = path.substr(0, at);
        if (!CreateDirectoryW(part.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) return false;
        if (at == std::wstring::npos) return true;
    }
}

enum class Mode { service, process, defer };

struct Config {
    std::wstring python, tools, dxc, llvm, cache;  // cache: the title's directory
    std::uint8_t fingerprint[32];
    Mode mode = Mode::service;
    unsigned services = 1;  // most translator services at once
    bool keep_hlsl = false;
};
Config* g_config;
INIT_ONCE g_config_once = INIT_ONCE_STATIC_INIT;

// Hashes name, size and write time of every converter source (tools/*.py, tools/pixel_aot_ops/**, the TitleLookup
// header the HLSL includes) and of DXC: a converter or compiler change gives every shader a new key.
void fingerprint_tree(Sha256& sha, const std::wstring& dir, int depth)
{
    WIN32_FIND_DATAW found;
    HANDLE find = FindFirstFileW((dir + L"\\*").c_str(), &found);
    if (find == INVALID_HANDLE_VALUE) return;
    std::vector<std::wstring> names;
    do {
        names.push_back(found.cFileName);
    } while (FindNextFileW(find, &found));
    FindClose(find);
    // FindFirstFile's order is the file system's; sort for a stable key.
    for (std::size_t i = 1; i < names.size(); ++i)
        for (std::size_t j = i; j && names[j] < names[j - 1]; --j) std::swap(names[j], names[j - 1]);
    for (const std::wstring& name : names) {
        if (name == L"." || name == L".." || name == L"__pycache__") continue;
        const std::wstring path = dir + L"\\" + name;
        WIN32_FILE_ATTRIBUTE_DATA data;
        if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &data)) continue;
        if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (depth > 0) fingerprint_tree(sha, path, depth - 1);
            continue;
        }
        if (name.size() <= 3 || name.compare(name.size() - 3, 3, L".py") != 0) continue;
        sha.update_text(narrow(path.substr(path.find_last_of(L"\\/") + 1)));
        sha.update(&data.nFileSizeLow, 4);
        sha.update(&data.ftLastWriteTime, sizeof(data.ftLastWriteTime));
    }
}

BOOL CALLBACK load_config(PINIT_ONCE, PVOID, PVOID*)
{
    auto* config = new (std::nothrow) Config();
    if (!config) return TRUE;
    config->python = env(L"X2W_PYTHON");
    if (config->python.empty()) config->python = L"python.exe";
    config->tools = env(L"X2W_TOOLS");
    if (config->tools.empty()) config->tools = module_directory() + L"\\tools";
    config->dxc = env(L"X2W_DXC");
    if (config->dxc.empty()) config->dxc = L"dxc.exe";
    config->llvm = env(L"X2W_LLVM_LIB");
    std::wstring root = env(L"X2W_CACHE_DIR");
    if (root.empty()) root = env(L"LOCALAPPDATA") + L"\\XPortPC\\cache";
    config->cache = root + L"\\" + title_name();
    const std::wstring pycache = root + L"\\pycache";
    for (std::wstring* path : {&config->python, &config->tools, &config->dxc, &config->llvm, &config->cache})
        for (wchar_t& ch : *path)
            if (ch == L'/') ch = L'\\';
    Sha256 sha;
    sha.update_text("x2w-pso-translate-2");
    fingerprint_tree(sha, config->tools, 2);
    const std::wstring header = config->tools + L"\\..\\src";
    WIN32_FIND_DATAW found;
    HANDLE find = FindFirstFileW((header + L"\\title_va_lookup.hlsli").c_str(), &found);
    if (find != INVALID_HANDLE_VALUE) {
        sha.update(&found.nFileSizeLow, 4);
        sha.update(&found.ftLastWriteTime, sizeof(found.ftLastWriteTime));
        FindClose(find);
    }
    WIN32_FILE_ATTRIBUTE_DATA dxc;
    if (GetFileAttributesExW(config->dxc.c_str(), GetFileExInfoStandard, &dxc)) {
        sha.update(&dxc.nFileSizeLow, 4);
        sha.update(&dxc.ftLastWriteTime, sizeof(dxc.ftLastWriteTime));
    }
    sha.update_text(narrow(config->dxc));
    sha.update_text(narrow(config->llvm));
    sha.finish(config->fingerprint);
    const std::wstring mode = env(L"X2W_TRANSLATE");
    config->mode = mode == L"process" ? Mode::process : mode == L"defer" ? Mode::defer : Mode::service;
    const DWORD cores = GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
    config->services = cores > 2 ? (cores - 1 < 8 ? cores - 1 : 8) : 1;
    const std::wstring services = env(L"X2W_TRANSLATOR_SERVICES");
    if (!services.empty()) config->services = static_cast<unsigned>(wcstoul(services.c_str(), nullptr, 10));
    config->keep_hlsl = env(L"X2W_KEEP_HLSL") == L"1";
    translator::Settings settings;
    settings.python = config->python;
    settings.tools = config->tools;
    settings.dxc = config->dxc;
    settings.llvm = config->llvm;
    settings.scratch = config->cache;
    settings.pycache = pycache;
    settings.max_services = config->mode == Mode::service ? config->services : 0;
    translator::configure(settings);
    g_config = config;
    return TRUE;
}

const Config* config()
{
    InitOnceExecuteOnce(&g_config_once, load_config, nullptr, nullptr);
    return g_config;
}

// --- the console bytecode container -----------------------------------------------------------------------------

struct Program {
    std::uint32_t stage = 0;
    const std::uint8_t* code = nullptr;
    std::uint32_t code_bytes = 0;
    std::vector<X2WShaderBinding> bindings;
    X2WShaderComputeInfo compute{};  // compute stage only
};

enum class Parsed { desktop, container, malformed };

// The only place that reads a console shader container (d3d12_xs_api.h). Real titles' container format is
// learned from owner logs and parsed here.
Parsed parse_container(const void* data, SIZE_T size, Program& out, std::string& why)
{
    if (!data || size < 4) {
        why = "empty bytecode";
        return Parsed::malformed;
    }
    std::uint32_t magic;
    std::memcpy(&magic, data, 4);
    if (magic == 0x43425844u) return Parsed::desktop;  // "DXBC": a desktop DXIL or DXBC container
    if (magic != X2W_SHADER_CONTAINER_MAGIC) {
        char text[96];
        std::snprintf(text, sizeof(text), "unknown bytecode container (first word 0x%08x, %llu bytes)", magic,
                      static_cast<unsigned long long>(size));
        why = text;
        return Parsed::malformed;
    }
    X2WShaderContainer header;
    if (size < sizeof(header)) {
        why = "truncated container header";
        return Parsed::malformed;
    }
    std::memcpy(&header, data, sizeof(header));
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    const std::uint64_t binding_end =
        std::uint64_t(header.binding_offset) + std::uint64_t(header.binding_count) * sizeof(X2WShaderBinding);
    const std::uint64_t code_end = std::uint64_t(header.code_offset) + header.code_bytes;
    const bool compute = header.stage == X2W_SHADER_STAGE_COMPUTE;
    const std::uint64_t info_end = std::uint64_t(header.stage_info_offset) + sizeof(X2WShaderComputeInfo);
    if (header.version != X2W_SHADER_CONTAINER_VERSION || header.stage > X2W_SHADER_STAGE_COMPUTE ||
        (compute ? !header.stage_info_offset || header.stage_info_offset % 4 || info_end > size
                 : header.stage_info_offset != 0) ||
        header.binding_count > 32 || binding_end > size ||
        header.code_offset % 4 || header.code_bytes % 4 || !header.code_bytes || code_end > size) {
        why = "malformed container header";
        return Parsed::malformed;
    }
    if (compute) std::memcpy(&out.compute, bytes + header.stage_info_offset, sizeof(out.compute));
    out.stage = header.stage;
    out.code = bytes + header.code_offset;
    out.code_bytes = header.code_bytes;
    out.bindings.resize(header.binding_count);
    if (header.binding_count)
        std::memcpy(out.bindings.data(), bytes + header.binding_offset,
                    header.binding_count * sizeof(X2WShaderBinding));
    return Parsed::container;
}

// --- translation ------------------------------------------------------------------------------------------------

bool read_file(const std::wstring& path, std::vector<std::uint8_t>& out)
{
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr,
                              OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER size{};
    bool good = GetFileSizeEx(file, &size) && size.QuadPart > 0 && size.QuadPart < (64 << 20);
    if (good) {
        out.resize(static_cast<std::size_t>(size.QuadPart));
        DWORD read = 0;
        good = ReadFile(file, out.data(), static_cast<DWORD>(out.size()), &read, nullptr) && read == out.size();
    }
    CloseHandle(file);
    return good;
}

bool write_file(const std::wstring& path, const void* data, std::size_t size)
{
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    const bool good = WriteFile(file, data, static_cast<DWORD>(size), &written, nullptr) && written == size;
    CloseHandle(file);
    return good;
}

std::wstring widen(const std::string& text) { return std::wstring(text.begin(), text.end()); }

// Runs tools/pso_translate.py. Returns 0 translated, 1 refused (reason in `why`), 2 tool failure (in `why`).
int run_translator(const Config& c, const char* stage, const std::wstring& base, const Program& program,
                   const std::string& roles, std::string& why)
{
    const std::wstring code = base + L".code", roles_path = base + L".roles.json", log = base + L".log";
    const std::wstring output = base + L".dxil", bindings = base + L".bind";
    if (!write_file(code, program.code, program.code_bytes) || !write_file(roles_path, roles.data(), roles.size())) {
        why = "cannot write the translator's input files in the cache directory";
        return 2;
    }
    std::wstring command = L"\"" + c.python + L"\" -B \"" + c.tools + L"\\pso_translate.py\" --stage " +
                           widen(stage) + L" --code \"" + code + L"\" --roles \"" + roles_path + L"\" --dxc \"" +
                           c.dxc + L"\" --output \"" + output + L"\" --bindings \"" + bindings + L"\"";
    if (!c.llvm.empty()) command += L" --llvm \"" + c.llvm + L"\"";
    if (c.keep_hlsl) command += L" --hlsl \"" + base + L".hlsl\"";
    SECURITY_ATTRIBUTES inherit{sizeof(inherit), nullptr, TRUE};
    HANDLE log_file = CreateFileW(log.c_str(), GENERIC_WRITE, FILE_SHARE_READ, &inherit, CREATE_ALWAYS,
                                  FILE_ATTRIBUTE_NORMAL, nullptr);
    HANDLE nul = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &inherit, OPEN_EXISTING, 0,
                             nullptr);
    int result = 2;
    if (log_file != INVALID_HANDLE_VALUE && nul != INVALID_HANDLE_VALUE) {
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = nul;
        startup.hStdOutput = log_file;
        startup.hStdError = log_file;
        PROCESS_INFORMATION process{};
        std::vector<wchar_t> line(command.begin(), command.end());
        line.push_back(0);
        if (CreateProcessW(nullptr, line.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr, nullptr, &startup,
                           &process)) {
            DWORD exit_code = 2;
            if (WaitForSingleObject(process.hProcess, 300000) == WAIT_OBJECT_0) {
                GetExitCodeProcess(process.hProcess, &exit_code);
            } else {
                TerminateProcess(process.hProcess, 2);
                why = "translator timed out after 300 s";
            }
            CloseHandle(process.hThread);
            CloseHandle(process.hProcess);
            result = exit_code <= 1 ? static_cast<int>(exit_code) : 2;
        } else {
            char text[160];
            std::snprintf(text, sizeof(text), "cannot start the translator (%s, error %lu); set X2W_PYTHON/X2W_TOOLS",
                          narrow(c.python).c_str(), GetLastError());
            why = text;
        }
    }
    if (log_file != INVALID_HANDLE_VALUE) CloseHandle(log_file);
    if (nul != INVALID_HANDLE_VALUE) CloseHandle(nul);
    if (result != 0 && why.empty()) {
        std::vector<std::uint8_t> text;
        std::string all = read_file(log, text) ? std::string(text.begin(), text.end()) : std::string();
        // The reason is the last "refused:" or "tool failure:" line; otherwise the log's tail.
        const char* marker = result == 1 ? "refused: " : "tool failure: ";
        const auto at = all.rfind(marker);
        why = at != std::string::npos ? all.substr(at + std::strlen(marker)) : all.substr(all.size() > 400 ? all.size() - 400 : 0);
        while (!why.empty() && (why.back() == '\n' || why.back() == '\r')) why.pop_back();
        if (why.empty()) why = "translator failed without output";
    }
    DeleteFileW(code.c_str());
    DeleteFileW(roles_path.c_str());
    DeleteFileW(log.c_str());
    return result;
}

const char* stage_name(std::uint32_t stage)
{
    return stage == X2W_SHADER_STAGE_VERTEX ? "vertex" : stage == X2W_SHADER_STAGE_COMPUTE ? "compute" : "pixel";
}

// --- the pipeline manifest (tools/pso_cache.py) -----------------------------------------------------------------

SRWLOCK g_manifest_lock = SRWLOCK_INIT;
std::vector<std::string>* g_manifest;  // input ids already in manifest.txt, sorted
bool g_wrote_config;

std::string utf8(const std::wstring& text)
{
    if (text.empty()) return {};
    const int n = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    std::string out(n > 0 ? n : 0, '\0');
    if (n > 0) WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), &out[0], n, nullptr, nullptr);
    return out;
}

std::string json_string(const std::string& text)
{
    std::string out = "\"";
    for (char ch : text) {
        if (ch == '"' || ch == '\\') out += '\\';
        if (static_cast<unsigned char>(ch) < 0x20) continue;
        out += ch;
    }
    return out + "\"";
}

bool append_file(const std::wstring& path, const std::string& text)
{
    HANDLE file = CreateFileW(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    const bool good = WriteFile(file, text.data(), static_cast<DWORD>(text.size()), &written, nullptr) && written == text.size();
    CloseHandle(file);
    return good;
}

// Records a console shader in the title's manifest (once per input) with its inputs, so tools/precompile_cache.py
// can translate it ahead of the next launch. Best effort: a failure here never fails the pipeline.
void record(const Config& c, const Program& program, const std::string& roles)
{
    Sha256 sha;
    sha.update_text("x2w-pso-input-1");
    sha.update_u32(program.stage);
    sha.update_text(roles);
    sha.update_u32(program.code_bytes);
    sha.update(program.code, program.code_bytes);
    std::uint8_t digest[32];
    sha.finish(digest);
    const std::string id = hex(digest, 32);
    AcquireSRWLockExclusive(&g_manifest_lock);
    if (!g_manifest) {
        g_manifest = new (std::nothrow) std::vector<std::string>();
        std::vector<std::uint8_t> text;
        if (g_manifest && read_file(c.cache + L"\\manifest.txt", text)) {
            std::size_t at = 0;
            while (at + 64 <= text.size()) {
                g_manifest->emplace_back(reinterpret_cast<const char*>(text.data() + at), 64);
                while (at < text.size() && text[at] != '\n') ++at;
                ++at;
            }
            std::sort(g_manifest->begin(), g_manifest->end());
        }
    }
    if (!g_manifest) {
        ReleaseSRWLockExclusive(&g_manifest_lock);
        return;
    }
    const auto at = std::lower_bound(g_manifest->begin(), g_manifest->end(), id);
    if ((at == g_manifest->end() || *at != id) && make_directories(c.cache + L"\\inputs")) {
        if (!g_wrote_config) {
            const std::string text = "{\"tools\": " + json_string(utf8(c.tools)) + ", \"dxc\": " +
                                       json_string(utf8(c.dxc)) + ", \"llvm\": " + json_string(utf8(c.llvm)) +
                                       ", \"fingerprint\": \"" + hex(c.fingerprint, 32) + "\"}\n";
            g_wrote_config = write_file(c.cache + L"\\translator.json", text.data(), text.size());
        }
        const std::wstring base = c.cache + L"\\inputs\\" + widen(id);
        if (write_file(base + L".code", program.code, program.code_bytes) &&
            write_file(base + L".roles.json", roles.data(), roles.size()) &&
            append_file(c.cache + L"\\manifest.txt", id + " " + stage_name(program.stage) + "\n")) {
            g_manifest->insert(at, id);
        }
    }
    ReleaseSRWLockExclusive(&g_manifest_lock);
}

// --- translation of a pipeline's shaders ------------------------------------------------------------------------

// One console shader of a pipeline: its entry contract, key, and DXIL and descriptor-table reads
// (pso_translate.py --bindings) once found or translated.
struct Shader {
    const Program* program = nullptr;
    std::string roles, key, why, bindings;
    std::vector<std::uint8_t> dxil;
    bool found = false;
};

// The key, the cache lookup and the manifest record.
void look_up(const Config& c, Shader& s)
{
    Sha256 sha;
    sha.update(c.fingerprint, 32);
    sha.update_u32(s.program->stage);
    sha.update_text(s.roles);
    sha.update_u32(s.program->code_bytes);
    sha.update(s.program->code, s.program->code_bytes);
    std::uint8_t key[32];
    sha.finish(key);
    s.key = hex(key, 32);
    record(c, *s.program, s.roles);
    // The sidecar is stored first, so a DXIL file in the cache always has its bindings.
    std::vector<std::uint8_t> text;
    if (read_file(c.cache + L"\\" + widen(s.key) + L".bind", text) &&
        read_file(c.cache + L"\\" + widen(s.key) + L".dxil", s.dxil)) {
        s.bindings.assign(text.begin(), text.end());
        s.found = true;
        count_shader(true);
    }
}

// Moves <base>.bind, <base>.dxil (and its HLSL) to the shader's cache files, sidecar first, and reads them back.
bool store(const Config& c, Shader& s, const std::wstring& base)
{
    const std::wstring final_base = c.cache + L"\\" + widen(s.key);
    if (c.keep_hlsl) MoveFileExW((base + L".hlsl").c_str(), (final_base + L".hlsl").c_str(), MOVEFILE_REPLACE_EXISTING);
    std::vector<std::uint8_t> text;
    if (!MoveFileExW((base + L".bind").c_str(), (final_base + L".bind").c_str(), MOVEFILE_REPLACE_EXISTING) ||
        !MoveFileExW((base + L".dxil").c_str(), (final_base + L".dxil").c_str(), MOVEFILE_REPLACE_EXISTING) ||
        !read_file(final_base + L".dxil", s.dxil) || !read_file(final_base + L".bind", text)) {
        DeleteFileW((base + L".dxil").c_str());
        DeleteFileW((base + L".bind").c_str());
        s.why = "cannot store the translation in the cache";
        return false;
    }
    s.bindings.assign(text.begin(), text.end());
    count_shader(false);
    return true;
}

std::wstring unique_base(const Config& c, const Shader& s, unsigned index)
{
    wchar_t unique[64];
    std::swprintf(unique, 64, L".%lu.%lu.%u", GetCurrentProcessId(), GetCurrentThreadId(), index);
    return c.cache + L"\\" + widen(s.key) + unique;
}

// Translates the shaders not found in the cache, in order: through the translator services all at once, else (or
// for a shader the services could not take) one tools/pso_translate.py process each. As when they were translated
// one after another, the shaders after the first that fails are not stored. Returns the index of the first failure
// with its `why` set, or `count`.
std::size_t translate_misses(const Config& c, Shader* shaders, std::size_t count)
{
    std::vector<std::size_t> misses;
    for (std::size_t i = 0; i < count; ++i)
        if (!shaders[i].found) misses.push_back(i);
    if (misses.empty()) return count;
    if (c.mode == Mode::defer) {
        shaders[misses[0]].why = "deferred to tools/precompile_cache.py (X2W_TRANSLATE=defer); the shader is recorded";
        return misses[0];
    }
    if (!make_directories(c.cache)) {
        shaders[misses[0]].why = "cannot create the cache directory " + narrow(c.cache);
        return misses[0];
    }
    std::vector<translator::Request> requests(misses.size());
    std::vector<translator::Result> results(misses.size());
    if (c.mode == Mode::service) {
        for (std::size_t m = 0; m < misses.size(); ++m) {
            const Shader& s = shaders[misses[m]];
            requests[m].stage = s.program->stage;
            requests[m].code = s.program->code;
            requests[m].code_bytes = s.program->code_bytes;
            requests[m].roles = s.roles;
            requests[m].want_hlsl = c.keep_hlsl;
        }
        translator::translate(requests.data(), results.data(), requests.size());
    } else {
        for (auto& r : results) r.message = "X2W_TRANSLATE=process";
    }
    static LONG noted_service, noted_fallback;
    for (std::size_t m = 0; m < misses.size(); ++m) {
        Shader& s = shaders[misses[m]];
        translator::Result& r = results[m];
        const std::wstring base = unique_base(c, s, static_cast<unsigned>(m));
        const std::wstring produced = base + L".dxil";
        int status = r.status;
        if (status == translator::unavailable) {
            if (c.mode == Mode::service && !InterlockedExchange(&noted_fallback, 1)) {
                log_note(create_graphics, ("translator service unavailable (" + r.message +
                                           "); translating with one tools/pso_translate.py process per shader").c_str(),
                         nullptr);
            }
            status = run_translator(c, stage_name(s.program->stage), base, *s.program, s.roles, s.why);
        } else if (status == translator::translated) {
            if (!InterlockedExchange(&noted_service, 1))
                log_note(create_graphics, "shaders translated by the translator service (tools/pso_service.py)", nullptr);
            if (c.keep_hlsl) write_file(base + L".hlsl", r.hlsl.data(), r.hlsl.size());
            if (!write_file(base + L".bind", r.bindings.data(), r.bindings.size()) ||
                !write_file(produced, r.dxil.data(), r.dxil.size())) {
                DeleteFileW(produced.c_str());
                DeleteFileW((base + L".bind").c_str());
                s.why = "cannot write the translation in the cache directory";
                return misses[m];
            }
        } else {
            s.why = r.message;
        }
        if (status != translator::translated) {
            DeleteFileW(produced.c_str());
            DeleteFileW((base + L".bind").c_str());
            if (c.keep_hlsl) DeleteFileW((base + L".hlsl").c_str());
            if (status != translator::refused) s.why = "translator failure: " + s.why;
            return misses[m];
        }
        if (!store(c, s, base)) return misses[m];
    }
    return count;
}

void refuse(const char* stage, const std::string& key, const std::string& why)
{
    std::string detail = std::string(stage) + " shader";
    if (!key.empty()) detail += " " + key.substr(0, 16);
    detail += " refused: " + why + " -> E_NOTIMPL";
    log_refused(create_graphics, detail.c_str(), false);
}

}  // namespace


void RootArgs::clear()
{
    std::memset(address, 0, sizeof(address));
    std::memset(constants, 0, sizeof(constants));
}

// --- root signatures --------------------------------------------------------------------------------------------

HRESULT create_root_signature(ID3D12Device* device, UINT node_mask, const void* blob, SIZE_T size, REFIID riid,
                              void** out)
{
    ComPtr<ID3D12VersionedRootSignatureDeserializer> reader;
    const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* title = nullptr;
    if (FAILED(D3D12CreateVersionedRootSignatureDeserializer(blob, size, IID_PPV_ARGS(&reader))) ||
        FAILED(reader->GetRootSignatureDescAtVersion(D3D_ROOT_SIGNATURE_VERSION_1_1, &title)) || !title) {
        log_note("d3d12_xs!ID3D12Device::CreateRootSignature",
                 "blob is not a root signature desktop D3D12 reads; created as given, without converter parameters",
                 nullptr);
        return device->CreateRootSignature(node_mask, blob, size, riid, out);
    }
    const D3D12_ROOT_SIGNATURE_DESC1& desc = title->Desc_1_1;
    if (desc.NumParameters > max_title_params) {
        log_note("d3d12_xs!ID3D12Device::CreateRootSignature",
                 "more than 64 title parameters; created as given, without converter parameters", nullptr);
        return device->CreateRootSignature(node_mask, blob, size, riid, out);
    }
    std::vector<D3D12_ROOT_PARAMETER1> params(desc.pParameters, desc.pParameters + desc.NumParameters);
    RootInfo info{};
    info.magic = root_magic;
    info.title_params = desc.NumParameters;
    for (UINT i = 0; i < desc.NumParameters; ++i) {
        info.types[i] = static_cast<std::uint8_t>(params[i].ParameterType);
        if (params[i].ParameterType == D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS)
            info.constants[i] = static_cast<std::uint8_t>(params[i].Constants.Num32BitValues);
        if (params[i].ParameterType == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE) {
            // Its tables point into title heaps (d3d12_xs_descriptors.h); the slot keeps its index and its one word.
            params[i].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
            params[i].Constants = {i, placeholder_space, 1};
        }
    }
    // The title-memory table: SRVs t0..t7 space1001 (vertex and pixel translations), the miss counter, then UAVs
    // u0..u7 space1001 of the same ranges (the compute translation, R5).
    D3D12_DESCRIPTOR_RANGE1 memory[3]{};
    memory[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    memory[0].NumDescriptors = title_memory_slots;
    memory[0].RegisterSpace = runtime_memory_space;
    memory[0].Flags = D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE | D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE;
    memory[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;  // x2w_lookup_misses (u0 space1000)
    memory[1].NumDescriptors = 1;
    memory[1].RegisterSpace = runtime_space;
    memory[1].Flags = memory[0].Flags;
    memory[1].OffsetInDescriptorsFromTableStart = title_memory_slots;
    memory[2] = memory[0];
    memory[2].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    memory[2].OffsetInDescriptorsFromTableStart = title_memory_slots + 1;
    D3D12_DESCRIPTOR_RANGE1 textures{};
    textures.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    textures.NumDescriptors = texture_table;
    textures.RegisterSpace = runtime_texture_space;
    textures.Flags = D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE | D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE;
    D3D12_DESCRIPTOR_RANGE1 samplers{};
    samplers.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER;
    samplers.NumDescriptors = sampler_table;
    samplers.RegisterSpace = runtime_texture_space;
    samplers.Flags = D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE;
    D3D12_ROOT_PARAMETER1 extra[converter_params]{};
    for (auto& p : extra) p.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    extra[param_range_count].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    extra[param_range_count].Constants = {1, runtime_space, 1};
    extra[param_ranges].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
    extra[param_ranges].Descriptor = {2, runtime_space, D3D12_ROOT_DESCRIPTOR_FLAG_DATA_VOLATILE};
    extra[param_memory].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    extra[param_memory].DescriptorTable = {3, memory};
    extra[param_push_words].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    extra[param_push_words].Constants = {3, runtime_space, push_word_count};
    extra[param_vertex_root].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    extra[param_vertex_root].Constants = {2, runtime_space, 2};
    extra[param_vertex_root].ShaderVisibility = D3D12_SHADER_VISIBILITY_VERTEX;
    extra[param_vertex_constants].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    extra[param_vertex_constants].Descriptor = {0, runtime_space, D3D12_ROOT_DESCRIPTOR_FLAG_DATA_VOLATILE};
    extra[param_vertex_constants].ShaderVisibility = D3D12_SHADER_VISIBILITY_VERTEX;
    for (UINT k = 0; k < pixel_constant_slots; ++k) {
        D3D12_ROOT_PARAMETER1& p = extra[param_pixel_constants + k];
        p.ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
        p.Descriptor = {k, runtime_pixel_constant_space, D3D12_ROOT_DESCRIPTOR_FLAG_DATA_VOLATILE};
        p.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    }
    extra[param_textures].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    extra[param_textures].DescriptorTable = {1, &textures};
    extra[param_textures].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    extra[param_samplers].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    extra[param_samplers].DescriptorTable = {1, &samplers};
    extra[param_samplers].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    for (auto& p : extra) params.push_back(p);
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC copy{};
    copy.Version = D3D_ROOT_SIGNATURE_VERSION_1_1;
    copy.Desc_1_1 = desc;
    copy.Desc_1_1.NumParameters = static_cast<UINT>(params.size());
    copy.Desc_1_1.pParameters = params.data();
    copy.Desc_1_1.Flags =
        static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(static_cast<std::uint32_t>(desc.Flags) & ~dropped_root_flags);
    ComPtr<ID3DBlob> serialized, errors;
    HRESULT hr = D3D12SerializeVersionedRootSignature(&copy, &serialized, &errors);
    if (FAILED(hr)) {
        std::string detail = "converter parameters do not fit the title's root signature";
        if (errors) detail += std::string(": ") + static_cast<const char*>(errors->GetBufferPointer());
        detail += "; created as given";
        log_note("d3d12_xs!ID3D12Device::CreateRootSignature", detail.c_str(), nullptr);
        return device->CreateRootSignature(node_mask, blob, size, riid, out);
    }
    ComPtr<ID3D12RootSignature> root;
    hr = device->CreateRootSignature(node_mask, serialized->GetBufferPointer(), serialized->GetBufferSize(),
                                     IID_PPV_ARGS(&root));
    if (FAILED(hr)) return hr;
    root->SetPrivateData(root_info_guid, sizeof(info), &info);
    return root->QueryInterface(riid, out);
}

bool root_info(ID3D12RootSignature* root, RootInfo* info)
{
    UINT size = sizeof(*info);
    return root && SUCCEEDED(root->GetPrivateData(root_info_guid, &size, info)) && size == sizeof(*info) &&
           info->magic == root_magic;
}

bool pso_info(ID3D12PipelineState* state, PsoInfo* info)
{
    UINT size = sizeof(*info);
    return state && SUCCEEDED(state->GetPrivateData(pso_info_guid, &size, info)) && size == sizeof(*info) &&
           info->magic == pso_magic;
}

// --- pipelines --------------------------------------------------------------------------------------------------

namespace {

// Why a root-word binding cannot be read, or null.
const char* root_word_problem(const RootInfo& root, const X2WShaderBinding& b)
{
    if (b.root_parameter >= root.title_params) return "a binding names a root parameter the root signature does not have";
    const auto type = static_cast<D3D12_ROOT_PARAMETER_TYPE>(root.types[b.root_parameter]);
    if (type == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE)
        return "a root-word binding names a descriptor table parameter (bind it as a descriptor table)";
    const bool address = type == D3D12_ROOT_PARAMETER_TYPE_CBV || type == D3D12_ROOT_PARAMETER_TYPE_SRV ||
                         type == D3D12_ROOT_PARAMETER_TYPE_UAV;
    if (address ? b.word > 1 : b.word >= root.constants[b.root_parameter]) return "a binding reads past its root parameter";
    return nullptr;
}

const char* table_problem(const RootInfo& root, const X2WShaderBinding& b)
{
    if (b.root_parameter >= root.title_params) return "a binding names a root parameter the root signature does not have";
    if (root.types[b.root_parameter] != D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE)
        return "a descriptor-table binding names a parameter that is not a descriptor table";
    if (b.word != 0) return "a descriptor-table binding has a word other than 0 (the table address is 32 bits)";
    return nullptr;
}

// Reads pso_translate.py's --bindings text into `info`. Returns null or the reason it cannot be bound.
const char* add_refs(const std::string& text, std::uint32_t stage, const std::vector<UINT>& tables, PsoInfo& info)
{
    std::size_t at = text.find('\n');
    if (text.compare(0, at, "x2w-bindings 1") != 0) return "the translator's bindings have an unknown format";
    while (at != std::string::npos && at + 1 < text.size()) {
        const std::size_t next = text.find('\n', at + 1);
        const std::string line = text.substr(at + 1, next == std::string::npos ? std::string::npos : next - at - 1);
        at = next;
        char kind[16] = {};
        unsigned slot = 0, set = 0, offset = 0;
        if (std::sscanf(line.c_str(), "%15s %u %u %u", kind, &slot, &set, &offset) != 4) return "malformed bindings line";
        TableRef ref{};
        ref.stage = static_cast<std::uint8_t>(stage);
        if (!std::strcmp(kind, "texture")) ref.kind = RefKind::texture;
        else if (!std::strcmp(kind, "sampler")) ref.kind = RefKind::sampler;
        else if (!std::strcmp(kind, "constants")) ref.kind = RefKind::constants;
        else return "unknown kind of descriptor in the bindings";
        const unsigned slots = ref.kind == RefKind::texture   ? 8
                               : ref.kind == RefKind::sampler ? sampler_table
                               : stage == X2W_SHADER_STAGE_VERTEX ? 1
                                                                  : pixel_constant_slots;
        if (slot >= slots) return "a descriptor slot the runtime does not bind";
        if (set >= tables.size()) return "a descriptor read through a set the container does not bind";
        const UINT increment = ref.kind == RefKind::sampler ? descriptors::sampler_increment : descriptors::view_increment;
        if (offset % increment)
            return ref.kind == RefKind::sampler
                       ? "an S# at a table offset that is not a multiple of 16 (the sampler descriptor size)"
                       : "a T# or V# at a table offset that is not a multiple of 32 (the CBV/SRV/UAV descriptor size)";
        if (info.ref_count == max_table_refs) return "more than 24 descriptor-table reads in one pipeline";
        ref.slot = static_cast<std::uint8_t>(slot);
        ref.parameter = static_cast<std::uint8_t>(tables[set]);
        ref.offset = offset;
        info.refs[info.ref_count++] = ref;
    }
    return nullptr;
}

}  // namespace

namespace {

// The shaders of a graphics pipeline after translation: desktop (nothing to translate), or translated DXIL and the
// pipeline's binding record.
struct GraphicsTranslation {
    bool translated = false;
    std::vector<std::uint8_t> vs, ps;
    PsoInfo info{};
};

// Translates the console shaders of a graphics pipeline. S_OK with translated=false for desktop bytecode; E_NOTIMPL
// after a logged refusal.
HRESULT translate_graphics(const D3D12_SHADER_BYTECODE& vs_code, const D3D12_SHADER_BYTECODE& ps_code,
                           bool other_stages, ID3D12RootSignature* root_signature, GraphicsTranslation& result)
{
    Program vs, ps;
    std::string why;
    const Parsed vs_kind = vs_code.BytecodeLength ? parse_container(vs_code.pShaderBytecode, vs_code.BytecodeLength, vs, why)
                                                   : Parsed::desktop;
    if (vs_kind == Parsed::malformed) {
        refuse("vertex", "", why);
        return E_NOTIMPL;
    }
    const Parsed ps_kind = ps_code.BytecodeLength ? parse_container(ps_code.pShaderBytecode, ps_code.BytecodeLength, ps, why)
                                                   : Parsed::desktop;
    if (ps_kind == Parsed::malformed) {
        refuse("pixel", "", why);
        return E_NOTIMPL;
    }
    if (vs_kind == Parsed::desktop && ps_kind == Parsed::desktop) return S_OK;

    // A console pipeline: every present stage must be a console shader of the stage it is bound to.
    if (vs_kind != Parsed::container || (ps_code.BytecodeLength && ps_kind != Parsed::container)) {
        refuse(vs_kind == Parsed::container ? "pixel" : "vertex", "",
               "desktop bytecode beside a console shader in one pipeline");
        return E_NOTIMPL;
    }
    if (other_stages) {
        refuse("vertex", "", "geometry, tessellation or stream output with console shaders is not translated");
        return E_NOTIMPL;
    }
    if (vs.stage != X2W_SHADER_STAGE_VERTEX || (ps_code.BytecodeLength && ps.stage != X2W_SHADER_STAGE_PIXEL)) {
        refuse("vertex", "", "a container's stage does not match the pipeline stage it is bound to");
        return E_NOTIMPL;
    }
    RootInfo root{};
    if (!root_info(root_signature, &root)) {
        refuse("vertex", "", "the root signature was not created through the shim, so it has no converter parameters");
        return E_NOTIMPL;
    }

    // Entry contracts. Root words become push words, numbered across both stages in binding order (vertex_aot role
    // "inline", pixel role "push:W"); descriptor tables become descriptor sets, numbered per stage in binding order.
    PsoInfo info{};
    info.magic = pso_magic;
    std::vector<UINT> tables[2];
    const auto push_word = [&](const X2WShaderBinding& b, const char* stage) -> bool {
        if (const char* problem = root_word_problem(root, b)) {
            refuse(stage, "", problem);
            return false;
        }
        if (info.push_count == push_word_count) {
            refuse(stage, "", "more than 32 root-word bindings in one pipeline");
            return false;
        }
        info.push[info.push_count++] = {static_cast<std::uint8_t>(b.root_parameter), static_cast<std::uint8_t>(b.word)};
        return true;
    };
    std::string vs_roles = "{\"user_sgprs\": {", ps_roles = "{\"sgprs\": {";
    bool used[106] = {};
    for (const X2WShaderBinding& b : vs.bindings) {
        char entry[96];
        if (b.sgpr > 105 || used[b.sgpr]) {
            refuse("vertex", "", "an entry SGPR is out of range or bound twice");
            return E_NOTIMPL;
        }
        used[b.sgpr] = true;
        if (b.kind == X2W_SHADER_BINDING_ROOT_WORD) {
            if (!push_word(b, "vertex")) return E_NOTIMPL;
            std::snprintf(entry, sizeof(entry), "\"%u\": {\"role\": \"inline\", \"word\": %u}", b.sgpr, info.push_count - 1);
        } else if (b.kind == X2W_SHADER_BINDING_TABLE) {
            if (const char* problem = table_problem(root, b)) {
                refuse("vertex", "", problem);
                return E_NOTIMPL;
            }
            std::snprintf(entry, sizeof(entry), "\"%u\": {\"role\": \"descriptors\", \"set\": %u}", b.sgpr,
                          static_cast<unsigned>(tables[0].size()));
            tables[0].push_back(b.root_parameter);
        } else if (b.kind == X2W_SHADER_BINDING_BASE_VERTEX || b.kind == X2W_SHADER_BINDING_START_INSTANCE) {
            std::snprintf(entry, sizeof(entry), "\"%u\": {\"role\": \"%s\"}", b.sgpr,
                          b.kind == X2W_SHADER_BINDING_BASE_VERTEX ? "base_vertex" : "start_instance");
        } else {
            refuse("vertex", "", "a vertex binding of a kind the vertex stage does not have (interpolation base)");
            return E_NOTIMPL;
        }
        if (vs_roles.back() != '{') vs_roles += ", ";
        vs_roles += entry;
    }
    vs_roles += "}}";
    std::memset(used, 0, sizeof(used));
    for (const X2WShaderBinding& b : ps.bindings) {
        char entry[64];
        if (b.sgpr > 105 || used[b.sgpr]) {
            refuse("pixel", "", "an entry SGPR is out of range or bound twice");
            return E_NOTIMPL;
        }
        used[b.sgpr] = true;
        if (b.kind == X2W_SHADER_BINDING_INTERP) {
            std::snprintf(entry, sizeof(entry), "\"s%u\": \"interp\"", b.sgpr);
        } else if (b.kind == X2W_SHADER_BINDING_ROOT_WORD) {
            if (!push_word(b, "pixel")) return E_NOTIMPL;
            std::snprintf(entry, sizeof(entry), "\"s%u\": \"push:%u\"", b.sgpr, info.push_count - 1);
        } else if (b.kind == X2W_SHADER_BINDING_TABLE) {
            if (const char* problem = table_problem(root, b)) {
                refuse("pixel", "", problem);
                return E_NOTIMPL;
            }
            if (tables[1].size() == 8) {
                refuse("pixel", "", "more than 8 descriptor tables in a pixel program");
                return E_NOTIMPL;
            }
            if (tables[1].empty()) std::snprintf(entry, sizeof(entry), "\"s%u\": \"descriptors\"", b.sgpr);
            else std::snprintf(entry, sizeof(entry), "\"s%u\": \"descriptors.%u\"", b.sgpr, static_cast<unsigned>(tables[1].size()));
            tables[1].push_back(b.root_parameter);
        } else {
            refuse("pixel", "", "a pixel binding of a kind the pixel stage does not have (base vertex, start instance)");
            return E_NOTIMPL;
        }
        if (ps_roles.back() != '{') ps_roles += ", ";
        ps_roles += entry;
    }
    ps_roles += "}}";

    const Config* c = config();
    if (!c) {
        refuse("vertex", "", "out of memory");
        return E_NOTIMPL;
    }
    Shader shaders[2];
    shaders[0].program = &vs;
    shaders[0].roles = vs_roles;
    shaders[1].program = &ps;
    shaders[1].roles = ps_roles;
    const std::size_t count = ps_code.BytecodeLength ? 2 : 1;
    for (std::size_t i = 0; i < count; ++i) look_up(*c, shaders[i]);
    // The pipeline's missing shaders translate together; the first that fails is reported, as when they were
    // translated one after another.
    const std::size_t failed = translate_misses(*c, shaders, count);
    for (std::size_t i = 0; i < count; ++i) {
        const char* stage = i ? "pixel" : "vertex";
        if (i == failed) {
            refuse(stage, shaders[i].key, shaders[i].why);
            return E_NOTIMPL;
        }
        if (const char* problem = add_refs(shaders[i].bindings, i ? X2W_SHADER_STAGE_PIXEL : X2W_SHADER_STAGE_VERTEX,
                                           tables[i], info)) {
            refuse(stage, shaders[i].key, problem);
            return E_NOTIMPL;
        }
    }
    result.translated = true;
    result.vs = std::move(shaders[0].dxil);
    if (ps_code.BytecodeLength) result.ps = std::move(shaders[1].dxil);
    result.info = info;
    return S_OK;
}

}  // namespace

HRESULT create_graphics_pipeline(ID3D12Device* device, const D3D12_GRAPHICS_PIPELINE_STATE_DESC* desc, REFIID riid,
                                 void** out)
{
    if (!desc) return device->CreateGraphicsPipelineState(desc, riid, out);
    GraphicsTranslation t;
    const bool other = desc->GS.BytecodeLength || desc->HS.BytecodeLength || desc->DS.BytecodeLength ||
                       desc->StreamOutput.NumEntries;
    if (FAILED(translate_graphics(desc->VS, desc->PS, other, desc->pRootSignature, t))) return E_NOTIMPL;
    if (!t.translated) return device->CreateGraphicsPipelineState(desc, riid, out);
    D3D12_GRAPHICS_PIPELINE_STATE_DESC copy = *desc;
    copy.VS = {t.vs.data(), t.vs.size()};
    if (desc->PS.BytecodeLength) copy.PS = {t.ps.data(), t.ps.size()};
    // Vertex data is read through title memory, not the input assembler.
    copy.InputLayout = {nullptr, 0};
    ComPtr<ID3D12PipelineState> state;
    const HRESULT hr = device->CreateGraphicsPipelineState(&copy, IID_PPV_ARGS(&state));
    if (FAILED(hr)) {
        char detail[160];
        std::snprintf(detail, sizeof(detail), "desktop CreateGraphicsPipelineState of the translation -> 0x%08lx",
                      static_cast<unsigned long>(hr));
        log_refused(create_graphics, detail, false);
        return hr;
    }
    state->SetPrivateData(pso_info_guid, sizeof(t.info), &t.info);
    return state->QueryInterface(riid, out);
}

// Compute (runtime rung R5). The entry contract: each root-word SGPR becomes the next push word, which the program
// reads as its inline user-data word of that index (tools/compute_aot.py's user:N role, from push_words); a
// workgroup-id binding is SV_GroupID's component. The workgroup and wave size come from the container's
// X2WShaderComputeInfo and are part of the key.
namespace {

const char* const create_compute = "d3d12_xs!ID3D12Device::CreateComputePipelineState";

struct ComputeTranslation {
    bool translated = false;
    std::vector<std::uint8_t> cs;
    PsoInfo info{};
};

// Translates the console shader of a compute pipeline; the contract of translate_graphics.
HRESULT translate_compute(const D3D12_SHADER_BYTECODE& cs_code, ID3D12RootSignature* root_signature,
                          ComputeTranslation& result)
{
    const char* symbol = create_compute;
    const auto refuse_cs = [symbol](const std::string& key, const std::string& why) {
        std::string detail = "compute shader";
        if (!key.empty()) detail += " " + key.substr(0, 16);
        detail += " refused: " + why + " -> E_NOTIMPL";
        log_refused(symbol, detail.c_str(), false);
        return E_NOTIMPL;
    };
    if (!cs_code.BytecodeLength) return S_OK;
    Program cs;
    std::string why;
    const Parsed kind = parse_container(cs_code.pShaderBytecode, cs_code.BytecodeLength, cs, why);
    if (kind == Parsed::desktop) return S_OK;
    if (kind == Parsed::malformed) return refuse_cs("", why);
    if (cs.stage != X2W_SHADER_STAGE_COMPUTE)
        return refuse_cs("", "a container's stage does not match the pipeline stage it is bound to");
    RootInfo root{};
    if (!root_info(root_signature, &root))
        return refuse_cs("", "the root signature was not created through the shim, so it has no converter parameters");

    PsoInfo info{};
    info.magic = compute_pso_magic;
    std::string roles = "{\"sgprs\": {";
    bool used[106] = {}, group[3] = {}, first = true;
    for (const X2WShaderBinding& b : cs.bindings) {
        if (b.sgpr > 105 || used[b.sgpr]) return refuse_cs("", "an entry SGPR is out of range or bound twice");
        used[b.sgpr] = true;
        char entry[64];
        if (b.kind == X2W_SHADER_BINDING_GROUP_ID) {
            if (b.word > 2 || group[b.word]) return refuse_cs("", "a workgroup id component is out of range or bound twice");
            group[b.word] = true;
            std::snprintf(entry, sizeof(entry), "%s\"s%u\": \"group_id.%c\"", first ? "" : ", ", b.sgpr,
                          "xyz"[b.word]);
            roles += entry;
            first = false;
            continue;
        }
        if (b.kind != X2W_SHADER_BINDING_ROOT_WORD)
            return refuse_cs("", "a compute binding other than a root-parameter word or a workgroup id");
        if (b.root_parameter >= root.title_params)
            return refuse_cs("", "a binding names a root parameter the root signature does not have");
        const auto type = static_cast<D3D12_ROOT_PARAMETER_TYPE>(root.types[b.root_parameter]);
        const bool address = type == D3D12_ROOT_PARAMETER_TYPE_CBV || type == D3D12_ROOT_PARAMETER_TYPE_SRV ||
                             type == D3D12_ROOT_PARAMETER_TYPE_UAV;
        if (type == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE ||
            (address ? b.word > 1 : b.word >= root.constants[b.root_parameter])) {
            return refuse_cs("", type == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE
                                     ? "a binding reads a descriptor table parameter (descriptor heaps come with R4)"
                                     : "a binding reads past its root parameter");
        }
        if (info.push_count == push_word_count) return refuse_cs("", "more than 32 root-word bindings");
        std::snprintf(entry, sizeof(entry), "%s\"s%u\": \"user:%u\"", first ? "" : ", ", b.sgpr,
                      info.push_count);
        roles += entry;
        first = false;
        info.push[info.push_count++] = {static_cast<std::uint8_t>(b.root_parameter), static_cast<std::uint8_t>(b.word)};
    }
    char tail[160];
    std::snprintf(tail, sizeof(tail), "}, \"numthreads\": [%u, %u, %u], \"wave\": %u, \"local_ids\": %u}",
                  cs.compute.numthreads[0], cs.compute.numthreads[1], cs.compute.numthreads[2], cs.compute.wave,
                  cs.compute.local_ids);
    roles += tail;

    const Config* c = config();
    if (!c) return refuse_cs("", "out of memory");
    Shader shader;
    shader.program = &cs;
    shader.roles = roles;
    look_up(*c, shader);
    if (translate_misses(*c, &shader, 1) == 0) return refuse_cs(shader.key, shader.why);
    const std::string& key = shader.key;
    const std::vector<std::uint8_t>& dxil = shader.dxil;
    if (shader.bindings != "x2w-bindings 1\n")
        return refuse_cs(key, "the translation reads descriptor tables, which compute pipelines do not bind yet");
    result.translated = true;
    result.cs = dxil;
    result.info = info;
    return S_OK;
}

}  // namespace

HRESULT create_compute_pipeline(ID3D12Device* device, const D3D12_COMPUTE_PIPELINE_STATE_DESC* desc, REFIID riid,
                                void** out)
{
    if (!desc) return device->CreateComputePipelineState(desc, riid, out);
    ComputeTranslation t;
    if (FAILED(translate_compute(desc->CS, desc->pRootSignature, t))) return E_NOTIMPL;
    if (!t.translated) return device->CreateComputePipelineState(desc, riid, out);
    D3D12_COMPUTE_PIPELINE_STATE_DESC copy = *desc;
    copy.CS = {t.cs.data(), t.cs.size()};
    ComPtr<ID3D12PipelineState> state;
    const HRESULT hr = device->CreateComputePipelineState(&copy, IID_PPV_ARGS(&state));
    if (FAILED(hr)) {
        char detail[160];
        std::snprintf(detail, sizeof(detail), "desktop CreateComputePipelineState of the translation -> 0x%08lx",
                      static_cast<unsigned long>(hr));
        log_refused(create_compute, detail, false);
        return hr;
    }
    state->SetPrivateData(pso_info_guid, sizeof(t.info), &t.info);
    return state->QueryInterface(riid, out);
}

// --- pipeline state streams (ID3D12Device2::CreatePipelineState) ----------------------------------------------

namespace {

const char* const create_stream = "d3d12_xs!ID3D12Device2::CreatePipelineState";

// Size and alignment of a subobject's payload, by D3D12_PIPELINE_STATE_SUBOBJECT_TYPE. Each subobject is the type
// word, then the payload at its natural alignment, padded to pointer alignment (the CD3DX12 stream layout). Types
// past the SDK header this builds with are listed by value, from the public DirectX-Headers definitions.
bool subobject_layout(UINT type, std::size_t* size, std::size_t* align)
{
    switch (type) {
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_ROOT_SIGNATURE: *size = sizeof(void*); *align = alignof(void*); return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_VS:
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_PS:
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_DS:
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_HS:
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_GS:
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_CS:
    case 24:  // AS
    case 25:  // MS
        *size = sizeof(D3D12_SHADER_BYTECODE); *align = alignof(D3D12_SHADER_BYTECODE); return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_STREAM_OUTPUT:
        *size = sizeof(D3D12_STREAM_OUTPUT_DESC); *align = alignof(D3D12_STREAM_OUTPUT_DESC); return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_BLEND: *size = sizeof(D3D12_BLEND_DESC); *align = 4; return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_SAMPLE_MASK: *size = 4; *align = 4; return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_RASTERIZER: *size = sizeof(D3D12_RASTERIZER_DESC); *align = 4; return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_DEPTH_STENCIL:
        *size = sizeof(D3D12_DEPTH_STENCIL_DESC); *align = 4; return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_INPUT_LAYOUT:
        *size = sizeof(D3D12_INPUT_LAYOUT_DESC); *align = alignof(D3D12_INPUT_LAYOUT_DESC); return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_IB_STRIP_CUT_VALUE:
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_PRIMITIVE_TOPOLOGY:
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_DEPTH_STENCIL_FORMAT:
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_NODE_MASK:
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_FLAGS:
        *size = 4; *align = 4; return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_RENDER_TARGET_FORMATS:
        *size = sizeof(D3D12_RT_FORMAT_ARRAY); *align = 4; return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_SAMPLE_DESC: *size = sizeof(DXGI_SAMPLE_DESC); *align = 4; return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_CACHED_PSO:
        *size = sizeof(D3D12_CACHED_PIPELINE_STATE); *align = alignof(D3D12_CACHED_PIPELINE_STATE); return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_DEPTH_STENCIL1:
        *size = sizeof(D3D12_DEPTH_STENCIL_DESC1); *align = 4; return true;
    case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_VIEW_INSTANCING:
        *size = sizeof(D3D12_VIEW_INSTANCING_DESC); *align = alignof(D3D12_VIEW_INSTANCING_DESC); return true;
    case 26: *size = 60; *align = 4; return true;  // DEPTH_STENCIL2: D3D12_DEPTH_STENCIL_DESC2
    case 27: *size = 44; *align = 4; return true;  // RASTERIZER1: D3D12_RASTERIZER_DESC1
    case 28: *size = 40; *align = 4; return true;  // RASTERIZER2: D3D12_RASTERIZER_DESC2
    case 29: *size = 2 * sizeof(void*); *align = alignof(void*); return true;  // SERIALIZED_ROOT_SIGNATURE
    default: return false;
    }
}
static_assert(sizeof(D3D12_SHADER_BYTECODE) == 16 && sizeof(D3D12_INPUT_LAYOUT_DESC) == 16);

std::size_t round_up(std::size_t value, std::size_t align) { return (value + align - 1) / align * align; }

struct Subobject {
    UINT type;
    std::size_t payload;  // byte offset of the payload in the stream
};

// Walks a stream. False, with `why`, when it cannot be walked (an unknown type, a subobject past the end).
bool walk_stream(const D3D12_PIPELINE_STATE_STREAM_DESC& desc, std::vector<Subobject>& out, std::string& why)
{
    const auto* bytes = static_cast<const std::uint8_t*>(desc.pPipelineStateSubobjectStream);
    std::size_t at = 0;
    while (at < desc.SizeInBytes) {
        if (desc.SizeInBytes - at < sizeof(UINT)) {
            why = "a truncated subobject";
            return false;
        }
        UINT type;
        std::memcpy(&type, bytes + at, sizeof(type));
        std::size_t size = 0, align = 0;
        if (!subobject_layout(type, &size, &align)) {
            why = "subobject type " + std::to_string(type) + " is not known to the shim";
            return false;
        }
        const std::size_t payload = round_up(at + sizeof(UINT), align);
        const std::size_t end = round_up(payload + size, alignof(void*));
        if (payload + size > desc.SizeInBytes) {
            why = "a subobject runs past the stream's size";
            return false;
        }
        out.push_back({type, payload});
        at = end;
    }
    return true;
}

// Bytecode the shim translates: anything that is not a desktop DXBC/DXIL container (parse_container decides).
bool console_bytecode(const D3D12_SHADER_BYTECODE& code)
{
    if (!code.pShaderBytecode || code.BytecodeLength < 4) return false;
    std::uint32_t magic;
    std::memcpy(&magic, code.pShaderBytecode, 4);
    return magic != 0x43425844u;  // "DXBC"
}

}  // namespace

HRESULT create_pipeline_state(ID3D12Device2* device, const D3D12_PIPELINE_STATE_STREAM_DESC* desc, REFIID riid,
                              void** out)
{
    if (!desc || !desc->pPipelineStateSubobjectStream || !desc->SizeInBytes) return device->CreatePipelineState(desc, riid, out);
    std::vector<Subobject> subobjects;
    std::string why;
    if (!walk_stream(*desc, subobjects, why)) {
        // Unwalkable: no console shader can be found in it, so it goes to desktop D3D12, which validates it (a console
        // container there fails creation rather than drawing anything).
        log_note(create_stream, (why + "; the stream is passed to desktop D3D12 unchanged").c_str(), nullptr);
        return device->CreatePipelineState(desc, riid, out);
    }
    const auto* bytes = static_cast<const std::uint8_t*>(desc->pPipelineStateSubobjectStream);
    const auto bytecode = [&](const Subobject& s) {
        D3D12_SHADER_BYTECODE code;
        std::memcpy(&code, bytes + s.payload, sizeof(code));
        return code;
    };
    D3D12_SHADER_BYTECODE vs{}, ps{}, cs{};
    std::size_t vs_at = 0, ps_at = 0, cs_at = 0;
    bool console = false, mesh = false, other = false, serialized_root = false;
    ID3D12RootSignature* root = nullptr;
    for (const Subobject& s : subobjects) {
        switch (s.type) {
        case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_ROOT_SIGNATURE:
            std::memcpy(&root, bytes + s.payload, sizeof(root));
            break;
        case 29: serialized_root = true; break;
        case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_VS: vs = bytecode(s); vs_at = s.payload; break;
        case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_PS: ps = bytecode(s); ps_at = s.payload; break;
        case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_CS: cs = bytecode(s); cs_at = s.payload; break;
        case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_DS:
        case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_HS:
        case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_GS:
            other = other || bytecode(s).BytecodeLength;
            console = console || console_bytecode(bytecode(s));
            break;
        case 24:
        case 25:
            mesh = mesh || bytecode(s).BytecodeLength;
            console = console || console_bytecode(bytecode(s));
            break;
        case D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_STREAM_OUTPUT: {
            D3D12_STREAM_OUTPUT_DESC so;
            std::memcpy(&so, bytes + s.payload, sizeof(so));
            other = other || so.NumEntries;
            break;
        }
        default: break;
        }
    }
    console = console || console_bytecode(vs) || console_bytecode(ps) || console_bytecode(cs);
    if (!console) return device->CreatePipelineState(desc, riid, out);

    if (mesh) {
        log_refused(create_stream,
                    "mesh or amplification pipeline with console shaders refused: the converter has no mesh or "
                    "amplification lowering -> E_NOTIMPL",
                    false);
        return E_NOTIMPL;
    }
    if (serialized_root) {
        log_refused(create_stream,
                    "console shaders with a serialized root signature subobject refused: translation needs a root "
                    "signature created through the shim -> E_NOTIMPL",
                    false);
        return E_NOTIMPL;
    }
    std::vector<std::uint64_t> storage((desc->SizeInBytes + 7) / 8);
    std::memcpy(storage.data(), bytes, desc->SizeInBytes);
    auto* copy = reinterpret_cast<std::uint8_t*>(storage.data());
    PsoInfo info{};
    GraphicsTranslation g;
    ComputeTranslation c;
    if (cs.BytecodeLength) {
        if (vs.BytecodeLength || ps.BytecodeLength || other) {
            log_refused(create_stream, "a stream with both a compute shader and graphics shaders -> E_NOTIMPL", false);
            return E_NOTIMPL;
        }
        if (FAILED(translate_compute(cs, root, c))) return E_NOTIMPL;
        const D3D12_SHADER_BYTECODE patched{c.cs.data(), c.cs.size()};
        std::memcpy(copy + cs_at, &patched, sizeof(patched));
        info = c.info;
    } else {
        if (FAILED(translate_graphics(vs, ps, other, root, g))) return E_NOTIMPL;
        const D3D12_SHADER_BYTECODE patched_vs{g.vs.data(), g.vs.size()};
        std::memcpy(copy + vs_at, &patched_vs, sizeof(patched_vs));
        if (ps.BytecodeLength) {
            const D3D12_SHADER_BYTECODE patched_ps{g.ps.data(), g.ps.size()};
            std::memcpy(copy + ps_at, &patched_ps, sizeof(patched_ps));
        }
        // Vertex data is read through title memory, not the input assembler.
        for (const Subobject& s : subobjects) {
            if (s.type != D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_INPUT_LAYOUT) continue;
            const D3D12_INPUT_LAYOUT_DESC none{nullptr, 0};
            std::memcpy(copy + s.payload, &none, sizeof(none));
        }
        info = g.info;
    }
    const D3D12_PIPELINE_STATE_STREAM_DESC patched{desc->SizeInBytes, copy};
    ComPtr<ID3D12PipelineState> state;
    const HRESULT hr = device->CreatePipelineState(&patched, IID_PPV_ARGS(&state));
    if (FAILED(hr)) {
        char detail[160];
        std::snprintf(detail, sizeof(detail), "desktop CreatePipelineState of the translated stream -> 0x%08lx",
                      static_cast<unsigned long>(hr));
        log_refused(create_stream, detail, false);
        return hr;
    }
    state->SetPrivateData(pso_info_guid, sizeof(info), &info);
    return state->QueryInterface(riid, out);
}

bool compute_pso_info(ID3D12PipelineState* state, PsoInfo* info)
{
    UINT size = sizeof(*info);
    return state && SUCCEEDED(state->GetPrivateData(pso_info_guid, &size, info)) && size == sizeof(*info) &&
           info->magic == compute_pso_magic;
}

void prestart_translator()
{
    // Off the device-creation path: the configuration hashes the converter's sources.
    TrySubmitThreadpoolCallback(
        [](PTP_CALLBACK_INSTANCE, void*) {
            const Config* c = config();
            // Only where the converter is installed: a desktop program on the shim without one starts nothing.
            if (c && c->mode == Mode::service &&
                GetFileAttributesW((c->tools + L"\\pso_service.py").c_str()) != INVALID_FILE_ATTRIBUTES) {
                translator::prestart();
            }
        },
        nullptr, nullptr);
}

// --- title memory and descriptors at draw time ------------------------------------------------------------------

using GetShaderViewFn = std::int32_t (*)(X2WTitleGpuRange*, void**, std::uint32_t, std::uint32_t*);
using TranslateFn = std::uint64_t (*)(std::uint64_t, std::uint64_t);

TranslateFn xmem_translate()
{
    HMODULE xmem = GetModuleHandleW(L"xmem.dll");
    return xmem ? reinterpret_cast<TranslateFn>(reinterpret_cast<void*>(GetProcAddress(xmem, "X2WTitleGpuTranslate")))
                : nullptr;
}

std::uint64_t translate_address(std::uint64_t address, std::uint64_t bytes)
{
    if (!address) return 0;
    const TranslateFn translate = xmem_translate();
    const std::uint64_t desktop = translate ? translate(address, bytes ? bytes : 4) : 0;
    return desktop ? desktop : address;
}

namespace {

// The TitleLookup miss counter of the live device (its mapped word), and the counts of devices already destroyed.
std::atomic<volatile std::uint32_t*> g_title_misses;
std::atomic<std::uint64_t> g_title_misses_before;

// The identity of the descriptors a block holds: (heap serial, index, generation) per entry; zero for a null entry.
template <unsigned N>
using BlockKey = std::array<std::uint32_t, 3 * N>;

}  // namespace

std::uint64_t title_lookup_misses()
{
    const volatile std::uint32_t* live = g_title_misses.load();
    return g_title_misses_before.load() + (live ? *live : 0);
}

class TitleViews {
public:
    explicit TitleViews(ID3D12Device* device) : device_(device) { InitializeSRWLock(&lock_); }
    ~TitleViews()
    {
        if (counter_word_) {
            volatile std::uint32_t* expected = counter_word_;
            if (g_title_misses.compare_exchange_strong(expected, nullptr)) g_title_misses_before += *counter_word_;
        }
    }

    // The shim's heaps, the table of title-memory SRVs and the miss counter, and the ranges buffer for the current
    // xmem.dll view.
    bool current(D3D12_GPU_DESCRIPTOR_HANDLE* table, D3D12_GPU_VIRTUAL_ADDRESS* ranges, UINT* count, BlockUse* use,
                 std::string& why)
    {
        AcquireSRWLockExclusive(&lock_);
        const bool good = ensure(why) && refresh(why);
        if (good) {
            hold(use, kind_view, block_);
            *table = views_gpu(block_ * memory_block);
            *ranges = ranges_all_->GetGPUVirtualAddress() + static_cast<UINT64>(block_) * ranges_slice;
            *count = static_cast<UINT>(last_.size());
        }
        ReleaseSRWLockExclusive(&lock_);
        return good;
    }
    ID3D12DescriptorHeap* view_heap() const { return heap_.Get(); }
    ID3D12DescriptorHeap* sampler_heap() const { return samplers_.Get(); }
    D3D12_GPU_VIRTUAL_ADDRESS zero_buffer() const { return zero_->GetGPUVirtualAddress(); }

    // A texture-table block holding `sources` (a null handle for a null SRV), and one for samplers (a null handle for
    // a point sampler). Blocks are cached by the identity of their descriptors, so a draw never changes a block an
    // earlier draw reads.
    bool texture_block(const BlockKey<texture_table>& key, const D3D12_CPU_DESCRIPTOR_HANDLE (&sources)[texture_table],
                       D3D12_GPU_DESCRIPTOR_HANDLE* out, BlockUse* use, std::string& why)
    {
        AcquireSRWLockExclusive(&lock_);
        bool good = true;
        auto it = texture_blocks_.find(key);
        if (it == texture_blocks_.end()) {
            const int found = texture_next_ < texture_block_count ? static_cast<int>(texture_next_++)
                                                                   : free_block(kind_texture, texture_block_count, ~0u);
            if (found < 0) {
                why = "all 4096 texture-table blocks are held by recorded lists or unfinished GPU work";
                good = false;
            } else {
                const UINT block = static_cast<UINT>(found);
                if (texture_keys_.size() <= block) texture_keys_.resize(block + 1);
                if (texture_keys_[block].second) texture_blocks_.erase(texture_keys_[block].first);
                const UINT first = texture_first + block * texture_table;
                for (UINT i = 0; i < texture_table; ++i) {
                    if (sources[i].ptr) {
                        device_->CopyDescriptorsSimple(1, views_cpu(first + i), sources[i],
                                                       D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
                    } else {
                        D3D12_SHADER_RESOURCE_VIEW_DESC null{};
                        null.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
                        null.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
                        null.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
                        null.Texture2D.MipLevels = 1;
                        device_->CreateShaderResourceView(nullptr, &null, views_cpu(first + i));
                    }
                }
                it = texture_blocks_.emplace(key, block).first;
                texture_keys_[block] = {key, true};
            }
        }
        if (good) {
            hold(use, kind_texture, it->second);
            *out = views_gpu(texture_first + it->second * texture_table);
        }
        ReleaseSRWLockExclusive(&lock_);
        return good;
    }

    bool sampler_block(const BlockKey<sampler_table>& key, const D3D12_CPU_DESCRIPTOR_HANDLE (&sources)[sampler_table],
                       D3D12_GPU_DESCRIPTOR_HANDLE* out, BlockUse* use, std::string& why)
    {
        AcquireSRWLockExclusive(&lock_);
        bool good = true;
        auto it = sampler_blocks_.find(key);
        if (it == sampler_blocks_.end()) {
            const int found = sampler_next_ < sampler_block_count ? static_cast<int>(sampler_next_++)
                                                                   : free_block(kind_sampler, sampler_block_count, ~0u);
            if (found < 0) {
                why = "all 512 sampler-table blocks are held by recorded lists or unfinished GPU work";
                good = false;
            } else {
                const UINT block = static_cast<UINT>(found);
                if (sampler_keys_.size() <= block) sampler_keys_.resize(block + 1);
                if (sampler_keys_[block].second) sampler_blocks_.erase(sampler_keys_[block].first);
                for (UINT i = 0; i < sampler_table; ++i) {
                    D3D12_CPU_DESCRIPTOR_HANDLE dst = samplers_->GetCPUDescriptorHandleForHeapStart();
                    dst.ptr += static_cast<SIZE_T>(block * sampler_table + i) * sampler_increment_;
                    if (sources[i].ptr) {
                        device_->CopyDescriptorsSimple(1, dst, sources[i], D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER);
                    } else {
                        D3D12_SAMPLER_DESC point{};
                        point.Filter = D3D12_FILTER_MIN_MAG_MIP_POINT;
                        point.AddressU = point.AddressV = point.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
                        point.MaxLOD = D3D12_FLOAT32_MAX;
                        device_->CreateSampler(&point, dst);
                    }
                }
                it = sampler_blocks_.emplace(key, block).first;
                sampler_keys_[block] = {key, true};
            }
        }
        if (good) {
            hold(use, kind_sampler, it->second);
            *out = samplers_->GetGPUDescriptorHandleForHeapStart();
            out->ptr += static_cast<UINT64>(it->second * sampler_table) * sampler_increment_;
        }
        ReleaseSRWLockExclusive(&lock_);
        return good;
    }

    // Block recycling (R5). A list holds every block a draw or dispatch it recorded reads until it is reset or
    // destroyed; each submission stamps the blocks of its lists with the next value of a fence the shim signals on
    // that queue right after it. A block is reused only when no list holds it and every stamp has completed.
    void release(BlockUse& use)
    {
        AcquireSRWLockExclusive(&lock_);
        for (std::uint32_t code : use.blocks) {
            BlockState& b = state(code >> 24, code & 0xffffff);
            if (b.holders) --b.holders;
        }
        use.blocks.clear();
        ReleaseSRWLockExclusive(&lock_);
    }
    void submitted(ID3D12CommandQueue* queue, BlockUse* const* uses, UINT count)
    {
        AcquireSRWLockExclusive(&lock_);
        UINT slot = 0;
        while (slot < queue_count_ && queue_ids_[slot] != queue) ++slot;
        if (slot == queue_count_ && queue_count_ < max_queues &&
            SUCCEEDED(device_->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fences_[slot])))) {
            queue_ids_[slot] = queue;
            ++queue_count_;
        }
        if (slot < queue_count_) {
            const std::uint64_t value = ++fence_values_[slot];
            for (UINT i = 0; i < count; ++i)
                for (std::uint32_t code : uses[i]->blocks) state(code >> 24, code & 0xffffff).stamp[slot] = value;
            queue->Signal(fences_[slot].Get(), value);
        } else {
            // More queues than the shim tracks: their blocks stay held for the device's lifetime.
            for (UINT i = 0; i < count; ++i)
                for (std::uint32_t code : uses[i]->blocks) ++state(code >> 24, code & 0xffffff).holders;
            if (!queue_overflow_noted_) {
                queue_overflow_noted_ = true;
                log_note("d3d12_xs!ID3D12CommandQueue::ExecuteCommandLists",
                         "more than 16 queues submit translated work; their descriptor blocks are not recycled", nullptr);
            }
        }
        ReleaseSRWLockExclusive(&lock_);
    }

    // Whether a miss at (serial, index) is the first of its kind on this device (it is logged then).
    bool first_miss(std::uint32_t serial, std::uint32_t index, RefKind kind)
    {
        AcquireSRWLockExclusive(&lock_);
        const std::uint64_t key = std::uint64_t(serial) << 34 | std::uint64_t(index) << 2 | static_cast<unsigned>(kind);
        bool first = false;
        if (misses_logged_.size() < 64 && misses_logged_.emplace(key, 0).second) first = true;
        ReleaseSRWLockExclusive(&lock_);
        return first;
    }

private:
    static constexpr UINT blocks = 256;  // title-memory views
    static constexpr UINT texture_block_count = 4096;
    static constexpr UINT sampler_block_count = 512;  // 2048 samplers, the desktop limit of a shader-visible heap
    static constexpr UINT texture_first = blocks * memory_block;
    static constexpr UINT max_queues = 16;
    enum : UINT { kind_view = 0, kind_texture = 1, kind_sampler = 2 };
    struct BlockState {
        std::uint32_t holders = 0;
        std::uint64_t stamp[max_queues] = {};
    };
    BlockState& state(UINT kind, UINT index)
    {
        std::vector<BlockState>& all = states_[kind];
        if (all.size() <= index) all.resize(index + 1);
        return all[index];
    }
    void hold(BlockUse* use, UINT kind, UINT index)
    {
        if (!use) return;
        const std::uint32_t code = kind << 24 | index;
        for (std::uint32_t held : use->blocks)
            if (held == code) return;
        use->blocks.push_back(code);
        ++state(kind, index).holders;
    }
    // A block of `kind` below `limit` that no list holds and no unfinished submission reads, other than `except`;
    // -1 when there is none.
    int free_block(UINT kind, UINT limit, UINT except)
    {
        std::uint64_t completed[max_queues];
        for (UINT q = 0; q < queue_count_; ++q) completed[q] = fences_[q]->GetCompletedValue();
        for (UINT n = 0; n < limit; ++n) {
            // Start after the last block handed out, so recently used blocks are reused last.
            const UINT index = (cursor_[kind] + 1 + n) % limit;
            if (index == except) continue;
            const BlockState& b = state(kind, index);
            bool done = b.holders == 0;
            for (UINT q = 0; done && q < queue_count_; ++q) done = b.stamp[q] <= completed[q];
            if (done) {
                cursor_[kind] = index;
                return static_cast<int>(index);
            }
        }
        return -1;
    }

    D3D12_CPU_DESCRIPTOR_HANDLE views_cpu(UINT index) const
    {
        D3D12_CPU_DESCRIPTOR_HANDLE h = heap_->GetCPUDescriptorHandleForHeapStart();
        h.ptr += static_cast<SIZE_T>(index) * increment_;
        return h;
    }
    D3D12_GPU_DESCRIPTOR_HANDLE views_gpu(UINT index) const
    {
        D3D12_GPU_DESCRIPTOR_HANDLE h = heap_->GetGPUDescriptorHandleForHeapStart();
        h.ptr += static_cast<UINT64>(index) * increment_;
        return h;
    }

    // The shim's shader-visible heaps, the TitleLookup miss counter and the zero buffer, created on first use.
    bool ensure(std::string& why)
    {
        if (heap_) return true;
        D3D12_DESCRIPTOR_HEAP_DESC desc{};
        desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        desc.NumDescriptors = texture_first + texture_block_count * texture_table;
        desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        D3D12_DESCRIPTOR_HEAP_DESC sampler_desc{};
        sampler_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER;
        sampler_desc.NumDescriptors = sampler_block_count * sampler_table;
        sampler_desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        // The miss counter: a CPU-readable buffer the shaders count into (write-back system memory, as the title
        // memory aliases are), and a zero-filled upload buffer for constant buffers whose view is missing.
        D3D12_HEAP_PROPERTIES counter_heap{};
        counter_heap.Type = D3D12_HEAP_TYPE_CUSTOM;
        counter_heap.CPUPageProperty = D3D12_CPU_PAGE_PROPERTY_WRITE_BACK;
        counter_heap.MemoryPoolPreference = D3D12_MEMORY_POOL_L0;
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = 256;
        buffer.Height = 1;
        buffer.DepthOrArraySize = 1;
        buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1;
        buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        buffer.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_RESOURCE_DESC zero = buffer;
        zero.Width = 65536;
        zero.Flags = D3D12_RESOURCE_FLAG_NONE;
        D3D12_HEAP_PROPERTIES upload{};
        upload.Type = D3D12_HEAP_TYPE_UPLOAD;
        void* mapped = nullptr;
        if (FAILED(device_->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&heap_))) ||
            FAILED(device_->CreateDescriptorHeap(&sampler_desc, IID_PPV_ARGS(&samplers_))) ||
            FAILED(device_->CreateCommittedResource(&counter_heap, D3D12_HEAP_FLAG_NONE, &buffer,
                                                    D3D12_RESOURCE_STATE_UNORDERED_ACCESS, nullptr,
                                                    IID_PPV_ARGS(&counter_))) ||
            FAILED(counter_->Map(0, nullptr, &mapped)) ||
            FAILED(device_->CreateCommittedResource(&upload, D3D12_HEAP_FLAG_NONE, &zero,
                                                    D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&zero_)))) {
            heap_.Reset();
            samplers_.Reset();
            counter_.Reset();
            zero_.Reset();
            why = "cannot create the shim's descriptor heaps or counter buffers";
            return false;
        }
        std::memset(mapped, 0, 256);
        counter_word_ = static_cast<volatile std::uint32_t*>(mapped);
        volatile std::uint32_t* expected = nullptr;
        g_title_misses.compare_exchange_strong(expected, counter_word_);
        void* zeros = nullptr;
        if (SUCCEEDED(zero_->Map(0, nullptr, &zeros))) {
            std::memset(zeros, 0, 65536);
            zero_->Unmap(0, nullptr);
        }
        increment_ = device_->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        sampler_increment_ = device_->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER);
        block_ = blocks - 1;
        return true;
    }

    bool refresh(std::string& why)
    {
        std::vector<X2WTitleGpuRange> ranges;
        std::vector<void*> resources;
        HMODULE xmem = GetModuleHandleW(L"xmem.dll");
        auto view = xmem ? reinterpret_cast<GetShaderViewFn>(
                               reinterpret_cast<void*>(GetProcAddress(xmem, "X2WTitleGpuGetShaderView")))
                         : nullptr;
        if (view) {
            std::uint32_t required = 0;
            std::int32_t hr = view(nullptr, nullptr, 0, &required);
            if (required) {
                ranges.resize(required);
                resources.resize(required);
                hr = view(ranges.data(), resources.data(), required, &required);
                if (FAILED(hr) || required != ranges.size()) {
                    for (void* r : resources)
                        if (r) static_cast<IUnknown*>(r)->Release();
                    why = "X2WTitleGpuGetShaderView failed";
                    return false;
                }
            } else if (hr != 0 && hr != static_cast<std::int32_t>(HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER))) {
                why = "X2WTitleGpuGetShaderView failed";
                return false;
            }
        }
        const auto release = [&]() {
            for (void* r : resources)
                if (r) static_cast<IUnknown*>(r)->Release();
        };
        if (ranges.size() > title_memory_slots) {
            release();
            why = "more than 8 title memory ranges; the converter's title_memory table has 8 slots";
            return false;
        }
        if (have_view_ && ranges.size() == last_.size() && resources == last_resources_ &&
            (ranges.empty() || std::memcmp(ranges.data(), last_.data(), ranges.size() * sizeof(ranges[0])) == 0)) {
            release();
            return true;
        }
        // A new block per view, so descriptors that recorded draws still read stay unchanged: a block is written
        // again only when no list holds it and the GPU has finished every submission that read it.
        const int next = have_view_ ? free_block(kind_view, blocks, block_) : 0;
        if (next < 0) {
            release();
            why = "all 256 title-memory view blocks are held by recorded lists or unfinished GPU work";
            return false;
        }
        block_ = static_cast<UINT>(next);
        D3D12_CPU_DESCRIPTOR_HANDLE handle = views_cpu(block_ * memory_block);
        D3D12_CPU_DESCRIPTOR_HANDLE uav_handle = views_cpu(block_ * memory_block + title_memory_slots + 1);
        for (UINT i = 0; i < title_memory_slots; ++i) {
            D3D12_SHADER_RESOURCE_VIEW_DESC raw{};
            raw.Format = DXGI_FORMAT_R32_TYPELESS;
            raw.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
            raw.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            raw.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
            ID3D12Resource* resource = nullptr;
            raw.Buffer.NumElements = 1;
            for (std::size_t r = 0; r < ranges.size(); ++r) {
                if (ranges[r].slot != i) continue;
                const std::uint64_t begin = std::uint64_t(ranges[r].begin_high) << 32 | ranges[r].begin_low;
                const std::uint64_t end = std::uint64_t(ranges[r].end_high) << 32 | ranges[r].end_low;
                resource = static_cast<ID3D12Resource*>(resources[r]);
                raw.Buffer.NumElements = static_cast<UINT>((end - begin) / 4);
            }
            device_->CreateShaderResourceView(resource, &raw, handle);
            handle.ptr += increment_;
            D3D12_UNORDERED_ACCESS_VIEW_DESC raw_uav{};
            raw_uav.Format = DXGI_FORMAT_R32_TYPELESS;
            raw_uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
            raw_uav.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
            raw_uav.Buffer.NumElements = raw.Buffer.NumElements;
            // A buffer the title created without UAV access (an UPLOAD buffer, d3d12_xs_resources.h) gets a null UAV:
            // translated shaders read it through the SRV, and a store to it writes nothing, as desktop D3D12 allows
            // no UAV on it.
            ID3D12Resource* writable = resource;
            if (resource) {
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
                D3D12_RESOURCE_DESC rd{};
                resource->GetDesc(&rd);
#else
                const D3D12_RESOURCE_DESC rd = resource->GetDesc();
#endif
                if (!(rd.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS)) writable = nullptr;
            }
            device_->CreateUnorderedAccessView(writable, nullptr, &raw_uav, uav_handle);
            uav_handle.ptr += increment_;
        }
        D3D12_UNORDERED_ACCESS_VIEW_DESC misses{};
        misses.Format = DXGI_FORMAT_R32_TYPELESS;
        misses.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        misses.Buffer.NumElements = 64;
        misses.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
        device_->CreateUnorderedAccessView(counter_.Get(), nullptr, &misses, handle);
        // The ranges as TitleLookup reads them (stride 24): one 256-byte slice per view block of a persistently
        // mapped upload buffer, rewritten only with its block (see free_block).
        if (!ranges_all_) {
            D3D12_HEAP_PROPERTIES upload{};
            upload.Type = D3D12_HEAP_TYPE_UPLOAD;
            D3D12_RESOURCE_DESC desc{};
            desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
            desc.Width = static_cast<UINT64>(blocks) * ranges_slice;
            desc.Height = 1;
            desc.DepthOrArraySize = 1;
            desc.MipLevels = 1;
            desc.SampleDesc.Count = 1;
            desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            void* mapped = nullptr;
            if (FAILED(device_->CreateCommittedResource(&upload, D3D12_HEAP_FLAG_NONE, &desc,
                                                        D3D12_RESOURCE_STATE_GENERIC_READ, nullptr,
                                                        IID_PPV_ARGS(&ranges_all_))) ||
                FAILED(ranges_all_->Map(0, nullptr, &mapped))) {
                ranges_all_.Reset();
                release();
                why = "cannot create the title ranges buffer";
                return false;
            }
            ranges_mapped_ = static_cast<std::uint8_t*>(mapped);
        }
        static_assert(title_memory_slots * sizeof(X2WTitleGpuRange) <= ranges_slice, "ranges slice too small");
        std::uint8_t* slice = ranges_mapped_ + static_cast<std::size_t>(block_) * ranges_slice;
        std::memset(slice, 0, ranges_slice);
        if (!ranges.empty()) std::memcpy(slice, ranges.data(), ranges.size() * sizeof(ranges[0]));
        have_view_ = true;
        release();
        last_ = ranges;
        last_resources_ = resources;
        return true;
    }

    ID3D12Device* device_;  // the desktop device; the owning wrapper outlives this object
    SRWLOCK lock_;
    ComPtr<ID3D12DescriptorHeap> heap_, samplers_;
    ComPtr<ID3D12Resource> counter_, zero_;
    volatile std::uint32_t* counter_word_ = nullptr;
    UINT increment_ = 0, sampler_increment_ = 0;
    UINT block_ = 0;
    bool have_view_ = false;
    static constexpr UINT ranges_slice = 256;
    ComPtr<ID3D12Resource> ranges_all_;  // the ranges of every title-memory view block, one slice each
    std::uint8_t* ranges_mapped_ = nullptr;
    std::vector<BlockState> states_[3];
    UINT cursor_[3] = {};
    UINT texture_next_ = 0, sampler_next_ = 0;  // blocks never handed out start here
    std::vector<std::pair<BlockKey<texture_table>, bool>> texture_keys_;  // the key each block holds, if any
    std::vector<std::pair<BlockKey<sampler_table>, bool>> sampler_keys_;
    ComPtr<ID3D12Fence> fences_[max_queues];
    std::uint64_t fence_values_[max_queues] = {};
    const void* queue_ids_[max_queues] = {};
    UINT queue_count_ = 0;
    bool queue_overflow_noted_ = false;
    std::vector<X2WTitleGpuRange> last_;
    std::vector<void*> last_resources_;  // identity only; not referenced
    std::map<BlockKey<texture_table>, UINT> texture_blocks_;
    std::map<BlockKey<sampler_table>, UINT> sampler_blocks_;
    std::map<std::uint64_t, int> misses_logged_;
};

TitleViews* create_title_views(ID3D12Device* device) { return new (std::nothrow) TitleViews(device); }
void release_blocks(TitleViews* views, BlockUse& use)
{
    if (views && !use.blocks.empty()) views->release(use);
}
void submitted_blocks(TitleViews* views, ID3D12CommandQueue* queue, BlockUse* const* uses, unsigned count)
{
    bool any = false;
    for (unsigned i = 0; i < count; ++i) any = any || !uses[i]->blocks.empty();
    if (views && any) views->submitted(queue, uses, count);
}
void destroy_title_views(TitleViews* views) { delete views; }

void set_placeholders(ID3D12GraphicsCommandList* list, const RootInfo& root)
{
    for (UINT i = 0; i < root.title_params; ++i)
        if (root.types[i] == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE) list->SetGraphicsRoot32BitConstant(i, 0, 0);
}

bool bind_for_draw(TitleViews* views, ID3D12GraphicsCommandList* list, const RootInfo& root, const PsoInfo& pso,
                   const RootArgs& args, const BoundHeaps& heaps, DrawBases bases, bool* ours_bound, BlockUse* use)
{
    const char* symbol = "d3d12_xs!ID3D12GraphicsCommandList::Draw";
    std::string why;
    D3D12_GPU_DESCRIPTOR_HANDLE table{};
    D3D12_GPU_VIRTUAL_ADDRESS ranges = 0;
    UINT count = 0;
    if (heaps.foreign) {
        log_refused(symbol,
                    "draw skipped: the title bound a shader-visible heap the shim did not create; translated shaders "
                    "read descriptors from title heaps only",
                    true);
        return false;
    }
    if (!views || !views->current(&table, &ranges, &count, use, why)) {
        log_refused(symbol, ("draw skipped: " + (why.empty() ? std::string("no title memory view") : why)).c_str(), true);
        return false;
    }

    // TextureLookup: each descriptor the shaders read from a title table, resolved to the slot of its heap.
    BlockKey<texture_table> texture_key{};
    BlockKey<sampler_table> sampler_key{};
    D3D12_CPU_DESCRIPTOR_HANDLE texture_src[texture_table] = {};
    D3D12_CPU_DESCRIPTOR_HANDLE sampler_src[sampler_table] = {};
    bool any_texture = false, any_sampler = false;
    D3D12_GPU_VIRTUAL_ADDRESS constants[1 + pixel_constant_slots] = {};
    bool any_constants[1 + pixel_constant_slots] = {};
    for (std::uint32_t r = 0; r < pso.ref_count; ++r) {
        const TableRef& ref = pso.refs[r];
        const descriptors::SlotKind want = ref.kind == RefKind::texture   ? descriptors::SlotKind::srv
                                           : ref.kind == RefKind::sampler ? descriptors::SlotKind::sampler
                                                                          : descriptors::SlotKind::cbv;
        const descriptors::Resolved found = descriptors::resolve(
            args.address[ref.parameter], ref.offset, want, ref.kind == RefKind::sampler ? heaps.samplers : heaps.views);
        if (!found.found) {
            count_texture_miss();
            if (views->first_miss(found.serial, found.index, ref.kind)) {
                char detail[320];
                std::snprintf(detail, sizeof(detail),
                              "TextureLookup miss: %s %s slot %u reads root parameter %u + %u (heap %u, descriptor "
                              "%u): %s; it reads %s",
                              ref.stage == X2W_SHADER_STAGE_VERTEX ? "vertex" : "pixel",
                              ref.kind == RefKind::texture   ? "texture"
                              : ref.kind == RefKind::sampler ? "sampler"
                                                             : "constant buffer",
                              ref.slot, ref.parameter, ref.offset, found.serial, found.index, found.why,
                              ref.kind == RefKind::texture   ? "a null SRV"
                              : ref.kind == RefKind::sampler ? "through a point sampler"
                                                             : "zeros");
                log_note(symbol, detail, nullptr);
            }
        }
        const std::uint32_t identity[3] = {found.found ? found.serial : 0, found.found ? found.index : 0,
                                           found.found ? found.generation : 0};
        if (ref.kind == RefKind::texture) {
            const UINT at = ref.slot < 2 ? ref.slot : ref.slot + 1u;  // the converter's texture registers skip t2
            texture_src[at] = found.found ? found.shadow : D3D12_CPU_DESCRIPTOR_HANDLE{};
            std::memcpy(&texture_key[3 * at], identity, sizeof(identity));
            any_texture = true;
        } else if (ref.kind == RefKind::sampler) {
            sampler_src[ref.slot] = found.found ? found.shadow : D3D12_CPU_DESCRIPTOR_HANDLE{};
            std::memcpy(&sampler_key[3 * ref.slot], identity, sizeof(identity));
            any_sampler = true;
        } else {
            const unsigned at = ref.stage == X2W_SHADER_STAGE_VERTEX ? 0 : 1 + ref.slot;
            constants[at] = found.found ? translate_address(found.cbv_address, 256) : views->zero_buffer();
            any_constants[at] = true;
        }
    }
    D3D12_GPU_DESCRIPTOR_HANDLE texture_table_at{}, sampler_table_at{};
    if ((any_texture && !views->texture_block(texture_key, texture_src, &texture_table_at, use, why)) ||
        (any_sampler && !views->sampler_block(sampler_key, sampler_src, &sampler_table_at, use, why))) {
        log_refused(symbol, ("draw skipped: " + why).c_str(), true);
        return false;
    }

    if (!*ours_bound) {
        ID3D12DescriptorHeap* ours[2] = {views->view_heap(), views->sampler_heap()};
        list->SetDescriptorHeaps(2, ours);
        *ours_bound = true;
    }
    set_placeholders(list, root);
    std::uint32_t words[push_word_count] = {};
    for (std::uint32_t i = 0; i < pso.push_count; ++i) {
        const PushSource s = pso.push[i];
        const auto type = static_cast<D3D12_ROOT_PARAMETER_TYPE>(root.types[s.parameter]);
        words[i] = type == D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS
                       ? args.constants[s.parameter][s.word]
                       : static_cast<std::uint32_t>(args.address[s.parameter] >> (32 * s.word));
    }
    const UINT base = root.title_params;
    list->SetGraphicsRoot32BitConstant(base + param_range_count, count, 0);
    list->SetGraphicsRootShaderResourceView(base + param_ranges, ranges);
    list->SetGraphicsRootDescriptorTable(base + param_memory, table);
    list->SetGraphicsRoot32BitConstants(base + param_push_words, push_word_count, words, 0);
    list->SetGraphicsRoot32BitConstants(base + param_vertex_root, 2, &bases, 0);
    if (any_constants[0]) list->SetGraphicsRootConstantBufferView(base + param_vertex_constants, constants[0]);
    for (UINT k = 0; k < pixel_constant_slots; ++k)
        if (any_constants[1 + k]) list->SetGraphicsRootConstantBufferView(base + param_pixel_constants + k, constants[1 + k]);
    if (any_texture) list->SetGraphicsRootDescriptorTable(base + param_textures, texture_table_at);
    if (any_sampler) list->SetGraphicsRootDescriptorTable(base + param_samplers, sampler_table_at);
    return true;
}

void set_compute_placeholders(ID3D12GraphicsCommandList* list, const RootInfo& root)
{
    for (UINT i = 0; i < root.title_params; ++i)
        if (root.types[i] == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE) list->SetComputeRoot32BitConstant(i, 0, 0);
}

// The compute counterpart of bind_for_draw (R5): title memory, its ranges and the push words through the compute
// root arguments. A translated compute pipeline reads no descriptor table (create_compute_pipeline refuses one).
bool bind_for_dispatch(TitleViews* views, ID3D12GraphicsCommandList* list, const RootInfo& root, const PsoInfo& pso,
                       const RootArgs& args, const BoundHeaps& heaps, bool* ours_bound, BlockUse* use)
{
    const char* symbol = "d3d12_xs!ID3D12GraphicsCommandList::Dispatch";
    std::string why;
    D3D12_GPU_DESCRIPTOR_HANDLE table{};
    D3D12_GPU_VIRTUAL_ADDRESS ranges = 0;
    UINT count = 0;
    if (heaps.foreign) {
        log_refused(symbol,
                    "dispatch skipped: the title bound a shader-visible heap the shim did not create; translated "
                    "shaders read descriptors from title heaps only",
                    true);
        return false;
    }
    if (!views || !views->current(&table, &ranges, &count, use, why)) {
        log_refused(symbol, ("dispatch skipped: " + (why.empty() ? std::string("no title memory view") : why)).c_str(),
                    true);
        return false;
    }
    if (!*ours_bound) {
        ID3D12DescriptorHeap* ours[2] = {views->view_heap(), views->sampler_heap()};
        list->SetDescriptorHeaps(2, ours);
        *ours_bound = true;
    }
    set_compute_placeholders(list, root);
    std::uint32_t words[push_word_count] = {};
    for (std::uint32_t i = 0; i < pso.push_count; ++i) {
        const PushSource s = pso.push[i];
        const auto type = static_cast<D3D12_ROOT_PARAMETER_TYPE>(root.types[s.parameter]);
        words[i] = type == D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS
                       ? args.constants[s.parameter][s.word]
                       : static_cast<std::uint32_t>(args.address[s.parameter] >> (32 * s.word));
    }
    const UINT base = root.title_params;
    list->SetComputeRoot32BitConstant(base + param_range_count, count, 0);
    list->SetComputeRootShaderResourceView(base + param_ranges, ranges);
    list->SetComputeRootDescriptorTable(base + param_memory, table);
    list->SetComputeRoot32BitConstants(base + param_push_words, push_word_count, words, 0);
    return true;
}

}  // namespace pipeline
}  // namespace d3d12_xs
