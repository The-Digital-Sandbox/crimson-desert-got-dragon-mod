#include "pch.h"
#include "ResourceReader.h"

#include <fileapi.h>

ResourceReader::ResourceReader()
{
    CreateDecompressor(COMPRESS_ALGORITHM_XPRESS, nullptr, &m_decompressor);

    std::string resourceFilePath = GetRelativePathToIfExists("resources.bin");
#ifdef RESOURCES_BIN_PATH
    if (resourceFilePath.empty())
        resourceFilePath = RESOURCES_BIN_PATH;
#endif

    if (!std::filesystem::exists(resourceFilePath))
    {
        std::string message = "Does " + resourceFilePath + " even exist?";
        OutputDebugString(message.c_str());
        exit(E_INVALIDARG);
    }

    m_resourcesFile = CreateFileA(
        resourceFilePath.c_str(),
        GENERIC_READ,
        FILE_SHARE_READ,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL);
    assert(m_resourcesFile != INVALID_HANDLE_VALUE);
}

ResourceReader::~ResourceReader()
{
    CloseHandle(m_resourcesFile);
    CloseDecompressor(m_decompressor);
}

void ResourceReader::Read(std::vector<BYTE>& decompressedBuffer, DWORD compressedDataSize)
{
    DWORD bytesRead;
    SIZE_T decompressedBufferSize{ 0 }, decompressedDataSize{ 0 };
    std::vector<BYTE> compressedBuffer;

    compressedBuffer.resize(compressedDataSize);
    
    bool success = ReadFile(m_resourcesFile, &compressedBuffer[0], compressedDataSize, &bytesRead, nullptr);
    assert(success);

    success = Decompress(
        m_decompressor,
        &compressedBuffer[0],
        bytesRead,
        NULL,
        0,
        &decompressedBufferSize);
    
    assert(!success);
    assert(GetLastError() == ERROR_INSUFFICIENT_BUFFER);

    decompressedBuffer.resize(decompressedBufferSize);

    success = Decompress(
        m_decompressor,
        &compressedBuffer[0],
        bytesRead,
        &decompressedBuffer[0],
        decompressedBufferSize,
        &decompressedDataSize);
    assert(success);
}

