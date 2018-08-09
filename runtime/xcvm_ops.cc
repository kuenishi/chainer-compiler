#include "xcvm_ops.h"

#include <xchainer/routines/connection.h>
#include <xchainer/routines/creation.h>
#include <xchainer/routines/linalg.h>
#include <xchainer/routines/manipulation.h>
#include <xchainer/routines/math.h>
#include <xchainer/routines/pooling.h>
#include <xchainer/shape.h>

#include <runtime/xcvm_ops.h>
#include <runtime/xcvm_state.h>

namespace oniku {
namespace runtime {

xchainer::Array InOp::RunImpl(XCVMState* st) {
    return st->Input(name);
}

void OutOp::RunImpl(XCVMState* st, const xchainer::Array& v) {
    st->Output(name, v);
}

xchainer::Array AddOp::RunImpl(XCVMState* st, const xchainer::Array& a, const xchainer::Array& b) {
    return a + b;
}

xchainer::Array ConvOp::RunImpl(XCVMState* st, const xchainer::Array& x, const xchainer::Array& w) {
    return xchainer::Conv(x, w, nonstd::nullopt, strides, pads);
}

xchainer::Array ConvWithBiasOp::RunImpl(XCVMState* st, const xchainer::Array& x, const xchainer::Array& w, const xchainer::Array& b) {
    return xchainer::Conv(x, w, b, strides, pads);
}

xchainer::Array IdentOp::RunImpl(XCVMState* st, const xchainer::Array& x) {
    return x;
}

xchainer::Array ReluOp::RunImpl(XCVMState* st, const xchainer::Array& x) {
    return xchainer::Maximum(x, 0);
}

xchainer::Array ReshapeOp::RunImpl(XCVMState* st, const xchainer::Array& data, const xchainer::Array& shape) {
    return xchainer::Reshape(data, ArrayToShape(shape));
}

xchainer::Array SoftmaxOp::RunImpl(XCVMState* st, const xchainer::Array& input) {
    return xchainer::Exp(xchainer::LogSoftmax(input, xchainer::OptionalAxes{static_cast<char>(axis)}));
}

xchainer::Array LogSoftmaxOp::RunImpl(XCVMState* st, const xchainer::Array& input) {
    return xchainer::LogSoftmax(input, xchainer::OptionalAxes{static_cast<char>(axis)});
}

xchainer::Array MaxPoolOp::RunImpl(XCVMState* st, const xchainer::Array& x) {
    return xchainer::MaxPool(x, kernel_shape, strides, pads, false);
}

xchainer::Array AveragePoolOp::RunImpl(XCVMState* st, const xchainer::Array& x) {
    xchainer::AveragePoolPadMode pad_mode = count_include_pad ? xchainer::AveragePoolPadMode::kZero : xchainer::AveragePoolPadMode::kIgnore;
    return xchainer::AveragePool(x, kernel_shape, strides, pads, pad_mode);
}

xchainer::Array MatMulOp::RunImpl(XCVMState* st, const xchainer::Array& a, const xchainer::Array& b) {
    return xchainer::Dot(a, b);
}

xchainer::Array GemmOp::RunImpl(XCVMState* st, const xchainer::Array& a, const xchainer::Array& b, const xchainer::Array& c) {
    xchainer::Array xa = a;
    xchainer::Array xb = b;
    if (trans_a) xa = xchainer::Transpose(xa);
    if (trans_b) xb = xchainer::Transpose(xb);
    xchainer::Array r = xchainer::Dot(xa, xb);
    if (alpha != 1.0) r *= alpha;
    xchainer::Array xc = c;
    if (beta != 1.0) xc *= beta;
    return r + xc;
}

}  // namespace runtime
}  // namespace oniku