cmake_minimum_required(VERSION 3.25)
project(hash-performance LANGUAGES CXX)
find_package(Qt6 6.11 REQUIRED COMPONENTS Core Gui)
add_executable(hash-performance harness.cpp ../../src/isolated/runtime.cpp
  ../../src/isolated/protocol.cpp ../../src/isolated/cleanup.cpp)
target_include_directories(hash-performance PRIVATE ../../include ../../src/isolated)
target_compile_features(hash-performance PRIVATE cxx_std_23)
target_compile_options(hash-performance PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(hash-performance PRIVATE Qt6::Core Qt6::Gui)
