#include "pch.h"
#include "Win32Application.h"

_Use_decl_annotations_
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int nCmdShow)
{
   return Win32Application::Run(hInstance, nCmdShow);
}
