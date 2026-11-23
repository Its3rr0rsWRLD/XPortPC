// XTaskQueue over the Windows thread pool.
// Behavior follows the public libHttpClient XTaskQueue.h comments (MIT) and the GDK reference
// (https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/xtaskqueue_members):
//   Manual: callbacks wait for XTaskQueueDispatch. ThreadPool: run on the thread pool, concurrently.
//   SerializedThreadPool: run on the thread pool one at a time, in order. Immediate: run on the
//   submitting thread. A null queue handle means the process task queue (by default ThreadPool for both
//   ports; XTaskQueueSetCurrentProcessTaskQueue(nullptr) removes it). Terminate cancels pending callbacks
//   (they run with canceled = true), refuses new ones with E_ABORT and then calls the termination callback;
//   a composite queue's termination leaves the ports it borrowed alone. Closing the last handle terminates
//   the queue without waiting.
// Our choices where the comments are silent, all logged nowhere because they are not failures:
//   canceled callbacks of a terminated queue run on the terminating thread; a waiter fires once per
//   signal and is re-armed after its callback has run; delayed callbacks count as pending until queued.
#include "gdk_internal.h"

#include <atomic>
#include <deque>
#include <map>
#include <vector>

namespace {

constexpr uint32_t queue_signature = 0x31515458;  // "XTQ1"
constexpr uint32_t port_signature = 0x31505458;   // "XTP1"

struct Port;
struct Queue;

struct Waiter {
    std::atomic<long> refs{1};
    uint64_t token = 0;
    Port* port = nullptr;
    Queue* queue = nullptr;
    HANDLE handle = nullptr;
    XTaskQueueCallback* callback = nullptr;
    void* context = nullptr;
    PTP_WAIT wait = nullptr;
    SRWLOCK lock = SRWLOCK_INIT;
    bool registered = true;
};

struct Entry {
    XTaskQueueCallback* callback;
    void* context;
    Waiter* waiter;  // re-armed after the callback; holds a reference
};

struct Timer {
    Port* port;
    Queue* queue;
    Entry entry;
    PTP_TIMER timer;
};

struct Port {
    uint32_t signature = port_signature;
    XTaskQueueDispatchMode mode;
    std::atomic<long> refs{1};
    SRWLOCK lock = SRWLOCK_INIT;
    CONDITION_VARIABLE changed = CONDITION_VARIABLE_INIT;
    std::deque<Entry> pending;
    std::vector<Timer*> timers;
    long inflight = 0;  // thread pool work items, dispatches in progress and armed timers
    bool serial_running = false;
    bool terminated = false;
};

struct Monitor {
    uint64_t token;
    XTaskQueueMonitorCallback* callback;
    void* context;
};

struct Queue {
    uint32_t signature = queue_signature;
    std::atomic<long> handles{1};
    std::atomic<long> refs{1};
    Port* ports[2] = {};
    bool owns[2] = {};
    std::atomic<bool> terminated{false};
    SRWLOCK lock = SRWLOCK_INIT;
    std::vector<Monitor> monitors;
    std::vector<Waiter*> waiters;
    std::atomic<long> monitor_calls{0};
};

std::atomic<uint64_t> g_token{0};

void port_addref(Port* port) { port->refs.fetch_add(1); }
void port_release(Port* port)
{
    if (port->refs.fetch_sub(1) == 1) delete port;
}
void queue_addref(Queue* queue) { queue->refs.fetch_add(1); }
void queue_release(Queue* queue)
{
    if (queue->refs.fetch_sub(1) == 1) {
        for (int i = 0; i < 2; ++i)
            if (queue->ports[i]) port_release(queue->ports[i]);
        queue->signature = 0;
        delete queue;
    }
}
void waiter_release(Waiter* waiter)
{
    if (waiter->refs.fetch_sub(1) == 1) delete waiter;
}

Queue* valid_queue(XTaskQueueHandle handle)
{
    auto* queue = reinterpret_cast<Queue*>(handle);
    return queue && queue->signature == queue_signature ? queue : nullptr;
}

Port* valid_port(XTaskQueuePortHandle handle)
{
    auto* port = reinterpret_cast<Port*>(handle);
    return port && port->signature == port_signature ? port : nullptr;
}

bool valid_mode(XTaskQueueDispatchMode mode) { return static_cast<uint32_t>(mode) <= 3; }
bool valid_port_index(XTaskQueuePort port) { return static_cast<uint32_t>(port) <= 1; }

// ---------------------------------------------------------------- process task queue
SRWLOCK g_process_lock = SRWLOCK_INIT;
Queue* g_process = nullptr;
bool g_process_cleared = false;

Queue* create_queue(XTaskQueueDispatchMode work, XTaskQueueDispatchMode completion)
{
    auto* queue = new Queue;
    const XTaskQueueDispatchMode modes[2] = {work, completion};
    for (int i = 0; i < 2; ++i) {
        queue->ports[i] = new Port;
        queue->ports[i]->mode = modes[i];
        queue->owns[i] = true;
    }
    return queue;
}

// A referenced queue for a handle (null: the process queue), or null.
Queue* acquire(XTaskQueueHandle handle)
{
    if (handle) {
        Queue* queue = valid_queue(handle);
        if (queue) queue_addref(queue);
        return queue;
    }
    AcquireSRWLockExclusive(&g_process_lock);
    if (!g_process && !g_process_cleared)
        g_process = create_queue(XTaskQueueDispatchMode::ThreadPool, XTaskQueueDispatchMode::ThreadPool);
    Queue* queue = g_process;
    if (queue) queue_addref(queue);
    ReleaseSRWLockExclusive(&g_process_lock);
    return queue;
}

// ---------------------------------------------------------------- running callbacks
void finish_inflight(Port* port)
{
    AcquireSRWLockExclusive(&port->lock);
    --port->inflight;
    ReleaseSRWLockExclusive(&port->lock);
    WakeAllConditionVariable(&port->changed);
}

void run_entry(Port* port, const Entry& entry, bool canceled)
{
    if (entry.callback) entry.callback(entry.context, canceled);
    if (Waiter* waiter = entry.waiter) {
        AcquireSRWLockExclusive(&waiter->lock);
        if (waiter->registered && !canceled) SetThreadpoolWait(waiter->wait, waiter->handle, nullptr);
        ReleaseSRWLockExclusive(&waiter->lock);
        waiter_release(waiter);
    }
    (void)port;
}

bool pop(Port* port, Entry* entry, bool* canceled)
{
    AcquireSRWLockExclusive(&port->lock);
    if (port->pending.empty()) {
        ReleaseSRWLockExclusive(&port->lock);
        return false;
    }
    *entry = port->pending.front();
    port->pending.pop_front();
    *canceled = port->terminated;
    ReleaseSRWLockExclusive(&port->lock);
    return true;
}

void CALLBACK pool_one(PTP_CALLBACK_INSTANCE, void* context)
{
    auto* port = static_cast<Port*>(context);
    Entry entry;
    bool canceled;
    if (pop(port, &entry, &canceled)) run_entry(port, entry, canceled);
    finish_inflight(port);
    port_release(port);
}

void CALLBACK pool_serial(PTP_CALLBACK_INSTANCE, void* context)
{
    auto* port = static_cast<Port*>(context);
    for (;;) {
        AcquireSRWLockExclusive(&port->lock);
        if (port->pending.empty()) {
            port->serial_running = false;
            ReleaseSRWLockExclusive(&port->lock);
            break;
        }
        const Entry entry = port->pending.front();
        port->pending.pop_front();
        const bool canceled = port->terminated;
        ReleaseSRWLockExclusive(&port->lock);
        run_entry(port, entry, canceled);
    }
    finish_inflight(port);
    port_release(port);
}

bool submit_pool(Port* port, PTP_SIMPLE_CALLBACK callback)
{
    port_addref(port);
    if (TrySubmitThreadpoolCallback(callback, port, nullptr)) return true;
    port_release(port);
    return false;
}

// Queues an entry on a port (inflight already excludes it). Returns false if the port is terminated.
bool enqueue(Port* port, const Entry& entry)
{
    if (port->mode == XTaskQueueDispatchMode::Immediate) {
        AcquireSRWLockShared(&port->lock);
        const bool terminated = port->terminated;
        ReleaseSRWLockShared(&port->lock);
        if (terminated) return false;
        run_entry(port, entry, false);
        return true;
    }
    AcquireSRWLockExclusive(&port->lock);
    if (port->terminated) {
        ReleaseSRWLockExclusive(&port->lock);
        return false;
    }
    port->pending.push_back(entry);
    bool start = false;
    if (port->mode == XTaskQueueDispatchMode::ThreadPool) {
        start = true;
    } else if (port->mode == XTaskQueueDispatchMode::SerializedThreadPool && !port->serial_running) {
        port->serial_running = start = true;
    }
    if (start) ++port->inflight;
    ReleaseSRWLockExclusive(&port->lock);
    WakeAllConditionVariable(&port->changed);
    if (start && !submit_pool(port, port->mode == XTaskQueueDispatchMode::ThreadPool ? pool_one : pool_serial)) {
        x2w_unimplemented("x2w_gdk!XTaskQueue", "TrySubmitThreadpoolCallback failed; callback runs inline");
        if (port->mode == XTaskQueueDispatchMode::ThreadPool) {
            Entry e;
            bool canceled;
            if (pop(port, &e, &canceled)) run_entry(port, e, canceled);
        } else {
            port_addref(port);
            pool_serial(nullptr, port);
            return true;
        }
        finish_inflight(port);
    }
    return true;
}

void notify_monitors(Queue* queue, XTaskQueuePort port)
{
    AcquireSRWLockShared(&queue->lock);
    if (queue->monitors.empty()) {
        ReleaseSRWLockShared(&queue->lock);
        return;
    }
    const std::vector<Monitor> monitors = queue->monitors;
    queue->monitor_calls.fetch_add(1);
    ReleaseSRWLockShared(&queue->lock);
    for (const Monitor& monitor : monitors)
        monitor.callback(monitor.context, reinterpret_cast<XTaskQueueHandle>(queue), port);
    queue->monitor_calls.fetch_sub(1);
}

HRESULT submit(Queue* queue, XTaskQueuePort which, const Entry& entry)
{
    if (queue->terminated.load()) return E_ABORT;
    Port* port = queue->ports[static_cast<uint32_t>(which)];
    if (!enqueue(port, entry)) return E_ABORT;
    if (port->mode != XTaskQueueDispatchMode::Immediate) notify_monitors(queue, which);
    return S_OK;
}

void CALLBACK timer_fired(PTP_CALLBACK_INSTANCE, void* context, PTP_TIMER)
{
    auto* timer = static_cast<Timer*>(context);
    Port* port = timer->port;
    AcquireSRWLockExclusive(&port->lock);
    bool mine = false;
    for (auto it = port->timers.begin(); it != port->timers.end(); ++it) {
        if (*it == timer) {
            port->timers.erase(it);
            mine = true;
            break;
        }
    }
    ReleaseSRWLockExclusive(&port->lock);
    if (!mine) return;  // the terminating thread owns it now
    if (enqueue(port, timer->entry)) {
        if (port->mode != XTaskQueueDispatchMode::Immediate) {
            for (int i = 0; i < 2; ++i)
                if (timer->queue->ports[i] == port) notify_monitors(timer->queue, static_cast<XTaskQueuePort>(i));
        }
    } else {
        run_entry(port, timer->entry, true);
    }
    finish_inflight(port);
    CloseThreadpoolTimer(timer->timer);
    queue_release(timer->queue);
    port_release(port);
    delete timer;
}

void CALLBACK waiter_signaled(PTP_CALLBACK_INSTANCE, void* context, PTP_WAIT, TP_WAIT_RESULT)
{
    auto* waiter = static_cast<Waiter*>(context);
    AcquireSRWLockShared(&waiter->lock);
    const bool registered = waiter->registered;
    ReleaseSRWLockShared(&waiter->lock);
    if (!registered) return;
    waiter->refs.fetch_add(1);
    const Entry entry{waiter->callback, waiter->context, waiter};
    if (!enqueue(waiter->port, entry)) {
        waiter_release(waiter);
        return;
    }
    if (waiter->port->mode != XTaskQueueDispatchMode::Immediate) {
        for (int i = 0; i < 2; ++i)
            if (waiter->queue->ports[i] == waiter->port)
                notify_monitors(waiter->queue, static_cast<XTaskQueuePort>(i));
    }
}

void stop_waiter(Waiter* waiter)
{
    AcquireSRWLockExclusive(&waiter->lock);
    waiter->registered = false;
    ReleaseSRWLockExclusive(&waiter->lock);
    SetThreadpoolWait(waiter->wait, nullptr, nullptr);
    WaitForThreadpoolWaitCallbacks(waiter->wait, TRUE);
    CloseThreadpoolWait(waiter->wait);
    waiter_release(waiter);
}

// Cancels a port's pending and delayed callbacks; they run here with canceled = true.
void terminate_port(Port* port)
{
    AcquireSRWLockExclusive(&port->lock);
    port->terminated = true;
    std::deque<Entry> pending;
    pending.swap(port->pending);
    std::vector<Timer*> timers;
    timers.swap(port->timers);
    ReleaseSRWLockExclusive(&port->lock);
    WakeAllConditionVariable(&port->changed);
    for (Timer* timer : timers) {
        SetThreadpoolTimer(timer->timer, nullptr, 0, 0);
        WaitForThreadpoolTimerCallbacks(timer->timer, TRUE);
        CloseThreadpoolTimer(timer->timer);
        run_entry(port, timer->entry, true);
        finish_inflight(port);
        queue_release(timer->queue);
        port_release(port);
        delete timer;
    }
    for (const Entry& entry : pending) run_entry(port, entry, true);
}

void wait_idle(Port* port)
{
    AcquireSRWLockExclusive(&port->lock);
    while (port->inflight > 0 || !port->pending.empty()) SleepConditionVariableSRW(&port->changed, &port->lock, INFINITE, 0);
    ReleaseSRWLockExclusive(&port->lock);
}

struct Termination {
    Queue* queue;
    void* context;
    XTaskQueueTerminatedCallback* callback;
};

void finish_termination(Termination* t)
{
    for (int i = 0; i < 2; ++i)
        if (t->queue->owns[i]) wait_idle(t->queue->ports[i]);
    if (t->callback) t->callback(t->context);
    queue_release(t->queue);
    delete t;
}

void CALLBACK termination_worker(PTP_CALLBACK_INSTANCE, void* context) { finish_termination(static_cast<Termination*>(context)); }

HRESULT terminate(Queue* queue, bool wait, void* context, XTaskQueueTerminatedCallback* callback)
{
    if (queue->terminated.exchange(true)) {
        if (callback) callback(context);
        return S_OK;
    }
    AcquireSRWLockExclusive(&queue->lock);
    std::vector<Waiter*> waiters;
    waiters.swap(queue->waiters);
    ReleaseSRWLockExclusive(&queue->lock);
    for (Waiter* waiter : waiters) stop_waiter(waiter);
    for (int i = 0; i < 2; ++i)
        if (queue->owns[i] && (i == 0 || queue->ports[1] != queue->ports[0])) terminate_port(queue->ports[i]);
    queue_addref(queue);
    auto* t = new Termination{queue, context, callback};
    if (wait || !TrySubmitThreadpoolCallback(termination_worker, t, nullptr)) finish_termination(t);
    return S_OK;
}

}  // namespace

namespace x2w {
uint64_t next_token() noexcept { return g_token.fetch_add(1) + 1; }
}  // namespace x2w

extern "C" {

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueuecreate
X2W_GDK_API HRESULT x2w_impl_XTaskQueueCreate(XTaskQueueDispatchMode workDispatchMode,
                                              XTaskQueueDispatchMode completionDispatchMode,
                                              XTaskQueueHandle* queue) noexcept
{
    if (!queue) return E_POINTER;
    *queue = nullptr;
    if (!valid_mode(workDispatchMode) || !valid_mode(completionDispatchMode)) {
        x2w_unimplemented("x2w_gdk!XTaskQueueCreate", "unknown dispatch mode; E_INVALIDARG");
        return E_INVALIDARG;
    }
    *queue = reinterpret_cast<XTaskQueueHandle>(create_queue(workDispatchMode, completionDispatchMode));
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueuecreatecomposite
X2W_GDK_API HRESULT x2w_impl_XTaskQueueCreateComposite(XTaskQueuePortHandle workPort,
                                                       XTaskQueuePortHandle completionPort,
                                                       XTaskQueueHandle* queue) noexcept
{
    if (!queue) return E_POINTER;
    *queue = nullptr;
    Port* ports[2] = {valid_port(workPort), valid_port(completionPort)};
    if (!ports[0] || !ports[1]) return E_INVALIDARG;
    auto* composite = new Queue;
    for (int i = 0; i < 2; ++i) {
        port_addref(ports[i]);
        composite->ports[i] = ports[i];
    }
    *queue = reinterpret_cast<XTaskQueueHandle>(composite);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueuegetport
X2W_GDK_API HRESULT x2w_impl_XTaskQueueGetPort(XTaskQueueHandle queue, XTaskQueuePort port,
                                               XTaskQueuePortHandle* portHandle) noexcept
{
    if (!portHandle) return E_POINTER;
    *portHandle = nullptr;
    if (!valid_port_index(port)) return E_INVALIDARG;
    Queue* q = acquire(queue);
    if (!q) return E_INVALIDARG;
    *portHandle = reinterpret_cast<XTaskQueuePortHandle>(q->ports[static_cast<uint32_t>(port)]);
    queue_release(q);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueueduplicatehandle
X2W_GDK_API HRESULT x2w_impl_XTaskQueueDuplicateHandle(XTaskQueueHandle queueHandle,
                                                       XTaskQueueHandle* duplicatedHandle) noexcept
{
    if (!duplicatedHandle) return E_POINTER;
    *duplicatedHandle = nullptr;
    Queue* q = valid_queue(queueHandle);
    if (!q) return E_INVALIDARG;
    q->handles.fetch_add(1);
    queue_addref(q);
    *duplicatedHandle = queueHandle;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueuedispatch
X2W_GDK_API bool x2w_impl_XTaskQueueDispatch(XTaskQueueHandle queue, XTaskQueuePort port,
                                             uint32_t timeoutInMs) noexcept
{
    if (!valid_port_index(port)) return false;
    Queue* q = acquire(queue);
    if (!q) return false;
    Port* p = q->ports[static_cast<uint32_t>(port)];
    const ULONGLONG start = GetTickCount64();
    AcquireSRWLockExclusive(&p->lock);
    // Only a Manual port holds callbacks for a dispatcher; the others run them on their own.
    while (p->pending.empty() || p->mode != XTaskQueueDispatchMode::Manual) {
        if (p->terminated || timeoutInMs == 0) break;
        DWORD remaining = INFINITE;
        if (timeoutInMs != INFINITE) {
            const ULONGLONG elapsed = GetTickCount64() - start;
            if (elapsed >= timeoutInMs) break;
            remaining = static_cast<DWORD>(timeoutInMs - elapsed);
        }
        if (!SleepConditionVariableSRW(&p->changed, &p->lock, remaining, 0) && GetLastError() == ERROR_TIMEOUT) break;
    }
    if (p->pending.empty() || p->mode != XTaskQueueDispatchMode::Manual) {
        ReleaseSRWLockExclusive(&p->lock);
        queue_release(q);
        return false;
    }
    const Entry entry = p->pending.front();
    p->pending.pop_front();
    const bool canceled = p->terminated;
    ++p->inflight;
    ReleaseSRWLockExclusive(&p->lock);
    run_entry(p, entry, canceled);
    finish_inflight(p);
    queue_release(q);
    return true;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueueclosehandle
X2W_GDK_API void x2w_impl_XTaskQueueCloseHandle(XTaskQueueHandle queue) noexcept
{
    Queue* q = valid_queue(queue);
    if (!q) return;
    if (q->handles.fetch_sub(1) == 1 && !q->terminated.load()) terminate(q, false, nullptr, nullptr);
    queue_release(q);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueueterminate
X2W_GDK_API HRESULT x2w_impl_XTaskQueueTerminate(XTaskQueueHandle queue, bool wait, void* callbackContext,
                                                 XTaskQueueTerminatedCallback* callback) noexcept
{
    Queue* q = acquire(queue);
    if (!q) return E_INVALIDARG;
    const HRESULT hr = terminate(q, wait, callbackContext, callback);
    queue_release(q);
    return hr;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueuesubmitcallback
X2W_GDK_API HRESULT x2w_impl_XTaskQueueSubmitCallback(XTaskQueueHandle queue, XTaskQueuePort port,
                                                      void* callbackContext, XTaskQueueCallback* callback) noexcept
{
    if (!callback || !valid_port_index(port)) return E_INVALIDARG;
    Queue* q = acquire(queue);
    if (!q) return E_INVALIDARG;
    const HRESULT hr = submit(q, port, Entry{callback, callbackContext, nullptr});
    queue_release(q);
    return hr;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueuesubmitdelayedcallback
X2W_GDK_API HRESULT x2w_impl_XTaskQueueSubmitDelayedCallback(XTaskQueueHandle queue, XTaskQueuePort port,
                                                             uint32_t delayMs, void* callbackContext,
                                                             XTaskQueueCallback* callback) noexcept
{
    if (!callback || !valid_port_index(port)) return E_INVALIDARG;
    Queue* q = acquire(queue);
    if (!q) return E_INVALIDARG;
    if (delayMs == 0) {
        const HRESULT hr = submit(q, port, Entry{callback, callbackContext, nullptr});
        queue_release(q);
        return hr;
    }
    if (q->terminated.load()) {
        queue_release(q);
        return E_ABORT;
    }
    Port* p = q->ports[static_cast<uint32_t>(port)];
    auto* timer = new Timer{p, q, Entry{callback, callbackContext, nullptr}, nullptr};
    timer->timer = CreateThreadpoolTimer(timer_fired, timer, nullptr);
    if (!timer->timer) {
        delete timer;
        queue_release(q);
        return HRESULT_FROM_WIN32(GetLastError());
    }
    AcquireSRWLockExclusive(&p->lock);
    if (p->terminated) {
        ReleaseSRWLockExclusive(&p->lock);
        CloseThreadpoolTimer(timer->timer);
        delete timer;
        queue_release(q);
        return E_ABORT;
    }
    port_addref(p);
    p->timers.push_back(timer);
    ++p->inflight;
    ReleaseSRWLockExclusive(&p->lock);
    // The timer keeps the queue reference taken by acquire().
    LARGE_INTEGER due;
    due.QuadPart = -static_cast<LONGLONG>(delayMs) * 10000;
    FILETIME ft;
    ft.dwLowDateTime = due.LowPart;
    ft.dwHighDateTime = static_cast<DWORD>(due.HighPart);
    SetThreadpoolTimer(timer->timer, &ft, 0, 0);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueueregisterwaiter
X2W_GDK_API HRESULT x2w_impl_XTaskQueueRegisterWaiter(XTaskQueueHandle queue, XTaskQueuePort port, HANDLE waitHandle,
                                                      void* callbackContext, XTaskQueueCallback* callback,
                                                      XTaskQueueRegistrationToken* token) noexcept
{
    if (!token) return E_POINTER;
    token->token = 0;
    if (!callback || !waitHandle || !valid_port_index(port)) return E_INVALIDARG;
    Queue* q = acquire(queue);
    if (!q) return E_INVALIDARG;
    if (q->terminated.load()) {
        queue_release(q);
        return E_ABORT;
    }
    auto* waiter = new Waiter;
    waiter->token = x2w::next_token();
    waiter->port = q->ports[static_cast<uint32_t>(port)];
    waiter->queue = q;  // not referenced: a queue stops its waiters before it goes away
    waiter->handle = waitHandle;
    waiter->callback = callback;
    waiter->context = callbackContext;
    waiter->wait = CreateThreadpoolWait(waiter_signaled, waiter, nullptr);
    if (!waiter->wait) {
        delete waiter;
        queue_release(q);
        return HRESULT_FROM_WIN32(GetLastError());
    }
    AcquireSRWLockExclusive(&q->lock);
    q->waiters.push_back(waiter);
    ReleaseSRWLockExclusive(&q->lock);
    SetThreadpoolWait(waiter->wait, waitHandle, nullptr);
    token->token = waiter->token;
    queue_release(q);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueueunregisterwaiter
X2W_GDK_API void x2w_impl_XTaskQueueUnregisterWaiter(XTaskQueueHandle queue, XTaskQueueRegistrationToken token) noexcept
{
    Queue* q = acquire(queue);
    if (!q) return;
    Waiter* found = nullptr;
    AcquireSRWLockExclusive(&q->lock);
    for (auto it = q->waiters.begin(); it != q->waiters.end(); ++it) {
        if ((*it)->token == token.token) {
            found = *it;
            q->waiters.erase(it);
            break;
        }
    }
    ReleaseSRWLockExclusive(&q->lock);
    if (found) stop_waiter(found);
    queue_release(q);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueueregistermonitor
X2W_GDK_API HRESULT x2w_impl_XTaskQueueRegisterMonitor(XTaskQueueHandle queue, void* callbackContext,
                                                       XTaskQueueMonitorCallback* callback,
                                                       XTaskQueueRegistrationToken* token) noexcept
{
    if (!token) return E_POINTER;
    token->token = 0;
    if (!callback) return E_INVALIDARG;
    Queue* q = acquire(queue);
    if (!q) return E_INVALIDARG;
    const uint64_t id = x2w::next_token();
    AcquireSRWLockExclusive(&q->lock);
    q->monitors.push_back(Monitor{id, callback, callbackContext});
    ReleaseSRWLockExclusive(&q->lock);
    token->token = id;
    queue_release(q);
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueueunregistermonitor
X2W_GDK_API void x2w_impl_XTaskQueueUnregisterMonitor(XTaskQueueHandle queue, XTaskQueueRegistrationToken token) noexcept
{
    Queue* q = acquire(queue);
    if (!q) return;
    AcquireSRWLockExclusive(&q->lock);
    for (auto it = q->monitors.begin(); it != q->monitors.end(); ++it) {
        if (it->token == token.token) {
            q->monitors.erase(it);
            break;
        }
    }
    ReleaseSRWLockExclusive(&q->lock);
    // "This blocks if there are outstanding monitor callbacks."
    while (q->monitor_calls.load() > 0) Sleep(0);
    queue_release(q);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueuegetcurrentprocesstaskqueue
X2W_GDK_API bool x2w_impl_XTaskQueueGetCurrentProcessTaskQueue(XTaskQueueHandle* queue) noexcept
{
    if (!queue) return false;
    Queue* q = acquire(nullptr);
    *queue = nullptr;
    if (!q) return false;
    q->handles.fetch_add(1);  // the caller closes this handle; acquire()'s reference is the handle's
    *queue = reinterpret_cast<XTaskQueueHandle>(q);
    return true;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xtaskqueue/functions/xtaskqueuesetcurrentprocesstaskqueue
X2W_GDK_API void x2w_impl_XTaskQueueSetCurrentProcessTaskQueue(XTaskQueueHandle queue) noexcept
{
    Queue* q = valid_queue(queue);
    if (q) {
        q->handles.fetch_add(1);
        queue_addref(q);
    }
    AcquireSRWLockExclusive(&g_process_lock);
    Queue* old = g_process;
    g_process = q;
    g_process_cleared = q == nullptr;
    ReleaseSRWLockExclusive(&g_process_lock);
    if (old) x2w_impl_XTaskQueueCloseHandle(reinterpret_cast<XTaskQueueHandle>(old));
}

}  // extern "C"
