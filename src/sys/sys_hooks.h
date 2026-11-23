// Integration surface of the system-library modules. Everything shimgen or the launcher needs is here.
//
//   X2WSysInit(title_dir, title_name, config_path)   once, before the title's imports are bound
//   X2WSysHookLookup(dll, symbol)                    per import: a replacement function, or null
//   X2WSysShutdown()                                 at exit: one summary line per module
//
// X2WSysHookLookup answers for the Win32 names the modules replace (file and path functions, thread affinity and
// priority, system info, processor topology, QueryPerformanceCounter). It accepts the dll names under which those
// functions are imported: kernel32.dll, kernelbase.dll and the api-ms-win-core-* sets. The other entries
// (GameInput, XAudio2, DirectStorage) are ordinary exports of x2w_sys.dll, listed in sys_modules.tsv.
#pragma once

#ifdef _WIN32
#define X2W_SYS_API extern "C" __declspec(dllexport)
#else
#define X2W_SYS_API extern "C"
#endif

X2W_SYS_API int __stdcall X2WSysInit(const char* title_dir, const char* title_name, const char* config_path);
X2W_SYS_API void* __stdcall X2WSysHookLookup(const char* dll, const char* symbol);
X2W_SYS_API void __stdcall X2WSysShutdown(void);
// What the file hooks know of a handle the title opened (and has not closed): writes "opened-as NAME flags=(...)
// type-at-open=T" (log-redacted) and returns 1, else returns 0. Calls nothing that can block (x2w_launch's stall lines).
X2W_SYS_API int __stdcall X2WSysDescribeHandle(void* handle, char* out, unsigned capacity);
