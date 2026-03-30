
#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN             // Exclude rarely-used stuff from Windows headers.
#endif

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <windows.h>
#include <memory>
#include <numeric>
#include <optional>
#include <shellapi.h>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <algorithm>
#include <variant>
#include <wrl.h>

#ifdef AGILITY_SDK

#include "AgilitySDK\build\native\include\d3d12.h"
#include "AgilitySDK\build\native\include\d3dcommon.h"
#include "AgilitySDK\build\native\include\d3d12sdklayers.h"
#include "AgilitySDK\build\native\include\d3d12shader.h"
#include "AgilitySDK\build\native\include\d3d12video.h"
#include "AgilitySDK\build\native\include\dxgiformat.h"
#include "d3dx12.h"

#else

#include "d3dx12.h"
#include <d3d12.h>
#include <d3dcommon.h>
#include <d3d12sdklayers.h>
#include <d3d12shader.h>
#include <d3d12video.h>
#include <dxgiformat.h>

#endif

#include <dxgi1_6.h>
#include <dxcore_interface.h>
#include <D3Dcompiler.h>
#include <DirectXMath.h>

// WinPixEventRuntime
#define USE_PIX // Use this to compile PIX markers into release builds

#ifdef WIN_PIX_EVENT_RUNTIME
#include "WinPixEventRuntime/Include/WinPixEventRuntime/pix3.h"
#endif
