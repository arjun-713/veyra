# Samay: invariant tests live here. Start with test_index_alignment,
# then add point_conservation, split_merge, parent_child_exclusivity,
# boundary_neighbors, rolling_window, memory_accounting, near_field_protection.
# See docs/map-correctness.md
add_executable(test_index_alignment test_index_alignment.cpp)
target_include_directories(test_index_alignment PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_index_alignment PRIVATE cxx_std_20)
target_compile_options(test_index_alignment PRIVATE -UNDEBUG)
add_test(NAME index_alignment COMMAND test_index_alignment)

add_executable(test_policy test_policy.cpp)
target_link_libraries(test_policy PRIVATE veyra_policy)
target_include_directories(test_policy PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_policy PRIVATE cxx_std_20)
target_compile_options(test_policy PRIVATE -Wall -Wextra -Wpedantic -UNDEBUG)
target_compile_definitions(test_policy PRIVATE VEYRA_SOURCE_DIR="${PROJECT_SOURCE_DIR}")
add_test(NAME policy COMMAND test_policy)

add_executable(policy_microbenchmark policy_microbenchmark.cpp)
target_link_libraries(policy_microbenchmark PRIVATE veyra_policy)
target_include_directories(policy_microbenchmark PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(policy_microbenchmark PRIVATE cxx_std_20)
target_compile_options(policy_microbenchmark PRIVATE -Wall -Wextra -Wpedantic -UNDEBUG)

add_executable(test_map_engine test_map_engine.cpp)
target_link_libraries(test_map_engine PRIVATE veyra_map)
target_include_directories(test_map_engine PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_map_engine PRIVATE cxx_std_20)
target_compile_options(test_map_engine PRIVATE -UNDEBUG)
add_test(NAME map_engine COMMAND test_map_engine)

find_package(Python3 COMPONENTS Interpreter REQUIRED)
add_test(
  NAME python_unittest
  COMMAND ${Python3_EXECUTABLE} -m unittest discover -s tests -p "test_*.py" -v
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
)
