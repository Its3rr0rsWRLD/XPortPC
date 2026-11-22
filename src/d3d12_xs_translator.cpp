// Translator service client of the graphics shim (d3d12_xs_translator.h).
//
// Like the rest of the shim, nothing here has a dynamic initializer or thread-local storage: the pool's state is
// constant-initialized and guarded by one SRW lock.
#include "d3d12_xs_translator.h"

#include <cstdio>
#include <cstring>
#include <new>

namespace d3d12_xs {
namespace translator {
namespace {

constexpr std::uint32_t ready_magic = 0x54573258u;  // "X2WT"
constexpr std::uint32_t protocol_version = 1;
constexpr DWORD wait_limit_ms = 300000;  // as the per-process path's limit
constexpr unsigned spawn_failures_to_give_up = 2;

struct Job {
    std::uint32_t stage = 0;
    std::vector<std::uint8_t> code;
    std::string roles;
    bool want_hlsl = false;
    Result result;
    bool done = false;
    bool queued = false;
    unsigned refs = 2;  // the caller and the queue/worker; changed under g_lock
    Job* next = nullptr;
};

struct Service {
    HANDLE process = nullptr;
    HANDLE to_service = nullptr;    // its stdin
    HANDLE from_service = nullptr;  // its stdout
};

SRWLOCK g_lock = SRWLOCK_INIT;
CONDITION_VARIABLE g_work = CONDITION_VARIABLE_INIT;  // a job was queued
CONDITION_VARIABLE g_done = CONDITION_VARIABLE_INIT;  // a job finished, or the pool changed
Settings* g_settings;
Job* g_head;
Job* g_tail;
unsigned g_services;  // running or starting
unsigned g_starting;
unsigned g_idle;
unsigned g_failures;  // consecutive start-up failures
bool g_broken;        // no service can run in this process
std::string* g_broken_why;
HANDLE g_job_object;

void release_locked(Job* job)
{
    if (--job->refs == 0) delete job;
}

Job* pop_locked()
{
    Job* job = g_head;
    if (job) {
        g_head = job->next;
        if (!g_head) g_tail = nullptr;
        job->next = nullptr;
        job->queued = false;
    }
    return job;
}

void remove_locked(Job* job)
{
    Job** at = &g_head;
    Job* previous = nullptr;
    while (*at && *at != job) {
        previous = *at;
        at = &(*at)->next;
    }
    if (!*at) return;
    *at = job->next;
    if (g_tail == job) g_tail = previous;
    job->next = nullptr;
    job->queued = false;
}

unsigned queued_locked()
{
    unsigned n = 0;
    for (Job* job = g_head; job; job = job->next) ++n;
    return n;
}

// With no service left and none possible, every queued job is answered `unavailable`.
void fail_queue_locked(const std::string& why)
{
    while (Job* job = pop_locked()) {
        job->result.status = unavailable;
        job->result.message = why;
        job->done = true;
        release_locked(job);
    }
    WakeAllConditionVariable(&g_done);
}

void give_up_locked(const std::string& why)
{
    g_broken = true;
    if (!g_broken_why) g_broken_why = new (std::nothrow) std::string(why);
    if (g_services == 0) fail_queue_locked(why);
}

// --- pipe I/O ---------------------------------------------------------------------------------------------------

bool read_all(HANDLE pipe, void* data, std::size_t size)
{
    auto* p = static_cast<std::uint8_t*>(data);
    while (size) {
        DWORD got = 0;
        const DWORD want = size > 0x10000000 ? 0x10000000 : static_cast<DWORD>(size);
        if (!ReadFile(pipe, p, want, &got, nullptr) || !got) return false;
        p += got;
        size -= got;
    }
    return true;
}

bool write_all(HANDLE pipe, const void* data, std::size_t size)
{
    const auto* p = static_cast<const std::uint8_t*>(data);
    while (size) {
        DWORD put = 0;
        const DWORD want = size > 0x10000000 ? 0x10000000 : static_cast<DWORD>(size);
        if (!WriteFile(pipe, p, want, &put, nullptr) || !put) return false;
        p += put;
        size -= put;
    }
    return true;
}

bool read_frame(HANDLE pipe, std::vector<std::uint8_t>& frame)
{
    std::uint32_t size = 0;
    if (!read_all(pipe, &size, 4) || size > (256u << 20)) return false;
    frame.resize(size);
    return !size || read_all(pipe, frame.data(), size);
}

void put_u32(std::vector<std::uint8_t>& out, std::uint32_t value)
{
    const auto* p = reinterpret_cast<const std::uint8_t*>(&value);
    out.insert(out.end(), p, p + 4);
}

void put_bytes(std::vector<std::uint8_t>& out, const void* data, std::size_t size)
{
    put_u32(out, static_cast<std::uint32_t>(size));
    const auto* p = static_cast<const std::uint8_t*>(data);
    out.insert(out.end(), p, p + size);
}

struct Cursor {
    const std::vector<std::uint8_t>& data;
    std::size_t at = 0;
    bool good = true;
    std::uint32_t u32()
    {
        std::uint32_t value = 0;
        if (at + 4 > data.size()) {
            good = false;
            return 0;
        }
        std::memcpy(&value, data.data() + at, 4);
        at += 4;
        return value;
    }
    template <class Out>
    void bytes(Out& out)
    {
        const std::uint32_t size = u32();
        if (!good || at + size > data.size()) {
            good = false;
            return;
        }
        out.assign(data.begin() + static_cast<std::ptrdiff_t>(at), data.begin() + static_cast<std::ptrdiff_t>(at + size));
        at += size;
    }
};

// One request and its response; false when the service failed (then it is not used again).
bool exchange(const Service& service, Job& job)
{
    std::vector<std::uint8_t> frame;
    put_u32(frame, 0);
    put_u32(frame, job.stage);
    put_u32(frame, job.want_hlsl ? 1u : 0u);
    put_bytes(frame, job.roles.data(), job.roles.size());
    put_bytes(frame, job.code.data(), job.code.size());
    const std::uint32_t payload = static_cast<std::uint32_t>(frame.size() - 4);
    std::memcpy(frame.data(), &payload, 4);
    std::vector<std::uint8_t> reply;
    if (!write_all(service.to_service, frame.data(), frame.size()) || !read_frame(service.from_service, reply)) {
        return false;
    }
    Cursor in{reply};
    const std::uint32_t status = in.u32();
    in.u32();  // instruction count
    in.bytes(job.result.message);
    in.bytes(job.result.dxil);
    in.bytes(job.result.hlsl);
    if (!in.good || status > tool_failure) return false;
    job.result.status = static_cast<int>(status);
    return true;
}

// --- service processes ------------------------------------------------------------------------------------------

void close_service(Service& s)
{
    if (s.to_service) CloseHandle(s.to_service);
    if (s.from_service) CloseHandle(s.from_service);
    if (s.process) {
        // Its stdin is closed, so a healthy service exits by itself; a hung one is stopped.
        if (WaitForSingleObject(s.process, 2000) != WAIT_OBJECT_0) TerminateProcess(s.process, 2);
        CloseHandle(s.process);
    }
    s = Service{};
}

HANDLE job_object()
{
    // Created under g_lock by the caller.
    if (!g_job_object) {
        HANDLE job = CreateJobObjectW(nullptr, nullptr);
        if (job) {
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits));
            g_job_object = job;
        } else {
            g_job_object = INVALID_HANDLE_VALUE;
        }
    }
    return g_job_object == INVALID_HANDLE_VALUE ? nullptr : g_job_object;
}

bool start_process(const Settings& c, HANDLE job, Service& out, std::string& why)
{
    SECURITY_ATTRIBUTES inherit{sizeof(inherit), nullptr, TRUE};
    HANDLE child_in = nullptr, child_out = nullptr, nul = INVALID_HANDLE_VALUE;
    Service s{};
    bool good = CreatePipe(&child_in, &s.to_service, &inherit, 0) && CreatePipe(&s.from_service, &child_out, &inherit, 0);
    if (good) {
        SetHandleInformation(s.to_service, HANDLE_FLAG_INHERIT, 0);
        SetHandleInformation(s.from_service, HANDLE_FLAG_INHERIT, 0);
        nul = CreateFileW(L"NUL", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, &inherit, OPEN_EXISTING, 0, nullptr);
        good = nul != INVALID_HANDLE_VALUE;
    }
    SIZE_T list_bytes = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &list_bytes);
    std::vector<std::uint8_t> list_storage(list_bytes);
    auto* list = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(list_storage.data());
    HANDLE handles[3] = {child_in, child_out, nul};
    good = good && InitializeProcThreadAttributeList(list, 1, 0, &list_bytes) &&
           UpdateProcThreadAttribute(list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handles, sizeof(handles), nullptr,
                                     nullptr);
    if (good) {
        // Bytecode cached outside the converter's directory: start-up then skips compiling the converter's modules.
        const std::wstring flags = c.pycache.empty() ? L"-B" : L"-X \"pycache_prefix=" + c.pycache + L"\"";
        std::wstring command = L"\"" + c.python + L"\" " + flags + L" \"" + c.tools + L"\\pso_service.py\" --dxc \"" +
                               c.dxc + L"\"";
        if (!c.llvm.empty()) command += L" --llvm \"" + c.llvm + L"\"";
        if (!c.scratch.empty()) command += L" --scratch \"" + c.scratch + L"\"";
        std::vector<wchar_t> line(command.begin(), command.end());
        line.push_back(0);
        STARTUPINFOEXW startup{};
        startup.StartupInfo.cb = sizeof(startup);
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = child_in;
        startup.StartupInfo.hStdOutput = child_out;
        startup.StartupInfo.hStdError = nul;
        startup.lpAttributeList = list;
        PROCESS_INFORMATION process{};
        good = CreateProcessW(nullptr, line.data(), nullptr, nullptr, TRUE,
                              CREATE_NO_WINDOW | CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT, nullptr, nullptr,
                              &startup.StartupInfo, &process) != FALSE;
        if (good) {
            if (job) AssignProcessToJobObject(job, process.hProcess);
            ResumeThread(process.hThread);
            CloseHandle(process.hThread);
            s.process = process.hProcess;
        } else {
            char text[64];
            std::snprintf(text, sizeof(text), "cannot start the translator service (error %lu)", GetLastError());
            why = text;
        }
        DeleteProcThreadAttributeList(list);
    } else if (why.empty()) {
        why = "cannot create the translator service's pipes";
    }
    if (child_in) CloseHandle(child_in);
    if (child_out) CloseHandle(child_out);
    if (nul != INVALID_HANDLE_VALUE) CloseHandle(nul);
    if (!good) {
        close_service(s);
        return false;
    }
    out = s;
    return true;
}

void spawn(unsigned count);
unsigned plan_locked();

DWORD WINAPI service_thread(void* parameter)
{
    Service service = *static_cast<Service*>(parameter);
    delete static_cast<Service*>(parameter);
    // The service writes one ready frame once the converter is imported and DXC is loaded.
    std::vector<std::uint8_t> ready;
    bool alive = read_frame(service.from_service, ready);
    if (alive) {
        Cursor in{ready};
        alive = in.u32() == ready_magic && in.u32() == protocol_version && in.good;
    }
    AcquireSRWLockExclusive(&g_lock);
    --g_starting;
    if (!alive) {
        --g_services;
        if (++g_failures >= spawn_failures_to_give_up) give_up_locked("the translator service did not start");
        WakeAllConditionVariable(&g_done);
        const unsigned replace = plan_locked();
        ReleaseSRWLockExclusive(&g_lock);
        close_service(service);
        spawn(replace);
        return 0;
    }
    g_failures = 0;
    for (;;) {
        ++g_idle;
        while (!g_head) SleepConditionVariableSRW(&g_work, &g_lock, INFINITE, 0);
        --g_idle;
        Job* job = pop_locked();
        ReleaseSRWLockExclusive(&g_lock);
        alive = exchange(service, *job);
        AcquireSRWLockExclusive(&g_lock);
        if (!alive) {
            job->result = Result{};
            job->result.message = "the translator service failed during the request";
        }
        job->done = true;
        release_locked(job);
        WakeAllConditionVariable(&g_done);
        if (!alive) break;
    }
    --g_services;
    // The queue is served by the others, or by a replacement.
    const unsigned replace = plan_locked();
    ReleaseSRWLockExclusive(&g_lock);
    close_service(service);
    spawn(replace);
    return 0;
}

// Starts `count` services; the caller has already counted them in g_services and g_starting.
void spawn(unsigned count)
{
    for (unsigned i = 0; i < count; ++i) {
        AcquireSRWLockExclusive(&g_lock);
        HANDLE job = job_object();
        ReleaseSRWLockExclusive(&g_lock);
        Service s{};
        std::string why;
        auto* parameter = start_process(*g_settings, job, s, why) ? new (std::nothrow) Service(s) : nullptr;
        HANDLE thread = parameter ? CreateThread(nullptr, 64 * 1024, service_thread, parameter, 0, nullptr) : nullptr;
        if (thread) {
            CloseHandle(thread);
            continue;
        }
        if (parameter) {
            close_service(*parameter);
            delete parameter;
            why = "cannot start the translator service's thread";
        }
        AcquireSRWLockExclusive(&g_lock);
        --g_services;
        --g_starting;
        give_up_locked(why.empty() ? "cannot start the translator service" : why);
        WakeAllConditionVariable(&g_done);
        ReleaseSRWLockExclusive(&g_lock);
    }
}

// How many services to start now for the queue (under g_lock); counts them as starting.
unsigned plan_locked()
{
    if (g_broken || !g_settings) return 0;
    const unsigned waiting = queued_locked();
    const unsigned ready_soon = g_idle + g_starting;
    unsigned need = waiting > ready_soon ? waiting - ready_soon : 0;
    if (g_services == 0 && waiting == 0) need = 0;
    const unsigned room = g_settings->max_services > g_services ? g_settings->max_services - g_services : 0;
    if (need > room) need = room;
    g_services += need;
    g_starting += need;
    return need;
}

}  // namespace

void configure(const Settings& settings)
{
    AcquireSRWLockExclusive(&g_lock);
    if (!g_settings) {
        g_settings = new (std::nothrow) Settings(settings);
        if (g_settings && g_settings->max_services == 0) give_up_locked("translator service disabled");
        // The shim's threads run in this DLL until the process exits: keep it loaded.
        HMODULE self = nullptr;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                           reinterpret_cast<LPCWSTR>(&configure), &self);
    }
    ReleaseSRWLockExclusive(&g_lock);
}

void prestart()
{
    AcquireSRWLockExclusive(&g_lock);
    unsigned start = 0;
    if (g_settings && !g_broken && g_services == 0) {
        start = 1;
        ++g_services;
        ++g_starting;
    }
    ReleaseSRWLockExclusive(&g_lock);
    spawn(start);
}

void translate(const Request* requests, Result* results, std::size_t count)
{
    std::vector<Job*> jobs;
    AcquireSRWLockExclusive(&g_lock);
    if (!g_settings || g_broken) {
        const std::string why = g_broken_why ? *g_broken_why : "no translator service";
        ReleaseSRWLockExclusive(&g_lock);
        for (std::size_t i = 0; i < count; ++i) {
            results[i] = Result{};
            results[i].message = why;
        }
        return;
    }
    for (std::size_t i = 0; i < count; ++i) {
        Job* job = new (std::nothrow) Job();
        if (job) {
            job->stage = requests[i].stage;
            job->code.assign(requests[i].code, requests[i].code + requests[i].code_bytes);
            job->roles = requests[i].roles;
            job->want_hlsl = requests[i].want_hlsl;
            job->queued = true;
            if (g_tail) g_tail->next = job; else g_head = job;
            g_tail = job;
        }
        jobs.push_back(job);
    }
    WakeAllConditionVariable(&g_work);
    const unsigned start = plan_locked();
    ReleaseSRWLockExclusive(&g_lock);
    spawn(start);

    const ULONGLONG deadline = GetTickCount64() + wait_limit_ms;
    AcquireSRWLockExclusive(&g_lock);
    for (std::size_t i = 0; i < count; ++i) {
        Job* job = jobs[i];
        results[i] = Result{};
        if (!job) {
            results[i].message = "out of memory";
            continue;
        }
        while (!job->done) {
            const ULONGLONG now = GetTickCount64();
            if (now >= deadline) break;
            SleepConditionVariableSRW(&g_done, &g_lock, static_cast<DWORD>(deadline - now), 0);
        }
        if (job->done) {
            results[i] = std::move(job->result);
        } else {
            // Abandoned: still queued (taken out) or in a service (the worker frees it when it ends).
            if (job->queued) {
                remove_locked(job);
                release_locked(job);
            }
            results[i].message = "the translator service did not answer within 300 s";
        }
        release_locked(job);
    }
    ReleaseSRWLockExclusive(&g_lock);
}

}  // namespace translator
}  // namespace d3d12_xs
