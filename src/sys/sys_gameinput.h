// GameInput: forward to the PC GameInput runtime, or fall back to XInput.
//
// Forwarding. The public PC runtime is GameInputRedist.dll (sideload or GameInputRedist.msi) or the GameInput.dll
// that modern Windows ships; both export GameInputCreate (Microsoft.GameInput NuGet, GDK input docs). When one
// loads, X2wGameInputCreate returns the runtime's own IGameInput, so the title talks to the real thing.
//
// Fallback. When no runtime loads, there is no IGameInput to hand out. The fallback keeps the whole input path
// testable and gives the gateway a state source: it enumerates XInput pads, logs connects and disconnects, and
// reports gamepad state in GameInput's units and button bits (GameInputGamepadButtons values from the public
// reference). X2wGameInputCreate then returns X2W_E_GAMEINPUT_FALLBACK with *out = null; a COM facade that turns
// this state into an IGameInput object is a follow-up that needs the public NuGet header at build time.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <xinput.h>

namespace x2w_sys::gi {

// Values of GameInputGamepadButtons (public reference, GDK input docs).
enum GamepadButtons : uint32_t {
    kMenu = 0x1, kView = 0x2, kA = 0x4, kB = 0x8, kX = 0x10, kY = 0x20,
    kDPadUp = 0x40, kDPadDown = 0x80, kDPadLeft = 0x100, kDPadRight = 0x200,
    kLeftShoulder = 0x400, kRightShoulder = 0x800, kLeftThumbstick = 0x1000, kRightThumbstick = 0x2000,
};

struct GamepadState {
    uint32_t buttons = 0;
    float left_trigger = 0, right_trigger = 0;  // 0..1
    float left_x = 0, left_y = 0, right_x = 0, right_y = 0;  // -1..1, no dead zone applied
    uint32_t packet = 0;
};

GamepadState convert(const XINPUT_STATE& state);

struct XInputApi {
    DWORD(WINAPI* get_state)(DWORD, XINPUT_STATE*) = nullptr;
    DWORD(WINAPI* get_capabilities)(DWORD, DWORD, XINPUT_CAPABILITIES*) = nullptr;
    HMODULE module = nullptr;
};
// Loads xinput1_4.dll, then xinput1_3.dll, then xinput9_1_0.dll. False when none loads.
bool load_xinput(XInputApi* api);

struct Device {
    uint32_t index = 0;
    uint8_t type = 0, subtype = 0;
};

class Fallback {
public:
    explicit Fallback(const XInputApi& api) : api_(api) {}
    // Connected pads in index order. Logs each connect and disconnect once per change.
    std::vector<Device> enumerate();
    bool read(uint32_t index, GamepadState* out);

private:
    XInputApi api_;
    bool connected_[XUSER_MAX_COUNT] = {};
    bool known_[XUSER_MAX_COUNT] = {};
};

enum class Backend { None = 0, Redist = 1, XInput = 2 };

constexpr HRESULT X2W_E_GAMEINPUT_FALLBACK = static_cast<HRESULT>(0xA2570001);

// Chooses a backend once. `dll_override` (or env X2W_GAMEINPUT_DLL) names the runtime to try first; "off" forces
// the fallback. Returns the chosen backend and logs the decision.
Backend select_backend(const char* dll_override = nullptr);
Backend current_backend();
void reset_for_test();
void apply_config_line(const std::string& key, const std::string& value);

}  // namespace x2w_sys::gi

extern "C" {
// Console-facing entry: same signature as the public GameInputCreate (IGameInput** out).
HRESULT WINAPI X2wGameInputCreate(void** out);
// Fallback state access for the gateway; false when the fallback is not active or the pad is absent.
int WINAPI X2wGameInputFallbackEnumerate(uint32_t* indices, uint32_t capacity);
int WINAPI X2wGameInputFallbackRead(uint32_t index, x2w_sys::gi::GamepadState* out);
int WINAPI X2wGameInputBackend(void);
}
