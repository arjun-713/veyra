add_executable(veyra_benchmark main.cpp)
target_compile_features(veyra_benchmark PRIVATE cxx_std_20)
target_link_libraries(veyra_benchmark PRIVATE veyra_map veyra_metrics veyra_policy)
target_include_directories(veyra_benchmark PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_options(veyra_benchmark PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(veyra_benchmark PRIVATE VEYRA_SOURCE_DIR="${PROJECT_SOURCE_DIR}")

if(BUILD_TESTING)
  find_package(Python3 COMPONENTS Interpreter REQUIRED)
  add_test(
    NAME benchmark_runtime
    COMMAND ${Python3_EXECUTABLE} -m unittest benchmarks.test_runtime -v
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
  )
  set_tests_properties(
    benchmark_runtime
    PROPERTIES ENVIRONMENT "VEYRA_BENCHMARK_BINARY=$<TARGET_FILE:veyra_benchmark>"
  )
endif()
