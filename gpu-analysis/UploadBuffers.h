#pragma once

#define D3D12_MAX_CPU_MAPPABLE_BUFFER_SIZE (UINT64)(UINT_MAX - 1024 * 64)

namespace UploadBuffers
{
    class Allocation;
        
    class Allocator
    {
        friend class Allocation;
            
        class Impl;
        std::unique_ptr<Impl> m_impl;

    public:
        Allocator(ID3D12Device* device);
        ~Allocator();

        Allocation Allocate(uint64_t size);

        // Writes a Signal to the command queue to indicate that the GPU has
        // finished with all allocations.
        void Signal(ID3D12CommandQueue* commandQueue);            
    };


    class Allocation
    {
        Allocator::Impl* m_allocator;
        ID3D12Resource* m_resource;
        uint64_t m_offset;

    public:
        Allocation(Allocator::Impl* allocator, ID3D12Resource* resource, uint64_t offset);
        ~Allocation();

        Allocation(Allocation const&) = delete;
        Allocation& operator= (Allocation const&) = delete;

        Allocation(Allocation&&) noexcept;
        Allocation& operator= (Allocation&&) noexcept;

        ID3D12Resource* GetResource() const;
        uint64_t GetOffset() const;
    };
}
