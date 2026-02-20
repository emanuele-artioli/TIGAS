#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "tigas_trace.hpp"

namespace tigas {

struct RGBFrame {
  int width;
  int height;
  std::vector<uint8_t> data;
};

struct Point3D {
  float x;
  float y;
  float z;
  uint8_t r;
  uint8_t g;
  uint8_t b;
  float opacity;
  float radius;
};

class GaussianRenderer {
 public:
  explicit GaussianRenderer(std::string ply_path, bool prefer_cuda = true);

  RGBFrame render(const MovementSample& sample) const;
  bool is_using_cuda() const;

 private:
  std::vector<Point3D> load_points(const std::string& path) const;
  std::string ply_path_;
  std::vector<Point3D> points_;
  bool prefer_cuda_;
  mutable bool use_cuda_;
  mutable bool cuda_warning_emitted_;
};

}  // namespace tigas
