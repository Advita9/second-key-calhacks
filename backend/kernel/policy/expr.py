"""Tiny safe expression language for policy `when` clauses. No eval, no exec, no builtins.

grammar (lowest to highest precedence):
    or > and > not > cmp(== != < <= > >= in, not in) > sum(+ -) > prod(* /) > unary(-) > atom
    atom := NUMBER | STRING | true | false | IDENT(.IDENT)*
          | '[' [expr (',' expr)*] ']' | '(' expr ')'

Rules:
- A bare ALL_CAPS identifier (`WIRE`, `PG_E`) is a string literal. Anything else is looked up
  in the environment; a missing name is an EvalError at run time and a PolicyLoadError at load.
- and / or / not only accept booleans. No truthiness.
- < <= > >= + - * / only accept numbers (bool is not a number). `/` is true division.
- `in` requires a list on the right. Comparisons do not chain (`a < b < c` is a ParseError).
- Limits: MAX_SOURCE chars, MAX_TOKENS tokens, MAX_DEPTH nesting. Exceeding any is a ParseError.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

MAX_DEPTH = 64
MAX_TOKENS = 512
MAX_SOURCE = 4096

KEYWORDS = frozenset({"and", "or", "not", "in", "true", "false"})
_ALL_CAPS = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ParseError(ValueError):
    """Malformed source. Raised by tokenize/parse."""


class EvalError(ValueError):
    """Well-formed expression that cannot be evaluated against this environment."""


@dataclass(frozen=True)
class Token:
    kind: str  # NUM STR IDENT KW OP EOF
    value: str
    pos: int


@dataclass(frozen=True)
class Lit:
    value: int | float | str | bool


@dataclass(frozen=True)
class Ident:
    name: str


@dataclass(frozen=True)
class ListLit:
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Not:
    operand: Node


@dataclass(frozen=True)
class Neg:
    operand: Node


@dataclass(frozen=True)
class BinOp:
    op: str  # or and == != < <= > >= in "not in" + - * /
    left: Node
    right: Node


Node = Lit | Ident | ListLit | Not | Neg | BinOp

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<num>\d[\d_]*(?:\.\d[\d_]*)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
  | (?P<str>'[^'\n]*'|"[^"\n]*")
  | (?P<op>==|!=|<=|>=|<|>|\+|-|\*|/|\(|\)|\[|\]|,)
    """,
    re.VERBOSE,
)


def tokenize(src: str) -> list[Token]:
    if not isinstance(src, str):
        raise ParseError("source must be a string")
    if len(src) > MAX_SOURCE:
        raise ParseError(f"source longer than {MAX_SOURCE} chars")
    out: list[Token] = []
    pos = 0
    n = len(src)
    while pos < n:
        m = _TOKEN_RE.match(src, pos)
        if m is None:
            raise ParseError(f"unexpected character {src[pos]!r} at {pos}")
        kind = m.lastgroup
        text = m.group()
        if kind == "ws":
            pass
        elif kind == "num":
            out.append(Token("NUM", text, pos))
        elif kind == "ident":
            parts = text.split(".")
            if any(part in KEYWORDS for part in parts):
                if len(parts) == 1:
                    out.append(Token("KW", text, pos))
                else:
                    raise ParseError(f"keyword inside dotted name {text!r} at {pos}")
            else:
                out.append(Token("IDENT", text, pos))
        elif kind == "str":
            out.append(Token("STR", text[1:-1], pos))
        else:
            out.append(Token("OP", text, pos))
        if len(out) > MAX_TOKENS:
            raise ParseError(f"more than {MAX_TOKENS} tokens")
        pos = m.end()
    out.append(Token("EOF", "", n))
    return out


_BINARY_PREC: dict[str, int] = {
    "or": 1,
    "and": 2,
    # not (prefix) = 3
    "==": 4,
    "!=": 4,
    "<": 4,
    "<=": 4,
    ">": 4,
    ">=": 4,
    "in": 4,
    "not in": 4,
    "+": 5,
    "-": 5,
    "*": 6,
    "/": 6,
    # unary minus (prefix) = 7
}
_NOT_PREC = 3
_CMP_PREC = 4


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.toks = tokens
        self.i = 0
        self.depth = 0

    # helpers --------------------------------------------------------------------------
    def peek(self, k: int = 0) -> Token:
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def take(self) -> Token:
        t = self.toks[self.i]
        if t.kind != "EOF":
            self.i += 1
        return t

    def expect_op(self, value: str) -> None:
        t = self.take()
        if t.kind != "OP" or t.value != value:
            raise ParseError(f"expected {value!r} at {t.pos}, got {t.value!r}")

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ParseError(f"nesting deeper than {MAX_DEPTH}")

    def leave(self) -> None:
        self.depth -= 1

    def binary_op(self) -> str | None:
        t = self.peek()
        if t.kind == "OP" and t.value in _BINARY_PREC:
            return t.value
        if t.kind == "KW":
            if t.value in ("and", "or", "in"):
                return t.value
            if t.value == "not":
                nxt = self.peek(1)
                if nxt.kind == "KW" and nxt.value == "in":
                    return "not in"
                raise ParseError(f"unexpected 'not' at {t.pos}")
        return None

    # grammar --------------------------------------------------------------------------
    def parse(self) -> Node:
        node = self.expr(1)
        t = self.peek()
        if t.kind != "EOF":
            raise ParseError(f"unexpected {t.value!r} at {t.pos}")
        return node

    def expr(self, min_prec: int) -> Node:
        """Precedence climbing over binary operators; left associative."""
        lhs = self.unary()
        while True:
            op = self.binary_op()
            if op is None:
                return lhs
            prec = _BINARY_PREC[op]
            if prec < min_prec:
                return lhs
            self.take()
            if op == "not in":
                self.take()
            rhs = self.expr(prec + 1)
            lhs = BinOp(op, lhs, rhs)
            if prec == _CMP_PREC:
                nxt = self.binary_op()
                if nxt is not None and _BINARY_PREC[nxt] == _CMP_PREC:
                    raise ParseError(f"chained comparison at {self.peek().pos}")

    def unary(self) -> Node:
        t = self.peek()
        if t.kind == "KW" and t.value == "not":
            self.take()
            self.enter()
            operand = self.expr(_NOT_PREC)
            self.leave()
            return Not(operand)
        if t.kind == "OP" and t.value == "-":
            self.take()
            self.enter()
            operand = self.unary()
            self.leave()
            return Neg(operand)
        return self.atom()

    def atom(self) -> Node:
        t = self.take()
        if t.kind == "NUM":
            return Lit(_number(t))
        if t.kind == "STR":
            return Lit(t.value)
        if t.kind == "KW":
            if t.value == "true":
                return Lit(True)
            if t.value == "false":
                return Lit(False)
            raise ParseError(f"unexpected keyword {t.value!r} at {t.pos}")
        if t.kind == "IDENT":
            if _ALL_CAPS.match(t.value):
                return Lit(t.value)
            return Ident(t.value)
        if t.kind == "OP" and t.value == "(":
            self.enter()
            node = self.expr(1)
            self.leave()
            self.expect_op(")")
            return node
        if t.kind == "OP" and t.value == "[":
            self.enter()
            items: list[Node] = []
            if not (self.peek().kind == "OP" and self.peek().value == "]"):
                items.append(self.expr(1))
                while self.peek().kind == "OP" and self.peek().value == ",":
                    self.take()
                    items.append(self.expr(1))
            self.leave()
            self.expect_op("]")
            return ListLit(tuple(items))
        if t.kind == "EOF":
            raise ParseError("unexpected end of expression")
        raise ParseError(f"unexpected {t.value!r} at {t.pos}")


def _number(t: Token) -> int | float:
    text = t.value.replace("_", "")
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError as e:  # e.g. int string longer than the interpreter's digit limit
        raise ParseError(f"bad number at {t.pos}: {e}") from None


def parse(src: str) -> Node:
    return _Parser(tokenize(src)).parse()


def free_identifiers(node: Node) -> frozenset[str]:
    """Names the expression reads from the environment. ALL_CAPS literals are not included."""
    out: set[str] = set()
    stack: list[Node] = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, Ident):
            out.add(n.name)
        elif isinstance(n, ListLit):
            stack.extend(n.items)
        elif isinstance(n, Not | Neg):
            stack.append(n.operand)
        elif isinstance(n, BinOp):
            stack.append(n.left)
            stack.append(n.right)
    return frozenset(out)


# evaluation -----------------------------------------------------------------------------


def _is_num(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _eq(a: object, b: object) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, list) or isinstance(b, list):
        if not (isinstance(a, list) and isinstance(b, list)) or len(a) != len(b):
            return False
        return all(_eq(x, y) for x, y in zip(a, b, strict=True))
    if _is_num(a) and _is_num(b):
        return bool(a == b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return False


def _bool(v: object, what: str) -> bool:
    if isinstance(v, bool):
        return v
    raise EvalError(f"{what} requires a boolean, got {type(v).__name__}")


def _num(v: object, what: str) -> int | float:
    if _is_num(v):
        assert isinstance(v, int | float)
        return v
    raise EvalError(f"{what} requires a number, got {type(v).__name__}")


def evaluate(node: Node, env: Mapping[str, object]) -> object:
    """Evaluate against `env`. Raises EvalError on unknown names, type mismatches, math errors."""
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, Ident):
        try:
            return env[node.name]
        except KeyError:
            raise EvalError(f"unknown identifier {node.name!r}") from None
    if isinstance(node, ListLit):
        return [evaluate(item, env) for item in node.items]
    if isinstance(node, Not):
        return not _bool(evaluate(node.operand, env), "not")
    if isinstance(node, Neg):
        return -_num(evaluate(node.operand, env), "unary -")
    op = node.op
    if op == "and":
        return _bool(evaluate(node.left, env), "and") and _bool(evaluate(node.right, env), "and")
    if op == "or":
        return _bool(evaluate(node.left, env), "or") or _bool(evaluate(node.right, env), "or")
    left = evaluate(node.left, env)
    right = evaluate(node.right, env)
    if op == "==":
        return _eq(left, right)
    if op == "!=":
        return not _eq(left, right)
    if op in ("in", "not in"):
        if not isinstance(right, list):
            raise EvalError(f"{op!r} requires a list on the right, got {type(right).__name__}")
        found = any(_eq(left, item) for item in right)
        return found if op == "in" else not found
    a = _num(left, op)
    b = _num(right, op)
    try:
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        if op == ">=":
            return a >= b
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return a / b
    except (ZeroDivisionError, OverflowError, ValueError) as e:
        raise EvalError(f"{op!r}: {e}") from None
    raise EvalError(f"unknown operator {op!r}")
