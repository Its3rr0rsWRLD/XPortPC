// GameInput v0 facade: an IGameInput object with the GDK-era (v0) vtable layout, backed by XInput.
//
// Why. A console title built against the GDK's GameInput.h calls IGameInput through the v0 vtable. The GameInput
// runtime on Windows (GameInput.dll / GameInputRedist.dll) implements a newer interface whose slots are not the v0
// ones (v1 removed and reordered members, see the "Version History" sections of the public GameInput reference on
// learn.microsoft.com), so a v0 caller that reaches it calls the wrong methods with the wrong arguments. The
// gameinput.dll shim (src/sys/gameinput_shim.cpp) hands such a title this object instead.
//
// Layout. Written from the public v0 reference pages (IGameInput, IGameInputReading, IGameInputDevice,
// IGameInputDispatcher member lists), in declaration order after IUnknown:
//   IGameInput          3 GetCurrentTimestamp  4 GetCurrentReading  5 GetNextReading  6 GetPreviousReading
//                       7 GetTemporalReading  8 RegisterReadingCallback  9 RegisterDeviceCallback
//                       10 RegisterGuideButtonCallback  11 RegisterKeyboardLayoutCallback  12 StopCallback
//                       13 UnregisterCallback  14 CreateDispatcher  15 CreateAggregateDevice  16 FindDeviceFromId
//                       17 FindDeviceFromObject  18 FindDeviceFromPlatformHandle  19 FindDeviceFromPlatformString
//                       20 EnableOemDeviceSupport  21 SetFocusPolicy
//   IGameInputReading   3 GetInputKind ... 22 GetGamepadState  23 GetRacingWheelState  24 GetUiNavigationState
//   IGameInputDevice    3 GetDeviceInfo  4 GetDeviceStatus  5 GetBatteryState ... 10 SetRumbleState ... 21
//   IGameInputDispatcher 3 Dispatch  4 OpenWaitHandle
// Every vtable has kSlots entries. A slot past the known ones logs "unknown-slot IFACE[N]" with its first three
// integer arguments and returns E_NOTIMPL, so a title built against a layout with more members never jumps into
// garbage. QueryInterface answers every IID with the same object (the IID is logged).
//
// Behaviour. Gamepad readings come from XInput (GameInputGamepadState: buttons, triggers, sticks). Each connected
// XInput pad is an IGameInputDevice; RegisterDeviceCallback reports the pads that are connected when it is called
// (synchronously for blocking enumeration, from a worker thread for asynchronous enumeration). Keyboard, mouse,
// raw reports, force feedback and the other kinds answer "no reading" / not implemented. Hot plugging after the
// registration is not reported.
//
// Logging. The first N calls of each method (X2W_GAMEINPUT_LOG_CALLS, default 8) are logged with their arguments,
// on stderr ("[x2w] gameinput: ...") and, under x2w_launch, in the run log as "shim-gameinput METHOD ARGS".
// X2W_GAMEINPUT_PADS=off hides the XInput pads (no devices, no readings).
#pragma once

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <cstdint>

namespace x2w_sys::gi0 {

constexpr int kSlots = 64;

// GameInputKind values (public reference).
constexpr uint32_t kKindUnknown = 0, kKindGamepad = 0x40000;
// GameInputDeviceStatus values.
constexpr uint32_t kStatusConnected = 0x1, kStatusInputEnabled = 0x2, kStatusOutputEnabled = 0x4;
// GameInputEnumerationKind values.
constexpr uint32_t kEnumNone = 0, kEnumAsync = 1, kEnumBlocking = 2;

// GAMEINPUT_E_* (facility 0x38A, public reference).
constexpr HRESULT kDeviceDisconnected = static_cast<HRESULT>(0x838A0001);
constexpr HRESULT kDeviceNotFound = static_cast<HRESULT>(0x838A0002);
constexpr HRESULT kReadingNotFound = static_cast<HRESULT>(0x838A0003);

// GameInputGamepadState.
struct GamepadStateV0 {
    uint32_t buttons;
    float left_trigger, right_trigger;
    float left_x, left_y, right_x, right_y;
};

// Calls logged so far, for tests.
long logged_calls();

}  // namespace x2w_sys::gi0

extern "C" {
// GameInputCreate for v0 callers: always succeeds with the facade (one shared object, a new reference each call).
HRESULT WINAPI X2wGameInputCreateV0(void** out);
}
