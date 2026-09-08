add_library(veyra_policy STATIC stub.cpp)
target_include_directories(veyra_policy PUBLIC ${PROJECT_SOURCE_DIR}/include)
target_compile_features(veyra_policy PUBLIC cxx_std_20)
