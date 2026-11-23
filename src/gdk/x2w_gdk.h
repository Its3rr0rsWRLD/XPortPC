#pragma once
// x2w_gdk.dll: the hand-written Gaming Runtime implementations behind tools/shimgen.py's generated shims,
// plus the support calls the generated code uses. One process-wide copy holds all state (task queues,
// async calls, the offline user, saves), so handles stay valid across every generated console DLL.
//
// Logging (docs/design/runtime.md, section 1, levels 2 and 3): x2w_unimplemented and x2w_stub_called
// report once per distinct (symbol, detail) as "[x2w] unimplemented <symbol> <detail>" on stderr and,
// when the process is x2w_launch, as a "shim-unimplemented" line in its run log.
//
// Environment:
//   X2W_FORWARD       "all", "none" or a comma list of families (a leading '-' turns one off) whose calls
//                     forward to the PC runtime DLL named in their spec. Unset: each family's spec default
//                     (off for every family until measured).
//   X2W_FORWARD_DIR   directory to load forward DLLs from instead of System32.
//   X2W_TITLE         title name for save folders and the package identifier (x2w_launch sets it from
//                     the program name); default: this process's EXE name.
//   X2W_TITLE_DIR     the title's folder, reported as the installed and mounted package; default: the
//                     EXE's folder.
//   X2W_SAVE_ROOT     root of the save folders; default %LOCALAPPDATA%\XPortPC\saves.
#include "x2w_gdk_impl.h"

extern "C" {

X2W_GDK_API void x2w_unimplemented(const char* symbol, const char* detail) noexcept;
X2W_GDK_API void x2w_stub_called(const char* symbol, const char* detail, const void* caller) noexcept;
X2W_GDK_API void x2w_note(const char* symbol, const char* detail) noexcept;
// The PC implementation of `name`, or null: forwarding for `family` is off, the DLL or its anchor export is
// missing, the DLL is one of our own generated shims, or it lacks `name`. Each reason is logged once.
X2W_GDK_API void* x2w_forward_resolve(const char* family, const char* dll, const char* anchor, const char* name,
                                      int enabled_by_default) noexcept;

// For source-built tests: a sink receives every event ("unimplemented", "stub", "note", "forward")
// in addition to stderr; counters and the first unimplemented call.
typedef void(__cdecl* X2WShimLogSink)(const char* kind, const char* symbol, const char* detail, void* context);
X2W_GDK_API void X2WShimSetLogSink(X2WShimLogSink sink, void* context) noexcept;
X2W_GDK_API uint32_t X2WShimUnimplementedCount(void) noexcept;
X2W_GDK_API size_t X2WShimFirstUnimplemented(char* buffer, size_t size) noexcept;

}  // extern "C"
