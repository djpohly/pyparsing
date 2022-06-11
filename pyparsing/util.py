# util.py
import warnings
import types
import collections
import itertools
import inspect
from functools import lru_cache
from typing import List, Union, Iterable, Callable, TypeVar, cast

_bslash = chr(92)
T = TypeVar("T", bound=Callable)


class __config_flags:
    """Internal class for defining compatibility and debugging flags"""

    _all_names: List[str] = []
    _fixed_names: List[str] = []
    _type_desc = "configuration"

    @classmethod
    def _set(cls, dname, value):
        if dname in cls._fixed_names:
            warnings.warn(
                f"{cls.__name__}.{dname} {cls._type_desc} is {str(getattr(cls, dname)).upper()}"
                f" and cannot be overridden"
            )
            return
        if dname in cls._all_names:
            setattr(cls, dname, value)
        else:
            raise ValueError(f"no such {cls._type_desc} {dname!r}")

    enable = classmethod(lambda cls, name: cls._set(name, True))
    disable = classmethod(lambda cls, name: cls._set(name, False))


@lru_cache(maxsize=128)
def col(loc: int, strg: str) -> int:
    """
    Returns current column within a string, counting newlines as line separators.
    The first column is number 1.

    Note: the default parsing behavior is to expand tabs in the input string
    before starting the parsing process.  See
    :class:`ParserElement.parse_string` for more
    information on parsing strings containing ``<TAB>`` s, and suggested
    methods to maintain a consistent view of the parsed string, the parse
    location, and line and column positions within the parsed string.
    """
    s = strg
    return 1 if 0 < loc < len(s) and s[loc - 1] == "\n" else loc - s.rfind("\n", 0, loc)


@lru_cache(maxsize=128)
def lineno(loc: int, strg: str) -> int:
    """Returns current line number within a string, counting newlines as line separators.
    The first line is number 1.

    Note - the default parsing behavior is to expand tabs in the input string
    before starting the parsing process.  See :class:`ParserElement.parse_string`
    for more information on parsing strings containing ``<TAB>`` s, and
    suggested methods to maintain a consistent view of the parsed string, the
    parse location, and line and column positions within the parsed string.
    """
    return strg.count("\n", 0, loc) + 1


@lru_cache(maxsize=128)
def line(loc: int, strg: str) -> str:
    """
    Returns the line of text containing loc within a string, counting newlines as line separators.
    """
    last_cr = strg.rfind("\n", 0, loc)
    next_cr = strg.find("\n", loc)
    return strg[last_cr + 1 : next_cr] if next_cr >= 0 else strg[last_cr + 1 :]


class _UnboundedCache:
    def __init__(self):
        cache = {}
        cache_get = cache.get
        self.not_in_cache = not_in_cache = object()

        def get(_, key):
            return cache_get(key, not_in_cache)

        def set_(_, key, value):
            cache[key] = value

        def clear(_):
            cache.clear()

        self.size = None
        self.get = types.MethodType(get, self)
        self.set = types.MethodType(set_, self)
        self.clear = types.MethodType(clear, self)


class _FifoCache:
    def __init__(self, size):
        self.not_in_cache = not_in_cache = object()
        cache = collections.OrderedDict()
        cache_get = cache.get

        def get(_, key):
            return cache_get(key, not_in_cache)

        def set_(_, key, value):
            cache[key] = value
            while len(cache) > size:
                cache.popitem(last=False)

        def clear(_):
            cache.clear()

        self.size = size
        self.get = types.MethodType(get, self)
        self.set = types.MethodType(set_, self)
        self.clear = types.MethodType(clear, self)


class LRUMemo:
    """
    A memoizing mapping that retains `capacity` deleted items

    The memo tracks retained items by their access order; once `capacity` items
    are retained, the least recently used item is discarded.
    """

    def __init__(self, capacity):
        self._capacity = capacity
        self._active = {}
        self._memory = collections.OrderedDict()

    def __getitem__(self, key):
        try:
            return self._active[key]
        except KeyError:
            self._memory.move_to_end(key)
            return self._memory[key]

    def __setitem__(self, key, value):
        self._memory.pop(key, None)
        self._active[key] = value

    def __delitem__(self, key):
        try:
            value = self._active.pop(key)
        except KeyError:
            pass
        else:
            while len(self._memory) >= self._capacity:
                self._memory.popitem(last=False)
            self._memory[key] = value

    def clear(self):
        self._active.clear()
        self._memory.clear()


class UnboundedMemo(dict):
    """
    A memoizing mapping that retains all deleted items
    """

    def __delitem__(self, key):
        pass


def _escape_regex_range_chars(s: str) -> str:
    # escape these chars: ^-[]
    for c in r"\^-[]":
        s = s.replace(c, _bslash + c)
    s = s.replace("\n", r"\n")
    s = s.replace("\t", r"\t")
    return str(s)


def _collapse_string_to_ranges(
    s: Union[str, Iterable[str]], re_escape: bool = True
) -> str:
    def is_consecutive(c):
        c_int = ord(c)
        is_consecutive.prev, prev = c_int, is_consecutive.prev
        if c_int - prev > 1:
            is_consecutive.value = next(is_consecutive.counter)
        return is_consecutive.value

    is_consecutive.prev = 0  # type: ignore [attr-defined]
    is_consecutive.counter = itertools.count()  # type: ignore [attr-defined]
    is_consecutive.value = -1  # type: ignore [attr-defined]

    def escape_re_range_char(c):
        return "\\" + c if c in r"\^-][" else c

    def no_escape_re_range_char(c):
        return c

    if not re_escape:
        escape_re_range_char = no_escape_re_range_char

    ret = []
    s = "".join(sorted(set(s)))
    if len(s) > 3:
        for _, chars in itertools.groupby(s, key=is_consecutive):
            first = last = next(chars)
            last = collections.deque(
                itertools.chain(iter([last]), chars), maxlen=1
            ).pop()
            if first == last:
                ret.append(escape_re_range_char(first))
            else:
                sep = "" if ord(last) == ord(first) + 1 else "-"
                ret.append(
                    f"{escape_re_range_char(first)}{sep}{escape_re_range_char(last)}"
                )
    else:
        ret = [escape_re_range_char(c) for c in s]

    return "".join(ret)


def _flatten(ll: list) -> list:
    ret = []
    for i in ll:
        if isinstance(i, list):
            ret.extend(_flatten(i))
        else:
            ret.append(i)
    return ret


def _duplicate_function(fn: T, name: str = "", context: str = "") -> T:
    """
    Creates a new function object as a "shallow copy" of an existing function.
    The new object refers to the existing code but can be given different
    attributes.

    Example::

        def foo():
            print("hello")
        bar = _duplicate_function(foo, "baz")

        print(bar)
        print(bar is foo)
        print(bar.__code__ is foo.__code__)
        bar()

    prints::

        <function baz at 0x7f5dfe8f3640>
        False
        True
        hello
    """
    wrapper = types.FunctionType(
        fn.__code__,
        fn.__globals__,
        name or fn.__name__,
        fn.__defaults__,
        fn.__closure__,
    )
    wrapper.__kwdefaults__ = fn.__kwdefaults__
    #wrapper.__annotations__ = fn.__annotations__
    if context:
        wrapper.__qualname__ = f"{context}.{wrapper.__name__}"
    else:
        wrapper.__qualname__ = wrapper.__name__
    return cast(T, wrapper)


def pep8_function_alias(name: str, wrapped: T) -> T:
    if not isinstance(wrapped, types.FunctionType):
        return wrapped
    wrapper = _duplicate_function(wrapped, name)
    wrapper.__doc__ = (
        f"Deprecated pre-PEP8 alias for :func:`{wrapped.__name__}`.\n\n"
        + (inspect.getdoc(wrapped) or "")
    )
    # This wrapper should work the same way as the original, so use a cast to
    # help out static type checkers.
    return cast(T, wrapper)


class _PEP8MethodAlias:
    def __init__(self, method: object):
        self.method = method

    def __set_name__(self, owner: type[object], name: str):
        wrapper: Union[classmethod, staticmethod, types.FunctionType]
        fn: object

        method = self.method
        if isinstance(method, (classmethod, staticmethod)):
            # Unwrap the function inside the descriptor
            fn = method.__get__(None, owner)
        else:
            fn = method

        if not isinstance(fn, types.FunctionType):
            # If we're not dealing with an actual function, pass the original
            # through unmodified
            setattr(owner, name, method)
            return

        wrapper = _duplicate_function(fn)
        wrapper.__doc__ = (
            f"Deprecated pre-PEP8 alias for :meth:`{fn.__name__}`.\n\n"
            + (inspect.getdoc(fn) or "")
        )
        # Re-wrap classmethod/staticmethod
        if isinstance(method, (classmethod, staticmethod)):
            wrapper = type(method)(wrapper)
        # Replace this object with the wrapper itself
        setattr(owner, name, wrapper)


def pep8_method_alias(wrapped: T) -> T:
    if not isinstance(wrapped, (types.FunctionType, classmethod, staticmethod)):
        return wrapped
    # This object will be replaced with an equivalent wrapper, so use a cast to
    # help out static type checkers.
    return cast(T, _PEP8MethodAlias(wrapped))
