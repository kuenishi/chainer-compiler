#include <iostream>

#include <gtest/gtest.h>

#include <chainerx/array.h>
#include <chainerx/context.h>
#include <chainerx/numeric.h>
#include <chainerx/routines/creation.h>
#include <chainerx/testing/array.h>

#include <runtime/xcvm.h>
#include <runtime/xcvm.pb.h>
#include <runtime/xcvm_proto_util.h>

namespace oniku {
namespace runtime {
namespace {

TEST(XCVMTest, Run) {
    chainerx::Context ctx;
    chainerx::SetGlobalDefaultContext(&ctx);

    XCProgramProto program;
    AddInOp(&program, 0, "in1");
    AddInOp(&program, 1, "in2");
    AddAddOp(&program, 2, 0, 1);
    AddOutOp(&program, "out", 2);
    // std::cerr << program.DebugString() << std::endl;

    XCVM xcvm(program);
    InOuts inputs;
    inputs["in1"] = chainerx::Eye(2, nonstd::nullopt, nonstd::nullopt, chainerx::Dtype::kFloat32);
    inputs["in2"] = chainerx::OnesLike(inputs["in1"]);
    InOuts outputs = xcvm.Run(inputs, XCVMOptions());
    ASSERT_EQ(1, outputs.count("out"));
    chainerx::Array e = chainerx::testing::BuildArray({2, 2}).WithData<float>({2, 1, 1, 2});
    // TODO(hamaji): Use EXPECT_ARRAY_EQ after fixing namespace?
    EXPECT_TRUE(chainerx::AllClose(e, outputs["out"], 0, 0));
}

}  // namespace
}  // namespace runtime
}  // namespace oniku
