// Gaming Runtime functions the gateway serves that x2w_gdk.dll has no implementation for (slots marked
// impl = "xgr" in tools/xgr/interfaces.toml). Signatures are the public flat functions of the GDK
// reference (learn.microsoft.com/gaming/gdk/docs/reference/system/...); each answers offline, like the
// x2w_gdk families (docs/design/runtime.md, section 2).
#include <windows.h>

#include <cstdio>
#include <cstring>
#include <string>

#include "x2w_gdk.h"

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xthread/functions/xthreadassertnottimesensitive
// A debugging aid: the runtime breaks when the calling thread was marked time-sensitive. Nothing here is
// time-sensitive, so it succeeds.
HRESULT xgr_impl_XThreadAssertNotTimeSensitive(void) noexcept { return S_OK; }

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgame/functions/xgamegetxboxtitleid
// The title ID of the running game: the <TitleId> of the MicrosoftGame.config in the title's folder
// (X2W_TITLE_DIR, set by x2w_launch), else 0.
HRESULT xgr_impl_XGameGetXboxTitleId(uint32_t* titleId) noexcept
{
    if (!titleId) return E_INVALIDARG;
    static const uint32_t cached = [] {
        wchar_t dir[MAX_PATH] = {};
        if (!GetEnvironmentVariableW(L"X2W_TITLE_DIR", dir, MAX_PATH)) return 0u;
        const std::wstring path = std::wstring(dir) + L"\\MicrosoftGame.config";
        HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        if (file == INVALID_HANDLE_VALUE) return 0u;
        char text[16384] = {};
        DWORD read = 0;
        ReadFile(file, text, sizeof text - 1, &read, nullptr);
        CloseHandle(file);
        const char* tag = std::strstr(text, "<TitleId>");
        return tag ? static_cast<uint32_t>(std::strtoul(tag + 9, nullptr, 16)) : 0u;
    }();
    *titleId = cached;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetgamerpictureasync
// The offline user's gamer picture: a 1x1 grey PNG, through the public XAsync provider protocol.
namespace {
const unsigned char gamer_picture[] = {
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52, 0x00, 0x00,
    0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, 0xde, 0x00, 0x00, 0x00,
    0x0c, 0x49, 0x44, 0x41, 0x54, 0x78, 0xda, 0x63, 0x68, 0x68, 0x68, 0x00, 0x00, 0x03, 0x04, 0x01, 0x81, 0x75,
    0x2e, 0x01, 0xbc, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82};
const char gamer_picture_identity = 0;

HRESULT CALLBACK gamer_picture_provider(XAsyncOp op, const XAsyncProviderData* data)
{
    switch (op) {
    case XAsyncOp::Begin:
        return x2w_impl_XAsyncSchedule(data->async, 0);
    case XAsyncOp::DoWork:
        x2w_impl_XAsyncComplete(data->async, S_OK, sizeof gamer_picture);
        return S_OK;
    case XAsyncOp::GetResult:
        if (data->bufferSize < sizeof gamer_picture) return E_NOT_SUFFICIENT_BUFFER;
        std::memcpy(data->buffer, gamer_picture, sizeof gamer_picture);
        return S_OK;
    default:
        return S_OK;
    }
}
}  // namespace

HRESULT xgr_impl_XUserGetGamerPictureAsync(XUserHandle user, uint32_t /*pictureSize*/, XAsyncBlock* async) noexcept
{
    if (!user || !async) return E_INVALIDARG;
    return x2w_impl_XAsyncBegin(async, nullptr, &gamer_picture_identity, "XUserGetGamerPictureAsync",
                                gamer_picture_provider);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetgamerpictureresultsize
HRESULT xgr_impl_XUserGetGamerPictureResultSize(XAsyncBlock* async, size_t* bufferSize) noexcept
{
    return x2w_impl_XAsyncGetResultSize(async, bufferSize);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetgamerpictureresult
HRESULT xgr_impl_XUserGetGamerPictureResult(XAsyncBlock* async, size_t bufferSize, void* buffer,
                                             size_t* bufferUsed) noexcept
{
    return x2w_impl_XAsyncGetResult(async, &gamer_picture_identity, bufferSize, buffer, bufferUsed);
}
