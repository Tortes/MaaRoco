#include "common.h"
#include <cstdint>
#include <mutex>
#include <winioctl.h>

namespace roco
{
namespace
{
// Interception's public driver protocol; no Python package or extra DLL needed.
constexpr DWORD write_ioctl = CTL_CODE(FILE_DEVICE_UNKNOWN, 0x820, METHOD_BUFFERED, FILE_ANY_ACCESS);
constexpr DWORD hardware_ioctl = CTL_CODE(FILE_DEVICE_UNKNOWN, 0x880, METHOD_BUFFERED, FILE_ANY_ACCESS);
struct MouseStroke
{
    uint16_t unit{}, flags{}, buttons{}, data{};
    uint32_t raw{};
    int32_t x{}, y{};
    uint32_t info{};
};
struct KeyStroke
{
    uint16_t unit{}, code{}, state{}, reserved{};
    uint32_t info{};
};
static_assert(sizeof(MouseStroke) == 24 && sizeof(KeyStroke) == 12);
struct Device
{
    HANDLE handle = INVALID_HANDLE_VALUE;
    ~Device()
    {
        if (handle != INVALID_HANDLE_VALUE)
            CloseHandle(handle);
    }
    bool open(bool keyboard)
    {
        if (handle != INVALID_HANDLE_VALUE)
        {
            CloseHandle(handle);
            handle = INVALID_HANDLE_VALUE;
        }
        for (int i = keyboard ? 0 : 10; i < (keyboard ? 10 : 20); ++i)
        {
            wchar_t path[64];
            swprintf_s(path, L"\\\\.\\interception%02d", i);
            HANDLE candidate = CreateFileW(path, GENERIC_READ, 0, nullptr, OPEN_EXISTING, 0, nullptr);
            if (candidate == INVALID_HANDLE_VALUE)
                continue;
            wchar_t id[512]{};
            DWORD size = 0;
            if (DeviceIoControl(candidate, hardware_ioctl, nullptr, 0, id, sizeof(id), &size, nullptr) &&
                size >= sizeof(wchar_t) && id[0])
            {
                handle = candidate;
                return true;
            }
            CloseHandle(candidate);
        }
        return false;
    }
    template <class T> bool send(T &stroke)
    {
        DWORD size = 0;
        return DeviceIoControl(handle, write_ioctl, &stroke, sizeof(stroke), nullptr, 0, &size, nullptr) != FALSE;
    }
};
std::mutex input_mutex;
} // namespace
bool relative_move(int dx, int dy)
{
    std::lock_guard lock(input_mutex);
    Device mouse;
    if (!mouse.open(false))
        return false;
    MouseStroke stroke{};
    stroke.x = dx;
    stroke.y = dy;
    return mouse.send(stroke);
}
bool driver_key(int vk)
{
    if (vk != 32 && vk != 49 && vk != 50 && vk != 51 && vk != 52 && vk != 87)
        return false;
    std::lock_guard lock(input_mutex);
    Device keyboard;
    if (!keyboard.open(true))
        return false;
    KeyStroke stroke{};
    stroke.code = static_cast<uint16_t>(MapVirtualKeyW(vk, MAPVK_VK_TO_VSC));
    if (!stroke.code)
        return false;
    bool down = keyboard.send(stroke);
    sleep(100);
    stroke.state = 1;
    // Always attempt key-up on the same physical device, even after a failed write.
    bool up = keyboard.send(stroke);
    return down && up;
}
} // namespace roco
