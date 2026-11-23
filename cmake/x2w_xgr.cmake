# The xgameruntime.dll gateway (docs/design/runtime.md, section 2, "The Gaming Runtime gateway"):
# shims\x2w_xgr.dll, which x2w_launch --xgr ours|trace|record loads for a title's xgameruntime.dll.
# tools/xgr_gen.py turns tools/xgr/interfaces.toml (learned CLSIDs, IIDs and slots) and the shimgen specs
# into xgr_table.inc at configure time. Needs x2w_gdk (cmake/x2w_shimgen.cmake) and MASM.
enable_language(ASM_MASM)
set(x2w_xgr_table "${CMAKE_SOURCE_DIR}/tools/xgr/interfaces.toml")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${CMAKE_SOURCE_DIR}/tools/xgr_gen.py" "${x2w_xgr_table}")
execute_process(COMMAND "${x2w_shimgen_python}" -B "${CMAKE_SOURCE_DIR}/tools/xgr_gen.py" --table "${x2w_xgr_table}"
    --out "${CMAKE_BINARY_DIR}/xgr/xgr_table.inc"
    RESULT_VARIABLE x2w_xgr_status OUTPUT_VARIABLE x2w_xgr_output ERROR_VARIABLE x2w_xgr_output)
if(NOT x2w_xgr_status EQUAL 0)
    message(FATAL_ERROR "tools/xgr_gen.py failed:\n${x2w_xgr_output}")
endif()
message(STATUS "${x2w_xgr_output}")

add_library(x2w_xgr SHARED src/xgr/xgr_gateway.cpp src/xgr/xgr_extra.cpp src/xgr/xgr_thunks.asm
    src/xgr/xgr_gateway.def)
target_include_directories(x2w_xgr PRIVATE "${CMAKE_BINARY_DIR}/xgr")
target_compile_features(x2w_xgr PRIVATE cxx_std_17)
target_compile_options(x2w_xgr PRIVATE $<$<COMPILE_LANGUAGE:CXX>:/W4 /EHsc>)
target_link_libraries(x2w_xgr PRIVATE x2w_gdk)
set_target_properties(x2w_xgr PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/shims")
add_dependencies(x2w_gdk_shims x2w_xgr)

add_test(NAME xgr_table COMMAND "${x2w_shimgen_python}" -B "${CMAKE_SOURCE_DIR}/tools/xgr_gen.py" --check)
set_tests_properties(xgr_table PROPERTIES TIMEOUT 60)

# Magic statics in a /MD title, run by tools/pc_jobs/run_xgr.ps1 under Windows and under x2w_launch.
add_executable(x2w_xgr_statics_title tests/xgr/statics_title.cpp)
target_compile_features(x2w_xgr_statics_title PRIVATE cxx_std_17)
target_link_options(x2w_xgr_statics_title PRIVATE /DYNAMICBASE /INCREMENTAL:NO)
set_target_properties(x2w_xgr_statics_title PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
