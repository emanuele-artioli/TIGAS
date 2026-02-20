#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace tigas {

struct MovementSample {
  int frame_id;
  int64_t t_ms;
  int duration_ms;
  float x;
  float y;
  float z;
  float angle;
  float elevation;
  int width;
  int height;
};

std::vector<MovementSample> load_movement_trace(const std::string& trace_path, int max_frames);

}  // namespace tigas
