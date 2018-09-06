#pragma once

#include <string>
#include <vector>

#include <nonstd/optional.hpp>

#include <chainerx/array.h>

#include <runtime/xchainer.h>
#include <runtime/xcvm.pb.h>

namespace oniku {
namespace runtime {

class XCVMOptions;
class XCVMVar;

class XCVMState {
public:
    class Auxiliary {
    public:
        virtual ~Auxiliary() = default;

    protected:
        Auxiliary() = default;
    };

    XCVMState(const XCVMOptions& options, int num_variables, const InOuts& inputs);
    ~XCVMState();

    int pc() const {
        return pc_;
    }
    void set_pc(int pc) {
        pc_ = pc;
    }

    chainerx::Array GetVar(int index);
    nonstd::optional<chainerx::Array> GetVarOptional(int index);
    std::vector<chainerx::Array> GetVarList(const std::vector<int>& index);
    void SetVar(int index, const chainerx::Array& value);
    void FreeVar(int index);

    std::vector<chainerx::Array>* CreateSequence(int index);
    std::vector<chainerx::Array>* GetSequence(int index);

    std::string GetVarString(int index);

    Auxiliary* GetAux(int index);
    void SetAux(int index, std::unique_ptr<Auxiliary>&& aux);

    chainerx::Array Input(const std::string& name);
    void Output(const std::string& name, chainerx::Array value);

    const InOuts& GetOutputs() const {
        return outputs_;
    }

    void CheckNans(const std::vector<int>& inputs, const std::vector<int>& outputs);
    void CheckInfs(const std::vector<int>& inputs, const std::vector<int>& outputs);

    int trace_level() const {
        return trace_level_;
    }
    bool is_training() const {
        return is_training_;
    }
    bool check_nans() const {
        return check_nans_;
    }
    bool check_infs() const {
        return check_infs_;
    }

private:
    int pc_;
    std::vector<std::unique_ptr<XCVMVar>> variables_;
    std::vector<std::unique_ptr<Auxiliary>> auxiliaries_;
    const InOuts& inputs_;
    InOuts outputs_;
    int trace_level_ = 0;
    bool is_training_ = false;
    bool check_nans_ = false;
    bool check_infs_ = false;
};

}  // namespace runtime
}  // namespace oniku
