#include "actions.h"

namespace roco
{
bool launch(MaaContext *, const json::value &)
{
    log("LaunchGame", "WeGame launch is Windows-only. Open the game manually, then select its macOS window.");
    return false;
}
} // namespace roco
