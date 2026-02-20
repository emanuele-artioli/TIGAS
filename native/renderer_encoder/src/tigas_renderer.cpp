#include "tigas_renderer.hpp"
#include "tigas_cuda_renderer.hpp"

#include <algorithm>
#include <cstdint>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <sstream>
#include <string>
#include <vector>

namespace {

float deg_to_rad(float degree) {
  return degree * 0.01745329251994329577f;
}

constexpr float kShC0 = 0.28209479177387814f;

float sigmoid(float x) {
  return 1.0f / (1.0f + std::exp(-x));
}

std::string trim_right(std::string value) {
  while (!value.empty() && (value.back() == '\r' || value.back() == '\n' || value.back() == ' ' || value.back() == '\t')) {
    value.pop_back();
  }
  return value;
}

size_t scalar_size_bytes(const std::string& type) {
  if (type == "char" || type == "int8" || type == "uchar" || type == "uint8") {
    return 1;
  }
  if (type == "short" || type == "int16" || type == "ushort" || type == "uint16") {
    return 2;
  }
  if (type == "int" || type == "int32" || type == "uint" || type == "uint32" || type == "float" || type == "float32") {
    return 4;
  }
  if (type == "double" || type == "float64") {
    return 8;
  }
  return 0;
}

double read_scalar_binary(std::istream& input, const std::string& type) {
  if (type == "char" || type == "int8") {
    int8_t value = 0;
    input.read(reinterpret_cast<char*>(&value), sizeof(value));
    return static_cast<double>(value);
  }
  if (type == "uchar" || type == "uint8") {
    uint8_t value = 0;
    input.read(reinterpret_cast<char*>(&value), sizeof(value));
    return static_cast<double>(value);
  }
  if (type == "short" || type == "int16") {
    int16_t value = 0;
    input.read(reinterpret_cast<char*>(&value), sizeof(value));
    return static_cast<double>(value);
  }
  if (type == "ushort" || type == "uint16") {
    uint16_t value = 0;
    input.read(reinterpret_cast<char*>(&value), sizeof(value));
    return static_cast<double>(value);
  }
  if (type == "int" || type == "int32") {
    int32_t value = 0;
    input.read(reinterpret_cast<char*>(&value), sizeof(value));
    return static_cast<double>(value);
  }
  if (type == "uint" || type == "uint32") {
    uint32_t value = 0;
    input.read(reinterpret_cast<char*>(&value), sizeof(value));
    return static_cast<double>(value);
  }
  if (type == "float" || type == "float32") {
    float value = 0.0f;
    input.read(reinterpret_cast<char*>(&value), sizeof(value));
    return static_cast<double>(value);
  }
  if (type == "double" || type == "float64") {
    double value = 0.0;
    input.read(reinterpret_cast<char*>(&value), sizeof(value));
    return value;
  }
  return std::numeric_limits<double>::quiet_NaN();
}

struct VertexProperty {
  std::string type;
  std::string name;
};

tigas::Point3D make_point(
    float x,
    float y,
    float z,
    bool has_rgb,
    int r,
    int g,
    int b,
    bool has_dc,
    float dc0,
    float dc1,
    float dc2,
    float opacity_logit,
    float scale0,
    float scale1,
    float scale2) {
  tigas::Point3D point{};
  point.x = x;
  point.y = y;
  point.z = z;
  point.opacity = std::clamp(sigmoid(opacity_logit), 0.02f, 1.0f);
  const float scale_avg = (scale0 + scale1 + scale2) / 3.0f;
  point.radius = std::clamp(std::exp(scale_avg), 0.25f, 8.0f);

  if (has_rgb) {
    point.r = static_cast<uint8_t>(std::clamp(r, 0, 255));
    point.g = static_cast<uint8_t>(std::clamp(g, 0, 255));
    point.b = static_cast<uint8_t>(std::clamp(b, 0, 255));
    return point;
  }

  if (has_dc) {
    const float red = std::clamp(0.5f + kShC0 * dc0, 0.0f, 1.0f);
    const float green = std::clamp(0.5f + kShC0 * dc1, 0.0f, 1.0f);
    const float blue = std::clamp(0.5f + kShC0 * dc2, 0.0f, 1.0f);
    point.r = static_cast<uint8_t>(red * 255.0f);
    point.g = static_cast<uint8_t>(green * 255.0f);
    point.b = static_cast<uint8_t>(blue * 255.0f);
    return point;
  }

  point.r = 255;
  point.g = 255;
  point.b = 255;
  return point;
}

}  // namespace

namespace tigas {

GaussianRenderer::GaussianRenderer(std::string ply_path, bool prefer_cuda)
    : ply_path_(std::move(ply_path)),
      points_(load_points(ply_path_)),
      prefer_cuda_(prefer_cuda),
      use_cuda_(prefer_cuda && cuda_backend::available()),
      cuda_warning_emitted_(false) {
  if (!ply_path_.empty() && points_.empty()) {
    throw std::runtime_error("Failed to parse PLY points from: " + ply_path_);
  }
}

bool GaussianRenderer::is_using_cuda() const {
  return use_cuda_;
}

std::vector<Point3D> GaussianRenderer::load_points(const std::string& path) const {
  std::ifstream input(path, std::ios::binary);
  if (!input.is_open()) {
    return {};
  }

  std::string line;
  bool binary_little_endian = false;
  bool ascii = false;
  bool in_vertex_element = false;
  bool unsupported_list_property = false;
  int vertex_count = 0;
  std::vector<VertexProperty> vertex_properties;

  while (std::getline(input, line)) {
    line = trim_right(line);
    if (line == "end_header") {
      break;
    }

    if (line.find("format ascii") != std::string::npos) {
      ascii = true;
      binary_little_endian = false;
      continue;
    }
    if (line.find("format binary_little_endian") != std::string::npos) {
      ascii = false;
      binary_little_endian = true;
      continue;
    }

    if (line.rfind("element vertex", 0) == 0) {
      std::istringstream ss(line);
      std::string element_token;
      std::string vertex_token;
      ss >> element_token >> vertex_token >> vertex_count;
      in_vertex_element = true;
      continue;
    }

    if (line.rfind("element ", 0) == 0 && line.rfind("element vertex", 0) != 0) {
      in_vertex_element = false;
      continue;
    }

    if (in_vertex_element && line.rfind("property list", 0) == 0) {
      unsupported_list_property = true;
      continue;
    }

    if (in_vertex_element && line.rfind("property ", 0) == 0) {
      std::istringstream ss(line);
      std::string property_token;
      std::string type;
      std::string name;
      ss >> property_token >> type >> name;
      if (!type.empty() && !name.empty()) {
        vertex_properties.push_back(VertexProperty{type, name});
      }
    }
  }

  if (vertex_count <= 0 || vertex_properties.empty() || unsupported_list_property) {
    return {};
  }
  if (!ascii && !binary_little_endian) {
    return {};
  }

  std::vector<Point3D> points;
  points.reserve(static_cast<size_t>(vertex_count));

  if (ascii) {
    for (int i = 0; i < vertex_count && std::getline(input, line); ++i) {
      line = trim_right(line);
      if (line.empty()) {
        continue;
      }

      std::istringstream ss(line);
      std::vector<double> values(vertex_properties.size(), 0.0);
      for (size_t prop_idx = 0; prop_idx < vertex_properties.size(); ++prop_idx) {
        ss >> values[prop_idx];
      }

      float x = 0.0f;
      float y = 0.0f;
      float z = 0.0f;
      bool has_rgb = false;
      int r = 255;
      int g = 255;
      int b = 255;
      bool has_dc = false;
      float dc0 = 0.0f;
      float dc1 = 0.0f;
      float dc2 = 0.0f;
      float opacity_logit = 0.0f;
      float scale0 = -1.5f;
      float scale1 = -1.5f;
      float scale2 = -1.5f;

      for (size_t prop_idx = 0; prop_idx < vertex_properties.size(); ++prop_idx) {
        const auto& prop = vertex_properties[prop_idx];
        const double value = values[prop_idx];
        if (prop.name == "x") x = static_cast<float>(value);
        else if (prop.name == "y") y = static_cast<float>(value);
        else if (prop.name == "z") z = static_cast<float>(value);
        else if (prop.name == "red" || prop.name == "r") {
          has_rgb = true;
          r = static_cast<int>(value);
        } else if (prop.name == "green" || prop.name == "g") {
          has_rgb = true;
          g = static_cast<int>(value);
        } else if (prop.name == "blue" || prop.name == "b") {
          has_rgb = true;
          b = static_cast<int>(value);
        } else if (prop.name == "f_dc_0") {
          has_dc = true;
          dc0 = static_cast<float>(value);
        } else if (prop.name == "f_dc_1") {
          has_dc = true;
          dc1 = static_cast<float>(value);
        } else if (prop.name == "f_dc_2") {
          has_dc = true;
          dc2 = static_cast<float>(value);
        } else if (prop.name == "opacity") {
          opacity_logit = static_cast<float>(value);
        } else if (prop.name == "scale_0") {
          scale0 = static_cast<float>(value);
        } else if (prop.name == "scale_1") {
          scale1 = static_cast<float>(value);
        } else if (prop.name == "scale_2") {
          scale2 = static_cast<float>(value);
        }
      }

      points.push_back(make_point(x, y, z, has_rgb, r, g, b, has_dc, dc0, dc1, dc2, opacity_logit, scale0, scale1, scale2));
    }
    return points;
  }

  for (int i = 0; i < vertex_count; ++i) {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    bool has_rgb = false;
    int r = 255;
    int g = 255;
    int b = 255;
    bool has_dc = false;
    float dc0 = 0.0f;
    float dc1 = 0.0f;
    float dc2 = 0.0f;
    float opacity_logit = 0.0f;
    float scale0 = -1.5f;
    float scale1 = -1.5f;
    float scale2 = -1.5f;

    for (const auto& prop : vertex_properties) {
      if (scalar_size_bytes(prop.type) == 0) {
        return {};
      }
      const double value = read_scalar_binary(input, prop.type);
      if (!input.good()) {
        return {};
      }

      if (prop.name == "x") x = static_cast<float>(value);
      else if (prop.name == "y") y = static_cast<float>(value);
      else if (prop.name == "z") z = static_cast<float>(value);
      else if (prop.name == "red" || prop.name == "r") {
        has_rgb = true;
        r = static_cast<int>(value);
      } else if (prop.name == "green" || prop.name == "g") {
        has_rgb = true;
        g = static_cast<int>(value);
      } else if (prop.name == "blue" || prop.name == "b") {
        has_rgb = true;
        b = static_cast<int>(value);
      } else if (prop.name == "f_dc_0") {
        has_dc = true;
        dc0 = static_cast<float>(value);
      } else if (prop.name == "f_dc_1") {
        has_dc = true;
        dc1 = static_cast<float>(value);
      } else if (prop.name == "f_dc_2") {
        has_dc = true;
        dc2 = static_cast<float>(value);
      } else if (prop.name == "opacity") {
        opacity_logit = static_cast<float>(value);
      } else if (prop.name == "scale_0") {
        scale0 = static_cast<float>(value);
      } else if (prop.name == "scale_1") {
        scale1 = static_cast<float>(value);
      } else if (prop.name == "scale_2") {
        scale2 = static_cast<float>(value);
      }
    }

    points.push_back(make_point(x, y, z, has_rgb, r, g, b, has_dc, dc0, dc1, dc2, opacity_logit, scale0, scale1, scale2));
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

  if (!points_.empty() && use_cuda_) {
    std::string error_message;
    if (cuda_backend::render_points(points_, sample, frame, error_message)) {
      return frame;
    }
    use_cuda_ = false;
    if (!cuda_warning_emitted_) {
      cuda_warning_emitted_ = true;
      std::cerr << "[tigas_renderer] CUDA render unavailable, switching to CPU fallback: " << error_message << "\n";
    }
  }

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

      const float depth_weight = std::clamp(2.0f / (1.0f + yz_z * yz_z), 0.15f, 1.0f);
      const float screen_radius = std::clamp((point.radius * fx / std::max(yz_z, 0.05f)) * 0.05f, 1.0f, 9.0f);
      const int radius_px = static_cast<int>(std::ceil(screen_radius));
      const float sigma2 = std::max(0.5f, screen_radius * screen_radius * 0.5f);

      for (int oy = -radius_px; oy <= radius_px; ++oy) {
        for (int ox = -radius_px; ox <= radius_px; ++ox) {
          const int x = px + ox;
          const int y = py + oy;
          if (x < 0 || y < 0 || x >= width || y >= height) {
            continue;
          }
          const float d2 = static_cast<float>(ox * ox + oy * oy);
          const float gaussian = std::exp(-d2 / (2.0f * sigma2));
          const float alpha = std::clamp(gaussian * point.opacity * depth_weight, 0.0f, 1.0f);
          const size_t idx = static_cast<size_t>((y * width + x) * 3);
          const float base_r = static_cast<float>(frame.data[idx + 0]);
          const float base_g = static_cast<float>(frame.data[idx + 1]);
          const float base_b = static_cast<float>(frame.data[idx + 2]);
          frame.data[idx + 0] = static_cast<uint8_t>(std::clamp(base_r * (1.0f - alpha) + point.r * alpha, 0.0f, 255.0f));
          frame.data[idx + 1] = static_cast<uint8_t>(std::clamp(base_g * (1.0f - alpha) + point.g * alpha, 0.0f, 255.0f));
          frame.data[idx + 2] = static_cast<uint8_t>(std::clamp(base_b * (1.0f - alpha) + point.b * alpha, 0.0f, 255.0f));
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
