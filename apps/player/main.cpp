#include <cerrno>
#include <cstdio>
#include <cstring>
#include <vector>

#include <unistd.h>

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

  std::vector<char*> command;
  command.reserve(static_cast<std::size_t>(argc) + 4U);
  command.push_back(const_cast<char*>("python3"));
  command.push_back(const_cast<char*>("-m"));
  command.push_back(const_cast<char*>("viewer.server"));
  for (int index = 1; index < argc; ++index) command.push_back(argv[index]);
  command.push_back(nullptr);
  execvp(command.front(), command.data());
  std::fprintf(stderr, "veyra_player: cannot start Python viewer runtime: %s\n", std::strerror(errno));
  return 127;
}
