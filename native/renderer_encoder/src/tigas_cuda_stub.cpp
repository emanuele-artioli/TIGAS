#include "tigas_cuda_renderer.hpp"

namespace tigas::cuda_backend {

bool available() {
  return false;
}

bool render_points(const std::vector<Point3D>&, const MovementSample&, RGBFrame&, std::string& error_message) {
  error_message = "CUDA backend unavailable in this build";
  return false;
}

}  // namespace tigas::cuda_backend
