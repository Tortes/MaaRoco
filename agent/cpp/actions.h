#pragma once
#include "common.h"
namespace roco
{
bool launch(MaaContext *context, const json::value &p);
bool explore(MaaContext *context, MaaTaskId task_id, const json::value &p, bool snow);
bool snow_throw(MaaContext *context, const json::value &p);
bool blue(const json::value &p, const MaaImageBuffer *image, MaaRect *box, MaaStringBuffer *detail);
void clear_explore_state(MaaTaskId task_id);
} // namespace roco
