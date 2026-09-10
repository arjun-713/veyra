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
