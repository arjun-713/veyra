add_library(veyra_metrics STATIC stub.cpp)
target_include_directories(veyra_metrics PUBLIC ${PROJECT_SOURCE_DIR}/include)
target_compile_features(veyra_metrics PUBLIC cxx_std_20)
