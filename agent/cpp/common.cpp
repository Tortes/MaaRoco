#include "common.h"
#include <fstream>
#include <iostream>
#include <limits>
#include <mutex>
#include <set>

namespace roco
{
json::value params(const char *raw)
{
    auto v = json::parse(std::string(raw && *raw ? raw : "{}"));
    return v && v->is_object() ? *v : json::value(json::object{});
}
double number(const json::value &p, const std::string &key, double fallback, double lo, double hi)
{
    try
    {
        double n = fallback;
        if (p.contains(key))
        {
            const auto &v = p.at(key);
            n = v.is_string() ? std::stod(v.as_string()) : v.as_double();
        }
        return std::isfinite(n) ? std::clamp(n, lo, hi) : fallback;
    }
    catch (...)
    {
        return fallback;
    }
}
int integer(const json::value &p, const std::string &key, int fallback, int lo, int hi)
{
    return static_cast<int>(number(p, key, fallback, lo, hi));
}
std::string utf8(const std::wstring &s)
{
    if (s.empty())
        return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0, nullptr, nullptr);
    std::string out(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), n, nullptr, nullptr);
    return out;
}
std::wstring wide(const std::string &s)
{
    if (s.empty())
        return {};
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()), nullptr, 0);
    if (!n)
        throw std::runtime_error("Invalid UTF-8");
    std::wstring out(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), n);
    return out;
}
void log(const std::string &scope, const std::string &text)
{
    static std::mutex mutex;
    std::lock_guard lock(mutex);
    std::cout << '[' << scope << "] " << text << std::endl;
    try
    {
        std::filesystem::create_directories("debug");
        std::ofstream f(scope.starts_with("Launch") ? "debug/launch_game.log" : "debug/target_pet.log", std::ios::app);
        SYSTEMTIME t{};
        GetLocalTime(&t);
        f << t.wYear << '-' << t.wMonth << '-' << t.wDay << ' ' << t.wHour << ':' << t.wMinute << ':' << t.wSecond
          << " [" << scope << "] " << text << '\n';
    }
    catch (...)
    {
    }
}
std::filesystem::path executable_path()
{
    std::wstring path(32768, 0);
    DWORD n = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (!n || n >= path.size())
        throw std::runtime_error("Cannot resolve executable path");
    path.resize(n);
    return path;
}
bool focus(HWND hwnd, int timeout_ms)
{
    const auto deadline = Clock::now() + std::chrono::milliseconds(timeout_ms);
    do
    {
        if (!IsWindow(hwnd))
            return false;
        if (GetForegroundWindow() == hwnd)
            return true;
        std::set<DWORD> ids{GetWindowThreadProcessId(hwnd, nullptr),
                            GetWindowThreadProcessId(GetForegroundWindow(), nullptr)};
        std::vector<DWORD> attached;
        for (auto id : ids)
            if (id && id != GetCurrentThreadId() && AttachThreadInput(GetCurrentThreadId(), id, TRUE))
                attached.push_back(id);
        ShowWindow(hwnd, IsIconic(hwnd) ? SW_RESTORE : SW_SHOW);
        SetWindowPos(hwnd, nullptr, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
        BringWindowToTop(hwnd);
        SetForegroundWindow(hwnd);
        SetActiveWindow(hwnd);
        SetFocus(hwnd);
        for (auto id : attached)
            AttachThreadInput(GetCurrentThreadId(), id, FALSE);
        if (GetForegroundWindow() == hwnd)
            return true;
        sleep(100);
    } while (Clock::now() < deadline);
    return false;
}
std::vector<Window> windows()
{
    std::vector<Window> result;
    EnumWindows(
        [](HWND hwnd, LPARAM arg) -> BOOL {
            if (!IsWindowVisible(hwnd))
                return TRUE;
            std::wstring title(GetWindowTextLengthW(hwnd) + 1, 0), cls(256, 0), path(32768, 0);
            title.resize(GetWindowTextW(hwnd, title.data(), static_cast<int>(title.size())));
            cls.resize(GetClassNameW(hwnd, cls.data(), static_cast<int>(cls.size())));
            DWORD pid = 0;
            GetWindowThreadProcessId(hwnd, &pid);
            HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
            DWORD len = static_cast<DWORD>(path.size());
            if (process)
            {
                if (!QueryFullProcessImageNameW(process, 0, path.data(), &len))
                    len = 0;
                CloseHandle(process);
            }
            else
                len = 0;
            path.resize(len);
            RECT r{};
            GetWindowRect(hwnd, &r);
            reinterpret_cast<std::vector<Window> *>(arg)->push_back(
                {hwnd, utf8(title), utf8(cls), utf8(std::filesystem::path(path).filename().wstring()),
                 static_cast<long long>(std::max(0L, r.right - r.left)) * std::max(0L, r.bottom - r.top)});
            return TRUE;
        },
        reinterpret_cast<LPARAM>(&result));
    return result;
}
std::optional<Window> select_window(const std::vector<Window> &all, const std::string &title, const std::string &cls,
                                    const std::string &process)
{
    std::optional<Window> found;
    for (const auto &w : all)
        if ((title.empty() || w.title.find(title) != std::string::npos) && (cls.empty() || w.class_name == cls))
            if (!found || w.area > found->area)
                found = w;
    if (found || process.empty())
        return found;
    auto expected = std::filesystem::path(wide(process)).filename().wstring();
    for (const auto &w : all)
        if (_wcsicmp(wide(w.process).c_str(), expected.c_str()) == 0)
            if (!found || w.area > found->area)
                found = w;
    return found;
}
Point tolerance(const Box &b)
{
    return {std::max(8, rounded(b.width * .4)), std::max(6, rounded(b.height * .4))};
}
Point aim_move(int ex, int ey, int step, int gain, int vertical)
{
    int h = std::max(1, step * gain / 100), v = std::max(1, h * vertical / 100);
    return {clamp(ex, h), clamp(floor_div(ey * vertical, 100), v)};
}
Point follow_move(Point p)
{
    int x = rounded(p.x * .45), y = rounded(p.y * .2);
    if (p.x && !x)
        x = p.x > 0 ? 1 : -1;
    if (p.y && !y)
        y = p.y > 0 ? 1 : -1;
    return {x, y};
}
bool reasonable(int w, int h, const Box &b, int area)
{
    return b.width > 0 && b.height > 0 && !(b.x + b.width <= w * .25 && b.y >= h * .85) &&
           static_cast<long long>(b.width) * b.height * 100 <= static_cast<long long>(w) * h * area;
}
bool same_target(const Box &a, const Box &b, int shift)
{
    if (std::min({a.width, a.height, b.width, b.height}) <= 0)
        return false;
    auto p = center(a), q = center(b);
    double wr = double(b.width) / a.width, hr = double(b.height) / a.height;
    return std::abs(p.x - q.x) <= shift && std::abs(p.y - q.y) <= shift && wr >= .4 && wr <= 2.5 && hr >= .4 &&
           hr <= 2.5;
}
std::optional<Box> locked_candidate(const std::vector<Box> &boxes, const Box &previous, Point move, int shift)
{
    auto p = center(previous);
    p.x -= rounded(move.x * .75);
    p.y -= rounded(move.y * .3);
    int tx = std::min(shift, std::max({64, previous.width * 2, rounded(std::abs(move.x) * .45)}));
    int ty = std::min(shift, std::max({48, previous.height * 2, rounded(std::abs(move.y) * .25)}));
    std::optional<Box> best;
    double best_cost = std::numeric_limits<double>::infinity();
    for (const auto &b : boxes)
    {
        if (!same_target(previous, b, shift))
            continue;
        double wr = double(b.width) / previous.width, hr = double(b.height) / previous.height;
        auto q = center(b);
        if (wr < .65 || wr > 1.55 || hr < .65 || hr > 1.55 || std::abs(q.x - p.x) > tx || std::abs(q.y - p.y) > ty)
            continue;
        double cost =
            std::abs(wr - 1) + std::abs(hr - 1) + double(std::abs(q.x - p.x)) / tx + double(std::abs(q.y - p.y)) / ty;
        if (cost < best_cost)
        {
            best_cost = cost;
            best = b;
        }
    }
    return best;
}
} // namespace roco
