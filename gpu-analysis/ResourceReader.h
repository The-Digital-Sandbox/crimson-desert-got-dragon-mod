#pragma once

#include <compressapi.h>
#include <filesystem>
#include <handleapi.h>
#include <vector>

typedef UINT32 ApiObjectId;

class ResourceReader
{
    DECOMPRESSOR_HANDLE m_decompressor = nullptr;
    HANDLE m_resourcesFile = INVALID_HANDLE_VALUE;

public:
    ResourceReader();
    ~ResourceReader();

    void Read(std::vector<BYTE>& decompressedBuffer, DWORD compressedDataSize);

    static std::string GetRelativePathToIfExists(const std::string name)
    {
        static const std::vector<std::string> possibleSrcDirPaths = {
			".\\",
			".\\..\\",
			".\\..\\..\\",
			".\\..\\..\\..\\"
        };

        for (auto path : possibleSrcDirPaths)
        {
            auto possibleValidPath = path + "\\" + name;
            if (std::filesystem::exists(possibleValidPath))
            {
                return possibleValidPath;
            }
        }
        return std::string();
    }
};