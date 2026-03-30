#include "pch.h"
#include "FrameResources.h"

using namespace Helpers;

void CreateAppResources()
{
#if defined(_DEBUG)
    // Enable the debug layer (requires the Graphics Tools optional feature).
    // NOTE: Enabling the debug layer after device creation will invalidate the active device.
    {
        ComPtr<ID3D12Debug> debugController;
        if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debugController))))
        {
            debugController->EnableDebugLayer();
        }
    }
#endif

    CreateAppResources_000();

    g_utilityCommandQueue->SetName(L"Utility Command Queue");
    g_utilityCommandList->SetName(L"Utility CommandList");
    g_utilityCommandAllocator->SetName(L"Utility Command Allocator");
    g_utilityComputeCommandQueue->SetName(L"Utility Compute Command Queue");
    g_utilityComputeCommandList->SetName(L"Utility Compute CommandList");
    g_utilityComputeCommandAllocator->SetName(L"Utility Compute Command Allocator");
    g_fence->SetName(L"Utility fence");

    // Close the init command lists and execute them to begin the initial GPU setup.
    CloseAndExecuteUtilityCommandList();
    ThrowIfFailed(g_utilityCommandList->Close());
    CloseAndExecuteUtilityComputeCommandList();
    ThrowIfFailed(g_utilityComputeCommandList->Close());

    FlushUtilityCommandQueue(g_utilityCommandQueue.Get());
    FlushUtilityCommandQueue(g_utilityComputeCommandQueue.Get());
}

void DestroyAppResources()
{
    for (const auto& commandQueueInfo : g_commandQueues)
        FlushCommandQueue(commandQueueInfo.first);
    FlushUtilityCommandQueue(g_utilityCommandQueue.Get());

    g_commandAllocators.clear();
    g_commandLists.clear();
    g_heaps.clear();
    g_fences.clear();
    g_rootSignatures.clear();
    g_commandSignatures.clear();
    g_psos.clear();
    g_stateObjects.clear();
    g_heaps.clear();
    g_resources.clear();
    g_descHeaps.clear();
    g_metaCommands.clear();
#if defined(DIRECT3D_EXPERIMENTAL_BUILD)
    g_d3dExtensions.clear();
#endif

    g_stagingResources.clear();
    g_indirectArgumentBuffers.clear();
    g_countBuffers.clear();
    g_bundleAllocatorsHandles.clear();
    g_utilityFencesInfo.clear();

    g_resourceReader.reset(nullptr);
    g_resourceReader = std::make_unique<ResourceReader>();

    g_constructionNeeded = false;
}
