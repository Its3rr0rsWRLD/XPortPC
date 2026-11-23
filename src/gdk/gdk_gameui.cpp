// XGameUI without a system UI: each dialog completes at once with a fixed, logged answer.
// Public reference: https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameui/xgameui_members
//   error dialog   completes with S_OK (as if dismissed), the error code is logged;
//   message dialog completes with its defaultButton;
//   text entry     completes with its defaultText (cut to maxTextLength).
#include "gdk_internal.h"

#include <cstring>
#include <string>
#include <utility>

namespace {

const char error_identity = 0, message_identity = 0, text_identity = 0;

struct Done : x2w::AsyncOp {
    HRESULT work() override { return S_OK; }
};

struct Button : x2w::AsyncOp {
    XGameUiMessageDialogButton button;
    explicit Button(XGameUiMessageDialogButton b) : button(b) {}
    HRESULT work() override { return S_OK; }
    size_t result_size() override { return sizeof button; }
    void get_result(void* buffer, size_t size) override
    {
        if (buffer && size >= sizeof button) memcpy(buffer, &button, sizeof button);
    }
};

struct Text : x2w::AsyncOp {
    std::string text;
    explicit Text(std::string t) : text(std::move(t)) {}
    HRESULT work() override { return S_OK; }
    size_t result_size() override { return text.size() + 1; }
    void get_result(void* buffer, size_t size) override
    {
        if (buffer && size >= text.size() + 1) memcpy(buffer, text.c_str(), text.size() + 1);
    }
};

}  // namespace

extern "C" {

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameui/functions/xgameuishowerrordialogasync
X2W_GDK_API HRESULT x2w_impl_XGameUiShowErrorDialogAsync(XAsyncBlock* async, HRESULT errorCode, const char* context) noexcept
{
    x2w_note("x2w_gdk!XGameUiShowErrorDialogAsync",
             x2w::format("no UI; error 0x%08lx dismissed", static_cast<unsigned long>(errorCode)).c_str());
    (void)context;
    return x2w::async_start(async, &error_identity, "XGameUiShowErrorDialogAsync", new Done);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameui/functions/xgameuishowerrordialogresult
X2W_GDK_API HRESULT x2w_impl_XGameUiShowErrorDialogResult(XAsyncBlock* async) noexcept
{
    return x2w::async_finish(async, &error_identity, [](x2w::AsyncOp*) { return S_OK; });
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameui/functions/xgameuishowmessagedialogasync
X2W_GDK_API HRESULT x2w_impl_XGameUiShowMessageDialogAsync(XAsyncBlock* async, const char* titleText,
                                                           const char* contentText, const char* firstButtonText,
                                                           const char* secondButtonText, const char* thirdButtonText,
                                                           XGameUiMessageDialogButton defaultButton,
                                                           XGameUiMessageDialogButton cancelButton) noexcept
{
    (void)titleText, (void)contentText, (void)firstButtonText, (void)secondButtonText, (void)thirdButtonText;
    (void)cancelButton;
    x2w_note("x2w_gdk!XGameUiShowMessageDialogAsync",
             x2w::format("no UI; default button %u chosen", static_cast<unsigned>(defaultButton)).c_str());
    return x2w::async_start(async, &message_identity, "XGameUiShowMessageDialogAsync", new Button(defaultButton));
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameui/functions/xgameuishowmessagedialogresult
X2W_GDK_API HRESULT x2w_impl_XGameUiShowMessageDialogResult(XAsyncBlock* async, XGameUiMessageDialogButton* resultButton) noexcept
{
    if (!resultButton) return E_POINTER;
    *resultButton = XGameUiMessageDialogButton::First;
    return x2w_impl_XAsyncGetResult(async, &message_identity, sizeof *resultButton, resultButton, nullptr);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameui/functions/xgameuishowtextentryasync
X2W_GDK_API HRESULT x2w_impl_XGameUiShowTextEntryAsync(XAsyncBlock* async, const char* titleText,
                                                       const char* descriptionText, const char* defaultText,
                                                       XGameUiTextEntryInputScope inputScope, uint32_t maxTextLength) noexcept
{
    (void)titleText, (void)descriptionText, (void)inputScope;
    std::string text = defaultText ? defaultText : "";
    if (maxTextLength && text.size() > maxTextLength) text.resize(maxTextLength);
    x2w_note("x2w_gdk!XGameUiShowTextEntryAsync", "no UI; default text returned");
    return x2w::async_start(async, &text_identity, "XGameUiShowTextEntryAsync", new Text(text));
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameui/functions/xgameuishowtextentryresultsize
X2W_GDK_API HRESULT x2w_impl_XGameUiShowTextEntryResultSize(XAsyncBlock* async, uint32_t* resultTextBufferSize) noexcept
{
    if (!resultTextBufferSize) return E_POINTER;
    *resultTextBufferSize = 0;
    size_t size = 0;
    const HRESULT hr = x2w_impl_XAsyncGetResultSize(async, &size);
    if (SUCCEEDED(hr)) *resultTextBufferSize = static_cast<uint32_t>(size);
    return hr;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameui/functions/xgameuishowtextentryresult
X2W_GDK_API HRESULT x2w_impl_XGameUiShowTextEntryResult(XAsyncBlock* async, uint32_t resultTextBufferSize,
                                                        char* resultTextBuffer, uint32_t* resultTextBufferUsed) noexcept
{
    size_t used = 0;
    const HRESULT hr = x2w_impl_XAsyncGetResult(async, &text_identity, resultTextBufferSize, resultTextBuffer, &used);
    if (resultTextBufferUsed) *resultTextBufferUsed = static_cast<uint32_t>(used);
    return hr;
}

}  // extern "C"
