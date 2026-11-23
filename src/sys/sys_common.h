// Shared helpers for the system-library modules (src/sys): logging with once-per-key lines, and the
// line-based config format. MIT licensed; see docs/design/system-libs.md.
#pragma once

#include <cstdarg>
#include <cstdint>
#include <string>
#include <vector>

#if defined(_MSC_VER)
#define X2W_SYS_PRINTF(a, b)
#else
#define X2W_SYS_PRINTF(a, b) __attribute__((format(printf, a, b)))
#endif

namespace x2w_sys {

using LogSink = void (*)(const char* line);

// Null restores the default sink (stderr, plus OutputDebugString on Windows). Lines get a "[x2w] " prefix.
void set_log_sink(LogSink sink);
// The title folder: every log line shows it as "<game>".
void set_hidden_dir(const std::string& dir);
void log(const char* fmt, ...) X2W_SYS_PRINTF(1, 2);
// Prints only the first time `key` is seen since reset_log_once(). Returns true when it printed.
bool log_once(const std::string& key, const char* fmt, ...) X2W_SYS_PRINTF(2, 3);
void reset_log_once();
// The text as a log line would show it (title folder as <game>, host paths as <path>\leaf), without the prefix.
std::string redact_line(const std::string& body);
// Tells x2w_launch (when it runs the title) that this module created the handle, for its stall lines. No-op otherwise.
void tag_handle(void* handle, const char* who);

std::string get_env(const char* name);
std::wstring widen(const std::string& utf8);
std::string narrow(const std::wstring& wide);

// Config text: one entry per line, "#" starts a comment, "key value..." or "key=value...". Keys are lower case.
struct ConfigEntry {
    std::string key;
    std::string value;
};
std::vector<ConfigEntry> parse_config(const std::string& text);
std::string trim(const std::string& s);

// a*b/c without overflow for c < 2^32 and b < 2^32 (a is any 64-bit value).
uint64_t mul_div_u64(uint64_t a, uint64_t b, uint64_t c);

}  // namespace x2w_sys
