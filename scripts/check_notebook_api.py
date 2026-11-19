"""Static API check of design / tutorial notebooks. Nothing in a notebook is executed.

    python scripts/check_notebook_api.py NOTEBOOK.ipynb [NOTEBOOK.ipynb ...] [--clean] [--verbose]

Per notebook:

1. **nbformat**: the file validates against the nbformat schema (``nbformat.validate``).
2. **syntax**: every code cell parses (magics and ``!`` lines transformed the way IPython does, then ``ast.parse``).
3. **names**: every name a code cell reads is bound somewhere in the notebook (assignment, import, ``def``, ``for``,
   ``with … as``, comprehension, argument …), is a builtin or an IPython name, or comes from a star import.
4. **imports**: every module the notebook imports imports, with ``sys.path`` as the notebooks set it (the repo root
   as the working directory; ``examples/designs``, ``examples/designs/<group>``, ``examples/tutorials`` and the
   notebook's own folder on the path); every ``from m import x`` name exists. An import in a cell that puts an
   upstream folder on ``sys.path`` at run time (``sys.path.insert(0, str(upstream_path(...)))``) is a note, not a
   failure.
5. **calls**: for every call the checker can resolve statically, the attribute exists and the arguments bind to
   ``inspect.signature`` (no unknown keyword, not too many positional arguments, no missing required argument when
   the call passes no ``*args`` / ``**kwargs``). Resolvable: an imported function or class, an attribute chain on an
   imported module, a function or lambda-free ``def`` of the notebook, a method or property of a variable assigned
   from a resolvable call (``d = Designer(...)`` → ``d.add(...)``; return types from annotations, e.g.
   ``q = d.add(...)`` → ``InstanceHandle``). Everything else is counted as *unchecked* (``--verbose`` lists them).

``--clean``: also require cleared outputs (no outputs, no execution counts), for notebooks written to be run later.

Importing a module runs its top-level code (the library, ``_common``): that is all that runs. Exit code 1 when a
notebook fails a check.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import importlib
import inspect
import json
import os
import sys
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IPYTHON_NAMES = {"display", "get_ipython", "In", "Out", "_", "__", "___", "exit", "quit"}
# factories without a return annotation whose result the notebooks use as a Designer
KNOWN_RETURNS = {"_common.design_copy": "quantcore_circuits.designer.Designer"}
_UNKNOWN = object()
DYNAMIC_MODULES = {"klayout", "pya"}  # extension classes whose methods are added at run time


def _cell_source(cell) -> str:
    src = cell["source"]
    return "".join(src) if isinstance(src, list) else src


def _python(cell: str) -> str:
    try:
        from IPython.core.inputtransformer2 import TransformerManager  # pylint: disable=import-outside-toplevel

        return TransformerManager().transform_cell(cell)
    except ImportError:
        return "\n".join("" if line.lstrip().startswith(("%", "!")) else line for line in cell.splitlines())


def _setup_path(nb: Path) -> None:
    os.environ.setdefault("QCC_LIVE", "0")
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    designs = ROOT / "examples" / "designs"
    helpers = sorted({p.parent for p in designs.glob("*/_*.py")})  # _qpdk, _surface17, _amplifiers, _legacy* …
    for p in (*helpers, ROOT / "examples" / "tutorials", designs, ROOT / "examples", ROOT, nb.parent):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    os.chdir(ROOT)


# ---- names ---------------------------------------------------------------------------------------------------------
def _bound_names(trees) -> set[str]:
    out = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                out.add(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(node.name)
            elif isinstance(node, ast.arg):
                out.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                out.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    if a.name != "*":
                        out.add(a.asname or a.name.split(".")[0])
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                out.update(node.names)
            elif isinstance(node, ast.MatchAs) and node.name:
                out.add(node.name)
    return out


# ---- static types --------------------------------------------------------------------------------------------------
def _return_type(func):
    """The class a callable returns, from its annotation (or :data:`KNOWN_RETURNS`); ``_UNKNOWN`` otherwise."""
    if inspect.isclass(func):
        return func
    key = f"{getattr(func, '__module__', '')}.{getattr(func, '__qualname__', '')}"
    if key in KNOWN_RETURNS:
        mod, _, name = KNOWN_RETURNS[key].rpartition(".")
        try:
            return getattr(importlib.import_module(mod), name)
        except Exception:  # noqa: BLE001
            return _UNKNOWN
    target = getattr(func, "__func__", func)
    ann = getattr(target, "__annotations__", {}).get("return")
    if ann is None:
        return _UNKNOWN
    if isinstance(ann, str):
        try:
            ann = eval(ann, getattr(target, "__globals__", {}))  # noqa: S307  (an annotation string, not notebook code)
        except Exception:  # noqa: BLE001
            return _UNKNOWN
    if typing.get_origin(ann) is not None:
        return typing.get_origin(ann) if inspect.isclass(typing.get_origin(ann)) else _UNKNOWN
    return ann if inspect.isclass(ann) else _UNKNOWN


def _instance_attrs(cls) -> set[str]:
    """Attributes instances of ``cls`` get outside the class body (``self.x = …`` in any method), dataclass /
    pydantic fields and annotations."""
    out = set()
    for klass in inspect.getmro(cls):
        out.update(getattr(klass, "__annotations__", {}) or {})
        out.update(getattr(klass, "model_fields", {}) or {})
        out.update(getattr(klass, "__dataclass_fields__", {}) or {})
        try:
            tree = ast.parse(inspect.getsource(klass).lstrip())  # dedented enough for a class statement
        except (OSError, TypeError, SyntaxError, IndentationError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name)
                    and node.value.id == "self"):
                out.add(node.attr)
    return out


class Checker:
    def __init__(self, nb_path: Path):
        self.path = nb_path
        self.problems: list[str] = []
        self.notes: list[str] = []  # imports the checker cannot follow (a cell that extends sys.path at run time)
        self.unchecked: list[str] = []
        self.checked = 0
        self.env: dict[str, object] = {}  # name → module / object (imports, star imports)
        self.types: dict[str, object] = {}  # name → class of the value (instances), or _UNKNOWN
        self.local_defs: dict[str, ast.FunctionDef] = {}

    def fail(self, where: str, msg: str) -> None:
        self.problems.append(f"{where}: {msg}")

    # -- imports
    def import_failed(self, where: str, what: str, e: Exception, runtime_path: bool) -> None:
        msg = f"{what} failed: {type(e).__name__}: {e}"
        if runtime_path:  # the cell puts a folder on sys.path when it runs: not something a static check can follow
            self.notes.append(f"{where}: {msg} (the cell extends sys.path at run time; not checked)")
        else:
            self.fail(where, msg)

    def do_imports(self, trees) -> None:
        for i, tree in trees:
            runtime_path = any(isinstance(n, ast.Call) and ast.unparse(n.func) in ("sys.path.insert", "sys.path.append")
                               and "upstream_path" in ast.unparse(n) for n in ast.walk(tree))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        try:
                            mod = importlib.import_module(a.name)
                        except Exception as e:  # noqa: BLE001
                            self.import_failed(f"cell {i} line {node.lineno}", f"import {a.name}", e, runtime_path)
                            continue
                        if a.asname:
                            self.env[a.asname] = mod
                        else:
                            self.env[a.name.split(".")[0]] = importlib.import_module(a.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    try:
                        mod = importlib.import_module(node.module)
                    except Exception as e:  # noqa: BLE001
                        self.import_failed(f"cell {i} line {node.lineno}", f"from {node.module} import …", e,
                                           runtime_path)
                        continue
                    for a in node.names:
                        if a.name == "*":
                            names = getattr(mod, "__all__", None) or [n for n in dir(mod) if not n.startswith("_")]
                            for n in names:
                                if hasattr(mod, n):
                                    self.env.setdefault(n, getattr(mod, n))
                                else:
                                    self.fail(f"cell {i} line {node.lineno}", f"{node.module}.__all__ lists {n!r}, "
                                              "which the module does not define")
                            continue
                        if hasattr(mod, a.name):
                            self.env[a.asname or a.name] = getattr(mod, a.name)
                        else:
                            try:
                                self.env[a.asname or a.name] = importlib.import_module(f"{node.module}.{a.name}")
                            except Exception:  # noqa: BLE001
                                self.fail(f"cell {i} line {node.lineno}", f"{node.module} has no {a.name!r}")

    # -- resolution
    def resolve(self, node):
        """The object an expression denotes (modules, functions, classes), else _UNKNOWN."""
        if isinstance(node, ast.Name):
            return self.env.get(node.id, _UNKNOWN)
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value)
            if base is _UNKNOWN:
                return _UNKNOWN
            if inspect.ismodule(base) or inspect.isclass(base):
                if hasattr(base, node.attr):
                    return getattr(base, node.attr)
                if inspect.ismodule(base):
                    try:
                        return importlib.import_module(f"{base.__name__}.{node.attr}")
                    except Exception:  # noqa: BLE001
                        pass
                raise AttributeError(f"{getattr(base, '__name__', base)} has no attribute {node.attr!r}")
        return _UNKNOWN

    def type_of(self, node):
        """The class of the value of an expression, when it can be told statically, else _UNKNOWN."""
        if isinstance(node, ast.Name):
            t = self.types.get(node.id, _UNKNOWN)
            if t is not _UNKNOWN:
                return t
            obj = self.env.get(node.id, _UNKNOWN)
            return _UNKNOWN if obj is _UNKNOWN or inspect.ismodule(obj) or callable(obj) else type(obj)
        if isinstance(node, ast.Call):
            try:
                func = self.callable_of(node.func)
            except AttributeError:
                return _UNKNOWN
            return _UNKNOWN if func is _UNKNOWN else _return_type(func[0])
        if isinstance(node, ast.Attribute):
            cls = self.type_of(node.value)
            if cls is _UNKNOWN or not inspect.isclass(cls):
                return _UNKNOWN
            attr = inspect.getattr_static(cls, node.attr, _UNKNOWN)
            if isinstance(attr, property) and attr.fget is not None:
                return _return_type(attr.fget)
        return _UNKNOWN

    def callable_of(self, func_node):
        """``(callable, bound)`` for the function a call node calls (``bound``: called on an instance, so the first
        parameter is filled), or _UNKNOWN. Raises AttributeError for a missing attribute on a known module / class."""
        if isinstance(func_node, ast.Name):
            if func_node.id in self.local_defs:
                return (self._stub(self.local_defs[func_node.id]), False)
            obj = self.env.get(func_node.id, _UNKNOWN)
            if obj is _UNKNOWN or func_node.id in self.types:
                return _UNKNOWN
            return (obj, False)
        if isinstance(func_node, ast.Attribute):
            try:
                base = self.resolve(func_node.value)
            except AttributeError:
                raise
            if base is not _UNKNOWN and (inspect.ismodule(base) or inspect.isclass(base)):
                if not hasattr(base, func_node.attr):
                    if inspect.ismodule(base):
                        raise AttributeError(f"module {base.__name__} has no attribute {func_node.attr!r}")
                    raise AttributeError(f"{base.__name__} has no attribute {func_node.attr!r}")
                return (getattr(base, func_node.attr), False)
            cls = self.type_of(func_node.value)
            if cls is _UNKNOWN or not inspect.isclass(cls):
                return _UNKNOWN
            if (cls.__module__ or "").split(".")[0] in DYNAMIC_MODULES:
                return _UNKNOWN  # KLayout classes: KQC adds methods at run time (e.g. Cell.length)
            static = inspect.getattr_static(cls, func_node.attr, _UNKNOWN)
            if static is _UNKNOWN:
                if func_node.attr in _instance_attrs(cls) or hasattr(cls, "__getattr__"):
                    return _UNKNOWN  # an instance attribute, or a class that answers any attribute (ports)
                raise AttributeError(f"{cls.__name__} has no attribute {func_node.attr!r}")
            if isinstance(static, (staticmethod, classmethod)):
                return (getattr(cls, func_node.attr), False)
            if isinstance(static, property) or not inspect.isroutine(static):
                return _UNKNOWN  # calling a property's value or a callable attribute
            return (getattr(cls, func_node.attr), True)
        return _UNKNOWN

    @staticmethod
    def _stub(fdef: ast.FunctionDef):
        """A do-nothing function with the notebook ``def``'s parameters (defaults replaced by None): its signature."""
        args = ast.arguments(
            posonlyargs=fdef.args.posonlyargs, args=fdef.args.args, vararg=fdef.args.vararg,
            kwonlyargs=fdef.args.kwonlyargs, kw_defaults=[None if d is None else ast.Constant(None)
                                                          for d in fdef.args.kw_defaults],
            kwarg=fdef.args.kwarg, defaults=[ast.Constant(None) for _ in fdef.args.defaults])
        for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
            if a is not None:
                a.annotation = None
        ns: dict = {}
        exec(f"def {fdef.name}({ast.unparse(args)}):\n    pass\n", ns)  # noqa: S102  (an empty stub, not notebook code)
        return ns[fdef.name]

    def check_call(self, where: str, node: ast.Call) -> None:
        label = ast.unparse(node.func)
        try:
            found = self.callable_of(node.func)
        except AttributeError as e:
            self.fail(where, f"{label}(…): {e}")
            return
        if found is _UNKNOWN:
            self.unchecked.append(f"{where}: {label}(…)")
            return
        func, bound = found
        try:
            sig = inspect.signature(func)
        except (TypeError, ValueError):
            self.unchecked.append(f"{where}: {label}(…) (no signature)")
            return
        star = any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords)
        npos = sum(1 for a in node.args if not isinstance(a, ast.Starred)) + (1 if bound else 0)
        kws = {k.arg: None for k in node.keywords if k.arg is not None}
        try:
            (sig.bind_partial if star else sig.bind)(*([None] * npos), **kws)
        except TypeError as e:
            self.fail(where, f"{label}(…) does not fit {getattr(func, '__qualname__', label)}{sig}: {e}")
            return
        self.checked += 1

    # -- the notebook
    def run(self, clean: bool = False) -> bool:
        import nbformat  # pylint: disable=import-outside-toplevel

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        try:
            nbformat.validate(nbformat.from_dict(raw))
        except Exception as e:  # noqa: BLE001
            self.fail("nbformat", f"{type(e).__name__}: {str(e)[:300]}")
        cells = raw.get("cells", [])
        trees = []
        for i, cell in enumerate(cells):
            if cell.get("cell_type") != "code":
                continue
            if clean and (cell.get("outputs") or cell.get("execution_count") is not None):
                self.fail(f"cell {i}", "has outputs / an execution count (--clean: clear them)")
            try:
                trees.append((i, ast.parse(_python(_cell_source(cell)))))
            except SyntaxError as e:
                self.fail(f"cell {i} line {e.lineno}", f"syntax error: {e.msg}")
        _setup_path(self.path)
        self.do_imports(trees)
        for _, tree in trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self.local_defs[node.name] = node
        # static types of simple assignments ``name = call(...)``: a name bound any other way too (two different
        # types, a for target, an argument, tuple unpacking …) stays unknown, so its calls are not checked
        simple, other = [], set()
        for _, tree in trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    simple.append((node.targets[0].id, node.value))
                    continue
                if isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        other.update(n.id for n in ast.walk(tgt) if isinstance(n, ast.Name))
                elif isinstance(node, (ast.For, ast.comprehension, ast.With, ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target] if hasattr(node, "target") else [i.optional_vars for i in node.items]
                    for tgt in targets:
                        if tgt is not None:
                            other.update(n.id for n in ast.walk(tgt) if isinstance(n, ast.Name))
                elif isinstance(node, ast.arg):
                    other.add(node.arg)
                elif isinstance(node, ast.NamedExpr):
                    other.add(node.target.id)
        simple_names = {n for n, _ in simple}
        for _ in range(3):  # a few passes: types flow through chains (d → q = d.add(...) → q.set(...))
            seen: dict[str, list] = {}
            for name, value in simple:
                seen.setdefault(name, []).append(self.type_of(value) if isinstance(value, ast.Call) else _UNKNOWN)
            self.types = {}
            for name, ts in seen.items():
                kinds = {id(x): x for x in ts}
                one = next(iter(kinds.values())) if len(kinds) == 1 else _UNKNOWN
                self.types[name] = _UNKNOWN if name in other or name in self.local_defs else one
        for name in other - simple_names:
            self.types.setdefault(name, _UNKNOWN)
        bound = _bound_names([t for _, t in trees]) | set(self.env) | set(dir(builtins)) | IPYTHON_NAMES
        for i, tree in trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound:
                    self.fail(f"cell {i} line {node.lineno}", f"name {node.id!r} is never defined in the notebook")
                if isinstance(node, ast.Call):
                    self.check_call(f"cell {i} line {node.lineno}", node)
        return not self.problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("notebooks", nargs="+", type=Path)
    ap.add_argument("--clean", action="store_true", help="also require cleared outputs")
    ap.add_argument("--verbose", action="store_true", help="list the calls that could not be checked")
    args = ap.parse_args(argv)
    cwd, path0 = os.getcwd(), list(sys.path)
    bad = 0
    for nb in args.notebooks:
        nb = nb.resolve()
        sys.path[:] = path0
        c = Checker(nb)
        try:
            ok = c.run(clean=args.clean)
        finally:
            os.chdir(cwd)
        rel = nb.relative_to(ROOT).as_posix() if ROOT in nb.parents else str(nb)
        print(f"{'OK  ' if ok else 'FAIL'} {rel}: {c.checked} calls checked, {len(c.unchecked)} unchecked, "
              f"{len(c.problems)} problem(s)")
        for p in c.problems:
            print(f"    {p}")
        for n in c.notes:
            print(f"    note: {n}")
        if args.verbose:
            for u in c.unchecked:
                print(f"    unchecked {u}")
        bad += not ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
