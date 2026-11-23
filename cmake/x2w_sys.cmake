# System-library modules (src/sys): path remapping, threading and timing, GameInput, XAudio2, DirectStorage.
# Design and integration notes: docs/design/system-libs.md. Included from CMakeLists.txt.
if(NOT WIN32)
    return()
endif()

set(X2W_SYS_SOURCES
    src/sys/sys_common.cpp src/sys/sys_paths.cpp src/sys/sys_threads.cpp src/sys/sys_gameinput.cpp
    src/sys/sys_audio.cpp src/sys/sys_dstorage.cpp src/sys/sys_hooks.cpp)

add_library(x2w_sys_obj OBJECT ${X2W_SYS_SOURCES})
target_include_directories(x2w_sys_obj PUBLIC src/sys)
target_compile_features(x2w_sys_obj PUBLIC cxx_std_20)

add_library(x2w_sys_lib STATIC $<TARGET_OBJECTS:x2w_sys_obj>)
target_include_directories(x2w_sys_lib PUBLIC src/sys)
target_compile_features(x2w_sys_lib PUBLIC cxx_std_20)

# The desktop DLL a shim directory can hold (--shims DIR). Not copied into out/.../shims by default: shimgen
# decides which console DLL names forward to it (docs/design/system-libs.md).
add_library(x2w_sys SHARED $<TARGET_OBJECTS:x2w_sys_obj> src/sys/sys_exports.def)
target_include_directories(x2w_sys PUBLIC src/sys)
target_compile_features(x2w_sys PUBLIC cxx_std_20)
set_target_properties(x2w_sys PROPERTIES OUTPUT_NAME x2w_sys)

add_library(x2w_sys_fake_runtime SHARED tests/sys/fake_runtime.cpp)

foreach(check IN ITEMS paths threads hooks)
    add_executable(sys_${check}_check tests/sys/sys_${check}_check.cpp)
    target_include_directories(sys_${check}_check PRIVATE tests/sys)
    target_link_libraries(sys_${check}_check PRIVATE x2w_sys_lib)
    add_test(NAME sys_${check} COMMAND sys_${check}_check)
    set_tests_properties(sys_${check} PROPERTIES TIMEOUT 60)
endforeach()
foreach(check IN ITEMS gameinput audio dstorage)
    add_executable(sys_${check}_check tests/sys/sys_${check}_check.cpp)
    target_include_directories(sys_${check}_check PRIVATE tests/sys)
    target_link_libraries(sys_${check}_check PRIVATE x2w_sys_lib)
    add_dependencies(sys_${check}_check x2w_sys_fake_runtime)
    add_test(NAME sys_${check} COMMAND sys_${check}_check "$<TARGET_FILE:x2w_sys_fake_runtime>")
    set_tests_properties(sys_${check} PROPERTIES TIMEOUT 60)
endforeach()
