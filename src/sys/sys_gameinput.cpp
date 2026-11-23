#include "sys_gameinput.h"

#include "sys_common.h"

#include <mutex>

namespace x2w_sys::gi {
namespace {
std::mutex g_mutex;
Backend g_backend = Backend::None;
bool g_selected = false;
HMODULE g_redist = nullptr;
HRESULT(WINAPI* g_create)(void**) = nullptr;
XInputApi g_xinput;
Fallback* g_fallback = nullptr;
std::string g_override;

float stick(SHORT v) {
    const float f = static_cast<float>(v) / 32767.0f;
    return f < -1.0f ? -1.0f : f;
}
}  // namespace

GamepadState convert(const XINPUT_STATE& s) {
    GamepadState g;
    const WORD b = s.Gamepad.wButtons;
    auto bit = [&](WORD xi, uint32_t gi) { if (b & xi) g.buttons |= gi; };
    bit(XINPUT_GAMEPAD_START, kMenu);
    bit(XINPUT_GAMEPAD_BACK, kView);
    bit(XINPUT_GAMEPAD_A, kA);
    bit(XINPUT_GAMEPAD_B, kB);
    bit(XINPUT_GAMEPAD_X, kX);
    bit(XINPUT_GAMEPAD_Y, kY);
    bit(XINPUT_GAMEPAD_DPAD_UP, kDPadUp);
    bit(XINPUT_GAMEPAD_DPAD_DOWN, kDPadDown);
    bit(XINPUT_GAMEPAD_DPAD_LEFT, kDPadLeft);
    bit(XINPUT_GAMEPAD_DPAD_RIGHT, kDPadRight);
    bit(XINPUT_GAMEPAD_LEFT_SHOULDER, kLeftShoulder);
    bit(XINPUT_GAMEPAD_RIGHT_SHOULDER, kRightShoulder);
    bit(XINPUT_GAMEPAD_LEFT_THUMB, kLeftThumbstick);
    bit(XINPUT_GAMEPAD_RIGHT_THUMB, kRightThumbstick);
    g.left_trigger = s.Gamepad.bLeftTrigger / 255.0f;
    g.right_trigger = s.Gamepad.bRightTrigger / 255.0f;
    g.left_x = stick(s.Gamepad.sThumbLX);
    g.left_y = stick(s.Gamepad.sThumbLY);
    g.right_x = stick(s.Gamepad.sThumbRX);
    g.right_y = stick(s.Gamepad.sThumbRY);
    g.packet = s.dwPacketNumber;
    return g;
}

bool load_xinput(XInputApi* api) {
    for (const wchar_t* name : {L"xinput1_4.dll", L"xinput1_3.dll", L"xinput9_1_0.dll"}) {
        HMODULE m = LoadLibraryExW(name, nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!m) continue;
        auto st = reinterpret_cast<decltype(api->get_state)>(GetProcAddress(m, "XInputGetState"));
        if (!st) { FreeLibrary(m); continue; }
        api->get_state = st;
        api->get_capabilities = reinterpret_cast<decltype(api->get_capabilities)>(GetProcAddress(m, "XInputGetCapabilities"));
        api->module = m;
        return true;
    }
    return false;
}

std::vector<Device> Fallback::enumerate() {
    std::vector<Device> out;
    for (DWORD i = 0; i < XUSER_MAX_COUNT; ++i) {
        XINPUT_STATE st{};
        const bool now = api_.get_state && api_.get_state(i, &st) == ERROR_SUCCESS;
        if (now) {
            Device d;
            d.index = i;
            XINPUT_CAPABILITIES caps{};
            if (api_.get_capabilities && api_.get_capabilities(i, 0, &caps) == ERROR_SUCCESS) {
                d.type = caps.Type;
                d.subtype = caps.SubType;
            }
            out.push_back(d);
            if (!known_[i] || !connected_[i])
                log("gameinput: fallback device %u connected (xinput type %u subtype %u)", i, d.type, d.subtype);
        } else if (known_[i] && connected_[i]) {
            log("gameinput: fallback device %u disconnected", i);
        }
        connected_[i] = now;
        known_[i] = true;
    }
    return out;
}

bool Fallback::read(uint32_t index, GamepadState* out) {
    if (index >= XUSER_MAX_COUNT || !api_.get_state) return false;
    XINPUT_STATE st{};
    if (api_.get_state(index, &st) != ERROR_SUCCESS) return false;
    if (out) *out = convert(st);
    return true;
}

Backend select_backend(const char* dll_override) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_selected) return g_backend;
    g_selected = true;
    std::string first = dll_override ? dll_override : (g_override.empty() ? get_env("X2W_GAMEINPUT_DLL") : g_override);
    if (first != "off") {
        std::vector<std::wstring> candidates;
        if (!first.empty()) candidates.push_back(widen(first));
        candidates.push_back(L"GameInputRedist.dll");
        candidates.push_back(L"GameInput.dll");
        // By full path too: when x2w's gameinput.dll shim is loaded, the bare name resolves to it.
        wchar_t system[MAX_PATH];
        const UINT length = GetSystemDirectoryW(system, MAX_PATH);
        if (length && length < MAX_PATH) candidates.push_back(std::wstring(system, length) + L"\\GameInput.dll");
        for (const auto& name : candidates) {
            const std::string shown = narrow(name.substr(name.find_last_of(L"\\/") == std::wstring::npos ? 0 : name.find_last_of(L"\\/") + 1));
            HMODULE m = LoadLibraryExW(name.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_SYSTEM32);
            if (!m) continue;
            if (GetProcAddress(m, "X2wGameInputIsShim")) {
                // x2w's own gameinput.dll (a shims directory, already loaded for the title): not a runtime.
                log("gameinput: %s is the x2w shim, not a runtime; skipped", shown.c_str());
                FreeLibrary(m);
                continue;
            }
            auto fn = reinterpret_cast<HRESULT(WINAPI*)(void**)>(GetProcAddress(m, "GameInputCreate"));
            if (!fn) {
                log("gameinput: %s loaded but has no GameInputCreate", shown.c_str());
                FreeLibrary(m);
                continue;
            }
            g_redist = m;
            g_create = fn;
            g_backend = Backend::Redist;
            log("gameinput: forwarding to %s", shown.c_str());
            return g_backend;
        }
        log("gameinput: no GameInput runtime found; using the XInput fallback");
    } else {
        log("gameinput: runtime disabled by configuration; using the XInput fallback");
    }
    if (load_xinput(&g_xinput)) {
        g_fallback = new Fallback(g_xinput);
        g_backend = Backend::XInput;
        for (const auto& d : g_fallback->enumerate()) (void)d;
    } else {
        log("gameinput: XInput could not be loaded either; no input backend");
        g_backend = Backend::None;
    }
    return g_backend;
}

Backend current_backend() { return g_backend; }

void reset_for_test() {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_redist) FreeLibrary(g_redist);
    if (g_xinput.module) FreeLibrary(g_xinput.module);
    delete g_fallback;
    g_fallback = nullptr;
    g_redist = nullptr;
    g_xinput = {};
    g_create = nullptr;
    g_backend = Backend::None;
    g_selected = false;
}

void apply_config_line(const std::string& key, const std::string& value) {
    if (key == "gameinput.dll") g_override = value;
}

}  // namespace x2w_sys::gi

using namespace x2w_sys::gi;

extern "C" {
HRESULT WINAPI X2wGameInputCreate(void** out) {
    if (!out) return E_POINTER;
    *out = nullptr;
    const Backend b = select_backend();
    if (b == Backend::Redist) return g_create(out);
    x2w_sys::log_once("gameinput:create", "gameinput: GameInputCreate has no runtime to forward to; returning the fallback status");
    return X2W_E_GAMEINPUT_FALLBACK;
}

int WINAPI X2wGameInputBackend(void) { return static_cast<int>(select_backend()); }

int WINAPI X2wGameInputFallbackEnumerate(uint32_t* indices, uint32_t capacity) {
    if (select_backend() != Backend::XInput || !g_fallback) return 0;
    const auto devices = g_fallback->enumerate();
    uint32_t n = 0;
    for (const auto& d : devices)
        if (n < capacity && indices) indices[n++] = d.index;
    return static_cast<int>(devices.size());
}

int WINAPI X2wGameInputFallbackRead(uint32_t index, GamepadState* out) {
    if (select_backend() != Backend::XInput || !g_fallback) return 0;
    return g_fallback->read(index, out) ? 1 : 0;
}
}
