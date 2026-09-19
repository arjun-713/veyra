#pragma once
#include <cmath>
#include <cstdint>

namespace veyra::map {

struct Observation;

// Range-dependent measurement uncertainty, and the outlier gate built on it.
//
// Why this exists: CellStats folds every return into a layer with equal
// weight. A 3 m return and an 80 m return at grazing incidence are treated as
// equally trustworthy, and one spurious return permanently shifts the mean of
// the cell it lands in. Every mature elevation mapper models this instead --
// ANYbotics/ETH elevation_mapping carries a per-point variance from a sensor
// noise model and rejects outliers on Mahalanobis distance before fusing.
//
// The model is sigma(r) = sigma_0 + k_linear * r + k_quadratic * r^2, and the
// three terms are not interchangeable curve-fitting knobs. Each is a distinct
// physical effect:
//
//   sigma_0      intrinsic ranging noise of the sensor, constant with range.
//   k_linear     beam divergence. The footprint grows linearly with range, so
//                on any surface that is not perpendicular to the beam the
//                height spread inside one footprint grows linearly too. For a
//                spinning LiDAR with ~0.1 deg divergence this dominates past
//                ~30 m, which is why a linear term is present at all -- a
//                purely quadratic model borrowed from depth-camera literature
//                understates mid-range error for LiDAR.
//   k_quadratic  time-of-flight resolution effects at long range.
//
// Defaults are order-of-magnitude figures for a 64-beam spinning LiDAR, NOT
// measurements from a calibrated unit. They give ~2 cm at 0 m and ~15 cm at
// 80 m. Per AGENTS.md they must not be reported as measured performance, and
// a deployment should fit them against its own sensor.
struct SensorNoiseModel {
  double sigma_0_m = 0.02;
  double k_linear = 0.0017;      // ~0.1 deg beam divergence
  double k_quadratic = 0.0;      // off by default; enable when fitted
  // Mahalanobis gate, in standard deviations, for accepting a return into a
  // layer that already holds evidence. 3.0 accepts ~99.7% of genuine returns.
  //
  // The gate widens automatically with range because the sensor term grows,
  // so a far return is not rejected merely for being imprecise -- only for
  // disagreeing by more than its own imprecision can explain. That asymmetry
  // is the point: without it, a range-aware gate would reject exactly the
  // distant returns it is supposed to accommodate.
  double mahalanobis_gate = 3.0;
  // A layer must hold at least this many returns before the gate is applied.
  // Rejecting against a mean built from one or two returns would let the first
  // spurious return lock the cell and reject the true surface that follows.
  std::uint32_t min_returns_before_gating = 5;

  [[nodiscard]] double stddev_at(double range_m) const noexcept {
    const double r = range_m > 0.0 ? range_m : 0.0;
    return sigma_0_m + k_linear * r + k_quadratic * r * r;
  }
  [[nodiscard]] double variance_at(double range_m) const noexcept {
    const double s = stddev_at(range_m);
    return s * s;
  }

  void validate() const;
};

// Where the sensor was when the returns were taken, in the same world frame as
// the observations. Supplied by the caller: the map is given poses, it does
// not estimate them (AGENTS.md -- pose is external input).
struct SensorPose {
  double x = 0.0;
  double y = 0.0;
  double z = 0.0;

  [[nodiscard]] double range_to(double px, double py, double pz) const noexcept {
    const double dx = px - x;
    const double dy = py - y;
    const double dz = pz - z;
    return std::sqrt(dx * dx + dy * dy + dz * dz);
  }
};

}  // namespace veyra::map
