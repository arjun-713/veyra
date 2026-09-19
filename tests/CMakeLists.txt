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

add_executable(test_split_merge test_split_merge.cpp)
target_include_directories(test_split_merge PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_split_merge PRIVATE cxx_std_20)
target_link_libraries(test_split_merge PRIVATE veyra_map)
add_test(NAME split_merge COMMAND test_split_merge)

add_executable(test_memory_accounting test_memory_accounting.cpp)
target_include_directories(test_memory_accounting PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_memory_accounting PRIVATE cxx_std_20)
target_link_libraries(test_memory_accounting PRIVATE veyra_map)
add_test(NAME memory_accounting COMMAND test_memory_accounting)

add_executable(test_point_conservation test_point_conservation.cpp)
target_include_directories(test_point_conservation PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_point_conservation PRIVATE cxx_std_20)
target_link_libraries(test_point_conservation PRIVATE veyra_map)
add_test(NAME point_conservation COMMAND test_point_conservation)

add_executable(test_rolling_window test_rolling_window.cpp)
target_include_directories(test_rolling_window PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_rolling_window PRIVATE cxx_std_20)
target_link_libraries(test_rolling_window PRIVATE veyra_map)
add_test(NAME rolling_window COMMAND test_rolling_window)

add_executable(test_parent_child_exclusivity test_parent_child_exclusivity.cpp)
target_include_directories(test_parent_child_exclusivity PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_parent_child_exclusivity PRIVATE cxx_std_20)
target_link_libraries(test_parent_child_exclusivity PRIVATE veyra_map)
add_test(NAME parent_child_exclusivity COMMAND test_parent_child_exclusivity)

add_executable(test_boundary_neighbors test_boundary_neighbors.cpp)
target_include_directories(test_boundary_neighbors PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_boundary_neighbors PRIVATE cxx_std_20)
target_link_libraries(test_boundary_neighbors PRIVATE veyra_map)
add_test(NAME boundary_neighbors COMMAND test_boundary_neighbors)

add_executable(test_near_field_protection test_near_field_protection.cpp)
target_include_directories(test_near_field_protection PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_near_field_protection PRIVATE cxx_std_20)
target_link_libraries(test_near_field_protection PRIVATE veyra_map veyra_policy)
add_test(NAME near_field_protection COMMAND test_near_field_protection)

add_executable(test_resolution_pass test_resolution_pass.cpp)
target_include_directories(test_resolution_pass PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_resolution_pass PRIVATE cxx_std_20)
target_link_libraries(test_resolution_pass PRIVATE veyra_map veyra_policy)
add_test(NAME resolution_pass COMMAND test_resolution_pass)

add_executable(test_snapshot test_snapshot.cpp)
target_include_directories(test_snapshot PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_snapshot PRIVATE cxx_std_20)
target_link_libraries(test_snapshot PRIVATE veyra_map)
add_test(NAME snapshot COMMAND test_snapshot)

add_executable(test_policy_adapter test_policy_adapter.cpp)
target_link_libraries(test_policy_adapter PRIVATE veyra_map veyra_policy veyra_metrics)
target_compile_definitions(test_policy_adapter PRIVATE VEYRA_SOURCE_DIR="${PROJECT_SOURCE_DIR}")
target_compile_options(test_policy_adapter PRIVATE -Wall -Wextra -Wpedantic -UNDEBUG)
add_test(NAME policy_adapter COMMAND test_policy_adapter)

add_executable(test_layered_terrain test_layered_terrain.cpp)
target_include_directories(test_layered_terrain PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_layered_terrain PRIVATE cxx_std_20)
target_compile_options(test_layered_terrain PRIVATE -Wall -Wextra -Wpedantic -UNDEBUG)
target_link_libraries(test_layered_terrain PRIVATE veyra_map)
add_test(NAME layered_terrain COMMAND test_layered_terrain)

add_executable(test_occupancy_uncertainty test_occupancy_uncertainty.cpp)
target_include_directories(test_occupancy_uncertainty PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_occupancy_uncertainty PRIVATE cxx_std_20)
target_compile_options(test_occupancy_uncertainty PRIVATE -Wall -Wextra -Wpedantic -UNDEBUG)
target_link_libraries(test_occupancy_uncertainty PRIVATE veyra_map)
add_test(NAME occupancy_uncertainty COMMAND test_occupancy_uncertainty)
