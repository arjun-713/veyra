add_library(veyra_temporal STATIC stub.cpp)
target_include_directories(veyra_temporal PUBLIC ${PROJECT_SOURCE_DIR}/include)
target_compile_features(veyra_temporal PUBLIC cxx_std_20)
