// XAsync and XAsyncProvider over our XTaskQueue.
// Behavior follows the public libHttpClient XAsync.h / XAsyncProvider.h comments (MIT) and
// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasync/xasync_members:
//   XAsyncBegin calls the provider with Begin (which normally calls XAsyncSchedule); DoWork runs on the
//   block's queue work port; a DoWork result other than E_PENDING completes the call; XAsyncComplete sets
//   the status, wakes XAsyncGetStatus(wait = true) and queues the completion callback on the completion
//   port. A call with no payload (or a failure) is cleaned up at completion; otherwise XAsyncGetResult
//   copies the payload and cleans up. XAsyncCancel asks the provider (Cancel), which completes with E_ABORT.
//   The status lives in the block's internal bytes, so it stays readable after cleanup.
#include "gdk_internal.h"

#include <atomic>
#include <string>

namespace {

constexpr uint32_t block_signature = 0x31534158;  // "XAS1"

struct AsyncState {
    long refs = 1;  // the operation's own reference, released after cleanup
    XAsyncBlock* block = nullptr;
    XAsyncProvider* provider = nullptr;
    void* context = nullptr;
    const void* identity = nullptr;
    std::string name;
    XTaskQueueHandle queue = nullptr;
    HANDLE done = nullptr;
    size_t required = 0;
    bool completed = false;
    bool cleaned = false;
    bool in_work = false;
    bool cleanup_deferred = false;
};

struct BlockInternal {
    AsyncState* state;
    volatile LONG status;
    uint32_t signature;
    uint64_t reserved[2];
};
static_assert(sizeof(BlockInternal) <= sizeof(XAsyncBlock::internal), "internal bytes");

SRWLOCK g_lock = SRWLOCK_INIT;

BlockInternal* internal_of(XAsyncBlock* block) { return reinterpret_cast<BlockInternal*>(block->internal); }

// The block's state with a reference, under the lock. Null when none.
AsyncState* acquire(XAsyncBlock* block)
{
    if (!block) return nullptr;
    AcquireSRWLockExclusive(&g_lock);
    BlockInternal* in = internal_of(block);
    AsyncState* state = in->signature == block_signature ? in->state : nullptr;
    if (state) ++state->refs;
    ReleaseSRWLockExclusive(&g_lock);
    return state;
}

void release(AsyncState* state)
{
    AcquireSRWLockExclusive(&g_lock);
    const bool last = --state->refs == 0;
    ReleaseSRWLockExclusive(&g_lock);
    if (!last) return;
    if (state->done) CloseHandle(state->done);
    if (state->queue) x2w_impl_XTaskQueueCloseHandle(state->queue);
    delete state;
}

HRESULT call(AsyncState* state, XAsyncOp op, size_t size = 0, void* buffer = nullptr)
{
    const XAsyncProviderData data{state->block, size, buffer, state->context};
    return state->provider(op, &data);
}

void cleanup(AsyncState* state)
{
    AcquireSRWLockExclusive(&g_lock);
    if (state->cleaned) {
        ReleaseSRWLockExclusive(&g_lock);
        return;
    }
    if (state->in_work) {
        state->cleanup_deferred = true;
        ReleaseSRWLockExclusive(&g_lock);
        return;
    }
    state->cleaned = true;
    BlockInternal* in = internal_of(state->block);
    if (in->state == state) in->state = nullptr;
    ReleaseSRWLockExclusive(&g_lock);
    call(state, XAsyncOp::Cleanup);
    release(state);
}

void CALLBACK completion_callback(void* context, bool /*canceled*/)
{
    auto* state = static_cast<AsyncState*>(context);
    XAsyncBlock* block = state->block;
    if (block->callback) block->callback(block);
    release(state);
}

void complete(AsyncState* state, HRESULT result, size_t required)
{
    if (result == E_PENDING) result = E_UNEXPECTED;
    AcquireSRWLockExclusive(&g_lock);
    if (state->completed) {
        ReleaseSRWLockExclusive(&g_lock);
        return;
    }
    state->completed = true;
    state->required = SUCCEEDED(result) ? required : 0;
    XAsyncCompletionRoutine* callback = state->block->callback;
    if (callback) ++state->refs;  // for the completion callback
    InterlockedExchange(&internal_of(state->block)->status, result);
    ReleaseSRWLockExclusive(&g_lock);
    if (FAILED(result) || required == 0) cleanup(state);
    SetEvent(state->done);
    if (callback) {
        if (FAILED(x2w_impl_XTaskQueueSubmitCallback(state->queue, XTaskQueuePort::Completion, state, completion_callback))) {
            // A terminated queue: the callback still marks the end of the call, so run it here.
            completion_callback(state, true);
        }
    }
}

void CALLBACK do_work(void* context, bool canceled)
{
    auto* state = static_cast<AsyncState*>(context);
    AcquireSRWLockExclusive(&g_lock);
    const bool run = !state->completed && !state->cleaned && !canceled;
    if (run) state->in_work = true;
    ReleaseSRWLockExclusive(&g_lock);
    if (canceled) complete(state, E_ABORT, 0);
    if (run) {
        const HRESULT hr = call(state, XAsyncOp::DoWork);
        AcquireSRWLockExclusive(&g_lock);
        state->in_work = false;
        const bool deferred = state->cleanup_deferred;
        ReleaseSRWLockExclusive(&g_lock);
        if (hr != E_PENDING) complete(state, hr, 0);  // ignored if the provider already completed
        if (deferred) cleanup(state);
    }
    release(state);
}

// ---------------------------------------------------------------- XAsyncRun's provider
HRESULT CALLBACK run_provider(XAsyncOp op, const XAsyncProviderData* data)
{
    auto* work = reinterpret_cast<XAsyncWork*>(data->context);
    switch (op) {
    case XAsyncOp::Begin: return x2w_impl_XAsyncSchedule(data->async, 0);
    case XAsyncOp::DoWork: return work(data->async);
    case XAsyncOp::Cancel: x2w_impl_XAsyncComplete(data->async, E_ABORT, 0); return S_OK;
    default: return S_OK;
    }
}

// ---------------------------------------------------------------- our own operations (x2w::AsyncOp)
HRESULT CALLBACK op_provider(XAsyncOp op, const XAsyncProviderData* data)
{
    auto* job = static_cast<x2w::AsyncOp*>(data->context);
    switch (op) {
    case XAsyncOp::Begin: return x2w_impl_XAsyncSchedule(data->async, 0);
    case XAsyncOp::DoWork: {
        const HRESULT hr = job->work();
        x2w_impl_XAsyncComplete(data->async, hr, SUCCEEDED(hr) ? job->result_size() : 0);
        return hr;
    }
    case XAsyncOp::GetResult: job->get_result(data->buffer, data->bufferSize); return S_OK;
    case XAsyncOp::Cancel: x2w_impl_XAsyncComplete(data->async, E_ABORT, 0); return S_OK;
    case XAsyncOp::Cleanup: delete job; return S_OK;
    }
    return S_OK;
}

HRESULT begin(XAsyncBlock* asyncBlock, void* context, const void* identity, const char* identityName,
              XAsyncProvider* provider, bool* consumed);

}  // namespace

namespace x2w {

HRESULT async_start(XAsyncBlock* block, const void* identity, const char* name, AsyncOp* op) noexcept
{
    if (!block) {
        delete op;
        return E_POINTER;
    }
    // begin() calls Cleanup (which deletes op) once it has created the call; before that, op is ours.
    bool consumed = false;
    const HRESULT hr = begin(block, op, identity, name, op_provider, &consumed);
    if (!consumed) delete op;
    return hr;
}

HRESULT async_finish(XAsyncBlock* block, const void* identity, const std::function<HRESULT(AsyncOp*)>& take) noexcept
{
    if (!block) return E_POINTER;
    AsyncState* state = acquire(block);
    if (!state) {
        BlockInternal* in = internal_of(block);
        if (in->signature != block_signature) return E_INVALIDARG;
        const HRESULT status = in->status;
        if (FAILED(status) || status == E_PENDING) return status;
        return take(nullptr);
    }
    HRESULT hr = internal_of(block)->status;
    if (hr == E_PENDING || FAILED(hr)) {
        release(state);
        return hr;
    }
    if (state->identity != identity) {
        release(state);
        return E_INVALIDARG;
    }
    hr = take(static_cast<AsyncOp*>(state->context));
    if (SUCCEEDED(hr)) cleanup(state);
    release(state);
    return hr;
}

}  // namespace x2w

namespace {

HRESULT begin(XAsyncBlock* asyncBlock, void* context, const void* identity, const char* identityName,
              XAsyncProvider* provider, bool* consumed)
{
    *consumed = false;
    if (!asyncBlock || !provider) return E_INVALIDARG;
    BlockInternal* in = internal_of(asyncBlock);
    AcquireSRWLockExclusive(&g_lock);
    const bool busy = in->signature == block_signature && in->state && in->status == E_PENDING;
    ReleaseSRWLockExclusive(&g_lock);
    if (busy) {
        x2w_unimplemented("x2w_gdk!XAsyncBegin", "XAsyncBlock reused while its call is pending; E_INVALIDARG");
        return E_INVALIDARG;
    }
    XTaskQueueHandle queue = nullptr;
    HRESULT hr = asyncBlock->queue ? x2w_impl_XTaskQueueDuplicateHandle(asyncBlock->queue, &queue)
                                   : (x2w_impl_XTaskQueueGetCurrentProcessTaskQueue(&queue) ? S_OK : E_INVALIDARG);
    if (FAILED(hr)) {
        x2w_unimplemented("x2w_gdk!XAsyncBegin", "no usable task queue (invalid handle or no process queue)");
        return hr;
    }
    auto* state = new AsyncState;
    state->block = asyncBlock;
    state->provider = provider;
    state->context = context;
    state->identity = identity;
    state->name = identityName ? identityName : "";
    state->queue = queue;
    state->done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    AcquireSRWLockExclusive(&g_lock);
    memset(asyncBlock->internal, 0, sizeof asyncBlock->internal);
    in->state = state;
    in->status = E_PENDING;
    in->signature = block_signature;
    ReleaseSRWLockExclusive(&g_lock);
    *consumed = true;
    hr = call(state, XAsyncOp::Begin);
    if (FAILED(hr)) {
        AcquireSRWLockExclusive(&g_lock);
        state->completed = true;
        InterlockedExchange(&in->status, hr);
        ReleaseSRWLockExclusive(&g_lock);
        cleanup(state);
        SetEvent(state->done);
    }
    return hr;
}

}  // namespace

extern "C" {

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasyncprovider/functions/xasyncbegin
X2W_GDK_API HRESULT x2w_impl_XAsyncBegin(XAsyncBlock* asyncBlock, void* context, const void* identity,
                                         const char* identityName, XAsyncProvider* provider) noexcept
{
    bool consumed;
    return begin(asyncBlock, context, identity, identityName, provider, &consumed);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasyncprovider/functions/xasyncschedule
X2W_GDK_API HRESULT x2w_impl_XAsyncSchedule(XAsyncBlock* asyncBlock, uint32_t delayInMs) noexcept
{
    AsyncState* state = acquire(asyncBlock);
    if (!state) return E_INVALIDARG;
    // The submitted callback owns this reference.
    const HRESULT hr =
        x2w_impl_XTaskQueueSubmitDelayedCallback(state->queue, XTaskQueuePort::Work, delayInMs, state, do_work);
    if (FAILED(hr)) release(state);
    return hr;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasyncprovider/functions/xasynccomplete
X2W_GDK_API void x2w_impl_XAsyncComplete(XAsyncBlock* asyncBlock, HRESULT result, size_t requiredBufferSize) noexcept
{
    AsyncState* state = acquire(asyncBlock);
    if (!state) return;
    complete(state, result, requiredBufferSize);
    release(state);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasyncprovider/functions/xasyncgetresult
X2W_GDK_API HRESULT x2w_impl_XAsyncGetResult(XAsyncBlock* asyncBlock, const void* identity, size_t bufferSize,
                                             void* buffer, size_t* bufferUsed) noexcept
{
    if (bufferUsed) *bufferUsed = 0;
    if (!asyncBlock) return E_POINTER;
    AsyncState* state = acquire(asyncBlock);
    if (!state) {
        BlockInternal* in = internal_of(asyncBlock);
        return in->signature == block_signature ? in->status : E_INVALIDARG;
    }
    HRESULT hr = internal_of(asyncBlock)->status;
    if (hr == E_PENDING || FAILED(hr)) {
        release(state);
        return hr;
    }
    if (identity != state->identity) {
        release(state);
        return E_INVALIDARG;
    }
    if (bufferSize < state->required || (state->required && !buffer)) {
        release(state);
        return x2w::insufficient_buffer;
    }
    hr = call(state, XAsyncOp::GetResult, bufferSize, buffer);
    if (SUCCEEDED(hr)) {
        if (bufferUsed) *bufferUsed = state->required;
        cleanup(state);
    }
    release(state);
    return hr;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasync/functions/xasyncgetstatus
X2W_GDK_API HRESULT x2w_impl_XAsyncGetStatus(XAsyncBlock* asyncBlock, bool wait) noexcept
{
    if (!asyncBlock) return E_POINTER;
    BlockInternal* in = internal_of(asyncBlock);
    if (in->signature != block_signature) return E_INVALIDARG;
    if (wait) {
        if (AsyncState* state = acquire(asyncBlock)) {
            WaitForSingleObject(state->done, INFINITE);
            release(state);
        }
    }
    return in->status;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasync/functions/xasyncgetresultsize
X2W_GDK_API HRESULT x2w_impl_XAsyncGetResultSize(XAsyncBlock* asyncBlock, size_t* bufferSize) noexcept
{
    if (!bufferSize) return E_POINTER;
    *bufferSize = 0;
    if (!asyncBlock) return E_POINTER;
    BlockInternal* in = internal_of(asyncBlock);
    if (in->signature != block_signature) return E_INVALIDARG;
    const HRESULT status = in->status;
    if (status == E_PENDING || FAILED(status)) return status;
    if (AsyncState* state = acquire(asyncBlock)) {
        *bufferSize = state->required;
        release(state);
    }
    return status;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasync/functions/xasynccancel
X2W_GDK_API void x2w_impl_XAsyncCancel(XAsyncBlock* asyncBlock) noexcept
{
    AsyncState* state = acquire(asyncBlock);
    if (!state) return;
    if (internal_of(asyncBlock)->status == E_PENDING) call(state, XAsyncOp::Cancel);
    release(state);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xasync/functions/xasyncrun
X2W_GDK_API HRESULT x2w_impl_XAsyncRun(XAsyncBlock* asyncBlock, XAsyncWork* work) noexcept
{
    if (!work) return E_INVALIDARG;
    return x2w_impl_XAsyncBegin(asyncBlock, reinterpret_cast<void*>(work), reinterpret_cast<const void*>(run_provider),
                                "XAsyncRun", run_provider);
}

}  // extern "C"
