#pragma once
#include <optional>

namespace UploadBuffers
{
    template< typename T >
    inline bool IsPow2(T Val)
    {
        static_assert(static_cast<T>(-1) > 0, "Signed type passed to IsPow2");
        return 0 == (Val & (Val - 1));
    }

    class AllocationTracker
    {
        struct Region
        {
            uint64_t Begin;
            uint64_t End;

            bool operator< (Region const& o) const
            {
                return Begin < o.Begin;
            }
        };

        // Due to alignment, the value we return from Allocate isn't necessarily
        // the beginning of the region.
        struct AllocatedRegion
        {
            uint64_t Offset;    // the value returned by Allocate
            Region Region;      // the actual region

            bool operator< (uint64_t offset) const
            {
                return Offset < offset;
            }
        };

        std::vector<Region> m_freeRegions;
        std::vector<AllocatedRegion> m_allocatedRegions;
        
    public:
        explicit AllocationTracker(uint64_t size)
        {
            m_freeRegions.push_back(Region{ 0, size });
        }

        std::optional<uint64_t> Allocate(uint64_t size, uint64_t alignment)
        {
            for (auto it = m_freeRegions.begin(); it != m_freeRegions.end(); ++it)
            {
                auto& region = *it;

                auto padding = GetAlignmentPadding(region.Begin, alignment);
                auto paddedSize = padding + size;

                if (region.End - region.Begin >= paddedSize)
                {
                    Region allocatedRegion{ region.Begin, region.Begin + paddedSize };
                    auto offset = allocatedRegion.Begin + padding;

                    region.Begin = allocatedRegion.End;

                    AddAllocatedRegion(offset, allocatedRegion);

                    CleanupFreeRegions();

                    return offset;
                }
            }

            return std::nullopt;
        }

        void Free(uint64_t offset)
        {
            Region r = TakeAllocatedRegion(offset);

            auto it = std::lower_bound(
                m_freeRegions.begin(),
                m_freeRegions.end(),
                r);

            m_freeRegions.insert(it, r);

            CleanupFreeRegions();
        }

    private:

        static uint64_t GetAlignmentPadding(uint64_t value, uint64_t alignment)
        {
            IsPow2(alignment);

            uint64_t padding = alignment - (value & (alignment - 1));
            padding = padding & (alignment - 1); // Handles the case where padding == alignment

            return padding;
        }
        
        void AddAllocatedRegion(uint64_t o, Region r)
        {
            auto it = std::lower_bound(m_allocatedRegions.begin(), m_allocatedRegions.end(), o);
            assert(it == m_allocatedRegions.end() || it->Offset != o);

            m_allocatedRegions.insert(it, AllocatedRegion{ o, r });
        }

        Region TakeAllocatedRegion(uint64_t offset)
        {
            auto it = std::lower_bound(
                m_allocatedRegions.begin(),
                m_allocatedRegions.end(),
                offset);

            if (it == m_allocatedRegions.end() || it->Offset != offset)
            {
                throw E_UNEXPECTED;
            }

            Region r = it->Region;
            m_allocatedRegions.erase(it);

            return r;
        }

        void CleanupFreeRegions()
        {
            auto it = m_freeRegions.begin();

            while (it != m_freeRegions.end())
            {
                // Remove empty regions
                if ((it->End - it->Begin) == 0)
                {
                    it = m_freeRegions.erase(it);
                    continue;
                }

                auto next = it;
                ++next;

                if (next != m_freeRegions.end())
                {
                    // TOOL_ASSERT(it->End <= next->Begin);

                    if (next->Begin == it->End)
                    {
                        it->End = next->End;
                        m_freeRegions.erase(next);
                        // The erase will invalidate all iterators from 'next'
                        // onwards.  'it' is still valid, and in fact we want to
                        // re-evaluate 'it' to see if it can be merged into
                        // whatever is now after it.
                        continue;
                    }
                }

                it = next;
            }
        }
    };
}
            