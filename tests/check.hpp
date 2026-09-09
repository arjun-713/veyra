// Assertion that survives -DNDEBUG.
//
// CMAKE_BUILD_TYPE=Release defines NDEBUG, which makes assert() a no-op, so a
// test built with assert() compiles down to `return 0` and passes without
// evaluating anything. CHECK always evaluates its condition and exits non-zero
// on failure, so CTest sees a real result in every build type.
#pragma once

#include <cstdio>
#include <cstdlib>

#define CHECK(cond)                                                                 \
  do {                                                                              \
    if (!(cond)) {                                                                  \
      std::fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
      std::exit(1);                                                                 \
    }                                                                               \
  } while (0)
