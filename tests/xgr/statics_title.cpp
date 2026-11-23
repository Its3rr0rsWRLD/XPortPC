// Function-local statics ("magic statics") in a title built like the GDK samples (dynamic C runtime, /MD):
// MSVC guards each one with a global guard word compared against the thread-local _Init_thread_epoch,
// whose template value is INT_MIN. If a mapped image's implicit TLS block read zero, every guard would look
// initialized and each static would stay zero; the GDK samples' UITK then registers two element classes
// under the same empty ID and throws. Prints the epoch and the statics, returns 0x5a when all is well.
#include <climits>
#include <cstdio>
#include <string>

extern "C" __declspec(thread) int _Init_thread_epoch;

namespace {
const std::string& first() { static std::string id("panel"); return id; }
const std::string& second() { static std::string id("statictext"); return id; }
int counter() { static int value = 41; return ++value; }
}  // namespace

int main() {
    const int epoch = _Init_thread_epoch;
    const bool ok = first() == "panel" && second() == "statictext" && counter() == 42 && counter() == 43;
    std::printf("xgr-statics epoch=%d first=%s second=%s ok=%d\n", epoch, first().c_str(), second().c_str(), ok ? 1 : 0);
    return ok ? 0x5a : 0x5b;
}
