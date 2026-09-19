add_library(veyra_map STATIC map.cpp terrain_query.cpp sensor_model.cpp tile_grid.cpp fusion.cpp split_merge.cpp resolution_pass.cpp snapshot.cpp)
target_include_directories(veyra_map PUBLIC ${PROJECT_SOURCE_DIR}/include)
target_compile_features(veyra_map PUBLIC cxx_std_20)
target_link_libraries(veyra_map PUBLIC veyra_policy)
