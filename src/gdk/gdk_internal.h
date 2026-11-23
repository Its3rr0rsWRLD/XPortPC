#pragma once
// Internal helpers shared by the x2w_gdk.dll modules. Not exported.
#include "x2w_gdk.h"

#include <functional>
#include <string>

namespace x2w {

// UTF-8 <-> UTF-16.
std::wstring widen(const std::string& text);
std::string narrow(const std::wstring& text);
// An environment variable as UTF-8, or "" when unset.
std::string env(const char* name);

// The title's name (safe as one path component), the title's folder, and the folder its saves live in.
std::string title_name();
std::string title_dir();
std::wstring save_dir();

// "dll!symbol"-style formatting helper for log details.
std::string format(const char* fmt, ...);

// HRESULT for a too-small caller buffer.
constexpr HRESULT insufficient_buffer = static_cast<HRESULT>(0x8007007AL);  // HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER)
constexpr HRESULT not_found = static_cast<HRESULT>(0x80070490L);            // HRESULT_FROM_WIN32(ERROR_NOT_FOUND)

// An asynchronous operation of ours, run through the public XAsync provider machinery (gdk_async.cpp).
// work() runs on the async block's work port; result_size() is what XAsyncGetResultSize reports after a
// successful work(); get_result() serves a caller of the generic XAsyncGetResult.
struct AsyncOp {
    virtual ~AsyncOp() = default;
    virtual HRESULT work() = 0;
    virtual size_t result_size() { return 0; }
    virtual void get_result(void* /*buffer*/, size_t /*size*/) {}
};

// Starts `op` (taking ownership) on `block`. On failure `op` is deleted and the HRESULT returned.
HRESULT async_start(XAsyncBlock* block, const void* identity, const char* name, AsyncOp* op) noexcept;
// For a Result function: E_PENDING while running, the failure code if the call failed, otherwise the
// result of `take(op)` (op is null for calls whose state is already gone, i.e. payload-free results).
// When take succeeds the call's state is released, as XAsyncGetResult does.
HRESULT async_finish(XAsyncBlock* block, const void* identity, const std::function<HRESULT(AsyncOp*)>& take) noexcept;

// Task queue internals for XUser change-event registrations (gdk_taskqueue.cpp).
uint64_t next_token() noexcept;

}  // namespace x2w
