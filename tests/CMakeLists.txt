# Group by subsystem; retain each CTest name and isolated invocation.
# Every target keeps assertions enabled, including Release builds.
function(veyra_test_suite target source)
  add_executable(${target} ${source})
  target_link_libraries(${target} PRIVATE veyra_map veyra_policy veyra_metrics)
  target_include_directories(${target} PRIVATE ${PROJECT_SOURCE_DIR}/include)
  target_compile_features(${target} PRIVATE cxx_std_20)
  target_compile_definitions(${target} PRIVATE VEYRA_SOURCE_DIR="${PROJECT_SOURCE_DIR}")
  veyra_enable_warnings(${target})
  veyra_enable_assertions(${target})
  foreach(suite IN LISTS ARGN)
    add_test(NAME ${suite} COMMAND ${target} ${suite})
  endforeach()
endfunction()

veyra_test_suite(test_map_topology test_map_topology.cpp
  index_alignment parent_child_exclusivity rolling_window)

veyra_test_suite(test_map_storage test_map_storage.cpp
  map_engine memory_accounting)

veyra_test_suite(test_map_conservation test_map_conservation.cpp
  split_merge point_conservation)

veyra_test_suite(test_map_properties test_map_properties.cpp
  randomized_map_invariants map_public_properties map_hardening_stress)

veyra_test_suite(test_resolution_policy test_resolution_policy.cpp
  policy policy_adapter near_field_protection resolution_pass)

veyra_test_suite(test_map_terrain test_map_terrain.cpp
  layered_terrain occupancy_uncertainty)

veyra_test_suite(test_visibility_clearing test_visibility_clearing.cpp
  depth_image_clearing persistent_clearing batch_clearing)

veyra_test_suite(test_ghost_prevention test_ghost_prevention.cpp
  ghost_retention clearing_static_erosion)

add_executable(test_boundary_neighbors test_boundary_neighbors.cpp)
target_link_libraries(test_boundary_neighbors PRIVATE veyra_map)
target_compile_features(test_boundary_neighbors PRIVATE cxx_std_20)
veyra_enable_warnings(test_boundary_neighbors)
veyra_enable_assertions(test_boundary_neighbors)
add_test(NAME boundary_neighbors COMMAND test_boundary_neighbors)

# The TileGrid snapshot also replaces global new/delete and uses its own
# snapshot API, so retain its independent translation unit and allocator.
add_executable(test_snapshot test_snapshot.cpp)
target_link_libraries(test_snapshot PRIVATE veyra_map)
target_compile_features(test_snapshot PRIVATE cxx_std_20)
veyra_enable_warnings(test_snapshot)
veyra_enable_assertions(test_snapshot)
add_test(NAME snapshot COMMAND test_snapshot)

add_executable(policy_microbenchmark policy_microbenchmark.cpp)
target_link_libraries(policy_microbenchmark PRIVATE veyra_policy)
target_compile_features(policy_microbenchmark PRIVATE cxx_std_20)
veyra_enable_warnings(policy_microbenchmark)
veyra_enable_assertions(policy_microbenchmark)

find_package(Python3 COMPONENTS Interpreter REQUIRED)
add_test(
  NAME python_unittest
  COMMAND ${Python3_EXECUTABLE} -m unittest discover -s tests -p "test_*.py" -v
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
)
if(TARGET veyra_benchmark)
  set_tests_properties(python_unittest PROPERTIES
    ENVIRONMENT "VEYRA_BENCHMARK_BINARY=$<TARGET_FILE:veyra_benchmark>")
endif()
set_tests_properties(python_unittest map_hardening_stress PROPERTIES TIMEOUT 600)
# This suite asserts wall-clock budgets: avoid competing with stress tests.
set_tests_properties(map_engine PROPERTIES RUN_SERIAL TRUE)
