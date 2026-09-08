cmake_minimum_required(VERSION 3.22)
project(veyra LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(BUILD_TESTING "Build tests" ON)
option(VEYRA_BUILD_APPS "Build apps" ON)

add_subdirectory(src)

include(CTest)
if(BUILD_TESTING)
  add_subdirectory(tests)
endif()

if(VEYRA_BUILD_APPS)
  add_subdirectory(apps)
endif()
