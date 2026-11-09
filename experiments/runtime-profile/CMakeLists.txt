cmake_minimum_required(VERSION 3.25)
project(runtime-profile LANGUAGES CXX)
find_package(Qt6 6.11 REQUIRED COMPONENTS Core Gui)
# Private executable only: no helper, decoder, install rules or public API.
add_executable(runtime-profile harness.cpp ../../src/isolated/runtime.cpp
  ../../src/isolated/protocol.cpp ../../src/isolated/cleanup.cpp)
target_include_directories(runtime-profile PRIVATE ../../include ../../src/isolated)
target_compile_features(runtime-profile PRIVATE cxx_std_23)
target_compile_options(runtime-profile PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(runtime-profile PRIVATE Qt6::Core Qt6::Gui)
