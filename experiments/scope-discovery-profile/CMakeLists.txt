cmake_minimum_required(VERSION 3.25)
project(scope-discovery-profile LANGUAGES CXX)
find_package(Qt6 6.11 REQUIRED COMPONENTS Core Gui Svg)
set(HOLONIGHT_IMAGES_ISOLATED ON CACHE BOOL "" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory(../.. images)
add_executable(scope-discovery-profile harness.cpp)
target_include_directories(scope-discovery-profile PRIVATE ../../src/isolated)
target_link_libraries(scope-discovery-profile PRIVATE HolonightImages::Isolated)
target_compile_options(scope-discovery-profile PRIVATE -Wall -Wextra -Wpedantic)

# The helper embeds runtime.cpp for validation; never vary its unused parent observer.
target_compile_definitions(holonight-images-helper PRIVATE PROFILE_HELPER_BUILD=1)
