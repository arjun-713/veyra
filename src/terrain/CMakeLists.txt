add_library(veyra_terrain STATIC stub.cpp)
target_include_directories(veyra_terrain PUBLIC ${PROJECT_SOURCE_DIR}/include)
target_compile_features(veyra_terrain PUBLIC cxx_std_20)
