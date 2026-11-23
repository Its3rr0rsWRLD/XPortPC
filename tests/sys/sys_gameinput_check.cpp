#include "check.h"
#include "sys_gameinput.h"

#include <cstring>

using namespace x2w_sys;
using namespace x2w_sys::gi;

namespace {
XINPUT_STATE g_states[XUSER_MAX_COUNT];
bool g_present[XUSER_MAX_COUNT];

DWORD WINAPI fake_get_state(DWORD i, XINPUT_STATE* s) {
    if (i >= XUSER_MAX_COUNT || !g_present[i]) return ERROR_DEVICE_NOT_CONNECTED;
    *s = g_states[i];
    return ERROR_SUCCESS;
}
DWORD WINAPI fake_caps(DWORD i, DWORD, XINPUT_CAPABILITIES* c) {
    std::memset(c, 0, sizeof *c);
    c->Type = XINPUT_DEVTYPE_GAMEPAD;
    c->SubType = static_cast<BYTE>(i + 1);
    return ERROR_SUCCESS;
}
}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: sys_gameinput_check <fake_runtime.dll>\n"); return 2; }
    chk::capture();

    // ---- state conversion --------------------------------------------------------------------------
    {
        XINPUT_STATE s{};
        s.dwPacketNumber = 77;
        s.Gamepad.wButtons = XINPUT_GAMEPAD_A | XINPUT_GAMEPAD_START | XINPUT_GAMEPAD_DPAD_LEFT | XINPUT_GAMEPAD_RIGHT_THUMB;
        s.Gamepad.bLeftTrigger = 255;
        s.Gamepad.bRightTrigger = 0;
        s.Gamepad.sThumbLX = -32768;
        s.Gamepad.sThumbLY = 32767;
        s.Gamepad.sThumbRX = 0;
        const GamepadState g = convert(s);
        CHECK_EQ(g.buttons, kA | kMenu | kDPadLeft | kRightThumbstick);
        CHECK(g.left_trigger == 1.0f && g.right_trigger == 0.0f);
        CHECK(g.left_x == -1.0f && g.left_y == 1.0f && g.right_x == 0.0f);
        CHECK_EQ(g.packet, 77u);
        // Every button maps to its own distinct bit with the documented value.
        struct { WORD xi; uint32_t gi; } all[] = {
            {XINPUT_GAMEPAD_START, 0x1}, {XINPUT_GAMEPAD_BACK, 0x2}, {XINPUT_GAMEPAD_A, 0x4}, {XINPUT_GAMEPAD_B, 0x8},
            {XINPUT_GAMEPAD_X, 0x10}, {XINPUT_GAMEPAD_Y, 0x20}, {XINPUT_GAMEPAD_DPAD_UP, 0x40}, {XINPUT_GAMEPAD_DPAD_DOWN, 0x80},
            {XINPUT_GAMEPAD_DPAD_LEFT, 0x100}, {XINPUT_GAMEPAD_DPAD_RIGHT, 0x200}, {XINPUT_GAMEPAD_LEFT_SHOULDER, 0x400},
            {XINPUT_GAMEPAD_RIGHT_SHOULDER, 0x800}, {XINPUT_GAMEPAD_LEFT_THUMB, 0x1000}, {XINPUT_GAMEPAD_RIGHT_THUMB, 0x2000}};
        for (const auto& b : all) {
            XINPUT_STATE t{};
            t.Gamepad.wButtons = b.xi;
            CHECK_EQ(convert(t).buttons, b.gi);
        }
        XINPUT_STATE none{};
        CHECK_EQ(convert(none).buttons, 0u);  // control
    }

    // ---- fallback enumeration with an injected XInput ------------------------------------------------
    {
        XInputApi api;
        api.get_state = &fake_get_state;
        api.get_capabilities = &fake_caps;
        Fallback fb(api);
        g_present[0] = true;
        g_present[2] = true;
        g_states[2].Gamepad.wButtons = XINPUT_GAMEPAD_B;
        auto devs = fb.enumerate();
        CHECK_EQ(devs.size(), 2u);
        CHECK(devs.size() == 2 && devs[0].index == 0 && devs[1].index == 2 && devs[1].subtype == 3);
        CHECK_EQ(chk::count("device 0 connected"), 1);
        CHECK_EQ(chk::count("device 2 connected"), 1);
        fb.enumerate();  // unchanged: no new connect lines
        CHECK_EQ(chk::count("connected (xinput"), 2);
        GamepadState g;
        CHECK(fb.read(2, &g) && g.buttons == kB);
        CHECK(!fb.read(1, &g));
        CHECK(!fb.read(9, &g));
        g_present[2] = false;
        devs = fb.enumerate();
        CHECK_EQ(devs.size(), 1u);
        CHECK_EQ(chk::count("device 2 disconnected"), 1);
        g_present[2] = true;
        fb.enumerate();
        CHECK_EQ(chk::count("device 2 connected"), 2);  // a reconnect is a new event
    }

    // ---- forwarding to a runtime ---------------------------------------------------------------------
    reset_for_test();
    {
        void* out = nullptr;
        CHECK(select_backend(argv[1]) == Backend::Redist);
        CHECK(X2wGameInputCreate(&out) == S_OK);
        CHECK_EQ(reinterpret_cast<uintptr_t>(out), 0x1234u);
        CHECK_EQ(X2wGameInputBackend(), 1);
        CHECK_EQ(chk::count("forwarding to"), 1);
    }
    // ---- fallback: runtime disabled -------------------------------------------------------------------
    reset_for_test();
    {
        void* out = reinterpret_cast<void*>(0x77);
        CHECK(select_backend("off") == Backend::XInput);  // XInput ships with Windows
        CHECK(X2wGameInputCreate(&out) == X2W_E_GAMEINPUT_FALLBACK);
        CHECK(out == nullptr);
        CHECK_EQ(X2wGameInputBackend(), 2);
        uint32_t idx[XUSER_MAX_COUNT];
        const int n = X2wGameInputFallbackEnumerate(idx, XUSER_MAX_COUNT);  // real pads, if any
        CHECK(n >= 0 && n <= static_cast<int>(XUSER_MAX_COUNT));
        std::printf("gameinput fallback: %d real XInput device(s)\n", n);
        GamepadState g;
        CHECK_EQ(X2wGameInputFallbackRead(3, &g) == 1, X2wGameInputFallbackRead(3, &g) == 1);  // no crash either way
    }
    // ---- no such runtime file: fall through to the fallback --------------------------------------------
    reset_for_test();
    {
        const Backend b = select_backend("C:\\definitely\\not\\here\\GameInputRedist.dll");
        CHECK(b == Backend::Redist || b == Backend::XInput);  // a real runtime on this PC is a valid outcome
        std::printf("gameinput without the named file: backend %d\n", static_cast<int>(b));
        CHECK(select_backend(nullptr) == current_backend());
    }
    reset_for_test();
    return finish("sys_gameinput");
}
