#include "tigas_trace.hpp"

#include <fstream>
#include <stdexcept>

#include <nlohmann/json.hpp>

namespace tigas {

std::vector<MovementSample> load_movement_trace(const std::string& trace_path, int max_frames) {
  std::ifstream input(trace_path);
  if (!input.is_open()) {
    throw std::runtime_error("Unable to open movement trace: " + trace_path);
  }

  nlohmann::json root;
  input >> root;
  if (!root.is_array()) {
    throw std::runtime_error("Movement trace must be a JSON array");
  }

  std::vector<MovementSample> samples;
  samples.reserve(root.size());

  int frame_id = 0;
  for (const auto& item : root) {
    if (max_frames > 0 && frame_id >= max_frames) {
      break;
    }

    samples.push_back(MovementSample{
        frame_id,
        item.value("tMs", 0),
        item.value("durationMs", 16),
        item.value("x", 0.0f),
        item.value("y", 0.0f),
        item.value("z", 0.0f),
        item.value("angle", 0.0f),
        item.value("elevation", 0.0f),
        item.value("width", 800),
        item.value("height", 600),
    });
    frame_id += 1;
  }

  return samples;
}

}  // namespace tigas
