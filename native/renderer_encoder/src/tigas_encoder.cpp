#include "tigas_encoder.hpp"

#include <cstring>
#include <string>
#include <stdexcept>

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
  if (avformat_alloc_output_context2(&format_ctx, nullptr, nullptr, output_path.c_str()) < 0) {
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
  const bool is_nvenc = config.codec.find("nvenc") != std::string::npos;
  codec_ctx->pix_fmt = config.lossless ? AV_PIX_FMT_YUV420P : (is_nvenc ? AV_PIX_FMT_NV12 : AV_PIX_FMT_YUV420P);

  if (!config.lossless) {
    if (is_nvenc) {
      av_opt_set(codec_ctx->priv_data, "preset", "p2", 0);
    } else {
      av_opt_set(codec_ctx->priv_data, "preset", "veryfast", 0);
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

  if (avformat_write_header(format_ctx, nullptr) < 0) {
    throw std::runtime_error("Unable to write output header");
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
  const std::string sei_payload = "frame_id=" + std::to_string(metadata.frame_id) + ";timestamp_ms=" + std::to_string(metadata.timestamp_ms);
  uint8_t sei_uuid[16] = {0x54, 0x49, 0x47, 0x41, 0x53, 0x2D, 0x53, 0x45, 0x49, 0x2D, 0x30, 0x30, 0x30, 0x30, 0x30, 0x31};
  AVFrameSideData* side_data = av_frame_new_side_data(av_frame, AV_FRAME_DATA_SEI_UNREGISTERED, static_cast<size_t>(16 + sei_payload.size()));
  if (side_data && side_data->data) {
    std::memcpy(side_data->data, sei_uuid, 16);
    std::memcpy(side_data->data + 16, sei_payload.data(), sei_payload.size());
  }

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
