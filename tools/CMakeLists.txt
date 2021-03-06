get_filename_component(CHAINER_COMPILER_ROOT_DIR ${CMAKE_CURRENT_SOURCE_DIR} PATH)
set(GSLLITE_INCLUDE_DIRS ${CHAINER_COMPILER_ROOT_DIR}/gsl-lite/include)
set(OPTIONALLITE_INCLUDE_DIRS ${CHAINER_COMPILER_ROOT_DIR}/optional-lite/include)

include_directories(${GSLLITE_INCLUDE_DIRS})
include_directories(${OPTIONALLITE_INCLUDE_DIRS})
include_directories(${CHAINER_COMPILER_ROOT_DIR})
include_directories(${CMAKE_BINARY_DIR}) # the root directory instead of `build/tools`

include_directories(${CUDA_INCLUDE_DIRS})

add_library(chainer_compiler_tools
  compiler_flags.cc
  util.cc
  )
add_dependencies(chainer_compiler_tools runtime_xcvm_pb_h)
set_hidden_(chainer_compiler_tools)

add_executable(dump dump.cc)
target_link_libraries(dump
  onnx_proto
  chainer_compiler_tools
  chainer_compiler_compiler
  chainer_compiler_runtime
  chainer_compiler_common
  chainerx
  protobuf
  )
set_target_properties(dump PROPERTIES OUTPUT_NAME "dump")

add_library(run_onnx_lib
  run_onnx.cc
  )
add_dependencies(run_onnx_lib runtime_xcvm_pb_h onnx_files)
set_hidden_(run_onnx_lib)

add_executable(run_onnx run_onnx_main.cc)
target_link_libraries(run_onnx
  run_onnx_lib
  chainer_compiler_tools
  chainer_compiler_compiler
  chainer_compiler_runtime
  chainer_compiler_common
  chainerx
  onnx
  onnx_proto
  protobuf
  ${CHAINER_COMPILER_NGRAPH_LIBRARIES}
  ${CHAINER_COMPILER_TVM_LIBRARIES}
  ${CHAINER_COMPILER_CUDA_LIBRARIES}
  )
set_target_properties(run_onnx PROPERTIES OUTPUT_NAME "run_onnx")

if(${CHAINER_COMPILER_ENABLE_OPENCV})
  add_library(train_imagenet_lib
    train_imagenet.cc
    )
  add_dependencies(run_onnx_lib runtime_xcvm_pb_h onnx_files)
  set_hidden_(train_imagenet_lib)

  add_executable(train_imagenet train_imagenet_main.cc)
  add_dependencies(train_imagenet runtime_xcvm_pb_h onnx_files)
  target_link_libraries(train_imagenet
    train_imagenet_lib
    chainer_compiler_tools
    chainer_compiler_compiler
    chainer_compiler_runtime
    chainer_compiler_common
    feeder
    chainerx
    onnx
    onnx_proto
    protobuf
    pthread
    ${CHAINER_COMPILER_NGRAPH_LIBRARIES}
    ${CHAINER_COMPILER_TVM_LIBRARIES}
    ${CHAINER_COMPILER_CUDA_LIBRARIES}
    ${OpenCV_LIBS}
    )
  set_target_properties(train_imagenet PROPERTIES OUTPUT_NAME "train_imagenet")
endif()

if (${CHAINER_COMPILER_ENABLE_PYTHON})
  include_directories(${PYTHON_INCLUDE_DIRS})

  add_library(run_onnx_core.so MODULE run_onnx_core.cc)
  set_hidden_(run_onnx_core.so)

  target_link_libraries(run_onnx_core.so
    PRIVATE
    run_onnx_lib
    chainer_compiler_tools
    chainer_compiler_compiler
    chainer_compiler_runtime
    chainer_compiler_common
    chainerx
    onnx
    onnx_proto
    protobuf
    pthread
    ${CHAINER_COMPILER_NGRAPH_LIBRARIES}
    ${CHAINER_COMPILER_TVM_LIBRARIES}
    ${CHAINER_COMPILER_CUDA_LIBRARIES}
    )
  set_target_properties(run_onnx_core.so
    PROPERTIES
    PREFIX "${PYTHON_MODULE_PREFIX}"
    SUFFIX "${PYTHON_MODULE_SUFFIX}")

  if(${CHAINER_COMPILER_ENABLE_OPENCV})
    add_library(train_imagenet_core.so MODULE train_imagenet_core.cc)
    set_hidden_(train_imagenet_core.so)

    target_link_libraries(train_imagenet_core.so
      PRIVATE
      train_imagenet_lib
      chainer_compiler_tools
      chainer_compiler_compiler
      chainer_compiler_runtime
      chainer_compiler_common
      feeder
      chainerx
      onnx
      onnx_proto
      protobuf
      pthread
      ${CHAINER_COMPILER_NGRAPH_LIBRARIES}
      ${CHAINER_COMPILER_TVM_LIBRARIES}
      ${CHAINER_COMPILER_CUDA_LIBRARIES}
      ${OpenCV_LIBS}
      )
    set_target_properties(train_imagenet_core.so
      PROPERTIES
      PREFIX "${PYTHON_MODULE_PREFIX}"
      SUFFIX "${PYTHON_MODULE_SUFFIX}")
  endif()

endif()
