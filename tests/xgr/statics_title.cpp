// Function-local statics ("magic statics") in a title built like the GDK samples (dynamic C runtime, /MD):
// MSVC guards each one with a global guard word compared against the thread-local _Init_thread_epoch,
// whose template value is INT_MIN. If a mapped image's implicit TLS block read zero, every guard would look
// initialized and each static would stay zero; the GDK samples' UITK then registers two element classes
// under the same empty ID and throws. Prints the epoch and the statics, returns 0x5a when all is well.
#include <windows.h>

#include <climits>
#include <cstdio>
#include <string>

extern "C" __declspec(thread) int _Init_thread_epoch;

namespace {
const std::string& first() { static std::string id("panel"); return id; }
const std::string& second() { static std::string id("statictext"); return id; }
const std::string& third() { static std::string id("image"); return id; }
int counter() { static int value = 41; return ++value; }
}  // namespace

// Then loads a DLL with implicit TLS of its own (the gateway, shims\x2w_xgr.dll beside this EXE), as the
// samples do when they load xgameruntime.dll, and checks the epoch and one more static after it.
int main() {
    const int epoch = _Init_thread_epoch;
    const bool before = first() == "panel" && second() == "statictext" && counter() == 42 && counter() == 43;
    const int epoch_after_two = _Init_thread_epoch;
    wchar_t path[MAX_PATH];
    const DWORD length = GetModuleFileNameW(nullptr, path, MAX_PATH);
    std::wstring dll(path, length);
    dll = dll.substr(0, dll.find_last_of(L'\\') + 1) + L"shims\\x2w_xgr.dll";
    HMODULE loaded = LoadLibraryW(dll.c_str());
    const int epoch_after_load = _Init_thread_epoch;
    const bool after = third() == "image";
    std::printf("xgr-statics epoch=%d after-two=%d loaded=%d after-load=%d first=%s second=%s third=%s ok=%d/%d\n",
                epoch, epoch_after_two, loaded ? 1 : 0, epoch_after_load, first().c_str(), second().c_str(),
                third().c_str(), before ? 1 : 0, after ? 1 : 0);
    return before && after ? 0x5a : 0x5b;
}
