#include "pch.h"
#include "Win32Application.h"

using namespace Helpers;

static bool m_doingGraphicsWork = false;

#ifdef AGILITY_SDK
#ifdef PREVIEW_BUILD
extern "C" { __declspec(dllexport) extern const UINT D3D12SDKVersion = D3D12_PREVIEW_SDK_VERSION; }
#else
extern "C" { __declspec(dllexport) extern const UINT D3D12SDKVersion = D3D12_SDK_VERSION; }
#endif
extern "C" { __declspec(dllexport) extern const char* D3D12SDKPath = u8".\\D3D12\\"; }
#endif

// Main message handler for the sample.
LRESULT CALLBACK WindowProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam)
{
    switch (message)
    {
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;

    default:
        break;
    }

    // Handle any messages the switch statement didn't.
    return DefWindowProc(hWnd, message, wParam, lParam);
}

HWND CreateAndShowWindow(const char* windowTitle, int windowWidth, int windowHeight)
{
    HWND hWnd;
    WNDCLASSEX windowClass;

    // init window class
    ZeroMemory(&windowClass, sizeof(WNDCLASSEX));
    windowClass.cbSize = sizeof(WNDCLASSEX);
    windowClass.style = CS_HREDRAW | CS_VREDRAW;
    windowClass.lpfnWndProc = WindowProc;
    windowClass.hInstance = GetModuleHandle(0);
    windowClass.hCursor = LoadCursor(NULL, IDC_ARROW);
    windowClass.lpszClassName = "PixCaptureReplayerClass";
    RegisterClassEx(&windowClass);

    RECT windowRect = { 0, 0, windowWidth, windowHeight };
    AdjustWindowRect(&windowRect, WS_OVERLAPPEDWINDOW, FALSE);    // adjust the size

    // Create the window and store a handle to it
    hWnd = CreateWindow(
        windowClass.lpszClassName,
        windowTitle,
        WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT,
        CW_USEDEFAULT,
        windowRect.right - windowRect.left,
        windowRect.bottom - windowRect.top,
        nullptr,                                     // We have no parent window.
        nullptr,                                     // We aren't using menus.
        GetModuleHandle(0),                          // application handle
        nullptr);

    // Show the window
    ShowWindow(hWnd, SW_SHOWDEFAULT);

    return hWnd;
}

void DestroyWindows()
{
    for (auto it : g_hWnds)
    {
        DestroyWindow(it.second);
    }
}


DWORD WINAPI DoWork(LPVOID lpParam)
{
    CreateAppResources();
    if (g_constructionNeeded)
    {
        CreateWindowResources(1, g_hWnds[1], (DWORD)GetBackBufferWidth_1(), GetBackBufferHeight_1(), GetBackBufferFormat_1());
    }
    RenderFrame();
    DestroyAppResources();
    m_doingGraphicsWork = false;
    return 0;
}

int Win32Application::Run(HINSTANCE hInstance, int nCmdShow)
{
    bool threadSuspended = true;
    HANDLE workerThread = CreateThread(NULL, 0, DoWork, nullptr, CREATE_SUSPENDED, nullptr);
    assert(workerThread != 0);
    g_hWnds[1] = CreateAndShowWindow("CrimsonDesert", g_windowWidth, g_windowHeight);

    // Main sample loop.
    MSG msg = {};
    while (msg.message != WM_QUIT)
    {   // Process any messages in the queue.
        if (PeekMessage(&msg, NULL, 0, 0, PM_REMOVE))
        {
            TranslateMessage(&msg);
            DispatchMessage(&msg);
        }
        else
        {
            // Creating and destroying app resources per frame is a heavy workload. Doing such lengthy
            // processing inside window proc can block any other messages for windows created on the
            // same thread. This means the app will be unresponsive during this time. So, we use a
            // worker thread to do this heavy work, and let the main thread continue handle other window
            // messages.
            if (!m_doingGraphicsWork)
            {
                m_doingGraphicsWork = true;
                if (threadSuspended)
                {
                    threadSuspended = false;
                    ResumeThread(workerThread);
                }
                else
                {
                    CloseHandle(workerThread);
                    workerThread = CreateThread(NULL, 0, DoWork, nullptr, 0, nullptr);
                }
            }
        }
    }

    DWORD exitCode{};
    BOOL result = GetExitCodeThread(workerThread, &exitCode);
    assert(result != 0);

    if (exitCode == STILL_ACTIVE)
    {
        WaitForSingleObject(workerThread, INFINITE);
        CloseHandle(workerThread);
    }

    DestroyAppResources();
    DestroyWindows();

    // Return this part of the WM_QUIT message to Windows.
    return static_cast<char>(msg.wParam);
}
