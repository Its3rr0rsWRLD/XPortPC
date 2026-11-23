// Thread-start stress title for x2w_launch: built with whole-program optimization (/GL, /LTCG) and the static C
// runtime, so its thread_local data is reached through TLS slot 0 (the launcher's slot-0 alias) and initialized
// and destroyed by the runtime's TLS callbacks. It has its own TLS callback, which checks the new thread's block
// on DLL_THREAD_ATTACH and DLL_THREAD_DETACH, and imports a package DLL with its own TLS and a DllMain
// (tests/native/thread_stress_pkg.cpp). main starts 64 threads at once, two rounds of 32 (CreateThread,
// _beginthreadex and std::thread in turn), each of which checks the template of both images, writes its own
// values and reads them back. Exit 0x1c5 when every check held, otherwise 0x200 | the number of failures (at
// most 0xff); one output line with the counts.
#include <windows.h>
#include <process.h>

#include <atomic>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>

extern "C" __declspec(dllimport) int __cdecl stress_pkg_touch(int value);
extern "C" __declspec(dllimport) long __cdecl stress_pkg_bad();

namespace {
constexpr unsigned kTemplate = 0x7e3a1c55u;
constexpr unsigned kMagic = 0x5157a7e5u;
std::atomic<long> failures{0};
std::atomic<long> workers_ok{0};
std::atomic<long> callbacks{0};

struct Local {
    unsigned magic = kMagic;
    std::string name;
    Local() : name("local") {}
    ~Local() {
        if (magic != kMagic) ++failures;
        magic = 0;
    }
};

thread_local unsigned t_value = kTemplate;
thread_local char t_pad[1024] = {7};
thread_local Local t_local;

void NTAPI stress_tls(PVOID, DWORD reason, PVOID) {
    if (reason == DLL_THREAD_ATTACH) {
        ++callbacks;
        if (t_value != kTemplate || t_pad[0] != 7 || t_local.magic != kMagic || t_local.name != "local") ++failures;
    } else if (reason == DLL_THREAD_DETACH) {
        // The runtime's thread_local destructors (an earlier callback) have run; trivial data is still there.
        if (t_pad[0] != 7) ++failures;
    }
}

void work(int index) {
    bool ok = t_value == kTemplate && t_pad[0] == 7 && t_local.magic == kMagic && t_local.name == "local";
    t_value = static_cast<unsigned>(index);
    t_local.name = "worker-" + std::to_string(index);
    ok = stress_pkg_touch(index) && ok;
    Sleep(0);
    ok = ok && t_value == static_cast<unsigned>(index) && t_local.name == "worker-" + std::to_string(index);
    if (ok) ++workers_ok;
    else ++failures;
}

DWORD WINAPI win32_worker(void* index) {
    work(static_cast<int>(reinterpret_cast<std::intptr_t>(index)));
    return 0;
}

unsigned __stdcall crt_worker(void* index) {
    work(static_cast<int>(reinterpret_cast<std::intptr_t>(index)));
    return 0;
}
}  // namespace

#pragma section(".CRT$XLY", long, read)
extern "C" __declspec(allocate(".CRT$XLY")) const PIMAGE_TLS_CALLBACK stress_tls_callback = stress_tls;
#pragma comment(linker, "/include:stress_tls_callback")

int main() {
    constexpr int kRounds = 2, kThreads = 32;
    for (int round = 0; round < kRounds; ++round) {
        std::vector<HANDLE> handles;
        std::vector<std::thread> threads;
        for (int i = 0; i < kThreads; ++i) {
            const int index = round * kThreads + i;
            void* argument = reinterpret_cast<void*>(static_cast<std::intptr_t>(index));
            if (i % 3 == 0) {
                if (HANDLE h = CreateThread(nullptr, 0, win32_worker, argument, 0, nullptr)) handles.push_back(h);
                else ++failures;
            } else if (i % 3 == 1) {
                const auto h = _beginthreadex(nullptr, 0, crt_worker, argument, 0, nullptr);
                if (h) handles.push_back(reinterpret_cast<HANDLE>(h));
                else ++failures;
            } else {
                threads.emplace_back(work, index);
            }
        }
        for (HANDLE h : handles) {
            WaitForSingleObject(h, INFINITE);
            CloseHandle(h);
        }
        for (auto& t : threads) t.join();
    }
    if (t_value != kTemplate || t_local.magic != kMagic) ++failures;
    const long bad = failures.load() + stress_pkg_bad() + (workers_ok.load() == kRounds * kThreads ? 0 : 1)
        + (callbacks.load() >= kRounds * kThreads ? 0 : 1);
    std::printf("thread-stress workers=%ld bad=%ld\n", workers_ok.load(), bad);
    std::fflush(stdout);
    return bad ? 0x200 | static_cast<int>(bad > 0xff ? 0xff : bad) : 0x1c5;
}
