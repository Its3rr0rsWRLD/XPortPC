// XUser: one offline local user, always signed in, never a guest, an adult with every privilege.
// Public reference: https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/xuser_members
// XUserAddAsync completes with that user whatever its options (no account picker exists). Its gamertag is
// X2W_GAMERTAG (default "XPortPC") and its id X2W_USER_ID (decimal; default 0x0009000000000001), both
// fixed for the process. No change event ever fires.
#include "gdk_internal.h"

#include <atomic>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>

struct XUserObject {
    uint32_t signature = 0x31525558;  // "XUR1"
    std::atomic<long> handles{0};
    uint64_t id = 0x0009000000000001ull;
    XUserLocalId local{1};
    std::string gamertag;
};

namespace {

XUserObject* the_user()
{
    static XUserObject* user = [] {
        auto* u = new XUserObject;
        u->gamertag = x2w::env("X2W_GAMERTAG");
        if (u->gamertag.empty()) u->gamertag = "XPortPC";
        if (u->gamertag.size() > 96) u->gamertag.resize(96);
        const std::string id = x2w::env("X2W_USER_ID");
        if (!id.empty()) u->id = std::strtoull(id.c_str(), nullptr, 10);
        return u;
    }();
    return user;
}

XUserObject* valid(XUserHandle handle)
{
    return handle && handle->signature == 0x31525558 ? handle : nullptr;
}

XUserHandle new_handle()
{
    XUserObject* user = the_user();
    user->handles.fetch_add(1);
    return user;
}

const char add_identity = 0;

struct AddUser : x2w::AsyncOp {
    HRESULT work() override { return S_OK; }
    size_t result_size() override { return sizeof(XUserHandle); }
    void get_result(void* buffer, size_t size) override
    {
        if (buffer && size >= sizeof(XUserHandle)) *static_cast<XUserHandle*>(buffer) = new_handle();
    }
};

SRWLOCK g_events_lock = SRWLOCK_INIT;
std::map<uint64_t, XUserChangeEventCallback*>* g_events = new std::map<uint64_t, XUserChangeEventCallback*>;

HRESULT copy_text(const std::string& text, size_t size, char* buffer, size_t* used)
{
    if (used) *used = 0;
    if (!buffer || size < text.size() + 1) return x2w::insufficient_buffer;
    memcpy(buffer, text.c_str(), text.size() + 1);
    if (used) *used = text.size() + 1;
    return S_OK;
}

}  // namespace

extern "C" {

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuseraddasync
X2W_GDK_API HRESULT x2w_impl_XUserAddAsync(XUserAddOptions options, XAsyncBlock* async) noexcept
{
    if (!async) return E_POINTER;
    x2w_note("x2w_gdk!XUserAddAsync",
             x2w::format("offline user added (options 0x%x)", static_cast<unsigned>(options)).c_str());
    return x2w::async_start(async, &add_identity, "XUserAddAsync", new AddUser);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuseraddresult
X2W_GDK_API HRESULT x2w_impl_XUserAddResult(XAsyncBlock* async, XUserHandle* newUser) noexcept
{
    if (!newUser) return E_POINTER;
    *newUser = nullptr;
    return x2w_impl_XAsyncGetResult(async, &add_identity, sizeof(XUserHandle), newUser, nullptr);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuserduplicatehandle
X2W_GDK_API HRESULT x2w_impl_XUserDuplicateHandle(XUserHandle handle, XUserHandle* duplicatedHandle) noexcept
{
    if (!duplicatedHandle) return E_POINTER;
    *duplicatedHandle = nullptr;
    if (!valid(handle)) return E_INVALIDARG;
    *duplicatedHandle = new_handle();
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuserclosehandle
X2W_GDK_API void x2w_impl_XUserCloseHandle(XUserHandle user) noexcept
{
    if (XUserObject* u = valid(user)) {
        if (u->handles.fetch_sub(1) <= 0) {
            u->handles.fetch_add(1);
            x2w_unimplemented("x2w_gdk!XUserCloseHandle", "handle closed more often than it was returned");
        }
    }
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusercompare
X2W_GDK_API int32_t x2w_impl_XUserCompare(XUserHandle user1, XUserHandle user2) noexcept
{
    const XUserObject* a = valid(user1);
    const XUserObject* b = valid(user2);
    if (a == b) return 0;
    return a < b ? -1 : 1;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetmaxusers
X2W_GDK_API HRESULT x2w_impl_XUserGetMaxUsers(uint32_t* maxUsers) noexcept
{
    if (!maxUsers) return E_POINTER;
    *maxUsers = 1;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetid
X2W_GDK_API HRESULT x2w_impl_XUserGetId(XUserHandle user, uint64_t* userId) noexcept
{
    if (!userId) return E_POINTER;
    *userId = 0;
    const XUserObject* u = valid(user);
    if (!u) return E_INVALIDARG;
    *userId = u->id;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuserfinduserbyid
// The page lists no codes; ERROR_NOT_FOUND is what XUserFindUserByLocalId documents.
X2W_GDK_API HRESULT x2w_impl_XUserFindUserById(uint64_t userId, XUserHandle* handle) noexcept
{
    if (!handle) return E_POINTER;
    *handle = nullptr;
    if (userId != the_user()->id) return x2w::not_found;
    *handle = new_handle();
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetlocalid
X2W_GDK_API HRESULT x2w_impl_XUserGetLocalId(XUserHandle user, XUserLocalId* userLocalId) noexcept
{
    if (!userLocalId) return E_POINTER;
    userLocalId->value = 0;
    const XUserObject* u = valid(user);
    if (!u) return E_INVALIDARG;
    *userLocalId = u->local;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuserfinduserbylocalid
X2W_GDK_API HRESULT x2w_impl_XUserFindUserByLocalId(XUserLocalId userLocalId, XUserHandle* handle) noexcept
{
    if (!handle) return E_POINTER;
    *handle = nullptr;
    if (userLocalId.value != the_user()->local.value) return x2w::not_found;
    *handle = new_handle();
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetisguest
X2W_GDK_API HRESULT x2w_impl_XUserGetIsGuest(XUserHandle user, bool* isGuest) noexcept
{
    if (!isGuest) return E_POINTER;
    *isGuest = false;
    return valid(user) ? S_OK : E_INVALIDARG;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetstate
X2W_GDK_API HRESULT x2w_impl_XUserGetState(XUserHandle user, XUserState* state) noexcept
{
    if (!state) return E_POINTER;
    *state = XUserState::SignedIn;
    return valid(user) ? S_OK : E_INVALIDARG;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetgamertag
// Sizes from XUserGamertagComponent's remarks: Classic 16 bytes, Modern 97, ModernSuffix 15, UniqueModern 101.
X2W_GDK_API HRESULT x2w_impl_XUserGetGamertag(XUserHandle user, XUserGamertagComponent gamertagComponent,
                                              size_t gamertagSize, char* gamertag, size_t* gamertagUsed) noexcept
{
    if (gamertagUsed) *gamertagUsed = 0;
    const XUserObject* u = valid(user);
    if (!u) return E_INVALIDARG;
    std::string text = u->gamertag;
    switch (gamertagComponent) {
    case XUserGamertagComponent::Classic:
        if (text.size() > 15) text.resize(15);
        break;
    case XUserGamertagComponent::Modern:
    case XUserGamertagComponent::UniqueModern: break;
    case XUserGamertagComponent::ModernSuffix: text.clear(); break;
    default: return E_INVALIDARG;
    }
    if (gamertag && gamertagSize < text.size() + 1) return E_NOT_SUFFICIENT_BUFFER;
    return copy_text(text, gamertagSize, gamertag, gamertagUsed);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetagegroup
X2W_GDK_API HRESULT x2w_impl_XUserGetAgeGroup(XUserHandle user, XUserAgeGroup* ageGroup) noexcept
{
    if (!ageGroup) return E_POINTER;
    *ageGroup = XUserAgeGroup::Adult;
    return valid(user) ? S_OK : E_INVALIDARG;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusercheckprivilege
X2W_GDK_API HRESULT x2w_impl_XUserCheckPrivilege(XUserHandle user, XUserPrivilegeOptions options,
                                                 XUserPrivilege privilege, bool* hasPrivilege,
                                                 XUserPrivilegeDenyReason* reason) noexcept
{
    (void)options;
    (void)privilege;
    if (!hasPrivilege) return E_POINTER;
    *hasPrivilege = true;
    if (reason) *reason = XUserPrivilegeDenyReason::None;
    return valid(user) ? S_OK : E_INVALIDARG;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuserregisterforchangeevent
X2W_GDK_API HRESULT x2w_impl_XUserRegisterForChangeEvent(XTaskQueueHandle queue, void* context,
                                                         XUserChangeEventCallback* callback,
                                                         XTaskQueueRegistrationToken* token) noexcept
{
    (void)queue;
    (void)context;
    if (!token) return E_POINTER;
    token->token = 0;
    if (!callback) return E_INVALIDARG;
    token->token = x2w::next_token();
    AcquireSRWLockExclusive(&g_events_lock);
    (*g_events)[token->token] = callback;
    ReleaseSRWLockExclusive(&g_events_lock);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuserunregisterforchangeevent
X2W_GDK_API bool x2w_impl_XUserUnregisterForChangeEvent(XTaskQueueRegistrationToken token, bool wait) noexcept
{
    (void)wait;
    AcquireSRWLockExclusive(&g_events_lock);
    g_events->erase(token.token);
    ReleaseSRWLockExclusive(&g_events_lock);
    return true;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetsignoutdeferral
// No sign-out ever happens, so no deferral is available (a documented return code).
X2W_GDK_API HRESULT x2w_impl_XUserGetSignOutDeferral(XUserSignOutDeferralHandle* deferral) noexcept
{
    if (deferral) *deferral = nullptr;
    return E_GAMEUSER_DEFERRAL_NOT_AVAILABLE;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuserclosesignoutdeferralhandle
X2W_GDK_API void x2w_impl_XUserCloseSignOutDeferralHandle(XUserSignOutDeferralHandle deferral) noexcept
{
    (void)deferral;
}

}  // extern "C"
