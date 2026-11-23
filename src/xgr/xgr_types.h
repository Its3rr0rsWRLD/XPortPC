#pragma once
// Public XNetworking types (https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/networking/xnetworking/
// xnetworking_members), used by the gateway-local functions in xgr_extra.cpp and the declarations that
// tools/xgr_gen.py puts in xgr_table.inc.
#include <windows.h>

#include <cstdint>

#include "x2w_gdk.h"

// .../xnetworking/enums/xnetworkingconnectivitylevelhint
enum class XNetworkingConnectivityLevelHint : uint32_t {
    Unknown = 0,
    None = 1,
    LocalAccess = 2,
    InternetAccess = 3,
    ConstrainedInternetAccess = 4,
};

// .../xnetworking/enums/xnetworkingconnectivitycosthint
enum class XNetworkingConnectivityCostHint : uint32_t {
    Unknown = 0,
    Unrestricted = 1,
    Fixed = 2,
    Variable = 3,
};

// .../xnetworking/structs/xnetworkingconnectivityhint
struct XNetworkingConnectivityHint {
    XNetworkingConnectivityLevelHint connectivityLevel;
    XNetworkingConnectivityCostHint connectivityCost;
    uint32_t ianaInterfaceType;
    bool networkInitialized;
    bool approachingDataLimit;
    bool overDataLimit;
    bool roaming;
};

// .../xnetworking/functions/xnetworkingconnectivityhintchangedcallback
typedef void CALLBACK XNetworkingConnectivityHintChangedCallback(void* context, const XNetworkingConnectivityHint* hint);
// .../xnetworking/functions/xnetworkingpreferredlocaludpmultiplayerportchangedcallback
typedef void CALLBACK XNetworkingPreferredLocalUdpMultiplayerPortChangedCallback(void* context,
                                                                                  uint16_t preferredLocalUdpMultiplayerPort);
