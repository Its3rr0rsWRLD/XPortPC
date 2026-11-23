#include "sys_common.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include "../common/x2w_redact.h"

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <unordered_set>

namespace x2w_sys {
namespace {
std::mutex g_mutex;
LogSink g_sink = nullptr;
std::unordered_set<std::string> g_seen;

std::string vformat(const char* fmt, va_list args) {
    va_list copy;
    va_copy(copy, args);
    const int n = std::vsnprintf(nullptr, 0, fmt, copy);
    va_end(copy);
    if (n <= 0) return {};
    std::string out(static_cast<size_t>(n), '\0');
    std::vsnprintf(out.data(), out.size() + 1, fmt, args);
    return out;
}

std::string g_hidden_dir;  // lower-case title folder; shown as <game>

std::string hide_dir(const std::string& text) {
    if (g_hidden_dir.size() < 3) return text;
    std::string result = text;
    for (char slash : {'\\', '/'}) {
        std::string needle = g_hidden_dir;
        for (char& c : needle) if (c == '\\' || c == '/') c = slash;
        std::string folded = result, out;
        for (char& c : folded) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        for (std::size_t at = 0; at < result.size();) {
            if (folded.compare(at, needle.size(), needle) == 0) { out += "<game>"; at += needle.size(); }
            else out += result[at++];
        }
        result = out;
    }
    return result;
}

void emit(const std::string& body) {
    LogSink sink;
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        sink = g_sink;
    }
    const std::string line = "[x2w] " + x2w_redact::apply(hide_dir(body));
    if (sink) {
        sink(line.c_str());
        return;
    }
    std::fprintf(stderr, "%s\n", line.c_str());
    std::fflush(stderr);
    OutputDebugStringA((line + "\n").c_str());
}
}  // namespace

void set_hidden_dir(const std::string& dir) {
    std::string d = dir;
    for (char& c : d) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    while (d.size() > 3 && (d.back() == '\\' || d.back() == '/')) d.pop_back();
    std::lock_guard<std::mutex> lock(g_mutex);
    g_hidden_dir = d;
}

void set_log_sink(LogSink sink) {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_sink = sink;
}

void log(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    const std::string body = vformat(fmt, args);
    va_end(args);
    emit(body);
}

bool log_once(const std::string& key, const char* fmt, ...) {
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        if (!g_seen.insert(key).second) return false;
    }
    va_list args;
    va_start(args, fmt);
    const std::string body = vformat(fmt, args);
    va_end(args);
    emit(body);
    return true;
}

void reset_log_once() {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_seen.clear();
}

std::string get_env(const char* name) {
    char buffer[4096];
    const DWORD n = GetEnvironmentVariableA(name, buffer, sizeof buffer);
    if (n == 0 || n >= sizeof buffer) return {};
    return std::string(buffer, n);
}

std::wstring widen(const std::string& s) {
    if (s.empty()) return {};
    const int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(static_cast<size_t>(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), n);
    return out;
}

std::string narrow(const std::wstring& w) {
    if (w.empty()) return {};
    const int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), static_cast<int>(w.size()), nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<size_t>(n), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), static_cast<int>(w.size()), out.data(), n, nullptr, nullptr);
    return out;
}

std::string trim(const std::string& s) {
    size_t b = 0, e = s.size();
    while (b < e && (s[b] == ' ' || s[b] == '\t' || s[b] == '\r')) ++b;
    while (e > b && (s[e - 1] == ' ' || s[e - 1] == '\t' || s[e - 1] == '\r')) --e;
    return s.substr(b, e - b);
}

std::vector<ConfigEntry> parse_config(const std::string& text) {
    std::vector<ConfigEntry> out;
    size_t pos = 0;
    while (pos <= text.size()) {
        size_t end = text.find('\n', pos);
        if (end == std::string::npos) end = text.size();
        std::string line = trim(text.substr(pos, end - pos));
        pos = end + 1;
        if (line.empty() || line[0] == '#') continue;
        const size_t split = line.find_first_of(" \t=");
        ConfigEntry entry;
        entry.key = split == std::string::npos ? line : line.substr(0, split);
        entry.value = split == std::string::npos ? std::string() : trim(line.substr(split + 1));
        if (!entry.value.empty() && entry.value[0] == '=') entry.value = trim(entry.value.substr(1));
        for (char& c : entry.key) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        out.push_back(std::move(entry));
    }
    return out;
}

uint64_t mul_div_u64(uint64_t a, uint64_t b, uint64_t c) {
    const uint64_t q = a / c;
    const uint64_t r = a % c;
    return q * b + (r * b) / c;
}

}  // namespace x2w_sys
