#pragma once

#include <cstdint>
#include <fstream>
#include <string>

#include "tigas_renderer.hpp"

namespace tigas {

struct EncodeConfig {
  std::string codec;
  int fps;
  int crf;
  bool lossless;
};

struct FrameMetadata {
  int frame_id;
  int64_t timestamp_ms;
};

class VideoEncoder {
 public:
  VideoEncoder(const std::string& output_path, const EncodeConfig& config, int width, int height);
  ~VideoEncoder();

  void encode_frame(const RGBFrame& frame, const FrameMetadata& metadata);
  void flush();

 private:
  void init(const std::string& output_path, const EncodeConfig& config, int width, int height);
  void write_packet(void* packet);

  void* format_context_;
  void* codec_context_;
  void* stream_;
  void* frame_;
  void* sws_context_;
  int64_t next_pts_;
};

class MetadataWriter {
 public:
  explicit MetadataWriter(const std::string& output_path);
  ~MetadataWriter();

  void append(const FrameMetadata& metadata);

 private:
  std::ofstream stream_;
};

}  // namespace tigas
