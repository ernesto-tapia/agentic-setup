"""Tool registry, the @tool decorator, and built-in tools.

Write a tool as a normal Python function with type hints and a docstring:

    from agentlab import tool

    @tool
    def add(a: int, b: int) -> str:
        '''Add two numbers.

        Args:
            a: first number
            b: second number
        '''
        return str(a + b)

The JSON schema the model sees is generated from the signature.
"""

import importlib.util
import inspect
import subprocess
import sys
import types
import typing
from pathlib import Path

REGISTRY = {}

# Set by the agent before each run so built-in tools know where to work.
CONTEXT = {"workdir": Path.cwd()}

_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


class Tool:
    def __init__(self, fn, name=None, description=None):
        self.fn = fn
        self.name = name or fn.__name__
        doc = inspect.getdoc(fn) or ""
        self.description = description or doc.split("\n\n")[0].strip() or self.name
        self.parameters = _schema(fn, _arg_docs(doc))

    def __call__(self, **kwargs):
        return self.fn(**kwargs)


def tool(fn=None, *, name=None, description=None):
    """Decorator that registers a function as a tool the model can call."""
    def wrap(f):
        t = Tool(f, name, description)
        REGISTRY[t.name] = t
        return f
    return wrap(fn) if fn else wrap


def _arg_docs(doc):
    """Parse a Google-style 'Args:' section into {name: description}."""
    out, in_args = {}, False
    for line in doc.splitlines():
        s = line.strip()
        if s.lower() in ("args:", "arguments:", "parameters:"):
            in_args = True
        elif in_args and ":" in s:
            k, v = s.split(":", 1)
            out[k.strip().split(" ")[0]] = v.strip()
        elif in_args and not s:
            in_args = False
    return out


def _json_type(hint):
    origin = typing.get_origin(hint)
    if origin is not None and origin in (typing.Union, getattr(types, "UnionType", typing.Union)):  # Optional[X], X | None
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        return _json_type(args[0]) if args else {"type": "string"}
    if origin in (list, typing.List):
        args = typing.get_args(hint)
        return {"type": "array", "items": _json_type(args[0]) if args else {}}
    return {"type": _TYPES.get(origin or hint, "string")}


def _schema(fn, docs):
    hints = typing.get_type_hints(fn)
    props, required = {}, []
    for pname, p in inspect.signature(fn).parameters.items():
        prop = _json_type(hints.get(pname, str))
        if pname in docs:
            prop["description"] = docs[pname]
        props[pname] = prop
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": props, "required": required}


def load_tools_dir(path):
    """Import every .py file in a project's tools/ folder (registers their @tool functions)."""
    path = Path(path)
    if not path.is_dir():
        return
    for file in sorted(path.glob("*.py")):
        name = f"agentlab_user_tools.{file.stem}"
        if file.name.startswith("_") or name in sys.modules:  # already loaded (e.g. by another agent)
            continue
        spec = importlib.util.spec_from_file_location(name, file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)


def _resolve(path):
    """Resolve a path inside the workdir, refusing to escape it."""
    root = Path(CONTEXT["workdir"]).resolve()
    p = (root / path).resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"Path '{path}' is outside the workdir {root}")
    return p


# ---------------------------------------------------------------- built-ins

@tool
def read_file(path: str) -> str:
    """Read a text file from the workdir.

    Args:
        path: file path relative to the workdir
    """
    return _resolve(path).read_text(errors="replace")


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file in the workdir.

    Args:
        path: file path relative to the workdir
        content: full new contents of the file
    """
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content)} chars to {path}"


@tool
def list_dir(path: str = ".") -> str:
    """List files and folders in a directory of the workdir.

    Args:
        path: directory relative to the workdir
    """
    p = _resolve(path)
    entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
    return "\n".join(e.name + ("/" if e.is_dir() else "") for e in entries) or "(empty)"


@tool
def run_shell(command: str, timeout: int = 60) -> str:
    """Run a shell command in the workdir and return its output.

    Args:
        command: the shell command to run
        timeout: seconds before the command is killed
    """
    r = subprocess.run(command, shell=True, cwd=CONTEXT["workdir"], capture_output=True, text=True, timeout=timeout)
    return f"exit code {r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
