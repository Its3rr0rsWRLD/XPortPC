#include "adapter_identity.h"

#include <algorithm>
#include <iterator>
#include <new>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <winternl.h> // NTSTATUS for d3dkmthk.h
#include <d3dkmthk.h>

namespace adapter_identity {
std::vector<std::wstring> physical_devices(const LUID& luid) noexcept
{
    D3DKMT_OPENADAPTERFROMLUID open{};
    open.AdapterLuid = luid;
    if (D3DKMTOpenAdapterFromLuid(&open) != 0) return {};
    const struct Close {
        D3DKMT_HANDLE adapter;
        ~Close()
        {
            D3DKMT_CLOSEADAPTER close{adapter};
            D3DKMTCloseAdapter(&close);
        }
    } close{open.hAdapter};
    std::vector<std::wstring> devices;
    UINT count = 0;
    D3DKMT_QUERYADAPTERINFO query{open.hAdapter, KMTQAITYPE_PHYSICALADAPTERCOUNT, &count, sizeof(count)};
    bool complete = D3DKMTQueryAdapterInfo(&query) == 0 && count > 0;
    for (UINT i = 0; complete && i < count; ++i) {
        WCHAR key[1024];
        UINT length = static_cast<UINT>(std::size(key));
        D3DKMT_QUERY_PHYSICAL_ADAPTER_PNP_KEY pnp{i, D3DKMT_PNP_KEY_HARDWARE, key, &length};
        query = {open.hAdapter, KMTQAITYPE_PHYSICALADAPTERPNPKEY, &pnp, sizeof(pnp)};
        complete = D3DKMTQueryAdapterInfo(&query) == 0 && key[0];
        try {
            if (complete) devices.emplace_back(key, wcsnlen(key, std::size(key)));
        } catch (const std::bad_alloc&) {
            return {};
        }
    }
    if (!complete) return {};
    std::sort(devices.begin(), devices.end());
    return devices;
}
}
