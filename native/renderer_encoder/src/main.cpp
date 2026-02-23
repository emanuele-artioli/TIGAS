#include <filesystem>
#include <chrono>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "tigas_encoder.hpp"
#include "tigas_renderer.hpp"
#include "tigas_trace.hpp"

namespace {

struct Args {
  std::string movement_trace;
  std::string output_dir;
  std::string ply_path;
  int max_frames = 600;
  int fps = 60;
  int crf = 26;
  std::string codec = "h264_nvenc";
  bool prefer_cuda = true;
  std::vector<int> crf_ladder;
  bool live_dash = false;
  bool realtime = false;
  int dash_window_size = 5;
};

std::vector<int> parse_crf_ladder(const std::string& input) {
  std::vector<int> values;
  std::stringstream ss(input);
  std::string token;
  while (std::getline(ss, token, ',')) {
    if (token.empty()) {
      continue;
    }
    values.push_back(std::stoi(token));
  }
  return values;
}

Args parse_args(int argc, char** argv) {
  Args args;
  for (int i = 1; i < argc; ++i) {
    std::string key = argv[i];
    auto read_value = [&](const std::string& name) -> std::string {
      if (i + 1 >= argc) {
        throw std::runtime_error("Missing value for " + name);
      }
      i += 1;
      return argv[i];
    };

    if (key == "--movement") {
      args.movement_trace = read_value(key);
    } else if (key == "--output-dir") {
      args.output_dir = read_value(key);
    } else if (key == "--ply") {
      args.ply_path = read_value(key);
    } else if (key == "--max-frames") {
      args.max_frames = std::stoi(read_value(key));
    } else if (key == "--fps") {
      args.fps = std::stoi(read_value(key));
    } else if (key == "--crf") {
      args.crf = std::stoi(read_value(key));
    } else if (key == "--codec") {
      args.codec = read_value(key);
    } else if (key == "--disable-cuda") {
      args.prefer_cuda = false;
    } else if (key == "--crf-ladder") {
      args.crf_ladder = parse_crf_ladder(read_value(key));
    } else if (key == "--live-dash") {
      args.live_dash = true;
      args.realtime = true;
    } else if (key == "--realtime") {
      args.realtime = true;
    } else if (key == "--dash-window-size") {
      args.dash_window_size = std::stoi(read_value(key));
    } else {
      throw std::runtime_error("Unknown argument: " + key);
    }
  }

  if (args.movement_trace.empty() || args.output_dir.empty()) {
    throw std::runtime_error("Required arguments: --movement --output-dir");
  }
  return args;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Args args = parse_args(argc, argv);
    std::filesystem::create_directories(args.output_dir);

    const auto movement = tigas::load_movement_trace(args.movement_trace, args.max_frames);
    if (movement.empty()) {
      throw std::runtime_error("Movement trace has no samples");
    }

    tigas::GaussianRenderer renderer(args.ply_path, args.prefer_cuda);
    const auto first_frame = renderer.render(movement.front());
    std::cout << "Renderer backend: " << (renderer.is_using_cuda() ? "CUDA" : "CPU") << "\n";

    const std::string lossless_path = (std::filesystem::path(args.output_dir) / "ground_truth_lossless.mkv").string();
    const std::string lossy_path = args.live_dash
                                     ? (std::filesystem::path(args.output_dir) / "stream.mpd").string()
                                     : (std::filesystem::path(args.output_dir) / "test_stream_lossy.mp4").string();
    const std::string metadata_path = (std::filesystem::path(args.output_dir) / "frame_metadata.csv").string();

    tigas::EncodeConfig lossless_cfg{"ffv1", args.fps, 0, true};
    tigas::EncodeConfig lossy_cfg{args.codec, args.fps, args.crf, false};
    lossy_cfg.live_dash = args.live_dash;
    lossy_cfg.dash_window_size = args.dash_window_size;

    std::unique_ptr<tigas::VideoEncoder> lossless_encoder;
    if (!args.live_dash) {
      lossless_encoder = std::make_unique<tigas::VideoEncoder>(lossless_path, lossless_cfg, first_frame.width, first_frame.height);
    }
    tigas::VideoEncoder lossy_encoder(lossy_path, lossy_cfg, first_frame.width, first_frame.height);
    std::vector<std::unique_ptr<tigas::VideoEncoder>> ladder_encoders;
    std::vector<std::string> ladder_paths;
    for (size_t idx = 0; idx < args.crf_ladder.size() && !args.live_dash; ++idx) {
      const int ladder_crf = args.crf_ladder[idx];
      if (ladder_crf == args.crf) {
        continue;
      }
      const std::string ladder_path = (std::filesystem::path(args.output_dir) / ("test_stream_lossy_p" + std::to_string(idx) + ".mp4")).string();
      tigas::EncodeConfig cfg{args.codec, args.fps, ladder_crf, false};
      ladder_encoders.emplace_back(std::make_unique<tigas::VideoEncoder>(ladder_path, cfg, first_frame.width, first_frame.height));
      ladder_paths.push_back(ladder_path);
    }
    tigas::MetadataWriter metadata_writer(metadata_path);
    const auto start_clock = std::chrono::steady_clock::now();

    for (const auto& sample : movement) {
      auto frame = renderer.render(sample);
      tigas::FrameMetadata metadata{sample.frame_id, sample.t_ms};

      if (lossless_encoder) {
        lossless_encoder->encode_frame(frame, metadata);
      }
      lossy_encoder.encode_frame(frame, metadata);
      for (auto& encoder : ladder_encoders) {
        encoder->encode_frame(frame, metadata);
      }
      metadata_writer.append(metadata);

      if (args.realtime) {
        const auto target = start_clock + std::chrono::milliseconds(sample.t_ms);
        const auto now = std::chrono::steady_clock::now();
        if (target > now) {
          std::this_thread::sleep_until(target);
        }
      }
    }

    if (lossless_encoder) {
      lossless_encoder->flush();
    }
    lossy_encoder.flush();
    for (auto& encoder : ladder_encoders) {
      encoder->flush();
    }

    std::cout << "Encoded " << movement.size() << " frames\n";
    if (lossless_encoder) {
      std::cout << "Lossless: " << lossless_path << "\n";
    }
    std::cout << (args.live_dash ? "LiveDASH: " : "Lossy: ") << lossy_path << "\n";
    for (const auto& path : ladder_paths) {
      std::cout << "LossyLadder: " << path << "\n";
    }
    std::cout << "Metadata: " << metadata_path << "\n";
    return 0;
  } catch (const std::exception& ex) {
    std::cerr << "[tigas_renderer_encoder] " << ex.what() << "\n";
    return 1;
  }
}
