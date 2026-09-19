#include "veyra/map/sensor_model.hpp"

#include <cmath>
#include <stdexcept>

namespace veyra::map {

void SensorNoiseModel::validate() const {
  if (!std::isfinite(sigma_0_m) || !std::isfinite(k_linear) || !std::isfinite(k_quadratic) ||
      !std::isfinite(mahalanobis_gate)) {
    throw std::invalid_argument("sensor noise model coefficients must be finite");
  }
  if (sigma_0_m <= 0.0) {
    // A zero constant term would make a return at zero range infinitely
    // trustworthy, and the gate would reject everything that followed it.
    throw std::invalid_argument("sigma_0_m must be positive");
  }
  if (k_linear < 0.0 || k_quadratic < 0.0) {
    throw std::invalid_argument("noise must not decrease with range");
  }
  if (mahalanobis_gate <= 0.0) {
    throw std::invalid_argument("mahalanobis gate must be positive");
  }
}

}  // namespace veyra::map
