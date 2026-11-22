#pragma once

#include <string>
#include <vector>

struct _LUID;

// Windows can list one device under several DXGI LUIDs, and vendor/device IDs do not tell them
// apart from separate adapters of the same model; the PnP device keys do.
namespace adapter_identity {
// Sorted PnP hardware keys of the physical adapters behind `luid`; empty when they cannot be read.
std::vector<std::wstring> physical_devices(const _LUID& luid) noexcept;
}
