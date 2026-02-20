#include "tigas_cuda_renderer.hpp"

#if defined(TIGAS_HAS_CUDA) && TIGAS_HAS_CUDA

#include <cmath>
#include <cstdint>
#include <string>
#include <vector>

#include <cuda_runtime.h>

namespace tigas::cuda_backend {

namespace {

struct CudaPoint {
  float x;
  float y;
  float z;
  uint8_t r;
  uint8_t g;
  uint8_t b;
  float opacity;
  float radius;
};

__device__ float clampf(float value, float lo, float hi) {
  return value < lo ? lo : (value > hi ? hi : value);
}

__global__ void project_points_kernel(
    const CudaPoint* points,
    int point_count,
    float* accum_r,
    float* accum_g,
    float* accum_b,
    float* accum_a,
    int width,
    int height,
    float cam_x,
    float cam_y,
    float cam_z,
    float yaw,
    float pitch) {
  const int idx = blockIdx.x * blockDim.x + threadIdx.x;
  if (idx >= point_count) {
    return;
  }

  const CudaPoint point = points[idx];
  const float tx = point.x - cam_x;
  const float ty = point.y - cam_y;
  const float tz = point.z - cam_z;

  const float c_yaw = cosf(yaw);
  const float s_yaw = sinf(yaw);
  const float c_pitch = cosf(pitch);
  const float s_pitch = sinf(pitch);

  const float xz_x = c_yaw * tx - s_yaw * tz;
  const float xz_z = s_yaw * tx + c_yaw * tz;
  const float yz_y = c_pitch * ty - s_pitch * xz_z;
  const float yz_z = s_pitch * ty + c_pitch * xz_z;

  if (yz_z <= 0.01f) {
    return;
  }

  const float cx = width * 0.5f;
  const float cy = height * 0.5f;
  const float fx = static_cast<float>(width);
  const float fy = static_cast<float>(height);

  const int px = static_cast<int>(cx + (xz_x / yz_z) * fx * 0.5f);
  const int py = static_cast<int>(cy - (yz_y / yz_z) * fy * 0.5f);
  if (px < 1 || py < 1 || px >= width - 1 || py >= height - 1) {
    return;
  }

  const float depth_weight = clampf(2.0f / (1.0f + yz_z * yz_z), 0.15f, 1.0f);
  const float screen_radius = clampf((point.radius * fx / fmaxf(yz_z, 0.05f)) * 0.05f, 1.0f, 9.0f);
  const int radius_px = static_cast<int>(ceilf(screen_radius));
  const float sigma2 = fmaxf(0.5f, screen_radius * screen_radius * 0.5f);

  for (int oy = -radius_px; oy <= radius_px; ++oy) {
    for (int ox = -radius_px; ox <= radius_px; ++ox) {
      const int x = px + ox;
      const int y = py + oy;
      if (x < 0 || y < 0 || x >= width || y >= height) {
        continue;
      }
      const float d2 = static_cast<float>(ox * ox + oy * oy);
      const float gaussian = expf(-d2 / (2.0f * sigma2));
      const float alpha = clampf(gaussian * point.opacity * depth_weight, 0.0f, 1.0f);
      const int pixel_idx = y * width + x;
      atomicAdd(&accum_r[pixel_idx], static_cast<float>(point.r) * alpha);
      atomicAdd(&accum_g[pixel_idx], static_cast<float>(point.g) * alpha);
      atomicAdd(&accum_b[pixel_idx], static_cast<float>(point.b) * alpha);
      atomicAdd(&accum_a[pixel_idx], alpha);
    }
  }
}

__global__ void normalize_kernel(
    const float* accum_r,
    const float* accum_g,
    const float* accum_b,
    const float* accum_a,
    uint8_t* image,
    int pixel_count) {
  const int idx = blockIdx.x * blockDim.x + threadIdx.x;
  if (idx >= pixel_count) {
    return;
  }
  const float alpha = accum_a[idx];
  const float inv = alpha > 1e-6f ? 1.0f / alpha : 0.0f;
  image[idx * 3 + 0] = static_cast<uint8_t>(clampf(accum_r[idx] * inv, 0.0f, 255.0f));
  image[idx * 3 + 1] = static_cast<uint8_t>(clampf(accum_g[idx] * inv, 0.0f, 255.0f));
  image[idx * 3 + 2] = static_cast<uint8_t>(clampf(accum_b[idx] * inv, 0.0f, 255.0f));
}

}  // namespace

bool available() {
  int device_count = 0;
  if (cudaGetDeviceCount(&device_count) != cudaSuccess) {
    return false;
  }
  return device_count > 0;
}

bool render_points(const std::vector<Point3D>& points, const MovementSample& sample, RGBFrame& frame, std::string& error_message) {
  frame.data.assign(static_cast<size_t>(frame.width * frame.height * 3), 0);

  if (points.empty()) {
    error_message = "No points to render";
    return false;
  }

  std::vector<CudaPoint> host_points;
  host_points.reserve(points.size());
  for (const auto& point : points) {
    host_points.push_back(CudaPoint{point.x, point.y, point.z, point.r, point.g, point.b, point.opacity, point.radius});
  }

  CudaPoint* device_points = nullptr;
  float* accum_r = nullptr;
  float* accum_g = nullptr;
  float* accum_b = nullptr;
  float* accum_a = nullptr;
  uint8_t* device_image = nullptr;

  const size_t points_bytes = host_points.size() * sizeof(CudaPoint);
  const size_t image_pixels = static_cast<size_t>(frame.width * frame.height);
  const size_t channel_bytes = image_pixels * sizeof(float);
  const size_t image_bytes = image_pixels * 3 * sizeof(uint8_t);

  if (cudaMalloc(&device_points, points_bytes) != cudaSuccess) {
    error_message = "cudaMalloc failed for point buffer";
    return false;
  }
  if (cudaMalloc(&accum_r, channel_bytes) != cudaSuccess ||
      cudaMalloc(&accum_g, channel_bytes) != cudaSuccess ||
      cudaMalloc(&accum_b, channel_bytes) != cudaSuccess ||
      cudaMalloc(&accum_a, channel_bytes) != cudaSuccess ||
      cudaMalloc(&device_image, image_bytes) != cudaSuccess) {
    cudaFree(device_points);
    if (accum_r) cudaFree(accum_r);
    if (accum_g) cudaFree(accum_g);
    if (accum_b) cudaFree(accum_b);
    if (accum_a) cudaFree(accum_a);
    if (device_image) cudaFree(device_image);
    error_message = "cudaMalloc failed for image buffer";
    return false;
  }

  if (cudaMemcpy(device_points, host_points.data(), points_bytes, cudaMemcpyHostToDevice) != cudaSuccess) {
    cudaFree(device_points);
    cudaFree(accum_r);
    cudaFree(accum_g);
    cudaFree(accum_b);
    cudaFree(accum_a);
    cudaFree(device_image);
    error_message = "cudaMemcpy host->device failed for points";
    return false;
  }

  cudaMemset(accum_r, 0, channel_bytes);
  cudaMemset(accum_g, 0, channel_bytes);
  cudaMemset(accum_b, 0, channel_bytes);
  cudaMemset(accum_a, 0, channel_bytes);
  cudaMemset(device_image, 0, image_bytes);

  const int threads = 256;
  const int blocks = static_cast<int>((host_points.size() + static_cast<size_t>(threads) - 1) / static_cast<size_t>(threads));
  const float yaw = sample.angle * 0.01745329251994329577f;
  const float pitch = sample.elevation * 0.01745329251994329577f;

  project_points_kernel<<<blocks, threads>>>(
      device_points,
      static_cast<int>(host_points.size()),
      accum_r,
      accum_g,
      accum_b,
      accum_a,
      frame.width,
      frame.height,
      sample.x,
      sample.y,
      sample.z,
      yaw,
      pitch);

  if (cudaDeviceSynchronize() != cudaSuccess) {
    cudaFree(device_points);
    cudaFree(accum_r);
    cudaFree(accum_g);
    cudaFree(accum_b);
    cudaFree(accum_a);
    cudaFree(device_image);
    error_message = "CUDA kernel execution failed";
    return false;
  }

  const int norm_blocks = static_cast<int>((image_pixels + static_cast<size_t>(threads) - 1) / static_cast<size_t>(threads));
  normalize_kernel<<<norm_blocks, threads>>>(accum_r, accum_g, accum_b, accum_a, device_image, static_cast<int>(image_pixels));
  if (cudaDeviceSynchronize() != cudaSuccess) {
    cudaFree(device_points);
    cudaFree(accum_r);
    cudaFree(accum_g);
    cudaFree(accum_b);
    cudaFree(accum_a);
    cudaFree(device_image);
    error_message = "CUDA normalization failed";
    return false;
  }

  if (cudaMemcpy(frame.data.data(), device_image, image_bytes, cudaMemcpyDeviceToHost) != cudaSuccess) {
    cudaFree(device_points);
    cudaFree(accum_r);
    cudaFree(accum_g);
    cudaFree(accum_b);
    cudaFree(accum_a);
    cudaFree(device_image);
    error_message = "cudaMemcpy device->host failed for image";
    return false;
  }

  cudaFree(device_points);
  cudaFree(accum_r);
  cudaFree(accum_g);
  cudaFree(accum_b);
  cudaFree(accum_a);
  cudaFree(device_image);
  return true;
}

}  // namespace tigas::cuda_backend

#else

namespace tigas::cuda_backend {

bool available() {
  return false;
}

bool render_points(const std::vector<Point3D>&, const MovementSample&, RGBFrame&, std::string& error_message) {
  error_message = "CUDA backend unavailable in this build";
  return false;
}

}  // namespace tigas::cuda_backend

#endif
