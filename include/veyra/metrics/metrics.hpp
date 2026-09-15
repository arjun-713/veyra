#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace veyra::metrics {

inline const char* domain() noexcept { return "Metrics"; }

struct DurationStatistics {
  std::uint64_t count = 0;
  double mean_ns = 0.0;
  std::int64_t min_ns = 0;
  std::int64_t max_ns = 0;
  std::int64_t p50_ns = 0;
  std::int64_t p95_ns = 0;
  std::int64_t p99_ns = 0;
};

// Integer-valued samples such as topology changes per measured frame. They
// deliberately use the same nearest-rank percentile definition as durations.
struct ValueStatistics {
  std::uint64_t count = 0;
  double mean = 0.0;
  std::int64_t min = 0;
  std::int64_t max = 0;
  std::int64_t p50 = 0;
  std::int64_t p95 = 0;
  std::int64_t p99 = 0;
};

struct MetricsReport {
  std::unordered_map<std::string, DurationStatistics> durations;
  std::unordered_map<std::string, ValueStatistics> values;
  std::unordered_map<std::string, std::uint64_t> counters;
  std::uint64_t frame_count = 0;
  std::optional<double> fps;
  double elapsed_seconds = 0.0;
  std::uint64_t logical_map_bytes = 0;
  // Logical bytes are a map implementation's accounting estimate. Allocated
  // bytes are optional because the public map snapshot does not expose an
  // allocator measurement. RSS is a process-level measurement, never map RAM.
  std::optional<std::uint64_t> allocated_map_bytes;
  std::optional<std::uint64_t> current_rss_bytes;
  std::optional<std::uint64_t> peak_rss_bytes;
};

// Reads resident process memory. nullopt means the platform or procfs did not
// provide a trustworthy measurement; zero is never used as that sentinel.
std::optional<std::uint64_t> read_process_rss_bytes() noexcept;

class MetricsCollector {
 public:
  using Clock = std::chrono::steady_clock;

  // Zero keeps all samples for finite offline runs; live runtimes supply a
  // positive rolling limit. Frame/counter totals remain lifetime totals.
  explicit MetricsCollector(Clock::time_point start = Clock::now(), std::size_t sample_limit = 0);

  // Call during setup when sample volume is known to avoid vector growth in
  // the recording path. The first use of a new name still inserts its map key.
  void reserve_duration_samples(std::string_view name, std::size_t capacity);

  // Durations are recorded in nanoseconds. Percentiles use nearest-rank:
  // sort ascending, select ceil(p * count) with one-based rank, and clamp the
  // rank to [1, count]. Thus p50 of four samples is the second sample.
  void record_duration(std::string_view name, std::chrono::nanoseconds duration);
  void add_counter(std::string_view name, std::int64_t delta = 1);
  void record_value(std::string_view name, std::int64_t value);
  void record_frame();

  void set_logical_map_bytes(std::uint64_t bytes) noexcept;
  void set_allocated_map_bytes(std::optional<std::uint64_t> bytes);
  // A nullopt observation records that this platform did not provide RSS; it
  // does not synthesize a zero value. Non-null observations update current and
  // peak process RSS independently of logical map accounting.
  void observe_rss_bytes(std::optional<std::uint64_t> bytes);

  MetricsReport report(Clock::time_point now = Clock::now()) const;

 private:
  struct Samples {
    std::vector<std::int64_t> values;
    std::size_t next = 0;
    void add(std::int64_t value, std::size_t limit);
  };
  std::unordered_map<std::string, Samples> durations_;
  std::unordered_map<std::string, Samples> values_;
  std::size_t sample_limit_ = 0;
  std::unordered_map<std::string, std::uint64_t> counters_;
  Clock::time_point start_;
  std::uint64_t frame_count_ = 0;
  std::uint64_t logical_map_bytes_ = 0;
  std::optional<std::uint64_t> allocated_map_bytes_;
  std::optional<std::uint64_t> current_rss_bytes_;
  std::optional<std::uint64_t> peak_rss_bytes_;
};

}  // namespace veyra::metrics
