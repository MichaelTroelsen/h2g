"""The goatwriter package keeps the single-file module's surface, and no test
can patch the facade by accident.

goatwriter.py was split into python/h2g/goatwriter/ (moves only). Its
__init__ re-exports every name, so imports are unchanged; but a function
patched on the PACKAGE no longer reaches any caller, because each caller looks
the name up in its own module. Such a patch would leave its test passing on
code it no longer controls. These tests make that impossible to write, and
pin that the facade hands out the defining module's own objects.
"""
import ast
import importlib
import inspect
import pathlib
import pkgutil

import h2g.goatwriter as G

TESTS = pathlib.Path(__file__).resolve().parent


def _submodules():
    return [importlib.import_module(f"h2g.goatwriter.{m.name}")
            for m in pkgutil.iter_modules(G.__path__)]


def _facade_aliases(tree):
    """Names a test file binds to the h2g.goatwriter package itself."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "h2g.goatwriter" and a.asname:
                    out.add(a.asname)
        if isinstance(n, ast.ImportFrom) and n.module == "h2g":
            for a in n.names:
                if a.name == "goatwriter":
                    out.add(a.asname or a.name)
    return out


def test_no_test_patches_a_function_on_the_facade():
    offenders = []
    # the tests, and the harness tools beside them (fid_loop2.py patched the
    # facade until v0.5.504 and nothing caught it)
    for path in sorted(TESTS.glob("test_*.py")) + sorted(TESTS.parent.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _facade_aliases(tree)
        if not aliases:
            continue
        for n in ast.walk(tree):
            # monkeypatch.setattr(G, "name", ...) / setattr(G, "name", ...)
            if (isinstance(n, ast.Call) and len(n.args) >= 2
                    and ast.unparse(n.func).endswith("setattr")
                    and isinstance(n.args[0], ast.Name)
                    and n.args[0].id in aliases):
                if not isinstance(n.args[1], ast.Constant):
                    # a computed name cannot be shown to be a submodule
                    offenders.append(f"{path.name}:{n.lineno} patches a "
                                     f"computed name on the package")
                elif not inspect.ismodule(getattr(G, n.args[1].value, None)):
                    offenders.append(f"{path.name}:{n.lineno} patches "
                                     f"{n.args[1].value} on the package")
            # G.name = ..., G.name += ..., del G.name -- the same dead patch
            targets = (n.targets if isinstance(n, (ast.Assign, ast.Delete))
                       else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign))
                       else [])
            for t in targets:
                for x in ast.walk(t):
                    if (isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
                            and x.value.id in aliases
                            and not inspect.ismodule(getattr(G, x.attr, None))):
                        offenders.append(f"{path.name}:{x.lineno} rebinds "
                                         f"{x.attr} on the package")
    assert not offenders, (
        "patch the DEFINING module (goatwriter.<module>.<name>); a patch on "
        "the package reaches no caller: " + "; ".join(offenders))


def test_every_submodule_name_is_reexported_as_the_same_object():
    missing, different = [], []
    for mod in _submodules():
        tree = ast.parse(inspect.getsource(mod))
        for node in tree.body:
            names = []
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [x.id for t in node.targets for x in ast.walk(t)
                         if isinstance(x, ast.Name)]
            for name in names:
                if not hasattr(G, name):
                    missing.append(f"{mod.__name__}.{name}")
                elif getattr(G, name) is not getattr(mod, name):
                    different.append(f"{mod.__name__}.{name}")
    assert not missing, f"not re-exported by the package: {missing}"
    assert not different, f"re-exported as a different object: {different}"


def test_cross_module_calls_go_through_the_defining_module():
    """The names tests patch are called, from any other module, as
    `_gw_<module>.<name>`: each such alias must BE that submodule, so a
    patch on the defining module is what every caller sees."""
    aliases = 0
    for mod in _submodules():
        for attr, val in vars(mod).items():
            if attr.startswith("_gw_"):
                aliases += 1
                want = importlib.import_module(f"h2g.goatwriter.{attr[4:]}")
                assert val is want, f"{mod.__name__}.{attr} is not {want.__name__}"
    assert aliases, "no module calls through a _gw_ alias; the check is vacuous"
