#pragma once

#include "pch.h"
#include "CapturedAssets.h"

typedef HRESULT(WINAPI* PDXCoreCreateAdapterFactory)(_In_ REFIID riid, _COM_Outptr_ void** factory);

namespace Helpers {
    inline std::string HrToString(HRESULT hr)
    {
        char s_str[64] = {};
        sprintf_s(s_str, "HRESULT of 0x%08X", static_cast<UINT>(hr));
        return std::string(s_str);
    }

    class HrException : public std::runtime_error
    {
    public:
        HrException(HRESULT hr) : std::runtime_error(HrToString(hr)), g_hr(hr) {}
        HRESULT Error() const { return g_hr; }
    private:
        const HRESULT g_hr;
    };

#define SAFE_RELEASE(p) if (p) (p)->Release()

    inline void ThrowIfFailed(HRESULT hr)
    {
        if (FAILED(hr))
        {
            throw HrException(hr);
        }
    }

    static ComPtr<IDXCoreAdapterFactory> GetOrCreateDXCoreAdapterFactory()
    {
        static HMODULE dxCoreModule = LoadLibraryExA("DXCore.dll", 0, LOAD_LIBRARY_SEARCH_SYSTEM32 | LOAD_LIBRARY_SEARCH_APPLICATION_DIR);

        if (dxCoreModule != NULL)
        {
            static auto* createDXCoreFactory = reinterpret_cast<PDXCoreCreateAdapterFactory>
                (GetProcAddress(dxCoreModule, "DXCoreCreateAdapterFactory"));

            ComPtr<IDXCoreAdapterFactory> factory;
            // Silent failure: If it succeeds, we're on an OS that supports the interface PIX knows about.
            (void)createDXCoreFactory(IID_PPV_ARGS(factory.GetAddressOf()));

            return factory;
        }

        return nullptr;
    }

    static ComPtr<IUnknown> GetPlaybackAdapter(const std::wstring& adapterDescription)
    {
        ComPtr<IDXGIFactory> dxgiFactory;
        ThrowIfFailed(CreateDXGIFactory(IID_PPV_ARGS(&dxgiFactory)));

        uint32_t adapterIndex = 0;
        for (ComPtr<IDXGIAdapter> nextAdapter; SUCCEEDED(dxgiFactory->EnumAdapters(adapterIndex, &nextAdapter)); adapterIndex++)
        {
            DXGI_ADAPTER_DESC desc{};
            ThrowIfFailed(nextAdapter->GetDesc(&desc));

            if (desc.Description == adapterDescription)
            {
                return nextAdapter;
            }
        }

        if (ComPtr<IDXCoreAdapterFactory> dxCoreFactory = GetOrCreateDXCoreAdapterFactory(); dxCoreFactory)
        {
            GUID adapterTypes[] = { DXCORE_ADAPTER_ATTRIBUTE_D3D12_CORE_COMPUTE };

            ComPtr<IDXCoreAdapterList> adapterList;
            ThrowIfFailed(dxCoreFactory->CreateAdapterList(
                static_cast<uint32_t>(_countof(adapterTypes)),
                adapterTypes,
                IID_PPV_ARGS(&adapterList)));

            uint32_t adapterCount = adapterList->GetAdapterCount();

            for (uint32_t a = 0; a < adapterCount; ++a)
            {
                ComPtr<IDXCoreAdapter> dxCoreAdapter;

                ThrowIfFailed(adapterList->GetAdapter(a, IID_PPV_ARGS(&dxCoreAdapter)));

                size_t size = 0;
                ThrowIfFailed(dxCoreAdapter->GetPropertySize(DXCoreAdapterProperty::DriverDescription, &size));

                std::vector<byte> buffer(size);
                ThrowIfFailed(dxCoreAdapter->GetProperty(DXCoreAdapterProperty::DriverDescription, size, buffer.data()));

                // DriverDescription is null-terminated array of chars.
                // The null terminating char is not required for comparison.
                buffer.pop_back();

                auto description = reinterpret_cast<char const*>(buffer.data());
                int size_needed = MultiByteToWideChar(CP_UTF8, 0, description, (int)buffer.size(), NULL, 0);
                std::wstring description_w(size_needed, 0);
                MultiByteToWideChar(CP_UTF8, 0, description, (int)buffer.size(), description_w.data(), size_needed);

                if (description_w == adapterDescription)
                {
                    return dxCoreAdapter;
                }
            }
        }

        // If capture time adapter is not present, return nullptr (i.e. create device using default adapter)
        return nullptr;
    }

    inline void CreateAndTrackCommandQueue(ApiObjectId handle, ID3D12Device4* pDevice, const D3D12_COMMAND_QUEUE_DESC* pDesc)
    {
        ComPtr<ID3D12CommandQueue> g_cmdQueue;
        ThrowIfFailed(pDevice->CreateCommandQueue(pDesc, IID_PPV_ARGS(&g_cmdQueue)));
        ComPtr<ID3D12Fence> g_fence;
        ThrowIfFailed(pDevice->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&g_fence)));

        g_commandQueues[handle] = g_cmdQueue;
        g_utilityFencesInfo.emplace(handle, std::make_pair(g_fence, 0));
    }

    inline void CreateAndTrackCommandAllocator(ApiObjectId handle, ID3D12Device4* pDevice, D3D12_COMMAND_LIST_TYPE cmdListType)
    {
        ComPtr<ID3D12CommandAllocator> g_cmdAllocator;
        ThrowIfFailed(pDevice->CreateCommandAllocator(cmdListType, IID_PPV_ARGS(&g_cmdAllocator)));
        g_commandAllocators[handle] = g_cmdAllocator;
    }

    inline void CreateAndTrackCommandList1(ApiObjectId handle, ID3D12Device4* pDevice, UINT nodeMask, D3D12_COMMAND_LIST_TYPE type, D3D12_COMMAND_LIST_FLAGS flags)
    {
        ComPtr<ID3D12GraphicsCommandList6> g_cmdList;
        ThrowIfFailed(pDevice->CreateCommandList1(nodeMask, type, flags, IID_PPV_ARGS(&g_cmdList)));
        g_commandLists[handle] = g_cmdList;
    }

    inline void CreateAndTrackCommandList(ApiObjectId handle, ID3D12Device4* pDevice, UINT nodeMask, D3D12_COMMAND_LIST_TYPE type)
    {
        ComPtr<ID3D12CommandAllocator> cmdAllocator;
        ThrowIfFailed(pDevice->CreateCommandAllocator(type, IID_PPV_ARGS(&cmdAllocator)));

        ComPtr<ID3D12GraphicsCommandList6> cmdList;
        ThrowIfFailed(pDevice->CreateCommandList(nodeMask, type, cmdAllocator.Get(), nullptr, IID_PPV_ARGS(&cmdList)));
        cmdList->Close();
        g_commandLists[handle] = cmdList;
    }

    inline void CreateAndTrackFence(ApiObjectId handle, ID3D12Device4* pDevice, D3D12_FENCE_FLAGS flags, UINT initialValue)
    {
        ComPtr<ID3D12Fence> g_fence;
        ThrowIfFailed(pDevice->CreateFence(initialValue, flags, IID_PPV_ARGS(&g_fence)));
        g_fences[handle] = g_fence;
    }

    inline void CreateAndTrackRootSignature(ApiObjectId handle, ID3D12Device4* pDevice, UINT nodeMask, ID3DBlob* pSignature)
    {
        ComPtr<ID3D12RootSignature> g_rootSignature;
        ThrowIfFailed(pDevice->CreateRootSignature(nodeMask, pSignature->GetBufferPointer(), pSignature->GetBufferSize(), IID_PPV_ARGS(&g_rootSignature)));
        g_rootSignatures[handle] = g_rootSignature;
    }

    inline void CreateAndTrackCommandSignature(ApiObjectId handle, ID3D12RootSignature* pRootSignature, ID3D12Device4* pDevice, const D3D12_COMMAND_SIGNATURE_DESC* pDesc)
    {
        ComPtr<ID3D12CommandSignature> cmdSignature;
        ThrowIfFailed(pDevice->CreateCommandSignature(pDesc, pRootSignature, IID_PPV_ARGS(&cmdSignature)));
        g_commandSignatures[handle] = cmdSignature;
    }

    inline void CreateAndTrackGraphicsPipelineState(ApiObjectId handle, ID3D12Device4* pDevice, const D3D12_GRAPHICS_PIPELINE_STATE_DESC* pDesc)
    {
        ComPtr<ID3D12PipelineState> g_pso;
        ThrowIfFailed(pDevice->CreateGraphicsPipelineState(pDesc, IID_PPV_ARGS(&g_pso)));
        g_psos[handle] = g_pso;
    }

    inline void CreateAndTrackComputePipelineState(ApiObjectId handle, ID3D12Device4* pDevice, const D3D12_COMPUTE_PIPELINE_STATE_DESC* pDesc)
    {
        ComPtr<ID3D12PipelineState> g_pso;
        ThrowIfFailed(pDevice->CreateComputePipelineState(pDesc, IID_PPV_ARGS(&g_pso)));
        g_psos[handle] = g_pso;
    }

    inline void CreateAndTrackPipelineState(ApiObjectId handle, ID3D12Device2* pDevice, const D3D12_PIPELINE_STATE_STREAM_DESC* pDesc)
    {
        ComPtr<ID3D12PipelineState> psoStream;
        ThrowIfFailed(pDevice->CreatePipelineState(pDesc, IID_PPV_ARGS(&psoStream)));
        g_psos[handle] = psoStream;
    }

    inline void CreateAndTrackStateObject(ApiObjectId handle, const D3D12_STATE_OBJECT_DESC* pDesc)
    {
        ComPtr<ID3D12StateObject> stateObject;
        ThrowIfFailed(g_device->CreateStateObject(pDesc, IID_PPV_ARGS(&stateObject)));
        g_stateObjects[handle] = stateObject;
    }

    inline void CreateAndTrackStateObject(ApiObjectId handle, const D3D12_STATE_OBJECT_DESC* pAddition, ID3D12StateObject* pStateObjectToGrowFrom)
    {
        ComPtr<ID3D12Device7> device7;
        ThrowIfFailed(g_device->QueryInterface(IID_PPV_ARGS(&device7)));
        ComPtr<ID3D12StateObject> stateObject;
        ThrowIfFailed(device7->AddToStateObject(pAddition, pStateObjectToGrowFrom, IID_PPV_ARGS(&stateObject)));
        g_stateObjects[handle] = stateObject;
    }

    inline void CreateAndTrackCommittedResource(ApiObjectId handle, ID3D12Device4* pDevice, D3D12_HEAP_PROPERTIES* pHeapProperties, D3D12_HEAP_FLAGS HeapFlags, const D3D12_RESOURCE_DESC* pDesc,
        D3D12_RESOURCE_STATES pInitialResourceState, const D3D12_CLEAR_VALUE* pOptimizedClearValue)
    {
        ComPtr<ID3D12Resource> resource;
        ThrowIfFailed(pDevice->CreateCommittedResource(pHeapProperties, HeapFlags, pDesc, pInitialResourceState, pOptimizedClearValue, IID_PPV_ARGS(&resource)));
        g_resources[handle] = resource;
    }

    inline void CreateAndTrackCommittedResource2(ApiObjectId handle, ID3D12Device4* pDevice, D3D12_HEAP_PROPERTIES* pHeapProperties, D3D12_HEAP_FLAGS HeapFlags, const D3D12_RESOURCE_DESC1* pDesc,
        D3D12_RESOURCE_STATES pInitialResourceState, const D3D12_CLEAR_VALUE* pOptimizedClearValue)
    {
        ComPtr<ID3D12Device8> device8;
        ThrowIfFailed(pDevice->QueryInterface(IID_PPV_ARGS(&device8)));

        ComPtr<ID3D12Resource> resource;
        ThrowIfFailed(device8->CreateCommittedResource2(pHeapProperties, HeapFlags, pDesc, pInitialResourceState, pOptimizedClearValue, nullptr, IID_PPV_ARGS(&resource)));
        g_resources[handle] = resource;
    }

    inline void SetBaseGpuvaIfPossible(ApiObjectId heapHandle, ComPtr<ID3D12Resource> resource, UINT heapOffset, D3D12_RESOURCE_DIMENSION dimension)
    {
        if (dimension != D3D12_RESOURCE_DIMENSION_BUFFER)
            return;

        auto& baseGpuva = g_heaps[heapHandle].BaseGpuva;
        auto address = resource->GetGPUVirtualAddress() - heapOffset;

        // The GPUVA shouldn't change, except the first time we set it.
        assert(baseGpuva == std::nullopt || *baseGpuva == address);

        baseGpuva = address;
    }

    inline void CreateAndTrackPlacedResource(ApiObjectId rHandle, ID3D12Device4* pDevice, const D3D12_RESOURCE_DESC* pDesc,
        D3D12_RESOURCE_STATES pInitialResourceState, const D3D12_CLEAR_VALUE* pOptimizedClearValue, ApiObjectId heapHandle, UINT heapOffset)
    {
        ComPtr<ID3D12Resource> resource;
        ThrowIfFailed(pDevice->CreatePlacedResource(g_heaps[heapHandle].Heap.Get(), heapOffset, pDesc, pInitialResourceState, pOptimizedClearValue, IID_PPV_ARGS(&resource)));
        g_resources[rHandle] = resource;
        SetBaseGpuvaIfPossible(heapHandle, resource, heapOffset, pDesc->Dimension);
    }

    inline void CreateAndTrackPlacedResource1(ApiObjectId rHandle, ID3D12Device8* pDevice, const D3D12_RESOURCE_DESC1* pDesc,
        D3D12_RESOURCE_STATES pInitialResourceState, const D3D12_CLEAR_VALUE* pOptimizedClearValue, ApiObjectId heapHandle, UINT heapOffset)
    {
        ComPtr<ID3D12Resource> resource;
        ThrowIfFailed(pDevice->CreatePlacedResource1(g_heaps[heapHandle].Heap.Get(), heapOffset, pDesc, pInitialResourceState, pOptimizedClearValue, IID_PPV_ARGS(&resource)));
        g_resources[rHandle] = resource;
        SetBaseGpuvaIfPossible(heapHandle, resource, heapOffset, pDesc->Dimension);
    }

    inline void CreateAndTrackReservedResource(ApiObjectId handle, ID3D12Device4* pDevice, const D3D12_RESOURCE_DESC* pDesc,
        D3D12_RESOURCE_STATES pInitialResourceState, const D3D12_CLEAR_VALUE* pOptimizedClearValue)
    {
        ComPtr<ID3D12Resource> resource;
        ThrowIfFailed(pDevice->CreateReservedResource(pDesc, pInitialResourceState, pOptimizedClearValue, IID_PPV_ARGS(&resource)));
        g_resources[handle] = resource;
    }

    inline void CreateAndTrackHeap(ApiObjectId handle, ID3D12Device4* pDevice, const D3D12_HEAP_DESC* pheapDesc)
    {
        D3D12Heap d3d12Heap;
        ThrowIfFailed(pDevice->CreateHeap(pheapDesc, IID_PPV_ARGS(&d3d12Heap.Heap)));
        g_heaps[handle] = d3d12Heap;
    }

    inline void CreateAndTrackQueryHeap(ApiObjectId handle, ID3D12Device4* pDevice, const D3D12_QUERY_HEAP_DESC *pDesc)
    {
        ComPtr<ID3D12QueryHeap> heap;
        ThrowIfFailed(pDevice->CreateQueryHeap(pDesc, IID_PPV_ARGS(&heap)));
        g_queryHeaps[handle] = heap;
    }

#if D3D12_SDK_VERSION >= 619 || (defined(PREVIEW_BUILD) && D3D12_PREVIEW_SDK_VERSION >= 719)
    inline void CreateAndTrackQueryHeap1(ApiObjectId handle, ID3D12Device4* pDevice, const D3D12_QUERY_HEAP_DESC* pDesc, D3D12_QUERY_HEAP_FLAGS flags)
    {
		ComPtr<ID3D12Device15> device15;
		ThrowIfFailed(pDevice->QueryInterface(IID_PPV_ARGS(&device15)));
        ComPtr<ID3D12QueryHeap> heap;
        ThrowIfFailed(device15->CreateQueryHeap1(pDesc, flags, IID_PPV_ARGS(&heap)));
        g_queryHeaps[handle] = heap;
    }
#endif

    inline void CreateAndTrackMetaCommand(ApiObjectId handle, ID3D12Device5* pDevice, REFGUID commandId, UINT nodeMask, const void* pCreationParametersData, SIZE_T creationParametersDataSizeInBytes)
    {
        ComPtr<ID3D12MetaCommand> metaCommand;
        ThrowIfFailed(pDevice->CreateMetaCommand(commandId, nodeMask, pCreationParametersData, creationParametersDataSizeInBytes, IID_PPV_ARGS(&metaCommand)));
        g_metaCommands[handle] = metaCommand;
    }

#if defined(DIRECT3D_EXPERIMENTAL_BUILD)
    inline void CreateAndTrackD3DExtension(ApiObjectId handle, ID3D12DeviceApiExtensions* pDeviceApiExtensions, REFIID extensionID, const D3D12_EXTENSION_ARGUMENTS* args)
    {
        ComPtr<ID3D12Extension> extension;
        ThrowIfFailed(pDeviceApiExtensions->CreateExtension(extensionID, args, IID_PPV_ARGS(&extension)));
        g_d3dExtensions[handle] = extension; 
    }
#endif

    inline Microsoft::WRL::ComPtr<ID3D12Resource>& GetResource(ApiObjectId handle)
    {
        return g_resources.at(handle);
    }

    inline ComPtr<ID3D12GraphicsCommandList6> GetCommandList(ApiObjectId handle)
    {
        return g_commandLists.at(handle);
    }

    inline ComPtr<ID3D12CommandAllocator> GetCommandAllocator(ApiObjectId handle)
    {
        auto find = g_commandAllocators.find(handle);
        if (find != g_commandAllocators.end())
            return find->second;
        else
            return nullptr;
    }

    inline ID3D12CommandQueue* GetCommandQueue(ApiObjectId handle)
    {
        auto find = g_commandQueues.find(handle);
        return (find->second).Get();
    }

    inline Microsoft::WRL::ComPtr<ID3D12Fence> GetFence(ApiObjectId handle)
    {
        auto find = g_fences.find(handle);
        if (find != g_fences.end())
            return find->second;
        else
            return nullptr;
    }

    inline ID3D12RootSignature* GetRootSignature(ApiObjectId handle)
    {
        auto find = g_rootSignatures.find(handle);
        if (find != g_rootSignatures.end())
            return find->second.Get();
        else
            return nullptr;
    }

    inline ID3D12CommandSignature* GetCommandSignature(ApiObjectId handle)
    {
        return g_commandSignatures.at(handle).Get();
    }

    inline ID3D12PipelineState* GetPipelineState(ApiObjectId handle)
    {
        auto find = g_psos.find(handle);
        if (find != g_psos.end())
            return (find->second).Get();
        else
            return nullptr;
    }

    inline Microsoft::WRL::ComPtr<ID3D12Heap> GetHeap(ApiObjectId handle)
    {
        auto find = g_heaps.find(handle);
        if (find != g_heaps.end())
            return find->second.Heap;
        else
            return nullptr;
    }

    inline Microsoft::WRL::ComPtr<ID3D12QueryHeap> GetQueryHeap(ApiObjectId handle)
    {
        auto find = g_queryHeaps.find(handle);
        if (find != g_queryHeaps.end())
            return find->second;
        else
            return nullptr;
    }

    inline ComPtr<ID3D12StateObject> GetStateObject(ApiObjectId handle)
    {
        return g_stateObjects.at(handle);
    }

    inline ComPtr<ID3D12MetaCommand> GetMetaCommand(ApiObjectId handle)
    {
        return g_metaCommands.at(handle);
    }



#if defined(DIRECT3D_EXPERIMENTAL_BUILD)
    inline ComPtr<ID3D12Extension> GetD3DExtension(ApiObjectId handle)
    {
        return g_d3dExtensions.at(handle);
    }
#endif

    inline void ResetCommandAllocators()
    {
        g_utilityCommandAllocator->Reset();
        for (const auto& commandAllocatorInfo : g_commandAllocators)
        {
            if (g_bundleAllocatorsHandles.find(commandAllocatorInfo.first) != g_bundleAllocatorsHandles.end())
                continue;
            ThrowIfFailed(commandAllocatorInfo.second->Reset());
        }
    }

    template <typename T>
    inline ComPtr<T> TryGet(const std::unordered_map<ApiObjectId, ComPtr<T>>& map, ApiObjectId handle)
    {
        auto it = map.find(handle);
        return it != map.end() ? it->second : nullptr;
    }

    inline ID3D12Object* GetObject(ApiObjectId handle)
    {
        ComPtr<ID3D12Object> object = nullptr;
        object = TryGet(g_resources, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_commandAllocators, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_commandLists, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_commandQueues, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_fences, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_descHeaps, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_psos, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_rootSignatures, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_queryHeaps, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_commandSignatures, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_metaCommands, handle);
        if (object != nullptr)
            return object.Get();
        object = TryGet(g_stateObjects, handle);
        if (object != nullptr)
            return object.Get();

        auto it = g_heaps.find(handle);
        if (it != g_heaps.end())
            return it->second.Heap.Get();

        return nullptr;
    }

    inline void FlushUtilityCommandQueue(ID3D12CommandQueue* utilityCommandQueue)
    {
        g_lastFenceSignaled++;
        ThrowIfFailed(utilityCommandQueue->Signal(g_fence.Get(), g_lastFenceSignaled));

        if (g_fence->GetCompletedValue() < g_lastFenceSignaled)
        {
            HANDLE eventHandle = CreateEventEx(nullptr, FALSE, FALSE, EVENT_ALL_ACCESS);

            ThrowIfFailed(g_fence->SetEventOnCompletion(g_lastFenceSignaled, eventHandle));

            WaitForSingleObject(eventHandle, INFINITE);
            CloseHandle(eventHandle);
        }
    }

    inline void FlushCommandQueue(ApiObjectId handle)
    {
        g_lastFenceSignaled++;
        GetCommandQueue(handle)->Signal(g_fence.Get(), g_lastFenceSignaled);

        if (g_fence->GetCompletedValue() < g_lastFenceSignaled)
        {
            HANDLE eventHandle = CreateEventEx(nullptr, FALSE, FALSE, EVENT_ALL_ACCESS);

            ThrowIfFailed(g_fence->SetEventOnCompletion(g_lastFenceSignaled, eventHandle));

            WaitForSingleObject(eventHandle, INFINITE);
            CloseHandle(eventHandle);
        }
    }

    static void CreateDummyPlacedBufferAndSetHeapBaseGpuva(D3D12Heap* heapInfo)
    {
        ComPtr<ID3D12Device> device;
        ThrowIfFailed(heapInfo->Heap->GetDevice(IID_PPV_ARGS(&device)));

        auto resourceDesc = CD3DX12_RESOURCE_DESC::Buffer(1ull);
        if (heapInfo->Heap->GetDesc().Flags & D3D12_HEAP_FLAG_SHARED_CROSS_ADAPTER)
        {
            resourceDesc.Flags |= D3D12_RESOURCE_FLAG_ALLOW_CROSS_ADAPTER;
        }

        D3D12_RESOURCE_STATES initialStateToUse{};
        switch (heapInfo->Heap->GetDesc().Properties.Type)
        {
        case D3D12_HEAP_TYPE_DEFAULT:
        case D3D12_HEAP_TYPE_CUSTOM:
            initialStateToUse = D3D12_RESOURCE_STATE_COMMON;
            break;

        case D3D12_HEAP_TYPE_UPLOAD:
            initialStateToUse = D3D12_RESOURCE_STATE_GENERIC_READ;
            break;

        case D3D12_HEAP_TYPE_READBACK:
            initialStateToUse = D3D12_RESOURCE_STATE_COPY_DEST;
            break;

        default:
            assert(false);
            throw E_UNEXPECTED;
        }

        ComPtr<ID3D12Resource> dummyResource;
        ThrowIfFailed(device->CreatePlacedResource(
            heapInfo->Heap.Get(),
            0ull,
            &resourceDesc,
            initialStateToUse,
            nullptr,
            IID_PPV_ARGS(&dummyResource)));

        heapInfo->BaseGpuva = dummyResource->GetGPUVirtualAddress();
    }

    static D3D12_GPU_VIRTUAL_ADDRESS GetGpuva(ApiObjectId rHandle, uint64_t offset)
    {
        // rHandle can either be handle to resource or heap.
        // For placed resources,
        //     rHandle -> Heap
        // For committed and reserved resources,
        //     rHandle -> Resource

        // This indicates an invalid GPUVA.
        if (rHandle == 0 && offset == -1)
        {
            return D3D12_GPU_VIRTUAL_ADDRESS(-1);
        }

        if (rHandle == 0 && offset == 0)
        {
            // This is just a null GPUVA.
            return 0ull;
        }

        auto it = g_resources.find(rHandle);
        if (it != g_resources.end())
        {
            return it->second->GetGPUVirtualAddress() + offset;
        }
        else
        {
            auto heap = g_heaps.find(rHandle);
            assert(heap != g_heaps.end());

            if (!heap->second.BaseGpuva.has_value())
            {
                // It's possible that the app is using a GPUVA within a live heap, but there weren't any placed resources
                // alive within the heap when PIX captured the heap. This means that we have not recreated any placed
                // resources within the heap, so it doesn't know the heap's base GPUVA.
                //
                // The fix: we try to create a dummy placed buffer in the heap, so that we can retrieve the placed buffer's
                // GPUVA, and therefore derive the heap's base GPUVA.
                CreateDummyPlacedBufferAndSetHeapBaseGpuva(&heap->second);
                assert(heap->second.BaseGpuva.has_value());
            }

            return *heap->second.BaseGpuva + offset;
        }
    }

    inline ComPtr<IDXGISwapChain3> GetSwapChain(ApiObjectId handle)
    {
        return g_swapChains.at(handle);
    }

    inline void CopyBytesToMappableResource(const byte* data, size_t size, ID3D12Resource* resource, size_t offsetInBytes)
    {
        D3D12_RANGE range = { 0, 0 };
        BYTE* mappedData;
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(resource->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        memcpy(mappedData + offsetInBytes, data, size);
        resource->Unmap(subresourceIndex, nullptr);
    }

    inline void CloseAndExecuteUtilityCommandList()
    {
        ThrowIfFailed(g_utilityCommandList->Close());

        ID3D12CommandList* commandLists[] = { g_utilityCommandList.Get() };
        g_utilityCommandQueue->ExecuteCommandLists(1, commandLists);

        ThrowIfFailed(g_utilityCommandList->Reset(g_utilityCommandAllocator.Get(), nullptr));

        g_uploadBuffers->Signal(g_utilityCommandQueue.Get());

        g_lastFenceSignaled++;
        ThrowIfFailed(g_utilityCommandQueue->Signal(g_fence.Get(), g_lastFenceSignaled));
    }

    inline void CloseAndExecuteUtilityComputeCommandList()
    {
        ThrowIfFailed(g_utilityComputeCommandList->Close());

        ID3D12CommandList* commandLists[] = { g_utilityComputeCommandList.Get() };
        g_utilityComputeCommandQueue->ExecuteCommandLists(1, commandLists);

        ThrowIfFailed(g_utilityComputeCommandList->Reset(g_utilityComputeCommandAllocator.Get(), nullptr));

        g_lastFenceSignaled++;
        ThrowIfFailed(g_utilityComputeCommandQueue->Signal(g_fence.Get(), g_lastFenceSignaled));
    }

    inline void CloseAndExecuteUtilityCommandListIfPossible()
    {
        g_resourcesCount++;
        if (g_resourcesCount > 100)
        {
            CloseAndExecuteUtilityCommandList();
            g_resourcesCount = 0;
        }
    }

    inline void LazyInitUavHeap()
    {
        if (!g_tmpUavDescriptorHeap)
        {
            D3D12_DESCRIPTOR_HEAP_DESC desc{};
            desc.NumDescriptors = g_maxTmpUavDescriptors;
            desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE; // Can't be shader-visible
            desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;

            ThrowIfFailed(g_device->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&g_tmpUavDescriptorHeap)));
        }
    }

    inline void LazyInitCbvHeap()
    {
        if (!g_tmpCbvDescriptorHeap)
        {
            D3D12_DESCRIPTOR_HEAP_DESC desc{};
            desc.NumDescriptors = g_maxTmpCbvDescriptors;
            desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE; // Can't be shader-visible
            desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;

            ThrowIfFailed(g_device->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&g_tmpCbvDescriptorHeap)));
        }
    }

    inline void LazyInitSrvHeap()
    {
        if (!g_tmpSrvDescriptorHeap)
        {
            D3D12_DESCRIPTOR_HEAP_DESC desc{};
            desc.NumDescriptors = g_maxTmpSrvDescriptors;
            desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE; // Can't be shader-visible
            desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;

            ThrowIfFailed(g_device->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&g_tmpSrvDescriptorHeap)));
        }
    }

    inline D3D12_CPU_DESCRIPTOR_HANDLE CreateTemporaryCpuDescriptor_Uav(ID3D12Resource* resource, ID3D12Resource* counterResource, D3D12_UNORDERED_ACCESS_VIEW_DESC* desc, uint32_t offset = 0)
    {
        LazyInitUavHeap();

        D3D12_CPU_DESCRIPTOR_HANDLE uavHandle = g_tmpUavDescriptorHeap->GetCPUDescriptorHandleForHeapStart();
        uavHandle.ptr += offset * g_cbvSrvUavDescriptorSize;

        g_device->CreateUnorderedAccessView(resource, counterResource, desc, uavHandle);
        return uavHandle;
    }

    inline D3D12_CPU_DESCRIPTOR_HANDLE CreateTemporaryCpuDescriptor_SamplerFeedbackUav(ID3D12Resource* targetResource, ID3D12Resource* feedbackResource, uint32_t offset)
    {
        LazyInitUavHeap();

        ComPtr<ID3D12Device8> device8;
        ThrowIfFailed(g_device->QueryInterface(IID_PPV_ARGS(&device8)));

        D3D12_CPU_DESCRIPTOR_HANDLE uavHandle = g_tmpUavDescriptorHeap->GetCPUDescriptorHandleForHeapStart();
        uavHandle.ptr += offset * g_cbvSrvUavDescriptorSize;

        device8->CreateSamplerFeedbackUnorderedAccessView(targetResource, feedbackResource, uavHandle);
        return uavHandle;
    }

    inline D3D12_CPU_DESCRIPTOR_HANDLE CreateTemporaryCpuDescriptor_Cbv(D3D12_CONSTANT_BUFFER_VIEW_DESC const* pCbv, uint32_t offset)
    {
        LazyInitCbvHeap();

        CD3DX12_CPU_DESCRIPTOR_HANDLE cbvHandle(g_tmpCbvDescriptorHeap->GetCPUDescriptorHandleForHeapStart());
        cbvHandle.Offset(offset, g_device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV));

        g_device->CreateConstantBufferView(pCbv, cbvHandle);

        return cbvHandle;
    }

    inline D3D12_CPU_DESCRIPTOR_HANDLE CreateTemporaryCpuDescriptor_Srv(ID3D12Resource* pResource, D3D12_SHADER_RESOURCE_VIEW_DESC const* pSrvDesc, uint32_t offset)
    {
        LazyInitSrvHeap();

        CD3DX12_CPU_DESCRIPTOR_HANDLE srvHandle(g_tmpSrvDescriptorHeap->GetCPUDescriptorHandleForHeapStart());
        srvHandle.Offset(offset, g_device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV));

        g_device->CreateShaderResourceView(pResource, pSrvDesc, srvHandle);

        return srvHandle;
    }

    inline D3D12_HEAP_FLAGS D3D12HeapFlags(D3D12_HEAP_FLAGS heapFlags)
    {
        return heapFlags & ~(D3D12_HEAP_FLAG_CREATE_NOT_RESIDENT | D3D12_HEAP_FLAG_CREATE_NOT_ZEROED);
    }

    inline D3D12_CPU_DESCRIPTOR_HANDLE GetCpuDescriptor(ID3D12DescriptorHeap* heap, UINT offset)
    {
        D3D12_CPU_DESCRIPTOR_HANDLE descriptor = heap->GetCPUDescriptorHandleForHeapStart();
        switch(heap->GetDesc().Type)
        {
            case D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV:
                descriptor.ptr += offset * g_cbvSrvUavDescriptorSize;
                break;
            case D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER:
                descriptor.ptr += offset * g_samplerDescriptorSize;
                break;
            case D3D12_DESCRIPTOR_HEAP_TYPE_DSV:
                descriptor.ptr += offset * g_dsvDescriptorSize;
                break;
            case D3D12_DESCRIPTOR_HEAP_TYPE_RTV:
                descriptor.ptr += offset * g_rtvDescriptorSize;
                break;
            default:
                assert(false);
        }
        return descriptor;
    }

    inline D3D12_GPU_DESCRIPTOR_HANDLE GetGpuDescriptor(ID3D12DescriptorHeap* heap, UINT offset)
    {
        D3D12_GPU_DESCRIPTOR_HANDLE descriptor = heap->GetGPUDescriptorHandleForHeapStart();
        switch(heap->GetDesc().Type)
        {
            case D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV:
                descriptor.ptr += offset * g_cbvSrvUavDescriptorSize;
                break;
            case D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER:
                descriptor.ptr += offset * g_samplerDescriptorSize;
                break;
            case D3D12_DESCRIPTOR_HEAP_TYPE_DSV:
                descriptor.ptr += offset * g_dsvDescriptorSize;
                break;
            case D3D12_DESCRIPTOR_HEAP_TYPE_RTV:
                descriptor.ptr += offset * g_rtvDescriptorSize;
                break;
            default:
                assert(false);
        }
        return descriptor;
    }

    // CBV
    inline void CreateConstantBufferView(D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, D3D12_GPU_VIRTUAL_ADDRESS bufferLocation, UINT sizeInBytes)
    {
        D3D12_CONSTANT_BUFFER_VIEW_DESC cbvDesc = { bufferLocation, sizeInBytes };
        g_device->CreateConstantBufferView(&cbvDesc, destDescriptor);
    }

    inline void CreateConstantBufferView_NullDesc(D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor)
    {
        g_device->CreateConstantBufferView(nullptr, destDescriptor);
    }

    // Sampler
    inline void CreateSampler(D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, D3D12_FILTER filter, D3D12_TEXTURE_ADDRESS_MODE addressU, D3D12_TEXTURE_ADDRESS_MODE addressV, D3D12_TEXTURE_ADDRESS_MODE addressW, FLOAT mipLODBias, UINT maxAnisotropy, D3D12_COMPARISON_FUNC comparisonFunc, FLOAT borderColor_0, FLOAT borderColor_1, FLOAT borderColor_2, FLOAT borderColor_3, FLOAT minLOD, FLOAT maxLOD)
    {
        D3D12_SAMPLER_DESC samplerDesc = { filter, addressU, addressV, addressW, mipLODBias, maxAnisotropy, comparisonFunc, borderColor_0, borderColor_1, borderColor_2, borderColor_3, minLOD, maxLOD };
        g_device->CreateSampler(&samplerDesc, destDescriptor);
    }

    // Buffer SRV
    inline void CreateShaderResourceView_Buffer(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT64 firstElement, UINT numElements, UINT structureByStride, D3D12_BUFFER_SRV_FLAGS flags)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.Buffer = { firstElement, numElements, structureByStride, flags };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

#if D3D12_SDK_VERSION >= 619 || (defined(PREVIEW_BUILD) && D3D12_PREVIEW_SDK_VERSION >= 719)
    // Buffer Byte Offset SRV
    inline void CreateShaderResourceView_BufferByteOffset(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT64 offset, UINT64 size, UINT structureByteStride, D3D12_BUFFER_SRV_FLAGS flags)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.BufferByteOffset = { offset, size, structureByteStride, flags };

        ComPtr<ID3D12Device15> device15;
        ThrowIfFailed(g_device->QueryInterface(IID_PPV_ARGS(&device15)));
        ThrowIfFailed(device15->TryCreateShaderResourceView(pResource, &srvDesc, destDescriptor));
    }
#endif

    // Texture1D SRV
    inline void CreateShaderResourceView_Tex1D(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT mostDetailedMips, UINT mipLevels, FLOAT resourceMinLODClamp)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.Texture1D = { mostDetailedMips, mipLevels, resourceMinLODClamp };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // Texture1DArray SRV
    inline void CreateShaderResourceView_Tex1DArray(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT mostDetailedMip, UINT mipLevels, UINT firstArraySlice, UINT arraySize, FLOAT resourceMinLODClamp)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.Texture1DArray = { mostDetailedMip, mipLevels, firstArraySlice, arraySize, resourceMinLODClamp };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // Texture2D SRV
    inline void CreateShaderResourceView_Tex2D(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT mostDetailedMip, UINT mipLevels, UINT planeSlice, FLOAT resourceMinLODClamp)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.Texture2D = { mostDetailedMip, mipLevels, planeSlice, resourceMinLODClamp };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // Texture2DArray SRV
    inline void CreateShaderResourceView_Tex2DArray(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT mostDetailedMip, UINT mipLevels, UINT firstArraySlice, UINT arraySize, UINT planeSlice, FLOAT resourceMinLODClamp)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.Texture2DArray = { mostDetailedMip, mipLevels, firstArraySlice, arraySize, planeSlice, resourceMinLODClamp };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // Texture2DMS SRV
    inline void CreateShaderResourceView_Tex2DMS(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT unusedFiled_NothingToDefine)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.Texture2DMS = { unusedFiled_NothingToDefine };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // Texture2DMSArray SRV
    inline void CreateShaderResourceView_Tex2DMSArray(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT firstArraySlice, UINT arraySize)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.Texture2DMSArray = { firstArraySlice, arraySize };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // Texture3D SRV
    inline void CreateShaderResourceView_Tex3D(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT mostDetailedMips, UINT mipLevels, FLOAT resourceMinLODClamp)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.Texture3D = { mostDetailedMips, mipLevels, resourceMinLODClamp };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // TextureCube SRV
    inline void CreateShaderResourceView_TexCube(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT mostDetailedMips, UINT mipLevels, FLOAT resourceMinLODClamp)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.TextureCube = { mostDetailedMips, mipLevels, resourceMinLODClamp };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // TextureCubeArray SRV
    inline void CreateShaderResourceView_TexCubeArray(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, UINT mostDetailedMip, UINT mipLevels, UINT first2DArrayFace, UINT numCubes, FLOAT resourceMinLODClamp)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.TextureCubeArray = { mostDetailedMip, mipLevels, first2DArrayFace, numCubes, resourceMinLODClamp };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // RaytracingAccelerationStructure SRV
    inline void CreateShaderResourceView_RaytracingAS(ID3D12Resource* pResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_SRV_DIMENSION viewDimension, UINT shader4ComponentMapping, D3D12_GPU_VIRTUAL_ADDRESS location)
    {
        D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = { format, viewDimension, shader4ComponentMapping };
        srvDesc.RaytracingAccelerationStructure = { location };
        g_device->CreateShaderResourceView(pResource, &srvDesc, destDescriptor);
    }

    // Buffer UAV
    inline void CreateUnorderedAccessView_Buffer(ID3D12Resource* pResource, ID3D12Resource* pCounterResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_UAV_DIMENSION viewDimension, UINT64 firstElement, UINT numElements, UINT structureBytesStride, UINT64 counterOffsetInBytes, D3D12_BUFFER_UAV_FLAGS flags)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = { format, viewDimension };
        uavDesc.Buffer = { firstElement, numElements, structureBytesStride, counterOffsetInBytes, flags };
        g_device->CreateUnorderedAccessView(pResource, pCounterResource, &uavDesc, destDescriptor);
    }

#if D3D12_SDK_VERSION >= 619 || (defined(PREVIEW_BUILD) && D3D12_PREVIEW_SDK_VERSION >= 719)
    // Buffer Byte Offset UAV
    inline void CreateUnorderedAccessView_BufferByteOffset(ID3D12Resource* pResource, ID3D12Resource* pCounterResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_UAV_DIMENSION viewDimension, UINT64 offset, UINT size, UINT structureByteStride, UINT64 counterOffsetInBytes, D3D12_BUFFER_UAV_FLAGS flags)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = { format, viewDimension };
        uavDesc.BufferByteOffset = { offset, size, structureByteStride, counterOffsetInBytes, flags };

        ComPtr<ID3D12Device15> device15;
        ThrowIfFailed(g_device->QueryInterface(IID_PPV_ARGS(&device15)));
        ThrowIfFailed(device15->TryCreateUnorderedAccessView(pResource, pCounterResource, &uavDesc, destDescriptor));
    }
#endif

    // Texture1D UAV
    inline void CreateUnorderedAccessView_Tex1D(ID3D12Resource* pResource, ID3D12Resource* pCounterResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_UAV_DIMENSION viewDimension, UINT mipSlice)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = { format, viewDimension };
        uavDesc.Texture1D = { mipSlice };
        g_device->CreateUnorderedAccessView(pResource, pCounterResource, &uavDesc, destDescriptor);
    }

    // Texture1DArray UAV
    inline void CreateUnorderedAccessView_Tex1DArray(ID3D12Resource* pResource, ID3D12Resource* pCounterResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_UAV_DIMENSION viewDimension, UINT mipSlice, UINT firstArraySlice, UINT arraySize)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = { format, viewDimension };
        uavDesc.Texture1DArray = { mipSlice, firstArraySlice, arraySize };
        g_device->CreateUnorderedAccessView(pResource, pCounterResource, &uavDesc, destDescriptor);
    }

    // Texture2D UAV
    inline void CreateUnorderedAccessView_Tex2D(ID3D12Resource* pResource, ID3D12Resource* pCounterResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_UAV_DIMENSION viewDimension, UINT mipSlice, UINT planeSlice)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = { format, viewDimension };
        uavDesc.Texture2D = { mipSlice, planeSlice };
        g_device->CreateUnorderedAccessView(pResource, pCounterResource, &uavDesc, destDescriptor);
    }

    // Texture2DArray UAV
    inline void CreateUnorderedAccessView_Tex2DArray(ID3D12Resource* pResource, ID3D12Resource* pCounterResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_UAV_DIMENSION viewDimension, UINT mipSlice, UINT firstArraySlice, UINT arraySize,  UINT planeSlice)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = { format, viewDimension };
        uavDesc.Texture2DArray = { mipSlice, firstArraySlice, arraySize, planeSlice };
        g_device->CreateUnorderedAccessView(pResource, pCounterResource, &uavDesc, destDescriptor);
    }

    // Texture2DMS and Texture2DMSArray are added in NonEventGeneratedCode.h::GetTexture2DMSCode

    // Texture3D UAV
    inline void CreateUnorderedAccessView_Tex3D(ID3D12Resource* pResource, ID3D12Resource* pCounterResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_UAV_DIMENSION viewDimension, UINT mipSlice, UINT firstWSlice, UINT wSize)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = { format, viewDimension };
        uavDesc.Texture3D = { mipSlice, firstWSlice, wSize };
        g_device->CreateUnorderedAccessView(pResource, pCounterResource, &uavDesc, destDescriptor);
    }

    // SamplerFeedback UAV
    inline void CreateUnorderedAccessView_SamplerFeedback(ID3D12Resource* pTargetedResource, ID3D12Resource* pFeedbackResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor)
    {
        ComPtr<ID3D12Device8> device8;
        ThrowIfFailed(g_device->QueryInterface(IID_PPV_ARGS(&device8)));

        device8->CreateSamplerFeedbackUnorderedAccessView(pTargetedResource, pFeedbackResource, destDescriptor);
    }

    inline void CreateTextureCopyLocation_PlacedFootprint(D3D12_TEXTURE_COPY_LOCATION& textureCopyLocation, ID3D12Resource* resource, UINT64 offset, const D3D12_SUBRESOURCE_FOOTPRINT subresourceFootprint)
    {
        textureCopyLocation.pResource = resource;
        textureCopyLocation.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        textureCopyLocation.PlacedFootprint.Offset = offset;
        textureCopyLocation.PlacedFootprint.Footprint = subresourceFootprint;
    }

    inline void CreateTextureCopyLocation_SubresourceIndex(D3D12_TEXTURE_COPY_LOCATION& textureCopyLocation, ID3D12Resource* resource , UINT subresourceIndex)
    {
        textureCopyLocation.pResource = resource;
        textureCopyLocation.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        textureCopyLocation.SubresourceIndex = subresourceIndex;
    }

    inline D3D12_TEXTURE_COPY_LOCATION CreateTextureCopyLocation_PlacedFootprint(ID3D12Resource* resource, UINT64 offset, DXGI_FORMAT format, UINT width, UINT height, UINT depth, UINT rowPitch)
    {
        D3D12_TEXTURE_COPY_LOCATION textureCopyLocation = {};
        textureCopyLocation.pResource = resource;
        textureCopyLocation.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        textureCopyLocation.PlacedFootprint.Offset = offset;
        textureCopyLocation.PlacedFootprint.Footprint = { format, width, height, depth, rowPitch };
        return textureCopyLocation;
    }

    inline D3D12_TEXTURE_COPY_LOCATION CreateTextureCopyLocation_SubresourceIndex(ID3D12Resource* resource, UINT subresourceIndex)
    {
        D3D12_TEXTURE_COPY_LOCATION textureCopyLocation = {};
        textureCopyLocation.pResource = resource;
        textureCopyLocation.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        textureCopyLocation.SubresourceIndex = subresourceIndex;
        return textureCopyLocation;
    }

    inline D3D12_GPU_VIRTUAL_ADDRESS* GetBottomLevelPointersStart(D3D12_SERIALIZED_RAYTRACING_ACCELERATION_STRUCTURE_HEADER* headerStart)
    {
        auto* gpuvasStart = headerStart + 1;
        return reinterpret_cast<D3D12_GPU_VIRTUAL_ADDRESS*>(gpuvasStart);
    }

#if D3D12_SDK_VERSION >= 616 || (defined(PREVIEW_BUILD) && D3D12_PREVIEW_SDK_VERSION >= 717)
    inline D3D12_GPU_VIRTUAL_ADDRESS* GetBottomLevelPointersStart(D3D12_SERIALIZED_RAYTRACING_ACCELERATION_STRUCTURE_HEADER1* headerStart)
    {
        auto* gpuvasStart = headerStart + 1;
        return reinterpret_cast<D3D12_GPU_VIRTUAL_ADDRESS*>(gpuvasStart);
    }
#endif

    inline size_t GetOpaqueBlobOffsetInBytes(size_t numBottomLevelPointers)
    {
        return sizeof(D3D12_SERIALIZED_RAYTRACING_ACCELERATION_STRUCTURE_HEADER)
            + sizeof(D3D12_GPU_VIRTUAL_ADDRESS) * numBottomLevelPointers;
    }

    inline ComPtr<ID3D12Resource> CreateGenericReadUploadBufferFromBytes(ID3D12Device* pDevice, UINT64 resourceSizeInBytes, const void* pData, size_t dataSizeInBytes)
    {
        ComPtr<ID3D12Resource> buffer;

        D3D12_HEAP_PROPERTIES heapProperties = CD3DX12_HEAP_PROPERTIES(D3D12_HEAP_TYPE_UPLOAD);
        D3D12_RESOURCE_DESC resourceDesc = CD3DX12_RESOURCE_DESC::Buffer(resourceSizeInBytes);

        ThrowIfFailed(
            pDevice->CreateCommittedResource(
                &heapProperties,
                D3D12_HEAP_FLAG_NONE,
                &resourceDesc,
                D3D12_RESOURCE_STATE_GENERIC_READ,
                nullptr,
                IID_PPV_ARGS(&buffer))
        );

        void* pUploadData = nullptr;
        buffer->Map(0, nullptr, &pUploadData);
        memcpy(pUploadData, pData, dataSizeInBytes);
        buffer->Unmap(0, nullptr);

        return buffer;
    }

    inline DXGI_FORMAT ToFlipModelCompatibleFormat(DXGI_FORMAT format)
    {
        switch (format)
        {
        case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:   return DXGI_FORMAT_R8G8B8A8_UNORM;
        case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:   return DXGI_FORMAT_B8G8R8A8_UNORM;
        case DXGI_FORMAT_B8G8R8X8_UNORM_SRGB:   return DXGI_FORMAT_B8G8R8X8_UNORM;
        default:                                return format;
        }
    }

    inline void CreateWindowResources(ApiObjectId cmdQueueHandle, HWND wnd, DWORD width, DWORD height, DXGI_FORMAT format)
    {
        ComPtr<IDXGIFactory4> pDxgiFactory;

        // Swap Chain

        DXGI_SWAP_CHAIN_DESC1 descSwapChain;
        ZeroMemory(&descSwapChain, sizeof(descSwapChain));
        descSwapChain.BufferCount = 2;
        descSwapChain.Width = width;
        descSwapChain.Height = height;
        descSwapChain.Format = ToFlipModelCompatibleFormat(format);
        descSwapChain.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        descSwapChain.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
        descSwapChain.SampleDesc.Count = 1;
        descSwapChain.SampleDesc.Quality = 0;

        ThrowIfFailed(CreateDXGIFactory1(IID_PPV_ARGS(&pDxgiFactory)));

        ComPtr<IDXGISwapChain1> swapChain1;
        ThrowIfFailed(pDxgiFactory->CreateSwapChainForHwnd(
            GetCommandQueue(cmdQueueHandle),
            wnd,
            &descSwapChain,
            nullptr,
            nullptr,
            &swapChain1));

        ComPtr<IDXGISwapChain3> swapChain3;
        ThrowIfFailed(swapChain1.As(&swapChain3));

        g_swapChains[cmdQueueHandle] = swapChain3;

        // This sample does not support fullscreen transitions.
        ThrowIfFailed(pDxgiFactory->MakeWindowAssociation(wnd, DXGI_MWA_NO_ALT_ENTER));
    }

    inline D3D12_RAYTRACING_GEOMETRY_DESC CreateRaytracingGeometryDesc_Triangles(D3D12_RAYTRACING_GEOMETRY_FLAGS flags, D3D12_RAYTRACING_GEOMETRY_TRIANGLES_DESC trianglesDesc)
    {
        D3D12_RAYTRACING_GEOMETRY_DESC desc{};
        desc.Type = D3D12_RAYTRACING_GEOMETRY_TYPE_TRIANGLES;
        desc.Flags = flags;
        desc.Triangles = trianglesDesc;
        return desc;
    }

    inline D3D12_RAYTRACING_GEOMETRY_DESC CreateRaytracingGeometryDesc_AABBs(D3D12_RAYTRACING_GEOMETRY_FLAGS flags, D3D12_RAYTRACING_GEOMETRY_AABBS_DESC aabbsDesc)
    {
        D3D12_RAYTRACING_GEOMETRY_DESC desc{};
        desc.Type = D3D12_RAYTRACING_GEOMETRY_TYPE_PROCEDURAL_PRIMITIVE_AABBS;
        desc.Flags = flags;
        desc.AABBs = aabbsDesc;
        return desc;
    }

    class ShaderTableBuilder
    {
        byte* m_nextArgumentStart;
        const byte* m_recordStart;

        template<typename T>
        void AlignNextArgumentStart()
        {
            auto misalignment = (m_nextArgumentStart - m_recordStart) % sizeof(T);
            if (misalignment != 0)
            {
                m_nextArgumentStart += sizeof(T) - misalignment;
            }
        }

    public:
        ShaderTableBuilder(byte* argumentsStart, const byte* recordStart)
            : m_nextArgumentStart(argumentsStart)
            , m_recordStart(recordStart)
        {
        }

        void AddGpuDescriptorHandle(D3D12_GPU_DESCRIPTOR_HANDLE gpuDescriptorHandle)
        {
            AlignNextArgumentStart<D3D12_GPU_DESCRIPTOR_HANDLE>();
            memcpy(m_nextArgumentStart, &gpuDescriptorHandle, sizeof(gpuDescriptorHandle));
            m_nextArgumentStart += sizeof(D3D12_GPU_DESCRIPTOR_HANDLE);
        }

        void AddRootConstants(std::vector<uint32_t> rootConstants)
        {
            AlignNextArgumentStart<uint32_t>();
            memcpy(m_nextArgumentStart, rootConstants.data(), rootConstants.size() * sizeof(uint32_t));
            m_nextArgumentStart += sizeof(uint32_t) * rootConstants.size();
        }

        void AddGpuva(D3D12_GPU_VIRTUAL_ADDRESS gpuva)
        {
            AlignNextArgumentStart<D3D12_GPU_VIRTUAL_ADDRESS>();
            memcpy(m_nextArgumentStart, &gpuva, sizeof(gpuva));
            m_nextArgumentStart += sizeof(gpuva);
        }
    };

#if defined(D3D12_SDK_VERSION) && (D3D12_SDK_VERSION >= 606)
    // Texture2DMS UAV
    inline void CreateUnorderedAccessView_Tex2DMS(ID3D12Resource* pResource, ID3D12Resource* pCounterResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_UAV_DIMENSION viewDimension, UINT unusedFieldNothingToDefine)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = { format, viewDimension };
        uavDesc.Texture2DMS = { unusedFieldNothingToDefine };
        g_device->CreateUnorderedAccessView(pResource, pCounterResource, &uavDesc, destDescriptor);
    }

    // Texture2DMSArray UAV
    inline void CreateUnorderedAccessView_Tex2DMSArray(ID3D12Resource* pResource, ID3D12Resource* pCounterResource, D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, DXGI_FORMAT format, D3D12_UAV_DIMENSION viewDimension, UINT firstArraySlice, UINT arraySize)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = { format, viewDimension };
        uavDesc.Texture2DMSArray = { firstArraySlice, arraySize };
        g_device->CreateUnorderedAccessView(pResource, pCounterResource, &uavDesc, destDescriptor);
    }

    // Sampler2
    inline void CreateSampler2_UintBorderColor(D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, D3D12_FILTER filter, D3D12_TEXTURE_ADDRESS_MODE addressU, D3D12_TEXTURE_ADDRESS_MODE addressV, D3D12_TEXTURE_ADDRESS_MODE addressW, FLOAT mipLODBias, UINT maxAnisotropy, D3D12_COMPARISON_FUNC comparisonFunc, UINT borderColor_0, UINT borderColor_1, UINT borderColor_2, UINT borderColor_3, FLOAT minLOD, FLOAT maxLOD, D3D12_SAMPLER_FLAGS flags)
    {
        D3D12_SAMPLER_DESC2 samplerDesc = {};
        samplerDesc.Filter = filter;
        samplerDesc.AddressU = addressU;
        samplerDesc.AddressV = addressV;
        samplerDesc.AddressW = addressW;
        samplerDesc.MipLODBias = mipLODBias;
        samplerDesc.MaxAnisotropy = maxAnisotropy;
        samplerDesc.ComparisonFunc = comparisonFunc;
        samplerDesc.MinLOD = minLOD;
        samplerDesc.MaxLOD = maxLOD;
        samplerDesc.Flags = flags;
        samplerDesc.UintBorderColor[0] = borderColor_0;
        samplerDesc.UintBorderColor[1] = borderColor_1;
        samplerDesc.UintBorderColor[2] = borderColor_2;
        samplerDesc.UintBorderColor[3] = borderColor_3;
        ComPtr<ID3D12Device11> device11;
        ThrowIfFailed(g_device->QueryInterface(IID_PPV_ARGS(&device11)));
        device11->CreateSampler2(&samplerDesc, destDescriptor);
    }

    // Sampler2
    inline void CreateSampler2_FloatBorderColor(D3D12_CPU_DESCRIPTOR_HANDLE destDescriptor, D3D12_FILTER filter, D3D12_TEXTURE_ADDRESS_MODE addressU, D3D12_TEXTURE_ADDRESS_MODE addressV, D3D12_TEXTURE_ADDRESS_MODE addressW, FLOAT mipLODBias, UINT maxAnisotropy, D3D12_COMPARISON_FUNC comparisonFunc, float borderColor_0, float borderColor_1, float borderColor_2, float borderColor_3, FLOAT minLOD, FLOAT maxLOD, D3D12_SAMPLER_FLAGS flags)
    {
        D3D12_SAMPLER_DESC2 samplerDesc = {};
        samplerDesc.Filter = filter;
        samplerDesc.AddressU = addressU;
        samplerDesc.AddressV = addressV;
        samplerDesc.AddressW = addressW;
        samplerDesc.MipLODBias = mipLODBias;
        samplerDesc.MaxAnisotropy = maxAnisotropy;
        samplerDesc.ComparisonFunc = comparisonFunc;
        samplerDesc.MinLOD = minLOD;
        samplerDesc.MaxLOD = maxLOD;
        samplerDesc.Flags = flags;
        samplerDesc.FloatBorderColor[0] = borderColor_0;
        samplerDesc.FloatBorderColor[1] = borderColor_1;
        samplerDesc.FloatBorderColor[2] = borderColor_2;
        samplerDesc.FloatBorderColor[3] = borderColor_3;
        ComPtr<ID3D12Device11> device11;
        ThrowIfFailed(g_device->QueryInterface(IID_PPV_ARGS(&device11)));
        device11->CreateSampler2(&samplerDesc, destDescriptor);
    }

    inline void CreateAndTrackCommittedResource3(ApiObjectId handle, ID3D12Device4* pDevice, D3D12_HEAP_PROPERTIES* pHeapProperties, D3D12_HEAP_FLAGS HeapFlags, const D3D12_RESOURCE_DESC1* pDesc,
        D3D12_BARRIER_LAYOUT initialLayout, const D3D12_CLEAR_VALUE* pOptimizedClearValue, UINT32 numCastableFormats, DXGI_FORMAT* castableFormats)
    {
        ComPtr<ID3D12Device10> device10;
        ThrowIfFailed(pDevice->QueryInterface(IID_PPV_ARGS(&device10)));

        ComPtr<ID3D12Resource> resource;
        ThrowIfFailed(device10->CreateCommittedResource3(pHeapProperties, HeapFlags, pDesc, initialLayout, pOptimizedClearValue, nullptr, numCastableFormats, castableFormats, IID_PPV_ARGS(&resource)));
        g_resources[handle] = resource;
    }

    inline void CreateAndTrackPlacedResource2(ApiObjectId rHandle, ID3D12Device4* pDevice, const D3D12_RESOURCE_DESC1* pDesc, D3D12_BARRIER_LAYOUT initialLayout,
        const D3D12_CLEAR_VALUE* pOptimizedClearValue, ApiObjectId heapHandle, UINT heapOffset, UINT32 numCastableFormats, DXGI_FORMAT* castableFormats)
    {
        ComPtr<ID3D12Device10> device10;
        ThrowIfFailed(pDevice->QueryInterface(IID_PPV_ARGS(&device10)));

        ComPtr<ID3D12Resource> resource;
        ThrowIfFailed(device10->CreatePlacedResource2(g_heaps[heapHandle].Heap.Get(), heapOffset, pDesc, initialLayout, pOptimizedClearValue, numCastableFormats, castableFormats, IID_PPV_ARGS(&resource)));
        g_resources[rHandle] = resource;
        SetBaseGpuvaIfPossible(heapHandle, resource, heapOffset, pDesc->Dimension);
    }

    inline void CreateAndTrackReservedResource2(ApiObjectId handle, ID3D12Device4* pDevice, const D3D12_RESOURCE_DESC* pDesc, D3D12_BARRIER_LAYOUT initialLayout,
        const D3D12_CLEAR_VALUE* pOptimizedClearValue, UINT32 numCastableFormats, DXGI_FORMAT* castableFormats)
    {
        ComPtr<ID3D12Device10> device10;
        ThrowIfFailed(pDevice->QueryInterface(IID_PPV_ARGS(&device10)));

        ComPtr<ID3D12Resource> resource;
        ThrowIfFailed(device10->CreateReservedResource2(pDesc, initialLayout, pOptimizedClearValue, nullptr, numCastableFormats, castableFormats, IID_PPV_ARGS(&resource)));
        g_resources[handle] = resource;
    }

    inline bool IsComputeSpecificLayout(D3D12_BARRIER_LAYOUT layout)
    {
        switch (layout)
        {
        case D3D12_BARRIER_LAYOUT_COMPUTE_QUEUE_COMMON:
        case D3D12_BARRIER_LAYOUT_COMPUTE_QUEUE_COPY_DEST:
        case D3D12_BARRIER_LAYOUT_COMPUTE_QUEUE_COPY_SOURCE:
        case D3D12_BARRIER_LAYOUT_COMPUTE_QUEUE_GENERIC_READ:
        case D3D12_BARRIER_LAYOUT_COMPUTE_QUEUE_SHADER_RESOURCE:
        case D3D12_BARRIER_LAYOUT_COMPUTE_QUEUE_UNORDERED_ACCESS:
            return true;
        default:
            return false;
        }
    }

    inline void TransitionToFinalStates_EnhancedBarriers(
        ID3D12Resource* resource,
        D3D12_RESOURCE_STATES beforeState,
        std::variant<D3D12_RESOURCE_STATES, D3D12_BARRIER_LAYOUT>* finalBarrierStates,
        size_t numSubresources)
    {
        std::vector<D3D12_RESOURCE_BARRIER> legacyBarriers;
        std::vector<D3D12_TEXTURE_BARRIER> enhancedBarriers_DirectQueue;
        std::vector<D3D12_TEXTURE_BARRIER> enhancedBarriers_ComputeQueue;

        for (UINT i = 0; i < numSubresources; ++i)
        {
            const auto& finalBarrierState = finalBarrierStates[i];
            if (std::holds_alternative<D3D12_RESOURCE_STATES>(finalBarrierState))
            {
                D3D12_RESOURCE_STATES finalState = std::get<D3D12_RESOURCE_STATES>(finalBarrierState);
                if (beforeState != finalState)
                {
                    legacyBarriers.push_back(CD3DX12_RESOURCE_BARRIER::Transition(resource, beforeState, finalState, i, D3D12_RESOURCE_BARRIER_FLAG_NONE));
                }
            }
            else
            {
                D3D12_BARRIER_LAYOUT finalLayout = std::get<D3D12_BARRIER_LAYOUT>(finalBarrierState);
                legacyBarriers.push_back(CD3DX12_RESOURCE_BARRIER::Transition(resource, beforeState, D3D12_RESOURCE_STATE_COMMON, i, D3D12_RESOURCE_BARRIER_FLAG_NONE));
                if (finalLayout != D3D12_BARRIER_LAYOUT_COMMON)
                {
                    D3D12_TEXTURE_BARRIER textureBarrier{};
                    textureBarrier.SyncAfter = D3D12_BARRIER_SYNC_NONE;
                    textureBarrier.AccessAfter = D3D12_BARRIER_ACCESS_NO_ACCESS;
                    textureBarrier.LayoutBefore = D3D12_BARRIER_LAYOUT_COMMON;
                    textureBarrier.LayoutAfter = finalLayout;
                    textureBarrier.pResource = resource;
                    textureBarrier.Subresources.NumMipLevels = 0;
                    textureBarrier.Subresources.IndexOrFirstMipLevel = i;
                    if (IsComputeSpecificLayout(finalLayout))
                    {
                        textureBarrier.SyncBefore = D3D12_BARRIER_SYNC_NONE;
                        textureBarrier.AccessBefore = D3D12_BARRIER_ACCESS_NO_ACCESS;
                        enhancedBarriers_ComputeQueue.push_back(textureBarrier);
                    }
                    else
                    {
                        // These were just used in a legacy barrier, so it needs SYNC_ALL and ACCESS_COMMON.
                        textureBarrier.SyncBefore = D3D12_BARRIER_SYNC_ALL;
                        textureBarrier.AccessBefore = D3D12_BARRIER_ACCESS_COMMON;
                        enhancedBarriers_DirectQueue.push_back(textureBarrier);
                    }
                }
            }
        }

        if (legacyBarriers.size() > 0)
        {
            g_utilityCommandList->ResourceBarrier((UINT)legacyBarriers.size(), legacyBarriers.data());
        }

        if (enhancedBarriers_DirectQueue.size() > 0)
        {
            ComPtr<ID3D12GraphicsCommandList7> cl7;
            ThrowIfFailed(g_utilityCommandList.As(&cl7));

            D3D12_BARRIER_GROUP group;
            group.Type = D3D12_BARRIER_TYPE_TEXTURE;
            group.NumBarriers = (UINT)enhancedBarriers_DirectQueue.size();
            group.pTextureBarriers = enhancedBarriers_DirectQueue.data();
            cl7->Barrier(1, &group);
        }

        if (enhancedBarriers_ComputeQueue.size() > 0)
        {
            ComPtr<ID3D12GraphicsCommandList7> cl7;
            ThrowIfFailed(g_utilityComputeCommandList->QueryInterface(IID_PPV_ARGS(&cl7)));

            D3D12_BARRIER_GROUP group;
            group.Type = D3D12_BARRIER_TYPE_TEXTURE;
            group.NumBarriers = (UINT)enhancedBarriers_ComputeQueue.size();
            group.pTextureBarriers = enhancedBarriers_ComputeQueue.data();
            cl7->Barrier(1, &group);
        }
    }
#endif // D3D12_SDK_VERSION >= 606

    inline UINT64 GetBackBufferWidth_1()
    {
        return GetResource(18239)->GetDesc().Width;
    }

    inline UINT GetBackBufferHeight_1()
    {
        return GetResource(18239)->GetDesc().Height;
    }

    inline DXGI_FORMAT GetBackBufferFormat_1()
    {
        return GetResource(18239)->GetDesc().Format;
    }

}
