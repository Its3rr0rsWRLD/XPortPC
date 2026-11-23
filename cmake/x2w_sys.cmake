# System-library modules (src/sys): path remapping, threading and timing, GameInput, XAudio2, DirectStorage.
# Design and integration notes: docs/design/system-libs.md. Included from CMakeLists.txt.
if(NOT WIN32)
    return()
endif()

# Microsoft's reference GDeflate codec and the libdeflate fork under it (third_party/gdeflate, notices in NOTICE.md).
enable_language(C)
set(X2W_GDEFLATE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/gdeflate")
set(X2W_LIBDEFLATE_DIR "${X2W_GDEFLATE_DIR}/libdeflate")
add_library(x2w_gdeflate STATIC
    "${X2W_LIBDEFLATE_DIR}/lib/adler32.c" "${X2W_LIBDEFLATE_DIR}/lib/crc32.c"
    "${X2W_LIBDEFLATE_DIR}/lib/deflate_compress.c" "${X2W_LIBDEFLATE_DIR}/lib/deflate_decompress.c"
    "${X2W_LIBDEFLATE_DIR}/lib/gdeflate_compress.c" "${X2W_LIBDEFLATE_DIR}/lib/gdeflate_decompress.c"
    "${X2W_LIBDEFLATE_DIR}/lib/gzip_compress.c" "${X2W_LIBDEFLATE_DIR}/lib/gzip_decompress.c"
    "${X2W_LIBDEFLATE_DIR}/lib/utils.c" "${X2W_LIBDEFLATE_DIR}/lib/zlib_compress.c"
    "${X2W_LIBDEFLATE_DIR}/lib/zlib_decompress.c" "${X2W_LIBDEFLATE_DIR}/lib/x86/cpu_features.c"
    "${X2W_GDEFLATE_DIR}/gdeflate/GDeflateCompress.cpp" "${X2W_GDEFLATE_DIR}/gdeflate/GDeflateDecompress.cpp")
target_include_directories(x2w_gdeflate PUBLIC "${X2W_GDEFLATE_DIR}/gdeflate" PRIVATE "${X2W_LIBDEFLATE_DIR}"
    "${X2W_LIBDEFLATE_DIR}/lib")
target_include_directories(x2w_gdeflate SYSTEM PUBLIC "${X2W_LIBDEFLATE_DIR}")
target_compile_features(x2w_gdeflate PUBLIC cxx_std_17)
if(MSVC)
    # The warnings Microsoft's own build disables to compile the reference sources unmodified.
    target_compile_options(x2w_gdeflate PRIVATE /wd4244 /wd4127 /wd4267 /wd4100 /wd4245 /wd4456 /wd4018 /wd4146 /wd4310)
endif()

set(X2W_SYS_SOURCES
    src/sys/sys_common.cpp src/sys/sys_paths.cpp src/sys/sys_threads.cpp src/sys/sys_gameinput.cpp
    src/sys/sys_audio.cpp src/sys/sys_dstorage.cpp src/sys/sys_hooks.cpp src/sys/sys_gdeflate.cpp)

add_library(x2w_sys_obj OBJECT ${X2W_SYS_SOURCES})
target_include_directories(x2w_sys_obj PUBLIC src/sys)
target_link_libraries(x2w_sys_obj PRIVATE x2w_gdeflate)
target_compile_features(x2w_sys_obj PUBLIC cxx_std_20)

add_library(x2w_sys_lib STATIC $<TARGET_OBJECTS:x2w_sys_obj>)
target_include_directories(x2w_sys_lib PUBLIC src/sys)
target_link_libraries(x2w_sys_lib PUBLIC x2w_gdeflate)
target_compile_features(x2w_sys_lib PUBLIC cxx_std_20)

# The desktop DLL a shim directory can hold (--shims DIR). The x2w_shims target copies it into shims/ (see
# CMakeLists.txt); x2w_launch loads it from there for the Win32 hooks (docs/design/system-libs.md).
add_library(x2w_sys SHARED $<TARGET_OBJECTS:x2w_sys_obj> src/sys/sys_exports.def)
target_include_directories(x2w_sys PUBLIC src/sys)
target_link_libraries(x2w_sys PRIVATE x2w_gdeflate)
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

# GDeflate: decoder checks against streams made by the reference encoder, and the packer tool that tests use to
# create fixtures (tests/sys/gdeflate_pack.cpp: gdeflate_pack IN OUT [LEVEL]).
add_executable(gdeflate_pack tests/sys/gdeflate_pack.cpp)
target_link_libraries(gdeflate_pack PRIVATE x2w_gdeflate)
add_executable(sys_gdeflate_check tests/sys/sys_gdeflate_check.cpp)
target_include_directories(sys_gdeflate_check PRIVATE tests/sys)
target_link_libraries(sys_gdeflate_check PRIVATE x2w_sys_lib)
add_test(NAME sys_gdeflate COMMAND sys_gdeflate_check)
set_tests_properties(sys_gdeflate PROPERTIES TIMEOUT 120)
