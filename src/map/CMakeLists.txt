add_library(veyra_map STATIC map.cpp tile_grid.cpp fusion.cpp split_merge.cpp)
target_include_directories(veyra_map PUBLIC ${PROJECT_SOURCE_DIR}/include)
target_compile_features(veyra_map PUBLIC cxx_std_20)
