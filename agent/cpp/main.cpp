#include "actions.h"
#include <MaaAgentServer/MaaAgentServerAPI.h>
#include <iostream>

namespace
{
MaaBool MAA_CALL action(MaaContext *ctx, MaaTaskId task_id, const char *, const char *name, const char *raw, MaaRecoId,
                        const MaaRect *, void *)
{
    try
    {
        auto p = roco::params(raw);
        std::string op(name);
        if (op == "launch_game_wait_and_run")
            return roco::launch(ctx, p);
        if (op == "target_pet_explore" || op == "yueya_xuexiong_explore")
            return roco::explore(ctx, task_id, p, op == "yueya_xuexiong_explore");
        if (op == "yueya_xuexiong_aim_and_throw")
            return roco::snow_throw(ctx, p);
        if (op == "battle_focused_key")
        {
            auto controller = MaaTaskerGetController(MaaContextGetTasker(ctx));
            auto buf = MaaStringBufferCreate();
            bool ok = MaaControllerGetInfo(controller, buf);
            auto info = roco::params(MaaStringBufferGet(buf));
            MaaStringBufferDestroy(buf);
            auto hwnd =
                reinterpret_cast<HWND>(static_cast<uintptr_t>(roco::number(info, "hwnd", 0, 0, 9007199254740991.0)));
            if (!ok || !roco::focus(hwnd, 300))
                return false;
            return roco::driver_key(roco::integer(p, "key", 0, 0, 255));
        }
    }
    catch (const std::exception &e)
    {
        roco::log("Agent", e.what());
    }
    return false;
}
MaaBool MAA_CALL recognition(MaaContext *, MaaTaskId, const char *, const char *, const char *raw,
                             const MaaImageBuffer *image, const MaaRect *, void *, MaaRect *box,
                             MaaStringBuffer *detail)
{
    try
    {
        return roco::blue(roco::params(raw), image, box, detail);
    }
    catch (const std::exception &e)
    {
        roco::log("Agent", e.what());
        return false;
    }
}
void MAA_CALL task_event(void *, const char *message, const char *raw, void *)
{
    try
    {
        std::string name(message);
        if (name == "Tasker.Task.Succeeded" || name == "Tasker.Task.Failed")
        {
            auto p = roco::params(raw);
            auto id = p.find<int64_t>("task_id");
            if (id)
                roco::clear_explore_state(*id);
        }
    }
    catch (...)
    {
    }
}
} // namespace
int main(int argc, char **argv)
{
    if (argc == 2 && std::string(argv[1]) == "--check")
    {
        std::cout << "MaaRoco native Agent: launch, battle, snow bear and target exploration; MaaFW " << MaaVersion()
                  << '\n';
        return 0;
    }
    if (argc != 2)
    {
        std::cerr << "Usage: MaaRocoAgent <socket_id>\n";
        return 2;
    }
    std::string logs = "./debug";
    MaaGlobalSetOption(MaaGlobalOption_LogDir, logs.data(), logs.size());
    for (auto name : {"launch_game_wait_and_run", "battle_focused_key", "target_pet_explore", "yueya_xuexiong_explore",
                      "yueya_xuexiong_aim_and_throw"})
        if (!MaaAgentServerRegisterCustomAction(name, action, nullptr))
            return 3;
    if (!MaaAgentServerRegisterCustomRecognition("yueya_xuexiong_blue", recognition, nullptr))
        return 3;
    MaaAgentServerAddTaskerSink(task_event, nullptr);
    if (!MaaAgentServerStartUp(argv[1]))
        return 4;
    MaaAgentServerJoin();
    MaaAgentServerShutDown();
    return 0;
}
