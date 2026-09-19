#include "actions.h"
#include <array>
#include <map>
#include <memory>
#include <mutex>

namespace roco
{
namespace
{
struct Settings
{
    std::string target = "TargetPetAimDetect";
    int gain = 100, tolerance = 200, attempts = 4, move = 360, settle = 10, frames = 1, area = 55, hold = 20,
        cooldown = 0;
    int base_lift = 0, distance_lift = 0, reference = 100, shift = 360;
    double score = .01;
};
Settings settings(const json::value &p, bool snow = false)
{
    Settings s;
    if (snow)
    {
        s.target = "YueyaXuexiongDetect";
        s.tolerance = 24;
        s.move = 480;
        s.settle = 140;
        s.frames = 2;
        s.hold = 80;
        s.base_lift = 30;
        s.distance_lift = 12;
        s.score = .60;
        s.shift = 140;
    }
    s.target = p.get("target_recognition", s.target);
    if (s.target.empty())
        s.target = snow ? "YueyaXuexiongDetect" : "TargetPetAimDetect";
    s.gain = integer(p, "aim_gain_percent", s.gain, 10, 300);
    s.tolerance = integer(p, "center_tolerance", s.tolerance, 1, 200);
    s.attempts = integer(p, "max_aim_attempts", s.attempts, 1, 20);
    s.move = integer(p, "max_relative_move", s.move, 1, 2000);
    s.settle = integer(p, "settle_delay_ms", s.settle, 0, 2000);
    s.frames = integer(p, "verification_frames", s.frames, 1, 4);
    s.area = integer(p, "max_target_area_percent", s.area, 1, 90);
    s.hold = integer(p, "min_hold_ms", s.hold, 1, 1000);
    s.cooldown = integer(p, "throw_cooldown_ms", s.cooldown, 0, 10000);
    s.base_lift = integer(p, "trajectory_base_lift_px", s.base_lift, 0, 200);
    s.distance_lift = integer(p, "trajectory_distance_lift_px", s.distance_lift, 0, 300);
    s.reference = integer(p, "trajectory_reference_height", s.reference, 20, 1000);
    s.shift = integer(p, "target_lock_max_shift", s.shift, 20, 2000);
    s.score = number(p, "detection_score_min", s.score, .01, .99);
    return s;
}
struct Frame
{
    MaaImageBuffer *image = MaaImageBufferCreate();
    ~Frame()
    {
        MaaImageBufferDestroy(image);
    }
    bool capture(MaaController *c, bool fresh = true)
    {
        return (!fresh || MaaControllerWait(c, MaaControllerPostScreencap(c)) == MaaStatus_Succeeded) &&
               MaaControllerCachedImage(c, image) && width() > 0 && height() > 0;
    }
    int width() const
    {
        return MaaImageBufferWidth(image);
    }
    int height() const
    {
        return MaaImageBufferHeight(image);
    }
};
std::optional<Box> read_box(const json::value &value)
{
    auto b = value.find<std::vector<int>>("box");
    if (!b || b->size() != 4 || (*b)[2] <= 0 || (*b)[3] <= 0)
        return {};
    return Box{(*b)[0], (*b)[1], (*b)[2], (*b)[3]};
}
std::vector<Box> detect(MaaContext *ctx, const Settings &s, Frame &frame, double threshold, bool prefer_best = false)
{
    auto id = MaaContextRunRecognition(ctx, s.target.c_str(), "{}", frame.image);
    if (id == MaaInvalidId)
        return {};
    auto buffer = MaaStringBufferCreate();
    MaaBool hit = false;
    Box box{};
    bool ok = MaaTaskerGetRecognitionDetail(MaaContextGetTasker(ctx), id, nullptr, nullptr, &hit, &box, buffer, nullptr,
                                            nullptr);
    auto detail = params(MaaStringBufferGet(buffer));
    MaaStringBufferDestroy(buffer);
    if (!ok || !hit)
        return {};
    if (prefer_best && box.width > 0 && box.height > 0)
        return {box};
    std::vector<Box> boxes;
    auto results = detail.find<json::array>("all");
    if (results)
        for (const auto &result : *results)
            if (result.is_object() && number(result, "score", 0, 0, 1) >= threshold)
                if (auto b = read_box(result))
                    boxes.push_back(*b);
    // Match the SDK's best-result fallback (also handles Custom recognition).
    if (boxes.empty() && box.width > 0 && box.height > 0)
        boxes.push_back(box);
    return boxes;
}
void control(MaaController *c, MaaCtrlId id)
{
    if (MaaControllerWait(c, id) != MaaStatus_Succeeded)
        throw std::runtime_error("Controller input failed");
}
void move(Point p)
{
    if (!relative_move(p.x, p.y))
        throw std::runtime_error("Interception relative move failed");
}
bool stopping(MaaContext *c)
{
    return MaaTaskerStopping(MaaContextGetTasker(c));
}
struct State
{
    bool held = false, seen = false, recovering = false;
    int centered = 0, round = 0, lost = 0, direction = -1, pitch = 0, scans = 0;
    std::optional<Box> locked;
    Point last;
    Clock::time_point held_at{};
};
std::mutex states_mutex;
std::map<MaaTaskId, State> states;
Point aim_point(const Box &b, const Settings &s)
{
    auto p = center(b);
    p.y = std::max(0, p.y - std::min(200, s.base_lift + s.distance_lift * s.reference / std::max(1, b.height)));
    return p;
}
bool at_pointer(Point p, const Box &b, const Settings &s)
{
    auto aim = aim_point(b, s);
    return std::abs(aim.x - p.x) <= s.tolerance && std::abs(aim.y - p.y) <= s.tolerance;
}
std::optional<Box> nearest(const std::vector<Box> &boxes, Point p)
{
    if (boxes.empty())
        return {};
    return *std::min_element(boxes.begin(), boxes.end(), [p](const Box &a, const Box &b) {
        auto ac = center(a), bc = center(b);
        auto distance = [p](Point q) { return std::hypot(double(q.x - p.x), double(q.y - p.y)); };
        return distance(ac) < distance(bc);
    });
}
} // namespace
void clear_explore_state(MaaTaskId id)
{
    std::lock_guard lock(states_mutex);
    states.erase(id);
}
bool explore(MaaContext *ctx, MaaTaskId id, const json::value &p, bool snow)
{
    // Each task owns its tracking state; locks never span RPCs or sleeps.
    State st;
    {
        std::lock_guard lock(states_mutex);
        st = states[id];
    }
    auto c = MaaTaskerGetController(MaaContextGetTasker(ctx));
    if (!c)
        return false;
    auto save = [&] {
        std::lock_guard lock(states_mutex);
        states[id] = st;
    };
    auto release = [&] {
        if (st.held)
        {
            control(c, MaaControllerPostTouchUp(c, 0));
            st.held = false;
        }
    };
    try
    {
        if (p.get("reset", false))
        {
            release();
            st = State{};
            save();
            return true;
        }
        if (stopping(ctx))
        {
            release();
            clear_explore_state(id);
            return true;
        }
        auto s = settings(p);
        if (snow && !p.contains("target_recognition"))
            s.target = "YueyaXuexiongExploreAimDetect";
        int scan = integer(p, "scan_step_units", 350, 10, 900),
            fast = integer(p, "relative_aim_fast_step_units", 720, 20, 1800);
        int slow = integer(p, "relative_aim_slow_step_units", 260, 10, 1000),
            fine = integer(p, "relative_aim_fine_step_units", 80, 2, 500);
        int vertical = integer(p, "relative_aim_vertical_gain_percent", 180, 100, 600),
            fine_radius = integer(p, "relative_aim_fine_radius_px", 120, 50, 500);
        int enter = integer(p, "aim_enter_delay_ms", 20, 0, 1000), grace = integer(p, "lost_grace_frames", 3, 0, 10);
        int recovery_frames = integer(p, "pitch_recovery_scan_frames", 4, 1, 100),
            recovery_step = integer(p, "pitch_recovery_step_units", 240, 20, 900);
        int pitch_limit = integer(p, "pitch_offset_limit_units", 900, 100, 2000),
            pitch_min = integer(p, "pitch_recovery_min_offset_units", 80, 1, 500);
        double lock_score = std::min(s.score, number(p, "locked_detection_score_min", .3, .01, .99));
        Frame frame;
        if (!frame.capture(c))
            throw std::runtime_error("Capture failed");
        int w = frame.width(), h = frame.height();
        Point screen{w / 2, h / 2};
        auto finish = [&] {
            save();
            sleep(s.settle);
            return true;
        };
        auto follow = [&] {
            st.centered = 0;
            ++st.lost;
            auto f = follow_move(st.last);
            if (f != Point{})
            {
                move(f);
                st.last = f;
                st.pitch = clamp(st.pitch + f.y, pitch_limit);
            }
            return finish();
        };
        if (!st.held)
        {
            control(c, MaaControllerPostTouchDown(c, 0, screen.x, screen.y, 0));
            int round = st.round + 1, pitch = st.pitch;
            st = State{};
            st.pitch = pitch;
            st.round = round;
            st.held = true;
            st.held_at = Clock::now();
            save();
            sleep(enter);
            if (!frame.capture(c))
                throw std::runtime_error("Capture failed after aim start");
        }
        auto boxes = detect(ctx, s, frame, st.locked ? lock_score : s.score);
        std::erase_if(boxes, [&](const Box &b) { return !reasonable(w, h, b, s.area); });
        if (boxes.empty())
        {
            st.centered = 0;
            if (st.seen && st.lost < grace)
                return follow();
            st.seen = false;
            st.lost = 0;
            st.locked.reset();
            if (st.recovering || (st.scans >= recovery_frames && std::abs(st.pitch) >= pitch_min))
            {
                int y = -clamp(st.pitch, recovery_step);
                st.last = {0, y};
                move(st.last);
                st.pitch = clamp(st.pitch + y, pitch_limit);
                st.recovering = st.pitch != 0;
                if (!st.recovering)
                    st.scans = 0;
            }
            else
            {
                ++st.scans;
                st.last = {st.direction * scan, 0};
                move(st.last);
            }
            return finish();
        }
        st.scans = 0;
        st.recovering = false;
        std::optional<Box> box;
        if (!st.locked)
        {
            box = nearest(boxes, screen);
            st.locked = box;
            st.last = {};
        }
        else
        {
            box = locked_candidate(boxes, *st.locked, st.last, s.shift);
            if (!box && st.lost < grace)
                return follow();
            if (!box)
            {
                st.centered = 0;
                st.seen = false;
                st.lost = 0;
                st.locked.reset();
                st.last = {};
                return finish();
            }
            st.locked = box;
        }
        st.seen = true;
        st.lost = 0;
        auto target = center(*box);
        int ex = target.x - screen.x, ey = target.y - screen.y;
        auto tol = tolerance(*box);
        if (std::abs(ex) <= tol.x && std::abs(ey) <= tol.y)
        {
            ++st.centered;
            if (st.centered < s.frames)
                return finish();
            sleep(s.hold -
                  static_cast<int>(
                      std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - st.held_at).count()));
            release();
            log("TargetPet", "release: target box center confirmed round=" + std::to_string(st.round) +
                                 " target=" + box_json(*box).dumps());
            int round = st.round;
            st = State{};
            st.round = round;
            sleep(s.cooldown);
            return finish();
        }
        st.centered = 0;
        int step = (std::abs(ex) > tol.x * 2 || std::abs(ey) > tol.y * 2)
                       ? fast
                       : (std::max(std::abs(ex), std::abs(ey)) <= fine_radius ? fine : slow);
        st.last = aim_move(ex, ey, step, s.gain, vertical);
        move(st.last);
        st.pitch = clamp(st.pitch + st.last.y, pitch_limit);
        if (st.last.x)
            st.direction = st.last.x > 0 ? 1 : -1;
        return finish();
    }
    catch (const std::exception &e)
    {
        log("TargetPet", e.what());
        try
        {
            release();
        }
        catch (...)
        {
        }
        clear_explore_state(id);
        return false;
    }
}
bool snow_throw(MaaContext *ctx, const json::value &p)
{
    auto c = MaaTaskerGetController(MaaContextGetTasker(ctx));
    if (!c)
        return false;
    auto s = settings(p, true);
    Frame frame;
    bool held = false, confirmed = false;
    Clock::time_point held_at{};
    auto release = [&] {
        if (held)
        {
            control(c, MaaControllerPostTouchUp(c, 0));
            held = false;
        }
    };
    try
    {
        if (!frame.capture(c, false))
            return false;
        auto boxes = detect(ctx, s, frame, s.score, true);
        if (boxes.empty())
            return false;
        Box box = boxes.front();
        if (!reasonable(frame.width(), frame.height(), box, s.area))
            return false;
        if (!frame.capture(c))
            return false;
        auto next = nearest(detect(ctx, s, frame, s.score), center(box));
        if (!next || !same_target(box, *next, s.shift) || !reasonable(frame.width(), frame.height(), *next, s.area))
            return false;
        box = *next;
        Point pointer{frame.width() / 2, frame.height() / 2};
        control(c, MaaControllerPostTouchDown(c, 0, pointer.x, pointer.y, 0));
        held = true;
        held_at = Clock::now();
        auto verify_box = [&] {
            if (!frame.capture(c))
                return false;
            auto update = nearest(detect(ctx, s, frame, s.score), center(box));
            if (!update || !same_target(box, *update, s.shift) ||
                !reasonable(frame.width(), frame.height(), *update, s.area))
                return false;
            box = *update;
            return true;
        };
        auto confirm = [&] {
            sleep(s.hold - static_cast<int>(
                               std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - held_at).count()));
            release();
            confirmed = true;
            log("TargetPet", "release: target confirmed on crosshair");
        };
        for (int attempt = 0; attempt < s.attempts && !stopping(ctx); ++attempt)
        {
            if (!frame.capture(c))
                break;
            if (at_pointer(pointer, box, s))
            {
                int verified = 1;
                while (verified < s.frames && !stopping(ctx))
                {
                    sleep(s.settle);
                    if (!verify_box())
                        throw std::runtime_error("Target lost while verifying");
                    if (!at_pointer(pointer, box, s))
                        break;
                    ++verified;
                }
                if (verified == s.frames && !stopping(ctx))
                {
                    confirm();
                    break;
                }
                continue;
            }
            auto aim = aim_point(box, s);
            pointer.x = std::clamp(pointer.x + clamp(floor_div((aim.x - pointer.x) * s.gain, 100), s.move), 0,
                                   frame.width() - 1);
            pointer.y = std::clamp(pointer.y + clamp(floor_div((aim.y - pointer.y) * s.gain, 100), s.move), 0,
                                   frame.height() - 1);
            control(c, MaaControllerPostTouchMove(c, 0, pointer.x, pointer.y, 0));
            if (s.frames == 1 && at_pointer(pointer, box, s) && !stopping(ctx))
            {
                confirm();
                break;
            }
            sleep(s.settle);
            if (!verify_box())
                break;
        }
        release();
        if (confirmed)
            sleep(s.cooldown);
        return confirmed;
    }
    catch (const std::exception &e)
    {
        log("TargetPet", e.what());
        try
        {
            release();
        }
        catch (...)
        {
        }
        return false;
    }
}

// OpenCV-compatible 8-bit HSV conversion and 8-connected components. The UI/NN
// framework retains its own OpenCV; this fallback needs no second OpenCV build.
bool blue(const json::value &p, const MaaImageBuffer *image, MaaRect *box, MaaStringBuffer *detail)
{
    int w = MaaImageBufferWidth(image), h = MaaImageBufferHeight(image);
    if (w <= 0 || h <= 0 || MaaImageBufferType(image) != 16)
        return false; // CV_8UC3
    auto lower = p.get("hsv_lower", std::vector<int>{100, 70, 140}),
         upper = p.get("hsv_upper", std::vector<int>{140, 255, 255});
    if (lower.size() != 3 || upper.size() != 3)
        return false;
    auto data = static_cast<const uint8_t *>(MaaImageBufferGetRawData(image));
    if (!data)
        return false;
    double ratio = number(p, "min_area_ratio", .002, .0001, .25), density_min = number(p, "min_density", .38, .05, 1),
           top_ratio = number(p, "min_top_ratio", .06, 0, .5);
    std::vector<uint8_t> mask(static_cast<size_t>(w) * h);
    for (size_t i = 0; i < mask.size(); ++i)
    {
        int b = data[i * 3], g = data[i * 3 + 1], r = data[i * 3 + 2], v = std::max({b, g, r}),
            minimum = std::min({b, g, r}), diff = v - minimum;
        int s = v ? (diff * rounded(double(255 << 12) / v) + (1 << 11)) >> 12 : 0;
        int hue = v == r ? g - b : (v == g ? b - r + 2 * diff : r - g + 4 * diff);
        hue = diff ? (hue * rounded(double(180 << 12) / (6 * diff)) + (1 << 11)) >> 12 : 0;
        if (hue < 0)
            hue += 180;
        mask[i] =
            hue >= lower[0] && hue <= upper[0] && s >= lower[1] && s <= upper[1] && v >= lower[2] && v <= upper[2];
    }
    int best_area = 0;
    Box best{};
    double best_x = 0, best_y = 0, best_density = 0;
    std::vector<int> queue;
    for (int i = 0; i < w * h; ++i)
    {
        if (!mask[i])
            continue;
        queue.clear();
        queue.push_back(i);
        mask[i] = 0;
        int minx = w, miny = h, maxx = 0, maxy = 0;
        long long sx = 0, sy = 0;
        for (size_t k = 0; k < queue.size(); ++k)
        {
            int x = queue[k] % w, y = queue[k] / w;
            minx = std::min(minx, x);
            miny = std::min(miny, y);
            maxx = std::max(maxx, x);
            maxy = std::max(maxy, y);
            sx += x;
            sy += y;
            for (int dy = -1; dy <= 1; ++dy)
                for (int dx = -1; dx <= 1; ++dx)
                {
                    int xx = x + dx, yy = y + dy;
                    if (xx >= 0 && xx < w && yy >= 0 && yy < h && mask[yy * w + xx])
                    {
                        mask[yy * w + xx] = 0;
                        queue.push_back(yy * w + xx);
                    }
                }
        }
        int area = static_cast<int>(queue.size()), bw = maxx - minx + 1, bh = maxy - miny + 1;
        double density = double(area) / (bw * bh);
        if (area < rounded(w * h * ratio) || miny < rounded(h * top_ratio) || density < density_min)
            continue;
        if (area > best_area || (area == best_area && std::pair(minx, miny) > std::pair(best.x, best.y)))
        {
            best_area = area;
            best = {minx, miny, bw, bh};
            best_x = double(sx) / area;
            best_y = double(sy) / area;
            best_density = density;
        }
    }
    if (!best_area)
        return false;
    *box = {rounded(best_x - best.width / 2.0), rounded(best_y - best.height / 2.0), best.width, best.height};
    json::value result = json::object{{"area", best_area},
                                      {"area_ratio", double(best_area) / (w * h)},
                                      {"density", best_density},
                                      {"min_density", density_min},
                                      {"min_top_ratio", top_ratio},
                                      {"center", json::array{best_x, best_y}},
                                      {"source_box", box_json(best)},
                                      {"hsv_lower", lower},
                                      {"hsv_upper", upper}};
    return MaaStringBufferSet(detail, result.dumps().c_str());
}
} // namespace roco
