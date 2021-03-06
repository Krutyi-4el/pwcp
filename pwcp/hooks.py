# Thanks to
# https://stackoverflow.com/a/43573798/
# https://stackoverflow.com/a/45168493/
# https://stackoverflow.com/a/48671982/

import sys
from os import getcwd
import linecache
from linecache import getlines
from importlib import invalidate_caches
from importlib.abc import SourceLoader
from importlib.util import spec_from_loader
from importlib.machinery import FileFinder, PathFinder
from traceback import print_exception
from types import ModuleType, TracebackType
from typing import Optional, Type
from .preprocessor import preprocess
from .config import FILE_EXTENSION


_path_importer_cache = {}
_path_hooks = []

preprocessed_files = {}


def patched_getlines(filename, module_globals=None):
    if filename in preprocessed_files:
        return preprocessed_files[filename].splitlines()
    return getlines(filename, module_globals)


def find_spec_fallback(fullname, path, target):
    spec = None
    for finder in sys.meta_path:
        if finder == PPyPathFinder:
            continue
        try:
            spec = finder.find_spec(fullname, path, target)
        except AttributeError:
            loader = finder.find_module(fullname, path)
            if loader:
                spec = spec_from_loader(fullname, loader)
        if spec and spec.loader:
            return spec
    return None


class Configurable:
    _config = {}

    @classmethod
    def set_config(cls, config: dict):
        cls._config = config


class PPyPathFinder(PathFinder, Configurable):
    """
    An overridden PathFinder which will hunt for ppy files in
    sys.path. Uses storage in this module to avoid conflicts with the
    original PathFinder
    """

    @classmethod
    def invalidate_caches(cls):
        for finder in _path_importer_cache.values():
            if hasattr(finder, "invalidate_caches"):
                finder.invalidate_caches()

    @classmethod
    def _path_hooks(cls, path):
        for hook in _path_hooks:
            try:
                return hook(path)
            except ImportError:
                continue
        else:
            return None

    @classmethod
    def _path_importer_cache(cls, path):
        if path == "":
            try:
                path = getcwd()
            except FileNotFoundError:
                # Don't cache the failure as the cwd can easily change to
                # a valid directory later on.
                return None
        try:
            finder = _path_importer_cache[path]
        except KeyError:
            finder = cls._path_hooks(path)
            _path_importer_cache[path] = finder
        return finder

    @classmethod
    def find_spec(cls, fullname, path, target=None):
        if cls._config.get("prefer_python"):
            spec = find_spec_fallback(fullname, path, target)
            if spec:
                return spec

        spec = super().find_spec(fullname, path, target)
        if spec is not None and spec.loader is not None:
            return spec
        return None


class PPyLoader(SourceLoader, Configurable):
    def __init__(self, fullname, path):
        self.fullname = fullname
        self.path = path

    def get_filename(self, fullname):
        return self.path

    def get_data(self, filename):
        """exec_module is already defined for us, we just have to provide a way
        of getting the source code of the module"""
        # save preprocessed file to display actual SyntaxError
        data = preprocessed_files[self.path] = preprocess(self.path, self._config)
        return data.encode()


def create_exception_handler(module: Optional[ModuleType]):
    def handle_exc(
        e_type: Type[BaseException], e: BaseException, tb: Optional[TracebackType]
    ):
        if isinstance(e, SyntaxError) and preprocessed_files.get(e.filename):
            # replace raw text from file with actual code
            data = preprocessed_files[e.filename]
            e.text = data.splitlines()[e.lineno - 1]
        # remove outer frames from traceback
        while tb and module and tb.tb_frame.f_code.co_filename != module.__file__:
            tb = tb.tb_next
        print_exception(e_type, e, tb)

    return handle_exc


LOADER_DETAILS = PPyLoader, [FILE_EXTENSION]


def _install():
    done = False

    def install(config: dict = {}):
        nonlocal done

        # (re)setting global configuration
        PPyLoader.set_config(config)
        PPyPathFinder.set_config(config)

        if done:
            return

        # insert the path finder
        sys.meta_path.insert(0, PPyPathFinder)
        _path_hooks.append(FileFinder.path_hook(LOADER_DETAILS))
        # clear any loaders that might already be in use by the FileFinder
        sys.path_importer_cache.clear()
        invalidate_caches()
        # patch getlines
        linecache.getlines = patched_getlines
        done = True

    return install


install = _install()
