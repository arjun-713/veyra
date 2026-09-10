#pragma once
#include <cstdint>

namespace veyra::map {

// One labelled point, already transformed into the odom frame by perception.
//
// PROPOSAL, not a settled interface. perception/semantic/semantic_provider.hpp
// is still a bare placeholder: SemanticProvider::infer returns a SemanticFrame
// that is forward-declared and defined nowhere, with no class enum and no field
// list. Whatever this struct contains, perception must then produce, so it
// needs the perception owner's sign-off before anything depends on it.
//
// Deliberately excludes slope, roughness and step. Those are speculative until
// perception confirms it computes them, and a field that is declared but never
// populated is worse than a missing one -- it looks like a working contract
// while carrying zeros into terrain logic downstream.
//
// Class id 0 means unlabelled, following the SemanticKITTI convention the
// pretrained models (SalsaNext, FRNet, Cylinder3D) are trained against. That
// matters later: unlabelled is not drivable, because AGENTS.md is explicit
// that unknown != free.
//
// Field order is chosen for packing, not for the order they are listed in the
// design note: the two doubles first, then the floats, then the byte.
struct Observation {
  double x = 0.0;  // double to match the index arithmetic in core/types.hpp
  double y = 0.0;
  float z = 0.0F;  // Cell stores float extremes, so double buys nothing here
  float confidence = 0.0F;
  std::uint8_t cls = 0;
};

}  // namespace veyra::map
