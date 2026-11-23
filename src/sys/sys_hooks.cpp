#include "sys_hooks.h"

#include "sys_audio.h"
#include "sys_common.h"
#include "sys_dstorage.h"
#include "sys_gameinput.h"
#include "sys_paths.h"
#include "sys_threads.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>

namespace {

std::string lower_ascii(std::string s) {
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

bool win32_dll(const std::string& dll) {
    const std::string d = lower_ascii(dll);
    return d == "kernel32.dll" || d == "kernelbase.dll" || d == "kernel32" || d.rfind("api-ms-win-core-", 0) == 0;
}

std::wstring base_name(const std::wstring& dir) {
    std::wstring d = dir;
    while (!d.empty() && (d.back() == L'\\' || d.back() == L'/')) d.pop_back();
    const size_t cut = d.find_last_of(L"\\/");
    return cut == std::wstring::npos ? d : d.substr(cut + 1);
}

// Deletes the contents of the T: folder. Only a folder named "temp" directly under the title's XPortPC folder.
void remove_tree(const std::wstring& dir) {
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((dir + L"\\*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        const std::wstring name = fd.cFileName;
        if (name == L"." || name == L"..") continue;
        const std::wstring full = dir + L"\\" + name;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) {  // never follow links
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) RemoveDirectoryW(full.c_str()); else DeleteFileW(full.c_str());
        } else if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            remove_tree(full);
            RemoveDirectoryW(full.c_str());
        } else {
            SetFileAttributesW(full.c_str(), FILE_ATTRIBUTE_NORMAL);
            DeleteFileW(full.c_str());
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

}  // namespace

namespace x2w_sys {
void clean_temp_folder() {
    auto& map = paths::global_map();
    const auto r = map.remap(L"T:\\");
    if (!r.remapped) return;
    const std::wstring expect = map.context().local_app_data + L"\\XPortPC\\" + map.context().title_name + L"\\temp";
    if (_wcsicmp(r.path.c_str(), expect.c_str()) != 0) return;  // a user rule points T: elsewhere: leave it alone
    const DWORD a = GetFileAttributesW(r.path.c_str());
    if (a == INVALID_FILE_ATTRIBUTES || !(a & FILE_ATTRIBUTE_DIRECTORY) || (a & FILE_ATTRIBUTE_REPARSE_POINT)) return;
    remove_tree(r.path);
    log("paths: cleared temporary storage %s (T: is deleted when a title ends)", narrow(r.path).c_str());
}
}  // namespace x2w_sys

X2W_SYS_API int __stdcall X2WSysInit(const char* title_dir, const char* title_name, const char* config_path) {
    using namespace x2w_sys;
    std::string cfg_file = config_path && *config_path ? config_path : get_env("X2W_SYS_CONFIG");
    if (cfg_file.empty() && title_dir && *title_dir) cfg_file = std::string(title_dir) + "\\x2w-sys.cfg";
    std::vector<ConfigEntry> entries;
    {
        std::ifstream in(cfg_file, std::ios::binary);
        if (in) {
            std::stringstream ss;
            ss << in.rdbuf();
            entries = parse_config(ss.str());
            log("sys: config %s (%zu entries)", cfg_file.c_str(), entries.size());
        }
    }
    paths::Context ctx;
    ctx.title_dir = widen(title_dir ? title_dir : "");
    while (ctx.title_dir.size() > 3 && (ctx.title_dir.back() == L'\\' || ctx.title_dir.back() == L'/')) ctx.title_dir.pop_back();
    ctx.title_name = widen(title_name && *title_name ? title_name : narrow(base_name(ctx.title_dir)));
    auto& map = paths::global_map();
    map.clear();
    map.set_context(ctx);
    bool defaults = true, clean_temp = true;
    for (const auto& e : entries) {
        if (e.key == "paths.defaults") defaults = e.value != "off" && e.value != "0";
        if (e.key == "paths.clean_temp") clean_temp = e.value != "off" && e.value != "0";
    }
    if (defaults && !ctx.title_dir.empty()) map.add_default_rules();
    for (const auto& e : entries) {
        paths::apply_config_line(e.key, e.value);
        threads::apply_config_line(e.key, e.value);
        gi::apply_config_line(e.key, e.value);
        audio::apply_config_line(e.key, e.value);
        ds::apply_config_line(e.key, e.value);
    }
    for (size_t i = 0; i < map.size(); ++i)
        log("paths: rule %s -> %s%s%s", narrow(map.rule(i).from).c_str(), narrow(map.rule(i).to).c_str(),
            map.rule(i).read_only ? " [ro]" : "", map.rule(i).mkdir ? " [mkdir]" : "");
    if (clean_temp) clean_temp_folder();
    threads::init_from_host();
    return 0;
}

X2W_SYS_API void* __stdcall X2WSysHookLookup(const char* dll, const char* symbol) {
    if (!dll || !symbol || !win32_dll(dll)) return nullptr;
    size_t n = 0;
    for (const auto* h = x2w_sys::paths::hooks(&n); n--; ++h)
        if (std::strcmp(h->symbol, symbol) == 0) return h->replacement;
    for (const auto* h = x2w_sys::threads::hooks(&n); n--; ++h)
        if (std::strcmp(h->symbol, symbol) == 0) return h->replacement;
    return nullptr;
}

X2W_SYS_API void __stdcall X2WSysShutdown(void) {
    x2w_sys::paths::log_summary();
    x2w_sys::threads::log_summary();
    const auto& a = x2w_sys::audio::stats();
    x2w_sys::log("audio: formats seen: %llu PCM, %llu ADPCM, %llu float, %llu XMA, %llu rejected",
                 static_cast<unsigned long long>(a.pcm), static_cast<unsigned long long>(a.adpcm),
                 static_cast<unsigned long long>(a.flt), static_cast<unsigned long long>(a.xma),
                 static_cast<unsigned long long>(a.rejected));
    const auto& d = x2w_sys::ds::stats();
    x2w_sys::log("directstorage: fallback %llu requests, %llu bytes read, %llu failed",
                 static_cast<unsigned long long>(d.requests), static_cast<unsigned long long>(d.bytes_read),
                 static_cast<unsigned long long>(d.failed));
}
