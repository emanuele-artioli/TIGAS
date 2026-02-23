#include "tigas_encoder.hpp"

#include <cstring>
#include <string>
#include <stdexcept>
#include <vector>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/opt.h>
#include <libavutil/pixfmt.h>
#include <libavutil/rational.h>
#include <libswscale/swscale.h>
}

namespace tigas {

namespace {

AVCodecID codec_id_for_name(const std::string& codec_name, bool lossless) {
  if (lossless) {
    return AV_CODEC_ID_FFV1;
  }
  if (codec_name.find("hevc") != std::string::npos) {
    return AV_CODEC_ID_HEVC;
  }
  return AV_CODEC_ID_H264;
}

std::vector<uint8_t> build_sei_rbsp(const FrameMetadata& metadata) {
  const std::string sei_payload = "frame_id=" + std::to_string(metadata.frame_id) + ";timestamp_ms=" + std::to_string(metadata.timestamp_ms);
  const uint8_t sei_uuid[16] = {0x54, 0x49, 0x47, 0x41, 0x53, 0x2D, 0x53, 0x45, 0x49, 0x2D, 0x30, 0x30, 0x30, 0x30, 0x30, 0x31};

  std::vector<uint8_t> rbsp;
  rbsp.push_back(5);  // payload_type user_data_unregistered

  const int payload_size = 16 + static_cast<int>(sei_payload.size());
  int remaining = payload_size;
  while (remaining >= 255) {
    rbsp.push_back(0xFF);
    remaining -= 255;
  }
  rbsp.push_back(static_cast<uint8_t>(remaining));

  rbsp.insert(rbsp.end(), sei_uuid, sei_uuid + 16);
  rbsp.insert(rbsp.end(), sei_payload.begin(), sei_payload.end());
  rbsp.push_back(0x80);  // rbsp_trailing_bits

  return rbsp;
}

std::vector<uint8_t> build_sei_user_data_payload(const FrameMetadata& metadata) {
  const std::string sei_payload = "frame_id=" + std::to_string(metadata.frame_id) + ";timestamp_ms=" + std::to_string(metadata.timestamp_ms);
  const uint8_t sei_uuid[16] = {0x54, 0x49, 0x47, 0x41, 0x53, 0x2D, 0x53, 0x45, 0x49, 0x2D, 0x30, 0x30, 0x30, 0x30, 0x30, 0x31};

  std::vector<uint8_t> out;
  out.reserve(16 + sei_payload.size());
  out.insert(out.end(), sei_uuid, sei_uuid + 16);
  out.insert(out.end(), sei_payload.begin(), sei_payload.end());
  return out;
}

std::vector<uint8_t> build_sei_nal_payload(const FrameMetadata& metadata, AVCodecID codec_id) {
  const std::vector<uint8_t> rbsp = build_sei_rbsp(metadata);
  std::vector<uint8_t> nal;
  if (codec_id == AV_CODEC_ID_HEVC) {
    nal.push_back(0x4E);
    nal.push_back(0x01);
  } else {
    nal.push_back(0x06);
  }
  nal.insert(nal.end(), rbsp.begin(), rbsp.end());
  return nal;
}

std::vector<uint8_t> build_sei_nal_with_length(const FrameMetadata& metadata, AVCodecID codec_id) {
  const std::vector<uint8_t> nal = build_sei_nal_payload(metadata, codec_id);
  const uint32_t nal_len = static_cast<uint32_t>(nal.size());
  std::vector<uint8_t> out;
  out.reserve(4 + nal.size());
  out.push_back(static_cast<uint8_t>((nal_len >> 24) & 0xFF));
  out.push_back(static_cast<uint8_t>((nal_len >> 16) & 0xFF));
  out.push_back(static_cast<uint8_t>((nal_len >> 8) & 0xFF));
  out.push_back(static_cast<uint8_t>(nal_len & 0xFF));
  out.insert(out.end(), nal.begin(), nal.end());
  return out;
}

std::vector<uint8_t> build_sei_nal_annexb(const FrameMetadata& metadata, AVCodecID codec_id) {
  const std::vector<uint8_t> nal = build_sei_nal_payload(metadata, codec_id);
  std::vector<uint8_t> out;
  out.reserve(4 + nal.size());
  out.insert(out.end(), {0x00, 0x00, 0x00, 0x01});
  out.insert(out.end(), nal.begin(), nal.end());
  return out;
}

bool packet_is_annexb(const AVPacket* packet) {
  if (!packet || packet->size < 4 || !packet->data) {
    return false;
  }
  const uint8_t* d = packet->data;
  return (d[0] == 0x00 && d[1] == 0x00 && d[2] == 0x01) ||
         (packet->size >= 4 && d[0] == 0x00 && d[1] == 0x00 && d[2] == 0x00 && d[3] == 0x01);
}

void prepend_sei_packet(AVPacket* packet, const FrameMetadata& metadata, AVCodecID codec_id) {
  if (codec_id != AV_CODEC_ID_H264 && codec_id != AV_CODEC_ID_HEVC) {
    return;
  }
  const std::vector<uint8_t> sei = packet_is_annexb(packet)
                                     ? build_sei_nal_annexb(metadata, codec_id)
                                     : build_sei_nal_with_length(metadata, codec_id);

  AVPacket rewritten;
  av_init_packet(&rewritten);
  rewritten.data = nullptr;
  rewritten.size = 0;

  const int total = static_cast<int>(sei.size()) + packet->size;
  if (av_new_packet(&rewritten, total) < 0) {
    return;
  }

  std::memcpy(rewritten.data, sei.data(), sei.size());
  std::memcpy(rewritten.data + sei.size(), packet->data, packet->size);
  rewritten.pts = packet->pts;
  rewritten.dts = packet->dts;
  rewritten.duration = packet->duration;
  rewritten.pos = packet->pos;
  rewritten.flags = packet->flags;
  rewritten.stream_index = packet->stream_index;

  av_packet_unref(packet);
  av_packet_move_ref(packet, &rewritten);
}

bool attach_sei_side_data(AVFrame* frame, const FrameMetadata& metadata, AVCodecID codec_id) {
  if (!frame || (codec_id != AV_CODEC_ID_H264 && codec_id != AV_CODEC_ID_HEVC)) {
    return false;
  }
  const std::vector<uint8_t> payload = build_sei_user_data_payload(metadata);
  AVFrameSideData* side_data = av_frame_new_side_data(frame, AV_FRAME_DATA_SEI_UNREGISTERED, static_cast<size_t>(payload.size()));
  if (!side_data || !side_data->data || side_data->size != static_cast<int>(payload.size())) {
    return false;
  }
  std::memcpy(side_data->data, payload.data(), payload.size());
  return true;
}

}

VideoEncoder::VideoEncoder(const std::string& output_path, const EncodeConfig& config, int width, int height)
    : format_context_(nullptr),
      codec_context_(nullptr),
      stream_(nullptr),
      frame_(nullptr),
      sws_context_(nullptr),
      next_pts_(0) {
  init(output_path, config, width, height);
}

void VideoEncoder::init(const std::string& output_path, const EncodeConfig& config, int width, int height) {
  AVFormatContext* format_ctx = nullptr;
  const char* format_name = config.live_dash ? "dash" : nullptr;
  if (avformat_alloc_output_context2(&format_ctx, nullptr, format_name, output_path.c_str()) < 0) {
    throw std::runtime_error("Failed to allocate output format context");
  }
  format_context_ = format_ctx;

  const AVCodec* codec = config.lossless ? avcodec_find_encoder(AV_CODEC_ID_FFV1) : avcodec_find_encoder_by_name(config.codec.c_str());
  if (!codec) {
    codec = avcodec_find_encoder(codec_id_for_name(config.codec, config.lossless));
  }
  if (!codec) {
    throw std::runtime_error("Unable to find encoder: " + config.codec);
  }

  AVStream* stream = avformat_new_stream(format_ctx, codec);
  if (!stream) {
    throw std::runtime_error("Unable to create stream");
  }
  stream_ = stream;

  AVCodecContext* codec_ctx = avcodec_alloc_context3(codec);
  if (!codec_ctx) {
    throw std::runtime_error("Unable to allocate codec context");
  }
  codec_context_ = codec_ctx;

  codec_ctx->codec_id = codec->id;
  codec_ctx->codec_type = AVMEDIA_TYPE_VIDEO;
  codec_ctx->width = width;
  codec_ctx->height = height;
  codec_ctx->time_base = AVRational{1, config.fps};
  codec_ctx->framerate = AVRational{config.fps, 1};
  codec_ctx->gop_size = 1;
  codec_ctx->max_b_frames = 0;
  const std::string resolved_codec_name = codec->name ? std::string(codec->name) : std::string();
  const bool is_nvenc = resolved_codec_name.find("nvenc") != std::string::npos;
  codec_ctx->pix_fmt = config.lossless ? AV_PIX_FMT_YUV420P : (is_nvenc ? AV_PIX_FMT_NV12 : AV_PIX_FMT_YUV420P);

  if (!config.lossless) {
    if (is_nvenc) {
      av_opt_set(codec_ctx->priv_data, "preset", "p2", 0);
    } else {
      av_opt_set(codec_ctx->priv_data, "preset", "veryfast", 0);
      av_opt_set_int(codec_ctx->priv_data, "udu_sei", 1, 0);
    }
    av_opt_set(codec_ctx->priv_data, "tune", "zerolatency", 0);
    av_opt_set_int(codec_ctx->priv_data, "bf", 0, 0);
    av_opt_set_int(codec_ctx->priv_data, "g", 1, 0);
    if (is_nvenc) {
      av_opt_set_int(codec_ctx->priv_data, "cq", config.crf, 0);
    } else {
      av_opt_set_int(codec_ctx->priv_data, "crf", config.crf, 0);
    }
  }

  if (format_ctx->oformat->flags & AVFMT_GLOBALHEADER) {
    codec_ctx->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
  }

  if (avcodec_open2(codec_ctx, codec, nullptr) < 0) {
    throw std::runtime_error("Unable to open codec");
  }

  if (avcodec_parameters_from_context(stream->codecpar, codec_ctx) < 0) {
    throw std::runtime_error("Unable to copy codec parameters");
  }
  stream->time_base = codec_ctx->time_base;

  if (!(format_ctx->oformat->flags & AVFMT_NOFILE)) {
    if (avio_open(&format_ctx->pb, output_path.c_str(), AVIO_FLAG_WRITE) < 0) {
      throw std::runtime_error("Unable to open output file: " + output_path);
    }
  }

  AVDictionary* mux_opts = nullptr;
  if (config.live_dash) {
    av_dict_set(&mux_opts, "streaming", "1", 0);
    av_dict_set(&mux_opts, "ldash", config.dash_archive_mode ? "0" : "1", 0);
    av_dict_set(&mux_opts, "window_size", std::to_string(config.dash_window_size).c_str(), 0);
    av_dict_set(&mux_opts, "extra_window_size", config.dash_archive_mode ? "0" : "0", 0);
    av_dict_set(&mux_opts, "remove_at_exit", "0", 0);
    av_dict_set(&mux_opts, "use_timeline", "1", 0);
    av_dict_set(&mux_opts, "use_template", "1", 0);
    av_dict_set(&mux_opts, "seg_duration", std::to_string(1.0 / static_cast<double>(config.fps)).c_str(), 0);
    av_dict_set(&mux_opts, "init_seg_name", config.dash_init_seg_name.c_str(), 0);
    av_dict_set(&mux_opts, "media_seg_name", config.dash_media_seg_name.c_str(), 0);

    if (config.dash_archive_mode) {
      av_dict_set(&mux_opts, "window_size", "0", 0);
    }
  }

  if (avformat_write_header(format_ctx, mux_opts ? &mux_opts : nullptr) < 0) {
    if (mux_opts) {
      av_dict_free(&mux_opts);
    }
    throw std::runtime_error("Unable to write output header");
  }
  if (mux_opts) {
    av_dict_free(&mux_opts);
  }

  AVFrame* frame = av_frame_alloc();
  if (!frame) {
    throw std::runtime_error("Unable to allocate frame");
  }
  frame_ = frame;
  frame->format = codec_ctx->pix_fmt;
  frame->width = width;
  frame->height = height;
  if (av_frame_get_buffer(frame, 32) < 0) {
    throw std::runtime_error("Unable to allocate frame buffer");
  }

  sws_context_ = sws_getContext(
      width,
      height,
      AV_PIX_FMT_RGB24,
      width,
      height,
      codec_ctx->pix_fmt,
      SWS_BICUBIC,
      nullptr,
      nullptr,
      nullptr);
  if (!sws_context_) {
    throw std::runtime_error("Unable to initialize swscale context");
  }
}

VideoEncoder::~VideoEncoder() {
  try {
    flush();
  } catch (...) {
  }

  if (frame_) {
    AVFrame* frame = static_cast<AVFrame*>(frame_);
    av_frame_free(&frame);
  }
  if (codec_context_) {
    AVCodecContext* codec_ctx = static_cast<AVCodecContext*>(codec_context_);
    avcodec_free_context(&codec_ctx);
  }
  if (format_context_) {
    AVFormatContext* format_ctx = static_cast<AVFormatContext*>(format_context_);
    if (!(format_ctx->oformat->flags & AVFMT_NOFILE) && format_ctx->pb) {
      avio_closep(&format_ctx->pb);
    }
    avformat_free_context(format_ctx);
  }
  if (sws_context_) {
    sws_freeContext(static_cast<SwsContext*>(sws_context_));
  }
}

void VideoEncoder::encode_frame(const RGBFrame& frame, const FrameMetadata& metadata) {
  AVCodecContext* codec_ctx = static_cast<AVCodecContext*>(codec_context_);
  AVFrame* av_frame = static_cast<AVFrame*>(frame_);
  SwsContext* sws_ctx = static_cast<SwsContext*>(sws_context_);
  AVStream* stream = static_cast<AVStream*>(stream_);

  if (av_frame_make_writable(av_frame) < 0) {
    throw std::runtime_error("Frame buffer not writable");
  }

  const uint8_t* src_slices[1] = {frame.data.data()};
  int src_stride[1] = {frame.width * 3};
  sws_scale(sws_ctx, src_slices, src_stride, 0, frame.height, av_frame->data, av_frame->linesize);

  av_frame->pts = next_pts_++;

  av_frame_remove_side_data(av_frame, AV_FRAME_DATA_SEI_UNREGISTERED);
  const bool side_data_attached = attach_sei_side_data(av_frame, metadata, codec_ctx->codec_id);

  if (avcodec_send_frame(codec_ctx, av_frame) < 0) {
    throw std::runtime_error("Unable to send frame to codec");
  }

  AVPacket packet;
  av_init_packet(&packet);
  packet.data = nullptr;
  packet.size = 0;

  while (true) {
    const int receive_result = avcodec_receive_packet(codec_ctx, &packet);
    if (receive_result == AVERROR(EAGAIN) || receive_result == AVERROR_EOF) {
      break;
    }
    if (receive_result < 0) {
      throw std::runtime_error("Unable to receive packet from codec");
    }

    packet.stream_index = stream->index;
    if (!side_data_attached) {
      prepend_sei_packet(&packet, metadata, codec_ctx->codec_id);
    }
    av_packet_rescale_ts(&packet, codec_ctx->time_base, stream->time_base);

    AVFormatContext* format_ctx = static_cast<AVFormatContext*>(format_context_);
    if (av_interleaved_write_frame(format_ctx, &packet) < 0) {
      av_packet_unref(&packet);
      throw std::runtime_error("Unable to write encoded packet");
    }
    av_packet_unref(&packet);
  }
}

void VideoEncoder::flush() {
  AVCodecContext* codec_ctx = static_cast<AVCodecContext*>(codec_context_);
  AVFormatContext* format_ctx = static_cast<AVFormatContext*>(format_context_);
  AVStream* stream = static_cast<AVStream*>(stream_);

  if (!codec_ctx || !format_ctx) {
    return;
  }

  avcodec_send_frame(codec_ctx, nullptr);

  AVPacket packet;
  av_init_packet(&packet);
  packet.data = nullptr;
  packet.size = 0;

  while (true) {
    const int receive_result = avcodec_receive_packet(codec_ctx, &packet);
    if (receive_result == AVERROR(EAGAIN) || receive_result == AVERROR_EOF) {
      break;
    }
    if (receive_result < 0) {
      break;
    }
    packet.stream_index = stream->index;
    av_packet_rescale_ts(&packet, codec_ctx->time_base, stream->time_base);
    av_interleaved_write_frame(format_ctx, &packet);
    av_packet_unref(&packet);
  }

  av_write_trailer(format_ctx);

  codec_context_ = nullptr;
  format_context_ = nullptr;
}

MetadataWriter::MetadataWriter(const std::string& output_path) : stream_(output_path) {
  if (!stream_.is_open()) {
    throw std::runtime_error("Unable to open metadata output: " + output_path);
  }
}

MetadataWriter::~MetadataWriter() {
  stream_.flush();
}

void MetadataWriter::append(const FrameMetadata& metadata) {
  stream_ << metadata.frame_id << "," << metadata.timestamp_ms << "\n";
}

}  // namespace tigas
