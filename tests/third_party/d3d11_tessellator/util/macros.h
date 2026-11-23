// Shim for the one Mesa macro the reference tessellator uses (Mesa src/util/macros.h defines it to mark impossible
// branches). Not part of the Microsoft sources; MIT, as the rest of this repository.
#pragma once
#include <cstdio>
#include <cstdlib>
#define UNREACHABLE(message) (std::fprintf(stderr, "tessellator: %s\n", message), std::abort())
