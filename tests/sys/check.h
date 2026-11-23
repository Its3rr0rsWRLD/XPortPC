// Tiny test helpers for the system-library checks.
#pragma once

#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>
#include <vector>

#include "sys_common.h"

namespace chk {
inline int failures = 0;
inline std::mutex log_mutex;
inline std::vector<std::string> lines;

inline void sink(const char* line) {
    std::lock_guard<std::mutex> lock(log_mutex);
    lines.emplace_back(line);
}
inline void capture() {
    x2w_sys::reset_log_once();
    { std::lock_guard<std::mutex> lock(log_mutex); lines.clear(); }
    x2w_sys::set_log_sink(&sink);
}
inline int count(const std::string& needle) {
    std::lock_guard<std::mutex> lock(log_mutex);
    int n = 0;
    for (const auto& l : lines) if (l.find(needle) != std::string::npos) ++n;
    return n;
}
inline void dump() {
    std::lock_guard<std::mutex> lock(log_mutex);
    for (const auto& l : lines) std::fprintf(stderr, "  log: %s\n", l.c_str());
}
}  // namespace chk

#define CHECK(cond)                                                                    \
    do {                                                                               \
        if (!(cond)) {                                                                 \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);       \
            ++chk::failures;                                                           \
        }                                                                              \
    } while (0)

#define CHECK_EQ(a, b)                                                                                     \
    do {                                                                                                   \
        const auto va_ = (a);                                                                              \
        const auto vb_ = (b);                                                                              \
        if (!(va_ == vb_)) {                                                                               \
            std::fprintf(stderr, "FAIL %s:%d: %s == %s (got %lld vs %lld)\n", __FILE__, __LINE__, #a, #b,  \
                         static_cast<long long>(va_), static_cast<long long>(vb_));                        \
            ++chk::failures;                                                                               \
        }                                                                                                  \
    } while (0)

inline int finish(const char* name) {
    if (chk::failures) {
        chk::dump();
        std::printf("FAIL %s (%d failed checks)\n", name, chk::failures);
        return 1;
    }
    std::printf("PASS %s\n", name);
    return 0;
}
