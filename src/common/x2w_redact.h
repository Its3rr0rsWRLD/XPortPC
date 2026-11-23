// Log redaction shared by the launcher and every shim that writes to stderr (MIT).
// Host paths and the program's file name are never logged: a drive path becomes "<path>\leaf" and the program's
// file name becomes "title.exe", unless the launcher was run with --show-program-name (X2W_SHOW_PROGRAM_NAME=1),
// which only our own tests use. The launcher sets X2W_TITLE to the program's file stem.
#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <cctype>
#include <string>

namespace x2w_redact {

inline std::string lower(std::string s)
{
    for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

// Read live from the process environment (not the CRT's copy, which a DLL snapshots when it loads).
inline std::string env(const char* name)
{
    char buffer[1024];
    const DWORD n = GetEnvironmentVariableA(name, buffer, sizeof buffer);
    return n && n < sizeof buffer ? std::string(buffer, n) : std::string();
}

inline std::string program_file()  // lower-case "<stem>.exe", or empty
{
    const std::string stem = env("X2W_TITLE");
    return stem.empty() ? stem : lower(stem) + ".exe";
}

inline bool show_names() { return env("X2W_SHOW_PROGRAM_NAME") == "1"; }

inline std::string replace_ci(const std::string& text, const std::string& needle_lower, const char* with)
{
    if (needle_lower.empty()) return text;
    const std::string folded = lower(text);
    std::string out;
    for (std::size_t at = 0; at < text.size();) {
        if (folded.compare(at, needle_lower.size(), needle_lower) == 0) { out += with; at += needle_lower.size(); }
        else out += text[at++];
    }
    return out;
}

inline std::string hide_paths(const std::string& text, const std::string& program_lower, const char* program_shown)
{
    static const char* const stops[] = {" -> ", " (", " [", "\"", "'", ", ", " = ", ": "};
    std::string out;
    std::size_t at = 0;
    while (at < text.size()) {
        const bool drive = at + 2 < text.size() && std::isalpha(static_cast<unsigned char>(text[at])) &&
                           text[at + 1] == ':' && (text[at + 2] == '\\' || text[at + 2] == '/') &&
                           (at == 0 || !std::isalnum(static_cast<unsigned char>(text[at - 1])));
        // UNC paths: \\server\share\..., \\?\UNC\..., \\?\C:\... (device names such as \\.\pipe\x stay)
        const bool unc = at + 2 < text.size() && text[at] == '\\' && text[at + 1] == '\\' &&
                         (std::isalnum(static_cast<unsigned char>(text[at + 2])) || text[at + 2] == '?') &&
                         (at == 0 || (text[at - 1] != '\\' && !std::isalnum(static_cast<unsigned char>(text[at - 1]))));
        const bool start = drive || unc;
        if (!start) { out += text[at++]; continue; }
        std::size_t end = text.size();
        for (const char* stop : stops) {
            const std::size_t found = text.find(stop, at + 3);
            if (found != std::string::npos && found < end) end = found;
        }
        while (end > at && (text[end - 1] == '\n' || text[end - 1] == '\r' || text[end - 1] == ' ')) --end;
        const std::string path = text.substr(at, end - at);
        const std::size_t slash = path.find_last_of("\\/");
        std::string leaf = slash == std::string::npos ? std::string() : path.substr(slash + 1);
        std::string folded = leaf;
        for (char& c : folded) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        if (!program_lower.empty() && folded == program_lower) leaf = program_shown;
        // A folder path's leaf can be the account name (C:\\Users\\<name>): never shown.
        const std::string user = lower(env("USERNAME"));
        if (!user.empty() && folded == user) leaf.clear();
        if (out.size() >= 4 && out.compare(out.size() - 4, 4, "\\\\?\\") == 0) out.resize(out.size() - 4);
        out += leaf.empty() ? "<path>" : "<path>\\" + leaf;
        at = end;
    }
    return out;
}

inline std::string apply(const std::string& text)
{
    if (show_names()) return text;
    const std::string program = program_file(), stem = lower(env("X2W_TITLE"));
    std::string out = replace_ci(hide_paths(text, program, "title.exe"), program, "title.exe");
    // The bare stem too (a runtime names the title by it), when long enough not to clobber ordinary words.
    if (stem.size() >= 5) out = replace_ci(out, stem, "title");
    return out;
}

}  // namespace x2w_redact
