"""구문 트리를 파이썬 클로저로 컴파일하고, 별도 스레드에서 가상 시간으로 실행합니다.

시간 모델: 문장 하나에 STEP µs, delay()는 가상 시간을 그만큼 진행합니다.
화면 쪽은 advance()로 '여기까지 진행해도 된다'는 예산(budget)을 늘려 주고,
실행기는 예산을 넘으면 sync()에서 기다립니다. 그래서 delay()가 UI를 막지 않고,
무한 루프여도 정지(stop) 요청을 다음 문장에서 바로 받습니다.
"""
import collections
import math
import random as _random
import sys
import threading
import time

from . import lang
from .lang import SketchError, josa
from . import libs

STEP = 2            # 문장 하나에 드는 가상 시간(µs)
MAX_DEPTH = 160     # 함수 호출 깊이(UNO 2KB RAM을 생각하면 넉넉함)
BRK, CNT, RET = 1, 2, 3


class StopSketch(BaseException):
    """정지 요청. 스케치 코드가 잡지 못하도록 BaseException."""


class RunError(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg


# ---------------------------------------------------------------- 형 변환
def _toint(v):
    if type(v) is int:
        return v
    if isinstance(v, float):
        if v != v or v in (math.inf, -math.inf):
            return 0
        return int(v)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, str):
        raise RunError('문자열을 숫자로 바로 쓸 수 없습니다. toInt()를 쓰십시오')
    if isinstance(v, list):
        raise RunError('배열을 숫자로 쓸 수 없습니다')
    return int(v)


def c_int(v):
    if type(v) is not int:
        v = _toint(v)
    return ((v + 32768) & 0xFFFF) - 32768


def c_uint(v):
    if type(v) is not int:
        v = _toint(v)
    return v & 0xFFFF


def c_long(v):
    if type(v) is not int:
        v = _toint(v)
    return ((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def c_ulong(v):
    if type(v) is not int:
        v = _toint(v)
    return v & 0xFFFFFFFF


def c_char(v):
    if type(v) is not int:
        v = _toint(v)
    return ((v + 128) & 0xFF) - 128


def c_uchar(v):
    if type(v) is not int:
        v = _toint(v)
    return v & 0xFF


def c_bool(v):
    if isinstance(v, str):
        return 1
    return 1 if v else 0


def c_float(v):
    if type(v) is float:
        return v
    if isinstance(v, str):
        raise RunError('문자열을 숫자로 바로 쓸 수 없습니다. toFloat()를 쓰십시오')
    return float(v)


def c_same(v):
    return v


CONV = {'int': c_int, 'uint': c_uint, 'long': c_long, 'ulong': c_ulong, 'char': c_char,
        'uchar': c_uchar, 'bool': c_bool, 'float': c_float}
INT_TYPES = {'bool', 'char', 'uchar', 'int', 'uint', 'long', 'ulong'}
NUM_TYPES = INT_TYPES | {'float'}
RANK = {'bool': 2, 'char': 2, 'uchar': 2, 'int': 2, 'uint': 3, 'long': 4, 'ulong': 5, 'float': 6}
RANK_NAME = {2: 'int', 3: 'uint', 4: 'long', 5: 'ulong', 6: 'float'}
SIZES = {'bool': 1, 'char': 1, 'uchar': 1, 'int': 2, 'uint': 2, 'long': 4, 'ulong': 4, 'float': 4,
         'String': 6, 'cstr': 2}


def arith_type(a, b):
    return RANK_NAME[max(RANK.get(a, 2), RANK.get(b, 2))]


def cdiv(a, b):
    if b == 0:
        raise RunError('0으로 나누었습니다')
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def cmod(a, b):
    if b == 0:
        raise RunError('0으로 나머지를 구했습니다')
    return a - b * cdiv(a, b)


def fdiv(a, b):
    if b == 0:
        if a == 0 or a != a:
            return math.nan
        return math.inf if a > 0 else -math.inf
    return a / b


def fmt_float(v, digits=2):
    if v != v:
        return 'nan'
    if v in (math.inf, -math.inf):
        return 'inf' if v > 0 else '-inf'
    digits = max(0, int(digits))
    s = f'{v:.{digits}f}'
    if s.startswith('-') and float(s) == 0:
        s = s[1:]
    return s


def fmt_int(v, base=10):
    v = int(v)
    if base == 10:
        return str(v)
    if v < 0:
        v &= 0xFFFFFFFF
    if base == 16:
        return f'{v:X}'
    if base == 2:
        return f'{v:b}'
    if base == 8:
        return f'{v:o}'
    raise RunError(f'{base}진법은 지원하지 않습니다')


def to_text(v, t, fmt=None):
    """Serial.print / String()에서 쓰는 글자 변환."""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        out = []
        for c in v:
            if isinstance(c, int):
                if c == 0:
                    break
                out.append(chr(c & 0xFF))
            else:
                raise RunError('이 배열은 글자로 출력할 수 없습니다. 원소를 하나씩 출력하십시오')
        return ''.join(out)
    if isinstance(v, libs.LibObject):
        raise RunError(f'{type(v).__name__} 객체는 출력할 수 없습니다')
    if t == 'float' or isinstance(v, float):
        return fmt_float(v, 2 if fmt is None else fmt)
    if t in ('char',) and fmt is None:
        return chr(v & 0xFF)
    return fmt_int(v, 10 if fmt is None else fmt)


class StrIndexLoc:
    """String 변수의 s[i] = c 를 위한 대리 컨테이너."""
    __slots__ = ('cont', 'key')

    def __init__(self, cont, key):
        self.cont, self.key = cont, key

    def __getitem__(self, i):
        return ord(self.cont[self.key][i])

    def __setitem__(self, i, v):
        s = self.cont[self.key]
        self.cont[self.key] = s[:i] + chr(v & 0xFF) + s[i + 1:]


# ---------------------------------------------------------------- 컴파일 단위
class Var:
    __slots__ = ('kind', 'idx', 'type', 'const', 'dims', 'cval', 'line')

    def __init__(self, kind, idx, type_, const=False, dims=None, cval=None, line=0):
        self.kind, self.idx, self.type, self.const, self.dims, self.cval, self.line = \
            kind, idx, type_, const, dims, cval, line


class Func:
    __slots__ = ('name', 'rtype', 'params', 'body', 'nslots', 'line', 'node', 'defaults')

    def __init__(self, name, rtype, params, line, node):
        self.name, self.rtype, self.params, self.line, self.node = name, rtype, params, line, node
        self.body = None
        self.nslots = 1
        self.defaults = []


BUILTIN_CONSTS = {
    'HIGH': (1, 'int'), 'LOW': (0, 'int'), 'INPUT': (0, 'int'), 'OUTPUT': (1, 'int'), 'INPUT_PULLUP': (2, 'int'),
    'LED_BUILTIN': (13, 'int'), 'true': (1, 'bool'), 'false': (0, 'bool'), 'TRUE': (1, 'bool'), 'FALSE': (0, 'bool'),
    'A0': (14, 'int'), 'A1': (15, 'int'), 'A2': (16, 'int'), 'A3': (17, 'int'), 'A4': (18, 'int'), 'A5': (19, 'int'),
    'PI': (math.pi, 'float'), 'HALF_PI': (math.pi / 2, 'float'), 'TWO_PI': (math.pi * 2, 'float'),
    'DEG_TO_RAD': (math.pi / 180, 'float'), 'RAD_TO_DEG': (180 / math.pi, 'float'), 'EULER': (math.e, 'float'),
    'DEC': (10, 'int'), 'HEX': (16, 'int'), 'OCT': (8, 'int'), 'BIN': (2, 'int'),
    'CHANGE': (1, 'int'), 'FALLING': (2, 'int'), 'RISING': (3, 'int'),
    'LSBFIRST': (0, 'int'), 'MSBFIRST': (1, 'int'), 'NULL': (0, 'int'), 'nullptr': (0, 'int'),
    'DHT11': (11, 'int'), 'DHT22': (22, 'int'), 'DHT21': (21, 'int'), 'AM2301': (21, 'int'),
    'NAN': (math.nan, 'float'), 'INFINITY': (math.inf, 'float'),
    'DEFAULT': (1, 'int'), 'INTERNAL': (3, 'int'), 'EXTERNAL': (0, 'int'),
    'SERIAL_8N1': (6, 'int'),
    'INT_MAX': (32767, 'int'), 'INT_MIN': (-32768, 'int'), 'LONG_MAX': (2147483647, 'long'),
    'LONG_MIN': (-2147483648, 'long'), 'UINT_MAX': (65535, 'uint'), 'ULONG_MAX': (4294967295, 'ulong'),
    'SDA': (18, 'int'), 'SCL': (19, 'int'),
}
for _i in range(14):
    BUILTIN_CONSTS[f'D{_i}'] = (_i, 'int')
del _i


class Compiler:
    def __init__(self, machine, includes):
        self.m = machine
        self.includes = includes
        self.G = []
        self.gscope = {}
        self.funcs = {}
        self.scopes = None
        self.nslots = 0
        self.cur = None
        self.ginit = []

    # --- 범위
    def declare(self, name, type_, line, const=False, dims=None, cval=None, static=False):
        if name in BUILTIN_CONSTS or name in BUILTINS or name in ('Serial', 'Wire'):
            raise SketchError(line, f"'{name}'{josa(name, '은는')} 이미 Arduino에서 쓰는 이름입니다")
        if self.scopes is None or static:
            if self.scopes is None and name in self.gscope:
                raise SketchError(line, f"'{name}'{josa(name, '이가')} 이미 선언되어 있습니다")
            idx = len(self.G)
            self.G.append(None)
            v = Var('g', idx, type_, const, dims, cval, line)
            if self.scopes is None:
                self.gscope[name] = v
            else:
                self.scopes[-1][name] = v
            return v
        if name in self.scopes[-1]:
            raise SketchError(line, f"'{name}'{josa(name, '이가')} 이 블록에 이미 선언되어 있습니다")
        self.nslots += 1
        v = Var('l', self.nslots, type_, const, dims, cval, line)
        self.scopes[-1][name] = v
        return v

    def lookup(self, name):
        if self.scopes:
            for sc in reversed(self.scopes):
                if name in sc:
                    return sc[name]
        return self.gscope.get(name)

    def need_lib(self, cls, line):
        if cls not in self.includes:
            hdr = {'Servo': 'Servo.h', 'LiquidCrystal_I2C': 'LiquidCrystal_I2C.h', 'DHT': 'DHT.h',
                   'TM1637Display': 'TM1637Display.h', 'LedControl': 'LedControl.h', 'Wire': 'Wire.h'}[cls]
            raise SketchError(line, f'{cls}를 쓰려면 맨 위에 #include <{hdr}>가 필요합니다')

    # --- 프로그램
    def compile(self, items):
        for it in items:
            if isinstance(it, lang.FuncDef):
                self.register_func(it)
        for it in items:
            if isinstance(it, lang.EnumDecl):
                self.enum(it)
            elif isinstance(it, lang.VarDecl):
                self.global_decl(it)
        for it in items:
            if isinstance(it, lang.FuncDef) and it.body is not None:
                self.compile_func(self.funcs[it.name], it)
        for name in ('setup', 'loop'):
            fi = self.funcs.get(name)
            if fi is None or fi.body is None:
                raise SketchError(0, f'{name}() 함수가 없습니다. void {name}() {{ }}를 만드십시오')
            if fi.params:
                raise SketchError(fi.line, f'{name}()에는 매개변수가 없어야 합니다')
        for fi in self.funcs.values():
            if fi.body is None:
                raise SketchError(fi.line, f"'{fi.name}' 함수는 선언만 있고 본문이 없습니다")
        return Program(self)

    def register_func(self, node):
        if node.name in BUILTINS:
            raise SketchError(node.line, f"'{node.name}'{josa(node.name, '은는')} Arduino 기본 함수 이름입니다. 다른 이름을 쓰십시오")
        params = []
        for p in node.params:
            t = p.type.base + '[]' * p.array
            params.append((p.name, t, p.ref, p.line, p.default))
        old = self.funcs.get(node.name)
        if old is not None:
            if old.body is not None and node.body is not None:
                raise SketchError(node.line, f"'{node.name}' 함수가 두 번 만들어져 있습니다. 이름이 같은 함수는 하나만 만들 수 있습니다")
            if len(old.params) != len(params):
                raise SketchError(node.line, f"'{node.name}' 함수의 선언과 본문에서 매개변수 개수가 다릅니다. 이름이 같은 함수는 하나만 만들 수 있습니다")
            if node.body is not None:
                old.params = params
                old.line = node.line
                old.node = node
            return
        self.funcs[node.name] = Func(node.name, node.rtype.base, params, node.line, node)

    def enum(self, it):
        val = 0
        for name, e in it.items:
            if e is not None:
                val = self.const_eval(e)
            self.declare(name, 'int', it.line, True, cval=val)
            self.G[self.gscope[name].idx] = val
            val += 1

    def global_decl(self, d):
        for dec in d.decls:
            self.var_decl(d.type, dec, d.line, glob=True)

    def compile_func(self, fi, node):
        self.cur = fi
        self.scopes = [{}]
        self.nslots = 0
        for name, t, ref, line, default in fi.params:
            if name is None:
                self.nslots += 1
                continue
            v = self.declare(name, t, line)
            if ref:
                v.kind = 'ref'
        fi.defaults = []
        for name, t, ref, line, default in fi.params:
            fi.defaults.append(None if default is None else self.expr(default))
        fi.body = self.block(node.body, new_scope=False)
        fi.nslots = self.nslots + 1
        self.scopes = None
        self.cur = None

    # --- 상수식
    def const_eval(self, e):
        if isinstance(e, lang.Num):
            return e.val
        if isinstance(e, lang.Name):
            if e.id in BUILTIN_CONSTS:
                return BUILTIN_CONSTS[e.id][0]
            v = self.lookup(e.id)
            if v is not None and v.cval is not None:
                return v.cval
            raise SketchError(e.line, f"'{e.id}'{josa(e.id, '은는')} 상수가 아니어서 여기에 쓸 수 없습니다")
        if isinstance(e, lang.Unary):
            x = self.const_eval(e.e)
            return {'-': lambda: -x, '+': lambda: x, '!': lambda: int(not x), '~': lambda: ~x}[e.op]()
        if isinstance(e, lang.Bin):
            a, b = self.const_eval(e.l), self.const_eval(e.r)
            ops = {'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b,
                   '/': lambda: cdiv(a, b) if isinstance(a, int) and isinstance(b, int) else a / b,
                   '%': lambda: cmod(a, b), '<<': lambda: a << b, '>>': lambda: a >> b,
                   '&': lambda: a & b, '|': lambda: a | b, '^': lambda: a ^ b,
                   '==': lambda: int(a == b), '!=': lambda: int(a != b), '<': lambda: int(a < b),
                   '>': lambda: int(a > b), '<=': lambda: int(a <= b), '>=': lambda: int(a >= b),
                   '&&': lambda: int(bool(a and b)), '||': lambda: int(bool(a or b))}
            try:
                return ops[e.op]()
            except RunError as err:
                raise SketchError(e.line, err.msg)
        if isinstance(e, lang.Cast):
            return CONV.get(e.type.base, c_same)(self.const_eval(e.e))
        if isinstance(e, lang.SizeOf):
            return self.sizeof(e)
        if isinstance(e, lang.Cond):
            return self.const_eval(e.a) if self.const_eval(e.c) else self.const_eval(e.b)
        raise SketchError(e.line, '여기에는 상수 값이 필요합니다')

    def sizeof(self, e):
        if e.type is not None:
            return SIZES.get(e.type.base, 2)
        x = e.e
        depth = 0
        while isinstance(x, lang.Index):
            depth += 1
            x = x.arr
        if isinstance(x, lang.Name):
            v = self.lookup(x.id)
            if v is not None:
                base = v.type.replace('[]', '')
                size = SIZES.get(base, 2)
                if v.dims:
                    for d in v.dims[depth:]:
                        size *= d
                return size
        if isinstance(x, lang.Str):
            return len(x.val) + 1
        _, t = self.expr(e.e)
        return SIZES.get(t.replace('[]', ''), 2)

    # --- 선언
    def var_decl(self, typ, dec, line, glob=False):
        base = typ.base
        if base == 'void':
            raise SketchError(line, "변수 자료형으로 void를 쓸 수 없습니다")
        if base in lang.LIB_CLASSES:
            self.need_lib(base, line)
        dims = []
        init = dec.init
        for d in dec.dims:
            if d is None:
                dims.append(None)
            else:
                n = self.const_eval(d)
                if not isinstance(n, int) or n <= 0:
                    raise SketchError(line, '배열 크기는 1 이상의 정수여야 합니다')
                dims.append(n)
        if dims and dims[0] is None:
            if isinstance(init, lang.InitList):
                dims[0] = len(init.items)
            elif isinstance(init, lang.Str):
                dims[0] = len(init.val) + 1
            else:
                raise SketchError(line, f"배열 '{dec.name}'의 크기를 알 수 없습니다")
        if any(d is None for d in dims):
            raise SketchError(line, '2차원 이상 배열은 첫 번째 [ ]를 빼고 크기를 모두 적어야 합니다. 예: int a[][3]')
        t = base + '[]' * len(dims)
        cval = None
        if typ.const and not dims and init is not None and base in NUM_TYPES:
            try:
                cval = CONV[base](self.const_eval(init))
            except SketchError:
                cval = None
        static = typ.static and self.scopes is not None
        # 초기값 식은 변수 선언 전에 컴파일(int x = x; 방지)
        maker = self.initializer(base, dims, init, dec.ctor, line, dec.name)
        v = self.declare(dec.name, t, line, typ.const, dims or None, cval, static=static)
        if v.kind == 'g':
            G = self.G
            idx = v.idx

            def ginit(f, maker=maker):
                G[idx] = maker(f)
            if glob or static:
                self.ginit.append((line, ginit))
                if static:
                    return None
            return None
        idx = v.idx
        m = self.m

        def run(f):
            m.line = line
            f[idx] = maker(f)
            return 0
        return run

    def initializer(self, base, dims, init, ctor, line, name):
        """선언된 변수의 처음 값을 만드는 함수(f → 값)."""
        if base in lang.LIB_CLASSES:
            cls = libs.CLASSES[base]
            args = [self.expr(a) for a in (ctor or [])]
            if init is not None:
                raise SketchError(line, f'{base} 객체는 = 로 초기화할 수 없습니다')
            m = self.m

            def make_obj(f):
                return cls(m, [a(f) for a, _ in args], line)
            if dims:
                return self.array_maker(dims, None, make_obj, base, line)
            return make_obj
        if ctor is not None:
            if dims or len(ctor) != 1:
                raise SketchError(line, f"'{name}' 선언을 이해하지 못했습니다")
            init = ctor[0]
        if dims:
            if base in ('char', 'uchar') and isinstance(init, lang.Str):
                s = [ord(c) & 0xFF for c in init.val] + [0]
                if len(s) > dims[0]:
                    raise SketchError(line, f'문자열이 배열 크기({dims[0]})보다 깁니다 (끝의 0 포함)')
                s += [0] * (dims[0] - len(s))
                return lambda f: list(s)
            if init is not None and not isinstance(init, lang.InitList):
                raise SketchError(line, '배열은 { } 목록으로 초기화하십시오')
            zero = self.zero(base)
            return self.array_maker(dims, init, lambda f: zero, base, line)
        if isinstance(init, lang.InitList):
            if len(init.items) == 1:
                init = init.items[0]
            elif not init.items:
                init = None
            else:
                raise SketchError(line, '배열이 아닌 변수에 { } 목록을 넣을 수 없습니다')
        if init is None:
            z = self.zero(base)
            return lambda f: z
        fn, t = self.expr(init)
        return self.converter(fn, t, base, line)

    def array_maker(self, dims, init, zero_fn, base, line):
        if init is not None:
            items = self.init_items(dims, init, base, line)
        else:
            items = None

        def build(f, level=0, items=items):
            n = dims[level]
            if level == len(dims) - 1:
                if items is None:
                    return [zero_fn(f) for _ in range(n)]
                out = [fn(f) for fn in items]
                out += [zero_fn(f) for _ in range(n - len(out))]
                return out
            if items is None:
                return [build(f, level + 1, None) for _ in range(n)]
            out = [build(f, level + 1, sub) for sub in items]
            out += [build(f, level + 1, None) for _ in range(n - len(out))]
            return out
        return build

    def init_items(self, dims, init, base, line):
        if len(init.items) > dims[0]:
            raise SketchError(line, f'초기값이 배열 크기({dims[0]})보다 많습니다')
        if len(dims) == 1:
            out = []
            for it in init.items:
                if isinstance(it, lang.InitList):
                    raise SketchError(line, '1차원 배열에 중괄호가 너무 많습니다')
                fn, t = self.expr(it)
                out.append(self.converter(fn, t, base, line))
            return out
        out = []
        for it in init.items:
            if isinstance(it, lang.Str) and base in ('char', 'uchar') and len(dims) == 2:
                s = [ord(c) & 0xFF for c in it.val] + [0]
                s += [0] * (dims[1] - len(s))
                out.append([(lambda f, c=c: c) for c in s[:dims[1]]])
            elif not isinstance(it, lang.InitList):
                raise SketchError(line, '다차원 배열은 { {..}, {..} } 형태로 초기화하십시오')
            else:
                out.append(self.init_items(dims[1:], it, base, line))
        return out

    @staticmethod
    def zero(base):
        if base == 'float':
            return 0.0
        if base in ('String', 'cstr'):
            return ''
        return 0

    def converter(self, fn, src, dst, line):
        """값 fn(자료형 src)을 dst 자료형으로 바꾸는 함수."""
        if src == 'void':
            raise SketchError(line, 'void 함수는 값을 돌려주지 않아서 결과를 쓸 수 없습니다')
        if dst in CONV:
            if src in ('String', 'cstr'):
                if dst in ('char', 'uchar') and src == 'cstr':
                    pass
                raise SketchError(line, f'문자열을 {dst} 변수에 넣을 수 없습니다')
            if src.endswith('[]'):
                raise SketchError(line, '배열을 숫자 변수에 넣을 수 없습니다')
            if src in lang.LIB_CLASSES:
                raise SketchError(line, f'{src} 객체를 숫자 변수에 넣을 수 없습니다')
            if src == dst and dst != 'float':
                return fn
            c = CONV[dst]
            return lambda f: c(fn(f))
        if dst == 'String':
            if src in ('String', 'cstr'):
                return fn
            return lambda f: to_text(fn(f), src)
        if dst == 'cstr':
            if src in ('String', 'cstr') or src in ('char[]', 'uchar[]'):
                if src.endswith('[]'):
                    return lambda f: to_text(fn(f), src)
                return fn
            raise SketchError(line, 'char* 변수에는 문자열만 넣을 수 있습니다')
        if dst.endswith('[]'):
            if src != dst and not (src.replace('uchar', 'char') == dst.replace('uchar', 'char')):
                raise SketchError(line, f'{src} 값을 {dst} 배열 매개변수로 넘길 수 없습니다')
            return fn
        if dst in lang.LIB_CLASSES:
            if src != dst:
                raise SketchError(line, f'{dst} 자리에 다른 값을 넣을 수 없습니다')
            return fn
        return fn

    # --- 문장
    def block(self, node, new_scope=True):
        if new_scope:
            self.scopes.append({})
        stmts = []
        for s in node.stmts:
            r = self.stmt(s)
            if r is not None:
                stmts.append(r)
        if new_scope:
            self.scopes.pop()
        stmts = tuple(stmts)
        if len(stmts) == 1:
            return stmts[0]

        def run(f):
            for s in stmts:
                r = s(f)
                if r:
                    return r
            return 0
        return run

    def stmt(self, s):
        m = self.m
        line = s.line
        if isinstance(s, lang.ExprStmt):
            e, _ = self.expr(s.e)

            def run(f):
                m.line = line
                m.t += STEP
                if m.t >= m.budget:
                    m.sync()
                e(f)
                return 0
            return run
        if isinstance(s, lang.VarDecl):
            if s.type.base in ('void',):
                raise SketchError(line, '변수 자료형으로 void를 쓸 수 없습니다')
            runs = [r for r in (self.var_decl(s.type, d, line) for d in s.decls) if r is not None]
            if not runs:
                return None
            if len(runs) == 1:
                return runs[0]

            def run(f):
                for r in runs:
                    r(f)
                return 0
            return run
        if isinstance(s, lang.Block):
            return self.block(s)
        if isinstance(s, lang.Empty):
            return None
        if isinstance(s, lang.If):
            c = self.cond(s.c)
            then = self.sub_stmt(s.then)
            other = self.sub_stmt(s.other) if s.other is not None else None

            def run(f):
                m.line = line
                m.t += STEP
                if m.t >= m.budget:
                    m.sync()
                if c(f):
                    return then(f)
                if other is not None:
                    return other(f)
                return 0
            return run
        if isinstance(s, lang.While):
            c = self.cond(s.c)
            self.scopes.append({})
            body = self.sub_stmt(s.body)
            self.scopes.pop()

            def run(f):
                while True:
                    m.line = line
                    m.t += STEP
                    if m.t >= m.budget:
                        m.sync()
                    if not c(f):
                        return 0
                    r = body(f)
                    if r:
                        if r == BRK:
                            return 0
                        if r == RET:
                            return r
            return run
        if isinstance(s, lang.DoWhile):
            c = self.cond(s.c)
            body = self.sub_stmt(s.body)

            def run(f):
                while True:
                    m.line = line
                    m.t += STEP
                    if m.t >= m.budget:
                        m.sync()
                    r = body(f)
                    if r:
                        if r == BRK:
                            return 0
                        if r == RET:
                            return r
                    if not c(f):
                        return 0
            return run
        if isinstance(s, lang.For):
            self.scopes.append({})
            init = self.stmt(s.init) if s.init is not None else None
            c = self.cond(s.c) if s.c is not None else None
            step = self.expr(s.step)[0] if s.step is not None else None
            body = self.sub_stmt(s.body)
            self.scopes.pop()

            def run(f):
                if init is not None:
                    init(f)
                while True:
                    m.line = line
                    m.t += STEP
                    if m.t >= m.budget:
                        m.sync()
                    if c is not None and not c(f):
                        return 0
                    r = body(f)
                    if r:
                        if r == BRK:
                            return 0
                        if r == RET:
                            return r
                    if step is not None:
                        step(f)
            return run
        if isinstance(s, lang.Switch):
            return self.switch(s)
        if isinstance(s, (lang.Case, lang.Default)):
            raise SketchError(line, 'case/default는 switch 안에만 쓸 수 있습니다')
        if isinstance(s, lang.Break):
            return lambda f: BRK
        if isinstance(s, lang.Continue):
            return lambda f: CNT
        if isinstance(s, lang.Return):
            fi = self.cur
            if s.e is None:
                if fi.rtype != 'void':
                    raise SketchError(line, f'{fi.name}(){josa(fi.name, '은는')} 값을 돌려줘야 합니다')
                return lambda f: RET
            if fi.rtype == 'void':
                raise SketchError(line, f'void 함수 {fi.name}(){josa(fi.name, '은는')} 값을 돌려줄 수 없습니다')
            e, t = self.expr(s.e)
            e = self.converter(e, t, fi.rtype, line)

            def run(f):
                m.line = line
                f[0] = e(f)
                return RET
            return run
        raise SketchError(line, '이 문장은 지원하지 않습니다')

    def sub_stmt(self, s):
        r = self.stmt(s)
        if r is None:
            return lambda f: 0
        return r

    def switch(self, s):
        m = self.m
        line = s.line
        e, t = self.expr(s.e)
        if t not in INT_TYPES:
            raise SketchError(line, 'switch에는 정수 값만 쓸 수 있습니다')
        self.scopes.append({})
        table = {}
        default = None
        stmts = []
        for st in s.body.stmts:
            if isinstance(st, lang.Case):
                v = self.const_eval(st.e)
                if v in table:
                    raise SketchError(st.line, f'case {v}가 두 번 있습니다')
                table[v] = len(stmts)
            elif isinstance(st, lang.Default):
                default = len(stmts)
            else:
                r = self.stmt(st)
                if r is not None:
                    stmts.append(r)
        self.scopes.pop()
        n = len(stmts)
        stmts = tuple(stmts)

        def run(f):
            m.line = line
            m.t += STEP
            if m.t >= m.budget:
                m.sync()
            start = table.get(e(f), default)
            if start is None:
                return 0
            for i in range(start, n):
                r = stmts[i](f)
                if r:
                    return 0 if r == BRK else r
            return 0
        return run

    def cond(self, node):
        fn, t = self.expr(node)
        if t in lang.LIB_CLASSES:
            raise SketchError(node.line, f'{t} 객체는 조건으로 쓸 수 없습니다')
        if t == 'String':
            raise SketchError(node.line, 'String은 조건으로 쓸 수 없습니다. length() > 0 처럼 비교하십시오')
        return fn

    # --- 식
    def expr(self, e):
        meth = getattr(self, 'x_' + type(e).__name__, None)
        if meth is None:
            raise SketchError(e.line, '이 식은 지원하지 않습니다')
        return meth(e)

    def x_Num(self, e):
        v = e.val
        return (lambda f: v), e.ntype

    def x_Str(self, e):
        v = e.val
        return (lambda f: v), 'cstr'

    def x_InitList(self, e):
        raise SketchError(e.line, '{ } 목록은 변수를 선언할 때만 쓸 수 있습니다')

    def x_Name(self, e):
        v = self.lookup(e.id)
        if v is None:
            if e.id in BUILTIN_CONSTS:
                c, t = BUILTIN_CONSTS[e.id]
                return (lambda f: c), t
            if e.id == 'Serial':
                return (lambda f: 1), 'bool'
            if e.id in self.funcs or e.id in BUILTINS:
                raise SketchError(e.line, f"함수 '{e.id}' 뒤에 ()가 필요합니다")
            raise SketchError(e.line, f"'{e.id}'{josa(e.id, '은는')} 아직 선언하지(만들지) 않은 이름입니다")
        i = v.idx
        if v.cval is not None:
            c = v.cval
            return (lambda f: c), v.type
        if v.kind == 'l':
            return (lambda f: f[i]), v.type
        if v.kind == 'g':
            G = self.G
            return (lambda f: G[i]), v.type

        def ref(f):
            c, k = f[i]
            return c[k]
        return ref, v.type

    def loc(self, e):
        """대입 대상: (f → (컨테이너, 키), 자료형)"""
        if isinstance(e, lang.Name):
            v = self.lookup(e.id)
            if v is None:
                if e.id in BUILTIN_CONSTS:
                    raise SketchError(e.line, f"'{e.id}'{josa(e.id, '은는')} 상수라서 값을 넣을 수 없습니다")
                raise SketchError(e.line, f"'{e.id}'{josa(e.id, '은는')} 아직 선언하지(만들지) 않은 이름입니다")
            if v.const:
                raise SketchError(e.line, f"const 변수 '{e.id}'에는 값을 넣을 수 없습니다")
            if v.dims:
                raise SketchError(e.line, f"배열 '{e.id}' 전체에 한 번에 값을 넣을 수 없습니다")
            i = v.idx
            if v.kind == 'l':
                return (lambda f: (f, i)), v.type
            if v.kind == 'g':
                G = self.G
                return (lambda f: (G, i)), v.type
            return (lambda f: f[i]), v.type
        if isinstance(e, lang.Index):
            arr, at = self.expr(e.arr)
            idx, it = self.expr(e.idx)
            if it not in INT_TYPES:
                raise SketchError(e.line, '배열 인덱스는 정수여야 합니다')
            if at == 'String':
                inner, _ = self.loc(e.arr)

                def sloc(f):
                    c, k = inner(f)
                    i = idx(f)
                    if not 0 <= i < len(c[k]):
                        raise RunError(f'문자열 범위를 벗어났습니다: 인덱스 {i}, 길이 {len(c[k])}')
                    return StrIndexLoc(c, k), i
                return sloc, 'char'
            if not at.endswith('[]'):
                raise SketchError(e.line, '배열이 아닌 값에 [ ]를 쓸 수 없습니다')
            if isinstance(e.arr, lang.Name):
                v = self.lookup(e.arr.id)
                if v is not None and v.const:
                    raise SketchError(e.line, f"const 배열 '{e.arr.id}'에는 값을 넣을 수 없습니다")

            def aloc(f):
                a = arr(f)
                i = idx(f)
                if 0 <= i < len(a):
                    return a, i
                raise RunError(f'배열 범위를 벗어났습니다. 크기가 {len(a)}이면 0~{len(a) - 1}번 칸만 쓸 수 있는데 {i}번 칸을 썼습니다')
            return aloc, at[:-2]
        raise SketchError(e.line, '여기에는 값을 넣을 수 없습니다 (변수나 배열 원소가 필요합니다)')

    def x_Index(self, e):
        arr, at = self.expr(e.arr)
        idx, it = self.expr(e.idx)
        if it not in INT_TYPES:
            raise SketchError(e.line, '배열 인덱스는 정수여야 합니다')
        if at in ('String', 'cstr'):
            def sidx(f):
                s = arr(f)
                i = idx(f)
                if 0 <= i < len(s):
                    return ord(s[i]) & 0xFF
                if i == len(s):
                    return 0
                raise RunError(f'문자열 범위를 벗어났습니다: 인덱스 {i}, 길이 {len(s)}')
            return sidx, 'char'
        if not at.endswith('[]'):
            raise SketchError(e.line, '배열이 아닌 값에 [ ]를 쓸 수 없습니다')

        def aidx(f):
            a = arr(f)
            i = idx(f)
            if 0 <= i < len(a):
                return a[i]
            raise RunError(f'배열 범위를 벗어났습니다. 크기가 {len(a)}이면 0~{len(a) - 1}번 칸만 쓸 수 있는데 {i}번 칸을 썼습니다')
        return aidx, at[:-2]

    def x_Assign(self, e):
        loc, t = self.loc(e.target)
        val, vt = self.expr(e.value)
        line = e.line
        if e.op == '=':
            if isinstance(e.value, lang.InitList):
                raise SketchError(line, '{ } 목록은 선언할 때만 쓸 수 있습니다')
            conv = self.converter(val, vt, t, line)
            if isinstance(e.target, lang.Name):
                v = self.lookup(e.target.id)
                i = v.idx
                if v.kind == 'l':
                    def set_local(f):
                        x = conv(f)
                        f[i] = x
                        return x
                    return set_local, t
                if v.kind == 'g':
                    G = self.G

                    def set_global(f):
                        x = conv(f)
                        G[i] = x
                        return x
                    return set_global, t

            def assign(f):
                c, k = loc(f)
                x = conv(f)
                c[k] = x
                return x
            return assign, t
        op = e.op[:-1]
        if t == 'String':
            if op != '+':
                raise SketchError(line, f'String에는 {e.op}를 쓸 수 없습니다')

            def sappend(f):
                c, k = loc(f)
                x = c[k] + to_text(val(f), vt)
                c[k] = x
                return x
            return sappend, t
        if t not in NUM_TYPES:
            raise SketchError(line, f'{t}에는 {e.op}를 쓸 수 없습니다')
        if vt not in NUM_TYPES:
            raise SketchError(line, f'숫자가 아닌 값으로 {e.op}를 할 수 없습니다')
        opfn, rt = self.binop(op, t, vt, line)
        conv = CONV[t]

        def compound(f):
            c, k = loc(f)
            x = conv(opfn(c[k], val(f)))
            c[k] = x
            return x
        return compound, t

    def binop(self, op, lt, rt, line):
        """(a, b) → 값 함수와 결과 자료형 (숫자끼리)."""
        res = arith_type(lt, rt)
        if op in ('&', '|', '^', '<<', '>>', '%') and res == 'float':
            if op == '%':
                return (lambda a, b: math.fmod(a, b) if b else math.nan), 'float'
            raise SketchError(line, f"실수(float)에는 '{op}' 연산을 쓸 수 없습니다")
        if op in ('<<', '>>'):
            res = arith_type(lt, 'int')
        w = CONV[res]
        if res == 'float':
            table = {'+': lambda a, b: a + b, '-': lambda a, b: a - b, '*': lambda a, b: a * b, '/': fdiv}
            return table[op], res
        table = {
            '+': lambda a, b: w(a + b), '-': lambda a, b: w(a - b), '*': lambda a, b: w(a * b),
            '/': lambda a, b: w(cdiv(a, b)), '%': lambda a, b: w(cmod(a, b)),
            '&': lambda a, b: w(a & b), '|': lambda a, b: w(a | b), '^': lambda a, b: w(a ^ b),
            '<<': lambda a, b: w(a << b) if 0 <= b < 64 else 0,
            '>>': lambda a, b: w(a >> b) if 0 <= b < 64 else (0 if a >= 0 else -1),
        }
        return table[op], res

    def x_Bin(self, e):
        op = e.op
        a, at = self.expr(e.l)
        b, bt = self.expr(e.r)
        line = e.line
        if op == '&&':
            return (lambda f: 1 if a(f) and b(f) else 0), 'bool'
        if op == '||':
            return (lambda f: 1 if a(f) or b(f) else 0), 'bool'
        strs = ('String', 'cstr')
        if op == '+' and (at == 'String' or bt == 'String'):
            return (lambda f: to_text(a(f), at) + to_text(b(f), bt)), 'String'
        if at in strs or bt in strs:
            if op == '+':
                raise SketchError(line, '문자열 리터럴은 +로 이을 수 없습니다. String("...")으로 감싸십시오')
            if op in ('==', '!=', '<', '>', '<=', '>='):
                if not (at in strs and bt in strs):
                    if (at in strs and bt == 'char[]') or (bt in strs and at == 'char[]'):
                        pass
                    else:
                        raise SketchError(line, '문자열과 숫자는 비교할 수 없습니다')
                if at == 'cstr' and bt == 'cstr':
                    raise SketchError(line, '문자열 리터럴끼리는 ==로 비교할 수 없습니다. String을 쓰십시오')
                a2 = (lambda f: to_text(a(f), at)) if at == 'char[]' else a
                b2 = (lambda f: to_text(b(f), bt)) if bt == 'char[]' else b
                return self.compare(op, a2, b2), 'bool'
            raise SketchError(line, f"문자열에는 '{op}' 연산을 쓸 수 없습니다")
        for t in (at, bt):
            if t not in NUM_TYPES:
                raise SketchError(line, f"{t} 값에는 '{op}' 연산을 쓸 수 없습니다")
        if op in ('==', '!=', '<', '>', '<=', '>='):
            return self.compare(op, a, b), 'bool'
        fn, rt = self.binop(op, at, bt, line)
        if op == '+' and rt != 'float':
            w = CONV[rt]
            return (lambda f: w(a(f) + b(f))), rt
        if op == '-' and rt != 'float':
            w = CONV[rt]
            return (lambda f: w(a(f) - b(f))), rt
        if op == '+':
            return (lambda f: a(f) + b(f)), rt
        return (lambda f: fn(a(f), b(f))), rt

    @staticmethod
    def compare(op, a, b):
        if op == '==':
            return lambda f: 1 if a(f) == b(f) else 0
        if op == '!=':
            return lambda f: 1 if a(f) != b(f) else 0
        if op == '<':
            return lambda f: 1 if a(f) < b(f) else 0
        if op == '>':
            return lambda f: 1 if a(f) > b(f) else 0
        if op == '<=':
            return lambda f: 1 if a(f) <= b(f) else 0
        return lambda f: 1 if a(f) >= b(f) else 0

    def x_Unary(self, e):
        a, t = self.expr(e.e)
        if e.op == '!':
            if t == 'String':
                raise SketchError(e.line, 'String에는 !를 쓸 수 없습니다')
            return (lambda f: 0 if a(f) else 1), 'bool'
        if t not in NUM_TYPES:
            raise SketchError(e.line, f"{t} 값에는 '{e.op}'를 쓸 수 없습니다")
        rt = arith_type(t, 'int')
        if e.op == '+':
            return a, rt
        if e.op == '-':
            if rt == 'float':
                return (lambda f: -a(f)), rt
            w = CONV[rt]
            return (lambda f: w(-a(f))), rt
        if rt == 'float':
            raise SketchError(e.line, "실수(float)에는 '~'를 쓸 수 없습니다")
        w = CONV[rt]
        return (lambda f: w(~a(f))), rt

    def x_IncDec(self, e):
        loc, t = self.loc(e.e)
        if t not in NUM_TYPES:
            raise SketchError(e.line, f'{t} 값에는 {e.op}를 쓸 수 없습니다')
        d = 1 if e.op == '++' else -1
        conv = CONV[t]
        if isinstance(e.e, lang.Name):
            v = self.lookup(e.e.id)
            i = v.idx
            if v.kind in ('l', 'g'):
                store = None if v.kind == 'l' else self.G
                if e.post:
                    if store is None:
                        def post_l(f):
                            x = f[i]
                            f[i] = conv(x + d)
                            return x
                        return post_l, t

                    def post_g(f):
                        x = store[i]
                        store[i] = conv(x + d)
                        return x
                    return post_g, t
        if e.post:
            def post(f):
                c, k = loc(f)
                x = c[k]
                c[k] = conv(x + d)
                return x
            return post, t

        def pre(f):
            c, k = loc(f)
            x = conv(c[k] + d)
            c[k] = x
            return x
        return pre, t

    def x_Cond(self, e):
        c = self.cond(e.c)
        a, at = self.expr(e.a)
        b, bt = self.expr(e.b)
        if at == bt:
            t = at
        elif at in NUM_TYPES and bt in NUM_TYPES:
            t = arith_type(at, bt)
            if t == 'float':
                a0, b0 = a, b
                a = lambda f: float(a0(f))
                b = lambda f: float(b0(f))
        elif {at, bt} <= {'String', 'cstr'}:
            t = 'String'
        else:
            raise SketchError(e.line, '? : 양쪽 값의 자료형이 맞지 않습니다')
        return (lambda f: a(f) if c(f) else b(f)), t

    def x_Comma(self, e):
        fns = [self.expr(x) for x in e.items]
        last_t = fns[-1][1]
        fs = [fn for fn, _ in fns]

        def run(f):
            r = None
            for fn in fs:
                r = fn(f)
            return r
        return run, last_t

    def x_Cast(self, e):
        a, t = self.expr(e.e)
        dst = e.type.base
        if dst in CONV:
            if t in ('String',):
                raise SketchError(e.line, f'String을 ({dst})로 바꿀 수 없습니다. toInt()/toFloat()를 쓰십시오')
            if t == 'cstr' and dst not in ('char', 'uchar'):
                raise SketchError(e.line, f'문자열을 ({dst})로 바꿀 수 없습니다')
            c = CONV[dst]
            return (lambda f: c(a(f))), dst
        if dst == 'String':
            return (lambda f: to_text(a(f), t)), 'String'
        raise SketchError(e.line, f'({dst})로 바꿀 수 없습니다')

    def x_SizeOf(self, e):
        v = self.sizeof(e)
        return (lambda f: v), 'uint'

    def x_Member(self, e):
        raise SketchError(e.line, f"'.{e.name}' 뒤에 ( )가 필요합니다")

    def x_Call(self, e):
        name = e.name
        fi = self.funcs.get(name)
        if fi is not None:
            return self.user_call(fi, e)
        v = self.lookup(name)
        if v is not None:
            raise SketchError(e.line, f"'{name}'{josa(name, '은는')} 함수가 아닙니다")
        b = BUILTINS.get(name)
        if b is None:
            raise SketchError(e.line, f"'{name}' 함수를 찾을 수 없습니다. 이름이 맞는지, 함수를 만들었는지 확인하십시오")
        return b(self, e)

    def user_call(self, fi, e):
        line = e.line
        params = fi.params
        if len(e.args) > len(params):
            raise SketchError(line, f'{fi.name}()에는 인자가 {len(params)}개 필요합니다 ({len(e.args)}개를 넣었습니다)')
        nreq = sum(1 for p in params if p[4] is None)
        if len(e.args) < nreq:
            raise SketchError(line, f'{fi.name}()에는 인자가 {nreq}개 필요합니다 ({len(e.args)}개를 넣었습니다)')
        argfns = []
        for k, (pname, pt, ref, pline, default) in enumerate(params):
            if k >= len(e.args):
                argfns.append(('default', k))
                continue
            a = e.args[k]
            if ref:
                loc, lt = self.loc(a)
                if lt != pt:
                    raise SketchError(line, f'{fi.name}()의 참조 매개변수 {pname}에는 {pt} 변수가 필요합니다')
                argfns.append(('ref', loc))
            else:
                fn, t = self.expr(a)
                argfns.append(('val', self.converter(fn, t, pt, line)))
        m = self.m
        nparams = len(params)
        simple = all(kind == 'val' for kind, _ in argfns)
        if simple:
            fns = tuple(fn for _, fn in argfns)

            def call(f):
                nf = [None] * fi.nslots
                k = 1
                for fn in fns:
                    nf[k] = fn(f)
                    k += 1
                m.depth += 1
                if m.depth > MAX_DEPTH:
                    raise RunError(f'함수 호출이 너무 깊습니다 ({MAX_DEPTH}단계). 재귀 호출을 확인하십시오')
                fi.body(nf)
                m.depth -= 1
                m.line = line
                return nf[0]
        else:
            convs = [CONV.get(p[1], c_same) for p in params]

            def call(f):
                nf = [None] * fi.nslots
                for k in range(nparams):
                    kind, fn = argfns[k]
                    if kind == 'val':
                        nf[k + 1] = fn(f)
                    elif kind == 'ref':
                        nf[k + 1] = fn(f)
                    else:
                        nf[k + 1] = convs[k](fi.defaults[k][0](nf))
                m.depth += 1
                if m.depth > MAX_DEPTH:
                    raise RunError(f'함수 호출이 너무 깊습니다 ({MAX_DEPTH}단계). 재귀 호출을 확인하십시오')
                fi.body(nf)
                m.depth -= 1
                m.line = line
                return nf[0]
        rt = fi.rtype
        if rt == 'void':
            return call, 'void'
        z = self.zero(rt)

        def call_ret(f):
            r = call(f)
            return z if r is None else r
        return call_ret, rt

    def x_Method(self, e):
        obj = e.obj
        if isinstance(obj, lang.Name) and obj.id == 'Serial' and self.lookup('Serial') is None:
            return serial_method(self, e)
        if isinstance(obj, lang.Name) and obj.id == 'Wire' and self.lookup('Wire') is None:
            self.need_lib('Wire', e.line)
            return wire_method(self, e)
        fn, t = self.expr(obj)
        if t in ('String', 'cstr'):
            return string_method(self, e, fn, t)
        if t in lang.LIB_CLASSES:
            cls = libs.CLASSES[t]
            api = cls.API.get(e.name)
            if api is None:
                raise SketchError(e.line, f"{t}에는 '{e.name}' 함수가 없습니다")
            rtype, nmin, nmax = api
            if not nmin <= len(e.args) <= nmax:
                need = f'{nmin}개' if nmin == nmax else f'{nmin}~{nmax}개'
                raise SketchError(e.line, f'{t}.{e.name}()에는 인자가 {need} 필요합니다')
            args = [self.expr(a) for a in e.args]
            fns = [a for a, _ in args]
            types = [t2 for _, t2 in args]
            mname = 'm_' + e.name
            m = self.m
            line = e.line

            def call(f):
                o = fn(f)
                r = getattr(o, mname)([a(f) for a in fns], types)
                m.line = line
                return r
            return call, rtype
        raise SketchError(e.line, f"{t} 값에는 .{e.name}()을 쓸 수 없습니다")


class Program:
    def __init__(self, comp):
        self.G = comp.G
        self.ginit = comp.ginit
        self.funcs = comp.funcs
        self.setup = comp.funcs['setup']
        self.loop = comp.funcs['loop']

    def call(self, fi):
        nf = [None] * fi.nslots
        fi.body(nf)
        return nf[0]


# ---------------------------------------------------------------- 내장 함수
BUILTINS = {}


def builtin(name, rtype, nmin, nmax=None, cost=0):
    """기계(Machine)의 메서드를 내장 함수로 등록하는 장식자. 인자는 값으로 넘깁니다."""
    nmax = nmin if nmax is None else nmax

    def deco(impl):
        def compile_call(comp, e, impl=impl):
            if not nmin <= len(e.args) <= nmax:
                need = f'{nmin}개' if nmin == nmax else f'{nmin}~{nmax}개'
                raise SketchError(e.line, f'{name}()에는 인자가 {need} 필요합니다 ({len(e.args)}개를 넣었습니다)')
            args = [comp.expr(a) for a in e.args]
            for a, t in args:
                if t in lang.LIB_CLASSES:
                    raise SketchError(e.line, f'{name}()에 {t} 객체를 넣을 수 없습니다')
            m = comp.m
            fns = [a for a, _ in args]
            types = [t for _, t in args]
            rt = rtype(types) if callable(rtype) else rtype
            bound = impl.__get__(m)
            line = e.line
            if len(fns) == 0:
                def call(f):
                    m.t += cost
                    r = bound()
                    m.line = line
                    return r
            elif len(fns) == 1:
                a0 = fns[0]

                def call(f):
                    m.t += cost
                    return bound(a0(f))
            elif len(fns) == 2:
                a0, a1 = fns

                def call(f):
                    m.t += cost
                    return bound(a0(f), a1(f))
            else:
                def call(f):
                    m.t += cost
                    return bound(*[a(f) for a in fns])
            return call, rt
        BUILTINS[name] = compile_call
        return impl
    return deco


def _arith_of_args(types):
    t = 'int'
    for x in types:
        if x not in NUM_TYPES:
            return 'float'
        t = arith_type(t, x)
    return t


class Machine:
    """가상 UNO 한 대. 컴파일된 스케치를 스레드에서 실행합니다."""

    def __init__(self, board):
        self.board = board
        board.machine = self
        self.t = 0
        self.budget = 0
        self.line = 0
        self.depth = 0
        self.cv = threading.Condition()
        self.thread = None
        self.stop_flag = False
        self.waiting = False
        self.state = 'idle'          # idle running done error stopped
        self.error = None
        self.program = None
        self.serial_out = collections.deque()
        self.serial_in = collections.deque()
        self.serial_baud = None
        self.serial_timeout = 1000
        self.interrupts = {}
        self.isr_levels = {}
        self.in_isr = False
        self.ints_enabled = True
        self.rng = _random.Random(0)
        self.warned = set()
        self.tx_count = 0

    # --- 컴파일
    def load(self, source):
        items, includes = lang.parse(source)
        comp = Compiler(self, includes)
        self.program = comp.compile(items)
        return self.program

    # --- 실행 제어
    def start(self):
        if self.program is None:
            raise RuntimeError('load() 먼저')
        self.stop()
        self.t = 0
        self.budget = 0
        self.depth = 0
        self.line = 0
        self.stop_flag = False
        self.waiting = False
        self.error = None
        self.serial_out.clear()
        self.serial_in.clear()
        self.serial_baud = None
        self.interrupts = {}
        self.isr_levels = {}
        self.in_isr = False
        self.ints_enabled = True
        self.rng = _random.Random(0)
        self.warned = set()
        self.board.reset_outputs()
        self.state = 'running'
        self.thread = threading.Thread(target=self._main, name='sketch', daemon=True)
        self.thread.start()

    def _main(self):
        prog = self.program
        old = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(max(old, 20000))
        except Exception:
            pass
        try:
            for line, init in prog.ginit:
                self.line = line
                init(None)
            self.line = prog.setup.line
            prog.call(prog.setup)
            while True:
                self.line = prog.loop.line
                self.t += STEP
                if self.t >= self.budget:
                    self.sync()
                self.depth = 0
                prog.call(prog.loop)
        except StopSketch:
            self.state = 'stopped'
        except RunError as e:
            self.error = SketchError(self.line, e.msg)
            self.state = 'error'
        except SketchError as e:
            self.error = e
            self.state = 'error'
        except RecursionError:
            self.error = SketchError(self.line, '함수 호출이 너무 깊습니다. 재귀 호출을 확인하십시오')
            self.state = 'error'
        except ZeroDivisionError:
            self.error = SketchError(self.line, '0으로 나누었습니다')
            self.state = 'error'
        except Exception as e:     # 인터프리터 자체 문제도 줄 번호와 함께 보여 줍니다
            self.error = SketchError(self.line, f'실행 중 오류가 났습니다: {type(e).__name__}: {e}')
            self.state = 'error'
        finally:
            with self.cv:
                self.waiting = False
                self.cv.notify_all()

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def stop(self):
        th = self.thread
        if th is None:
            return
        with self.cv:
            self.stop_flag = True
            self.budget = -1
            self.cv.notify_all()
        th.join(2.0)
        self.thread = None
        if self.state == 'running':
            self.state = 'stopped'

    def advance(self, budget_us):
        with self.cv:
            if not self.stop_flag and budget_us > self.budget:
                self.budget = int(budget_us)
                self.cv.notify_all()

    def run_for(self, ms, timeout=20.0):
        """테스트용: 가상 시간 ms만큼 실행하고 멈출 때까지 기다립니다."""
        if not self.running():
            if self.state in ('idle',):
                self.start()
            else:
                return
        deadline = time.monotonic() + timeout
        with self.cv:
            self.budget = self.t + int(ms * 1000)
            self.cv.notify_all()
            while self.thread is not None and self.thread.is_alive():
                if self.waiting and self.t >= self.budget:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('스케치가 제한 시간 안에 멈추지 않았습니다')
                self.cv.wait(0.02)
        if self.thread is not None and not self.thread.is_alive():
            self.thread.join()

    def sync(self):
        """예산을 다 썼을 때 호출됩니다. 정지 요청을 확인하고 다음 예산을 기다립니다."""
        if self.stop_flag:
            raise StopSketch()
        if not self.in_isr and self.interrupts and self.ints_enabled:
            self.service_interrupts()
        with self.cv:
            if self.t < self.budget and not self.stop_flag:
                return
            self.waiting = True
            self.cv.notify_all()
            while self.t >= self.budget and not self.stop_flag:
                self.cv.wait(0.25)
            self.waiting = False
        if self.stop_flag:
            raise StopSketch()

    def wait_until(self, t_end):
        """가상 시간 t_end(µs)까지 진행합니다. 중간에 예산이 모자라면 기다립니다."""
        while True:
            if t_end <= self.budget:
                if t_end > self.t:
                    self.t = t_end
                if self.interrupts and not self.in_isr and self.ints_enabled:
                    self.service_interrupts()
                return
            if self.budget > self.t:
                self.t = self.budget
            self.sync()

    def service_interrupts(self):
        for pin, (fi, mode) in list(self.interrupts.items()):
            lvl = self.board.digital_level(pin)
            prev = self.isr_levels.get(pin, lvl)
            self.isr_levels[pin] = lvl
            fire = (mode == 1 and lvl != prev) or (mode == 3 and lvl and not prev) or \
                   (mode == 2 and prev and not lvl) or (mode == 0 and not lvl)
            if fire:
                self.in_isr = True
                saved = self.line, self.depth
                try:
                    self.program.call(fi)
                finally:
                    self.in_isr = False
                    self.line, self.depth = saved

    def warn(self, key, msg):
        if key not in self.warned:
            self.warned.add(key)
            self.board.add_runtime_warning(msg)

    # --- 핀 확인
    def pin(self, p, what='핀'):
        if type(p) is not int:
            p = _toint(p)
        if not 0 <= p <= 19:
            raise RunError(f'{p}번 핀은 없습니다 (UNO는 0~13, A0~A5)')
        return p

    # --- 디지털/아날로그
    @builtin('pinMode', 'void', 2)
    def b_pinMode(self, p, mode):
        p = self.pin(p)
        if mode not in (0, 1, 2):
            raise RunError('pinMode의 두 번째 값은 INPUT, OUTPUT, INPUT_PULLUP 중 하나여야 합니다')
        self.board.pin_mode(p, mode)

    @builtin('digitalWrite', 'void', 2, cost=4)
    def b_digitalWrite(self, p, v):
        self.board.digital_write(self.pin(p), 1 if v else 0)

    @builtin('digitalRead', 'int', 1, cost=4)
    def b_digitalRead(self, p):
        return self.board.digital_read(self.pin(p))

    @builtin('analogRead', 'int', 1, cost=110)
    def b_analogRead(self, p):
        p = _toint(p)
        if 0 <= p <= 5:
            p += 14
        if not 14 <= p <= 19:
            raise RunError(f'analogRead()는 A0~A5에만 쓸 수 있습니다 ({p}번 핀)')
        return self.board.analog_read(p)

    @builtin('analogWrite', 'void', 2, cost=6)
    def b_analogWrite(self, p, v):
        p = self.pin(p)
        v = max(0, min(255, _toint(v)))
        self.board.analog_write(p, v)

    @builtin('analogReference', 'void', 1)
    def b_analogReference(self, v):
        pass

    @builtin('tone', 'void', 2, 3)
    def b_tone(self, p, freq, dur=0):
        p = self.pin(p)
        freq = _toint(freq)
        if freq <= 0:
            self.board.no_tone(p)
            return
        end = self.t + _toint(dur) * 1000 if dur else None
        self.board.tone(p, freq, end)

    @builtin('noTone', 'void', 1)
    def b_noTone(self, p):
        self.board.no_tone(self.pin(p))

    @builtin('pulseIn', 'ulong', 2, 3)
    def b_pulseIn(self, p, level, timeout=1000000):
        p = self.pin(p)
        width = self.board.pulse_in(p, 1 if level else 0)
        timeout = _toint(timeout)
        if width is None or width > timeout:
            self.wait_until(self.t + timeout)
            return 0
        self.wait_until(self.t + width + 400)
        return int(width)

    @builtin('pulseInLong', 'ulong', 2, 3)
    def b_pulseInLong(self, p, level, timeout=1000000):
        return self.b_pulseIn(p, level, timeout)

    @builtin('shiftOut', 'void', 4)
    def b_shiftOut(self, dpin, cpin, order, val):
        self.board.shift_out(self.pin(dpin), self.pin(cpin), order, _toint(val) & 0xFF)
        self.t += 100

    # --- 시간
    @builtin('delay', 'void', 1)
    def b_delay(self, ms):
        ms = _toint(ms)
        if ms < 0:
            ms &= 0xFFFFFFFF
        if ms:
            self.wait_until(self.t + ms * 1000)

    @builtin('delayMicroseconds', 'void', 1)
    def b_delayMicroseconds(self, us):
        us = _toint(us) & 0xFFFF
        self.wait_until(self.t + us)

    @builtin('millis', 'ulong', 0)
    def b_millis(self):
        return (self.t // 1000) & 0xFFFFFFFF

    @builtin('micros', 'ulong', 0)
    def b_micros(self):
        return (self.t // 4 * 4) & 0xFFFFFFFF

    @builtin('yield', 'void', 0)
    def b_yield(self):
        pass

    # --- 수학
    @builtin('map', 'long', 5)
    def b_map(self, x, a, b, c, d):
        if b == a:
            raise RunError('map()의 입력 범위가 0입니다 (fromLow와 fromHigh가 같습니다)')
        x, a, b, c, d = (_toint(v) for v in (x, a, b, c, d))
        return c_long(cdiv((x - a) * (d - c), (b - a)) + c)

    @builtin('constrain', _arith_of_args, 3)
    def b_constrain(self, x, lo, hi):
        return lo if x < lo else hi if x > hi else x

    @builtin('min', _arith_of_args, 2)
    def b_min(self, a, b):
        return a if a < b else b

    @builtin('max', _arith_of_args, 2)
    def b_max(self, a, b):
        return a if a > b else b

    @builtin('abs', _arith_of_args, 1)
    def b_abs(self, a):
        return -a if a < 0 else a

    @builtin('sq', _arith_of_args, 1)
    def b_sq(self, a):
        return a * a

    @builtin('sqrt', 'float', 1)
    def b_sqrt(self, a):
        return math.sqrt(a) if a >= 0 else math.nan

    @builtin('pow', 'float', 2)
    def b_pow(self, a, b):
        try:
            return float(math.pow(a, b))
        except (ValueError, OverflowError):
            return math.nan

    @builtin('round', 'long', 1)
    def b_round(self, a):
        return c_long(math.floor(a + 0.5) if a >= 0 else math.ceil(a - 0.5))

    @builtin('isnan', 'bool', 1)
    def b_isnan(self, a):
        return 1 if isinstance(a, float) and a != a else 0

    @builtin('isinf', 'bool', 1)
    def b_isinf(self, a):
        return 1 if a in (math.inf, -math.inf) else 0

    @builtin('random', 'long', 1, 2)
    def b_random(self, a, b=None):
        if b is None:
            lo, hi = 0, _toint(a)
        else:
            lo, hi = _toint(a), _toint(b)
        if hi <= lo:
            return lo
        return self.rng.randrange(lo, hi)

    @builtin('randomSeed', 'void', 1)
    def b_randomSeed(self, s):
        self.rng.seed(_toint(s))

    # --- 비트
    @builtin('bitRead', 'int', 2)
    def b_bitRead(self, x, n):
        return (_toint(x) >> _toint(n)) & 1

    @builtin('bit', 'ulong', 1)
    def b_bit(self, n):
        return 1 << _toint(n)

    @builtin('lowByte', 'uchar', 1)
    def b_lowByte(self, x):
        return _toint(x) & 0xFF

    @builtin('highByte', 'uchar', 1)
    def b_highByte(self, x):
        return (_toint(x) >> 8) & 0xFF

    # --- 문자 판별
    @builtin('isDigit', 'bool', 1)
    def b_isDigit(self, c):
        return 1 if 48 <= c <= 57 else 0

    @builtin('isAlpha', 'bool', 1)
    def b_isAlpha(self, c):
        return 1 if chr(c & 0xFF).isascii() and chr(c & 0xFF).isalpha() else 0

    @builtin('isAlphaNumeric', 'bool', 1)
    def b_isAlphaNumeric(self, c):
        return 1 if chr(c & 0xFF).isascii() and chr(c & 0xFF).isalnum() else 0

    @builtin('isSpace', 'bool', 1)
    def b_isSpace(self, c):
        return 1 if chr(c & 0xFF) in ' \t\n\r\f\v' else 0

    @builtin('isWhitespace', 'bool', 1)
    def b_isWhitespace(self, c):
        return 1 if chr(c & 0xFF) in ' \t' else 0

    @builtin('isUpperCase', 'bool', 1)
    def b_isUpperCase(self, c):
        return 1 if 65 <= c <= 90 else 0

    @builtin('isLowerCase', 'bool', 1)
    def b_isLowerCase(self, c):
        return 1 if 97 <= c <= 122 else 0

    @builtin('isPunct', 'bool', 1)
    def b_isPunct(self, c):
        import string
        return 1 if chr(c & 0xFF) in string.punctuation else 0

    @builtin('toupper', 'char', 1)
    def b_toupper(self, c):
        return ord(chr(c & 0xFF).upper()) if 97 <= c <= 122 else c

    @builtin('tolower', 'char', 1)
    def b_tolower(self, c):
        return ord(chr(c & 0xFF).lower()) if 65 <= c <= 90 else c

    @builtin('strlen', 'uint', 1)
    def b_strlen(self, s):
        return len(to_text(s, 'cstr'))

    @builtin('F', 'cstr', 1)
    def b_F(self, s):
        return s

    # --- 인터럽트
    @builtin('digitalPinToInterrupt', 'int', 1)
    def b_digitalPinToInterrupt(self, p):
        return {2: 0, 3: 1}.get(_toint(p), -1)

    @builtin('interrupts', 'void', 0)
    def b_interrupts(self):
        self.ints_enabled = True

    @builtin('noInterrupts', 'void', 0)
    def b_noInterrupts(self):
        self.ints_enabled = False

    @builtin('detachInterrupt', 'void', 1)
    def b_detachInterrupt(self, n):
        self.interrupts.pop({0: 2, 1: 3}.get(_toint(n), -1), None)

    # --- 시리얼 내부 동작
    def serial_write(self, text):
        if self.serial_baud is None:
            self.warn('serial-begin', 'Serial.begin()을 하지 않고 Serial로 출력했습니다. setup()에서 Serial.begin(9600);을 호출하십시오')
            return
        self.serial_out.append(text)
        self.tx_count += len(text)
        self.board.serial_activity('tx', self.t)
        # 보드 속도에 맞춰 전송 시간 진행(버퍼 64바이트는 생략)
        self.t += int(len(text) * 10_000_000 / self.serial_baud)

    def serial_wait(self, timeout_ms, need=1):
        end = self.t + timeout_ms * 1000
        while len(self.serial_in) < need and self.t < end:
            self.wait_until(min(end, self.t + 5000))
        return len(self.serial_in) >= need

    def feed_serial(self, text):
        """시리얼 모니터에서 보낸 글자."""
        for ch in text:
            self.serial_in.append(ord(ch) & 0xFF)
        self.board.serial_activity('rx', self.t)


def _lvalue_bit_builtin(name, op):
    def compile_call(comp, e):
        if len(e.args) != (3 if name == 'bitWrite' else 2):
            raise SketchError(e.line, f'{name}()의 인자 개수가 맞지 않습니다')
        loc, t = comp.loc(e.args[0])
        if t not in INT_TYPES:
            raise SketchError(e.line, f'{name}()의 첫 번째 인자는 정수 변수여야 합니다')
        n, _ = comp.expr(e.args[1])
        b = comp.expr(e.args[2])[0] if name == 'bitWrite' else None
        conv = CONV[t]

        def call(f):
            c, k = loc(f)
            bitn = n(f)
            if name == 'bitSet' or (name == 'bitWrite' and b(f)):
                c[k] = conv(c[k] | (1 << bitn))
            else:
                c[k] = conv(c[k] & ~(1 << bitn))
            return c[k]
        return call, t
    BUILTINS[name] = compile_call


for _n in ('bitSet', 'bitClear', 'bitWrite'):
    _lvalue_bit_builtin(_n, None)


def _compile_attach(comp, e):
    if len(e.args) != 3:
        raise SketchError(e.line, 'attachInterrupt(번호, 함수, 모드)처럼 인자 3개가 필요합니다')
    intr, _ = comp.expr(e.args[0])
    fnode = e.args[1]
    if not isinstance(fnode, lang.Name) or fnode.id not in comp.funcs:
        raise SketchError(e.line, 'attachInterrupt()의 두 번째 인자는 함수 이름이어야 합니다')
    fi = comp.funcs[fnode.id]
    if fi.params:
        raise SketchError(e.line, '인터럽트 함수에는 매개변수가 없어야 합니다')
    mode, _ = comp.expr(e.args[2])
    m = comp.m

    def call(f):
        n = intr(f)
        pin = {0: 2, 1: 3}.get(n)
        if pin is None:
            raise RunError('UNO에서 인터럽트는 2번, 3번 핀에서만 쓸 수 있습니다. digitalPinToInterrupt(2)처럼 쓰십시오')
        m.interrupts[pin] = (fi, mode(f))
        m.isr_levels[pin] = m.board.digital_level(pin)
    return call, 'void'


BUILTINS['attachInterrupt'] = _compile_attach


def _compile_string_ctor(comp, e):
    if not e.args:
        return (lambda f: ''), 'String'
    if len(e.args) > 2:
        raise SketchError(e.line, 'String()에는 인자가 1~2개 필요합니다')
    a, t = comp.expr(e.args[0])
    if len(e.args) == 2:
        fmt, _ = comp.expr(e.args[1])

        def conv(f):
            base = fmt(f)
            s = to_text(a(f), t, base)
            return s.lower() if base == 16 and t != 'float' else s   # Arduino String은 소문자 16진수
        return conv, 'String'
    return (lambda f: to_text(a(f), t)), 'String'


BUILTINS['String'] = _compile_string_ctor


def _math1(name, fn):
    def compile_call(comp, e):
        if len(e.args) != 1:
            raise SketchError(e.line, f'{name}()에는 인자가 1개 필요합니다')
        a, t = comp.expr(e.args[0])
        if t not in NUM_TYPES:
            raise SketchError(e.line, f'{name}()에는 숫자가 필요합니다')

        def call(f):
            try:
                return float(fn(a(f)))
            except (ValueError, OverflowError):
                return math.nan
        return call, 'float'
    BUILTINS[name] = compile_call


for _n, _f in (('sin', math.sin), ('cos', math.cos), ('tan', math.tan), ('asin', math.asin),
               ('acos', math.acos), ('atan', math.atan), ('exp', math.exp), ('log', math.log),
               ('log10', math.log10), ('floor', math.floor), ('ceil', math.ceil), ('fabs', abs),
               ('degrees', math.degrees), ('radians', math.radians), ('trunc', math.trunc)):
    _math1(_n, _f)


def _compile_atan2(comp, e):
    if len(e.args) != 2:
        raise SketchError(e.line, 'atan2()에는 인자가 2개 필요합니다')
    a, _ = comp.expr(e.args[0])
    b, _ = comp.expr(e.args[1])
    return (lambda f: math.atan2(a(f), b(f))), 'float'


BUILTINS['atan2'] = _compile_atan2


def _compile_fmod(comp, e):
    if len(e.args) != 2:
        raise SketchError(e.line, 'fmod()에는 인자가 2개 필요합니다')
    a, _ = comp.expr(e.args[0])
    b, _ = comp.expr(e.args[1])
    return (lambda f: math.fmod(a(f), b(f)) if b(f) else math.nan), 'float'


BUILTINS['fmod'] = _compile_fmod


# ---------------------------------------------------------------- Serial
SERIAL_API = {
    'begin': ('void', 1, 2), 'end': ('void', 0, 0), 'print': ('uint', 0, 2), 'println': ('uint', 0, 2),
    'write': ('uint', 1, 2), 'available': ('int', 0, 0), 'read': ('int', 0, 0), 'peek': ('int', 0, 0),
    'parseInt': ('long', 0, 1), 'parseFloat': ('float', 0, 1), 'readString': ('String', 0, 0),
    'readStringUntil': ('String', 1, 1), 'setTimeout': ('void', 1, 1), 'flush': ('void', 0, 0),
    'availableForWrite': ('int', 0, 0),
}


def serial_method(comp, e):
    api = SERIAL_API.get(e.name)
    if api is None:
        raise SketchError(e.line, f"Serial에는 '{e.name}' 함수가 없습니다")
    rtype, nmin, nmax = api
    if not nmin <= len(e.args) <= nmax:
        need = f'{nmin}개' if nmin == nmax else f'{nmin}~{nmax}개'
        raise SketchError(e.line, f'Serial.{e.name}()에는 인자가 {need} 필요합니다')
    args = [comp.expr(a) for a in e.args]
    m = comp.m
    name = e.name
    if name in ('print', 'println'):
        nl = '\r\n' if name == 'println' else ''
        if not args:
            return (lambda f: m.serial_write(nl) or len(nl)), rtype
        a, t = args[0]
        if t in lang.LIB_CLASSES:
            raise SketchError(e.line, f'{t} 객체는 출력할 수 없습니다')
        if len(args) == 2:
            fmt = args[1][0]

            def pr2(f):
                s = to_text(a(f), t, fmt(f)) + nl
                m.serial_write(s)
                return len(s)
            return pr2, rtype

        def pr(f):
            s = to_text(a(f), t) + nl
            m.serial_write(s)
            return len(s)
        return pr, rtype
    if name == 'write':
        a, t = args[0]

        def wr(f):
            v = a(f)
            s = v if isinstance(v, str) else to_text(v, 'char[]') if isinstance(v, list) else chr(_toint(v) & 0xFF)
            m.serial_write(s)
            return len(s)
        return wr, rtype
    if name == 'begin':
        a, _ = args[0]

        def begin(f):
            baud = _toint(a(f))
            if baud <= 0:
                raise RunError('Serial.begin()의 통신 속도가 올바르지 않습니다')
            m.serial_baud = baud
            m.board.serial_used = True
        return begin, rtype
    if name == 'end':
        def end(f):
            m.serial_baud = None
        return end, rtype
    if name == 'available':
        return (lambda f: len(m.serial_in)), rtype
    if name == 'availableForWrite':
        return (lambda f: 63), rtype
    if name == 'read':
        return (lambda f: m.serial_in.popleft() if m.serial_in else -1), rtype
    if name == 'peek':
        return (lambda f: m.serial_in[0] if m.serial_in else -1), rtype
    if name == 'flush':
        return (lambda f: None), rtype
    if name == 'setTimeout':
        a, _ = args[0]

        def st(f):
            m.serial_timeout = max(0, _toint(a(f)))
        return st, rtype
    if name == 'readString':
        def rs(f):
            out = []
            while m.serial_wait(m.serial_timeout):
                out.append(chr(m.serial_in.popleft()))
            return ''.join(out)
        return rs, rtype
    if name == 'readStringUntil':
        a, _ = args[0]

        def rsu(f):
            stop = _toint(a(f)) & 0xFF
            out = []
            while m.serial_wait(m.serial_timeout):
                c = m.serial_in.popleft()
                if c == stop:
                    break
                out.append(chr(c))
            return ''.join(out)
        return rsu, rtype
    if name in ('parseInt', 'parseFloat'):
        is_float = name == 'parseFloat'

        def parse(f):
            # 숫자가 아닌 글자는 건너뛰고, 숫자가 나오면 끝까지 읽습니다
            while True:
                if not m.serial_wait(m.serial_timeout):
                    return 0.0 if is_float else 0
                c = chr(m.serial_in[0])
                if c.isdigit() or c == '-' or (is_float and c == '.'):
                    break
                m.serial_in.popleft()
            text = []
            while True:
                if not m.serial_in and not m.serial_wait(m.serial_timeout):
                    break
                c = chr(m.serial_in[0])
                if c.isdigit() or (c == '-' and not text) or (is_float and c == '.' and '.' not in text):
                    text.append(c)
                    m.serial_in.popleft()
                else:
                    break
            s = ''.join(text)
            try:
                return float(s) if is_float else c_long(int(s))
            except ValueError:
                return 0.0 if is_float else 0
        return parse, rtype
    raise SketchError(e.line, f"Serial.{name}(){josa(name, '은는')} 지원하지 않습니다")


def wire_method(comp, e):
    api = libs.WIRE_API.get(e.name)
    if api is None:
        raise SketchError(e.line, f"Wire에는 '{e.name}' 함수가 없습니다")
    rtype, nmin, nmax = api
    if not nmin <= len(e.args) <= nmax:
        raise SketchError(e.line, f'Wire.{e.name}()의 인자 개수가 맞지 않습니다')
    args = [comp.expr(a)[0] for a in e.args]
    m = comp.m
    meth = getattr(libs.Wire, 'm_' + e.name)
    return (lambda f: meth(m, [a(f) for a in args])), rtype


# ---------------------------------------------------------------- String 메서드
STRING_API = {
    'length': ('uint', 0, 0), 'charAt': ('char', 1, 1), 'substring': ('String', 1, 2),
    'indexOf': ('int', 1, 2), 'lastIndexOf': ('int', 1, 2), 'toInt': ('long', 0, 0),
    'toFloat': ('float', 0, 0), 'toDouble': ('float', 0, 0), 'equals': ('bool', 1, 1),
    'equalsIgnoreCase': ('bool', 1, 1), 'startsWith': ('bool', 1, 2), 'endsWith': ('bool', 1, 1),
    'compareTo': ('int', 1, 1), 'c_str': ('cstr', 0, 0), 'isEmpty': ('bool', 0, 0),
    'concat': ('bool', 1, 1), 'trim': ('void', 0, 0), 'toUpperCase': ('void', 0, 0),
    'toLowerCase': ('void', 0, 0), 'replace': ('void', 2, 2), 'remove': ('void', 1, 2),
    'setCharAt': ('void', 2, 2), 'reserve': ('bool', 1, 1),
}
MUTATING = {'concat', 'trim', 'toUpperCase', 'toLowerCase', 'replace', 'remove', 'setCharAt'}


def _str_arg(v, t):
    if isinstance(v, str):
        return v
    if t in ('char', 'uchar'):
        return chr(v & 0xFF)
    return to_text(v, t)


def _to_long_prefix(s):
    s = s.strip()
    i = 0
    if i < len(s) and s[i] in '+-':
        i += 1
    j = i
    while j < len(s) and s[j].isdigit():
        j += 1
    try:
        return c_long(int(s[:j])) if j > i else 0
    except ValueError:
        return 0


def _to_float_prefix(s):
    import re
    mt = re.match(r'\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?', s)
    return float(mt.group()) if mt else 0.0


def string_method(comp, e, obj, t):
    api = STRING_API.get(e.name)
    if api is None:
        raise SketchError(e.line, f"String에는 '{e.name}' 함수가 없습니다")
    rtype, nmin, nmax = api
    if not nmin <= len(e.args) <= nmax:
        need = f'{nmin}개' if nmin == nmax else f'{nmin}~{nmax}개'
        raise SketchError(e.line, f'{e.name}()에는 인자가 {need} 필요합니다')
    args = [comp.expr(a) for a in e.args]
    fns = [a for a, _ in args]
    types = [t2 for _, t2 in args]
    name = e.name

    def ints(f):
        return [_toint(a(f)) for a in fns]

    if name in MUTATING:
        if t != 'String':
            raise SketchError(e.line, f'{name}(){josa(name, '은는')} String 변수에만 쓸 수 있습니다')
        loc, _ = comp.loc(e.obj)

        def mut(f):
            c, k = loc(f)
            s = c[k]
            vals = [a(f) for a in fns]
            if name == 'concat':
                c[k] = s + _str_arg(vals[0], types[0])
                return 1
            if name == 'trim':
                c[k] = s.strip()
            elif name == 'toUpperCase':
                c[k] = s.upper()
            elif name == 'toLowerCase':
                c[k] = s.lower()
            elif name == 'replace':
                c[k] = s.replace(_str_arg(vals[0], types[0]), _str_arg(vals[1], types[1]))
            elif name == 'remove':
                i = _toint(vals[0])
                n = _toint(vals[1]) if len(vals) > 1 else len(s)
                c[k] = s[:i] + s[i + n:]
            elif name == 'setCharAt':
                i = _toint(vals[0])
                if 0 <= i < len(s):
                    c[k] = s[:i] + chr(_toint(vals[1]) & 0xFF) + s[i + 1:]
            return None
        return mut, rtype

    if name == 'length':
        return (lambda f: len(obj(f))), rtype
    if name == 'isEmpty':
        return (lambda f: 0 if obj(f) else 1), rtype
    if name == 'charAt':
        a = fns[0]

        def charat(f):
            s = obj(f)
            i = _toint(a(f))
            return ord(s[i]) & 0xFF if 0 <= i < len(s) else 0
        return charat, rtype
    if name == 'substring':
        def sub(f):
            s = obj(f)
            v = ints(f)
            a = max(0, v[0])
            b = v[1] if len(v) > 1 else len(s)
            if b < a:
                a, b = b, a
            return s[a:b]
        return sub, rtype
    if name in ('indexOf', 'lastIndexOf'):
        def idx(f):
            s = obj(f)
            x = _str_arg(fns[0](f), types[0])
            if len(fns) > 1:
                frm = _toint(fns[1](f))
                return s.find(x, frm) if name == 'indexOf' else s.rfind(x, 0, frm + len(x))
            return s.find(x) if name == 'indexOf' else s.rfind(x)
        return idx, rtype
    if name == 'toInt':
        return (lambda f: _to_long_prefix(obj(f))), rtype
    if name in ('toFloat', 'toDouble'):
        return (lambda f: _to_float_prefix(obj(f))), rtype
    if name == 'equals':
        return (lambda f: 1 if obj(f) == _str_arg(fns[0](f), types[0]) else 0), rtype
    if name == 'equalsIgnoreCase':
        return (lambda f: 1 if obj(f).lower() == _str_arg(fns[0](f), types[0]).lower() else 0), rtype
    if name == 'startsWith':
        return (lambda f: 1 if obj(f).startswith(_str_arg(fns[0](f), types[0])) else 0), rtype
    if name == 'endsWith':
        return (lambda f: 1 if obj(f).endswith(_str_arg(fns[0](f), types[0])) else 0), rtype
    if name == 'compareTo':
        def cmp(f):
            a, b = obj(f), _str_arg(fns[0](f), types[0])
            return (a > b) - (a < b)
        return cmp, rtype
    if name == 'c_str':
        return obj, rtype
    if name == 'reserve':
        return (lambda f: 1), rtype
    raise SketchError(e.line, f'String.{name}(){josa(name, '은는')} 지원하지 않습니다')



# ---------------------------------------------------------------- C 문자열 함수(char 배열)
import re as _re

_FMT = _re.compile(r'%([-+ 0#]*)(\d*)(?:\.(\d+))?(hh|h|ll|l)?([diuxXcsfFeEgGo%])')


def c_format(fmt, vals, types):
    """AVR printf와 같게: %f 계열은 지원하지 않아 '?'로 나옵니다."""
    out = []
    k = 0
    pos = 0
    for mt in _FMT.finditer(fmt):
        out.append(fmt[pos:mt.start()])
        pos = mt.end()
        flags, width, prec, length, conv = mt.groups()
        if conv == '%':
            out.append('%')
            continue
        if k >= len(vals):
            raise RunError('sprintf 형식에 맞는 값이 모자랍니다')
        v, t = vals[k], types[k]
        k += 1
        if conv in 'fFeEgG':
            s = '?'
        elif conv == 's':
            s = to_text(v, 'cstr')
        elif conv == 'c':
            s = chr(_toint(v) & 0xFF)
        else:
            n = _toint(v)
            if conv in 'di':
                n = c_long(n) if length == 'l' else c_int(n)
            elif conv in 'uxXo':
                n = c_ulong(n) if length == 'l' else c_uint(n)
            spec = {'d': 'd', 'i': 'd', 'u': 'd', 'x': 'x', 'X': 'X', 'o': 'o'}[conv]
            s = format(n, spec)
            if prec:
                s = s.rjust(int(prec), '0') if not s.startswith('-') else '-' + s[1:].rjust(int(prec), '0')
        if width:
            w = int(width)
            if '-' in flags:
                s = s.ljust(w)
            elif '0' in flags and conv not in 'sc':
                neg = s.startswith('-')
                s = ('-' if neg else '') + s[1 if neg else 0:].rjust(w - (1 if neg else 0), '0')
            else:
                s = s.rjust(w)
        out.append(s)
    out.append(fmt[pos:])
    return ''.join(out)


def write_cstr(buf, text, limit=None):
    if not isinstance(buf, list):
        raise RunError('첫 번째 인자는 char 배열이어야 합니다')
    if limit is not None:
        text = text[:max(0, limit - 1)]
    need = len(text) + 1
    if need > len(buf):
        raise RunError(f'char 배열이 작습니다. 글자 끝을 표시하는 0까지 {need}칸이 필요한데 {len(buf)}칸뿐입니다. 실제 보드에서는 다른 변수 값이 망가집니다')
    for i, ch in enumerate(text):
        buf[i] = ord(ch) & 0xFF
    buf[len(text)] = 0


def _cstr_builtin(name, nmin, nmax, rtype, impl):
    def compile_call(comp, e):
        if not nmin <= len(e.args) <= nmax:
            need = f'{nmin}개' if nmin == nmax else f'{nmin}개 이상'
            raise SketchError(e.line, f'{name}()에는 인자가 {need} 필요합니다')
        args = [comp.expr(a) for a in e.args]
        fns = [a for a, _ in args]
        types = [t for _, t in args]
        return (lambda f: impl([a(f) for a in fns], types)), rtype
    BUILTINS[name] = compile_call


def _sprintf(a, t):
    s = c_format(to_text(a[1], 'cstr'), a[2:], t[2:])
    write_cstr(a[0], s)
    return len(s)


def _snprintf(a, t):
    s = c_format(to_text(a[2], 'cstr'), a[3:], t[3:])
    write_cstr(a[0], s, _toint(a[1]))
    return len(s)


def _dtostrf(a, t):
    width, prec = _toint(a[1]), _toint(a[2])
    s = fmt_float(float(a[0]), prec)
    s = s.ljust(-width) if width < 0 else s.rjust(width)
    write_cstr(a[3], s)
    return a[3]


def _itoa(a, t):
    s = fmt_int(_toint(a[0]), _toint(a[2])).lower()
    write_cstr(a[1], s)
    return a[1]


def _strcmp(a, t):
    x, y = to_text(a[0], 'cstr'), to_text(a[1], 'cstr')
    return (x > y) - (x < y)


_cstr_builtin('sprintf', 2, 12, 'int', _sprintf)
_cstr_builtin('snprintf', 3, 13, 'int', _snprintf)
_cstr_builtin('dtostrf', 4, 4, 'char[]', _dtostrf)
_cstr_builtin('itoa', 3, 3, 'char[]', _itoa)
_cstr_builtin('strcpy', 2, 2, 'char[]', lambda a, t: (write_cstr(a[0], to_text(a[1], 'cstr')), a[0])[1])
_cstr_builtin('strcat', 2, 2, 'char[]',
              lambda a, t: (write_cstr(a[0], to_text(a[0], 'cstr') + to_text(a[1], 'cstr')), a[0])[1])
_cstr_builtin('strcmp', 2, 2, 'int', _strcmp)
_cstr_builtin('atoi', 1, 1, 'int', lambda a, t: c_int(_to_long_prefix(to_text(a[0], 'cstr'))))
_cstr_builtin('atol', 1, 1, 'long', lambda a, t: _to_long_prefix(to_text(a[0], 'cstr')))
_cstr_builtin('atof', 1, 1, 'float', lambda a, t: _to_float_prefix(to_text(a[0], 'cstr')))
BUILTINS.pop('strlen', None)
_cstr_builtin('strlen', 1, 1, 'uint', lambda a, t: len(to_text(a[0], 'cstr')))
