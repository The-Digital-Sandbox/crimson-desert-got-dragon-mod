#include "pch.h"
#include "CapturedAssets.h"

UINT g_windowWidth = 1280u;
UINT g_windowHeight = 720u;
UINT g_frameIndex = 0u;
UINT g_rtvDescriptorSize = 0u;
UINT g_cbvSrvUavDescriptorSize = 0u;
UINT g_samplerDescriptorSize = 0u;
UINT g_dsvDescriptorSize = 0u;
UINT g_resourcesCount = 0u;
UINT64 g_lastFenceSignaled = 0u;
bool g_constructionNeeded = true;
std::wstring g_captureTimeAdapterDesc;
D3D_FEATURE_LEVEL g_minFeatureLevel;

D3D12_TEXTURE_COPY_LOCATION g_textureCopyLocationPlacedFootprint;
D3D12_TEXTURE_COPY_LOCATION g_textureCopyLocationSubresourceIndex;

ComPtr<IDXGIFactory> g_dxgiFactory;
ComPtr<ID3D12Device5> g_device;
ComPtr<ID3D12CommandAllocator> g_utilityCommandAllocator;
ComPtr<ID3D12GraphicsCommandList4> g_utilityCommandList;
ComPtr<ID3D12CommandQueue> g_utilityCommandQueue;
ComPtr<ID3D12CommandAllocator> g_utilityComputeCommandAllocator;
ComPtr<ID3D12GraphicsCommandList4> g_utilityComputeCommandList;
ComPtr<ID3D12CommandQueue> g_utilityComputeCommandQueue;
ComPtr<ID3D12Fence> g_fence;
ComPtr<ID3D12DescriptorHeap> g_rtvHeap;
ComPtr<ID3D12DescriptorHeap> g_dsvHeap;
ComPtr<ID3D12DescriptorHeap> g_tmpUavDescriptorHeap;
ComPtr<ID3D12DescriptorHeap> g_tmpCbvDescriptorHeap;
ComPtr<ID3D12DescriptorHeap> g_tmpSrvDescriptorHeap;
std::unordered_map<ApiObjectId, std::pair<ComPtr<ID3D12Fence>, UINT64>> g_utilityFencesInfo;

std::unique_ptr<ResourceReader> g_resourceReader = std::make_unique<ResourceReader>();
std::unique_ptr<UploadBuffers::Allocator> g_uploadBuffers = nullptr;

std::vector<ComPtr<ID3D12Resource>> g_stagingResources;

std::unordered_map<ApiObjectId, ComPtr<ID3D12Resource>> g_resources;
std::unordered_map<std::string, ComPtr<ID3D12Resource>> g_indirectArgumentBuffers;
std::unordered_map<std::string, ComPtr<ID3D12Resource>> g_countBuffers;
std::unordered_map<ApiObjectId, ComPtr<ID3D12GraphicsCommandList6>> g_commandLists;
std::unordered_map<ApiObjectId, ComPtr<ID3D12CommandAllocator>> g_commandAllocators;
std::unordered_set<ApiObjectId> g_bundleAllocatorsHandles;
std::unordered_map<ApiObjectId, ComPtr<ID3D12CommandQueue>> g_commandQueues;
std::unordered_map<ApiObjectId, ComPtr<ID3D12Fence>> g_fences;
std::unordered_map<ApiObjectId, ComPtr<ID3D12RootSignature>> g_rootSignatures;
std::unordered_map<ApiObjectId, ComPtr<ID3D12CommandSignature>> g_commandSignatures;
std::unordered_map<ApiObjectId, ComPtr<ID3D12PipelineState>> g_psos;
std::unordered_map<ApiObjectId, ComPtr<ID3D12DescriptorHeap>> g_descHeaps;
std::unordered_map<ApiObjectId, D3D12Heap> g_heaps;
std::unordered_map<ApiObjectId, ComPtr<ID3D12QueryHeap>> g_queryHeaps;
std::unordered_map<ApiObjectId, ComPtr<ID3D12StateObject>> g_stateObjects;
std::unordered_map<ApiObjectId, ComPtr<ID3D12MetaCommand>> g_metaCommands;
std::unordered_map<ApiObjectId, ComPtr<IDXGISwapChain3>> g_swapChains;
std::unordered_map<ApiObjectId, HWND> g_hWnds;
#if defined(DIRECT3D_EXPERIMENTAL_BUILD)
std::unordered_map<ApiObjectId, ComPtr<ID3D12Extension>> g_d3dExtensions;
#endif

std::vector<ComPtr<ID3D12Resource>> g_perFrameBuffers;
        
ComPtr<ID3D12DescriptorHeap> g_descriptorHeap_392;
ComPtr<ID3D12DescriptorHeap> g_descriptorHeap_393;
UINT g_maxTmpCbvDescriptors = 0;
UINT g_maxTmpSrvDescriptors = 0;
UINT g_maxTmpUavDescriptors = 0;
