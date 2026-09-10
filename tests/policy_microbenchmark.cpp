#include "veyra/policy/policy.hpp"

#include <chrono>
#include <cstdint>
#include <iostream>

int main() {
  constexpr std::uint64_t sample_count = 1'000'000;
  auto config = veyra::policy::PolicyConfig::defaults().with_mode(veyra::policy::LodMode::UtilityLod);
  config.utility.ema_alpha = 0.35;
  config.utility.split_consecutive_frames = 2;
  veyra::policy::LodPolicy policy{config};

  std::uint64_t checksum = 0;
  const auto started = std::chrono::steady_clock::now();
  for (std::uint64_t index = 0; index < sample_count; ++index) {
    const auto decision = policy.decide({.range_m = 65.0 + static_cast<double>(index % 20),
                                         .active_level = 3,
                                         .state_cell = {3, static_cast<std::int32_t>(index % 251), 0},
                                         .geometry_complexity = static_cast<double>(index % 5) / 4.0,
                                         .semantic_importance = static_cast<double>(index % 7) / 6.0,
                                         .motion = static_cast<double>(index % 3) / 2.0,
                                         .traversability_risk = static_cast<double>(index % 11) / 10.0,
                                         .semantic_uncertainty = static_cast<double>(index % 4) / 3.0,
                                         .observation_quality = 0.9,
                                         .point_density = 0.9,
                                         .range_rate_mps = -2.0});
    checksum += static_cast<std::uint64_t>(decision.requested_level);
  }
  const auto elapsed = std::chrono::steady_clock::now() - started;
  const auto elapsed_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(elapsed).count();
  const double decisions_per_second = static_cast<double>(sample_count) * 1'000'000'000.0 /
                                      static_cast<double>(elapsed_ns);
  std::cout << "policy_decisions=" << sample_count << " elapsed_ns=" << elapsed_ns
            << " decisions_per_second=" << decisions_per_second << " checksum=" << checksum << '\n';
}
