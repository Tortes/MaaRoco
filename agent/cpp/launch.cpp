#include "actions.h"
#include <stdexcept>

namespace roco
{
namespace
{
std::wstring quote(const std::wstring &s)
{
    std::wstring result = L"\"";
    size_t slashes = 0;
    for (auto ch : s)
    {
        if (ch == L'\\')
        {
            ++slashes;
            continue;
        }
        if (ch == L'"')
            result.append(slashes * 2 + 1, L'\\');
        else
            result.append(slashes, L'\\');
        slashes = 0;
        result += ch;
    }
    result.append(slashes * 2, L'\\');
    return result + L'"';
}
struct Child
{
    HANDLE process = nullptr, input = nullptr, job = nullptr;
    Child(HWND hwnd, const std::string &entry, int mouse, int keyboard)
    {
        auto exe = executable_path().parent_path() / L"MaaRocoRunner.exe";
        std::wstring command = quote(exe.wstring()) + L" --hwnd " + std::to_wstring(reinterpret_cast<uintptr_t>(hwnd)) +
                               L" --entry " + quote(wide(entry)) + L" --mouse-method " + std::to_wstring(mouse) +
                               L" --keyboard-method " + std::to_wstring(keyboard);
        SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
        HANDLE read = nullptr;
        if (!CreatePipe(&read, &input, &sa, 0))
            throw std::runtime_error("Cannot create runner stop pipe");
        SetHandleInformation(input, HANDLE_FLAG_INHERIT, 0);
        std::filesystem::create_directories("debug");
        HANDLE output =
            CreateFileW(L"debug/launch_game_runner_console.log", FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        &sa, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        STARTUPINFOW si{};
        si.cb = sizeof(si);
        si.dwFlags = STARTF_USESTDHANDLES;
        si.hStdInput = read;
        si.hStdOutput = output;
        si.hStdError = output;
        PROCESS_INFORMATION pi{};
        job = CreateJobObjectW(nullptr, nullptr);
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        bool ready = job && SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits)) &&
                     output != INVALID_HANDLE_VALUE;
        BOOL ok = ready && CreateProcessW(exe.c_str(), command.data(), nullptr, nullptr, TRUE,
                                          CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr, nullptr, &si, &pi);
        CloseHandle(read);
        if (output != INVALID_HANDLE_VALUE)
            CloseHandle(output);
        if (!ok)
        {
            if (job)
                CloseHandle(job);
            CloseHandle(input);
            job = nullptr;
            input = nullptr;
            throw std::runtime_error("Cannot start MaaRocoRunner");
        }
        process = pi.hProcess;
        if (!AssignProcessToJobObject(job, process))
        {
            TerminateProcess(process, 9);
            CloseHandle(pi.hThread);
            CloseHandle(process);
            CloseHandle(input);
            CloseHandle(job);
            throw std::runtime_error("Cannot supervise MaaRocoRunner");
        }
        ResumeThread(pi.hThread);
        CloseHandle(pi.hThread);
    }
    Child(const Child &) = delete;
    bool running() const
    {
        return WaitForSingleObject(process, 0) == WAIT_TIMEOUT;
    }
    DWORD code() const
    {
        DWORD code = 1;
        GetExitCodeProcess(process, &code);
        return code;
    }
    void stop()
    {
        if (!process || !running())
            return;
        if (input)
        {
            DWORD size = 0;
            WriteFile(input, "stop\n", 5, &size, nullptr);
            CloseHandle(input);
            input = nullptr;
        }
        if (WaitForSingleObject(process, 10000) == WAIT_TIMEOUT)
        {
            TerminateJobObject(job, 9);
            WaitForSingleObject(process, 3000);
        }
    }
    ~Child()
    {
        stop();
        if (input)
            CloseHandle(input);
        if (process)
            CloseHandle(process);
        if (job)
            CloseHandle(job);
    }
};
} // namespace
bool launch(MaaContext *ctx, const json::value &p)
{
    auto tasker = MaaContextGetTasker(ctx);
    const auto title = p.get("title_contains", std::string("洛克王国：世界")),
               cls = p.get("class_name", std::string("UnrealWindow")),
               process = p.get("process_name", std::string("NRC-Win64-Shipping.exe"));
    const auto wt = p.get("wegame_title_contains", std::string("WeGame")),
               wc = p.get("wegame_class_name", std::string()),
               wp = p.get("wegame_process_name", std::string("wegame.exe"));
    const auto we = p.get("wegame_click_entry", std::string("LaunchGameClickWeGameStart")),
               entry = p.get("downstream_entry", std::string("LaunchGameEnterWorldStart"));
    int timeout = integer(p, "timeout_ms", 180000, 1, 900000), poll = integer(p, "poll_interval_ms", 500, 1, 10000);
    int retry = integer(p, "wegame_retry_interval_ms", 3000, 1, 60000),
        success_retry = integer(p, "wegame_success_retry_interval_ms", 15000, 1, 120000);
    int attempt_timeout = integer(p, "wegame_click_attempt_timeout_ms", 10000, 1, 120000),
        diagnostic = integer(p, "diagnostic_interval_ms", 10000, 1, 60000);
    int mouse = integer(p, "mouse_method", 512, 1, 1 << 20), keyboard = integer(p, "keyboard_method", 512, 1, 1 << 20);
    int wm = integer(p, "wegame_mouse_method", 1, 1, 1 << 20), wk = integer(p, "wegame_keyboard_method", 1, 1, 1 << 20);
    auto deadline = Clock::now() + std::chrono::milliseconds(timeout), next_click = Clock::now(),
         next_log = Clock::now();
    HWND hwnd = nullptr;
    int attempts = 0;
    log("LaunchGame", "waiting for game window");
    while (Clock::now() < deadline)
    {
        if (MaaTaskerStopping(tasker))
            return true;
        auto all = windows();
        auto game = select_window(all, title, cls, process);
        if (game)
        {
            hwnd = game->hwnd;
            break;
        }
        if (Clock::now() >= next_log)
        {
            log("LaunchGame", "waiting; visible windows=" + std::to_string(all.size()));
            next_log = Clock::now() + std::chrono::milliseconds(diagnostic);
        }
        if (Clock::now() >= next_click)
            if (auto wegame = select_window(all, wt, wc, wp))
            {
                log("LaunchGame", "starting template click attempt=" + std::to_string(++attempts) + " entry=" + we);
                Child child(wegame->hwnd, we, wm, wk);
                auto attempt_end = std::min(deadline, Clock::now() + std::chrono::milliseconds(attempt_timeout));
                while (child.running() && Clock::now() < attempt_end)
                {
                    if (MaaTaskerStopping(tasker))
                    {
                        child.stop();
                        return true;
                    }
                    if (auto current = select_window(windows(), title, cls, process))
                    {
                        hwnd = current->hwnd;
                        child.stop();
                        break;
                    }
                    if (!IsWindow(wegame->hwnd))
                    {
                        child.stop();
                        break;
                    }
                    sleep(100);
                }
                if (hwnd)
                    break;
                bool timed_out = child.running();
                if (timed_out)
                    child.stop();
                next_click =
                    Clock::now() + std::chrono::milliseconds(!timed_out && child.code() == 0 ? success_retry : retry);
            }
        // Stop remains responsive even if a user configures a long poll interval.
        for (int elapsed = 0; elapsed < poll; elapsed += 100)
        {
            if (MaaTaskerStopping(tasker))
                return true;
            sleep(std::min(100, poll - elapsed));
        }
    }
    if (!hwnd)
    {
        log("LaunchGame", "game window wait timed out");
        return false;
    }
    log("LaunchGame", "game window found; starting entry=" + entry);
    Child child(hwnd, entry, mouse, keyboard);
    while (child.running())
    {
        if (MaaTaskerStopping(tasker) || !IsWindow(hwnd))
        {
            child.stop();
            return true;
        }
        sleep(100);
    }
    log("LaunchGame", "downstream exit=" + std::to_string(child.code()));
    return child.code() == 0;
}
} // namespace roco
