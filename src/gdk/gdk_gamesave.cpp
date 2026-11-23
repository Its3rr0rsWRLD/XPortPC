// XGameSave over local folders.
// Public reference: https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/xgamesave_members
//
// Layout: <X2W_SAVE_ROOT or %LOCALAPPDATA%\XPortPC\saves>\<title>\<container>\<blob>.blob, plus
// x2w.container holding the display name. Container and blob names are stored percent-encoded (every
// character but letters, digits, '_' and '-'), so '/' and '.' never reach the file system. A container
// exists once an update to it has been submitted, as with the service. Saves are per title, not per user
// (there is one offline user). Each blob write goes to a temporary file that replaces the old one, so a
// crash leaves either version of a blob; an update of several blobs is not atomic as a whole.
// Never in sync trouble: needsSync is always false and syncOnDemand is ignored.
#include "gdk_internal.h"

#include <algorithm>
#include <cstring>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace {

constexpr uint32_t provider_signature = 0x31505358;   // "XSP1"
constexpr uint32_t container_signature = 0x31435358;  // "XSC1"
constexpr uint32_t update_signature = 0x31555358;     // "XSU1"
constexpr int64_t quota_bytes = 256ll * 1024 * 1024;  // our own figure; the service's quota is per title

struct Blob {
    std::string name;
    uint32_t size;
};

}  // namespace

struct XGameSaveProviderObject {
    uint32_t signature = provider_signature;
    std::wstring root;
};

struct XGameSaveContainerObject {
    uint32_t signature = container_signature;
    std::wstring root;
    std::wstring dir;
    std::string name;
    SRWLOCK lock = SRWLOCK_INIT;
    std::set<std::string> names;  // stable storage for the name pointers handed out
};

struct XGameSaveUpdateObject {
    uint32_t signature = update_signature;
    XGameSaveContainerObject* container = nullptr;
    std::string display;
    struct Op {
        std::string blob;
        bool remove;
        std::vector<uint8_t> data;
    };
    std::vector<Op> ops;
};

namespace {

XGameSaveProviderObject* valid(XGameSaveProviderHandle h) { return h && h->signature == provider_signature ? h : nullptr; }
XGameSaveContainerObject* valid(XGameSaveContainerHandle h) { return h && h->signature == container_signature ? h : nullptr; }
XGameSaveUpdateObject* valid(XGameSaveUpdateHandle h) { return h && h->signature == update_signature ? h : nullptr; }

// "letters, digits, underscores, and forward slashes" (E_GS_INVALID_CONTAINER_NAME).
bool valid_container_name(const char* name)
{
    if (!name || !*name || strlen(name) > 256) return false;
    for (const char* c = name; *c; ++c) {
        const bool ok = (*c >= 'A' && *c <= 'Z') || (*c >= 'a' && *c <= 'z') || (*c >= '0' && *c <= '9') ||
                        *c == '_' || *c == '/';
        if (!ok) return false;
    }
    return true;
}

std::wstring encode(const std::string& name)
{
    std::wstring out;
    for (const unsigned char c : name) {
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-') {
            out += static_cast<wchar_t>(c);
        } else {
            wchar_t hex[4];
            swprintf(hex, 4, L"%%%02X", c);
            out += hex;
        }
    }
    return out;
}

bool decode(const std::wstring& text, std::string* out)
{
    out->clear();
    for (size_t i = 0; i < text.size(); ++i) {
        const wchar_t c = text[i];
        if (c == L'%') {
            if (i + 2 >= text.size()) return false;
            const std::wstring hex = text.substr(i + 1, 2);
            wchar_t* end = nullptr;
            const unsigned long value = wcstoul(hex.c_str(), &end, 16);
            if (!end || *end) return false;
            *out += static_cast<char>(value);
            i += 2;
        } else if (c < 128) {
            *out += static_cast<char>(c);
        } else {
            return false;
        }
    }
    return true;
}

bool make_dirs(const std::wstring& path)
{
    if (path.empty()) return false;
    if (CreateDirectoryW(path.c_str(), nullptr) || GetLastError() == ERROR_ALREADY_EXISTS) return true;
    const auto slash = path.find_last_of(L"\\/");
    if (slash == std::wstring::npos || slash < 3) return false;
    if (!make_dirs(path.substr(0, slash))) return false;
    return CreateDirectoryW(path.c_str(), nullptr) || GetLastError() == ERROR_ALREADY_EXISTS;
}

bool is_dir(const std::wstring& path)
{
    const DWORD a = GetFileAttributesW(path.c_str());
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}

std::vector<Blob> list_blobs(const std::wstring& dir, uint64_t* total = nullptr, time_t* modified = nullptr)
{
    std::vector<Blob> blobs;
    if (total) *total = 0;
    if (modified) *modified = 0;
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW((dir + L"\\*.blob").c_str(), &data);
    if (find == INVALID_HANDLE_VALUE) return blobs;
    do {
        if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        std::wstring file = data.cFileName;
        file.resize(file.size() - 5);
        std::string name;
        if (!decode(file, &name)) continue;
        blobs.push_back(Blob{name, data.nFileSizeLow});
        if (total) *total += data.nFileSizeLow;
        if (modified) {
            ULARGE_INTEGER t;
            t.LowPart = data.ftLastWriteTime.dwLowDateTime;
            t.HighPart = data.ftLastWriteTime.dwHighDateTime;
            const time_t unix = static_cast<time_t>((t.QuadPart - 116444736000000000ull) / 10000000ull);
            if (unix > *modified) *modified = unix;
        }
    } while (FindNextFileW(find, &data));
    FindClose(find);
    std::sort(blobs.begin(), blobs.end(), [](const Blob& a, const Blob& b) { return a.name < b.name; });
    return blobs;
}

std::string read_text(const std::wstring& path)
{
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (file == INVALID_HANDLE_VALUE) return {};
    char buffer[1024];
    DWORD read = 0;
    ReadFile(file, buffer, sizeof buffer, &read, nullptr);
    CloseHandle(file);
    return std::string(buffer, read);
}

bool read_file(const std::wstring& path, uint8_t* out, uint32_t size)
{
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD read = 0;
    const BOOL ok = ReadFile(file, out, size, &read, nullptr);
    CloseHandle(file);
    return ok && read == size;
}

bool write_file(const std::wstring& path, const void* data, size_t size)
{
    const std::wstring temp = path + L".tmp";
    HANDLE file = CreateFileW(temp.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    const BOOL ok = size == 0 || WriteFile(file, data, static_cast<DWORD>(size), &written, nullptr);
    FlushFileBuffers(file);
    CloseHandle(file);
    if (!ok || written != size) {
        DeleteFileW(temp.c_str());
        return false;
    }
    return MoveFileExW(temp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
}

uint64_t used_bytes(const std::wstring& root)
{
    uint64_t total = 0;
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW((root + L"\\*").c_str(), &data);
    if (find == INVALID_HANDLE_VALUE) return 0;
    do {
        if ((data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && data.cFileName[0] != L'.') {
            uint64_t size = 0;
            list_blobs(root + L"\\" + data.cFileName, &size);
            total += size;
        }
    } while (FindNextFileW(find, &data));
    FindClose(find);
    return total;
}

// Calls back with each container whose name starts with prefix (all when prefix is null). Returns false
// if the callback stopped the enumeration.
void enumerate_containers(const std::wstring& root, const char* prefix, const char* exact, void* context,
                          XGameSaveContainerInfoCallback* callback)
{
    std::vector<std::pair<std::string, std::wstring>> found;
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW((root + L"\\*").c_str(), &data);
    if (find != INVALID_HANDLE_VALUE) {
        do {
            if (!(data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || data.cFileName[0] == L'.') continue;
            std::string name;
            if (!decode(data.cFileName, &name)) continue;
            if (exact && name != exact) continue;
            if (prefix && name.compare(0, strlen(prefix), prefix) != 0) continue;
            found.emplace_back(name, root + L"\\" + data.cFileName);
        } while (FindNextFileW(find, &data));
        FindClose(find);
    }
    std::sort(found.begin(), found.end());
    for (const auto& [name, dir] : found) {
        uint64_t total = 0;
        time_t modified = 0;
        const std::vector<Blob> blobs = list_blobs(dir, &total, &modified);
        const std::string display = read_text(dir + L"\\x2w.container");
        XGameSaveContainerInfo info{};
        info.name = name.c_str();
        info.displayName = display.c_str();
        info.blobCount = static_cast<uint32_t>(blobs.size());
        info.totalSize = total;
        info.lastModifiedTime = modified;
        info.needsSync = false;
        if (!callback(&info, context)) break;
    }
}

const char* intern(XGameSaveContainerObject* c, const std::string& name)
{
    AcquireSRWLockExclusive(&c->lock);
    const char* text = c->names.insert(name).first->c_str();
    ReleaseSRWLockExclusive(&c->lock);
    return text;
}

// The blobs a read returns, in order. names null: every blob in the container.
HRESULT select_blobs(XGameSaveContainerObject* c, const char** names, uint32_t count, std::vector<Blob>* out)
{
    const std::vector<Blob> all = list_blobs(c->dir);
    out->clear();
    if (!names) {
        *out = all;
        return S_OK;
    }
    for (uint32_t i = 0; i < count; ++i) {
        if (!names[i]) return E_INVALIDARG;
        auto it = std::find_if(all.begin(), all.end(), [&](const Blob& b) { return b.name == names[i]; });
        if (it == all.end()) return E_GS_BLOB_NOT_FOUND;
        out->push_back(*it);
    }
    return S_OK;
}

size_t required_size(const std::vector<Blob>& blobs)
{
    size_t size = blobs.size() * sizeof(XGameSaveBlob);
    for (const Blob& b : blobs) size += b.size;
    return size;
}

// Lays the blobs out as XGameSaveBlob[count] followed by their data.
HRESULT fill(XGameSaveContainerObject* c, const std::vector<Blob>& blobs,
             const std::vector<std::vector<uint8_t>>* contents, size_t size, XGameSaveBlob* out)
{
    if (!out || size < required_size(blobs)) return E_GS_PROVIDED_BUFFER_TOO_SMALL;
    uint8_t* data = reinterpret_cast<uint8_t*>(out + blobs.size());
    for (size_t i = 0; i < blobs.size(); ++i) {
        out[i].info.name = intern(c, blobs[i].name);
        out[i].info.size = blobs[i].size;
        out[i].data = data;
        if (contents) {
            memcpy(data, (*contents)[i].data(), blobs[i].size);
        } else if (!read_file(c->dir + L"\\" + encode(blobs[i].name) + L".blob", data, blobs[i].size)) {
            return E_GS_BLOB_NOT_FOUND;
        }
        data += blobs[i].size;
    }
    return S_OK;
}

HRESULT submit(XGameSaveUpdateObject* u)
{
    XGameSaveContainerObject* c = u->container;
    size_t bytes = 0;
    for (const auto& op : u->ops) bytes += op.data.size();
    if (bytes > GS_MAX_BLOB_SIZE) return E_GS_UPDATE_TOO_BIG;
    if (static_cast<int64_t>(used_bytes(c->root) + bytes) > quota_bytes) return E_GS_QUOTA_EXCEEDED;
    if (!make_dirs(c->dir)) return E_GS_OUT_OF_LOCAL_STORAGE;
    if (!u->display.empty() || GetFileAttributesW((c->dir + L"\\x2w.container").c_str()) == INVALID_FILE_ATTRIBUTES)
        write_file(c->dir + L"\\x2w.container", u->display.data(), u->display.size());
    for (const auto& op : u->ops) {
        const std::wstring path = c->dir + L"\\" + encode(op.blob) + L".blob";
        if (op.remove) {
            DeleteFileW(path.c_str());
        } else if (!write_file(path, op.data.data(), op.data.size())) {
            return E_GS_OUT_OF_LOCAL_STORAGE;
        }
    }
    return S_OK;
}

void delete_tree(const std::wstring& dir)
{
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW((dir + L"\\*").c_str(), &data);
    if (find != INVALID_HANDLE_VALUE) {
        do {
            if (data.cFileName[0] == L'.') continue;
            DeleteFileW((dir + L"\\" + data.cFileName).c_str());
        } while (FindNextFileW(find, &data));
        FindClose(find);
    }
    RemoveDirectoryW(dir.c_str());
}

HRESULT delete_container(XGameSaveProviderObject* p, const char* name)
{
    if (!valid_container_name(name)) return E_GS_INVALID_CONTAINER_NAME;
    const std::wstring dir = p->root + L"\\" + encode(name);
    if (is_dir(dir)) delete_tree(dir);  // deleting a missing container succeeds (the page does not say)
    return S_OK;
}

HRESULT open_provider(XGameSaveProviderHandle* provider)
{
    auto* p = new XGameSaveProviderObject;
    p->root = x2w::save_dir();
    if (!make_dirs(p->root)) {
        delete p;
        x2w_unimplemented("x2w_gdk!XGameSaveInitializeProvider", "cannot create the save folder");
        return E_GS_OUT_OF_LOCAL_STORAGE;
    }
    x2w_note("x2w_gdk!XGameSaveInitializeProvider", ("local saves in " + x2w::narrow(p->root)).c_str());
    *provider = p;
    return S_OK;
}

// ---------------------------------------------------------------- async operations
const char init_identity = 0, quota_identity = 0, delete_identity = 0, read_identity = 0, submit_identity = 0;

struct InitOp : x2w::AsyncOp {
    XGameSaveProviderHandle provider = nullptr;
    ~InitOp() override
    {
        if (provider) delete provider;  // never handed out
    }
    HRESULT work() override { return open_provider(&provider); }
    size_t result_size() override { return sizeof provider; }
    void get_result(void* buffer, size_t size) override
    {
        if (buffer && size >= sizeof provider) {
            *static_cast<XGameSaveProviderHandle*>(buffer) = provider;
            provider = nullptr;
        }
    }
};

struct QuotaOp : x2w::AsyncOp {
    XGameSaveProviderObject* provider;
    int64_t quota = 0;
    explicit QuotaOp(XGameSaveProviderObject* p) : provider(p) {}
    HRESULT work() override
    {
        quota = quota_bytes - static_cast<int64_t>(used_bytes(provider->root));
        if (quota < 0) quota = 0;
        return S_OK;
    }
    size_t result_size() override { return sizeof quota; }
    void get_result(void* buffer, size_t size) override
    {
        if (buffer && size >= sizeof quota) memcpy(buffer, &quota, sizeof quota);
    }
};

struct DeleteOp : x2w::AsyncOp {
    XGameSaveProviderObject* provider;
    std::string name;
    DeleteOp(XGameSaveProviderObject* p, const char* n) : provider(p), name(n ? n : "") {}
    HRESULT work() override { return delete_container(provider, name.c_str()); }
};

struct ReadOp : x2w::AsyncOp {
    XGameSaveContainerObject* container;
    std::vector<std::string> requested;
    bool all;
    std::vector<Blob> blobs;
    std::vector<std::vector<uint8_t>> contents;
    ReadOp(XGameSaveContainerObject* c, const char** names, uint32_t count) : container(c), all(!names)
    {
        for (uint32_t i = 0; names && i < count; ++i) requested.push_back(names[i] ? names[i] : "");
    }
    HRESULT work() override
    {
        std::vector<const char*> names;
        for (const auto& n : requested) names.push_back(n.c_str());
        HRESULT hr = select_blobs(container, all ? nullptr : names.data(), static_cast<uint32_t>(names.size()), &blobs);
        if (FAILED(hr)) return hr;
        for (const Blob& b : blobs) {
            contents.emplace_back(b.size);
            if (!read_file(container->dir + L"\\" + encode(b.name) + L".blob", contents.back().data(), b.size))
                return E_GS_BLOB_NOT_FOUND;
        }
        return S_OK;
    }
    size_t result_size() override { return required_size(blobs); }
};

struct SubmitOp : x2w::AsyncOp {
    XGameSaveUpdateObject* update;
    explicit SubmitOp(XGameSaveUpdateObject* u) : update(u) {}
    HRESULT work() override { return submit(update); }
};

HRESULT no_payload(XAsyncBlock* async, const void* identity)
{
    return x2w::async_finish(async, identity, [](x2w::AsyncOp*) { return S_OK; });
}

}  // namespace

extern "C" {

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesaveinitializeprovider
X2W_GDK_API HRESULT x2w_impl_XGameSaveInitializeProvider(XUserHandle requestingUser, const char* configurationId,
                                                         bool syncOnDemand, XGameSaveProviderHandle* provider) noexcept
{
    (void)requestingUser;
    (void)configurationId;
    (void)syncOnDemand;
    if (!provider) return E_POINTER;
    *provider = nullptr;
    return open_provider(provider);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesaveinitializeproviderasync
X2W_GDK_API HRESULT x2w_impl_XGameSaveInitializeProviderAsync(XUserHandle requestingUser, const char* configurationId,
                                                              bool syncOnDemand, XAsyncBlock* async) noexcept
{
    (void)requestingUser;
    (void)configurationId;
    (void)syncOnDemand;
    return x2w::async_start(async, &init_identity, "XGameSaveInitializeProviderAsync", new InitOp);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesaveinitializeproviderresult
X2W_GDK_API HRESULT x2w_impl_XGameSaveInitializeProviderResult(XAsyncBlock* async, XGameSaveProviderHandle* provider) noexcept
{
    if (!provider) return E_POINTER;
    *provider = nullptr;
    return x2w_impl_XAsyncGetResult(async, &init_identity, sizeof *provider, provider, nullptr);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavecloseprovider
X2W_GDK_API void x2w_impl_XGameSaveCloseProvider(XGameSaveProviderHandle provider) noexcept
{
    if (XGameSaveProviderObject* p = valid(provider)) {
        p->signature = 0;
        delete p;
    }
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavegetremainingquota
X2W_GDK_API HRESULT x2w_impl_XGameSaveGetRemainingQuota(XGameSaveProviderHandle provider, int64_t* remainingQuota) noexcept
{
    if (!remainingQuota) return E_POINTER;
    *remainingQuota = 0;
    XGameSaveProviderObject* p = valid(provider);
    if (!p) return E_INVALIDARG;
    QuotaOp op(p);
    op.work();
    *remainingQuota = op.quota;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavegetremainingquotaasync
X2W_GDK_API HRESULT x2w_impl_XGameSaveGetRemainingQuotaAsync(XGameSaveProviderHandle provider, XAsyncBlock* async) noexcept
{
    XGameSaveProviderObject* p = valid(provider);
    if (!p) return E_INVALIDARG;
    return x2w::async_start(async, &quota_identity, "XGameSaveGetRemainingQuotaAsync", new QuotaOp(p));
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavegetremainingquotaresult
X2W_GDK_API HRESULT x2w_impl_XGameSaveGetRemainingQuotaResult(XAsyncBlock* async, int64_t* remainingQuota) noexcept
{
    if (!remainingQuota) return E_POINTER;
    *remainingQuota = 0;
    return x2w_impl_XAsyncGetResult(async, &quota_identity, sizeof *remainingQuota, remainingQuota, nullptr);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavedeletecontainer
X2W_GDK_API HRESULT x2w_impl_XGameSaveDeleteContainer(XGameSaveProviderHandle provider, const char* containerName) noexcept
{
    XGameSaveProviderObject* p = valid(provider);
    if (!p) return E_INVALIDARG;
    return delete_container(p, containerName);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavedeletecontainerasync
X2W_GDK_API HRESULT x2w_impl_XGameSaveDeleteContainerAsync(XGameSaveProviderHandle provider, const char* containerName,
                                                           XAsyncBlock* async) noexcept
{
    XGameSaveProviderObject* p = valid(provider);
    if (!p) return E_INVALIDARG;
    return x2w::async_start(async, &delete_identity, "XGameSaveDeleteContainerAsync", new DeleteOp(p, containerName));
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavedeletecontainerresult
X2W_GDK_API HRESULT x2w_impl_XGameSaveDeleteContainerResult(XAsyncBlock* async) noexcept
{
    return no_payload(async, &delete_identity);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavecreatecontainer
X2W_GDK_API HRESULT x2w_impl_XGameSaveCreateContainer(XGameSaveProviderHandle provider, const char* containerName,
                                                      XGameSaveContainerHandle* containerContext) noexcept
{
    if (!containerContext) return E_POINTER;
    *containerContext = nullptr;
    XGameSaveProviderObject* p = valid(provider);
    if (!p) return E_INVALIDARG;
    if (!valid_container_name(containerName)) return E_GS_INVALID_CONTAINER_NAME;
    auto* c = new XGameSaveContainerObject;
    c->root = p->root;
    c->name = containerName;
    c->dir = p->root + L"\\" + encode(containerName);
    *containerContext = c;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesaveclosecontainer
X2W_GDK_API void x2w_impl_XGameSaveCloseContainer(XGameSaveContainerHandle context) noexcept
{
    if (XGameSaveContainerObject* c = valid(context)) {
        c->signature = 0;
        delete c;
    }
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavegetcontainerinfo
// A missing container: the callback is not called and S_OK is returned (the page does not say).
X2W_GDK_API HRESULT x2w_impl_XGameSaveGetContainerInfo(XGameSaveProviderHandle provider, const char* containerName,
                                                       void* context, XGameSaveContainerInfoCallback* callback) noexcept
{
    XGameSaveProviderObject* p = valid(provider);
    if (!p || !callback) return E_INVALIDARG;
    if (!valid_container_name(containerName)) return E_GS_INVALID_CONTAINER_NAME;
    enumerate_containers(p->root, nullptr, containerName, context, callback);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesaveenumeratecontainerinfo
X2W_GDK_API HRESULT x2w_impl_XGameSaveEnumerateContainerInfo(XGameSaveProviderHandle provider, void* context,
                                                             XGameSaveContainerInfoCallback* callback) noexcept
{
    XGameSaveProviderObject* p = valid(provider);
    if (!p || !callback) return E_INVALIDARG;
    enumerate_containers(p->root, nullptr, nullptr, context, callback);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesaveenumeratecontainerinfobyname
X2W_GDK_API HRESULT x2w_impl_XGameSaveEnumerateContainerInfoByName(XGameSaveProviderHandle provider,
                                                                   const char* containerNamePrefix, void* context,
                                                                   XGameSaveContainerInfoCallback* callback) noexcept
{
    XGameSaveProviderObject* p = valid(provider);
    if (!p || !callback) return E_INVALIDARG;
    enumerate_containers(p->root, containerNamePrefix ? containerNamePrefix : "", nullptr, context, callback);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesaveenumerateblobinfo
X2W_GDK_API HRESULT x2w_impl_XGameSaveEnumerateBlobInfo(XGameSaveContainerHandle container, void* context,
                                                        XGameSaveBlobInfoCallback* callback) noexcept
{
    return x2w_impl_XGameSaveEnumerateBlobInfoByName(container, "", context, callback);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesaveenumerateblobinfobyname
X2W_GDK_API HRESULT x2w_impl_XGameSaveEnumerateBlobInfoByName(XGameSaveContainerHandle container,
                                                              const char* blobNamePrefix, void* context,
                                                              XGameSaveBlobInfoCallback* callback) noexcept
{
    XGameSaveContainerObject* c = valid(container);
    if (!c || !callback) return E_INVALIDARG;
    const std::string prefix = blobNamePrefix ? blobNamePrefix : "";
    for (const Blob& blob : list_blobs(c->dir)) {
        if (blob.name.compare(0, prefix.size(), prefix) != 0) continue;
        const XGameSaveBlobInfo info{intern(c, blob.name), blob.size};
        if (!callback(&info, context)) break;
    }
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavereadblobdata
// Buffer layout (the page leaves it open): XGameSaveBlob[count], then the blobs' bytes, so the size the
// public sample computes (sizeof(XGameSaveBlob) + size per blob) is enough. Name pointers stay valid until
// the container is closed. blobNames null reads every blob.
X2W_GDK_API HRESULT x2w_impl_XGameSaveReadBlobData(XGameSaveContainerHandle container, const char** blobNames,
                                                   uint32_t* countOfBlobs, size_t blobsSize, XGameSaveBlob* blobData) noexcept
{
    XGameSaveContainerObject* c = valid(container);
    if (!c || !countOfBlobs) return E_INVALIDARG;
    std::vector<Blob> blobs;
    HRESULT hr = select_blobs(c, blobNames, *countOfBlobs, &blobs);
    if (FAILED(hr)) return hr;
    hr = fill(c, blobs, nullptr, blobsSize, blobData);
    if (SUCCEEDED(hr)) *countOfBlobs = static_cast<uint32_t>(blobs.size());
    return hr;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavereadblobdataasync
X2W_GDK_API HRESULT x2w_impl_XGameSaveReadBlobDataAsync(XGameSaveContainerHandle container, const char** blobNames,
                                                        uint32_t countOfBlobs, XAsyncBlock* async) noexcept
{
    XGameSaveContainerObject* c = valid(container);
    if (!c) return E_INVALIDARG;
    return x2w::async_start(async, &read_identity, "XGameSaveReadBlobDataAsync", new ReadOp(c, blobNames, countOfBlobs));
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavereadblobdataresult
X2W_GDK_API HRESULT x2w_impl_XGameSaveReadBlobDataResult(XAsyncBlock* async, size_t blobsSize, XGameSaveBlob* blobData,
                                                         uint32_t* countOfBlobs) noexcept
{
    if (!countOfBlobs) return E_POINTER;
    *countOfBlobs = 0;
    return x2w::async_finish(async, &read_identity, [&](x2w::AsyncOp* op) -> HRESULT {
        auto* read = static_cast<ReadOp*>(op);
        if (!read) return E_UNEXPECTED;
        const HRESULT hr = fill(read->container, read->blobs, &read->contents, blobsSize, blobData);
        if (SUCCEEDED(hr)) *countOfBlobs = static_cast<uint32_t>(read->blobs.size());
        return hr;
    });
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavecreateupdate
X2W_GDK_API HRESULT x2w_impl_XGameSaveCreateUpdate(XGameSaveContainerHandle container, const char* containerDisplayName,
                                                   XGameSaveUpdateHandle* updateContext) noexcept
{
    if (!updateContext) return E_POINTER;
    *updateContext = nullptr;
    XGameSaveContainerObject* c = valid(container);
    if (!c) return E_INVALIDARG;
    auto* u = new XGameSaveUpdateObject;
    u->container = c;
    u->display = containerDisplayName ? containerDisplayName : "";
    *updateContext = u;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavecloseupdate
X2W_GDK_API void x2w_impl_XGameSaveCloseUpdate(XGameSaveUpdateHandle context) noexcept
{
    if (XGameSaveUpdateObject* u = valid(context)) {
        u->signature = 0;
        delete u;
    }
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavesubmitblobwrite
X2W_GDK_API HRESULT x2w_impl_XGameSaveSubmitBlobWrite(XGameSaveUpdateHandle updateContext, const char* blobName,
                                                      const uint8_t* data, size_t byteCount) noexcept
{
    XGameSaveUpdateObject* u = valid(updateContext);
    if (!u || !blobName || !*blobName || (byteCount && !data)) return E_INVALIDARG;
    if (byteCount > GS_MAX_BLOB_SIZE) return E_GS_UPDATE_TOO_BIG;
    u->ops.push_back(XGameSaveUpdateObject::Op{blobName, false, std::vector<uint8_t>(data, data + byteCount)});
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavesubmitblobdelete
X2W_GDK_API HRESULT x2w_impl_XGameSaveSubmitBlobDelete(XGameSaveUpdateHandle updateContext, const char* blobName) noexcept
{
    XGameSaveUpdateObject* u = valid(updateContext);
    if (!u || !blobName || !*blobName) return E_INVALIDARG;
    u->ops.push_back(XGameSaveUpdateObject::Op{blobName, true, {}});
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavesubmitupdate
X2W_GDK_API HRESULT x2w_impl_XGameSaveSubmitUpdate(XGameSaveUpdateHandle updateContext) noexcept
{
    XGameSaveUpdateObject* u = valid(updateContext);
    if (!u) return E_INVALIDARG;
    return submit(u);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavesubmitupdateasync
X2W_GDK_API HRESULT x2w_impl_XGameSaveSubmitUpdateAsync(XGameSaveUpdateHandle updateContext, XAsyncBlock* async) noexcept
{
    XGameSaveUpdateObject* u = valid(updateContext);
    if (!u) return E_INVALIDARG;
    return x2w::async_start(async, &submit_identity, "XGameSaveSubmitUpdateAsync", new SubmitOp(u));
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgamesave/functions/xgamesavesubmitupdateresult
X2W_GDK_API HRESULT x2w_impl_XGameSaveSubmitUpdateResult(XAsyncBlock* async) noexcept
{
    return no_payload(async, &submit_identity);
}

}  // extern "C"
