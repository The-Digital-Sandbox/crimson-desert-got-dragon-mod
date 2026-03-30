#include "pch.h"

#include "FrameResources.h"
#include "RenderFrame.h"
#include "ResourceModifications.h"

using namespace Helpers;

void RenderFrame()
{
    ResetCommandAllocators();
    RenderFrame_000();
    RenderFrame_001();
    RenderFrame_002();
    RenderFrame_003();
    RenderFrame_004();
    RenderFrame_005();
    RenderFrame_006();
    RenderFrame_007();
    RenderFrame_008();
    RenderFrame_009();
    RenderFrame_010();
    RenderFrame_011();
    RenderFrame_012();
    RenderFrame_013();
    RenderFrame_014();
    RenderFrame_015();
    RenderFrame_016();
    RenderFrame_017();
    RenderFrame_018();
    RenderFrame_019();
    RenderFrame_020();
    RenderFrame_021();
    RenderFrame_022();
    RenderFrame_023();
    RenderFrame_024();
    RenderFrame_025();
    RenderFrame_026();
    RenderFrame_027();
    RenderFrame_028();
    RenderFrame_029();
    RenderFrame_030();
    RenderFrame_031();
    RenderFrame_032();
    RenderFrame_033();
    RenderFrame_034();
    RenderFrame_035();
    RenderFrame_036();
    RenderFrame_037();
    RenderFrame_038();
    RenderFrame_039();
    RenderFrame_040();
    RenderFrame_041();
    RenderFrame_042();
    RenderFrame_043();
    RenderFrame_044();
    RenderFrame_045();
    RenderFrame_046();
    RenderFrame_047();
    RenderFrame_048();
    RenderFrame_049();

    // Some events like DispatchRays() can create new resources per frame.
    // Thus, these resources need to be released after GPU is done with them.
    g_perFrameBuffers.clear();
}