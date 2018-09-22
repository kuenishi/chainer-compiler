# coding: utf-8

import chainer
import chainer.links as L

# Network definition


class B(chainer.Chain):
    def __init__(self, n_out, p):
        super(B, self).__init__()
        with self.init_scope():
            self.l = L.Linear(None, n_out)
        self.p = p

    def forward(self, x):
        x = self.l(x) * self.p
        return x


class A(chainer.Chain):

    def __init__(self):
        super(A, self).__init__()
        with self.init_scope():
            self.l0 = L.Linear(3)
            self.l1 = B(10, 3.1)
            self.l2 = B(20, 4.2)

    def forward(self, x):
        x = self.l0(x)
        x = self.l1(x) + self.l2.p
        x = self.l2(x) + self.l1.p
        return x


# ======================================

import chainer2onnx


if __name__ == '__main__':
    import numpy as np
    np.random.seed(314)

    model = A()

    v = np.random.rand(10, 20).astype(np.float32)
    chainer2onnx.generate_testcase(model, [v])