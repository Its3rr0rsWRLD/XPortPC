#pragma once
// Gaming Runtime flat-API types used by XPortPC's system-library shims (docs/design/runtime.md, section 2).
//
// Sources: public documentation only.
//   - XTaskQueue, XAsync, XAsyncProvider: the public MIT-licensed headers of microsoft/libHttpClient
//     (Include/XTaskQueue.h, Include/XAsync.h, Include/XAsyncProvider.h, commit c5007fd9), which are the
//     same flat APIs the GDK reference documents at
//     https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/xtaskqueue_members
//     https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasync/xasync_members
//   - Everything else: the Microsoft Learn GDK reference pages cited beside each declaration
//     (read 2026-11-22, docs view gdk-2610). Where a page gives no value, none is invented here.
// No GDK headers, console SDKs or title files were used.
#include <stddef.h>
#include <stdint.h>
#include <time.h>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

extern "C" {

// ---------------------------------------------------------------- XTaskQueue (libHttpClient XTaskQueue.h)
typedef struct XTaskQueueObject* XTaskQueueHandle;
typedef struct XTaskQueuePortObject* XTaskQueuePortHandle;

enum class XTaskQueueDispatchMode : uint32_t { Manual, ThreadPool, SerializedThreadPool, Immediate };
enum class XTaskQueuePort : uint32_t { Work, Completion };

struct XTaskQueueRegistrationToken {
    uint64_t token;
};

typedef void CALLBACK XTaskQueueCallback(void* context, bool canceled);
typedef void CALLBACK XTaskQueueMonitorCallback(void* context, XTaskQueueHandle queue, XTaskQueuePort port);
typedef void CALLBACK XTaskQueueTerminatedCallback(void* context);

// ---------------------------------------------------------------- XAsync (libHttpClient XAsync.h, XAsyncProvider.h)
struct XAsyncBlock;
typedef void CALLBACK XAsyncCompletionRoutine(struct XAsyncBlock* asyncBlock);
typedef HRESULT CALLBACK XAsyncWork(struct XAsyncBlock* asyncBlock);

struct XAsyncBlock {
    XTaskQueueHandle queue;
    void* context;
    XAsyncCompletionRoutine* callback;
    unsigned char internal[sizeof(void*) * 4];
};

enum class XAsyncOp : uint32_t { Begin, DoWork, GetResult, Cancel, Cleanup };

struct XAsyncProviderData {
    XAsyncBlock* async;
    size_t bufferSize;
    void* buffer;
    void* context;
};

typedef HRESULT CALLBACK XAsyncProvider(XAsyncOp op, const XAsyncProviderData* data);

// ---------------------------------------------------------------- shared types
// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameruntimetypes/structs/xversion
typedef struct XVersion {
    union {
        struct {
            uint16_t major;
            uint16_t minor;
            uint16_t build;
            uint16_t revision;
        };
        uint64_t Value;
    };
} XVersion;

// ---------------------------------------------------------------- XGameRuntime error codes
// https://learn.microsoft.com/en-us/gaming/gdk/_content/gc/reference/system/xgameruntimeinit/xgameruntimeinit_members
#define E_GAMERUNTIME_NOT_INITIALIZED ((HRESULT)0x89240100L)
#define E_GAMERUNTIME_DLL_NOT_FOUND ((HRESULT)0x89240101L)
#define E_GAMERUNTIME_VERSION_MISMATCH ((HRESULT)0x89240102L)
#define E_GAMERUNTIME_INVALID_HANDLE ((HRESULT)0x8924010CL)

// ---------------------------------------------------------------- XSystem
// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xsystem/enums/xsystemdevicetype
enum class XSystemDeviceType : uint32_t {
    Unknown = 0x00,
    Pc = 0x01,
    XboxOne = 0x02,
    XboxOneS = 0x03,
    XboxOneX = 0x04,
    XboxOneXDevkit = 0x05,
    XboxScarlettLockhart = 0x06,
    XboxScarlettAnaconda = 0x07,
    XboxScarlettDevkit = 0x08
};

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xsystem/structs/xsystemanalyticsinfo
typedef struct XSystemAnalyticsInfo {
    XVersion osVersion;
    XVersion hostingOsVersion;
    char family[64];
    char form[64];
} XSystemAnalyticsInfo;

// ---------------------------------------------------------------- XUser
typedef struct XUserObject* XUserHandle;
typedef struct XUserSignOutDeferralObject* XUserSignOutDeferralHandle;

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/structs/xuserlocalid
typedef struct XUserLocalId {
    uint64_t value;
} XUserLocalId;

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/enums/xuseraddoptions
enum class XUserAddOptions : uint32_t {
    None = 0x00,
    AddDefaultUserSilently = 0x01,
    AllowGuests = 0x02,
    AddDefaultUserAllowingUI = 0x04,
};

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/enums/xuserstate
enum class XUserState : uint32_t { SignedIn = 0, SigningOut = 1, SignedOut = 2 };

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/enums/xusergamertagcomponent
// Remarks give the maximum sizes in bytes: Classic 16, Modern 97, ModernSuffix 15, UniqueModern 101.
enum class XUserGamertagComponent : uint32_t { Classic = 0, Modern = 1, ModernSuffix = 2, UniqueModern = 3 };

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/enums/xuseragegroup
enum class XUserAgeGroup : uint32_t { Unknown = 0, Child = 1, Teen = 2, Adult = 3 };

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/enums/xuserprivilegedenyreason
enum class XUserPrivilegeDenyReason : uint32_t {
    None = 0,
    PurchaseRequired = 1,
    Restricted = 2,
    Banned = 3,
    Unknown = 0xFFFFFFFF
};

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/enums/xuserchangeevent
enum class XUserChangeEvent : uint32_t {
    SignedInAgain = 0,
    SigningOut = 1,
    SignedOut = 2,
    Gamertag = 3,
    GamerPicture = 4,
    Privileges = 5,
};

// XUserPrivilegeOptions and XUserPrivilege are passed through; their values are not needed here.
enum class XUserPrivilegeOptions : uint32_t;
enum class XUserPrivilege : uint32_t;

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xuserchangeeventcallback
typedef void CALLBACK XUserChangeEventCallback(void* context, XUserLocalId userLocalId, XUserChangeEvent event);

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/xuser_members (error codes)
#define E_GAMEUSER_MAX_USERS_ADDED ((HRESULT)0x89245100L)
#define E_GAMEUSER_SIGNED_OUT ((HRESULT)0x89245101L)
#define E_GAMEUSER_RESOLVE_USER_ISSUE_REQUIRED ((HRESULT)0x89245102L)
#define E_GAMEUSER_DEFERRAL_NOT_AVAILABLE ((HRESULT)0x89245103L)
#define E_GAMEUSER_USER_NOT_FOUND ((HRESULT)0x89245104L)
#define E_GAMEUSER_NO_TOKEN_REQUIRED ((HRESULT)0x89245105L)
#define E_GAMEUSER_NO_DEFAULT_USER ((HRESULT)0x89245106L)
#define E_GAMEUSER_FAILED_TO_RESOLVE ((HRESULT)0x89245107L)

// ---------------------------------------------------------------- XGameSave
typedef struct XGameSaveProviderObject* XGameSaveProviderHandle;
typedef struct XGameSaveContainerObject* XGameSaveContainerHandle;
typedef struct XGameSaveUpdateObject* XGameSaveUpdateHandle;

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/structs/xgamesavecontainerinfo
typedef struct XGameSaveContainerInfo {
    const char* name;
    const char* displayName;
    uint32_t blobCount;
    uint64_t totalSize;
    time_t lastModifiedTime;
    bool needsSync;
} XGameSaveContainerInfo;

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/structs/xgamesaveblobinfo
typedef struct XGameSaveBlobInfo {
    const char* name;
    uint32_t size;
} XGameSaveBlobInfo;

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/structs/xgamesaveblob
typedef struct XGameSaveBlob {
    XGameSaveBlobInfo info;
    uint8_t* data;
} XGameSaveBlob;

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesaveblobinfocallback
typedef bool CALLBACK XGameSaveBlobInfoCallback(const XGameSaveBlobInfo* info, void* context);
// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavecontainerinfocallback
typedef bool CALLBACK XGameSaveContainerInfoCallback(const XGameSaveContainerInfo* info, void* context);

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/xgamesave_members (error codes)
#define GS_MAX_BLOB_SIZE (16u * 1024u * 1024u)
#define E_GS_INVALID_CONTAINER_NAME ((HRESULT)0x80830001L)
#define E_GS_NO_ACCESS ((HRESULT)0x80830002L)
#define E_GS_OUT_OF_LOCAL_STORAGE ((HRESULT)0x80830003L)
#define E_GS_USER_CANCELED ((HRESULT)0x80830004L)
#define E_GS_UPDATE_TOO_BIG ((HRESULT)0x80830005L)
#define E_GS_QUOTA_EXCEEDED ((HRESULT)0x80830006L)
#define E_GS_PROVIDED_BUFFER_TOO_SMALL ((HRESULT)0x80830007L)
#define E_GS_BLOB_NOT_FOUND ((HRESULT)0x80830008L)
#define E_GS_NO_SERVICE_CONFIGURATION ((HRESULT)0x80830009L)
#define E_GS_CONTAINER_NOT_IN_SYNC ((HRESULT)0x8083000AL)
#define E_GS_CONTAINER_SYNC_FAILED ((HRESULT)0x8083000BL)
#define E_GS_USER_NOT_REGISTERED_IN_SERVICE ((HRESULT)0x8083000CL)
#define E_GS_HANDLE_EXPIRED ((HRESULT)0x8083000DL)

// ---------------------------------------------------------------- XPackage
typedef struct XPackageMountObject* XPackageMountHandle;
struct XPackageChunkSelector;  // passed through; never read by the shim

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/enums/xpackagekind
enum class XPackageKind : uint32_t { Game, Content, PublisherContent };
// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/enums/xpackageenumerationscope
enum class XPackageEnumerationScope : uint32_t { ThisOnly, ThisAndRelated, ThisPublisher };
// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/enums/xpackagechunkavailability
enum class XPackageChunkAvailability : uint32_t { Ready, Pending, Installable, Unavailable };

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/structs/xpackagedetails
typedef struct XPackageDetails {
    const char* packageIdentifier;
    XVersion version;
    XPackageKind kind;
    const char* displayName;
    const char* description;
    const char* publisher;
    const char* storeId;
    bool installing;
    uint32_t index;
    uint32_t count;
    bool ageRestricted;
    const char* titleID;
} XPackageDetails;

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackageenumeratepackages
// (the page's example callback: bool CALLBACK f(void* context, const XPackageDetails* details))
typedef bool CALLBACK XPackageEnumerationCallback(void* context, const XPackageDetails* details);

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/xpackage_members (error codes)
#define E_GAMEPACKAGE_APP_NOT_PACKAGED ((HRESULT)0x89245200L)
#define E_GAMEPACKAGE_NO_PACKAGE_IDENTIFIER ((HRESULT)0x89245208L)

// ---------------------------------------------------------------- XGameUI
// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameui/enums/xgameuimessagedialogbutton
enum class XGameUiMessageDialogButton : uint32_t { First = 0, Second = 1, Third = 2 };
// Passed through; the values are not needed here.
enum class XGameUiTextEntryInputScope : uint32_t;

}  // extern "C"
