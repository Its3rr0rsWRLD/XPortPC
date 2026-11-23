// Source-built fixture for tools/shimgen.py and x2w_gdk.dll. It imports the generated shim's functions by
// the placeholder console DLL name x2w_shimgen_fixture.dll (tests/shimgen/fixture_manifest.json plus every
// spec, with tests/shimgen/fixture_override.toml), exactly as a title would import a console DLL, and
// exercises the family modules through it.
//
// Usage: shimgen_fixture SCENARIO
//   taskqueue  manual / thread pool / serialized / immediate queues, delayed callbacks, composite queues,
//              the process queue, waiters, monitors, termination
//   async      XAsyncRun, XAsyncBegin providers, status, result size, cancel, wait
//   user       XGameRuntimeInitialize, XUserAddAsync, gamertag, ids, lookups, XSystem answers
//   save       XGameSave round trip under a temporary X2W_SAVE_ROOT (sync and async), errors
//   package    XPackage identifier, mount path, enumeration, chunks
//   gameui     message dialog, text entry and error dialog completions
//   stubs      typed stubs (out-params zeroed, override return, first call logged once), untyped stubs,
//              an ordinal export, the forced stub
//   forward    X2W_FORWARD_DIR holding x2w_shimgen_fakepc.dll: the fixture family forwards
//   fallback   X2W_FORWARD_DIR without it: the same call falls back to its stub and logs why
// Exit code 0 on success; each failed check prints a line and the exit code is 1.
#include "x2w_shimgen_fixture_exports.h"

#include <atomic>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

extern "C" __declspec(dllimport) uintptr_t X2WFixtureUnknown();

namespace {

int failures = 0;
#define CHECK(cond)                                                                       \
    do {                                                                                  \
        if (!(cond)) {                                                                    \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                   \
            ++failures;                                                                   \
        }                                                                                 \
    } while (0)

// x2w_gdk.dll's test helpers, found at run time so the fixture's imports name only the placeholder DLL.
using SetSink = void (*)(void(__cdecl*)(const char*, const char*, const char*, void*), void*);
using Count = uint32_t (*)();
using First = size_t (*)(char*, size_t);
struct Helpers {
    SetSink set_sink;
    Count count;
    First first;
};
Helpers helpers()
{
    HMODULE gdk = GetModuleHandleW(L"x2w_gdk.dll");
    return {reinterpret_cast<SetSink>(GetProcAddress(gdk, "X2WShimSetLogSink")),
            reinterpret_cast<Count>(GetProcAddress(gdk, "X2WShimUnimplementedCount")),
            reinterpret_cast<First>(GetProcAddress(gdk, "X2WShimFirstUnimplemented"))};
}

std::vector<std::string> events;
SRWLOCK events_lock = SRWLOCK_INIT;
void __cdecl sink(const char* kind, const char* symbol, const char* detail, void*)
{
    AcquireSRWLockExclusive(&events_lock);
    events.push_back(std::string(kind) + " " + symbol + " " + detail);
    ReleaseSRWLockExclusive(&events_lock);
}
size_t count_events(const char* needle)
{
    AcquireSRWLockShared(&events_lock);
    size_t n = 0;
    for (const auto& e : events) n += e.find(needle) != std::string::npos;
    ReleaseSRWLockShared(&events_lock);
    return n;
}

// ---------------------------------------------------------------- taskqueue
struct Counter {
    std::atomic<int> calls{0};
    std::atomic<int> canceled{0};
    std::atomic<int> concurrent{0};
    std::atomic<int> max_concurrent{0};
    std::vector<int> order;
    SRWLOCK lock = SRWLOCK_INIT;
    DWORD thread = 0;
};

struct Tagged {
    Counter* counter;
    int tag;
};

void CALLBACK count_cb(void* context, bool canceled)
{
    auto* t = static_cast<Tagged*>(context);
    Counter* c = t->counter;
    const int now = c->concurrent.fetch_add(1) + 1;
    int seen = c->max_concurrent.load();
    while (now > seen && !c->max_concurrent.compare_exchange_weak(seen, now)) {
    }
    if (c->thread == 0) c->thread = GetCurrentThreadId();
    AcquireSRWLockExclusive(&c->lock);
    c->order.push_back(t->tag);
    ReleaseSRWLockExclusive(&c->lock);
    Sleep(1);
    (canceled ? c->canceled : c->calls).fetch_add(1);
    c->concurrent.fetch_sub(1);
}

bool wait_for(const std::atomic<int>& value, int target, DWORD ms = 5000)
{
    const ULONGLONG end = GetTickCount64() + ms;
    while (value.load() < target && GetTickCount64() < end) Sleep(1);
    return value.load() >= target;
}

void CALLBACK terminated_cb(void* context) { static_cast<std::atomic<int>*>(context)->fetch_add(1); }

struct MonitorState {
    std::atomic<int> hits{0};
    XTaskQueuePort last{XTaskQueuePort::Work};
};
void CALLBACK monitor_cb(void* context, XTaskQueueHandle, XTaskQueuePort port)
{
    auto* m = static_cast<MonitorState*>(context);
    m->last = port;
    m->hits.fetch_add(1);
}

void taskqueue()
{
    // Manual: nothing runs until dispatched; order is kept; dispatch on an empty port times out.
    {
        XTaskQueueHandle q = nullptr;
        CHECK(XTaskQueueCreate(XTaskQueueDispatchMode::Manual, XTaskQueueDispatchMode::Manual, &q) == S_OK && q);
        Counter c;
        Tagged t[3] = {{&c, 1}, {&c, 2}, {&c, 3}};
        MonitorState m;
        XTaskQueueRegistrationToken mt{};
        CHECK(XTaskQueueRegisterMonitor(q, &m, monitor_cb, &mt) == S_OK && mt.token);
        for (auto& x : t) CHECK(XTaskQueueSubmitCallback(q, XTaskQueuePort::Work, &x, count_cb) == S_OK);
        CHECK(m.hits == 3);
        Sleep(20);
        CHECK(c.calls == 0);
        CHECK(!XTaskQueueDispatch(q, XTaskQueuePort::Completion, 0));
        while (XTaskQueueDispatch(q, XTaskQueuePort::Work, 0)) {
        }
        CHECK(c.calls == 3);
        CHECK((c.order == std::vector<int>{1, 2, 3}));
        CHECK(c.thread == GetCurrentThreadId());
        const ULONGLONG start = GetTickCount64();
        CHECK(!XTaskQueueDispatch(q, XTaskQueuePort::Work, 50));
        CHECK(GetTickCount64() - start >= 40);
        // Delayed: waits in the timer, then a dispatch with a timeout picks it up.
        Tagged late{&c, 4};
        CHECK(XTaskQueueSubmitDelayedCallback(q, XTaskQueuePort::Completion, 30, &late, count_cb) == S_OK);
        CHECK(!XTaskQueueDispatch(q, XTaskQueuePort::Completion, 0));
        CHECK(XTaskQueueDispatch(q, XTaskQueuePort::Completion, 2000));
        CHECK(c.calls == 4);
        CHECK(m.last == XTaskQueuePort::Completion);
        XTaskQueueUnregisterMonitor(q, mt);
        // Termination cancels what is pending (canceled = true) and refuses new callbacks.
        Tagged pending{&c, 5}, delayed{&c, 6};
        XTaskQueueSubmitCallback(q, XTaskQueuePort::Work, &pending, count_cb);
        XTaskQueueSubmitDelayedCallback(q, XTaskQueuePort::Work, 60000, &delayed, count_cb);
        std::atomic<int> done{0};
        CHECK(XTaskQueueTerminate(q, true, &done, terminated_cb) == S_OK);
        CHECK(done == 1);
        CHECK(c.canceled == 2);
        CHECK(XTaskQueueSubmitCallback(q, XTaskQueuePort::Work, &pending, count_cb) == E_ABORT);
        XTaskQueueCloseHandle(q);
    }
    // ThreadPool: runs concurrently without dispatch.
    {
        XTaskQueueHandle q = nullptr;
        CHECK(XTaskQueueCreate(XTaskQueueDispatchMode::ThreadPool, XTaskQueueDispatchMode::ThreadPool, &q) == S_OK);
        Counter c;
        std::vector<Tagged> t(64, Tagged{&c, 0});
        for (auto& x : t) XTaskQueueSubmitCallback(q, XTaskQueuePort::Work, &x, count_cb);
        CHECK(wait_for(c.calls, 64));
        CHECK(c.max_concurrent >= 1);
        XTaskQueueCloseHandle(q);
    }
    // SerializedThreadPool: one at a time, in order.
    {
        XTaskQueueHandle q = nullptr;
        CHECK(XTaskQueueCreate(XTaskQueueDispatchMode::SerializedThreadPool, XTaskQueueDispatchMode::Immediate, &q) == S_OK);
        Counter c;
        std::vector<Tagged> t;
        for (int i = 0; i < 32; ++i) t.push_back(Tagged{&c, i});
        for (auto& x : t) XTaskQueueSubmitCallback(q, XTaskQueuePort::Work, &x, count_cb);
        CHECK(wait_for(c.calls, 32));
        CHECK(c.max_concurrent == 1);
        bool ordered = c.order.size() == 32;
        for (int i = 0; ordered && i < 32; ++i) ordered = c.order[static_cast<size_t>(i)] == i;
        CHECK(ordered);
        // Immediate: runs on the submitting thread before Submit returns.
        Counter ic;
        Tagged it{&ic, 1};
        CHECK(XTaskQueueSubmitCallback(q, XTaskQueuePort::Completion, &it, count_cb) == S_OK);
        CHECK(ic.calls == 1 && ic.thread == GetCurrentThreadId());
        // Duplicate keeps the queue alive after the first close.
        XTaskQueueHandle dup = nullptr;
        CHECK(XTaskQueueDuplicateHandle(q, &dup) == S_OK && dup);
        XTaskQueueCloseHandle(q);
        CHECK(XTaskQueueSubmitCallback(dup, XTaskQueuePort::Completion, &it, count_cb) == S_OK);
        CHECK(ic.calls == 2);
        XTaskQueueCloseHandle(dup);
    }
    // Composite queue over a manual queue's ports; terminating it leaves the ports' owner usable.
    {
        XTaskQueueHandle q = nullptr;
        XTaskQueueCreate(XTaskQueueDispatchMode::Manual, XTaskQueueDispatchMode::Manual, &q);
        XTaskQueuePortHandle work = nullptr, completion = nullptr;
        CHECK(XTaskQueueGetPort(q, XTaskQueuePort::Work, &work) == S_OK && work);
        CHECK(XTaskQueueGetPort(q, XTaskQueuePort::Completion, &completion) == S_OK && completion);
        XTaskQueueHandle composite = nullptr;
        CHECK(XTaskQueueCreateComposite(completion, work, &composite) == S_OK && composite);
        Counter c;
        Tagged x{&c, 1};
        CHECK(XTaskQueueSubmitCallback(composite, XTaskQueuePort::Work, &x, count_cb) == S_OK);
        CHECK(XTaskQueueDispatch(q, XTaskQueuePort::Completion, 0));  // composite's work = q's completion
        CHECK(c.calls == 1);
        CHECK(XTaskQueueTerminate(composite, true, nullptr, nullptr) == S_OK);
        CHECK(XTaskQueueSubmitCallback(q, XTaskQueuePort::Work, &x, count_cb) == S_OK);
        CHECK(XTaskQueueDispatch(q, XTaskQueuePort::Work, 0));
        XTaskQueueCloseHandle(composite);
        XTaskQueueCloseHandle(q);
    }
    // Waiter: fires once per signal of an auto-reset event.
    {
        XTaskQueueHandle q = nullptr;
        XTaskQueueCreate(XTaskQueueDispatchMode::ThreadPool, XTaskQueueDispatchMode::ThreadPool, &q);
        HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        Counter c;
        Tagged x{&c, 1};
        XTaskQueueRegistrationToken token{};
        CHECK(XTaskQueueRegisterWaiter(q, XTaskQueuePort::Work, event, &x, count_cb, &token) == S_OK && token.token);
        SetEvent(event);
        CHECK(wait_for(c.calls, 1));
        Sleep(20);
        SetEvent(event);
        CHECK(wait_for(c.calls, 2));
        XTaskQueueUnregisterWaiter(q, token);
        SetEvent(event);
        Sleep(50);
        CHECK(c.calls == 2);
        CloseHandle(event);
        XTaskQueueCloseHandle(q);
    }
    // The process queue: a null handle submits to it; it can be replaced and removed.
    {
        XTaskQueueHandle process = nullptr;
        CHECK(XTaskQueueGetCurrentProcessTaskQueue(&process) && process);
        Counter c;
        Tagged x{&c, 1};
        CHECK(XTaskQueueSubmitCallback(nullptr, XTaskQueuePort::Work, &x, count_cb) == S_OK);
        CHECK(wait_for(c.calls, 1));
        XTaskQueueHandle manual = nullptr;
        XTaskQueueCreate(XTaskQueueDispatchMode::Manual, XTaskQueueDispatchMode::Manual, &manual);
        XTaskQueueSetCurrentProcessTaskQueue(manual);
        CHECK(XTaskQueueSubmitCallback(nullptr, XTaskQueuePort::Work, &x, count_cb) == S_OK);
        CHECK(XTaskQueueDispatch(manual, XTaskQueuePort::Work, 0) && c.calls == 2);
        XTaskQueueSetCurrentProcessTaskQueue(nullptr);
        XTaskQueueHandle none = reinterpret_cast<XTaskQueueHandle>(1);
        CHECK(!XTaskQueueGetCurrentProcessTaskQueue(&none) && none == nullptr);
        XTaskQueueSetCurrentProcessTaskQueue(process);
        XTaskQueueCloseHandle(process);
        XTaskQueueCloseHandle(manual);
    }
    XTaskQueueHandle bad = nullptr;
    CHECK(XTaskQueueCreate(static_cast<XTaskQueueDispatchMode>(9), XTaskQueueDispatchMode::Manual, &bad) == E_INVALIDARG);
}

// ---------------------------------------------------------------- async
std::atomic<int> work_runs{0};
HRESULT CALLBACK work_ok(XAsyncBlock*) { work_runs.fetch_add(1); return S_OK; }
HRESULT CALLBACK work_fail(XAsyncBlock*) { return E_ACCESSDENIED; }
std::atomic<int> completions{0};
void CALLBACK on_complete(XAsyncBlock*) { completions.fetch_add(1); }

const char provider_identity = 0;
struct ProviderContext {
    std::atomic<int> cleanups{0};
    bool cancel_seen = false;
    uint32_t value = 0x1234;
};
HRESULT CALLBACK provider(XAsyncOp op, const XAsyncProviderData* data)
{
    auto* p = static_cast<ProviderContext*>(data->context);
    switch (op) {
    case XAsyncOp::Begin: return XAsyncSchedule(data->async, 0);
    case XAsyncOp::DoWork: XAsyncComplete(data->async, S_OK, sizeof p->value); return S_OK;
    case XAsyncOp::GetResult: memcpy(data->buffer, &p->value, sizeof p->value); return S_OK;
    case XAsyncOp::Cancel: p->cancel_seen = true; XAsyncComplete(data->async, E_ABORT, 0); return S_OK;
    case XAsyncOp::Cleanup: p->cleanups.fetch_add(1); return S_OK;
    }
    return S_OK;
}
HRESULT CALLBACK slow_provider(XAsyncOp op, const XAsyncProviderData* data)
{
    if (op == XAsyncOp::Begin) return XAsyncSchedule(data->async, 60000);  // never runs unless canceled
    return provider(op, data);
}

void async()
{
    XTaskQueueHandle q = nullptr;
    XTaskQueueCreate(XTaskQueueDispatchMode::Manual, XTaskQueueDispatchMode::Manual, &q);
    {
        XAsyncBlock block{};
        block.queue = q;
        block.callback = on_complete;
        CHECK(XAsyncRun(&block, work_ok) == S_OK);
        CHECK(XAsyncGetStatus(&block, false) == E_PENDING);
        CHECK(XTaskQueueDispatch(q, XTaskQueuePort::Work, 0) && work_runs == 1);
        CHECK(XAsyncGetStatus(&block, false) == S_OK);
        CHECK(completions == 0);  // the callback waits for the completion port
        CHECK(XTaskQueueDispatch(q, XTaskQueuePort::Completion, 0) && completions == 1);
        size_t size = 99;
        CHECK(XAsyncGetResultSize(&block, &size) == S_OK && size == 0);
        // Reuse after completion; a failing work item reports its HRESULT.
        CHECK(XAsyncRun(&block, work_fail) == S_OK);
        XTaskQueueDispatch(q, XTaskQueuePort::Work, 0);
        CHECK(XAsyncGetStatus(&block, false) == E_ACCESSDENIED);
        XTaskQueueDispatch(q, XTaskQueuePort::Completion, 0);
    }
    {
        ProviderContext ctx;
        XAsyncBlock block{};
        block.queue = q;
        CHECK(XAsyncBegin(&block, &ctx, &provider_identity, "fixture", provider) == S_OK);
        size_t size = 0;
        CHECK(XAsyncGetResultSize(&block, &size) == E_PENDING);
        XTaskQueueDispatch(q, XTaskQueuePort::Work, 0);
        CHECK(XAsyncGetResultSize(&block, &size) == S_OK && size == sizeof(uint32_t));
        uint32_t value = 0;
        size_t used = 0;
        CHECK(XAsyncGetResult(&block, &provider_identity, 1, &value, &used) == E_NOT_SUFFICIENT_BUFFER);
        CHECK(XAsyncGetResult(&block, nullptr, sizeof value, &value, &used) == E_INVALIDARG);
        CHECK(XAsyncGetResult(&block, &provider_identity, sizeof value, &value, &used) == S_OK);
        CHECK(value == 0x1234 && used == sizeof value && ctx.cleanups == 1);
    }
    {
        ProviderContext ctx;
        XAsyncBlock block{};
        block.queue = q;
        CHECK(XAsyncBegin(&block, &ctx, &provider_identity, "fixture", slow_provider) == S_OK);
        XAsyncCancel(&block);
        CHECK(ctx.cancel_seen && XAsyncGetStatus(&block, false) == E_ABORT && ctx.cleanups == 1);
    }
    XTaskQueueCloseHandle(q);
    {
        // Thread pool queue (null queue: the process queue) and a blocking wait.
        XAsyncBlock block{};
        CHECK(XAsyncRun(&block, work_ok) == S_OK);
        CHECK(XAsyncGetStatus(&block, true) == S_OK && work_runs == 2);
    }
}

// ---------------------------------------------------------------- user and system
void user()
{
    CHECK(XGameRuntimeInitialize() == S_OK);
    XAsyncBlock block{};
    CHECK(XUserAddAsync(XUserAddOptions::AddDefaultUserSilently, &block) == S_OK);
    CHECK(XAsyncGetStatus(&block, true) == S_OK);
    XUserHandle user = nullptr;
    CHECK(XUserAddResult(&block, &user) == S_OK && user);
    char tag[128] = {};
    size_t used = 0;
    CHECK(XUserGetGamertag(user, XUserGamertagComponent::Modern, sizeof tag, tag, &used) == S_OK);
    CHECK(std::strcmp(tag, "FixturePlayerWithALongName") == 0 && used == std::strlen(tag) + 1);
    CHECK(XUserGetGamertag(user, XUserGamertagComponent::Classic, sizeof tag, tag, &used) == S_OK);
    CHECK(std::strlen(tag) == 15 && used == 16);
    CHECK(XUserGetGamertag(user, XUserGamertagComponent::Modern, 4, tag, &used) == E_NOT_SUFFICIENT_BUFFER);
    uint64_t id = 0;
    CHECK(XUserGetId(user, &id) == S_OK && id == 4242);
    XUserLocalId local{};
    CHECK(XUserGetLocalId(user, &local) == S_OK && local.value != 0);
    XUserHandle found = nullptr, by_local = nullptr, dup = nullptr;
    CHECK(XUserFindUserById(4242, &found) == S_OK && found);
    CHECK(XUserFindUserByLocalId(local, &by_local) == S_OK && by_local);
    CHECK(XUserFindUserById(1, &dup) == static_cast<HRESULT>(0x80070490L) && dup == nullptr);
    CHECK(XUserDuplicateHandle(user, &dup) == S_OK && XUserCompare(user, dup) == 0 && XUserCompare(found, by_local) == 0);
    XUserState state = XUserState::SignedOut;
    bool guest = true, privilege = false;
    XUserAgeGroup age = XUserAgeGroup::Unknown;
    XUserPrivilegeDenyReason reason = XUserPrivilegeDenyReason::Unknown;
    CHECK(XUserGetState(user, &state) == S_OK && state == XUserState::SignedIn);
    CHECK(XUserGetIsGuest(user, &guest) == S_OK && !guest);
    CHECK(XUserGetAgeGroup(user, &age) == S_OK && age == XUserAgeGroup::Adult);
    CHECK(XUserCheckPrivilege(user, XUserPrivilegeOptions{}, XUserPrivilege{}, &privilege, &reason) == S_OK && privilege &&
          reason == XUserPrivilegeDenyReason::None);
    XTaskQueueRegistrationToken token{};
    CHECK(XUserRegisterForChangeEvent(nullptr, nullptr, [](void*, XUserLocalId, XUserChangeEvent) {}, &token) == S_OK);
    CHECK(XUserUnregisterForChangeEvent(token, true));
    XUserSignOutDeferralHandle deferral = nullptr;
    CHECK(XUserGetSignOutDeferral(&deferral) == E_GAMEUSER_DEFERRAL_NOT_AVAILABLE);
    for (XUserHandle h : {user, found, by_local, dup}) XUserCloseHandle(h);

    CHECK(XSystemGetDeviceType() == XSystemDeviceType::XboxScarlettAnaconda);
    char console[64] = {};
    CHECK(XSystemGetConsoleId(sizeof console, console, &used) == S_OK && used == 39);
    CHECK(std::strcmp(console, "00000000.00000000.00000000.00000000.00") == 0);
    CHECK(XSystemGetConsoleId(10, console, &used) == static_cast<HRESULT>(0x8007007AL));
    char sandbox[32] = {};
    CHECK(XSystemGetXboxLiveSandboxId(sizeof sandbox, sandbox, &used) == S_OK && std::strcmp(sandbox, "RETAIL") == 0);
    const XSystemAnalyticsInfo info = XSystemGetAnalyticsInfo();
    CHECK(std::strcmp(info.family, "Xbox") == 0 && info.osVersion.major >= 10);
    XGameRuntimeUninitialize();
}

// ---------------------------------------------------------------- save
struct Seen {
    std::vector<std::string> names;
    std::vector<uint32_t> sizes;
    uint64_t total = 0;
};
bool CALLBACK container_cb(const XGameSaveContainerInfo* info, void* context)
{
    auto* s = static_cast<Seen*>(context);
    s->names.push_back(std::string(info->name) + "|" + info->displayName + "|" + std::to_string(info->blobCount));
    s->total = info->totalSize;
    return true;
}
bool CALLBACK blob_cb(const XGameSaveBlobInfo* info, void* context)
{
    auto* s = static_cast<Seen*>(context);
    s->names.push_back(info->name);
    s->sizes.push_back(info->size);
    return true;
}

void save(const std::wstring& root)
{
    XGameSaveProviderHandle provider = nullptr;
    CHECK(XGameSaveInitializeProvider(nullptr, "00000000-0000-0000-0000-000000000000", false, &provider) == S_OK && provider);
    XGameSaveContainerHandle container = nullptr;
    CHECK(XGameSaveCreateContainer(provider, "bad name!", &container) == E_GS_INVALID_CONTAINER_NAME && !container);
    CHECK(XGameSaveCreateContainer(provider, "slot/1", &container) == S_OK && container);
    XGameSaveUpdateHandle update = nullptr;
    CHECK(XGameSaveCreateUpdate(container, "Slot One", &update) == S_OK && update);
    const std::string a = "first blob", b(70000, 'z');
    CHECK(XGameSaveSubmitBlobWrite(update, "profile.dat", reinterpret_cast<const uint8_t*>(a.data()), a.size()) == S_OK);
    CHECK(XGameSaveSubmitBlobWrite(update, "world", reinterpret_cast<const uint8_t*>(b.data()), b.size()) == S_OK);
    CHECK(XGameSaveSubmitUpdate(update) == S_OK);
    XGameSaveCloseUpdate(update);
    XGameSaveCloseContainer(container);
    XGameSaveCloseProvider(provider);

    // The files are where the docs/design/runtime.md layout says.
    const std::wstring dir = root + L"\\shimgen_fixture_title\\slot%2F1";
    CHECK(GetFileAttributesW((dir + L"\\profile%2Edat.blob").c_str()) != INVALID_FILE_ATTRIBUTES);
    CHECK(GetFileAttributesW((dir + L"\\world.blob").c_str()) != INVALID_FILE_ATTRIBUTES);

    // Reopen through the async provider and read everything back.
    XAsyncBlock block{};
    CHECK(XGameSaveInitializeProviderAsync(nullptr, "scid", false, &block) == S_OK);
    CHECK(XAsyncGetStatus(&block, true) == S_OK);
    CHECK(XGameSaveInitializeProviderResult(&block, &provider) == S_OK && provider);
    Seen containers;
    CHECK(XGameSaveEnumerateContainerInfo(provider, &containers, container_cb) == S_OK);
    CHECK(containers.names.size() == 1 && containers.names[0] == "slot/1|Slot One|2");
    CHECK(containers.total == a.size() + b.size());
    Seen prefixed;
    CHECK(XGameSaveEnumerateContainerInfoByName(provider, "other", &prefixed, container_cb) == S_OK && prefixed.names.empty());
    int64_t quota = 0;
    CHECK(XGameSaveGetRemainingQuota(provider, &quota) == S_OK && quota > 0);
    CHECK(XGameSaveCreateContainer(provider, "slot/1", &container) == S_OK);
    Seen blobs;
    CHECK(XGameSaveEnumerateBlobInfo(container, &blobs, blob_cb) == S_OK);
    CHECK((blobs.names == std::vector<std::string>{"profile.dat", "world"}));
    CHECK((blobs.sizes == std::vector<uint32_t>{static_cast<uint32_t>(a.size()), static_cast<uint32_t>(b.size())}));

    size_t size = 2 * sizeof(XGameSaveBlob) + a.size() + b.size();
    std::vector<uint8_t> buffer(size);
    auto* out = reinterpret_cast<XGameSaveBlob*>(buffer.data());
    uint32_t count = 0;
    CHECK(XGameSaveReadBlobData(container, nullptr, &count, size - 1, out) == E_GS_PROVIDED_BUFFER_TOO_SMALL);
    CHECK(XGameSaveReadBlobData(container, nullptr, &count, size, out) == S_OK && count == 2);
    CHECK(std::strcmp(out[0].info.name, "profile.dat") == 0 && out[0].info.size == a.size());
    CHECK(std::memcmp(out[0].data, a.data(), a.size()) == 0 && std::memcmp(out[1].data, b.data(), b.size()) == 0);
    const char* one[] = {"world"};
    count = 1;
    CHECK(XGameSaveReadBlobData(container, one, &count, size, out) == S_OK && count == 1 && out[0].info.size == b.size());
    const char* missing[] = {"nope"};
    count = 1;
    CHECK(XGameSaveReadBlobData(container, missing, &count, size, out) == E_GS_BLOB_NOT_FOUND);

    // Async read, then delete one blob asynchronously.
    XAsyncBlock read{};
    const char* first[] = {"profile.dat"};
    CHECK(XGameSaveReadBlobDataAsync(container, first, 1, &read) == S_OK);
    CHECK(XAsyncGetStatus(&read, true) == S_OK);
    size_t needed = 0;
    CHECK(XAsyncGetResultSize(&read, &needed) == S_OK && needed == sizeof(XGameSaveBlob) + a.size());
    count = 0;
    CHECK(XGameSaveReadBlobDataResult(&read, needed, out, &count) == S_OK && count == 1);
    CHECK(std::memcmp(out[0].data, a.data(), a.size()) == 0);
    CHECK(XGameSaveCreateUpdate(container, "", &update) == S_OK);
    CHECK(XGameSaveSubmitBlobDelete(update, "world") == S_OK);
    XAsyncBlock submit{};
    CHECK(XGameSaveSubmitUpdateAsync(update, &submit) == S_OK);
    CHECK(XAsyncGetStatus(&submit, true) == S_OK && XGameSaveSubmitUpdateResult(&submit) == S_OK);
    XGameSaveCloseUpdate(update);
    Seen after;
    XGameSaveEnumerateBlobInfo(container, &after, blob_cb);
    CHECK((after.names == std::vector<std::string>{"profile.dat"}));
    XGameSaveCloseContainer(container);

    XAsyncBlock del{};
    CHECK(XGameSaveDeleteContainerAsync(provider, "slot/1", &del) == S_OK);
    CHECK(XAsyncGetStatus(&del, true) == S_OK && XGameSaveDeleteContainerResult(&del) == S_OK);
    Seen none;
    XGameSaveEnumerateContainerInfo(provider, &none, container_cb);
    CHECK(none.names.empty());
    XGameSaveCloseProvider(provider);
}

// ---------------------------------------------------------------- package
bool CALLBACK package_cb(void* context, const XPackageDetails* details)
{
    auto* s = static_cast<Seen*>(context);
    s->names.push_back(details->packageIdentifier);
    return true;
}

void package(const std::string& title_dir)
{
    char id[64] = {};
    CHECK(XPackageGetCurrentProcessPackageIdentifier(sizeof id, id) == S_OK);
    CHECK(std::strcmp(id, "x2w.shimgen_fixture_title") == 0);
    CHECK(XPackageGetCurrentProcessPackageIdentifier(4, id) == static_cast<HRESULT>(0x8007007AL));
    std::strcpy(id, "x2w.shimgen_fixture_title");
    CHECK(XPackageIsPackagedProcess());
    char locale[LOCALE_NAME_MAX_LENGTH] = {};
    CHECK(XPackageGetUserLocale(sizeof locale, locale) == S_OK && locale[0]);
    XPackageMountHandle mount = nullptr;
    CHECK(XPackageMount("someone.else", &mount) == E_GAMEPACKAGE_NO_PACKAGE_IDENTIFIER && !mount);
    CHECK(XPackageMount(id, &mount) == S_OK && mount);
    size_t size = 0;
    CHECK(XPackageGetMountPathSize(mount, &size) == S_OK && size == title_dir.size() + 1);
    std::string path(size, '\0');
    CHECK(XPackageGetMountPath(mount, size, path.data()) == S_OK && std::strcmp(path.c_str(), title_dir.c_str()) == 0);
    XPackageCloseMountHandle(mount);
    XAsyncBlock block{};
    CHECK(XPackageMountWithUiAsync(id, &block) == S_OK && XAsyncGetStatus(&block, true) == S_OK);
    CHECK(XPackageMountWithUiResult(&block, &mount) == S_OK && mount);
    XPackageCloseMountHandle(mount);
    Seen games, dlc;
    CHECK(XPackageEnumeratePackages(XPackageKind::Game, XPackageEnumerationScope::ThisOnly, &games, package_cb) == S_OK);
    CHECK(games.names.size() == 1 && games.names[0] == id);
    CHECK(XPackageEnumeratePackages(XPackageKind::Content, XPackageEnumerationScope::ThisAndRelated, &dlc, package_cb) == S_OK);
    CHECK(dlc.names.empty());
    XPackageChunkAvailability availability = XPackageChunkAvailability::Unavailable;
    CHECK(XPackageFindChunkAvailability(id, 0, nullptr, &availability) == S_OK && availability == XPackageChunkAvailability::Ready);
}

// ---------------------------------------------------------------- gameui
void gameui()
{
    XAsyncBlock block{};
    CHECK(XGameUiShowMessageDialogAsync(&block, "t", "c", "a", "b", nullptr, XGameUiMessageDialogButton::Second,
                                        XGameUiMessageDialogButton::First) == S_OK);
    XAsyncGetStatus(&block, true);
    XGameUiMessageDialogButton button = XGameUiMessageDialogButton::First;
    CHECK(XGameUiShowMessageDialogResult(&block, &button) == S_OK && button == XGameUiMessageDialogButton::Second);
    XAsyncBlock text{};
    CHECK(XGameUiShowTextEntryAsync(&text, "t", "d", "default text", XGameUiTextEntryInputScope{}, 7) == S_OK);
    XAsyncGetStatus(&text, true);
    uint32_t size = 0, used = 0;
    CHECK(XGameUiShowTextEntryResultSize(&text, &size) == S_OK && size == 8);
    char buffer[16] = {};
    CHECK(XGameUiShowTextEntryResult(&text, sizeof buffer, buffer, &used) == S_OK && used == 8);
    CHECK(std::strcmp(buffer, "default") == 0);
    XAsyncBlock error{};
    CHECK(XGameUiShowErrorDialogAsync(&error, E_FAIL, nullptr) == S_OK);
    CHECK(XAsyncGetStatus(&error, true) == S_OK && XGameUiShowErrorDialogResult(&error) == S_OK);
}

// ---------------------------------------------------------------- stubs
void stubs()
{
    Helpers h = helpers();
    CHECK(h.set_sink && h.count && h.first);
    if (!h.set_sink) return;
    h.set_sink(sink, nullptr);
    const uint32_t before = h.count();
    // A typed stub with out-params and an out-buffer: zeroed, E_NOTIMPL, logged once.
    char id[8];
    std::memset(id, 'x', sizeof id);
    size_t used = 77;
    CHECK(XSystemGetAppSpecificDeviceId(sizeof id, id, &used) == E_NOTIMPL);
    CHECK(XSystemGetAppSpecificDeviceId(sizeof id, id, &used) == E_NOTIMPL);
    CHECK(used == 0 && id[0] == 0 && id[7] == 0);
    CHECK(count_events("x2w_shimgen_fixture!XSystemGetAppSpecificDeviceId stub returns E_NOTIMPL, first caller shimgen_fixture.exe+0x") == 1);
    // Override: a stub with its own return value; a spec'd implementation forced to a stub.
    uint32_t value = 5;
    CHECK(X2WFixtureOverridden(&value) == S_FALSE && value == 0);
    uint32_t max = 9;
    CHECK(XUserGetMaxUsers(&max) == E_GAMEUSER_NO_DEFAULT_USER && max == 0);
    // Untyped stubs: 0, or E_NOTIMPL for an *Async name.
    CHECK(X2WFixtureUnknown() == 0);
    using Untyped = uintptr_t (*)();
    HMODULE shim = GetModuleHandleW(L"x2w_shimgen_fixture.dll");
    auto async_stub = reinterpret_cast<Untyped>(GetProcAddress(shim, "XUserGetTokenAndSignatureAsync"));
    CHECK(async_stub && static_cast<HRESULT>(async_stub()) == E_NOTIMPL);
    auto ordinal = reinterpret_cast<Untyped>(GetProcAddress(shim, MAKEINTRESOURCEA(7)));
    CHECK(ordinal && ordinal() == 0);
    CHECK(count_events("x2w_shimgen_fixture!#7 untyped stub returns 0") == 1);
    CHECK(GetProcAddress(shim, "x2w_shimgen_dll") != nullptr);
    CHECK(h.count() == before + 6);
    char first[256] = {};
    h.first(first, sizeof first);
    CHECK(std::strstr(first, "x2w_shimgen_fixture!XSystemGetAppSpecificDeviceId") == first);
    h.set_sink(nullptr, nullptr);
}

void forward(bool available)
{
    Helpers h = helpers();
    if (h.set_sink) h.set_sink(sink, nullptr);
    if (available) {
        CHECK(X2WFixtureForwarded(6, 7) == 43);  // x2w_shimgen_fakepc.dll: a * b + 1
        CHECK(count_events("forward x2w_gdk!forward.fixture to ") == 1);
        // The fake DLL lacks this one, so it falls back to its stub.
        uint32_t value = 1;
        CHECK(X2WFixtureOverridden(&value) == S_FALSE);
        CHECK(count_events("lacks X2WFixtureOverridden, using the fallback") == 1);
    } else {
        CHECK(X2WFixtureForwarded(6, 7) == -1);
        CHECK(count_events("not loadable") == 1);
    }
    // Families whose forwarding is off by default never forward.
    CHECK(XSystemGetDeviceType() == XSystemDeviceType::XboxScarlettAnaconda);
    if (h.set_sink) h.set_sink(nullptr, nullptr);
}

std::wstring temp_dir(const wchar_t* leaf)
{
    wchar_t base[MAX_PATH];
    GetTempPathW(MAX_PATH, base);
    std::wstring dir = std::wstring(base) + L"x2w_shimgen_" + leaf + L"_" + std::to_wstring(GetCurrentProcessId());
    CreateDirectoryW(dir.c_str(), nullptr);
    return dir;
}

std::string exe_dir()
{
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    std::string dir = path;
    return dir.substr(0, dir.find_last_of("\\/"));
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc < 2) {
        std::printf("usage: shimgen_fixture SCENARIO\n");
        return 2;
    }
    const std::string scenario = argv[1];
    // Environment for the family modules, set before their first use.
    SetEnvironmentVariableW(L"X2W_TITLE", L"shimgen_fixture_title");
    const std::string title_dir = exe_dir() + "\\title-folder";
    SetEnvironmentVariableA("X2W_TITLE_DIR", title_dir.c_str());
    SetEnvironmentVariableW(L"X2W_GAMERTAG", L"FixturePlayerWithALongName");
    SetEnvironmentVariableW(L"X2W_USER_ID", L"4242");
    const std::wstring save_root = temp_dir(L"saves");
    SetEnvironmentVariableW(L"X2W_SAVE_ROOT", save_root.c_str());
    if (scenario == "forward") SetEnvironmentVariableA("X2W_FORWARD_DIR", exe_dir().c_str());
    if (scenario == "fallback") SetEnvironmentVariableW(L"X2W_FORWARD_DIR", temp_dir(L"empty").c_str());

    if (scenario == "taskqueue") taskqueue();
    else if (scenario == "async") async();
    else if (scenario == "user") user();
    else if (scenario == "save") save(save_root);
    else if (scenario == "package") package(title_dir);
    else if (scenario == "gameui") gameui();
    else if (scenario == "stubs") stubs();
    else if (scenario == "forward") forward(true);
    else if (scenario == "fallback") forward(false);
    else {
        std::printf("unknown scenario %s\n", scenario.c_str());
        return 2;
    }
    std::printf("%s: %s (%d failure%s)\n", scenario.c_str(), failures ? "FAIL" : "ok", failures, failures == 1 ? "" : "s");
    return failures ? 1 : 0;
}
