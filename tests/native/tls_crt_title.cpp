// Source-built title linked with the static C runtime (/MT), so the runtime's own startup, its _tls_used
// directory and its thread_local machinery run inside the mapped image: a thread_local object with a dynamic
// initializer and a destructor, a thread_local int and a thread_local pointer from the template (the pointer
// is fixed up by base relocations), and std::thread workers. main returns 0x13f when every check held, under
// Windows and under x2w_launch alike, and prints one line with the counts.
#include <windows.h>

#include <atomic>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>

namespace {
std::atomic<int> constructed{0};
std::atomic<int> destroyed{0};

struct PerThread {
    int id;
    std::string name;
    PerThread() : id(++constructed), name("thread-" + std::to_string(id)) {}
    ~PerThread() { ++destroyed; }
};

thread_local PerThread t_object;
thread_local int t_counter = 41;
thread_local const char* t_label = "template-label";

bool sees_template() { return t_counter == 41 && t_label && std::strcmp(t_label, "template-label") == 0; }

bool names_this_title(const char* path) {
    const char* file = std::strrchr(path, '\\');
    file = file ? file + 1 : path;
    return _stricmp(file, "x2w_tls_crt_title.exe") == 0;
}
}  // namespace

int main() {
    unsigned code = 0x100;
    if (sees_template()) code |= 0x01;
    t_counter = 99;
    const int main_id = t_object.id;

    bool workers_saw_template = true;
    int worker_ids[2] = {};
    std::string worker_names[2];
    for (int i = 0; i < 2; ++i) {
        // One worker at a time, so the object ids are deterministic.
        std::thread worker([&, i] {
            workers_saw_template = workers_saw_template && sees_template();
            t_counter = 7 + i;
            worker_ids[i] = t_object.id;
            worker_names[i] = t_object.name;
            workers_saw_template = workers_saw_template && t_counter == 7 + i;
        });
        worker.join();
    }
    if (workers_saw_template) code |= 0x02;
    if (main_id == 1 && worker_ids[0] == 2 && worker_ids[1] == 3 && worker_names[1] == "thread-3") code |= 0x04;
    // Each worker's thread_local destructor ran when it ended (the runtime's TLS callback on thread detach).
    if (destroyed == 2) code |= 0x08;
    if (t_counter == 99 && t_object.id == 1 && t_object.name == "thread-1") code |= 0x10;
    // The runtime's program name and GetModuleFileNameA(NULL) name this executable.
    char path[MAX_PATH] = {};
    if (GetModuleFileNameA(nullptr, path, MAX_PATH) && names_this_title(path) && _pgmptr && names_this_title(_pgmptr))
        code |= 0x20;
    std::printf("tls-crt code=0x%x constructed=%d destroyed=%d\n", code, constructed.load(), destroyed.load());
    std::fflush(stdout);
    return static_cast<int>(code);
}
