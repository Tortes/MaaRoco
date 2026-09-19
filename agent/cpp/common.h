#pragma once
#include <MaaFramework/MaaAPI.h>
#include <MaaFramework/Utility/MaaBuffer.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <json.hpp>
#include <optional>
#include <string>
#include <thread>
#include <vector>
#include <windows.h>

namespace roco
{
using Clock = std::chrono::steady_clock;
using Box = MaaRect;
struct Point
{
    int x = 0, y = 0;
    bool operator==(const Point &) const = default;
};
inline void sleep(int ms)
{
    if (ms > 0)
        std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}
inline int clamp(int n, int limit)
{
    return std::clamp(n, -limit, limit);
}
// Match Python's floor division and nearest-even rounding for calibrated movement.
inline int floor_div(int a, int b)
{
    int q = a / b;
    return q - ((a % b != 0 && a < 0) ? 1 : 0);
}
inline int rounded(double x)
{
    return static_cast<int>(std::nearbyint(x));
}
inline Point center(const Box &b)
{
    return {b.x + b.width / 2, b.y + b.height / 2};
}
inline json::value box_json(const Box &b)
{
    return json::array{b.x, b.y, b.width, b.height};
}
json::value params(const char *raw);
int integer(const json::value &p, const std::string &key, int fallback, int lo, int hi);
double number(const json::value &p, const std::string &key, double fallback, double lo, double hi);
std::string utf8(const std::wstring &s);
std::wstring wide(const std::string &s);
void log(const std::string &scope, const std::string &text);
bool focus(HWND hwnd, int timeout_ms = 5000);
bool relative_move(int dx, int dy);
bool driver_key(int vk);
std::filesystem::path executable_path();
struct Window
{
    HWND hwnd{};
    std::string title, class_name, process;
    long long area{};
};
std::vector<Window> windows();
std::optional<Window> select_window(const std::vector<Window> &all, const std::string &title, const std::string &cls,
                                    const std::string &process);
Point tolerance(const Box &b);
Point aim_move(int ex, int ey, int step, int gain, int vertical);
Point follow_move(Point move);
bool reasonable(int w, int h, const Box &b, int area);
bool same_target(const Box &a, const Box &b, int shift);
std::optional<Box> locked_candidate(const std::vector<Box> &boxes, const Box &previous, Point move, int shift);
} // namespace roco
