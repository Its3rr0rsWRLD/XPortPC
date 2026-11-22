// Pipeline translation, root signatures and draw-time bindings of the graphics shim (d3d12_xs_pipeline.h).
//
// Like the rest of the shim, nothing here has a dynamic initializer or thread-local storage: process-wide state is
// constant-initialized and filled once through INIT_ONCE, so the DLL keeps an empty TLS template.
#include "d3d12_xs_pipeline.h"
#include "d3d12_xs_api.h"
#include "d3d12_xs_wrap.h"
#include "era_title_gpu_api.h"

#include <wrl/client.h>

#include <cstdio>
#include <cstring>
#include <new>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace d3d12_xs {
namespace pipeline {
namespace {

constexpr std::uint32_t root_magic = 0x52573258u;  // "X2WR"
constexpr std::uint32_t pso_magic = 0x50573258u;   // "X2WP"
// {6b1a3c52-0f6e-4f0e-9a5d-58325752e001} and ...02: private-data keys of RootInfo and PsoInfo.
constexpr GUID root_info_guid = {0x6b1a3c52, 0x0f6e, 0x4f0e, {0x9a, 0x5d, 0x58, 0x32, 0x57, 0x52, 0xe0, 0x01}};
constexpr GUID pso_info_guid = {0x6b1a3c52, 0x0f6e, 0x4f0e, {0x9a, 0x5d, 0x58, 0x32, 0x57, 0x52, 0xe0, 0x02}};
constexpr UINT runtime_space = 1000;
constexpr UINT runtime_memory_space = 1001;
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

struct Config {
    std::wstring python, tools, dxc, llvm, cache;  // cache: the title's directory
    std::uint8_t fingerprint[32];
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
    for (std::wstring* path : {&config->python, &config->tools, &config->dxc, &config->llvm, &config->cache})
        for (wchar_t& ch : *path)
            if (ch == L'/') ch = L'\\';
    Sha256 sha;
    sha.update_text("x2w-pso-translate-1");
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
    if (header.version != X2W_SHADER_CONTAINER_VERSION || header.reserved ||
        header.stage > X2W_SHADER_STAGE_PIXEL || header.binding_count > 32 || binding_end > size ||
        header.code_offset % 4 || header.code_bytes % 4 || !header.code_bytes || code_end > size) {
        why = "malformed container header";
        return Parsed::malformed;
    }
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
    const std::wstring output = base + L".dxil";
    if (!write_file(code, program.code, program.code_bytes) || !write_file(roles_path, roles.data(), roles.size())) {
        why = "cannot write the translator's input files in the cache directory";
        return 2;
    }
    std::wstring command = L"\"" + c.python + L"\" -B \"" + c.tools + L"\\pso_translate.py\" --stage " +
                           widen(stage) + L" --code \"" + code + L"\" --roles \"" + roles_path + L"\" --dxc \"" +
                           c.dxc + L"\" --output \"" + output + L"\"";
    if (!c.llvm.empty()) command += L" --llvm \"" + c.llvm + L"\"";
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

const char* stage_name(std::uint32_t stage) { return stage == X2W_SHADER_STAGE_VERTEX ? "vertex" : "pixel"; }

// The DXIL of one console shader: from the cache, or translated and cached. Returns false with `why` set.
bool translated_shader(const Program& program, const std::string& roles, std::vector<std::uint8_t>& dxil,
                       std::string& key_text, std::string& why)
{
    const Config* c = config();
    if (!c) {
        why = "out of memory";
        return false;
    }
    Sha256 sha;
    sha.update(c->fingerprint, 32);
    sha.update_u32(program.stage);
    sha.update_text(roles);
    sha.update_u32(program.code_bytes);
    sha.update(program.code, program.code_bytes);
    std::uint8_t key[32];
    sha.finish(key);
    key_text = hex(key, 32);
    const std::wstring final_path = c->cache + L"\\" + widen(key_text) + L".dxil";
    if (read_file(final_path, dxil)) {
        count_shader(true);
        return true;
    }
    if (!make_directories(c->cache)) {
        why = "cannot create the cache directory " + narrow(c->cache);
        return false;
    }
    wchar_t unique[64];
    std::swprintf(unique, 64, L".%lu.%lu", GetCurrentProcessId(), GetCurrentThreadId());
    const std::wstring base = c->cache + L"\\" + widen(key_text) + unique;
    const int result = run_translator(*c, stage_name(program.stage), base, program, roles, why);
    const std::wstring produced = base + L".dxil";
    if (result != 0) {
        DeleteFileW(produced.c_str());
        if (result == 2) why = "translator failure: " + why;
        return false;
    }
    if (!MoveFileExW(produced.c_str(), final_path.c_str(), MOVEFILE_REPLACE_EXISTING) || !read_file(final_path, dxil)) {
        DeleteFileW(produced.c_str());
        why = "cannot store the translation in the cache";
        return false;
    }
    count_shader(false);
    return true;
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
    }
    D3D12_DESCRIPTOR_RANGE1 memory{};
    memory.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    memory.NumDescriptors = title_memory_slots;
    memory.BaseShaderRegister = 0;
    memory.RegisterSpace = runtime_memory_space;
    memory.Flags = D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE | D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE;
    memory.OffsetInDescriptorsFromTableStart = 0;
    D3D12_ROOT_PARAMETER1 extra[converter_params]{};
    extra[param_range_count].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    extra[param_range_count].Constants = {1, runtime_space, 1};
    extra[param_ranges].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
    extra[param_ranges].Descriptor = {2, runtime_space, D3D12_ROOT_DESCRIPTOR_FLAG_DATA_VOLATILE};
    extra[param_memory].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    extra[param_memory].DescriptorTable = {1, &memory};
    extra[param_push_words].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    extra[param_push_words].Constants = {3, runtime_space, push_word_count};
    for (auto& p : extra) {
        p.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        params.push_back(p);
    }
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

HRESULT create_graphics_pipeline(ID3D12Device* device, const D3D12_GRAPHICS_PIPELINE_STATE_DESC* desc, REFIID riid,
                                 void** out)
{
    if (!desc) return device->CreateGraphicsPipelineState(desc, riid, out);
    Program vs, ps;
    std::string why;
    const Parsed vs_kind = desc->VS.BytecodeLength ? parse_container(desc->VS.pShaderBytecode, desc->VS.BytecodeLength, vs, why)
                                                   : Parsed::desktop;
    if (vs_kind == Parsed::malformed) {
        refuse("vertex", "", why);
        return E_NOTIMPL;
    }
    const Parsed ps_kind = desc->PS.BytecodeLength ? parse_container(desc->PS.pShaderBytecode, desc->PS.BytecodeLength, ps, why)
                                                   : Parsed::desktop;
    if (ps_kind == Parsed::malformed) {
        refuse("pixel", "", why);
        return E_NOTIMPL;
    }
    if (vs_kind == Parsed::desktop && ps_kind == Parsed::desktop) return device->CreateGraphicsPipelineState(desc, riid, out);

    // A console pipeline: every present stage must be a console shader of the stage it is bound to.
    if (vs_kind != Parsed::container || (desc->PS.BytecodeLength && ps_kind != Parsed::container)) {
        refuse(vs_kind == Parsed::container ? "pixel" : "vertex", "",
               "desktop bytecode beside a console shader in one pipeline");
        return E_NOTIMPL;
    }
    if (desc->GS.BytecodeLength || desc->HS.BytecodeLength || desc->DS.BytecodeLength || desc->StreamOutput.NumEntries) {
        refuse("vertex", "", "geometry, tessellation or stream output with console shaders is not translated");
        return E_NOTIMPL;
    }
    if (vs.stage != X2W_SHADER_STAGE_VERTEX || (desc->PS.BytecodeLength && ps.stage != X2W_SHADER_STAGE_PIXEL)) {
        refuse("vertex", "", "a container's stage does not match the pipeline stage it is bound to");
        return E_NOTIMPL;
    }
    RootInfo root{};
    if (!root_info(desc->pRootSignature, &root)) {
        refuse("vertex", "", "the root signature was not created through the shim, so it has no converter parameters");
        return E_NOTIMPL;
    }

    // Entry contracts. Vertex: each root-word SGPR becomes the next push word. Pixel: the interpolation base only.
    PsoInfo info{};
    info.magic = pso_magic;
    std::string vs_roles = "{\"user_sgprs\": {", ps_roles = "{\"sgprs\": {";
    bool used[106] = {};
    for (const X2WShaderBinding& b : vs.bindings) {
        char entry[96];
        if (b.sgpr > 105 || used[b.sgpr]) {
            refuse("vertex", "", "an entry SGPR is out of range or bound twice");
            return E_NOTIMPL;
        }
        used[b.sgpr] = true;
        if (b.kind != X2W_SHADER_BINDING_ROOT_WORD) {
            refuse("vertex", "", "a vertex binding other than a root-parameter word");
            return E_NOTIMPL;
        }
        if (b.root_parameter >= root.title_params) {
            refuse("vertex", "", "a binding names a root parameter the root signature does not have");
            return E_NOTIMPL;
        }
        const auto type = static_cast<D3D12_ROOT_PARAMETER_TYPE>(root.types[b.root_parameter]);
        const bool address = type == D3D12_ROOT_PARAMETER_TYPE_CBV || type == D3D12_ROOT_PARAMETER_TYPE_SRV ||
                             type == D3D12_ROOT_PARAMETER_TYPE_UAV;
        if (type == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE ||
            (address ? b.word > 1 : b.word >= root.constants[b.root_parameter])) {
            refuse("vertex", "", type == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE
                                     ? "a binding reads a descriptor table parameter (descriptor heaps come with R4)"
                                     : "a binding reads past its root parameter");
            return E_NOTIMPL;
        }
        if (info.push_count == push_word_count) {
            refuse("vertex", "", "more than 32 root-word bindings");
            return E_NOTIMPL;
        }
        std::snprintf(entry, sizeof(entry), "%s\"%u\": {\"role\": \"inline\", \"word\": %u}", info.push_count ? ", " : "",
                      b.sgpr, info.push_count);
        vs_roles += entry;
        info.push[info.push_count++] = {static_cast<std::uint8_t>(b.root_parameter), static_cast<std::uint8_t>(b.word)};
    }
    vs_roles += "}}";
    bool first = true;
    for (const X2WShaderBinding& b : ps.bindings) {
        if (b.kind != X2W_SHADER_BINDING_INTERP || b.sgpr > 105) {
            refuse("pixel", "", "pixel bindings other than the interpolation base are not bound by the runtime yet");
            return E_NOTIMPL;
        }
        char entry[48];
        std::snprintf(entry, sizeof(entry), "%s\"s%u\": \"interp\"", first ? "" : ", ", b.sgpr);
        ps_roles += entry;
        first = false;
    }
    ps_roles += "}}";

    std::vector<std::uint8_t> vs_dxil, ps_dxil;
    std::string key;
    if (!translated_shader(vs, vs_roles, vs_dxil, key, why)) {
        refuse("vertex", key, why);
        return E_NOTIMPL;
    }
    if (desc->PS.BytecodeLength && !translated_shader(ps, ps_roles, ps_dxil, key, why)) {
        refuse("pixel", key, why);
        return E_NOTIMPL;
    }
    D3D12_GRAPHICS_PIPELINE_STATE_DESC copy = *desc;
    copy.VS = {vs_dxil.data(), vs_dxil.size()};
    if (desc->PS.BytecodeLength) copy.PS = {ps_dxil.data(), ps_dxil.size()};
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
    state->SetPrivateData(pso_info_guid, sizeof(info), &info);
    return state->QueryInterface(riid, out);
}

HRESULT create_compute_pipeline(ID3D12Device* device, const D3D12_COMPUTE_PIPELINE_STATE_DESC* desc, REFIID riid,
                                void** out)
{
    Program cs;
    std::string why;
    if (desc && desc->CS.BytecodeLength &&
        parse_container(desc->CS.pShaderBytecode, desc->CS.BytecodeLength, cs, why) != Parsed::desktop) {
        if (why.empty()) why = "console compute shaders are translated from rung R5";
        log_refused("d3d12_xs!ID3D12Device::CreateComputePipelineState", ("compute shader refused: " + why).c_str(),
                    false);
        return E_NOTIMPL;
    }
    return device->CreateComputePipelineState(desc, riid, out);
}

// --- title memory at draw time ----------------------------------------------------------------------------------

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

class TitleViews {
public:
    explicit TitleViews(ID3D12Device* device) : device_(device) { InitializeSRWLock(&lock_); }

    // The shim's heap, the table of title-memory SRVs and the ranges buffer for the current xmem.dll view.
    bool current(ID3D12DescriptorHeap** heap, D3D12_GPU_DESCRIPTOR_HANDLE* table, D3D12_GPU_VIRTUAL_ADDRESS* ranges,
                 UINT* count, std::string& why)
    {
        AcquireSRWLockExclusive(&lock_);
        const bool good = refresh(why);
        if (good) {
            *heap = heap_.Get();
            *table = heap_->GetGPUDescriptorHandleForHeapStart();
            table->ptr += static_cast<UINT64>(block_) * title_memory_slots * increment_;
            *ranges = ranges_.back()->GetGPUVirtualAddress();
            *count = static_cast<UINT>(last_.size());
        }
        ReleaseSRWLockExclusive(&lock_);
        return good;
    }

private:
    static constexpr UINT blocks = 256;

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
        if (heap_ && ranges.size() == last_.size() && resources == last_resources_ &&
            (ranges.empty() || std::memcmp(ranges.data(), last_.data(), ranges.size() * sizeof(ranges[0])) == 0)) {
            release();
            return true;
        }
        if (!heap_) {
            D3D12_DESCRIPTOR_HEAP_DESC desc{};
            desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
            desc.NumDescriptors = blocks * title_memory_slots;
            desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
            if (FAILED(device_->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&heap_)))) {
                release();
                why = "cannot create the shim's descriptor heap";
                return false;
            }
            increment_ = device_->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            block_ = blocks - 1;
        }
        // A new block per view, so descriptors that recorded draws still read stay unchanged until the heap wraps.
        if (++used_ > blocks) {
            release();
            why = "the title memory view changed more than 256 times on one device";
            return false;
        }
        block_ = (block_ + 1) % blocks;
        D3D12_CPU_DESCRIPTOR_HANDLE handle = heap_->GetCPUDescriptorHandleForHeapStart();
        handle.ptr += static_cast<SIZE_T>(block_) * title_memory_slots * increment_;
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
        }
        // The ranges as TitleLookup reads them (stride 24), in an upload buffer kept for the device's lifetime.
        D3D12_HEAP_PROPERTIES upload{};
        upload.Type = D3D12_HEAP_TYPE_UPLOAD;
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = (ranges.empty() ? 1 : ranges.size()) * sizeof(X2WTitleGpuRange);
        desc.Height = 1;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> buffer;
        void* mapped = nullptr;
        if (FAILED(device_->CreateCommittedResource(&upload, D3D12_HEAP_FLAG_NONE, &desc,
                                                    D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&buffer))) ||
            FAILED(buffer->Map(0, nullptr, &mapped))) {
            release();
            why = "cannot create the title ranges buffer";
            return false;
        }
        std::memset(mapped, 0, static_cast<std::size_t>(desc.Width));
        if (!ranges.empty()) std::memcpy(mapped, ranges.data(), ranges.size() * sizeof(ranges[0]));
        buffer->Unmap(0, nullptr);
        ranges_.push_back(buffer);
        release();
        last_ = ranges;
        last_resources_ = resources;
        return true;
    }

    ID3D12Device* device_;  // the desktop device; the owning wrapper outlives this object
    SRWLOCK lock_;
    ComPtr<ID3D12DescriptorHeap> heap_;
    UINT increment_ = 0;
    UINT block_ = 0;
    UINT used_ = 0;
    std::vector<ComPtr<ID3D12Resource>> ranges_;
    std::vector<X2WTitleGpuRange> last_;
    std::vector<void*> last_resources_;  // identity only; not referenced
};

TitleViews* create_title_views(ID3D12Device* device) { return new (std::nothrow) TitleViews(device); }
void destroy_title_views(TitleViews* views) { delete views; }

bool bind_for_draw(TitleViews* views, ID3D12GraphicsCommandList* list, const RootInfo& root, const PsoInfo& pso,
                   const RootArgs& args, ID3D12DescriptorHeap* title_heap, bool* ours_bound)
{
    const char* symbol = "d3d12_xs!ID3D12GraphicsCommandList::Draw";
    std::string why;
    ID3D12DescriptorHeap* heap = nullptr;
    D3D12_GPU_DESCRIPTOR_HANDLE table{};
    D3D12_GPU_VIRTUAL_ADDRESS ranges = 0;
    UINT count = 0;
    if (!views || !views->current(&heap, &table, &ranges, &count, why)) {
        log_refused(symbol, ("draw skipped: " + (why.empty() ? std::string("no title memory view") : why)).c_str(), true);
        return false;
    }
    if (title_heap && title_heap != heap) {
        log_refused(symbol,
                    "draw skipped: the title bound its own CBV/SRV/UAV heap; the converter's title-memory table "
                    "needs a shadow heap (R4)",
                    true);
        return false;
    }
    if (!*ours_bound) {
        list->SetDescriptorHeaps(1, &heap);
        *ours_bound = true;
    }
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
    return true;
}

}  // namespace pipeline
}  // namespace d3d12_xs
