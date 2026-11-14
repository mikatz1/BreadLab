"""스케치 소스를 토큰과 구문 트리로 바꿉니다. Arduino C/C++의 부분집합만 다룹니다."""
import re


class SketchError(Exception):
    """줄 번호가 붙은 스케치 오류(컴파일·실행 모두)."""

    def __init__(self, line, msg):
        super().__init__(msg)
        self.line = line
        self.msg = msg

    def __str__(self):
        return f'{self.line}번째 줄: {self.msg}' if self.line else self.msg


def _final(word):
    w = str(word).rstrip("'\")( ")
    return w[-1] if w else ''


def _has_final(word):
    """낱말 끝소리에 받침이 있는지(조사 고르기용). 영문·숫자는 읽는 소리 기준."""
    c = _final(word)
    if not c:
        return False
    if '\uac00' <= c <= '\ud7a3':
        return (ord(c) - 0xAC00) % 28 != 0
    if c.isdigit():
        return c in '013678'
    return c.lower() in 'lmnr'


def josa(word, pair):
    """josa('x', '이가') → '가'. pair: 이가 은는 을를 와과 으로"""
    pairs = {'이가': ('이', '가'), '은는': ('은', '는'), '을를': ('을', '를'), '와과': ('과', '와'),
             '으로': ('으로', '로')}
    a, b = pairs[pair]
    try:                                    # 영어 화면에서는 조사를 붙이지 않습니다('와/과'만 and)
        import i18n
        if i18n.lang() != 'ko':
            return ' and' if pair == '와과' else ''
    except ImportError:
        pass
    c = _final(word)
    if pair == '으로' and c and '\uac00' <= c <= '\ud7a3' and (ord(c) - 0xAC00) % 28 == 8:
        return '로'
    return a if _has_final(word) else b


# ---------------------------------------------------------------- 토큰
class Tok:
    __slots__ = ('kind', 'val', 'line', 'ntype')

    def __init__(self, kind, val, line, ntype=None):
        self.kind, self.val, self.line, self.ntype = kind, val, line, ntype

    def __repr__(self):
        return f'Tok({self.kind},{self.val!r},{self.line})'


TOKEN_RE = re.compile(r'''
 (?P<ws>[ \t\r\f\v]+)
|(?P<num>0[xX][0-9a-fA-F']+[uUlL]*|0[bB][01']+[uUlL]*|(?:\d[\d']*\.\d*|\.\d+|\d[\d']*)(?:[eE][+-]?\d+)?[fFuUlL]*)
|(?P<id>[A-Za-z_]\w*)
|(?P<str>"(?:\\.|[^"\\\n])*")
|(?P<chr>'(?:\\.|[^'\\\n])+')
|(?P<op><<=|>>=|\+\+|--|->|::|&&|\|\||<<|>>|[-+*/%&|^!=<>]=|[-+*/%&|^!~<>=?:;,.(){}\[\]#])
''', re.X)

ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '0': '\0', '\\': '\\', "'": "'", '"': '"', 'a': '\a', 'b': '\b', 'f': '\f', 'v': '\v'}
BIN_CONST = re.compile(r'^B[01]{1,8}$')


def unescape(body, line):
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == '\\' and i + 1 < len(body):
            n = body[i + 1]
            if n == 'x':
                m = re.match(r'[0-9a-fA-F]{1,2}', body[i + 2:])
                if not m:
                    raise SketchError(line, '\\x 뒤에 16진수가 필요합니다')
                out.append(chr(int(m.group(), 16)))
                i += 2 + len(m.group())
                continue
            if n in ESCAPES:
                out.append(ESCAPES[n])
                i += 2
                continue
            out.append(n)
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def int_type(value, suffix, decimal):
    u = 'u' in suffix
    l = 'l' in suffix
    if u and l:
        return 'ulong'
    if l:
        return 'long' if value <= 0x7FFFFFFF else 'ulong'
    if u:
        return 'uint' if value <= 0xFFFF else 'ulong'
    if value <= 0x7FFF:
        return 'int'
    if not decimal and value <= 0xFFFF:
        return 'uint'
    if value <= 0x7FFFFFFF:
        return 'long'
    return 'ulong'


def parse_number(text, line):
    t = text.replace("'", '')
    low = t.lower()
    if low.startswith('0x'):
        digits = low[2:].rstrip('ul')
        suffix = low[2 + len(digits):]
        v = int(digits, 16)
        return v, int_type(v, suffix, False)
    if low.startswith('0b'):
        digits = low[2:].rstrip('ul')
        suffix = low[2 + len(digits):]
        v = int(digits, 2)
        return v, int_type(v, suffix, False)
    is_float = ('.' in low) or ('e' in low)
    if is_float:
        body = low.rstrip('fl')
        try:
            return float(body), 'float'
        except ValueError:
            raise SketchError(line, f"'{text}'{josa(text, '은는')} 올바른 숫자가 아닙니다")
    digits = low.rstrip('ul')
    suffix = low[len(digits):]
    if 'f' in suffix:
        raise SketchError(line, f"'{text}': 정수에는 f를 붙일 수 없습니다")
    if len(digits) > 1 and digits.startswith('0'):
        try:
            v = int(digits, 8)
        except ValueError:
            raise SketchError(line, f"'{text}': 0으로 시작하는 수는 8진수입니다")
        return v, int_type(v, suffix, False)
    v = int(digits)
    return v, int_type(v, suffix, True)


def tokenize_line(text, line):
    toks = []
    pos = 0
    n = len(text)
    while pos < n:
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise SketchError(line, f"알 수 없는 문자 '{text[pos]}'")
        kind = m.lastgroup
        val = m.group()
        pos = m.end()
        if kind == 'ws':
            continue
        if kind == 'num':
            v, nt = parse_number(val, line)
            toks.append(Tok('num', v, line, nt))
        elif kind == 'id':
            if BIN_CONST.match(val):
                toks.append(Tok('num', int(val[1:], 2), line, 'int'))
            else:
                toks.append(Tok('id', val, line))
        elif kind == 'str':
            s = unescape(val[1:-1], line)
            if toks and toks[-1].kind == 'str':     # "ab" "cd" → "abcd"
                toks[-1].val += s
            else:
                toks.append(Tok('str', s, line))
        elif kind == 'chr':
            s = unescape(val[1:-1], line)
            if len(s) != 1:
                raise SketchError(line, f"문자 상수 {val}에는 글자가 하나만 들어가야 합니다")
            toks.append(Tok('num', ord(s) & 0xFF, line, 'char'))
        else:
            toks.append(Tok('op', val, line))
    return toks


def strip_comments(src):
    """주석을 지우고 줄바꿈은 그대로 둡니다(줄 번호 유지)."""
    out = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            while i < n and src[i] != '\n':
                i += 1
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            end = src.find('*/', i + 2)
            if end < 0:
                end = n
            out.append(''.join('\n' if ch == '\n' else ' ' for ch in src[i:end + 2]))
            i = end + 2
            continue
        if c in '"\'':
            j = i + 1
            while j < n and src[j] != c and src[j] != '\n':
                j += 2 if src[j] == '\\' else 1
            out.append(src[i:j + 1])
            i = j + 1
            continue
        out.append(c)
        i += 1
    return ''.join(out)


# 지원하는 #include 이름 → 라이브러리 이름
LIBRARIES = {
    'Arduino.h': None, 'SPI.h': None, 'Adafruit_Sensor.h': None, 'DHT_U.h': 'DHT',
    'Servo.h': 'Servo', 'Wire.h': 'Wire', 'LiquidCrystal_I2C.h': 'LiquidCrystal_I2C',
    'DHT.h': 'DHT', 'TM1637Display.h': 'TM1637Display', 'LedControl.h': 'LedControl',
}


def preprocess(src):
    """주석 제거 → #define/#include/#ifdef 처리 → 매크로 확장된 토큰 목록."""
    text = strip_comments(src)
    raw = text.split('\n')
    lines = []
    i = 0
    while i < len(raw):
        line = raw[i]
        start = i
        while line.rstrip().endswith('\\') and i + 1 < len(raw):
            i += 1
            line = line.rstrip()[:-1] + ' ' + raw[i]
        lines.append((start + 1, line))
        i += 1
    macros = {}
    includes = {}
    out = []
    cond = []   # 조건부 컴파일 스택: (현재 활성, 이미 참인 가지 있었음)

    def active():
        return all(c[0] for c in cond)

    for lineno, line in lines:
        s = line.strip()
        if s.startswith('#'):
            m = re.match(r'#\s*(\w*)\s*(.*)', s)
            word, rest = m.group(1), m.group(2).strip()
            if word in ('ifdef', 'ifndef'):
                name = rest.split()[0] if rest else ''
                val = (name in macros) == (word == 'ifdef')
                cond.append([val, val])
            elif word == 'if':
                val = eval_pp_cond(rest, macros, lineno)
                cond.append([val, val])
            elif word == 'elif':
                if not cond:
                    raise SketchError(lineno, '#elif 앞에 #if가 없습니다')
                if cond[-1][1]:
                    cond[-1][0] = False
                else:
                    val = eval_pp_cond(rest, macros, lineno)
                    cond[-1] = [val, val]
            elif word == 'else':
                if not cond:
                    raise SketchError(lineno, '#else 앞에 #if가 없습니다')
                cond[-1][0] = not cond[-1][1]
                cond[-1][1] = True
            elif word == 'endif':
                if not cond:
                    raise SketchError(lineno, '#endif 앞에 #if가 없습니다')
                cond.pop()
            elif not active():
                continue
            elif word == 'include':
                m2 = re.match(r'[<"]([^>"]+)[>"]', rest)
                if not m2:
                    raise SketchError(lineno, '#include 형식이 올바르지 않습니다')
                name = m2.group(1)
                if name not in LIBRARIES:
                    raise SketchError(lineno, f"'{name}' 라이브러리는 지원하지 않습니다")
                if LIBRARIES[name]:
                    includes[LIBRARIES[name]] = lineno
                if name in ('LiquidCrystal_I2C.h',):
                    includes.setdefault('Wire', lineno)
            elif word == 'define':
                m2 = re.match(r'([A-Za-z_]\w*)(\(([^)]*)\))?\s*(.*)', rest)
                if not m2:
                    raise SketchError(lineno, '#define 형식이 올바르지 않습니다')
                name = m2.group(1)
                params = None
                if m2.group(2) is not None:
                    params = [p.strip() for p in m2.group(3).split(',') if p.strip()]
                body = tokenize_line(m2.group(4), lineno)
                macros[name] = (params, body)
            elif word == 'undef':
                macros.pop(rest.split()[0] if rest else '', None)
            elif word in ('pragma', 'line', 'warning', ''):
                pass
            elif word == 'error':
                raise SketchError(lineno, f'#error {rest}')
            else:
                raise SketchError(lineno, f"'#{word}' 지시문은 지원하지 않습니다")
            continue
        if not active():
            continue
        toks = tokenize_line(line, lineno)
        if toks:
            out.extend(expand(toks, macros, frozenset(), lineno))
    if cond:
        raise SketchError(len(lines), '#if/#ifdef가 #endif로 닫히지 않았습니다')
    out.append(Tok('eof', None, len(lines) + 1))
    return out, includes


def eval_pp_cond(text, macros, line):
    text = re.sub(r'defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)',
                  lambda m: '1' if (m.group(1) or m.group(2)) in macros else '0', text)
    toks = expand(tokenize_line(text, line), macros, frozenset(), line)
    expr = ' '.join(str(t.val) for t in toks)
    expr = expr.replace('&&', ' and ').replace('||', ' or ').replace('!', ' not ').replace('not =', '!=')
    expr = re.sub(r'\b[A-Za-z_]\w*\b', lambda m: m.group() if m.group() in ('and', 'or', 'not') else '0', expr)
    try:
        return bool(eval(expr, {'__builtins__': {}}, {}))
    except Exception:
        raise SketchError(line, '#if 조건을 이해하지 못했습니다')


def expand(toks, macros, hide, line):
    out = []
    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        if t.kind == 'id' and t.val in macros and t.val not in hide:
            params, body = macros[t.val]
            if params is None:
                body2 = [Tok(b.kind, b.val, line, b.ntype) for b in body]
                out.extend(expand(body2, macros, hide | {t.val}, line))
                i += 1
                continue
            if i + 1 < n and toks[i + 1].kind == 'op' and toks[i + 1].val == '(':
                depth = 0
                args = [[]]
                j = i + 1
                while j < n:
                    tj = toks[j]
                    if tj.kind == 'op' and tj.val == '(':
                        depth += 1
                        if depth > 1:
                            args[-1].append(tj)
                    elif tj.kind == 'op' and tj.val == ')':
                        depth -= 1
                        if depth == 0:
                            break
                        args[-1].append(tj)
                    elif tj.kind == 'op' and tj.val == ',' and depth == 1:
                        args.append([])
                    else:
                        args[-1].append(tj)
                    j += 1
                if j >= n:
                    raise SketchError(line, f"매크로 {t.val}(...)의 괄호가 닫히지 않았습니다")
                if args == [[]]:
                    args = []
                if len(args) != len(params):
                    raise SketchError(line, f"매크로 {t.val}에는 인자가 {len(params)}개 필요합니다")
                sub = []
                for b in body:
                    if b.kind == 'id' and b.val in params:
                        sub.append(Tok('op', '(', line))
                        sub.extend(expand(args[params.index(b.val)], macros, hide, line))
                        sub.append(Tok('op', ')', line))
                    else:
                        sub.append(Tok(b.kind, b.val, line, b.ntype))
                out.extend(expand(sub, macros, hide | {t.val}, line))
                i = j + 1
                continue
        out.append(t)
        i += 1
    return out


# ---------------------------------------------------------------- 구문 트리
class Node:
    __slots__ = ('line',)
    fields = ()

    def __init__(self, line, *args):
        self.line = line
        for name, v in zip(self.fields, args):
            setattr(self, name, v)

    def __repr__(self):
        return f"{type(self).__name__}({', '.join(repr(getattr(self, f, None)) for f in self.fields)})"


def node(name, *fields):
    return type(name, (Node,), {'__slots__': fields, 'fields': fields})


Num = node('Num', 'val', 'ntype')
Str = node('Str', 'val')
Name = node('Name', 'id')
Bin = node('Bin', 'op', 'l', 'r')
Unary = node('Unary', 'op', 'e')
IncDec = node('IncDec', 'op', 'e', 'post')
Assign = node('Assign', 'op', 'target', 'value')
Cond = node('Cond', 'c', 'a', 'b')
Call = node('Call', 'name', 'args')
Method = node('Method', 'obj', 'name', 'args')
Member = node('Member', 'obj', 'name')
Index = node('Index', 'arr', 'idx')
Cast = node('Cast', 'type', 'e')
InitList = node('InitList', 'items')
Comma = node('Comma', 'items')
SizeOf = node('SizeOf', 'type', 'e')

Block = node('Block', 'stmts')
VarDecl = node('VarDecl', 'type', 'decls')        # decls: [Declarator]
Declarator = node('Declarator', 'name', 'dims', 'init', 'ctor')
If = node('If', 'c', 'then', 'other')
While = node('While', 'c', 'body')
DoWhile = node('DoWhile', 'body', 'c')
For = node('For', 'init', 'c', 'step', 'body')
Switch = node('Switch', 'e', 'body')
Case = node('Case', 'e')
Default = node('Default')
Break = node('Break')
Continue = node('Continue')
Return = node('Return', 'e')
ExprStmt = node('ExprStmt', 'e')
Empty = node('Empty')
FuncDef = node('FuncDef', 'rtype', 'name', 'params', 'body')
Param = node('Param', 'type', 'name', 'array', 'ref', 'default')
EnumDecl = node('EnumDecl', 'items')


class Type:
    """정규화한 자료형. base: void bool char uchar int uint long ulong float String cstr 또는 라이브러리 클래스."""
    __slots__ = ('base', 'const', 'static')

    def __init__(self, base, const=False, static=False):
        self.base, self.const, self.static = base, const, static

    def __repr__(self):
        return f'Type({self.base})'


LIB_CLASSES = ('Servo', 'LiquidCrystal_I2C', 'DHT', 'TM1637Display', 'LedControl')
TYPE_WORDS = {
    'void', 'bool', 'boolean', 'char', 'byte', 'int', 'short', 'long', 'unsigned', 'signed', 'float',
    'double', 'word', 'String', 'size_t', 'int8_t', 'uint8_t', 'int16_t', 'uint16_t', 'int32_t',
    'uint32_t', 'int64_t', 'uint64_t', 'const', 'static', 'volatile', 'unsigned', 'auto',
} | set(LIB_CLASSES)
SIMPLE = {
    'void': 'void', 'bool': 'bool', 'boolean': 'bool', 'byte': 'uchar', 'uint8_t': 'uchar',
    'int8_t': 'char', 'int16_t': 'int', 'uint16_t': 'uint', 'word': 'uint', 'size_t': 'uint',
    'int32_t': 'long', 'uint32_t': 'ulong', 'int64_t': 'long', 'uint64_t': 'ulong',
    'float': 'float', 'double': 'float', 'String': 'String',
}
CAST_WORDS = {'int', 'float', 'long', 'byte', 'char', 'bool', 'word', 'double', 'String', 'boolean'}

BINPREC = {'||': 1, '&&': 2, '|': 3, '^': 4, '&': 5, '==': 6, '!=': 6, '<': 7, '<=': 7, '>': 7, '>=': 7,
           '<<': 8, '>>': 8, '+': 9, '-': 9, '*': 10, '/': 10, '%': 10}
ASSIGN_OPS = {'=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>='}


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0
        self.enum_names = set()

    # --- 토큰 다루기
    def peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else self.toks[-1]

    def next(self):
        t = self.toks[self.i]
        if t.kind != 'eof':
            self.i += 1
        return t

    def is_op(self, val, k=0):
        t = self.peek(k)
        return t.kind == 'op' and t.val == val

    def accept(self, val):
        if self.is_op(val):
            return self.next()
        return None

    def expect(self, val, what=None):
        t = self.peek()
        if t.kind == 'op' and t.val == val:
            return self.next()
        line = t.line
        if val == ';':
            # 세미콜론 빠짐은 보통 앞 줄 끝에서 생깁니다
            prev = self.toks[self.i - 1] if self.i > 0 else t
            line = prev.line
            raise SketchError(line, "문장 끝에 ';'가 필요합니다")
        got = '파일 끝' if t.kind == 'eof' else f"'{t.val}'"
        raise SketchError(line, f"'{val}'가 필요한데 {got}{josa(got, '이가')} 있습니다" + (f' ({what})' if what else ''))

    def expect_id(self, what='이름'):
        t = self.peek()
        if t.kind != 'id':
            got = '파일 끝' if t.kind == 'eof' else f"'{t.val}'"
            raise SketchError(t.line, f'{what}이 필요한데 {got}{josa(got, '이가')} 있습니다')
        return self.next()

    # --- 자료형
    def at_type(self, k=0):
        t = self.peek(k)
        return t.kind == 'id' and t.val in TYPE_WORDS

    def parse_type(self):
        line = self.peek().line
        const = static = False
        words = []
        while self.peek().kind == 'id' and self.peek().val in TYPE_WORDS:
            # 이미 자료형이 있고 다음 낱말 뒤에 [ = ; , ( 가 오면 그 낱말은 변수 이름(예: char word[])
            nxt = self.peek(1)
            if any(w not in ('unsigned', 'signed') for w in words) and nxt.kind == 'op' and                     nxt.val in ('[', '=', ';', ',', '(', ')') and self.peek().val not in ('long', 'int', 'double'):
                break
            w = self.next().val
            if w == 'const':
                const = True
            elif w == 'static':
                static = True
            elif w in ('volatile', 'signed', 'auto'):
                if w == 'auto':
                    raise SketchError(line, "'auto'는 지원하지 않습니다. 자료형을 직접 적으십시오")
                if w == 'signed':
                    words.append('signed')
            else:
                words.append(w)
        if not words:
            raise SketchError(line, '자료형이 필요합니다')
        base = self.norm_type(words, line)
        ptr = 0
        while self.accept('*'):
            ptr += 1
            if self.peek().kind == 'id' and self.peek().val == 'const':
                self.next()
        if ptr:
            if base in ('char', 'uchar') and ptr == 1:
                base = 'cstr'
            else:
                raise SketchError(line, '포인터(*)는 지원하지 않습니다. 배열이나 String을 쓰십시오')
        return Type(base, const, static)

    @staticmethod
    def norm_type(words, line):
        ws = [w for w in words if w != 'signed']
        uns = 'unsigned' in ws
        ws = [w for w in ws if w != 'unsigned']
        if len(ws) == 1 and ws[0] in LIB_CLASSES:
            return ws[0]
        if len(ws) == 1 and ws[0] in SIMPLE:
            b = SIMPLE[ws[0]]
            if uns and b == 'char':
                return 'uchar'
            return b
        if not ws:
            return 'uint' if uns else 'int'
        if ws == ['char']:
            return 'uchar' if uns else 'char'
        if ws in (['int'], ['short'], ['short', 'int']):
            return 'uint' if uns else 'int'
        if ws in (['long'], ['long', 'int'], ['long', 'long'], ['long', 'long', 'int']):
            return 'ulong' if uns else 'long'
        if ws == ['long', 'double']:
            return 'float'
        raise SketchError(line, f"'{' '.join(words)}' 자료형을 이해하지 못했습니다")

    # --- 최상위
    def parse_program(self):
        items = []
        while self.peek().kind != 'eof':
            if self.accept(';'):
                continue
            t = self.peek()
            if t.kind == 'id' and t.val == 'enum':
                items.append(self.parse_enum())
                continue
            if t.kind == 'id' and t.val in ('struct', 'class', 'typedef', 'union', 'template', 'namespace'):
                raise SketchError(t.line, f"'{t.val}'는 지원하지 않습니다")
            if not self.at_type():
                got = '파일 끝' if t.kind == 'eof' else f"'{t.val}'"
                raise SketchError(t.line, f'여기에는 함수나 변수를 만드는 문장이 와야 하는데 {got}{josa(got, '이가')} 있습니다')
            typ = self.parse_type()
            name = self.expect_id('함수나 변수 이름')
            if self.is_op('(') and typ.base not in LIB_CLASSES and self.looks_like_params():
                items.append(self.parse_function(typ, name))
            else:
                items.append(self.parse_decl_rest(typ, name))
        return items

    def looks_like_params(self):
        # '(' 다음이 ')' 또는 자료형이면 함수
        return self.is_op(')', 1) or self.at_type(1)

    def parse_enum(self):
        line = self.next().line
        if self.peek().kind == 'id':
            self.next()
        self.expect('{')
        items = []
        val = 0
        while not self.is_op('}'):
            name = self.expect_id('열거 상수 이름').val
            e = None
            if self.accept('='):
                e = self.parse_cond()
            items.append((name, e))
            self.enum_names.add(name)
            if not self.accept(','):
                break
        self.expect('}')
        self.expect(';')
        return EnumDecl(line, items)

    def parse_function(self, rtype, name):
        self.expect('(')
        params = []
        if self.is_op('void') or (self.peek().kind == 'id' and self.peek().val == 'void' and self.is_op(')', 1)):
            self.next()
        while not self.is_op(')'):
            pline = self.peek().line
            ptype = self.parse_type()
            ref = bool(self.accept('&'))
            pname = None
            if self.peek().kind == 'id':
                pname = self.next().val
            array = 0
            while self.accept('['):
                if not self.is_op(']'):
                    self.parse_cond()
                self.expect(']')
                array += 1
            default = None
            if self.accept('='):
                default = self.parse_assign()
            params.append(Param(pline, ptype, pname, array, ref, default))
            if not self.accept(','):
                break
        self.expect(')', '함수 매개변수 목록')
        if self.accept(';'):
            return FuncDef(name.line, rtype, name.val, params, None)
        if not self.is_op('{'):
            raise SketchError(self.peek().line, "함수 본문을 여는 '{'가 필요합니다")
        body = self.parse_block()
        return FuncDef(name.line, rtype, name.val, params, body)

    def parse_decl_rest(self, typ, name_tok):
        decls = [self.parse_declarator(typ, name_tok)]
        while self.accept(','):
            decls.append(self.parse_declarator(typ, self.expect_id('변수 이름')))
        self.expect(';')
        return VarDecl(name_tok.line, typ, decls)

    def parse_declarator(self, typ, name_tok):
        dims = []
        while self.accept('['):
            if self.is_op(']'):
                dims.append(None)
            else:
                dims.append(self.parse_cond())
            self.expect(']')
        init = ctor = None
        if self.accept('='):
            if self.is_op('{'):
                init = self.parse_init_list()
            else:
                init = self.parse_assign()
        elif self.is_op('('):
            self.next()
            ctor = []
            while not self.is_op(')'):
                ctor.append(self.parse_assign())
                if not self.accept(','):
                    break
            self.expect(')')
        elif self.is_op('{'):
            init = self.parse_init_list()
        return Declarator(name_tok.line, name_tok.val, dims, init, ctor)

    def parse_init_list(self):
        line = self.expect('{').line
        items = []
        while not self.is_op('}'):
            if self.is_op('{'):
                items.append(self.parse_init_list())
            else:
                items.append(self.parse_assign())
            if not self.accept(','):
                break
        self.expect('}', '초기값 목록')
        return InitList(line, items)

    # --- 문장
    def parse_block(self):
        line = self.expect('{').line
        stmts = []
        while not self.is_op('}'):
            if self.peek().kind == 'eof':
                raise SketchError(line, "'{'가 '}'로 닫히지 않았습니다")
            stmts.append(self.parse_stmt())
        self.next()
        return Block(line, stmts)

    def parse_stmt(self):
        t = self.peek()
        line = t.line
        if t.kind == 'op':
            if t.val == '{':
                return self.parse_block()
            if t.val == ';':
                self.next()
                return Empty(line)
        if t.kind == 'id':
            w = t.val
            if w == 'if':
                self.next()
                self.expect('(')
                c = self.parse_expr()
                self.expect(')', 'if 조건')
                then = self.parse_stmt()
                other = None
                if self.peek().kind == 'id' and self.peek().val == 'else':
                    self.next()
                    other = self.parse_stmt()
                return If(line, c, then, other)
            if w == 'while':
                self.next()
                self.expect('(')
                c = self.parse_expr()
                self.expect(')', 'while 조건')
                return While(line, c, self.parse_stmt())
            if w == 'do':
                self.next()
                body = self.parse_stmt()
                t2 = self.peek()
                if not (t2.kind == 'id' and t2.val == 'while'):
                    raise SketchError(t2.line, "do { } 뒤에 while(...)이 필요합니다")
                self.next()
                self.expect('(')
                c = self.parse_expr()
                self.expect(')')
                self.expect(';')
                return DoWhile(line, body, c)
            if w == 'for':
                self.next()
                self.expect('(')
                init = None
                if not self.is_op(';'):
                    if self.at_type():
                        typ = self.parse_type()
                        init = self.parse_decl_rest(typ, self.expect_id('변수 이름'))
                    else:
                        init = ExprStmt(line, self.parse_expr())
                        self.expect(';')
                else:
                    self.next()
                c = None if self.is_op(';') else self.parse_expr()
                self.expect(';')
                step = None if self.is_op(')') else self.parse_expr()
                self.expect(')', 'for 괄호')
                return For(line, init, c, step, self.parse_stmt())
            if w == 'switch':
                self.next()
                self.expect('(')
                e = self.parse_expr()
                self.expect(')')
                if not self.is_op('{'):
                    raise SketchError(self.peek().line, "switch 뒤에 '{'가 필요합니다")
                return Switch(line, e, self.parse_block())
            if w == 'case':
                self.next()
                e = self.parse_cond()
                self.expect(':', 'case')
                return Case(line, e)
            if w == 'default':
                self.next()
                self.expect(':', 'default')
                return Default(line)
            if w == 'break':
                self.next()
                self.expect(';')
                return Break(line)
            if w == 'continue':
                self.next()
                self.expect(';')
                return Continue(line)
            if w == 'return':
                self.next()
                e = None if self.is_op(';') else self.parse_expr()
                self.expect(';')
                return Return(line, e)
            if w == 'goto':
                raise SketchError(line, "'goto'는 지원하지 않습니다")
            if w == 'else':
                raise SketchError(line, "'else' 앞에 짝이 되는 if가 없습니다")
            if self.at_type() and not (w in CAST_WORDS and self.is_op('(', 1)):
                typ = self.parse_type()
                return self.parse_decl_rest(typ, self.expect_id('변수 이름'))
        e = self.parse_expr()
        self.expect(';')
        return ExprStmt(line, e)

    # --- 식
    def parse_expr(self):
        e = self.parse_assign()
        if self.is_op(','):
            items = [e]
            while self.accept(','):
                items.append(self.parse_assign())
            return Comma(e.line, items)
        return e

    def parse_assign(self):
        lhs = self.parse_cond()
        t = self.peek()
        if t.kind == 'op' and t.val in ASSIGN_OPS:
            self.next()
            rhs = self.parse_assign()
            return Assign(t.line, t.val, lhs, rhs)
        return lhs

    def parse_cond(self):
        c = self.parse_bin(1)
        if self.is_op('?'):
            line = self.next().line
            a = self.parse_expr()
            self.expect(':', '조건 연산자 ?:')
            b = self.parse_assign()
            return Cond(line, c, a, b)
        return c

    def parse_bin(self, minp):
        left = self.parse_unary()
        while True:
            t = self.peek()
            if t.kind != 'op' or t.val not in BINPREC:
                return left
            p = BINPREC[t.val]
            if p < minp:
                return left
            self.next()
            right = self.parse_bin(p + 1)
            left = Bin(t.line, t.val, left, right)

    def parse_unary(self):
        t = self.peek()
        if t.kind == 'op':
            if t.val in ('!', '~', '-', '+'):
                self.next()
                return Unary(t.line, t.val, self.parse_unary())
            if t.val in ('++', '--'):
                self.next()
                return IncDec(t.line, t.val, self.parse_unary(), False)
            if t.val in ('*', '&'):
                raise SketchError(t.line, f"포인터 연산자 '{t.val}'는 지원하지 않습니다")
            if t.val == '(' and self.at_type(1):
                # (자료형) 식
                save = self.i
                self.next()
                try:
                    typ = self.parse_type()
                except SketchError:
                    self.i = save
                    return self.parse_postfix()
                if self.accept(')'):
                    return Cast(t.line, typ, self.parse_unary())
                self.i = save
        if t.kind == 'id' and t.val == 'sizeof':
            self.next()
            self.expect('(')
            if self.at_type():
                typ = self.parse_type()
                self.expect(')')
                return SizeOf(t.line, typ, None)
            e = self.parse_expr()
            self.expect(')')
            return SizeOf(t.line, None, e)
        return self.parse_postfix()

    def parse_args(self):
        self.expect('(')
        args = []
        while not self.is_op(')'):
            args.append(self.parse_assign())
            if not self.accept(','):
                break
        self.expect(')', '함수 호출의 닫는 괄호')
        return args

    def parse_postfix(self):
        e = self.parse_primary()
        while True:
            t = self.peek()
            if t.kind != 'op':
                return e
            if t.val == '(':
                if not isinstance(e, Name):
                    raise SketchError(t.line, '이 식은 함수처럼 호출할 수 없습니다')
                e = Call(e.line, e.id, self.parse_args())
            elif t.val == '[':
                self.next()
                idx = self.parse_expr()
                self.expect(']')
                e = Index(t.line, e, idx)
            elif t.val in ('.', '->'):
                self.next()
                name = self.expect_id('멤버 이름').val
                if self.is_op('('):
                    e = Method(t.line, e, name, self.parse_args())
                else:
                    e = Member(t.line, e, name)
            elif t.val in ('++', '--'):
                self.next()
                e = IncDec(t.line, t.val, e, True)
            else:
                return e

    def parse_primary(self):
        t = self.next()
        if t.kind == 'num':
            return Num(t.line, t.val, t.ntype)
        if t.kind == 'str':
            return Str(t.line, t.val)
        if t.kind == 'id':
            if t.val in CAST_WORDS and self.is_op('('):
                args = self.parse_args()
                if t.val == 'String':
                    return Call(t.line, 'String', args)
                if len(args) != 1:
                    raise SketchError(t.line, f'{t.val}(...)에는 값이 하나 필요합니다')
                return Cast(t.line, Type(self.norm_type([t.val], t.line)), args[0])
            if t.val in TYPE_WORDS:
                raise SketchError(t.line, f"'{t.val}'를 여기에 쓸 수 없습니다")
            return Name(t.line, t.val)
        if t.kind == 'op' and t.val == '(':
            e = self.parse_expr()
            self.expect(')')
            return e
        if t.kind == 'op' and t.val == '{':
            self.i -= 1
            return self.parse_init_list()
        got = '파일 끝' if t.kind == 'eof' else f"'{t.val}'"
        raise SketchError(t.line, f'여기에 값이나 식이 와야 하는데 {got}{josa(got, '이가')} 있습니다')


def parse(src):
    toks, includes = preprocess(src)
    items = Parser(toks).parse_program()
    return items, includes
