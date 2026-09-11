#pragma once

namespace veyra::runtime {
// Shared native map/policy engine; batch benchmarks and the supervised runtime
// use one observation contract and implementation.
int engine_main(int argc, char** argv);
}  // namespace veyra::runtime
