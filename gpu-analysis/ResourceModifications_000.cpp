#pragma once

#include "pch.h"
#include "ResourceModifications.h"
#include "Helpers.h"

using namespace Helpers;

void ModifyResource_000_000(std::vector<BYTE>& data, size_t& offset)
{
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(1675).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_1675_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_1675_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(1675).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(8).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 255; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_8_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_8_0[255], &data[offset], 4096);
        offset += 4096;
        GetResource(8).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(7).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 255; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_7_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_7_0[255], &data[offset], 4096);
        offset += 4096;
        GetResource(7).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17152).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 3; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17152_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17152_0[3], &data[offset], 4096);
        offset += 4096;
        GetResource(17152).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17153).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 2; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17153_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17153_0[2], &data[offset], 4096);
        offset += 4096;
        GetResource(17153).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17154).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 4; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17154_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17154_0[4], &data[offset], 4096);
        offset += 4096;
        GetResource(17154).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17155).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 2; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17155_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17155_0[2], &data[offset], 4096);
        offset += 4096;
        GetResource(17155).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17156).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 9; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17156_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17156_0[9], &data[offset], 4096);
        offset += 4096;
        GetResource(17156).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17157).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 2; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17157_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17157_0[2], &data[offset], 4096);
        offset += 4096;
        GetResource(17157).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17158).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 8; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17158_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17158_0[8], &data[offset], 4096);
        offset += 4096;
        GetResource(17158).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17159).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 2; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17159_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17159_0[2], &data[offset], 4096);
        offset += 4096;
        GetResource(17159).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17160).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 7; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17160_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17160_0[7], &data[offset], 4096);
        offset += 4096;
        GetResource(17160).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17161).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 9; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17161_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17161_0[9], &data[offset], 4096);
        offset += 4096;
        GetResource(17161).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17162).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17162_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17162_0[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17162).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17166).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 8; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17166_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17166_0[8], &data[offset], 4096);
        offset += 4096;
        GetResource(17166).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17167).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17167_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17167_0[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17167).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17168).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 3; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17168_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17168_0[3], &data[offset], 4096);
        offset += 4096;
        GetResource(17168).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17169).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 2; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17169_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17169_0[2], &data[offset], 4096);
        offset += 4096;
        GetResource(17169).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17170).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 4; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17170_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17170_0[4], &data[offset], 4096);
        offset += 4096;
        GetResource(17170).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17171).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 8; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17171_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17171_0[8], &data[offset], 4096);
        offset += 4096;
        GetResource(17171).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17172).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 4; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17172_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17172_0[4], &data[offset], 4096);
        offset += 4096;
        GetResource(17172).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17173).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 9; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17173_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17173_0[9], &data[offset], 4096);
        offset += 4096;
        GetResource(17173).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17174).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 4; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17174_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17174_0[4], &data[offset], 4096);
        offset += 4096;
        GetResource(17174).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17176).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17176_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17176_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17176).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17177).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 5; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17177_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17177_0[5], &data[offset], 4096);
        offset += 4096;
        GetResource(17177).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17178).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17178_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17178_0[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17178).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17179).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 9; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17179_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17179_0[9], &data[offset], 4096);
        offset += 4096;
        GetResource(17179).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17180).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17180_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17180_0[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17180).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17181).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 9; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17181_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17181_0[9], &data[offset], 4096);
        offset += 4096;
        GetResource(17181).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17182).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17182_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17182_0[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17182).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17183).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 10; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17183_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17183_0[10], &data[offset], 4096);
        offset += 4096;
        GetResource(17183).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17184).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17184_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17184_0[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17184).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17185).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 11; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17185_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17185_0[11], &data[offset], 4096);
        offset += 4096;
        GetResource(17185).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17186).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17186_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17186_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17186).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17187).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17187_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17187_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17187).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17207).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 9; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17207_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17207_0[9], &data[offset], 4096);
        offset += 4096;
        GetResource(17207).Get()->Unmap(subresourceIndex, nullptr);
    }
}

void ModifyResource_000_001(std::vector<BYTE>& data, size_t& offset)
{
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17188).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17188_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17188_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17188).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17164).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17164_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17164_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17164).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17190).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17190_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17190_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17190).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17165).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17165_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17165_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17165).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17175).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17175_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17175_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17175).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17189).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17189_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17189_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17189).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17151).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17151_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17151_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17151).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17163).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17163_0[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17163_0[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17163).Get()->Unmap(subresourceIndex, nullptr);
    }
}

void ModifyResource_001_000(std::vector<BYTE>& data, size_t& offset)
{
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(7).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_7_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_7_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(7).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17166).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17166_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17166_1[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17166).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17167).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17167_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17167_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17167).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17171).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17171_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17171_1[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17171).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17172).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17172_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17172_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17172).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17173).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 6; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17173_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17173_1[6], &data[offset], 4096);
        offset += 4096;
        GetResource(17173).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17174).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17174_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17174_1[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17174).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17176).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17176_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17176_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17176).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17177).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17177_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17177_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17177).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17178).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17178_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17178_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17178).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17179).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 4; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17179_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17179_1[4], &data[offset], 4096);
        offset += 4096;
        GetResource(17179).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17180).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17180_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17180_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17180).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17181).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17181_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17181_1[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17181).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17184).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17184_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17184_1[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17184).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17185).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 9; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17185_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17185_1[9], &data[offset], 4096);
        offset += 4096;
        GetResource(17185).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17186).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17186_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17186_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17186).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17187).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17187_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17187_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17187).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17294).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17294_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17294_1[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17294).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17188).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17188_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17188_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17188).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17164).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17164_1[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17164_1[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17164).Get()->Unmap(subresourceIndex, nullptr);
    }
}

void ModifyResource_002_000(std::vector<BYTE>& data, size_t& offset)
{
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17327).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 1; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17327_2[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17327_2[1], &data[offset], 4096);
        offset += 4096;
        GetResource(17327).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17158).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17158_2[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17158_2[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17158).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17159).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17159_2[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17159_2[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17159).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17298).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17298_2[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17298_2[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17298).Get()->Unmap(subresourceIndex, nullptr);
    }
}

void ModifyResource_003_000(std::vector<BYTE>& data, size_t& offset)
{
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17211).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17211_3[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17211_3[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17211).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(7).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 4; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_7_3[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_7_3[4], &data[offset], 4096);
        offset += 4096;
        GetResource(7).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17152).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 2; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17152_3[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17152_3[2], &data[offset], 4096);
        offset += 4096;
        GetResource(17152).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17153).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17153_3[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17153_3[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17153).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17154).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17154_3[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17154_3[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17154).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17155).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 2; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17155_3[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17155_3[2], &data[offset], 4096);
        offset += 4096;
        GetResource(17155).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17156).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17156_3[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17156_3[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17156).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17157).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 0; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17157_3[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17157_3[0], &data[offset], 4096);
        offset += 4096;
        GetResource(17157).Get()->Unmap(subresourceIndex, nullptr);
    }
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17298).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 18; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17298_3[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17298_3[18], &data[offset], 4096);
        offset += 4096;
        GetResource(17298).Get()->Unmap(subresourceIndex, nullptr);
    }
}

void ModifyResource_004_000(std::vector<BYTE>& data, size_t& offset)
{
    {
        BYTE* mappedData;
        D3D12_RANGE range = { 0, 0 };
        constexpr uint32_t subresourceIndex = 0;
        ThrowIfFailed(GetResource(17211).Get()->Map(subresourceIndex, &range, reinterpret_cast<void**>(&mappedData)));
        for (auto i = 0u; i < 2; ++i)
        {
            memcpy(mappedData + 4096 * PagesIndex_17211_4[i], &data[offset], 4096);
            offset += 4096;
        }
        memcpy(mappedData + 4096 * PagesIndex_17211_4[2], &data[offset], 4096);
        offset += 4096;
        GetResource(17211).Get()->Unmap(subresourceIndex, nullptr);
    }
}

