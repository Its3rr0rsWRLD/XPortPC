#pragma once

// The translator service client of the d3d12_xs.dll graphics shim (docs/design/runtime.md, section 3).
//
// A pool of long-lived tools/pso_service.py processes, each with the converter imported once and DXC loaded in
// process, translates console shaders on a cache miss. The shim talks to each over its stdin and stdout (the frames
// of tools/pso_service.py). One shim thread per service takes requests from a shared queue, so a pipeline's shaders
// and pipelines created on several title threads translate in parallel. The pool starts with one process (at device
// creation, or on the first miss) and grows while requests wait, up to `max_services`. Services are in a job object
// that kills them with the title. When no service can run, translate() reports `unavailable` and the caller uses the
// per-process path (tools/pso_translate.py per shader); a service that fails mid-request does the same for that
// request.

#include <windows.h>

#include <cstdint>
#include <string>
#include <vector>

namespace d3d12_xs {
namespace translator {

struct Settings {
    std::wstring python, tools, dxc, llvm, scratch;  // scratch: a directory for dxc.exe if the library cannot load
    std::wstring pycache;  // Python's bytecode cache for the services (the converter's directory stays untouched)
    unsigned max_services = 1;
};

struct Request {
    std::uint32_t stage = 0;  // X2WShaderStage
    const std::uint8_t* code = nullptr;
    std::uint32_t code_bytes = 0;
    std::string roles;
    bool want_hlsl = false;
};

enum Status : int { translated = 0, refused = 1, tool_failure = 2, unavailable = 3 };

struct Result {
    int status = unavailable;
    std::string message;  // refusal reason, failure, or why the service was unavailable
    std::vector<std::uint8_t> dxil, hlsl;
    std::string bindings;  // the descriptor-table reads, as pso_translate.py --bindings writes them
};

// Once, before any other call. Takes a copy.
void configure(const Settings& settings);
// Starts the first service in the background if none runs yet.
void prestart();
// Translates `count` requests through the services and waits for all of them.
void translate(const Request* requests, Result* results, std::size_t count);

}  // namespace translator
}  // namespace d3d12_xs
