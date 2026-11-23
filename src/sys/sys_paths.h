// Console-style path remapping. Rules are data: "<from> -> <to> [flags]". The defaults come from the public
// GDK local-storage overview (learn.microsoft.com/gaming/gdk/_content/gc/system/overviews/local-storage):
// drive G: is the installed game data (read only on console), drive T: is temporary local storage deleted when
// the title ends, drive D: is a development-only scratch partition. Persistent local storage and mounted DLC
// have no fixed letter (the title gets those paths from XPersistentLocalStorageGetPath / XPackageGetMountPath),
// so the gateway adds rules for them at run time with add_rule().
#pragma once

#include <string>
#include <vector>

namespace x2w_sys::paths {

struct Rule {
    std::wstring from;      // normalized: backslashes, no trailing backslash (e.g. L"G:")
    std::wstring to;        // expanded target, no trailing backslash
    bool mkdir = false;     // create missing parent directories on write-like operations
    bool read_only = false; // write-like operations fail with ERROR_ACCESS_DENIED
    std::string spec;       // the rule as written, for logs
};

struct Context {
    std::wstring title_dir;       // the title's install folder (package root)
    std::wstring title_name;      // short name used in %TITLE%
    std::wstring local_app_data;  // empty: read %LOCALAPPDATA%
};

struct Result {
    bool remapped = false;
    bool deny_write = false;  // the matching rule is read only
    bool mkdir = false;
    size_t rule_index = 0;
    std::wstring path;  // the path to use (the input when not remapped)
};

class Map {
public:
    void set_context(const Context& ctx);
    const Context& context() const { return ctx_; }
    // Spec: "G:\ -> %TITLEDIR%\ [ro] [mkdir]". Variables: %TITLEDIR%, %TITLE%, %LOCALAPPDATA%, %XPORT%
    // (= %LOCALAPPDATA%\XPortPC\%TITLE%). Returns false and fills *error for a malformed rule.
    bool add_rule(const std::string& spec, std::string* error = nullptr);
    void add_default_rules();
    void clear();
    size_t size() const { return rules_.size(); }
    const Rule& rule(size_t i) const { return rules_[i]; }

    // Longest matching prefix wins. Matching is case-insensitive on whole path components and accepts "/" and a
    // "\\?\" prefix. Drive-relative paths ("G:foo"), UNC paths and relative paths are never remapped.
    Result remap(const std::wstring& path) const;

private:
    std::wstring expand(const std::wstring& text) const;
    Context ctx_;
    std::vector<Rule> rules_;
};

// Counters for the end-of-run summary.
struct Stats {
    unsigned long long remaps = 0;
    unsigned long long denied = 0;
};

// Process-wide map used by the hooks.
Map& global_map();
Stats& global_stats();
void apply_config_line(const std::string& key, const std::string& value);
void log_summary();
// For a handle the title opened through the hooks and has not closed: "opened-as NAME flags=(...) type-at-open=T".
bool describe_handle(void* handle, std::string* out);

// Hook table for sys_hooks.cpp: (symbol, replacement) pairs, kernel32 signatures.
struct HookEntry {
    const char* symbol;
    void* replacement;
};
const HookEntry* hooks(size_t* count);

}  // namespace x2w_sys::paths
