# Samay: invariant tests live here. Start with test_index_alignment,
# then add point_conservation, split_merge, parent_child_exclusivity,
# boundary_neighbors, rolling_window, memory_accounting, near_field_protection.
# See docs/map-correctness.md
add_executable(test_index_alignment test_index_alignment.cpp)
target_include_directories(test_index_alignment PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_index_alignment PRIVATE cxx_std_20)
add_test(NAME index_alignment COMMAND test_index_alignment)

add_executable(test_split_merge test_split_merge.cpp)
target_include_directories(test_split_merge PRIVATE ${PROJECT_SOURCE_DIR}/include)
target_compile_features(test_split_merge PRIVATE cxx_std_20)
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
