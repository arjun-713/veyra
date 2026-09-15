#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>

#include "veyra/metrics/metrics.hpp"

namespace {

using namespace std::chrono_literals;
using veyra::metrics::MetricsCollector;

void empty_report_has_no_measurements() {
  const auto start = MetricsCollector::Clock::time_point{};
  MetricsCollector collector{start};
  const auto report = collector.report(start + 1s);

  assert(report.durations.empty());
  assert(report.counters.empty());
  assert(report.frame_count == 0);
  assert(!report.fps.has_value());
}

void duration_statistics_use_nearest_rank_percentiles() {
  const auto start = MetricsCollector::Clock::time_point{};
  MetricsCollector collector{start};
  collector.reserve_duration_samples("map", 4);
  collector.record_duration("map", 4ms);
  collector.record_duration("map", 1ms);
  collector.record_duration("map", 3ms);
  collector.record_duration("map", 2ms);

  const auto report = collector.report(start + 2s);
  const auto& stats = report.durations.at("map");
  assert(stats.count == 4);
  assert(stats.min_ns == 1'000'000);
  assert(stats.max_ns == 4'000'000);
  assert(stats.mean_ns == 2'500'000.0);
  assert(stats.p50_ns == 2'000'000);
  assert(stats.p95_ns == 4'000'000);
  assert(stats.p99_ns == 4'000'000);
}

void counters_and_fps_are_aggregated_from_real_inputs() {
  const auto start = MetricsCollector::Clock::time_point{};
  MetricsCollector collector{start};
  collector.add_counter("active_cells", 10);
  collector.add_counter("active_cells", 7);
  collector.record_frame();
  collector.record_frame();
  collector.set_logical_map_bytes(1234);
  collector.set_allocated_map_bytes(std::nullopt);
  collector.observe_rss_bytes(5678);
  collector.observe_rss_bytes(6000);
  collector.observe_rss_bytes(5900);

  const auto report = collector.report(start + 2s);
  assert(report.counters.at("active_cells") == 17);
  assert(report.frame_count == 2);
  assert(report.fps.has_value());
  assert(*report.fps == 1.0);
  assert(report.logical_map_bytes == 1234);
  assert(!report.allocated_map_bytes.has_value());
  assert(report.current_rss_bytes.has_value());
  assert(*report.current_rss_bytes == 5900);
  assert(report.peak_rss_bytes == 6000);
}

void value_statistics_use_the_same_nearest_rank_definition() {
  const auto start = MetricsCollector::Clock::time_point{};
  MetricsCollector collector{start};
  collector.record_value("topology_churn", 4);
  collector.record_value("topology_churn", 1);
  collector.record_value("topology_churn", 3);
  collector.record_value("topology_churn", 2);

  const auto report = collector.report(start + 1s);
  const auto& stats = report.values.at("topology_churn");
  assert(stats.count == 4);
  assert(stats.mean == 2.5);
  assert(stats.min == 1);
  assert(stats.max == 4);
  assert(stats.p50 == 2);
  assert(stats.p95 == 4);
  assert(stats.p99 == 4);
}

void invalid_inputs_are_rejected() {
  MetricsCollector collector;
  bool threw = false;
  try {
    collector.record_duration("bad", -1ns);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);

  threw = false;
  try {
    collector.record_duration("", 1ns);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);

  threw = false;
  try {
    collector.add_counter("bad", -1);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);

  threw = false;
  try {
    collector.report(MetricsCollector::Clock::time_point{} - 1ns);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);
}

void rss_state_is_explicit() {
  MetricsCollector collector;
  const auto initial = collector.report();
  assert(!initial.current_rss_bytes.has_value());
  assert(!initial.peak_rss_bytes.has_value());

  collector.observe_rss_bytes(std::nullopt);
  assert(!collector.report().current_rss_bytes.has_value());
  collector.observe_rss_bytes(42);
  assert(collector.report().current_rss_bytes == 42);
  assert(collector.report().peak_rss_bytes == 42);
}

void rss_sampler_is_measured_or_unavailable() {
  const auto rss = veyra::metrics::read_process_rss_bytes();
  if (rss.has_value()) {
    assert(*rss > 0);
  }
}

void rolling_samples_discard_old_latency_without_losing_frame_totals() {
  const auto start = MetricsCollector::Clock::time_point{};
  MetricsCollector collector{start, 3};
  collector.reserve_duration_samples("map", 10000);
  for (int value : {1000, 2000, 10, 20, 30}) {
    collector.record_duration("map", std::chrono::nanoseconds{value});
    collector.record_value("cells", value);
    collector.record_frame();
  }
  const auto report = collector.report(start + 1s);
  assert(report.frame_count == 5);
  assert(report.durations.at("map").count == 3);
  assert(report.durations.at("map").p50_ns == 20);
  assert(report.durations.at("map").p99_ns == 30);
  assert(report.values.at("cells").count == 3);
  assert(report.values.at("cells").mean == 20.0);
}

}  // namespace

int main() {
  rolling_samples_discard_old_latency_without_losing_frame_totals();
  empty_report_has_no_measurements();
  duration_statistics_use_nearest_rank_percentiles();
  counters_and_fps_are_aggregated_from_real_inputs();
  invalid_inputs_are_rejected();
  rss_state_is_explicit();
  rss_sampler_is_measured_or_unavailable();
  value_statistics_use_the_same_nearest_rank_definition();
}
