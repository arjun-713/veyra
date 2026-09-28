#include "veyra/runtime/engine.hpp"

#include <cstdio>

#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif

int main(int argc, char** argv) {
#if defined(_WIN32)
  _setmode(_fileno(stdin), _O_BINARY);
  _setmode(_fileno(stdout), _O_BINARY);
#endif
  return veyra::runtime::engine_main(argc, argv);
}
