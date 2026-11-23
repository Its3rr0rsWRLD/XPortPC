#include "sys_gameinput_v0.h"

#include "sys_common.h"
#include "sys_gameinput.h"

#include <array>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <utility>
#include <vector>

namespace x2w_sys::gi0 {
namespace {

// ---------------------------------------------------------------- logging
using LaunchLog = void(__cdecl*)(const char* kind, const char* symbol, const char* detail);

LaunchLog launch_log() {
    static LaunchLog fn = [] {
        auto found = reinterpret_cast<LaunchLog>(GetProcAddress(GetModuleHandleW(nullptr), "x2w_launch_log_shim"));
        if (!found)
            if (HMODULE launcher = GetModuleHandleW(L"x2w_launch.exe"))
                found = reinterpret_cast<LaunchLog>(GetProcAddress(launcher, "x2w_launch_log_shim"));
        return found;
    }();
    return fn;
}

long call_limit() {
    static long limit = [] {
        const std::string text = get_env("X2W_GAMEINPUT_LOG_CALLS");
        return text.empty() ? 8L : std::strtol(text.c_str(), nullptr, 0);
    }();
    return limit;
}

volatile long g_logged;

void emit(const char* method, const char* fmt, ...) X2W_SYS_PRINTF(2, 3);
void emit(const char* method, const char* fmt, ...) {
    char detail[512];
    va_list args;
    va_start(args, fmt);
    std::vsnprintf(detail, sizeof detail, fmt, args);
    va_end(args);
    InterlockedIncrement(&g_logged);
    log("gameinput: %s %s", method, detail);
    if (LaunchLog fn = launch_log()) fn("gameinput", method, detail);
}

// The first call_limit() calls of each method site are logged.
#define GI_LOG(method, ...)                                                        \
    do {                                                                           \
        static volatile long calls_;                                               \
        if (InterlockedIncrement(&calls_) <= call_limit()) emit(method, __VA_ARGS__); \
    } while (0)

using u64 = unsigned long long;

// ---------------------------------------------------------------- backend
std::once_flag g_once;
gi::XInputApi g_xinput;
DWORD(WINAPI* g_set_state)(DWORD, XINPUT_VIBRATION*) = nullptr;
bool g_pads = true;
LARGE_INTEGER g_qpf;

void init() {
    std::call_once(g_once, [] {
        QueryPerformanceFrequency(&g_qpf);
        g_pads = get_env("X2W_GAMEINPUT_PADS") != "off";
        if (g_pads && gi::load_xinput(&g_xinput))
            g_set_state = reinterpret_cast<decltype(g_set_state)>(GetProcAddress(g_xinput.module, "XInputSetState"));
        log("gameinput: v0 facade ready (xinput %s, pads %s)", g_xinput.get_state ? "loaded" : "missing",
            g_pads ? "on" : "off");
    });
}

uint64_t now_us() {
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return mul_div_u64(static_cast<uint64_t>(t.QuadPart), 1000000, static_cast<uint64_t>(g_qpf.QuadPart));
}

bool read_pad(uint32_t index, XINPUT_STATE* state) {
    if (!g_pads || !g_xinput.get_state || index >= XUSER_MAX_COUNT) return false;
    return g_xinput.get_state(index, state) == ERROR_SUCCESS;
}

int first_pad() {
    XINPUT_STATE s;
    for (uint32_t i = 0; i < XUSER_MAX_COUNT; ++i)
        if (read_pad(i, &s)) return static_cast<int>(i);
    return -1;
}

// ---------------------------------------------------------------- objects
using Vtable = std::array<void*, kSlots>;

template <int Iface, int N>
u64 STDMETHODCALLTYPE unknown_slot(void* self, u64 a, u64 b, u64 c) {
    static const char* const names[] = {"IGameInput", "IGameInputReading", "IGameInputDevice", "IGameInputDispatcher"};
    char method[64];
    std::snprintf(method, sizeof method, "unknown-slot %s[%d]", names[Iface], N);
    static volatile long calls_;
    if (InterlockedIncrement(&calls_) <= call_limit())
        emit(method, "this=%p a=0x%llx b=0x%llx c=0x%llx -> E_NOTIMPL", self, a, b, c);
    return static_cast<u64>(static_cast<uint32_t>(E_NOTIMPL));
}

template <int Iface, std::size_t... N>
Vtable unknown_table(std::index_sequence<N...>) {
    return Vtable{{reinterpret_cast<void*>(&unknown_slot<Iface, static_cast<int>(N)>)...}};
}

struct Object {
    void** vtbl;
};

struct DeviceInfoV0 {
    uint32_t info_size;
    uint16_t vendor_id, product_id, revision_number;
    uint8_t interface_number, collection_number;
    uint16_t usage_page, usage_id;
    uint16_t hardware_version[4], firmware_version[4];
    uint8_t device_id[32], device_root_id[32];
    int32_t device_family;
    uint32_t capabilities, supported_input, supported_rumble_motors;
    uint32_t counts[12];       // input/output/feature reports, axes, buttons, switches, touch points/sensors,
                               // force-feedback/haptic motors, strings, descriptor size: all 0
    const void* pointers[20];  // per-kind info, display name, strings, descriptor: all point at zeros
};

alignas(16) const unsigned char g_zeros[4096] = {};

struct Device : Object {
    uint32_t index;
    union {
        DeviceInfoV0 info;
        unsigned char info_bytes[1024];
    };
};

struct Reading : Object {
    volatile long refs;
    uint32_t kind;
    uint32_t index;
    uint64_t sequence;
    uint64_t timestamp;
    GamepadStateV0 gamepad;
};

Vtable g_input_vt, g_reading_vt, g_device_vt, g_dispatcher_vt;
Object g_input, g_dispatcher;
Device g_devices[XUSER_MAX_COUNT];

bool is_device(const void* p) {
    for (const auto& d : g_devices)
        if (p == &d) return true;
    return false;
}

bool is_reading(const void* p) {
    return p && static_cast<const Object*>(p)->vtbl == g_reading_vt.data();
}

// ---------------------------------------------------------------- IUnknown
HRESULT STDMETHODCALLTYPE qi(Object* self, const GUID* iid, void** out) {
    if (iid)
        GI_LOG("QueryInterface", "this=%p iid={%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x}", static_cast<void*>(self),
               iid->Data1, iid->Data2, iid->Data3, iid->Data4[0], iid->Data4[1], iid->Data4[2], iid->Data4[3],
               iid->Data4[4], iid->Data4[5], iid->Data4[6], iid->Data4[7]);
    if (!out) return E_POINTER;
    *out = self;
    if (is_reading(self)) InterlockedIncrement(&static_cast<Reading*>(self)->refs);
    return S_OK;
}
ULONG STDMETHODCALLTYPE static_addref(Object*) { return 2; }
ULONG STDMETHODCALLTYPE static_release(Object*) { return 1; }

ULONG STDMETHODCALLTYPE reading_addref(Reading* self) { return static_cast<ULONG>(InterlockedIncrement(&self->refs)); }
ULONG STDMETHODCALLTYPE reading_release(Reading* self) {
    const long left = InterlockedDecrement(&self->refs);
    if (left == 0) delete self;
    return static_cast<ULONG>(left);
}

Reading* make_reading(uint32_t index, const XINPUT_STATE& s) {
    auto* r = new Reading{};
    r->vtbl = g_reading_vt.data();
    r->refs = 1;
    r->kind = kKindGamepad;
    r->index = index;
    r->sequence = s.dwPacketNumber;
    r->timestamp = now_us();
    const gi::GamepadState g = gi::convert(s);
    r->gamepad = {g.buttons, g.left_trigger, g.right_trigger, g.left_x, g.left_y, g.right_x, g.right_y};
    return r;
}

// ---------------------------------------------------------------- IGameInput
uint64_t STDMETHODCALLTYPE get_current_timestamp(Object*) {
    const uint64_t t = now_us();
    GI_LOG("GetCurrentTimestamp", "-> %llu", static_cast<u64>(t));
    return t;
}

int pad_for(void* device) {
    if (device) return is_device(device) ? static_cast<int>(static_cast<Device*>(device)->index) : -1;
    return first_pad();
}

HRESULT current(uint32_t kind, void* device, Reading** out) {
    *out = nullptr;
    if (!(kind & kKindGamepad)) return kReadingNotFound;
    const int index = pad_for(device);
    XINPUT_STATE s{};
    if (index < 0 || !read_pad(static_cast<uint32_t>(index), &s)) return device ? kDeviceDisconnected : kReadingNotFound;
    *out = make_reading(static_cast<uint32_t>(index), s);
    return S_OK;
}

HRESULT STDMETHODCALLTYPE get_current_reading(Object*, uint32_t kind, void* device, void** reading) {
    if (!reading) return E_POINTER;
    Reading* r = nullptr;
    const HRESULT hr = current(kind, device, &r);
    *reading = r;
    GI_LOG("GetCurrentReading", "kind=0x%x device=%p -> 0x%08lx", kind, device, static_cast<unsigned long>(hr));
    return hr;
}

HRESULT STDMETHODCALLTYPE get_next_reading(Object*, void* reference, uint32_t kind, void* device, void** reading) {
    if (!reading) return E_POINTER;
    Reading* r = nullptr;
    HRESULT hr = current(kind, device, &r);
    if (SUCCEEDED(hr) && is_reading(reference)) {
        const auto* ref = static_cast<Reading*>(reference);
        if (ref->index == r->index && ref->sequence == r->sequence) {
            reading_release(r);
            r = nullptr;
            hr = kReadingNotFound;
        }
    }
    *reading = r;
    GI_LOG("GetNextReading", "reference=%p kind=0x%x device=%p -> 0x%08lx", reference, kind, device,
           static_cast<unsigned long>(hr));
    return hr;
}

HRESULT STDMETHODCALLTYPE get_previous_reading(Object*, void* reference, uint32_t kind, void* device, void** reading) {
    if (reading) *reading = nullptr;
    GI_LOG("GetPreviousReading", "reference=%p kind=0x%x device=%p -> READING_NOT_FOUND", reference, kind, device);
    return reading ? kReadingNotFound : E_POINTER;
}

HRESULT STDMETHODCALLTYPE get_temporal_reading(Object*, uint64_t timestamp, void* device, void** reading) {
    if (!reading) return E_POINTER;
    Reading* r = nullptr;
    const HRESULT hr = current(kKindGamepad, device, &r);
    *reading = r;
    GI_LOG("GetTemporalReading", "timestamp=%llu device=%p -> 0x%08lx", static_cast<u64>(timestamp), device,
           static_cast<unsigned long>(hr));
    return hr;
}

// Callbacks.
using DeviceCallback = void(CALLBACK*)(uint64_t token, void* context, void* device, uint64_t timestamp,
                                       uint32_t current_status, uint32_t previous_status);
struct Registration {
    uint64_t token;
    int type;  // 0 reading, 1 device, 2 guide, 3 keyboard layout
    void* context;
    void* callback;
    uint32_t kind, filter;
    bool active;
};
std::mutex g_mutex;
std::vector<Registration> g_registrations;
uint64_t g_next_token = 1;

uint64_t add_registration(int type, void* context, void* callback, uint32_t kind, uint32_t filter) {
    std::lock_guard<std::mutex> lock(g_mutex);
    const uint64_t token = g_next_token++;
    g_registrations.push_back({token, type, context, callback, kind, filter, true});
    return token;
}

bool registration_active(uint64_t token) {
    std::lock_guard<std::mutex> lock(g_mutex);
    for (const auto& r : g_registrations)
        if (r.token == token) return r.active;
    return false;
}

// Reports each connected pad to a device callback.
void enumerate_to(uint64_t token, void* context, DeviceCallback callback, void* device, uint32_t kind, uint32_t filter) {
    if (!(filter & kStatusConnected)) return;
    if (kind != kKindUnknown && !(kind & kKindGamepad)) return;
    for (uint32_t i = 0; i < XUSER_MAX_COUNT; ++i) {
        if (device && device != &g_devices[i]) continue;
        XINPUT_STATE s;
        if (!read_pad(i, &s) || !registration_active(token)) continue;
        GI_LOG("device-callback", "token=%llu device=%p (xinput %u) connected", static_cast<u64>(token),
               static_cast<void*>(&g_devices[i]), i);
        callback(token, context, &g_devices[i], now_us(), kStatusConnected | kStatusInputEnabled | kStatusOutputEnabled, 0);
    }
}

struct AsyncEnum {
    uint64_t token;
    void* context;
    DeviceCallback callback;
    void* device;
    uint32_t kind, filter;
};

DWORD WINAPI async_enum(void* p) {
    auto* job = static_cast<AsyncEnum*>(p);
    enumerate_to(job->token, job->context, job->callback, job->device, job->kind, job->filter);
    delete job;
    return 0;
}

HRESULT STDMETHODCALLTYPE register_reading_callback(Object*, void* device, uint32_t kind, float threshold, void* context,
                                                    void* callback, uint64_t* token) {
    const uint64_t t = add_registration(0, context, callback, kind, 0);
    if (token) *token = t;
    GI_LOG("RegisterReadingCallback", "device=%p kind=0x%x threshold=%g context=%p callback=%p -> token %llu", device,
           kind, static_cast<double>(threshold), context, callback, static_cast<u64>(t));
    return S_OK;
}

HRESULT STDMETHODCALLTYPE register_device_callback(Object*, void* device, uint32_t kind, uint32_t filter,
                                                   uint32_t enumeration, void* context, void* callback, uint64_t* token) {
    const uint64_t t = add_registration(1, context, callback, kind, filter);
    if (token) *token = t;
    GI_LOG("RegisterDeviceCallback", "device=%p kind=0x%x status=0x%x enumeration=%u context=%p callback=%p -> token %llu",
           device, kind, filter, enumeration, context, callback, static_cast<u64>(t));
    if (callback && enumeration == kEnumBlocking) {
        enumerate_to(t, context, reinterpret_cast<DeviceCallback>(callback), device, kind, filter);
    } else if (callback && enumeration == kEnumAsync) {
        auto* job = new AsyncEnum{t, context, reinterpret_cast<DeviceCallback>(callback), device, kind, filter};
        HANDLE thread = CreateThread(nullptr, 0, async_enum, job, 0, nullptr);
        if (thread) CloseHandle(thread);
        else delete job;
    }
    return S_OK;
}

HRESULT STDMETHODCALLTYPE register_guide_button_callback(Object*, void* device, void* context, void* callback,
                                                         uint64_t* token) {
    const uint64_t t = add_registration(2, context, callback, 0, 0);
    if (token) *token = t;
    GI_LOG("RegisterGuideButtonCallback", "device=%p context=%p callback=%p -> token %llu", device, context, callback,
           static_cast<u64>(t));
    return S_OK;
}

HRESULT STDMETHODCALLTYPE register_keyboard_layout_callback(Object*, void* device, void* context, void* callback,
                                                            uint64_t* token) {
    const uint64_t t = add_registration(3, context, callback, 0, 0);
    if (token) *token = t;
    GI_LOG("RegisterKeyboardLayoutCallback", "device=%p context=%p callback=%p -> token %llu", device, context, callback,
           static_cast<u64>(t));
    return S_OK;
}

bool deactivate(uint64_t token) {
    std::lock_guard<std::mutex> lock(g_mutex);
    for (auto& r : g_registrations)
        if (r.token == token) {
            const bool was = r.active;
            r.active = false;
            return was;
        }
    return false;
}

void STDMETHODCALLTYPE stop_callback(Object*, uint64_t token) {
    const bool found = deactivate(token);
    GI_LOG("StopCallback", "token=%llu%s", static_cast<u64>(token), found ? "" : " (unknown)");
}

bool STDMETHODCALLTYPE unregister_callback(Object*, uint64_t token, uint64_t timeout_us) {
    const bool found = deactivate(token);
    GI_LOG("UnregisterCallback", "token=%llu timeout=%llu -> %s", static_cast<u64>(token), static_cast<u64>(timeout_us),
           found ? "true" : "false (unknown)");
    return true;
}

HRESULT STDMETHODCALLTYPE create_dispatcher(Object*, void** dispatcher) {
    GI_LOG("CreateDispatcher", "out=%p", static_cast<void*>(dispatcher));
    if (!dispatcher) return E_POINTER;
    *dispatcher = &g_dispatcher;
    return S_OK;
}

HRESULT STDMETHODCALLTYPE create_aggregate_device(Object*, uint32_t kind, void** device) {
    if (device) *device = nullptr;
    GI_LOG("CreateAggregateDevice", "kind=0x%x -> E_NOTIMPL", kind);
    return E_NOTIMPL;
}

HRESULT STDMETHODCALLTYPE find_device_from_id(Object*, const void* id, void** device) {
    if (device) *device = nullptr;
    for (auto& d : g_devices) {
        XINPUT_STATE s;
        if (id && std::memcmp(id, d.info.device_id, 32) == 0 && read_pad(d.index, &s)) {
            if (device) *device = &d;
            GI_LOG("FindDeviceFromId", "id=%p -> device %p", id, static_cast<void*>(&d));
            return S_OK;
        }
    }
    GI_LOG("FindDeviceFromId", "id=%p -> DEVICE_NOT_FOUND", id);
    return kDeviceNotFound;
}

HRESULT STDMETHODCALLTYPE find_device_from_object(Object*, void* object, void** device) {
    if (device) *device = nullptr;
    GI_LOG("FindDeviceFromObject", "object=%p -> DEVICE_NOT_FOUND", object);
    return kDeviceNotFound;
}

HRESULT STDMETHODCALLTYPE find_device_from_platform_handle(Object*, HANDLE handle, void** device) {
    if (device) *device = nullptr;
    GI_LOG("FindDeviceFromPlatformHandle", "handle=%p -> DEVICE_NOT_FOUND", static_cast<void*>(handle));
    return kDeviceNotFound;
}

HRESULT STDMETHODCALLTYPE find_device_from_platform_string(Object*, const wchar_t* text, void** device) {
    if (device) *device = nullptr;
    GI_LOG("FindDeviceFromPlatformString", "string=%s -> DEVICE_NOT_FOUND", text ? "(set)" : "(null)");
    return kDeviceNotFound;
}

HRESULT STDMETHODCALLTYPE enable_oem_device_support(Object*, uint16_t vendor, uint16_t product, uint8_t iface,
                                                    uint8_t collection) {
    GI_LOG("EnableOemDeviceSupport", "vendor=0x%04x product=0x%04x interface=%u collection=%u -> S_OK", vendor, product,
           iface, collection);
    return S_OK;
}

void STDMETHODCALLTYPE set_focus_policy(Object*, uint32_t policy) { GI_LOG("SetFocusPolicy", "policy=0x%x", policy); }

// ---------------------------------------------------------------- IGameInputReading
uint32_t STDMETHODCALLTYPE reading_kind(Reading* r) { return r->kind; }
uint64_t STDMETHODCALLTYPE reading_sequence(Reading* r, uint32_t) { return r->sequence; }
uint64_t STDMETHODCALLTYPE reading_timestamp(Reading* r) { return r->timestamp; }
void STDMETHODCALLTYPE reading_device(Reading* r, void** device) {
    if (device) *device = &g_devices[r->index];
}
bool STDMETHODCALLTYPE reading_raw(Reading*, void** report) {
    if (report) *report = nullptr;
    return false;
}
uint32_t STDMETHODCALLTYPE reading_count(Reading*) { return 0; }
uint32_t STDMETHODCALLTYPE reading_array(Reading*, uint32_t, void*) { return 0; }
bool STDMETHODCALLTYPE reading_no_state(Reading*, void*) { return false; }
bool STDMETHODCALLTYPE reading_gamepad(Reading* r, GamepadStateV0* out) {
    GI_LOG("GetGamepadState", "reading=%p buttons=0x%x", static_cast<void*>(r), r->gamepad.buttons);
    if (out) *out = r->gamepad;
    return out != nullptr;
}
bool STDMETHODCALLTYPE reading_mouse(Reading* r, void*) {
    GI_LOG("GetMouseState", "reading=%p -> false", static_cast<void*>(r));
    return false;
}
uint32_t STDMETHODCALLTYPE reading_key_state(Reading* r, uint32_t count, void*) {
    GI_LOG("GetKeyState", "reading=%p count=%u -> 0", static_cast<void*>(r), count);
    return 0;
}

// ---------------------------------------------------------------- IGameInputDevice
const void* STDMETHODCALLTYPE device_info(Device* d) {
    GI_LOG("GetDeviceInfo", "device=%p (xinput %u)", static_cast<void*>(d), d->index);
    return &d->info;
}
uint32_t STDMETHODCALLTYPE device_status(Device* d) {
    XINPUT_STATE s;
    const uint32_t status = read_pad(d->index, &s) ? kStatusConnected | kStatusInputEnabled | kStatusOutputEnabled : 0;
    GI_LOG("GetDeviceStatus", "device=%p -> 0x%x", static_cast<void*>(d), status);
    return status;
}
void STDMETHODCALLTYPE device_battery(Device*, void* state) {
    if (state) std::memset(state, 0, 20);  // GameInputBatteryState: four floats and the status (0, not present)
}
HRESULT STDMETHODCALLTYPE device_create_ff_effect(Device*, uint32_t motor, const void*, void** effect) {
    if (effect) *effect = nullptr;
    GI_LOG("CreateForceFeedbackEffect", "motor=%u -> E_NOTIMPL", motor);
    return E_NOTIMPL;
}
bool STDMETHODCALLTYPE device_ff_powered(Device*, uint32_t) { return false; }
void STDMETHODCALLTYPE device_ff_gain(Device*, uint32_t, float) {}
HRESULT STDMETHODCALLTYPE device_haptic(Device*, uint32_t, const void*) { return E_NOTIMPL; }
void STDMETHODCALLTYPE device_rumble(Device* d, const float* params) {
    // GameInputRumbleParams: lowFrequency, highFrequency, leftTrigger, rightTrigger (0..1).
    auto word = [](float v) { return static_cast<WORD>((v < 0 ? 0 : v > 1 ? 1 : v) * 65535.0f); };
    XINPUT_VIBRATION v{params ? word(params[0]) : WORD(0), params ? word(params[1]) : WORD(0)};
    if (g_set_state) g_set_state(d->index, &v);
    GI_LOG("SetRumbleState", "device=%p low=%u high=%u", static_cast<void*>(d), v.wLeftMotorSpeed, v.wRightMotorSpeed);
}
void STDMETHODCALLTYPE device_void_bool(Device*, bool) {}
void STDMETHODCALLTYPE device_void(Device*) {}
HRESULT STDMETHODCALLTYPE device_raw(Device* d, u64 a, u64 b, u64 c) {
    GI_LOG("raw-device-call", "device=%p a=0x%llx b=0x%llx c=0x%llx -> E_NOTIMPL", static_cast<void*>(d), a, b, c);
    return E_NOTIMPL;
}
bool STDMETHODCALLTYPE device_acquire(Device*, uint64_t) { return false; }

// ---------------------------------------------------------------- IGameInputDispatcher
bool STDMETHODCALLTYPE dispatch(Object*, uint64_t quota) {
    GI_LOG("Dispatch", "quota=%llu -> false", static_cast<u64>(quota));
    return false;
}
HRESULT STDMETHODCALLTYPE open_wait_handle(Object*, HANDLE* handle) {
    GI_LOG("OpenWaitHandle", "out=%p", static_cast<void*>(handle));
    if (!handle) return E_POINTER;
    *handle = CreateEventW(nullptr, TRUE, FALSE, nullptr);  // never signalled: there is no background work
    return *handle ? S_OK : HRESULT_FROM_WIN32(GetLastError());
}

template <class F>
void* fn(F f) {
    return reinterpret_cast<void*>(f);
}

std::once_flag g_tables_once;
void build_tables() {
    std::call_once(g_tables_once, [] {
        g_input_vt = unknown_table<0>(std::make_index_sequence<kSlots>());
        g_reading_vt = unknown_table<1>(std::make_index_sequence<kSlots>());
        g_device_vt = unknown_table<2>(std::make_index_sequence<kSlots>());
        g_dispatcher_vt = unknown_table<3>(std::make_index_sequence<kSlots>());
        for (Vtable* vt : {&g_input_vt, &g_device_vt, &g_dispatcher_vt}) {
            (*vt)[0] = fn(&qi);
            (*vt)[1] = fn(&static_addref);
            (*vt)[2] = fn(&static_release);
        }
        auto& i = g_input_vt;
        i[3] = fn(&get_current_timestamp);
        i[4] = fn(&get_current_reading);
        i[5] = fn(&get_next_reading);
        i[6] = fn(&get_previous_reading);
        i[7] = fn(&get_temporal_reading);
        i[8] = fn(&register_reading_callback);
        i[9] = fn(&register_device_callback);
        i[10] = fn(&register_guide_button_callback);
        i[11] = fn(&register_keyboard_layout_callback);
        i[12] = fn(&stop_callback);
        i[13] = fn(&unregister_callback);
        i[14] = fn(&create_dispatcher);
        i[15] = fn(&create_aggregate_device);
        i[16] = fn(&find_device_from_id);
        i[17] = fn(&find_device_from_object);
        i[18] = fn(&find_device_from_platform_handle);
        i[19] = fn(&find_device_from_platform_string);
        i[20] = fn(&enable_oem_device_support);
        i[21] = fn(&set_focus_policy);

        auto& r = g_reading_vt;
        r[0] = fn(&qi);
        r[1] = fn(&reading_addref);
        r[2] = fn(&reading_release);
        r[3] = fn(&reading_kind);
        r[4] = fn(&reading_sequence);
        r[5] = fn(&reading_timestamp);
        r[6] = fn(&reading_device);
        r[7] = fn(&reading_raw);
        r[8] = fn(&reading_count);    // GetControllerAxisCount
        r[9] = fn(&reading_array);    // GetControllerAxisState
        r[10] = fn(&reading_count);   // GetControllerButtonCount
        r[11] = fn(&reading_array);   // GetControllerButtonState
        r[12] = fn(&reading_count);   // GetControllerSwitchCount
        r[13] = fn(&reading_array);   // GetControllerSwitchState
        r[14] = fn(&reading_count);   // GetKeyCount
        r[15] = fn(&reading_key_state);
        r[16] = fn(&reading_mouse);
        r[17] = fn(&reading_count);   // GetTouchCount
        r[18] = fn(&reading_array);   // GetTouchState
        r[19] = fn(&reading_no_state);  // GetMotionState
        r[20] = fn(&reading_no_state);  // GetArcadeStickState
        r[21] = fn(&reading_no_state);  // GetFlightStickState
        r[22] = fn(&reading_gamepad);
        r[23] = fn(&reading_no_state);  // GetRacingWheelState
        r[24] = fn(&reading_no_state);  // GetUiNavigationState

        auto& d = g_device_vt;
        d[3] = fn(&device_info);
        d[4] = fn(&device_status);
        d[5] = fn(&device_battery);
        d[6] = fn(&device_create_ff_effect);
        d[7] = fn(&device_ff_powered);
        d[8] = fn(&device_ff_gain);
        d[9] = fn(&device_haptic);
        d[10] = fn(&device_rumble);
        d[11] = fn(&device_void_bool);  // SetInputSynchronizationState
        d[12] = fn(&device_void);       // SendInputSynchronizationHint
        d[13] = fn(&device_void);       // PowerOff
        for (int slot = 14; slot <= 19; ++slot) d[slot] = fn(&device_raw);  // raw reports, features, output, ioctl
        d[20] = fn(&device_acquire);
        d[21] = fn(&device_void);       // ReleaseExclusiveRawDeviceAccess

        g_dispatcher_vt[3] = fn(&dispatch);
        g_dispatcher_vt[4] = fn(&open_wait_handle);

        g_input.vtbl = g_input_vt.data();
        g_dispatcher.vtbl = g_dispatcher_vt.data();
        for (uint32_t n = 0; n < XUSER_MAX_COUNT; ++n) {
            Device& dev = g_devices[n];
            dev.vtbl = g_device_vt.data();
            dev.index = n;
            std::memset(dev.info_bytes, 0, sizeof dev.info_bytes);
            DeviceInfoV0& info = dev.info;
            info.info_size = sizeof(DeviceInfoV0);
            info.vendor_id = 0x045e;  // a Microsoft Xbox controller, as XInput reports one
            info.product_id = 0x0b12;
            info.usage_page = 0x01;
            info.usage_id = 0x05;  // HID generic desktop: gamepad
            std::snprintf(reinterpret_cast<char*>(info.device_id), sizeof info.device_id, "x2w-xinput-pad-%u", n);
            std::memcpy(info.device_root_id, info.device_id, sizeof info.device_id);
            info.device_family = 1;  // GameInputFamilyXboxOne
            info.supported_input = kKindGamepad;
            info.supported_rumble_motors = 0x3;  // low and high frequency
            for (auto& p : info.pointers) p = g_zeros;
        }
    });
}

}  // namespace

long logged_calls() { return g_logged; }

}  // namespace x2w_sys::gi0

extern "C" HRESULT WINAPI X2wGameInputCreateV0(void** out) {
    using namespace x2w_sys::gi0;
    init();
    build_tables();
    GI_LOG("GameInputCreate", "out=%p -> S_OK (v0 facade %p)", static_cast<void*>(out), static_cast<void*>(&g_input));
    if (!out) return E_POINTER;
    *out = &g_input;
    return S_OK;
}
