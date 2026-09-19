#include <mach-o/dyld.h>
#include <unistd.h>
#include <cstdio>
#include <filesystem>
#include <vector>

int main(int argc, char **argv)
{
    uint32_t size = 0;
    _NSGetExecutablePath(nullptr, &size);
    std::vector<char> path(size);
    if (_NSGetExecutablePath(path.data(), &size) != 0)
        return 1;
    const auto contents = std::filesystem::canonical(path.data()).parent_path().parent_path();
    const auto runtime = contents / "Resources";
    const auto executable = (runtime / "MFAAvalonia").string();
    if (chdir(runtime.c_str()) != 0)
        return 1;
    std::vector<char *> args{const_cast<char *>(executable.c_str())};
    for (int i = 1; i < argc; ++i)
        args.push_back(argv[i]);
    args.push_back(nullptr);
    execv(executable.c_str(), args.data());
    perror("Cannot start MaaRoco frontend");
    return 1;
}
