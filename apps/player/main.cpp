#include <cerrno>
#include <cstdio>
#include <cstring>
#include <vector>

#if defined(_WIN32)
#include <process.h>
#define VEYRA_EXECVP _execvp
#else
#include <unistd.h>
#define VEYRA_EXECVP execvp
#endif

int main(int argc, char** argv) {
  bool has_runtime_config = false;
  for (int index = 1; index < argc; ++index) {
    const char* argument = argv[index];
    if (std::strcmp(argument, "--runtime-config") == 0 ||
        std::strncmp(argument, "--runtime-config=", 17) == 0) {
      has_runtime_config = true;
      break;
    }
  }
  if (!has_runtime_config) {
    std::fputs("usage: veyra_player --runtime-config viewer/runtime.json [viewer options]\n", stderr);
    return 2;
  }

#if defined(_WIN32)
  std::vector<const char*> command;
#else
  std::vector<char*> command;
#endif
  command.reserve(static_cast<std::size_t>(argc) + 4U);
#if defined(_WIN32)
  command.push_back("python.exe");
#else
  command.push_back(const_cast<char*>("python3"));
#endif
  command.push_back(const_cast<char*>("-m"));
  command.push_back(const_cast<char*>("viewer.server"));
  for (int index = 1; index < argc; ++index) command.push_back(argv[index]);
  command.push_back(nullptr);
  VEYRA_EXECVP(command.front(), command.data());
  std::fprintf(stderr, "veyra_player: cannot start Python viewer runtime: %s\n", std::strerror(errno));
  return 127;
}
