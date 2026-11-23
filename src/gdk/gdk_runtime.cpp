// XGameRuntime initialization and XSystem identity answers.
// docs/design/runtime.md, section 2: titles branch on the device type, so XSystem reports an Xbox Series X
// (XboxScarlettAnaconda) and the retail defaults the public pages document.
#include "gdk_internal.h"

#include <atomic>
#include <cstdio>
#include <cstring>

namespace {
std::atomic<long> g_initialized{0};

HRESULT copy_string(const char* text, size_t size, char* buffer, size_t* used)
{
    const size_t needed = strlen(text) + 1;
    if (used) *used = 0;
    if (!buffer || size < needed) return x2w::insufficient_buffer;
    memcpy(buffer, text, needed);
    if (used) *used = needed;
    return S_OK;
}
}  // namespace

extern "C" {

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameruntimeinit/functions/xgameruntimeinitialize
// Every binary using the runtime calls it; the page does not say whether calls are counted, so each call
// succeeds and is counted.
X2W_GDK_API HRESULT x2w_impl_XGameRuntimeInitialize(void) noexcept
{
    if (g_initialized.fetch_add(1) == 0)
        x2w_note("x2w_gdk!XGameRuntimeInitialize", x2w::format("offline runtime for title %s", x2w::title_name().c_str()).c_str());
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameruntimeinit/functions/xgameruntimeuninitialize
X2W_GDK_API void x2w_impl_XGameRuntimeUninitialize(void) noexcept
{
    long current = g_initialized.load();
    while (current > 0 && !g_initialized.compare_exchange_weak(current, current - 1)) {
    }
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xsystem/functions/xsystemgetdevicetype
X2W_GDK_API XSystemDeviceType x2w_impl_XSystemGetDeviceType(void) noexcept
{
    return XSystemDeviceType::XboxScarlettAnaconda;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xsystem/functions/xsystemgetconsoleid
// "In RETAIL, the function always returns 00000000.00000000.00000000.00000000.00." The page names
// XSystemConsoleIdBytes without a value; this answer needs strlen + 1 = 39 bytes.
X2W_GDK_API HRESULT x2w_impl_XSystemGetConsoleId(size_t consoleIdSize, char* consoleId, size_t* consoleIdUsed) noexcept
{
    return copy_string("00000000.00000000.00000000.00000000.00", consoleIdSize, consoleId, consoleIdUsed);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xsystem/functions/xsystemgetxboxlivesandboxid
// "If the sandbox ID isn't found ... it defaults to 'RETAIL'."
X2W_GDK_API HRESULT x2w_impl_XSystemGetXboxLiveSandboxId(size_t sandboxIdSize, char* sandboxId, size_t* sandboxIdUsed) noexcept
{
    return copy_string("RETAIL", sandboxIdSize, sandboxId, sandboxIdUsed);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xsystem/functions/xsystemgetanalyticsinfo
// family "Xbox" is one of the page's example values. The page gives no Series X form string or console OS
// version, so form is our own label and both versions report the host Windows version.
X2W_GDK_API XSystemAnalyticsInfo x2w_impl_XSystemGetAnalyticsInfo(void) noexcept
{
    XSystemAnalyticsInfo info{};
    using RtlGetVersionFn = LONG(WINAPI*)(OSVERSIONINFOW*);
    OSVERSIONINFOW version{};
    version.dwOSVersionInfoSize = sizeof version;
    if (auto fn = reinterpret_cast<RtlGetVersionFn>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion")))
        fn(&version);
    info.osVersion.major = static_cast<uint16_t>(version.dwMajorVersion);
    info.osVersion.minor = static_cast<uint16_t>(version.dwMinorVersion);
    info.osVersion.build = static_cast<uint16_t>(version.dwBuildNumber);
    info.hostingOsVersion = info.osVersion;
    std::snprintf(info.family, sizeof info.family, "%s", "Xbox");
    std::snprintf(info.form, sizeof info.form, "%s", "Xbox Series X (XPortPC)");
    return info;
}

}  // extern "C"
