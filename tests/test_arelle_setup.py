import io
import os
import tempfile
import types
import unittest
import tarfile
import zipfile
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

            # Minimal valid taxonomy package zip (just enough for detection).
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("pkg/META-INF/taxonomyPackage.xml", "<tp:taxonomyPackage xmlns:tp='http://xbrl.org/2016/taxonomy-package'/>")
            zip_bytes = buf.getvalue()

            out = io.StringIO()
            with patch.dict("sys.modules", {"arelle": fake_arelle}):
                with patch("cmdrvl_xew.arelle_setup.urllib.request.urlopen", return_value=FakeResponse(zip_bytes)):
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
            self.assertIn("Downloaded 1 URL file", out.getvalue())

    def test_mirrors_directory_urls_then_installs(self):
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
                    return {"name": "sec-dei-2025", "version": "none", "identifier": "fake"}

                @staticmethod
                def rebuildRemappings(cntlr):  # noqa: ARG001
                    calls["rebuild"].append(True)

                @staticmethod
                def save(cntlr):  # noqa: ARG001
                    calls["save"].append(True)

            fake_arelle = types.ModuleType("arelle")
            fake_arelle.Cntlr = FakeCntlrModule
            fake_arelle.PackageManager = FakePackageManager

            base_url = "https://example.com/dei/2025/"
            args = SimpleNamespace(
                package=[],
                url=[base_url],
                download_dir=str(download_dir),
                user_agent="Example example@example.com",
                min_interval=0.0,
                force=False,
                arelle_xdg_config_home=str(xdg_home),
            )

            index_html = (
                "<html><body>"
                "<a href=\"dei-2025.xsd\">dei-2025.xsd</a>"
                "<a href=\"dei-2025_def.xsd\">dei-2025_def.xsd</a>"
                "</body></html>"
            ).encode("utf-8")

            class FakeResponse(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

            def fake_urlopen(req):
                url = getattr(req, "full_url", req)
                if url == base_url:
                    return FakeResponse(index_html)
                if url.endswith(".xsd"):
                    return FakeResponse(b"xsd-bytes")
                raise AssertionError(f"Unexpected urlopen URL: {url}")

            out = io.StringIO()
            with patch.dict("sys.modules", {"arelle": fake_arelle}):
                with patch("cmdrvl_xew.arelle_setup.urllib.request.urlopen", side_effect=fake_urlopen):
                    with patch.dict(os.environ, {"XDG_CONFIG_HOME": "prev"}):
                        with redirect_stdout(out):
                            rc = run_arelle_install_packages(args)
                        self.assertEqual(os.environ.get("XDG_CONFIG_HOME"), "prev")

            self.assertEqual(rc, ExitCode.SUCCESS)
            mirror_dir = download_dir / "_mirror" / "example.com" / "dei" / "2025"
            self.assertTrue((mirror_dir / "dei-2025.xsd").exists())
            self.assertTrue((mirror_dir / "dei-2025_def.xsd").exists())
            self.assertTrue((mirror_dir / "META-INF" / "catalog.xml").exists())
            self.assertTrue((mirror_dir / "META-INF" / "taxonomyPackage.xml").exists())

            self.assertEqual(len(calls["add"]), 1)
            _cntlr, add_path = calls["add"][0]
            self.assertEqual(Path(add_path).resolve(), (mirror_dir / "META-INF" / "taxonomyPackage.xml").resolve())
            self.assertIn("Mirrored 1 taxonomy directory URL", out.getvalue())

    def test_installs_from_bundle_tarball(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            xdg_home = tmp / "xdg"

            # Build a tiny bundle tarball with one taxonomy .zip and one mirrored directory package.
            bundle_root = tmp / "bundle" / "xew-arelle"
            pkg_dir = bundle_root / "arelle" / "taxonomy-packages"
            pkg_dir.mkdir(parents=True, exist_ok=True)

            zip_path = pkg_dir / "us-gaap-2025.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(
                    "pkg/META-INF/taxonomyPackage.xml",
                    "<tp:taxonomyPackage xmlns:tp='http://xbrl.org/2016/taxonomy-package'/>",
                )

            mirror_dir = pkg_dir / "_mirror" / "example.com" / "dei" / "2025" / "META-INF"
            mirror_dir.mkdir(parents=True, exist_ok=True)
            (mirror_dir / "taxonomyPackage.xml").write_text(
                "<tp:taxonomyPackage xmlns:tp='http://xbrl.org/2016/taxonomy-package'/>",
                encoding="utf-8",
            )

            bundle_tar = tmp / "bundle.tgz"
            with tarfile.open(bundle_tar, "w:gz") as tf:
                tf.add(bundle_root, arcname="xew-arelle")

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
                    return {"name": Path(url).name, "version": "x", "identifier": "fake"}

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
                package=[],
                url=[],
                bundle_uri=str(bundle_tar),
                bundle_sha256=None,
                aws_profile=None,
                no_bundle=False,
                arelle_xdg_config_home=str(xdg_home),
                force=False,
            )

            out = io.StringIO()
            with patch.dict("sys.modules", {"arelle": fake_arelle}):
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": "prev"}):
                    with redirect_stdout(out):
                        rc = run_arelle_install_packages(args)
                    self.assertEqual(os.environ.get("XDG_CONFIG_HOME"), "prev")

            self.assertEqual(rc, ExitCode.SUCCESS)
            extracted_zip = xdg_home / "arelle" / "taxonomy-packages" / "us-gaap-2025.zip"
            extracted_pkg_xml = (
                xdg_home
                / "arelle"
                / "taxonomy-packages"
                / "_mirror"
                / "example.com"
                / "dei"
                / "2025"
                / "META-INF"
                / "taxonomyPackage.xml"
            )
            self.assertTrue(extracted_zip.exists())
            self.assertTrue(extracted_pkg_xml.exists())
            self.assertEqual(len(calls["add"]), 2)
            self.assertIn("Bundle source:", out.getvalue())


if __name__ == "__main__":
    unittest.main()
