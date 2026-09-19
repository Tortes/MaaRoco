#include "common.h"
#include <iostream>
#include <map>

int main(int argc, char **argv)
{
    using namespace roco;
    if (argc == 2 && std::string(argv[1]) == "--check")
    {
        std::cout << "MaaRoco native launch runner; MaaFW " << MaaVersion() << '\n';
        return 0;
    }
    try
    {
        std::map<std::string, std::string> args;
        for (int i = 1; i + 1 < argc; i += 2)
            args[argv[i]] = argv[i + 1];
        if (!args.contains("--hwnd"))
            return 2;
        HWND hwnd = reinterpret_cast<HWND>(static_cast<uintptr_t>(std::stoull(args.at("--hwnd"))));
        auto entry = args.contains("--entry") ? args.at("--entry") : "LaunchGameEnterWorldStart";
        int mouse = args.contains("--mouse-method") ? std::stoi(args.at("--mouse-method")) : 512;
        int keyboard = args.contains("--keyboard-method") ? std::stoi(args.at("--keyboard-method")) : 512;
        using SetDpi = BOOL(WINAPI *)(HANDLE);
        auto set_dpi =
            reinterpret_cast<SetDpi>(GetProcAddress(GetModuleHandleW(L"user32.dll"), "SetProcessDpiAwarenessContext"));
        if (set_dpi)
            set_dpi(reinterpret_cast<HANDLE>(-4));
        if (!IsWindow(hwnd))
            return 2;
        auto resource = MaaResourceCreate();
        struct Cleanup
        {
            MaaResource *r;
            MaaController *c = nullptr;
            MaaTasker *t = nullptr;
            ~Cleanup()
            {
                if (t)
                {
                    if (MaaTaskerRunning(t))
                        MaaTaskerWait(t, MaaTaskerPostStop(t));
                    MaaTaskerDestroy(t);
                }
                if (c)
                    MaaControllerDestroy(c);
                MaaResourceDestroy(r);
            }
        } cleanup{resource};
        if (!resource)
            return 3;
        const char *files[] = {"pipeline/LaunchGame.json",
                               "image/wegame_start_button.png",
                               "image/wegame_source_qq.png",
                               "image/wegame_source_wechat.png",
                               "image/wegame_source_menu_wechat.png",
                               "image/game_enter_world_button.png"};
        for (const auto *file : files)
        {
            auto path = std::filesystem::path("resource") / file;
            if (!std::filesystem::is_regular_file(path))
            {
                log("LaunchGameRunner", "missing resource: " + path.string());
                return 3;
            }
            auto id = std::string(file).starts_with("pipeline")
                          ? MaaResourcePostPipeline(resource, path.string().c_str())
                          : MaaResourcePostImage(resource, path.string().c_str());
            if (MaaResourceWait(resource, id) != MaaStatus_Succeeded)
                return 3;
        }
        if (!focus(hwnd))
            return 7;
        cleanup.c = MaaWin32ControllerCreate(hwnd, 1 << 5, mouse, keyboard);
        if (!cleanup.c || MaaControllerWait(cleanup.c, MaaControllerPostConnection(cleanup.c)) != MaaStatus_Succeeded)
            return 4;
        if (!focus(hwnd))
            return 7;
        cleanup.t = MaaTaskerCreate();
        if (!cleanup.t || !MaaTaskerBindResource(cleanup.t, resource) ||
            !MaaTaskerBindController(cleanup.t, cleanup.c) || !MaaTaskerInited(cleanup.t))
            return 5;
        std::string logs = "./debug";
        MaaGlobalSetOption(MaaGlobalOption_LogDir, logs.data(), logs.size());
        auto id = MaaTaskerPostTask(cleanup.t, entry.c_str(), "{}");
        log("LaunchGameRunner", "starting entry=" + entry);
        auto input = GetStdHandle(STD_INPUT_HANDLE);
        while (true)
        {
            auto status = MaaTaskerStatus(cleanup.t, id);
            if (status == MaaStatus_Succeeded)
                return 0;
            if (status == MaaStatus_Failed || status == MaaStatus_Invalid)
                return 6;
            DWORD available = 0;
            bool closed = !PeekNamedPipe(input, nullptr, 0, nullptr, &available, nullptr);
            if (closed || available || !IsWindow(hwnd))
            {
                log("LaunchGameRunner", "parent stopped or window closed");
                return 0;
            }
            sleep(100);
        }
    }
    catch (const std::exception &e)
    {
        log("LaunchGameRunner", e.what());
        return 8;
    }
}
