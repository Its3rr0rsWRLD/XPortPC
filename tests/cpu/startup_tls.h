#pragma once

#include <windows.h>

// Pointer members give the linker constant, relocated TLS directory entries.
// Both fixture images use an empty static TLS data template.
struct TlsDirectory {
    void* start;
    void* end;
    ULONG* index;
    PIMAGE_TLS_CALLBACK* callbacks;
    DWORD zero_fill;
    DWORD characteristics;
};

struct StartupTlsEvent {
    DWORD thread;
    DWORD reason;
    DWORD value;
};

constexpr unsigned startup_tls_capacity = 64;
