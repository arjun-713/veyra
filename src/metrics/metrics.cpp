#include "veyra/metrics/metrics.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <type_traits>

#if defined(__linux__)
#include <unistd.h>
#endif

namespace veyra::metrics {
namespace {

void validate_name(std::string_view name) {
  if (name.empty()) {
    throw std::invalid_argument("metric name must not be empty");
  }
}

std::int64_t nearest_rank(const std::vector<std::int64_t> &sorted,
                          double percentile) {
  const auto rank = static_cast<std::size_t>(
      std::ceil(percentile * static_cast<double>(sorted.size())));
  const auto index = std::min(sorted.size() - 1, rank == 0 ? 0 : rank - 1);
  return sorted[index];
}

template <typename Statistics>
Statistics summarize(const std::vector<std::int64_t> &samples) {
  Statistics result;
  if (samples.empty()) {
    return result;
  }

  auto sorted = samples;
  std::sort(sorted.begin(), sorted.end());
  long double sum = 0.0L;
  for (const auto sample : samples) {
    sum += static_cast<long double>(sample);
  }

  result.count = sorted.size();
  if constexpr (std::is_same_v<Statistics, DurationStatistics>) {
    result.mean_ns = static_cast<double>(sum / sorted.size());
    result.min_ns = sorted.front();
    result.max_ns = sorted.back();
    result.p50_ns = nearest_rank(sorted, 0.50);
    result.p95_ns = nearest_rank(sorted, 0.95);
    result.p99_ns = nearest_rank(sorted, 0.99);
  } else {
    result.mean = static_cast<double>(sum / sorted.size());
    result.min = sorted.front();
    result.max = sorted.back();
    result.p50 = nearest_rank(sorted, 0.50);
    result.p95 = nearest_rank(sorted, 0.95);
    result.p99 = nearest_rank(sorted, 0.99);
  }
  return result;
}

} // namespace

std::optional<std::uint64_t> read_process_rss_bytes() noexcept {
#if defined(__linux__)
  std::ifstream statm("/proc/self/statm");
  std::uint64_t total_pages = 0;
  std::uint64_t resident_pages = 0;
  if (!(statm >> total_pages >> resident_pages) || resident_pages == 0) {
    return std::nullopt;
  }

  const auto page_size = sysconf(_SC_PAGESIZE);
  if (page_size <= 0) {
    return std::nullopt;
  }
  const auto page_size_u = static_cast<std::uint64_t>(page_size);
  if (resident_pages > std::numeric_limits<std::uint64_t>::max() /
                           page_size_u) {
    return std::nullopt;
  }
  return resident_pages * page_size_u;
#else
  return std::nullopt;
#endif
}

MetricsCollector::MetricsCollector(Clock::time_point start) : start_(start) {}

void MetricsCollector::reserve_duration_samples(std::string_view name,
                                                std::size_t capacity) {
  validate_name(name);
  durations_[std::string(name)].reserve(capacity);
}

void MetricsCollector::record_duration(std::string_view name,
                                       std::chrono::nanoseconds duration) {
  validate_name(name);
  if (duration.count() < 0) {
    throw std::invalid_argument("duration must not be negative");
  }
  durations_[std::string(name)].push_back(duration.count());
}

void MetricsCollector::add_counter(std::string_view name, std::int64_t delta) {
  validate_name(name);
  if (delta < 0) {
    throw std::invalid_argument("counter delta must not be negative");
  }
  auto &counter = counters_[std::string(name)];
  const auto amount = static_cast<std::uint64_t>(delta);
  if (counter > std::numeric_limits<std::uint64_t>::max() - amount) {
    throw std::overflow_error("counter overflow");
  }
  counter += amount;
}

void MetricsCollector::record_value(std::string_view name, std::int64_t value) {
  validate_name(name);
  values_[std::string(name)].push_back(value);
}

void MetricsCollector::record_frame() {
  if (frame_count_ == std::numeric_limits<std::uint64_t>::max()) {
    throw std::overflow_error("frame count overflow");
  }
  ++frame_count_;
}

void MetricsCollector::set_logical_map_bytes(std::uint64_t bytes) noexcept {
  logical_map_bytes_ = bytes;
}

void MetricsCollector::set_allocated_map_bytes(
    std::optional<std::uint64_t> bytes) {
  if (bytes.has_value() && *bytes == 0) {
    throw std::invalid_argument("allocated map bytes must be positive");
  }
  allocated_map_bytes_ = bytes;
}

void MetricsCollector::observe_rss_bytes(std::optional<std::uint64_t> bytes) {
  if (!bytes.has_value()) {
    return;
  }
  if (*bytes == 0) {
    throw std::invalid_argument("RSS must be positive");
  }
  current_rss_bytes_ = bytes;
  if (!peak_rss_bytes_.has_value() || *bytes > *peak_rss_bytes_) {
    peak_rss_bytes_ = bytes;
  }
}

MetricsReport MetricsCollector::report(Clock::time_point now) const {
  if (now < start_) {
    throw std::invalid_argument("report time must not precede collector start");
  }

  const auto elapsed = now - start_;
  const auto elapsed_ns = elapsed.count();
  if (elapsed_ns < 0) {
    throw std::invalid_argument("elapsed time must not be negative");
  }

  MetricsReport result;
  result.counters = counters_;
  result.frame_count = frame_count_;
  result.elapsed_seconds = std::chrono::duration<double>(elapsed).count();
  result.logical_map_bytes = logical_map_bytes_;
  result.allocated_map_bytes = allocated_map_bytes_;
  result.current_rss_bytes = current_rss_bytes_;
  result.peak_rss_bytes = peak_rss_bytes_;
  for (const auto &[name, samples] : durations_) {
    result.durations.emplace(name, summarize<DurationStatistics>(samples));
  }
  for (const auto &[name, samples] : values_) {
    result.values.emplace(name, summarize<ValueStatistics>(samples));
  }
  if (frame_count_ > 0 && result.elapsed_seconds > 0.0 &&
      std::isfinite(result.elapsed_seconds)) {
    result.fps = static_cast<double>(frame_count_) / result.elapsed_seconds;
  }
  return result;
}

} // namespace veyra::metrics
