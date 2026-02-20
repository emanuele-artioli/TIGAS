cmake_minimum_required(VERSION 3.20)
project(tigas_renderer_encoder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(TIGAS_USE_CUDA "Enable CUDA acceleration" ON)

find_package(PkgConfig REQUIRED)
pkg_check_modules(AVFORMAT REQUIRED libavformat)
pkg_check_modules(AVCODEC REQUIRED libavcodec)
pkg_check_modules(AVUTIL REQUIRED libavutil)
pkg_check_modules(SWSCALE REQUIRED libswscale)

find_package(nlohmann_json REQUIRED)

add_executable(tigas_renderer_encoder
  src/main.cpp
  src/tigas_trace.cpp
  src/tigas_renderer.cpp
  src/tigas_encoder.cpp
)

target_include_directories(tigas_renderer_encoder PRIVATE
  include
  ${AVFORMAT_INCLUDE_DIRS}
  ${AVCODEC_INCLUDE_DIRS}
  ${AVUTIL_INCLUDE_DIRS}
  ${SWSCALE_INCLUDE_DIRS}
)

target_link_directories(tigas_renderer_encoder PRIVATE
  ${AVFORMAT_LIBRARY_DIRS}
  ${AVCODEC_LIBRARY_DIRS}
  ${AVUTIL_LIBRARY_DIRS}
  ${SWSCALE_LIBRARY_DIRS}
)

target_link_libraries(tigas_renderer_encoder PRIVATE
  nlohmann_json::nlohmann_json
  ${AVFORMAT_LIBRARIES}
  ${AVCODEC_LIBRARIES}
  ${AVUTIL_LIBRARIES}
  ${SWSCALE_LIBRARIES}
)

target_compile_options(tigas_renderer_encoder PRIVATE
  ${AVFORMAT_CFLAGS_OTHER}
  ${AVCODEC_CFLAGS_OTHER}
  ${AVUTIL_CFLAGS_OTHER}
  ${SWSCALE_CFLAGS_OTHER}
)

if(TIGAS_USE_CUDA)
  target_compile_definitions(tigas_renderer_encoder PRIVATE TIGAS_USE_CUDA=1)
endif()
