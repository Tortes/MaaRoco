#include "common.h"
#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>

namespace roco
{
namespace
{
bool focus_controller(MaaController *controller)
{
    if (!controller || !AXIsProcessTrusted())
    {
        log("MacOSInput", "Grant Accessibility permission to MaaRoco and its Agent, then restart the app.");
        return false;
    }
    auto buffer = MaaStringBufferCreate();
    const bool ok = MaaControllerGetInfo(controller, buffer);
    const auto info = params(MaaStringBufferGet(buffer));
    MaaStringBufferDestroy(buffer);
    if (!ok || info.get("type", std::string()) != "macos")
        return false;
    const auto window = static_cast<CGWindowID>(number(info, "window_id", 0, 0, UINT32_MAX));
    if (!window)
        return false;
    @autoreleasepool
    {
        CFArrayRef list = CGWindowListCopyWindowInfo(kCGWindowListOptionIncludingWindow, window);
        if (!list || CFArrayGetCount(list) == 0)
        {
            if (list) CFRelease(list);
            return false;
        }
        auto item = static_cast<CFDictionaryRef>(CFArrayGetValueAtIndex(list, 0));
        auto owner = static_cast<CFNumberRef>(CFDictionaryGetValue(item, kCGWindowOwnerPID));
        pid_t pid = 0;
        if (owner) CFNumberGetValue(owner, kCFNumberIntType, &pid);
        CFRelease(list);
        if (pid <= 0)
            return false;
        NSRunningApplication *app = [NSRunningApplication runningApplicationWithProcessIdentifier:pid];
        if (!app)
            return false;
        [app activateWithOptions:NSApplicationActivateIgnoringOtherApps];
        for (int i = 0; i < 5; ++i)
        {
            if ([NSWorkspace sharedWorkspace].frontmostApplication.processIdentifier == pid)
                return true;
            sleep(50);
        }
    }
    log("MacOSInput", "Could not activate the selected game window; input skipped.");
    return false;
}
int mac_key(int key)
{
    // Custom battle actions keep their Windows VK parameters on both platforms.
    switch (key)
    {
    case 32: return 49; // Space
    case 49: return 18; // 1
    case 50: return 19; // 2
    case 51: return 20; // 3
    case 52: return 21; // 4
    case 87: return 13; // W
    default: return -1;
    }
}
} // namespace
bool battle_key(MaaController *controller, int key)
{
    const int code = mac_key(key);
    if (code < 0 || !focus_controller(controller))
        return false;
    const bool down = MaaControllerWait(controller, MaaControllerPostKeyDown(controller, code)) == MaaStatus_Succeeded;
    sleep(100);
    const bool up = MaaControllerWait(controller, MaaControllerPostKeyUp(controller, code)) == MaaStatus_Succeeded;
    return down && up;
}
bool relative_move(MaaController *controller, int dx, int dy)
{
    if (!focus_controller(controller))
        return false;
    CGEventRef current = CGEventCreate(nullptr);
    if (!current)
        return false;
    const CGPoint position = CGEventGetLocation(current);
    CFRelease(current);
    const bool held = CGEventSourceButtonState(kCGEventSourceStateCombinedSessionState, kCGMouseButtonLeft);
    CGEventRef event = CGEventCreateMouseEvent(nullptr, held ? kCGEventLeftMouseDragged : kCGEventMouseMoved,
                                              position, kCGMouseButtonLeft);
    if (!event)
        return false;
    // Keep the cursor anchored while delivering deltas to a mouse-look game.
    // Games/compatibility layers may ignore synthetic deltas; this preview requires a live test.
    CGEventSetIntegerValueField(event, kCGMouseEventDeltaX, dx);
    CGEventSetIntegerValueField(event, kCGMouseEventDeltaY, dy);
    CGEventPost(kCGHIDEventTap, event);
    CFRelease(event);
    return true;
}
} // namespace roco
