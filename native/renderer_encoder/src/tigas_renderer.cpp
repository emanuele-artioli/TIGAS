#include "tigas_renderer.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>

namespace {

float deg_to_rad(float degree) {
  return degree * 0.01745329251994329577f;
}

}  // namespace

namespace tigas {

GaussianRenderer::GaussianRenderer(std::string ply_path)
    : ply_path_(std::move(ply_path)), points_(load_points(ply_path_)) {}

std::vector<Point3D> GaussianRenderer::load_points(const std::string& path) const {
  std::ifstream input(path);
  if (!input.is_open()) {
    return {};
  }

  std::string line;
  bool in_header = true;
  bool ascii = false;
  int vertex_count = 0;

  while (in_header && std::getline(input, line)) {
    if (line == "end_header") {
      in_header = false;
      break;
    }
    if (line.find("format ascii") != std::string::npos) {
      ascii = true;
    }
    if (line.rfind("element vertex", 0) == 0) {
      std::istringstream ss(line);
      std::string element_name;
      ss >> element_name >> element_name >> vertex_count;
    }
  }

  if (!ascii || vertex_count <= 0) {
    return {};
  }

  std::vector<Point3D> points;
  points.reserve(static_cast<size_t>(vertex_count));

  for (int i = 0; i < vertex_count && std::getline(input, line); ++i) {
    std::istringstream ss(line);
    Point3D point{};
    int r = 255;
    int g = 255;
    int b = 255;
    ss >> point.x >> point.y >> point.z >> r >> g >> b;
    point.r = static_cast<uint8_t>(std::clamp(r, 0, 255));
    point.g = static_cast<uint8_t>(std::clamp(g, 0, 255));
    point.b = static_cast<uint8_t>(std::clamp(b, 0, 255));
    points.push_back(point);
  }

  return points;
}

RGBFrame GaussianRenderer::render(const MovementSample& sample) const {
  const int width = std::clamp(sample.width, 64, 1280);
  const int height = std::clamp(sample.height, 64, 720);

  RGBFrame frame;
  frame.width = width;
  frame.height = height;
  frame.data.resize(static_cast<size_t>(width * height * 3));

  const float yaw = deg_to_rad(sample.angle);
  const float pitch = deg_to_rad(sample.elevation);
  const float cx = width * 0.5f;
  const float cy = height * 0.5f;

  if (!points_.empty()) {
    for (const auto& point : points_) {
      const float tx = point.x - sample.x;
      const float ty = point.y - sample.y;
      const float tz = point.z - sample.z;

      const float xz_x = std::cos(yaw) * tx - std::sin(yaw) * tz;
      const float xz_z = std::sin(yaw) * tx + std::cos(yaw) * tz;
      const float yz_y = std::cos(pitch) * ty - std::sin(pitch) * xz_z;
      const float yz_z = std::sin(pitch) * ty + std::cos(pitch) * xz_z;

      if (yz_z <= 0.01f) {
        continue;
      }

      const float fx = static_cast<float>(width);
      const float fy = static_cast<float>(height);
      const int px = static_cast<int>(cx + (xz_x / yz_z) * fx * 0.5f);
      const int py = static_cast<int>(cy - (yz_y / yz_z) * fy * 0.5f);
      if (px < 1 || py < 1 || px >= width - 1 || py >= height - 1) {
        continue;
      }

      const float depth_weight = std::clamp(2.0f / (1.0f + yz_z * yz_z), 0.1f, 1.0f);
      for (int oy = -1; oy <= 1; ++oy) {
        for (int ox = -1; ox <= 1; ++ox) {
          const int x = px + ox;
          const int y = py + oy;
          const size_t idx = static_cast<size_t>((y * width + x) * 3);
          frame.data[idx + 0] = static_cast<uint8_t>(std::clamp(static_cast<float>(frame.data[idx + 0]) * 0.35f + point.r * depth_weight, 0.0f, 255.0f));
          frame.data[idx + 1] = static_cast<uint8_t>(std::clamp(static_cast<float>(frame.data[idx + 1]) * 0.35f + point.g * depth_weight, 0.0f, 255.0f));
          frame.data[idx + 2] = static_cast<uint8_t>(std::clamp(static_cast<float>(frame.data[idx + 2]) * 0.35f + point.b * depth_weight, 0.0f, 255.0f));
        }
      }
    }
    return frame;
  }

  const float phase = 0.6f * sample.x + 0.4f * sample.z + yaw;
  const float elev = pitch;

  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      const float nx = static_cast<float>(x) / static_cast<float>(width);
      const float ny = static_cast<float>(y) / static_cast<float>(height);

      const float r = std::sin((nx + phase) * 3.1415926f) * 0.5f + 0.5f;
      const float g = std::cos((ny + elev) * 3.1415926f) * 0.5f + 0.5f;
      const float b = std::sin((nx + ny + phase) * 3.1415926f) * 0.5f + 0.5f;

      const size_t idx = static_cast<size_t>((y * width + x) * 3);
      frame.data[idx + 0] = static_cast<uint8_t>(std::clamp(r, 0.0f, 1.0f) * 255.0f);
      frame.data[idx + 1] = static_cast<uint8_t>(std::clamp(g, 0.0f, 1.0f) * 255.0f);
      frame.data[idx + 2] = static_cast<uint8_t>(std::clamp(b, 0.0f, 1.0f) * 255.0f);
    }
  }

  return frame;
}

}  // namespace tigas
