"""
Unit tests for verify-pack CLI command and verification functionality.
"""

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmdrvl_xew.cli import validate_verify_args
from cmdrvl_xew.verify import run_verify_pack, _validate_findings_schema, SchemaValidationResult


class TestVerifyPackCLI(unittest.TestCase):
    """Test cases for verify-pack CLI argument validation."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_valid_pack_directory(self):
        """Test validation with valid Evidence Pack directory."""
        # Create valid pack structure
        pack_dir = self.temp_path / "test_pack"
        pack_dir.mkdir()
        manifest_path = pack_dir / "pack_manifest.json"
        manifest_path.write_text('{"pack_sha256": "abc123", "files": []}')

        args = argparse.Namespace(pack=str(pack_dir), quiet=False, verbose=False)
        errors = validate_verify_args(args)

        self.assertEqual(len(errors), 0)
        # Should normalize to absolute path
        self.assertEqual(args.pack, str(pack_dir.resolve()))

    def test_nonexistent_pack_directory(self):
        """Test validation with nonexistent Evidence Pack directory."""
        args = argparse.Namespace(pack="/nonexistent/path", quiet=False, verbose=False)
        errors = validate_verify_args(args)

        self.assertEqual(len(errors), 1)
        self.assertIn("Evidence Pack directory does not exist", errors[0])

    def test_pack_is_file_not_directory(self):
        """Test validation when pack path is a file, not directory."""
        test_file = self.temp_path / "test_file.txt"
        test_file.write_text("not a directory")

        args = argparse.Namespace(pack=str(test_file), quiet=False, verbose=False)
        errors = validate_verify_args(args)

        self.assertEqual(len(errors), 1)
        self.assertIn("Evidence Pack path is not a directory", errors[0])

    def test_missing_pack_manifest(self):
        """Test validation when pack_manifest.json is missing."""
        pack_dir = self.temp_path / "pack_without_manifest"
        pack_dir.mkdir()

        args = argparse.Namespace(pack=str(pack_dir), quiet=False, verbose=False)
        errors = validate_verify_args(args)

        self.assertEqual(len(errors), 1)
        self.assertIn("Evidence Pack missing pack_manifest.json", errors[0])

    def test_mutually_exclusive_flags(self):
        """Test validation of mutually exclusive quiet and verbose flags."""
        pack_dir = self.temp_path / "test_pack"
        pack_dir.mkdir()
        manifest_path = pack_dir / "pack_manifest.json"
        manifest_path.write_text('{"pack_sha256": "abc123", "files": []}')

        args = argparse.Namespace(pack=str(pack_dir), quiet=True, verbose=True)
        errors = validate_verify_args(args)

        self.assertEqual(len(errors), 1)
        self.assertIn("Cannot use both --quiet and --verbose flags", errors[0])

    def test_missing_pack_argument(self):
        """Test validation when pack argument is missing."""
        args = argparse.Namespace(quiet=False, verbose=False)
        errors = validate_verify_args(args)

        self.assertEqual(len(errors), 1)
        self.assertIn("Evidence Pack directory is required", errors[0])


class TestVerifyPackFunctionality(unittest.TestCase):
    """Test cases for verify-pack core functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def _create_valid_pack(self, pack_dir: Path, files_data: list[tuple[str, str]]) -> None:
        """Create a valid Evidence Pack for testing."""
        pack_dir.mkdir(exist_ok=True)

        # Create files and compute their hashes
        files = []
        for rel_path, content in files_data:
            file_path = pack_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding='utf-8')

            # Compute hash and size
            import hashlib
            content_bytes = content.encode('utf-8')
            sha256 = hashlib.sha256(content_bytes).hexdigest()

            files.append({
                "path": rel_path,
                "sha256": sha256,
                "bytes": len(content_bytes)
            })

        # Compute pack SHA256
        from cmdrvl_xew.verify import _compute_pack_sha256
        pack_sha256 = _compute_pack_sha256(files)

        # Create manifest
        manifest = {
            "pack_sha256": pack_sha256,
            "files": files
        }

        manifest_path = pack_dir / "pack_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    def test_successful_verification(self):
        """Test successful verification of valid Evidence Pack."""
        pack_dir = self.temp_path / "valid_pack"
        files_data = [
            ("test_file.txt", "Hello, world!"),
            ("data/results.json", '{"status": "ok"}')
        ]
        self._create_valid_pack(pack_dir, files_data)

        args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=False,
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=False
        )

        # Should return 0 for successful verification
        with patch('builtins.print'):  # Suppress output
            result = run_verify_pack(args)
        self.assertEqual(result, 0)

    def test_missing_manifest(self):
        """Test verification fails when manifest is missing."""
        pack_dir = self.temp_path / "pack_no_manifest"
        pack_dir.mkdir()

        args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=False,
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=False
        )

        # Should return 2 for verification failure
        result = run_verify_pack(args)
        self.assertEqual(result, 3)

    def test_check_only_mode(self):
        """Test check-only mode skips hash verification."""
        pack_dir = self.temp_path / "check_only_pack"
        files_data = [("test_file.txt", "Hello, world!")]
        self._create_valid_pack(pack_dir, files_data)

        args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=False,
            quiet=True,
            verbose=False,
            check_only=True,
            fail_fast=False
        )

        with patch('builtins.print'):  # Suppress output
            result = run_verify_pack(args)
        self.assertEqual(result, 0)

    def test_file_hash_mismatch(self):
        """Test verification fails when file hash doesn't match."""
        pack_dir = self.temp_path / "hash_mismatch_pack"
        files_data = [("test_file.txt", "Original content")]
        self._create_valid_pack(pack_dir, files_data)

        # Modify file after creating manifest
        test_file = pack_dir / "test_file.txt"
        test_file.write_text("Modified content", encoding='utf-8')

        args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=False,
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=False
        )

        with patch('sys.stderr'):  # Suppress stderr
            result = run_verify_pack(args)
        self.assertEqual(result, 3)

    def test_fail_fast_mode(self):
        """Test fail-fast mode stops on first error."""
        pack_dir = self.temp_path / "fail_fast_pack"
        files_data = [("test_file.txt", "content")]
        self._create_valid_pack(pack_dir, files_data)

        # Remove file to cause error
        (pack_dir / "test_file.txt").unlink()

        args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=False,
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=True
        )

        with patch('sys.stderr'):  # Suppress stderr
            result = run_verify_pack(args)
        self.assertEqual(result, 3)


class TestSchemaValidation(unittest.TestCase):
    """Test cases for schema validation functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_missing_findings_file(self):
        """Test schema validation when xew_findings.json is missing."""
        pack_dir = self.temp_path / "no_findings"
        pack_dir.mkdir()

        result = _validate_findings_schema(pack_dir, quiet=True, verbose=False)

        self.assertTrue(result.success)
        self.assertTrue(result.is_missing_optional)
        self.assertIn("xew_findings.json not found", result.error_message)

    def test_invalid_json_findings(self):
        """Test schema validation with invalid JSON."""
        pack_dir = self.temp_path / "invalid_json"
        pack_dir.mkdir()

        findings_path = pack_dir / "xew_findings.json"
        findings_path.write_text("invalid json {", encoding='utf-8')

        result = _validate_findings_schema(pack_dir, quiet=True, verbose=False)

        self.assertFalse(result.success)
        self.assertFalse(result.is_missing_optional)
        self.assertIn("Failed to parse xew_findings.json", result.error_message)

    def test_valid_findings_without_jsonschema(self):
        """Test schema validation when jsonschema package is not available."""
        pack_dir = self.temp_path / "valid_findings"
        pack_dir.mkdir()

        findings_data = {
            "pack_id": "test_pack",
            "findings": []
        }
        findings_path = pack_dir / "xew_findings.json"
        findings_path.write_text(json.dumps(findings_data), encoding='utf-8')

        # Mock missing jsonschema import
        with patch('builtins.__import__', side_effect=ModuleNotFoundError("No module named 'jsonschema'")):
            result = _validate_findings_schema(pack_dir, quiet=True, verbose=False)

        self.assertTrue(result.success)
        self.assertTrue(result.is_missing_optional)
        self.assertIn("jsonschema not installed", result.error_message)

    def test_valid_findings_with_jsonschema(self):
        """Test schema validation passes with jsonschema installed."""
        if importlib.util.find_spec("jsonschema") is None:
            self.skipTest("jsonschema not installed")

        pack_dir = self.temp_path / "valid_schema"
        pack_dir.mkdir()
        findings_path = pack_dir / "xew_findings.json"
        findings_path.write_text(json.dumps(self._minimal_valid_findings()), encoding='utf-8')

        result = _validate_findings_schema(pack_dir, quiet=True, verbose=False)

        self.assertTrue(result.success)
        self.assertFalse(result.is_missing_optional)

    def test_invalid_findings_with_jsonschema(self):
        """Test schema validation fails with jsonschema installed."""
        if importlib.util.find_spec("jsonschema") is None:
            self.skipTest("jsonschema not installed")

        pack_dir = self.temp_path / "invalid_schema"
        pack_dir.mkdir()

        findings = self._minimal_valid_findings()
        findings.pop("schema_id", None)
        findings_path = pack_dir / "xew_findings.json"
        findings_path.write_text(json.dumps(findings), encoding='utf-8')

        result = _validate_findings_schema(pack_dir, quiet=True, verbose=False)

        self.assertFalse(result.success)
        self.assertFalse(result.is_missing_optional)
        self.assertIn("Schema validation failed", result.error_message)

    def _minimal_valid_findings(self):
        return {
            "schema_id": "cmdrvl.xew_findings",
            "schema_version": "1.0",
            "generated_at": "2025-01-31T12:00:00Z",
            "toolchain": {
                "cmdrvl_xew_version": "dev",
                "arelle_version": "not_installed",
                "config": {}
            },
            "input": {
                "cik": "0000123456",
                "accession": "0000123456-25-000001",
                "form": "10-Q",
                "filed_date": "2025-01-31",
                "primary_document_url": "https://example.com/primary.html",
                "primary_artifact_path": "artifacts/primary.html"
            },
            "artifacts": [
                {
                    "path": "artifacts/primary.html",
                    "role": "primary_ixbrl",
                    "sha256": "0" * 64,
                    "bytes": 10
                }
            ],
            "findings": []
        }


if __name__ == '__main__':
    unittest.main()
