cmake_minimum_required(VERSION 3.22)
project(veyra LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(BUILD_TESTING "Build tests" ON)
option(VEYRA_BUILD_APPS "Build apps" ON)

function(veyra_enable_warnings target)
  if(MSVC)
    target_compile_options(${target} PRIVATE /W4)
  else()
    target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
  endif()
endfunction()

function(veyra_enable_assertions target)
  if(MSVC)
    target_compile_options(${target} PRIVATE /UNDEBUG)
  else()
    target_compile_options(${target} PRIVATE -UNDEBUG)
  endif()
endfunction()

include(CTest)
add_subdirectory(src)

if(BUILD_TESTING)
  add_subdirectory(tests)
endif()

if(VEYRA_BUILD_APPS)
  add_subdirectory(apps)
endif()
