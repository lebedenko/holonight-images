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

if(HOLONIGHT_IMAGES_ISOLATED)
  add_executable(isolated-transaction-test isolated_transaction_test.cpp)
  target_link_libraries(isolated-transaction-test PRIVATE HolonightImages::Isolated GTest::gtest)
  target_compile_definitions(isolated-transaction-test PRIVATE HELPER_PATH="$<TARGET_FILE:holonight-images-helper>")
  add_dependencies(isolated-transaction-test holonight-images-helper)
  add_test(NAME isolated-transaction COMMAND isolated-transaction-test --gtest_filter=TransactionHelper.*)
  add_executable(isolated-cleanup-test isolated_cleanup_test.cpp)
  target_link_libraries(isolated-cleanup-test PRIVATE HolonightImages::Isolated GTest::gtest_main)
  add_test(NAME isolated-cleanup COMMAND isolated-cleanup-test)
  add_executable(isolated-capture-test isolated_capture_test.cpp)
  target_link_libraries(isolated-capture-test PRIVATE HolonightImages::Isolated)
  add_test(NAME isolated-capture COMMAND isolated-capture-test)
  add_executable(isolated-protocol-test isolated_protocol_test.cpp)
  target_link_libraries(isolated-protocol-test PRIVATE HolonightImages::Isolated GTest::gtest_main)
  add_test(NAME isolated-protocol COMMAND isolated-protocol-test)
  if(HOLONIGHT_IMAGES_RUNTIME_BUNDLE)
    add_test(NAME isolated-installed-package COMMAND ${CMAKE_COMMAND}
      -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/isolated-consumer
      -DPROVIDER_BUILD=${PROJECT_BINARY_DIR} -DTEST_ROOT=${CMAKE_CURRENT_BINARY_DIR}/isolated-package-test
      -DFIXTURES=${CMAKE_CURRENT_BINARY_DIR}/fixtures -DRUN_RUNTIME=${HOLONIGHT_IMAGES_RUNTIME_TESTING} -P ${CMAKE_CURRENT_SOURCE_DIR}/isolated-package-test.cmake)
  endif()
endif()
if(HOLONIGHT_IMAGES_ISOLATED)
  add_executable(isolated-fault-helper isolated_fault_helper.cpp ../src/isolated/protocol.cpp)
  target_link_libraries(isolated-fault-helper PRIVATE HolonightImages::Images)
  add_executable(isolated-runtime-test isolated_runtime_test.cpp)
  target_link_libraries(isolated-runtime-test PRIVATE HolonightImages::Isolated)
  set(HOLONIGHT_IMAGES_FAULT_RUNTIME "" CACHE PATH "Explicitly prepared test-only fault runtime")
  if(HOLONIGHT_IMAGES_RUNTIME_TESTING AND HOLONIGHT_IMAGES_FAULT_RUNTIME AND HOLONIGHT_IMAGES_RUNTIME_BUNDLE)
    add_test(NAME isolated-source-transaction COMMAND isolated-transaction-test --gtest_filter=SourceTransaction.* --gtest_break_on_failure)
    set_tests_properties(isolated-source-transaction PROPERTIES ENVIRONMENT
      "HN_TRANSACTION_RUNTIME=${HOLONIGHT_IMAGES_RUNTIME_BUNDLE};HN_TRANSACTION_FAULT_RUNTIME=${HOLONIGHT_IMAGES_FAULT_RUNTIME}")
    add_test(NAME isolated-namespace-denied COMMAND /usr/bin/bwrap --unshare-user --disable-userns
      --ro-bind / / --proc /proc --dev-bind /dev /dev --setenv HN_TEST_NAMESPACE_DENIED 1
      $<TARGET_FILE:isolated-runtime-test> ${HOLONIGHT_IMAGES_RUNTIME_BUNDLE} ${HOLONIGHT_IMAGES_FAULT_RUNTIME})
    add_test(NAME isolated-runtime-faults COMMAND isolated-runtime-test
      ${HOLONIGHT_IMAGES_RUNTIME_BUNDLE} ${HOLONIGHT_IMAGES_FAULT_RUNTIME})
  endif()
endif()
