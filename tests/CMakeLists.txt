find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_executable(images-test image_test.cpp svg_test.cpp)
target_link_libraries(images-test PRIVATE HolonightImages::Images GTest::gtest)
target_compile_definitions(images-test PRIVATE FIXTURE_DIR="${CMAKE_CURRENT_BINARY_DIR}/fixtures")
add_custom_target(fixtures COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/format-fixtures.py ${CMAKE_CURRENT_BINARY_DIR}/fixtures)
add_dependencies(images-test fixtures)
add_test(NAME images COMMAND images-test)
add_test(NAME installed-package COMMAND ${CMAKE_COMMAND} -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/package-consumer -DPROVIDER_BUILD=${PROJECT_BINARY_DIR} -DTEST_ROOT=${CMAKE_CURRENT_BINARY_DIR}/package-test -P ${CMAKE_CURRENT_SOURCE_DIR}/package-test.cmake)

# A separate process prevents raster tests from caching image-reader plugins first.
add_executable(svg-without-image-plugin-test svg_without_image_plugin_test.cpp)
target_link_libraries(svg-without-image-plugin-test PRIVATE HolonightImages::Images)
add_test(NAME svg-without-image-plugin COMMAND svg-without-image-plugin-test)
