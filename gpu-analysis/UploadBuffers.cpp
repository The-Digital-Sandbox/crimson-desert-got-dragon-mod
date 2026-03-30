#include "pch.h"

#include "UploadBuffers.h"
#include "AllocationTracker.h"
#include "Helpers.h"

#include <iterator>

namespace UploadBuffers
{
    //
    // Allocator implementation
    //

    class Allocator::Impl
    {
        Microsoft::WRL::ComPtr<ID3D12Device> m_device;
        Microsoft::WRL::ComPtr<ID3D12Fence> m_fence;

        struct Heap
        {
            Microsoft::WRL::ComPtr<ID3D12Resource> Resource;
            AllocationTracker Allocations;

            Heap(Microsoft::WRL::ComPtr<ID3D12Resource> resource, uint64_t size)
                : Resource(std::move(resource))
                , Allocations(size)
            {
            }
        };

        struct Alloc
        {
            Heap* Heap;
            uint64_t Begin;
            uint64_t FenceValue;

            bool operator!= (Allocation const& a) const
            {
                return (a.GetResource() != Heap->Resource.Get() || a.GetOffset() != Begin);
            }
        };

        std::vector<std::unique_ptr<Heap>> m_heaps;
        std::optional<Alloc> m_activeAlloc;
        std::vector<Alloc> m_markedFreeAllocs;
        std::vector<Alloc> m_pendingFreedAllocs;

        uint64_t m_nextFence = 1;

    public:
        Impl(ID3D12Device* device)
            : m_device(device)
        {
            Helpers::ThrowIfFailed(m_device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&m_fence)));
        }

        ~Impl()
        {
            uint64_t highestFreedFence = std::accumulate(
                m_pendingFreedAllocs.begin(),
                m_pendingFreedAllocs.end(),
                uint64_t{ 0 },
                [] (auto a, auto b) { return std::max(a, b.FenceValue); });

            if (highestFreedFence > 0)
            {
                HANDLE event = CreateEvent(nullptr, TRUE, FALSE, nullptr);
                Helpers::ThrowIfFailed(m_fence->SetEventOnCompletion(highestFreedFence, event));
                WaitForSingleObject(event, INFINITE);
            }
        }

        Allocation Allocate(uint64_t size)
        {
            if (m_activeAlloc)
            {
                throw (E_UNEXPECTED);
            }

            CheckForCompletedFreeAllocations();

            m_activeAlloc = AllocateFromHeap(size);

            return Allocation{ this, m_activeAlloc->Heap->Resource.Get(), m_activeAlloc->Begin };
        }

        void MarkFree(Allocation const& allocation)
        {
            if (!m_activeAlloc || *m_activeAlloc != allocation)
            {
                throw E_UNEXPECTED;
            }

            m_markedFreeAllocs.push_back(*m_activeAlloc);
            m_activeAlloc = std::nullopt;
        }

        void Signal(ID3D12CommandQueue* commandQueue)
        {
            if (m_markedFreeAllocs.empty())
                return;

            uint64_t value = m_markedFreeAllocs.back().FenceValue;
            Helpers::ThrowIfFailed(commandQueue->Signal(m_fence.Get(), value));

            m_pendingFreedAllocs.insert(m_pendingFreedAllocs.end(), m_markedFreeAllocs.begin(), m_markedFreeAllocs.end());
            m_markedFreeAllocs.clear();
        }

    private:
        void CheckForCompletedFreeAllocations()
        {
            uint64_t completedFenceValue = m_fence->GetCompletedValue();

            std::vector<Alloc>::iterator completedEnd = m_pendingFreedAllocs.end();
            for (auto it = m_pendingFreedAllocs.begin(); it != m_pendingFreedAllocs.end(); ++it)
            {
                if (it->FenceValue > completedFenceValue)
                {
                    completedEnd = it;
                    break;
                }
            }

            // Allocations from m_pendingFreedAllocs.begin() to completedEnd
            // have been completed.
            for (auto it = m_pendingFreedAllocs.begin(); it != completedEnd; ++it)
            {
                auto heap = it->Heap;
                heap->Allocations.Free(it->Begin);
            }

            m_pendingFreedAllocs.erase(m_pendingFreedAllocs.begin(), completedEnd);
        }

        Alloc AllocateFromHeap(uint64_t size)
        {
            for (auto& heap : m_heaps)
            {
                if (auto offset = heap->Allocations.Allocate(size, D3D12_TEXTURE_DATA_PLACEMENT_ALIGNMENT))
                {
                    return Alloc{ heap.get(), *offset, m_nextFence++ };
                }
            }

            m_heaps.push_back(MakeNewHeap(size));
            return Alloc{ m_heaps.back().get(), *m_heaps.back()->Allocations.Allocate(size, D3D12_TEXTURE_DATA_PLACEMENT_ALIGNMENT), m_nextFence++ };
        }

        std::unique_ptr<Heap> MakeNewHeap(uint64_t size)
        {
            // It's the caller's responsibility to make sure that they're allocating below the max mappable buffer size
            assert(size <= D3D12_MAX_CPU_MAPPABLE_BUFFER_SIZE);

            // Round size up to the nearest MB
            constexpr uint64_t megabyte = 1024 * 1024;
            size = ((size / megabyte) + 1) * megabyte;

            // ...and double it... to a point. Some drivers don't like mapping >= ~2GB buffers, so we shouldn't exceed this.
            // One exception: we exceed 2GB if the requested buffer is >=2GB. If the user was able to capture this scenario,
            // then we would have mapped >=2GB buffers at capture time, so the driver must support it.
            constexpr uint64_t oneGigabyte = 1024ull * 1024ull * 1024ull;
            if (size < oneGigabyte)
            {
                size *= 2;
            }

            // But keep us below D3D12_MAX_CPU_MAPPABLE_BUFFER_SIZE, so that we can definitely map the resource
            size = std::min(size, D3D12_MAX_CPU_MAPPABLE_BUFFER_SIZE);

            D3D12_HEAP_PROPERTIES heapProperties = CD3DX12_HEAP_PROPERTIES(D3D12_HEAP_TYPE_UPLOAD);
            D3D12_RESOURCE_DESC resourceDesc = CD3DX12_RESOURCE_DESC::Buffer(size);

            ComPtr<ID3D12Resource> resource;
            Helpers::ThrowIfFailed(m_device->CreateCommittedResource(
                &heapProperties,
                D3D12_HEAP_FLAG_NONE,
                &resourceDesc,
                D3D12_RESOURCE_STATE_GENERIC_READ,
                nullptr,
                IID_PPV_ARGS(&resource)));

            return std::make_unique<Heap>(std::move(resource), size);
        }
    };

    Allocator::Allocator(ID3D12Device* device)
        : m_impl(std::make_unique<Impl>(device))
    {
    }

    Allocator::~Allocator() = default;

    Allocation Allocator::Allocate(uint64_t size)
    {
        return m_impl->Allocate(size);
    }

    void Allocator::Signal(ID3D12CommandQueue* commandQueue)
    {
        m_impl->Signal(commandQueue);
    }


    //
    // Allocation implementation
    //
        
    Allocation::Allocation(Allocator::Impl* allocator, ID3D12Resource* resource, uint64_t offset)
        : m_allocator(allocator)
        , m_resource(resource)
        , m_offset(offset)
    {
    }

        
    Allocation::~Allocation()
    {
        if (m_allocator)
            m_allocator->MarkFree(*this);
    }

        
    Allocation::Allocation(Allocation&& other) noexcept
        : m_allocator(nullptr)
        , m_resource(nullptr)
        , m_offset(0)
    {
        *this = std::move(other);
    }

        
    Allocation& Allocation::operator= (Allocation&& other) noexcept
    {
        std::swap(other.m_allocator, m_allocator);
        std::swap(other.m_resource, m_resource);
        std::swap(other.m_offset, m_offset);
        return *this;
    }

        
    ID3D12Resource* Allocation::GetResource() const
    {
        return m_resource;
    }

        
    uint64_t Allocation::GetOffset() const
    {
        return m_offset;
    }
}
