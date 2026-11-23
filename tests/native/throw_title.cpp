// Source-built title linked with the static C runtime (/MT, /EHsc) that throws and catches C++ exceptions of
// three types (std::runtime_error, a struct in a named namespace, int), each three times from its own
// non-inlined function, on the main thread and on a std::thread worker. Under x2w_launch the image is mapped
// by pe_map, so the throws exercise the runtime's ThrowInfo lookup in a mapped image, and with --log the
// launcher's "cpp-throw TYPE at SITE from CALLER" lines. main returns 0x107 when every throw was caught with
// its value, under Windows and under x2w_launch alike, and prints one line with the counts and one with the
// RVAs of the three throwing functions (relative to __ImageBase, so the same under both loaders).
#include <windows.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <thread>

extern "C" IMAGE_DOS_HEADER __ImageBase;

namespace probe {
struct bad_probe {
    int code;
};
}  // namespace probe

namespace {
__declspec(noinline) void throw_runtime(int i) { throw std::runtime_error("probe " + std::to_string(i)); }
__declspec(noinline) void throw_probe(int i) { throw probe::bad_probe{100 + i}; }
__declspec(noinline) void throw_int(int i) { throw 200 + i; }

// The number of throws of each kind that were caught with the expected value.
struct Counts {
    int runtime = 0;
    int probe = 0;
    int integer = 0;
};

void throw_all(Counts& counts) {
    for (int i = 0; i < 3; ++i) {
        try {
            throw_runtime(i);
        } catch (const std::exception& error) {  // caught through its base class
            if (std::strcmp(error.what(), ("probe " + std::to_string(i)).c_str()) == 0) ++counts.runtime;
        }
        try {
            throw_probe(i);
        } catch (const probe::bad_probe& error) {
            if (error.code == 100 + i) ++counts.probe;
        }
        try {
            throw_int(i);
        } catch (int value) {
            if (value == 200 + i) ++counts.integer;
        }
    }
}

unsigned rva(const void* address) {
    return static_cast<unsigned>(reinterpret_cast<std::uintptr_t>(address) -
                                 reinterpret_cast<std::uintptr_t>(&__ImageBase));
}
}  // namespace

int main() {
    unsigned code = 0x100;
    Counts main_counts;
    throw_all(main_counts);
    if (main_counts.runtime == 3 && main_counts.probe == 3 && main_counts.integer == 3) code |= 0x01;

    Counts worker_counts;
    std::thread worker([&] { throw_all(worker_counts); });
    worker.join();
    if (worker_counts.runtime == 3 && worker_counts.probe == 3 && worker_counts.integer == 3) code |= 0x02;

    // A rethrow inside a handler and an exception that leaves a nested try.
    int rethrown = 0;
    try {
        try {
            throw_probe(7);
        } catch (const probe::bad_probe&) {
            throw;
        }
    } catch (const probe::bad_probe& error) {
        if (error.code == 107) rethrown = 1;
    }
    if (rethrown) code |= 0x04;

    std::printf("cpp-throw code=0x%x main=%d/%d/%d worker=%d/%d/%d\n", code, main_counts.runtime,
                main_counts.probe, main_counts.integer, worker_counts.runtime, worker_counts.probe,
                worker_counts.integer);
    std::printf("sites runtime=0x%x probe=0x%x int=0x%x\n", rva(reinterpret_cast<const void*>(&throw_runtime)),
                rva(reinterpret_cast<const void*>(&throw_probe)), rva(reinterpret_cast<const void*>(&throw_int)));
    std::fflush(stdout);
    return static_cast<int>(code);
}
