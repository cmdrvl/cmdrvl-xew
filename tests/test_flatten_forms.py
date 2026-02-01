import argparse
import tempfile
from pathlib import Path
import unittest

from cmdrvl_xew.flatten import run_flatten


def _write_fixture(root: Path, form_dir: str, basename: str) -> tuple[Path, Path]:
    edgar_dir = root / "edgar"
    edgar_dir.mkdir(parents=True, exist_ok=True)

    form_path = edgar_dir / form_dir
    form_path.mkdir(parents=True, exist_ok=True)

    primary_path = form_path / f"{basename}.htm"
    primary_path.write_text(
        f'<link:schemaRef xlink:href="{basename}.xsd"/>',
        encoding="utf-8",
    )

    (form_path / "ex31-1.htm").write_text("exhibit", encoding="utf-8")

    (edgar_dir / "EX-101.SCH").mkdir(parents=True, exist_ok=True)
    (edgar_dir / "EX-101.CAL").mkdir(parents=True, exist_ok=True)
    (edgar_dir / "EX-101.DEF").mkdir(parents=True, exist_ok=True)
    (edgar_dir / "EX-101.LAB").mkdir(parents=True, exist_ok=True)
    (edgar_dir / "EX-101.PRE").mkdir(parents=True, exist_ok=True)

    (edgar_dir / "EX-101.SCH" / f"{basename}.xsd").write_text("schema", encoding="utf-8")
    (edgar_dir / "EX-101.CAL" / f"{basename}_cal.xml").write_text("cal", encoding="utf-8")
    (edgar_dir / "EX-101.DEF" / f"{basename}_def.xml").write_text("def", encoding="utf-8")
    (edgar_dir / "EX-101.LAB" / f"{basename}_lab.xml").write_text("lab", encoding="utf-8")
    (edgar_dir / "EX-101.PRE" / f"{basename}_pre.xml").write_text("pre", encoding="utf-8")

    out_dir = root / "out"
    return edgar_dir, out_dir


class TestFlattenAdditionalForms(unittest.TestCase):
    def _run_flatten(self, form_dir: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edgar_dir, out_dir = _write_fixture(root, form_dir, "sample-20240101")

            args = argparse.Namespace(edgar_dir=str(edgar_dir), out=str(out_dir), force=False)
            rc = run_flatten(args)
            self.assertEqual(rc, 0)

            expected = {
                "sample-20240101.htm",
                "sample-20240101.xsd",
                "sample-20240101_cal.xml",
                "sample-20240101_def.xml",
                "sample-20240101_lab.xml",
                "sample-20240101_pre.xml",
            }
            self.assertTrue(out_dir.is_dir())
            self.assertTrue(expected.issubset({p.name for p in out_dir.iterdir()}))

    def test_flatten_supports_20f(self) -> None:
        self._run_flatten("20-F")

    def test_flatten_supports_6k(self) -> None:
        self._run_flatten("6-K")

    def test_flatten_supports_8k(self) -> None:
        self._run_flatten("8-K")


if __name__ == "__main__":
    unittest.main()
