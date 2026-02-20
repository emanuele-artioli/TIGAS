#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>

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
};

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

    tigas::GaussianRenderer renderer(args.ply_path);
    const auto first_frame = renderer.render(movement.front());

    const std::string lossless_path = (std::filesystem::path(args.output_dir) / "ground_truth_lossless.mkv").string();
    const std::string lossy_path = (std::filesystem::path(args.output_dir) / "test_stream_lossy.mp4").string();
    const std::string metadata_path = (std::filesystem::path(args.output_dir) / "frame_metadata.csv").string();

    tigas::EncodeConfig lossless_cfg{"ffv1", args.fps, 0, true};
    tigas::EncodeConfig lossy_cfg{args.codec, args.fps, args.crf, false};

    tigas::VideoEncoder lossless_encoder(lossless_path, lossless_cfg, first_frame.width, first_frame.height);
    tigas::VideoEncoder lossy_encoder(lossy_path, lossy_cfg, first_frame.width, first_frame.height);
    tigas::MetadataWriter metadata_writer(metadata_path);

    for (const auto& sample : movement) {
      auto frame = renderer.render(sample);
      tigas::FrameMetadata metadata{sample.frame_id, sample.t_ms};

      lossless_encoder.encode_frame(frame, metadata);
      lossy_encoder.encode_frame(frame, metadata);
      metadata_writer.append(metadata);
    }

    lossless_encoder.flush();
    lossy_encoder.flush();

    std::cout << "Encoded " << movement.size() << " frames\n";
    std::cout << "Lossless: " << lossless_path << "\n";
    std::cout << "Lossy: " << lossy_path << "\n";
    std::cout << "Metadata: " << metadata_path << "\n";
    return 0;
  } catch (const std::exception& ex) {
    std::cerr << "[tigas_renderer_encoder] " << ex.what() << "\n";
    return 1;
  }
}
