// XPackage: the title's folder is its installed package, and mounting the title's own identifier gives
// that folder. Public reference: https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/xpackage_members
// The identifier is "x2w." + the title name, cut to 32 characters (the reference names
// XPACKAGE_IDENTIFIER_MAX_LENGTH without a value; its sample sizes a char array with it, so we stay short).
// Every chunk is Ready. Content packages (DLC) do not exist.
#include "gdk_internal.h"

#include <cstring>
#include <string>

struct XPackageMountObject {
    uint32_t signature = 0x314d5058;  // "XPM1"
    std::string path;
};

namespace {

std::string identifier()
{
    std::string id = "x2w." + x2w::title_name();
    if (id.size() > 32) id.resize(32);
    return id;
}

HRESULT copy_string(const std::string& text, size_t size, char* buffer)
{
    if (!buffer || size < text.size() + 1) return x2w::insufficient_buffer;
    memcpy(buffer, text.c_str(), text.size() + 1);
    return S_OK;
}

XPackageMountObject* valid(XPackageMountHandle h) { return h && h->signature == 0x314d5058 ? h : nullptr; }

HRESULT mount(const char* packageIdentifier, XPackageMountHandle* out)
{
    if (!out) return E_POINTER;
    *out = nullptr;
    if (!packageIdentifier || identifier() != packageIdentifier) {
        x2w_note("x2w_gdk!XPackageMount", x2w::format("unknown package %s", packageIdentifier ? packageIdentifier : "(null)").c_str());
        return E_GAMEPACKAGE_NO_PACKAGE_IDENTIFIER;
    }
    auto* m = new XPackageMountObject;
    m->path = x2w::title_dir();
    *out = m;
    return S_OK;
}

const char mount_identity = 0;

struct MountOp : x2w::AsyncOp {
    std::string id;
    XPackageMountHandle handle = nullptr;
    explicit MountOp(const char* i) : id(i ? i : "") {}
    ~MountOp() override { delete handle; }
    HRESULT work() override { return mount(id.c_str(), &handle); }
    size_t result_size() override { return sizeof handle; }
    void get_result(void* buffer, size_t size) override
    {
        if (buffer && size >= sizeof handle) {
            *static_cast<XPackageMountHandle*>(buffer) = handle;
            handle = nullptr;
        }
    }
};

}  // namespace

extern "C" {

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackagegetcurrentprocesspackageidentifier
X2W_GDK_API HRESULT x2w_impl_XPackageGetCurrentProcessPackageIdentifier(size_t bufferSize, char* buffer) noexcept
{
    return copy_string(identifier(), bufferSize, buffer);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackageispackagedprocess
X2W_GDK_API bool x2w_impl_XPackageIsPackagedProcess(void) noexcept { return true; }

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackagegetuserlocale
X2W_GDK_API HRESULT x2w_impl_XPackageGetUserLocale(size_t localeSize, char* locale) noexcept
{
    wchar_t name[LOCALE_NAME_MAX_LENGTH];
    if (!GetUserDefaultLocaleName(name, LOCALE_NAME_MAX_LENGTH)) wcscpy_s(name, LOCALE_NAME_MAX_LENGTH, L"en-US");
    return copy_string(x2w::narrow(name), localeSize, locale);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackagemount
X2W_GDK_API HRESULT x2w_impl_XPackageMount(const char* packageIdentifier, XPackageMountHandle* mountHandle) noexcept
{
    return mount(packageIdentifier, mountHandle);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackagemountwithuiasync
X2W_GDK_API HRESULT x2w_impl_XPackageMountWithUiAsync(const char* packageIdentifier, XAsyncBlock* async) noexcept
{
    return x2w::async_start(async, &mount_identity, "XPackageMountWithUiAsync", new MountOp(packageIdentifier));
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackagemountwithuiresult
X2W_GDK_API HRESULT x2w_impl_XPackageMountWithUiResult(XAsyncBlock* async, XPackageMountHandle* mountHandle) noexcept
{
    if (!mountHandle) return E_POINTER;
    *mountHandle = nullptr;
    return x2w_impl_XAsyncGetResult(async, &mount_identity, sizeof *mountHandle, mountHandle, nullptr);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackagegetmountpathsize
X2W_GDK_API HRESULT x2w_impl_XPackageGetMountPathSize(XPackageMountHandle mountHandle, size_t* pathSize) noexcept
{
    if (!pathSize) return E_POINTER;
    *pathSize = 0;
    XPackageMountObject* m = valid(mountHandle);
    if (!m) return E_INVALIDARG;
    *pathSize = m->path.size() + 1;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackagegetmountpath
X2W_GDK_API HRESULT x2w_impl_XPackageGetMountPath(XPackageMountHandle mountHandle, size_t pathSize, char* path) noexcept
{
    XPackageMountObject* m = valid(mountHandle);
    if (!m) return E_INVALIDARG;
    return copy_string(m->path, pathSize, path);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackageclosemounthandle
X2W_GDK_API void x2w_impl_XPackageCloseMountHandle(XPackageMountHandle mountHandle) noexcept
{
    if (XPackageMountObject* m = valid(mountHandle)) {
        m->signature = 0;
        delete m;
    }
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackageenumeratepackages
X2W_GDK_API HRESULT x2w_impl_XPackageEnumeratePackages(XPackageKind kind, XPackageEnumerationScope scope, void* context,
                                                       XPackageEnumerationCallback* callback) noexcept
{
    (void)scope;
    if (!callback) return E_INVALIDARG;
    if (kind != XPackageKind::Game) return S_OK;  // no DLC or publisher content exists
    const std::string id = identifier(), name = x2w::title_name();
    XPackageDetails details{};
    details.packageIdentifier = id.c_str();
    details.version.major = 1;
    details.kind = XPackageKind::Game;
    details.displayName = name.c_str();
    details.description = "";
    details.publisher = "";
    details.storeId = "";
    details.installing = false;
    details.index = 0;
    details.count = 1;
    details.ageRestricted = false;
    details.titleID = "";
    callback(context, &details);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xpackage/functions/xpackagefindchunkavailability
X2W_GDK_API HRESULT x2w_impl_XPackageFindChunkAvailability(const char* packageIdentifier, uint32_t selectorCount,
                                                           XPackageChunkSelector* selectors,
                                                           XPackageChunkAvailability* availability) noexcept
{
    (void)packageIdentifier;
    (void)selectorCount;
    (void)selectors;
    if (!availability) return E_POINTER;
    *availability = XPackageChunkAvailability::Ready;
    return S_OK;
}

}  // extern "C"
