import chainer

import onnx
import onnx.helper as oh
from onnx import numpy_helper
from onnx import TensorProto
from onnx import ModelProto

import elichika.parser.core as core
import elichika.parser.graphs as graphs
import elichika.parser.values as values
import elichika.parser.nodes as nodes
import elichika.parser.functions as functions
import elichika.parser.functions_builtin as functions_builtin
import elichika.parser.values_builtin as values_builtin
import elichika.parser.utils as utils

import numpy as np
import collections

def size2d(x):
    if isinstance(x, collections.Iterable):
        return x
    return (x, x)

def get_onnx_dtype(dtype):
    a = np.zeros((), dtype=dtype)
    dt = onnx.mapping.NP_TYPE_TO_TENSOR_TYPE[a.dtype]
    return dt

assigned_names = []
node2onnx_parameter = {}
value2onnx_parameter = {}

class NodeONNXParameter:
    def __init__(self, onnx_name, value):
        self.onnx_name = onnx_name
        self.original_value = value

class ValueONNXParameter:
    def __init__(self, onnx_name, value):
        self.onnx_name = onnx_name
        self.original_value = value

def onnx_name(value):
    if isinstance(value, values.Value):
        return value2onnx_parameter[value].onnx_name
    if isinstance(value, nodes.Node):
        return node2onnx_parameter[value].onnx_name

def generate_onnx_value_name(value : 'values.Value', none_name = ''):
    base_name = ''

    if value.generator != None:
        base_name = value.name + '_' + str(value.generator.lineprop)
    base_name = value.name

    if base_name == '':
        base_name = none_name

    ind = 0
    name = base_name

    if name == '':
        name = 'noname'

    while (name in assigned_names):
        ind+=1
        name = base_name + '_' + str(ind)

    assigned_names.append(name)
    return name

def generate_onnx_node_name(node : 'nodes.Node'):
    base_name = str(node)

    ind = 0
    name = base_name
    while (name in assigned_names):
        ind+=1
        name = base_name + '_' + str(ind)

    assigned_names.append(name)
    return name


def generate_onnx_name(name : 'str'):
    base_name = str(name)

    ind = 0
    name = base_name
    while (name in assigned_names):
        ind+=1
        name = base_name + '_' + str(ind)

    assigned_names.append(name)
    return name


def assign_onnx_name_to_value(value : 'values.Value', none_name = ''):
    if not value in value2onnx_parameter:
        value2onnx_parameter[value] = ValueONNXParameter(generate_onnx_value_name(value, none_name), value)

    if isinstance(value, values.TupleValue):
        tupleValue = value # type : values.TupleValue
        for value_ in tupleValue.values:
            if isinstance(value_, values.Value):
                 assign_onnx_name_to_value(value_, value2onnx_parameter[tupleValue].onnx_name)
            elif isinstance(value_, values.Attribute):
                assign_onnx_name_to_value(value_.get_obj(False).get_value(), value2onnx_parameter[tupleValue].onnx_name)
            elif isinstance(value_, values.Object):
                assign_onnx_name_to_value(value_.get_value(), value2onnx_parameter[tupleValue].onnx_name)
            else:
                assert(False)

def assign_onnx_name(graph : 'graphs.Graph'):

    for v in graph.input_values:
        assign_onnx_name_to_value(v)

    for v in graph.output_values:
        assign_onnx_name_to_value(v)

    for node in graph.nodes:
        for input in node.inputs:
            assign_onnx_name_to_value(input)

        for output in node.outputs:
            assign_onnx_name_to_value(output)

        if not node in node2onnx_parameter:
            node2onnx_parameter[node] = NodeONNXParameter(generate_onnx_node_name(node), node)

        for subgraph in node.subgraphs:
            assign_onnx_name(subgraph)

def preprocess(graph : 'graphs.Graph', isMain : 'bool'):

    # replace inputs
    if not isMain:
        input_values = graph.input_values.copy()
        copied_input_values = [functions.generate_copied_value(v) for v in input_values]

        old2new = {}

        for i in range(len(input_values)):
            copied_input_values[i].name = input_values[i].name + '_in'
            old2new[input_values[i]] = copied_input_values[i]

        for node in graph.nodes:
            for i in range(len(input_values)):
                node.replace_inputs(input_values[i], copied_input_values[i])

        graph.input_values = copied_input_values

        for i in range(len(graph.output_values)):
            if graph.output_values[i] in old2new.keys():
                graph.output_values[i] = old2new[graph.output_values[i]]

    replacing = {}
    for value in graph.output_values:
        if value in graph.input_values:
            copied_value = functions.generate_copied_value(value)
            copied_value.name = value.name + '_cp'
            replacing[value] = copied_value
            node = nodes.NodeCopy(value)
            node.set_outputs([copied_value])
            graph.add_node(node)

    for i in range(len(graph.output_values)):
        if graph.output_values[i] in replacing.keys():
            graph.output_values[i] = replacing[graph.output_values[i]]

    # fix duplicates (if same output value exsits, error is caused.)
    output_values = graph.output_values.copy()
    duplicates = {}
    for i in range(len(output_values)):
        if output_values[i] in duplicates.keys():
            copied_value = functions.generate_copied_value(output_values[i])

            node = nodes.NodeCopy(output_values[i])
            node.set_outputs([copied_value])
            graph.add_node(node)

            copied_value.name = output_values[i].name + '_cp_out_' + str(duplicates[output_values[i]])
            duplicates[output_values[i]] += 1
            output_values[i] = copied_value
        else:
            duplicates[output_values[i]] = 0

    graph.output_values = output_values

    for node in graph.nodes:
        for subgraph in node.subgraphs:
            preprocess(subgraph, False)


def convert_onnx_chainer_linear(onnx_graph : 'ONNXGraph', node : 'nodes.Node'):
    chainer_inst = node.func.owner.inst # type: chainer.links.Linear
    onnx_name = node2onnx_parameter[node].onnx_name

    x = ONNXValue(onnx_graph, node.inputs[0])
    o = ONNXValue(onnx_graph, node.outputs[0])

    if chainer_inst.W.data is None:
        print("W is unknown. Please infer this model.")

    w = ONNXValue(onnx_graph, chainer_inst.W.data, [onnx_name, '/W'])

    (x_shape,) = onnx_graph.add_node(
        'Shape',
        [x],
        [None],
        str(node.lineprop))

    (batch_size_1,) = onnx_graph.add_node(
        'Gather',
        [x_shape, ONNXValue(onnx_graph, np.array(0, dtype=np.int64), [onnx_name, '/Zero'])],
        [None],
        str(node.lineprop))

    (batch_size_2,) = onnx_graph.add_node(
        'Unsqueeze',
        [batch_size_1],
        [None],
        str(node.lineprop),
        axes=[0])

    (mat_shape,) = onnx_graph.add_node(
        'Concat',
        [batch_size_2, ONNXValue(onnx_graph, np.array([-1], dtype=np.int64), [onnx_name, '/Minus1'])],
        [None],
        str(node.lineprop),
        axis=0)

    (x_reshape,) = onnx_graph.add_node(
        'Reshape',
        [x, mat_shape],
        [None],
        str(node.lineprop))

    if chainer_inst.b is not None:
        b = ONNXValue(onnx_graph, chainer_inst.b.data, [onnx_name, '/b'])

        onnx_graph.add_node(
            'Gemm',
            [x_reshape, w, b],
            [o],
            str(node.lineprop),
            transA=0,
            transB=1)
    else:
        temp = ONNXValue(onnx_graph, np.float32, [onnx_name, '/Temp'])

        onnx_graph.add_node(
            'Transpose',
            [w],
            [temp],
            str(node.lineprop),
            perm=[1, 0])

        onnx_graph.add_node(
            'MatMul',
            [x_reshape, temp],
            [o],
            str(node.lineprop))

def convert_onnx_chainer_convolution2d(onnx_graph : 'ONNXGraph', node : 'nodes.Node'):
    chainer_inst = node.func.owner.inst # type: chainer.links.Convolution2D
    onnx_name = node2onnx_parameter[node].onnx_name

    ksize = size2d(chainer_inst.ksize)
    stride = size2d(chainer_inst.stride)
    ps = size2d(chainer_inst.pad)
    pads = ps + ps

    x = ONNXValue(onnx_graph, node.inputs[0])
    o = ONNXValue(onnx_graph, node.outputs[0])
    w = ONNXValue(onnx_graph, chainer_inst.W.data, [onnx_name, '/W'])
    b = None

    if chainer_inst.b is not None:
        b = ONNXValue(onnx_graph, chainer_inst.b.data, [onnx_name, '/b'])

    onnx_graph.add_node(
        'Conv',
        [x, w] + ([] if b is None else [b]),
        [o],
        str(node.lineprop),
        kernel_shape=ksize,
        pads=pads,
        strides=stride)

class ONNXValue:
    """
    A wrapper of ONNX value

    Args:
        onnx_graph : an instance of ONNXGraph
        any_value : wrapped value. values.Value, np.array or np.float32(any size)
        name : a value of name. string or array
    """
    def __init__(self, onnx_graph : 'ONNXGraph', any_value = None, name = None):
        assert(isinstance(onnx_graph,ONNXGraph))
        self.value = None # values.Value
        self.np_value = None # np.array
        self.onnx_graph = onnx_graph
        self.name = ''

        name_ = ''

        if(isinstance(name, list)):
            for n in name:
                if isinstance(n,values.Value):
                    name_ += value2onnx_parameter[self.value].onnx_name
                elif n is None:
                    name_ += ''
                else:
                    name_ += str(n)

        if(isinstance(name, str)):
            name_ = name

        if name is not None:
            name_ = generate_onnx_name(name_)

        if(any_value == np.float32 or any_value == np.float64 or any_value == np.int32 or any_value == np.int64):
            self.tensor = self.onnx_graph.new_empty_tensor(['TODO'], any_value, name_)
            self.name = name_

        if isinstance(any_value, values.Value):
            self.value = any_value
            if name is not None:
                self.name = name_
            else:
                self.name = value2onnx_parameter[self.value].onnx_name

        if isinstance(any_value, np.ndarray):
            self.np_value = any_value
            self.tensor = onnx_graph.new_tensor_with_np(self.np_value, name_)
            self.name = name_

    def create_sequence(self) -> 'ONNXValue':
        if(isinstance(self.value, values.ListValue)):
            ret = ONNXValue(self.onnx_graph,values.ListValue(), [self.name, '/create_sequence'])
            self.onnx_graph.add_node(
                "Identity",
                [self.name],
                [ret],
                str('create_sequence'))

            return ret

        if(isinstance(self.value, values.TupleValue)):
            value = self.value # values.TupleValue
            ret = ONNXValue(self.onnx_graph,values.ListValue(), [self.name, '/create_sequence'])
            self.onnx_graph.add_node(
                "ChainerSequenceCreate",
                [ONNXValue(self.onnx_graph, v) for v in value.values],
                [ret],
                str('create_sequence'))

            return ret

        assert(False)




class ONNXInitrializer:
    def __init__(self):
        self.node = None
        self.name = NameError
        self.dt = 0
        self.shape = ()

class ONNXGraph:
    def __init__(self, generator : 'ONNXGenerator', parent : 'ONNXGraph'):
        self.generator = generator
        self.parent = parent
        self.nodes = []
        self.input_tensor = []
        self.output_tensor = []

    def try_get_attribute(self, value, calling_node : 'nodes.Node' = None):

        if calling_node is None:
            lineinfo = 'unknown'
        else:
            lineinfo = str(calling_node.lineprop)

        if isinstance(value, values.NumberValue):
            value_ = value  # type: values.NumberValue
            if value_.internal_value is None:
                print('Warning : unconst attribute in {}'.format(lineinfo))
            return value_.internal_value

        if isinstance(value, values.BoolValue):
            value_ = value  # type: values.BoolValue
            if value_.internal_value is None:
                print('Warning : unconst attribute in {}'.format(lineinfo))
            return value_.internal_value

        if isinstance(value, values.StrValue):
            value_ = value  # type: values.StrValue
            if value_.internal_value is None:
                print('Warning : unconst attribute in {}'.format(lineinfo))
            return value_.internal_value

        if isinstance(value, values.NoneValue):
            value_ = value  # type: values.NoneValue
            return None

        # error
        print("Cannot convert a value into an attribute")
        return -1

    def new_empty_tensor(self, dims, dtype, name):
        '''
        generate a tensor for connecting between nodes
        '''
        dt = onnx.mapping.NP_TYPE_TO_TENSOR_TYPE[np.dtype(dtype)]
        tensor = oh.make_tensor_value_info(name, dt, dims)
        self.generator.tensors[name] = tensor
        return tensor

    def new_empty_tensor_with_value(self, value):
        '''
        generate a tensor with Value to indicate shape
        it is for inputting and outputting
        '''
        if isinstance(value, values.TensorValue):
            dtype = np.float32
            if value.dtype is not None:
                dtype = value.dtype

            if len(value.shape) > 0:
                shape = list(value.shape)
                shape = [x if x != -1 else 'Undefined' for x in shape]
                # type estimation is not correct. so shape needs to be undefined.
                shape = None
                return self.new_empty_tensor(shape, dtype, value2onnx_parameter[value].onnx_name)
            else:
                shape = None
                return self.new_empty_tensor(shape, dtype, value2onnx_parameter[value].onnx_name)

        if isinstance(value, values.BoolValue):
            return self.new_empty_tensor(None, np.bool, value2onnx_parameter[value].onnx_name)

        if isinstance(value, values.ListValue):
            vi = onnx.ValueInfoProto()
            vi.name = value2onnx_parameter[value].onnx_name
            vi.type.sequence_type.elem_type.tensor_type.elem_type = onnx.TensorProto.FLOAT
            self.generator.tensors[vi.name] = vi
            return vi

        if isinstance(value, values.NumberValue):
            if value.dtype is not None:
                return self.new_empty_tensor(None, value.dtype, value2onnx_parameter[value].onnx_name)
            elif value.internal_value is not None:
                if isinstance(value.internal_value, int):
                    dtype = np.array(value.internal_value).dtype
                    return self.new_empty_tensor(None, dtype, value2onnx_parameter[value].onnx_name)
                if isinstance(value.internal_value, float):
                    dtype = np.array(value.internal_value).dtype
                    return self.new_empty_tensor(None, dtype, value2onnx_parameter[value].onnx_name)

        return self.new_empty_tensor(None, np.float32, value2onnx_parameter[value].onnx_name)

    def new_tensor_with_np(self, ndarray_, name):
        '''
        generate a tensor which contains np data
        it is for constant input
        '''
        tensor = numpy_helper.from_array(ndarray_, name=name)
        dt = onnx.mapping.NP_TYPE_TO_TENSOR_TYPE[np.dtype(ndarray_.dtype)]
        initializer = ONNXInitrializer()
        initializer.name = name
        initializer.node = tensor
        initializer.dt = dt
        initializer.shape = ndarray_.shape

        assert(not (name in self.generator.initializers.keys()))
        self.generator.initializers[name] = initializer

        return tensor

    def new_tensor_with_value(self, value):
        '''
        generate a tensor which value
        it is for constant input
        '''
        name = value2onnx_parameter[value].onnx_name

        if isinstance(value, values.NumberValue):
            if value.internal_value is None:
                # any value
                if value.dtype is None:
                    arr = np.array(0)
                else:
                    arr = np.array(0, dtype=value.dtype)
                return self.new_tensor_with_np(arr, name)
            else:
                arr = np.array(value.internal_value)
                return self.new_tensor_with_np(arr, name)

        if isinstance(value, values.BoolValue):
            arr = np.array(value.internal_value)
            return self.new_tensor_with_np(arr, name)

        if isinstance(value, values.NoneValue):
            arr = np.array(False)
            return self.new_tensor_with_np(arr, name)


        print('Warning : Found uknown type {} in new_tensor_with_value. Float is stored.'.format(type(value)))
        arr = np.array(0.0, dtype=np.float32)
        return self.new_tensor_with_np(arr, name)

    def add_node(self, optype, inputs, outputs, name, **kwargs):

        inputs_ = []
        outputs_ = []

        for input in inputs:
            if isinstance(input, str):
                inputs_.append(input)
            elif isinstance(input, ONNXValue):
                inputs_.append(input.name)
            else:
                assert(False)

        output_values = []

        for output in outputs:
            if isinstance(output, str):
                outputs_.append(output)
            elif isinstance(output, ONNXValue):
                outputs_.append(output.name)
            elif output is None:
                o = ONNXValue(self, np.float32, [name, '/', optype, '/Output'])
                output_values.append(o)
                outputs_.append(o.name)
            else:
                assert(False)

        node = oh.make_node(optype, inputs_, outputs_, name, **kwargs)
        self.nodes.append(node)

        return tuple(output_values)

    def try_get_tensor(self, onnx_name : 'str'):
        if onnx_name in self.generator.tensors.keys():
            return self.generator.tensors[onnx_name]

        #if self.parent is not None:
        #    return self.parent.try_get_tensor(onnx_name)

        return None

    def set_input(self, input):
        self.input_tensor = []

        for input_ in input:
            onnx_name = value2onnx_parameter[input_].onnx_name
            value = self.try_get_tensor(onnx_name)
            assert(value is not None)
            self.input_tensor.append(value)

    def set_output(self, output):
        self.output_tensor = [self.generator.tensors[value2onnx_parameter[x].onnx_name] for x in output]

    def generate_graph(self, name : 'str', isMain = False):

        input_tensor_and_initializer = self.input_tensor.copy()
        initializers = []

        # add initializers
        if isMain:
            for v in self.generator.initializers.values():
                if v.node in self.input_tensor:
                    continue
                if v.node in self.output_tensor:
                    continue

                initializers.append(v.node)

                tensor = oh.make_tensor_value_info(v.name, v.dt, v.shape)
                input_tensor_and_initializer.append(tensor)

        return oh.make_graph(self.nodes, name, input_tensor_and_initializer, self.output_tensor, initializer=initializers)

class ONNXGenerator:
    def __init__(self):
        self.onnx_graphs = []
        self.initializers = {}
        self.tensors = {}
        self.onnx_tensors = {}

    def generate_graph(self, inputs, outputs, graph : 'graphs.Graph', parent : 'ONNXGraph', isMain = False):
        onnx_graph = ONNXGraph(self, parent)

        def generate_input_tensors(inputs_):
            for input in inputs_:
                if not (value2onnx_parameter[input].onnx_name in self.onnx_tensors.keys()):

                    def generate_tensor_constant(input_):
                        tensor = onnx_graph.new_tensor_with_value(input_)
                        self.onnx_tensors[value2onnx_parameter[input_].onnx_name] = tensor
                        if isinstance(input_, values.TupleValue):
                            for value in input_.values:
                                if not isinstance(value, values.Value):
                                    continue
                                generate_tensor_constant(value)

                    def generate_tensor(input_):
                        tensor = onnx_graph.new_empty_tensor_with_value(input_)
                        self.onnx_tensors[value2onnx_parameter[input_].onnx_name] = tensor
                        if isinstance(input_, values.TupleValue):
                            for value in input_.values:
                                if not isinstance(value, values.Value):
                                    continue
                            for value in input_.values:
                                generate_tensor(value)


                    if input.generator is None and not (input in inputs):
                        generate_tensor_constant(input)
                    else:
                        generate_tensor(input)

        def generate_output_tensors(outputs_):

            def generate_tensor(output_):
                tensor = onnx_graph.new_empty_tensor_with_value(output_)
                self.onnx_tensors[value2onnx_parameter[output_].onnx_name] = tensor
                if isinstance(output_, values.TupleValue):
                    for value in output_.values:
                        if not isinstance(value, values.Value):
                            continue
                        generate_tensor(value)

            for output in outputs_:
                if not (value2onnx_parameter[output].onnx_name in self.onnx_tensors.keys()):
                    generate_tensor(output)

        generate_input_tensors(inputs)

        for node in graph.nodes:
            generate_input_tensors(node.inputs)
            generate_output_tensors(node.outputs)

        generate_output_tensors(outputs)

        for node in graph.nodes:
            if isinstance(node, nodes.NodeCopy):
                node_ = node # type: nodes.Copy
                onnx_node = oh.make_node(
                    'Identity',
                    [value2onnx_parameter[node_.value].onnx_name],
                    [value2onnx_parameter[node.outputs[0]].onnx_name])

                onnx_graph.nodes.append(onnx_node)

            '''
            # disabled because of SSA
            if isinstance(node, nodes.NodeNonVolatileAssign):
                node_ = node # type: nodes.NodeNonVolatileAssign
                onnx_node = oh.make_node(
                    'Identity',
                    [value2onnx_parameter[node_.value].onnx_name],
                    [value2onnx_parameter[node_.target_value].onnx_name])

                onnx_graph.nodes.append(onnx_node)
            '''

            if isinstance(node, nodes.NodeAugAssign):
                node_ = node # type: nodes.AugAssign
                binops = {}
                binops[nodes.BinOpType.Add] = 'Add'
                binops[nodes.BinOpType.Sub] = 'Sub'
                binops[nodes.BinOpType.Unknown] = 'Add'

                # TODO: fix for reference types

                onnx_node = oh.make_node(
                    binops[node_.binop],
                    [value2onnx_parameter[node_.target].onnx_name,
                    value2onnx_parameter[node_.value].onnx_name],
                    [value2onnx_parameter[node.outputs[0]].onnx_name])
                onnx_graph.nodes.append(onnx_node)

            if isinstance(node, nodes.NodeBinOp):
                node_ = node # type: nodes.NodeBinOp
                binops = {}
                binops[nodes.BinOpType.Add] = 'Add'
                binops[nodes.BinOpType.Sub] = 'Sub'
                binops[nodes.BinOpType.Mul] = 'Mul'
                binops[nodes.BinOpType.Unknown] = 'Add'

                if isinstance(node_.left, values.ListValue) or isinstance(node_.left, values.TupleValue):
                    assert(isinstance(node_.right, values.ListValue) or isinstance(node_.right, values.TupleValue))
                    binops[nodes.BinOpType.Add] = 'ChainerGenericAdd'

                    left = ONNXValue(onnx_graph, node_.left)
                    right = ONNXValue(onnx_graph, node_.right)
                    seq_left = left.create_sequence()
                    seq_right = right.create_sequence()
                    onnx_graph.add_node(binops[node_.binop], [seq_left, seq_right], [value2onnx_parameter[node.outputs[0]].onnx_name], None)

                else:
                    onnx_node = oh.make_node(binops[node_.binop], [value2onnx_parameter[node_.left].onnx_name, value2onnx_parameter[node_.right].onnx_name], [value2onnx_parameter[node.outputs[0]].onnx_name])
                    onnx_graph.nodes.append(onnx_node)

            if isinstance(node, nodes.NodeUnaryOp):
                node_ = node # type: nodes.NodeUnaryOp

                if node_.unaryop == nodes.UnaryOpType.UAdd:
                    zero_ = onnx_graph.new_tensor_with_np(np.array(0, dtype=np.float), node2onnx_parameter[node_].onnx_name + '/Zero')
                    onnx_node = oh.make_node(
                        'Add',
                        [zero_.name, value2onnx_parameter[node_.operand].onnx_name],
                        [value2onnx_parameter[node.outputs[0]].onnx_name])
                    onnx_graph.nodes.append(onnx_node)

                if node_.unaryop == nodes.UnaryOpType.USub:
                    zero_ = onnx_graph.new_tensor_with_np(np.array(0, dtype=np.float), node2onnx_parameter[node_].onnx_name + '/Zero')
                    onnx_node = oh.make_node(
                        'Sub',
                        [zero_.name, value2onnx_parameter[node_.operand].onnx_name],
                        [value2onnx_parameter[node.outputs[0]].onnx_name])
                    onnx_graph.nodes.append(onnx_node)

                if node_.unaryop == nodes.UnaryOpType.Not:
                    onnx_node = oh.make_node(
                        'Not',
                        [value2onnx_parameter[node_.operand].onnx_name],
                        [value2onnx_parameter[node.outputs[0]].onnx_name])
                    onnx_graph.nodes.append(onnx_node)

            if isinstance(node, nodes.NodeCompare):
                node_ = node # type: nodes.NodeCompare

                op_str = None
                op_not = False

                if node_.compare == nodes.CompareType.Eq:
                    op_str = 'Equal'
                if node_.compare == nodes.CompareType.NotEq:
                    op_str = 'Equal'
                    op_not = True
                if node_.compare == nodes.CompareType.Gt:
                    op_str = 'Greater'
                if node_.compare == nodes.CompareType.GtE:
                    op_str = 'Less'
                    op_not = True
                if node_.compare == nodes.CompareType.Lt:
                    op_str = 'Less'
                if node_.compare == nodes.CompareType.LtE:
                    op_str = 'Greater'
                    op_not = True
                if node_.compare == nodes.CompareType.Is:
                    op_str = 'ChainerGenericIs'
                if node_.compare == nodes.CompareType.IsNot:
                    op_str = 'ChainerGenericIs'
                    op_not = True

                if op_not:
                    op_not_temp = onnx_graph.new_empty_tensor(['TODO'], np.bool, value2onnx_parameter[node.outputs[0]].onnx_name + '/NotTemp')
                    onnx_node1 = oh.make_node(op_str, [value2onnx_parameter[node_.left].onnx_name, value2onnx_parameter[node_.right].onnx_name], [op_not_temp.name])
                    onnx_node2 = oh.make_node('Not', [op_not_temp.name], [value2onnx_parameter[node.outputs[0]].onnx_name])
                    onnx_graph.nodes.append(onnx_node1)
                    onnx_graph.nodes.append(onnx_node2)
                else:
                    onnx_node = oh.make_node(op_str, [value2onnx_parameter[node_.left].onnx_name, value2onnx_parameter[node_.right].onnx_name], [value2onnx_parameter[node.outputs[0]].onnx_name])
                    onnx_graph.nodes.append(onnx_node)

            if isinstance(node, nodes.NodeGetItem):
                node_ = node # type: nodes.NodeGetItem
                if len(node_.indexes) == 1:

                    if isinstance(node_.target, values.ListValue) or isinstance(node_.target, values.RangeValue):
                        onnx_node = oh.make_node(
                            'ChainerSequenceLookup',
                            [value2onnx_parameter[node_.target].onnx_name, value2onnx_parameter[node_.indexes[0]].onnx_name],
                            [value2onnx_parameter[node.outputs[0]].onnx_name])
                        onnx_graph.nodes.append(onnx_node)

                    else:
                        onnx_node = oh.make_node(
                            'ChainerGetItem',
                            [value2onnx_parameter[node_.target].onnx_name, value2onnx_parameter[node_.indexes[0]].onnx_name],
                            [value2onnx_parameter[node.outputs[0]].onnx_name],
                            slice_specs=[1])
                        onnx_graph.nodes.append(onnx_node)
                else:
                    indices = []
                    slice_specs = []

                    for index in node_.indexes:
                        indices.append(value2onnx_parameter[index].onnx_name)
                        slice_specs.append(1)

                    onnx_node = oh.make_node(
                        'ChainerGetItem',
                        [value2onnx_parameter[node_.target].onnx_name] + indices,
                        [value2onnx_parameter[node.outputs[0]].onnx_name],
                        slice_specs=slice_specs)
                    onnx_graph.nodes.append(onnx_node)

            if isinstance(node, nodes.NodeSlice):
                node_ = node # type: nodes.NodeSlice

                indices = []

                for index in node_.indices:
                    indices.append(value2onnx_parameter[index].onnx_name)

                if isinstance(node_.target, values.ListValue):
                    onnx_node = oh.make_node(
                        'ChainerSequenceGetSlice',
                        [value2onnx_parameter[node_.target].onnx_name] + indices,
                        [value2onnx_parameter[node.outputs[0]].onnx_name])
                    onnx_graph.nodes.append(onnx_node)
                else:
                    onnx_node = oh.make_node(
                        'ChainerGetItem',
                        [value2onnx_parameter[node_.target].onnx_name] + indices,
                        [value2onnx_parameter[node.outputs[0]].onnx_name],
                        slice_specs=node_.slice_specs)
                    onnx_graph.nodes.append(onnx_node)


            if isinstance(node, nodes.NodeCall):

                if isinstance(node.func, functions_builtin.AppendFunction):
                    # append
                    onnx_node = oh.make_node(
                        "ChainerSequenceAppend",
                        [value2onnx_parameter[node.inputs[0]].onnx_name, value2onnx_parameter[node.inputs[1]].onnx_name],
                        [value2onnx_parameter[node.outputs[0]].onnx_name],
                        str(node.lineprop))
                    onnx_graph.nodes.append(onnx_node)

                if isinstance(node.func, functions_builtin.NDArrayShapeFunction):
                    # shape
                    op_shape_temp = onnx_graph.new_empty_tensor(['TODO'], np.int32, value2onnx_parameter[node.outputs[0]].onnx_name + '/ShapeTemp')

                    onnx_node = oh.make_node(
                        "Shape",
                        [value2onnx_parameter[node.inputs[0]].onnx_name],
                        [op_shape_temp.name],
                        str(node.lineprop))

                    onnx_graph.nodes.append(onnx_node)

                    onnx_node = oh.make_node(
                        "ChainerSequenceSeparate",
                        [op_shape_temp.name],
                        [value2onnx_parameter[node.outputs[0]].onnx_name],
                        str(node.lineprop))

                    onnx_graph.nodes.append(onnx_node)

                if isinstance(node.func, functions_builtin.ReluFunction):
                    # relu
                    onnx_node = oh.make_node("Relu", [value2onnx_parameter[node.inputs[0]].onnx_name], [value2onnx_parameter[node.outputs[0]].onnx_name])
                    onnx_graph.nodes.append(onnx_node)

                if isinstance(node.func, functions_builtin.SoftmaxFunction):
                    # softmax
                    onnx_node = oh.make_node(
                        "Softmax",
                        [value2onnx_parameter[node.inputs[0]].onnx_name],
                        [value2onnx_parameter[node.outputs[0]].onnx_name],
                        str(node.lineprop),
                        axis = onnx_graph.try_get_attribute(node.inputs[1]))

                    onnx_graph.nodes.append(onnx_node)

                if isinstance(node.func, functions_builtin.PadSequenceFunction):
                    # pad_sequence
                    kwargs = {}

                    if node.inputs[1] is not None:
                        value = onnx_graph.try_get_attribute(node.inputs[1])
                        if value is not None:
                            kwargs['length'] = value
                    if node.inputs[2] is not None:
                        value = onnx_graph.try_get_attribute(node.inputs[2])
                        if value != 0:
                            kwargs['value'] = float(value)

                    onnx_node = oh.make_node(
                        "ChainerSequencePad",
                        [value2onnx_parameter[node.inputs[0]].onnx_name],
                        [value2onnx_parameter[node.outputs[0]].onnx_name],
                        str(node.lineprop),
                        **kwargs)

                    onnx_graph.nodes.append(onnx_node)

                if isinstance(node.func, functions_builtin.SoftmaxCrossEntropyFunction):
                    # softmax_cross_entropy
                    onnx_node = oh.make_node(
                        "ChainerSoftmaxCrossEntropy",
                        [value2onnx_parameter[node.inputs[0]].onnx_name,
                         value2onnx_parameter[node.inputs[1]].onnx_name],
                        [value2onnx_parameter[node.outputs[0]].onnx_name],
                        str(node.lineprop))

                    onnx_graph.nodes.append(onnx_node)

                if isinstance(node.func, values_builtin.ChainerLinkFunction):
                    original_inst = node.func.owner.inst

                    if isinstance(original_inst, chainer.links.Linear):
                        convert_onnx_chainer_linear(onnx_graph, node)

                    if isinstance(original_inst, chainer.links.Convolution2D):
                        convert_onnx_chainer_convolution2d(onnx_graph, node)

            if isinstance(node, nodes.NodeIf):
                node_ = node # type: nodes.NodeIf

                true_graph = self.generate_graph(node_.true_graph.input_values, node_.true_graph.output_values, node_.true_graph, onnx_graph)
                false_graph = self.generate_graph(node_.false_graph.input_values, node_.false_graph.output_values, node_.false_graph, onnx_graph)

                onnx_node = oh.make_node(
                    'If',
                    [value2onnx_parameter[node_.cond].onnx_name] + [value2onnx_parameter[x].onnx_name for x in node.input_values],
                    [value2onnx_parameter[x].onnx_name for x in node.outputs],
                    then_branch=true_graph,
                    else_branch=false_graph)

                onnx_graph.nodes.append(onnx_node)

            if isinstance(node, nodes.NodeFor):
                node_ = node # type: nodes.NodeFor

                # get length of sequence
                op_len = onnx_graph.new_empty_tensor(['TODO'], np.int, value2onnx_parameter[node_.iter_value].onnx_name + '/Len')

                onnx_node = oh.make_node(
                    'ChainerGenericLen',
                    [value2onnx_parameter[node_.iter_value].onnx_name],
                    [op_len.name])
                onnx_graph.nodes.append(onnx_node)

                body_graph = self.generate_graph(node_.body_graph.input_values, node_.body_graph.output_values, node_.body_graph, onnx_graph)

                # for
                onnx_node = oh.make_node(
                    'Loop',
                    [op_len.name] + [""] + [value2onnx_parameter[node_.iter_value].onnx_name] + [value2onnx_parameter[x].onnx_name for x in node.input_values],
                    [value2onnx_parameter[x].onnx_name for x in node.outputs],
                    body=body_graph)
                onnx_graph.nodes.append(onnx_node)

            if isinstance(node, nodes.NodeForGenerator):
                node_ = node # type: nodes.NodeForGenerator

                # get value from sequence with index
                if isinstance(node_.iter_value, values.ListValue) or isinstance(node_.iter_value, values.RangeValue):
                    onnx_node = oh.make_node(
                        'ChainerSequenceLookup',
                        [value2onnx_parameter[node_.iter_value].onnx_name, value2onnx_parameter[node_.counter_value].onnx_name],
                        [value2onnx_parameter[node_.outputs[0]].onnx_name])
                    onnx_graph.nodes.append(onnx_node)
                else:
                    onnx_node = oh.make_node(
                        'ChainerGetItem',
                        [value2onnx_parameter[node_.iter_value].onnx_name, value2onnx_parameter[node_.counter_value].onnx_name],
                        [value2onnx_parameter[node_.outputs[0]].onnx_name],
                        slice_specs=[1])
                    onnx_graph.nodes.append(onnx_node)

            if isinstance(node, nodes.NodeListcomp):
                node_ = node # type: nodes.NodeListcomp

                # get length of sequence
                tensor_len = ONNXValue(onnx_graph, np.array(0).dtype, [value2onnx_parameter[node_.iter_value].onnx_name, '/Len'])

                onnx_graph.add_node(
                    'ChainerGenericLen',
                    [value2onnx_parameter[node_.iter_value].onnx_name],
                    [tensor_len],
                    str(node.lineprop))

                body_graph = self.generate_graph(node_.body_graph.input_values, node_.body_graph.output_values, node_.body_graph, onnx_graph)

                onnx_node = oh.make_node(
                    'Loop',
                    [tensor_len.name] + [""] + [value2onnx_parameter[node_.iter_value].onnx_name] + [value2onnx_parameter[x].onnx_name for x in node.input_values],
                    [value2onnx_parameter[x].onnx_name for x in node.outputs],
                    body=body_graph)

                onnx_graph.nodes.append(onnx_node)

            if isinstance(node, nodes.NodeConvert):
                node_ = node # type: nodes.NodeConvert
                if node_.classtype == 'List':

                     if isinstance(node_.value, values.ListValue):
                        onnx_node = oh.make_node(
                            "Identity",
                            [value2onnx_parameter[node.inputs[0]].onnx_name],
                            [value2onnx_parameter[node.outputs[0]].onnx_name],
                            str(node.lineprop))

                        onnx_graph.nodes.append(onnx_node)

                     else:
                        # not supported yet
                        assert False

                else:
                    # not supported yet
                    assert False

            if isinstance(node, nodes.NodeGenerate):
                node_ = node # type: nodes.NodeGenerate
                if node_.classtype == 'range':
                    onnx_node = oh.make_node(
                        "ChainerSequenceRange",
                        [value2onnx_parameter[input].onnx_name for input in node.inputs],
                        [value2onnx_parameter[node.outputs[0]].onnx_name],
                        str(node.lineprop))

                    onnx_graph.nodes.append(onnx_node)

                if node_.classtype == 'array':
                    dtype_value = onnx_graph.try_get_attribute(node.inputs[1])
                    if dtype_value is not None:
                        dtype = utils.int_2_numpy_type(dtype_value)
                    else:
                        dtype = None

                    copy = onnx_graph.try_get_attribute(node.inputs[2])
                    order = onnx_graph.try_get_attribute(node.inputs[3])
                    subok = onnx_graph.try_get_attribute(node.inputs[4])
                    ndmin = onnx_graph.try_get_attribute(node.inputs[5])

                    assert copy is True  # TODO(hamaji): Not supported yet.
                    assert order == 'K'  # TODO(hamaji): Not supported yet.
                    assert subok is False   # TODO(hamaji): Not supported yet.
                    assert ndmin == 0  # TODO(hamaji): Not supported yet.

                    value = ONNXValue(onnx_graph, node.inputs[0])
                    o = ONNXValue(onnx_graph, node.outputs[0])

                    if isinstance(node.inputs[0], values.ListValue):
                        if dtype is None:
                            onnx_node = onnx_graph.add_node(
                                "ChainerSequenceStack",
                                [value],
                                [o],
                                str(node.lineprop))
                        else:
                            casting_name = value2onnx_parameter[node.outputs[0]].onnx_name + '/Cast'
                            onnx_node = onnx_graph.add_node(
                                "ChainerSequenceStack",
                                [value],
                                [casting_name],
                                str(node.lineprop))

                            onnx_node = onnx_graph.add_node(
                                "Cast",
                                [casting_name],
                                [o],
                                str(node.lineprop),
                                to=get_onnx_dtype(dtype))
                    else:
                        onnx_node = onnx_graph.add_node(
                            "Identity",
                            [value],
                            [o],
                            str(node.lineprop))

                if node_.classtype == 'List':
                    onnx_node = oh.make_node(
                        "ChainerSequenceCreate",
                        [value2onnx_parameter[x].onnx_name for x in node.args],
                        [value2onnx_parameter[node.outputs[0]].onnx_name],
                        str(node.lineprop))
                    onnx_graph.nodes.append(onnx_node)

        onnx_graph.set_input(inputs)
        onnx_graph.set_output(outputs)

        return onnx_graph.generate_graph(graph.name, isMain=isMain)

    def generate_model(self, inputs, outputs, graph)-> 'ModelProto':
        assign_onnx_name(graph)

        graph_ = self.generate_graph(inputs, outputs, graph, None, True)
        model = oh.make_model(graph_, producer_name="elichika", producer_version="0.1")
        return model

class ONNXModel:
    def __init__(self):
        self.model = None
        self.inputs = []
        self.outputs = []

def compile_model(model, inputs) -> 'ONNXModel':
    # assign names
    assigned_names.clear()
    node2onnx_parameter.clear()
    value2onnx_parameter.clear()

    inputs_, outputs_, graph_ = core.convert_model(model, inputs)

    if graph_ is None:
        return None

    preprocess(graph_, True)

    generator = ONNXGenerator()
    model = generator.generate_model(graph_.input_values, graph_.output_values, graph_)

    # check inputs


    onnx_model = ONNXModel()
    onnx_model.model = model
    onnx_model.inputs = graph_.input_values
    onnx_model.outputs = graph_.output_values
    return onnx_model

def save_model(path : 'str', model : 'ModelProto'):
    with open(path, "wb") as f:
        f.write(model.SerializeToString())

def save_model_as_text(path : 'str', model : 'ModelProto'):
    with open(path, "w") as f:
        print(model, file=f)
