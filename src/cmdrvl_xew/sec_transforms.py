"""Registers the vendored SEC `ixt-sec` inline transforms with Arelle.

arelle-release does not ship them. The two files in ``xew_edgar_ixt_sec/`` are Arelle/EDGAR's,
unchanged (see its NOTICE.md). Arelle is never allowed to run without them: if they cannot be
verified and registered, loading is refused.

Arelle keeps one plugin registry per process, and keeps what is already in it when a new controller
is created. ``reset_plugin_registry`` therefore runs before the controller exists, so that nothing
registered earlier can take part in a load, and again after the load.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

EDGAR_COMMIT = "99e94b6c6f5ca2ef06a9c2f29b0a4290a7f959db"
TRANSFORM_DIR = Path(__file__).resolve().parent / "xew_edgar_ixt_sec"
PINNED_SHA256 = {
    "__init__.py": "2296586f945ffd95ab37d3d4147c4e45f42ce4e5f397f61143e053208adefbf1",
    "text2num.py": "6c9b26354320a2fb34fe380cdc71ff7f8d1cc712811e6b10c661e512f0383409",
}
SEC_IXT_NAMESPACE = "http://www.sec.gov/inlineXBRL/transformation/2015-08-31"
EXPECTED_TRANSFORMS = frozenset(
    {
        "boolballotbox", "countrynameen", "datequarterend", "durday", "durhour", "durmonth",
        "durweek", "durwordsen", "duryear", "edgarprovcountryen", "entityfilercategoryen",
        "exchnameen", "numinf", "numnan", "numneginf", "numwordsen", "stateprovnameen",
        "yesnoballotbox",
    }
)
# Recorded instead of the identity when a pack did not read the filing with Arelle.
NOT_LOADED = "not_loaded"


class SecTransformError(Exception):
    """The vendored transforms could not be verified or registered."""


def _digest(hashes: dict[str, str]) -> str:
    # The same bytes `shasum -a 256 __init__.py text2num.py` prints.
    listing = "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes))
    return hashlib.sha256(listing.encode("ascii")).hexdigest()


def identity() -> str:
    """What packs record. Only meaningful after ``register`` has verified the files."""
    return f"Arelle/EDGAR transform {EDGAR_COMMIT[:12]} sha256:{_digest(PINNED_SHA256)}"


def _verify_files(directory: Path) -> None:
    for name, expected in PINNED_SHA256.items():
        path = directory / name
        if not path.is_file():
            raise SecTransformError(f"vendored transform file is missing: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SecTransformError(f"vendored transform file differs from the pinned upstream bytes: {path}")


def reset_plugin_registry() -> None:
    """Empty Arelle's process-wide plugin registry."""
    from arelle import PluginManager  # type: ignore

    PluginManager.close()


def register(controller: Any) -> None:
    """Register exactly the vendored transforms on ``controller``, or raise SecTransformError.

    The module info is built from the vendored path. ``PluginManager.addPluginModule`` is not used:
    it first runs entry-point discovery, which imports every installed Arelle plugin.
    """
    from arelle import PluginManager  # type: ignore

    directory = Path(TRANSFORM_DIR)
    _verify_files(directory)
    # Arelle imports a plugin directory as a top-level module of the same name. Drop earlier
    # imports so that the relative import of text2num cannot resolve to another copy.
    package = directory.name
    for name in [n for n in sys.modules if n == package or n.startswith(package + ".")]:
        del sys.modules[name]

    PluginManager.init(controller, loadPluginConfig=False)
    info = PluginManager.getInstance().moduleModuleInfo(moduleURL=str(directory))
    if PluginManager.addPluginModuleInfo(info) is None:
        raise SecTransformError(f"Arelle did not accept the transform module in {directory}")
    controller.modelManager.customTransforms = None
    controller.modelManager.loadCustomTransforms()  # only Arelle's own CLI and GUI call this

    registered = controller.modelManager.customTransforms or {}
    expected = {(SEC_IXT_NAMESPACE, name) for name in EXPECTED_TRANSFORMS}
    if {(q.namespaceURI, q.localName) for q in registered} != expected:
        raise SecTransformError(f"expected the {len(expected)} SEC transforms, Arelle registered {len(registered)}")
    vendored = {(directory / name).resolve() for name in PINNED_SHA256}
    for qname, function in registered.items():
        if Path(function.__code__.co_filename).resolve() not in vendored:
            raise SecTransformError(f"transform {qname.localName} does not come from the vendored files")
    helper = sys.modules.get(f"{package}.text2num")
    if helper is None or Path(helper.__file__).resolve() not in vendored:
        raise SecTransformError("text2num was not imported from the vendored files")
