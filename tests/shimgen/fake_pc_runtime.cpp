// Source-built stand-in for a PC runtime DLL, for the shimgen fixture's forwarding test: the fixture family
// (tests/shimgen/fixture_override.toml) forwards X2WFixtureForwarded here when X2W_FORWARD_DIR holds it.
#include <cstdint>

extern "C" int32_t X2WFixtureForwarded(int32_t a, int32_t b) { return a * b + 1; }
