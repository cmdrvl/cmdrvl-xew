import io
import os
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cmdrvl_xew.arelle_setup import run_arelle_install_packages
from cmdrvl_xew.exit_codes import ExitCode


class TestArelleSetup(unittest.TestCase):
    def test_requires_package(self):
        args = SimpleNamespace(package=[], url=[], arelle_xdg_config_home=None)
        with self.assertRaises(SystemExit) as ctx:
            run_arelle_install_packages(args)
        self.assertEqual(ctx.exception.code, ExitCode.INVOCATION_ERROR)

    def test_missing_package_path(self):
        args = SimpleNamespace(package=["/does/not/exist.zip"], arelle_xdg_config_home=None)
        with self.assertRaises(SystemExit) as ctx:
            run_arelle_install_packages(args)
        self.assertEqual(ctx.exception.code, ExitCode.INVOCATION_ERROR)

    def test_installs_packages_into_config_home(self):
        with tempfile.TemporaryDirectory() as td:
            xdg_home = Path(td) / "xdg"
            pkg = Path(td) / "us-gaap.zip"
            pkg.write_bytes(b"not-a-real-package")

            calls: dict[str, list] = {"add": [], "rebuild": [], "save": []}

            class FakeWebCache:
                def __init__(self):
                    self.httpUserAgent = None

            class FakeCntlrInstance:
                def __init__(self, *_args, **_kwargs):
                    self.webCache = FakeWebCache()
                    # Mirror Arelle behavior: userAppDir is XDG_CONFIG_HOME/arelle.
                    self.userAppDir = str(Path(os.environ["XDG_CONFIG_HOME"]) / "arelle")

            class FakeCntlrModule:
                Cntlr = FakeCntlrInstance

            class FakePackageManager:
                @staticmethod
                def init(cntlr, loadPackagesConfig=True):  # noqa: ARG001
                    calls.setdefault("init", []).append(loadPackagesConfig)

                @staticmethod
                def addPackage(cntlr, url, packageManifestName=None):  # noqa: ARG001
                    calls["add"].append((cntlr, url))
                    return {"name": "us-gaap", "version": "2025", "identifier": "fake"}

                @staticmethod
                def rebuildRemappings(cntlr):  # noqa: ARG001
                    calls["rebuild"].append(True)

                @staticmethod
                def save(cntlr):  # noqa: ARG001
                    calls["save"].append(True)

            fake_arelle = types.ModuleType("arelle")
            fake_arelle.Cntlr = FakeCntlrModule
            fake_arelle.PackageManager = FakePackageManager

            args = SimpleNamespace(
                package=[str(pkg)],
                arelle_xdg_config_home=str(xdg_home),
            )

            out = io.StringIO()
            with patch.dict("sys.modules", {"arelle": fake_arelle}):
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": "prev"}):
                    with redirect_stdout(out):
                        rc = run_arelle_install_packages(args)
                    self.assertEqual(os.environ.get("XDG_CONFIG_HOME"), "prev")

            self.assertEqual(rc, ExitCode.SUCCESS)
            self.assertTrue(xdg_home.exists())
            self.assertEqual(len(calls["add"]), 1)
            _cntlr, url = calls["add"][0]
            self.assertEqual(Path(url).name, "us-gaap.zip")
            self.assertEqual(calls.get("init"), [True])
            self.assertEqual(len(calls["rebuild"]), 1)
            self.assertEqual(len(calls["save"]), 1)
            self.assertIn("taxonomyPackages.json", out.getvalue())

    def test_downloads_urls_then_installs(self):
        with tempfile.TemporaryDirectory() as td:
            xdg_home = Path(td) / "xdg"
            download_dir = Path(td) / "downloads"

            calls: dict[str, list] = {"add": [], "rebuild": [], "save": []}

            class FakeWebCache:
                def __init__(self):
                    self.httpUserAgent = None

            class FakeCntlrInstance:
                def __init__(self, *_args, **_kwargs):
                    self.webCache = FakeWebCache()
                    self.userAppDir = str(Path(os.environ["XDG_CONFIG_HOME"]) / "arelle")

            class FakeCntlrModule:
                Cntlr = FakeCntlrInstance

            class FakePackageManager:
                @staticmethod
                def init(cntlr, loadPackagesConfig=True):  # noqa: ARG001
                    calls.setdefault("init", []).append(loadPackagesConfig)

                @staticmethod
                def addPackage(cntlr, url, packageManifestName=None):  # noqa: ARG001
                    calls["add"].append((cntlr, url))
                    return {"name": "us-gaap", "version": "2025", "identifier": "fake"}

                @staticmethod
                def rebuildRemappings(cntlr):  # noqa: ARG001
                    calls["rebuild"].append(True)

                @staticmethod
                def save(cntlr):  # noqa: ARG001
                    calls["save"].append(True)

            fake_arelle = types.ModuleType("arelle")
            fake_arelle.Cntlr = FakeCntlrModule
            fake_arelle.PackageManager = FakePackageManager

            url = "https://example.com/us-gaap-2025.zip"
            args = SimpleNamespace(
                package=[],
                url=[url],
                download_dir=str(download_dir),
                user_agent="Example example@example.com",
                min_interval=0.0,
                force=False,
                arelle_xdg_config_home=str(xdg_home),
            )

            class FakeResponse(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

            out = io.StringIO()
            with patch.dict("sys.modules", {"arelle": fake_arelle}):
                with patch("cmdrvl_xew.arelle_setup.urllib.request.urlopen", return_value=FakeResponse(b"zip-bytes")):
                    with patch.dict(os.environ, {"XDG_CONFIG_HOME": "prev"}):
                        with redirect_stdout(out):
                            rc = run_arelle_install_packages(args)
                        self.assertEqual(os.environ.get("XDG_CONFIG_HOME"), "prev")

            self.assertEqual(rc, ExitCode.SUCCESS)
            downloaded = download_dir / "us-gaap-2025.zip"
            self.assertTrue(downloaded.exists())
            self.assertEqual(len(calls["add"]), 1)
            _cntlr, add_path = calls["add"][0]
            self.assertEqual(Path(add_path).resolve(), downloaded.resolve())
            self.assertIn("Downloaded 1 package", out.getvalue())


if __name__ == "__main__":
    unittest.main()
