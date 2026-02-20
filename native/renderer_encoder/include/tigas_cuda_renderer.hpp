#pragma once

#include <string>
#include <vector>

#include "tigas_renderer.hpp"
#include "tigas_trace.hpp"

namespace tigas::cuda_backend {

bool available();
bool render_points(const std::vector<Point3D>& points, const MovementSample& sample, RGBFrame& frame, std::string& error_message);

}  // namespace tigas::cuda_backend
