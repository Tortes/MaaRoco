#include "common.h"
#include <iostream>
#include <stdexcept>
using namespace roco;
void check(bool pass, const char *message)
{
    if (!pass)
        throw std::runtime_error(message);
}
int main()
{
    try
    {
        check(tolerance({634, 305, 62, 23}) == Point{25, 9}, "small target tolerance");
        check(tolerance({661, 317, 88, 60}) == Point{35, 24}, "large target tolerance");
        check(tolerance({0, 0, 10, 10}) == Point{8, 6}, "minimum tolerance");
        check(aim_move(-523, -287, 240, 100, 320) == Point{-240, -768}, "fast movement");
        check(aim_move(1, -107, 24, 100, 320) == Point{1, -76}, "vertical clamp");
        check(aim_move(81, -8, 24, 100, 320) == Point{24, -26}, "negative floor division");
        int pitch = 900;
        for (int expected : {-240, -240, -240, -180})
        {
            int movement = -clamp(pitch, 240);
            check(movement == expected, "pitch recovery");
            pitch = clamp(pitch + movement, 900);
        }
        check(pitch == 0, "pitch restored");
        auto a = locked_candidate({{180, 320, 82, 39}, {1120, 367, 158, 83}}, {92, 329, 80, 37}, {-240, -13}, 360);
        check(a && a->x == 180, "nearest predicted target");
        check(!locked_candidate({{1120, 367, 158, 83}}, {92, 329, 80, 37}, {-240, -13}, 360), "reject far target");
        auto b = locked_candidate({{471, 159, 38, 32}, {633, 360, 74, 57}}, {631, 368, 73, 62}, {2, 75}, 360);
        check(b && b->x == 633, "2026-08-09 target lock regression");
        check(!locked_candidate({{471, 159, 38, 32}}, {631, 368, 73, 62}, {2, 75}, 360), "reject wrong size");
        check(!reasonable(1280, 720, {0, 650, 50, 50}, 55), "HUD rejection");
        check(!reasonable(1280, 720, {0, 0, 1280, 720}, 55), "oversized target rejection");
        auto p = params("{\"timeout_ms\":\"120\"}");
        check(integer(p, "timeout_ms", 5, 1, 1000) == 120, "string numeric option");
        check(integer(params("invalid"), "n", 50, 1, 100) == 50, "malformed JSON defaults");
#ifdef _WIN32
        std::vector<Window> all{{reinterpret_cast<HWND>(1), "Game", "UnrealWindow", "game.exe", 100},
                                {reinterpret_cast<HWND>(2), "Game", "UnrealWindow", "game.exe", 1000}};
        check(select_window(all, "Game", "UnrealWindow", "wrong.exe")->hwnd == reinterpret_cast<HWND>(2),
              "largest matching window");
        check(select_window(all, "Missing", "Missing", "GAME.EXE")->hwnd == reinterpret_cast<HWND>(2),
              "case-insensitive process fallback");
        check(!select_window(all, "Missing", "Missing", "none.exe"), "no unrelated window selected");
#endif
        std::cout << "Native strategy and window selection tests passed\n";
        return 0;
    }
    catch (const std::exception &e)
    {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
