// gameinput.dll for console titles: GameInputCreate hands out x2w_sys's GameInput v0 facade
// (src/sys/sys_gameinput_v0.h). x2w_launch loads this from its shims directory for a title's gameinput.dll imports
// and dynamic loads, so a title built against the GDK's v0 GameInput.h never reaches the newer Windows runtime,
// whose vtable differs. x2w_sys.dll is found beside this DLL (the launcher loads shims with
// LOAD_WITH_ALTERED_SEARCH_PATH) or is already loaded.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

extern "C" HRESULT WINAPI X2wGameInputCreateV0(void** out);

extern "C" HRESULT WINAPI GameInputCreate(void** out) { return X2wGameInputCreateV0(out); }

// Marker: x2w_sys does not forward to this DLL when it looks for the Windows GameInput runtime.
extern "C" int WINAPI X2wGameInputIsShim(void) { return 1; }
