"""
Unit tests for standardized exit codes across all CLI commands.
"""

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

from cmdrvl_xew.exit_codes import (
    ExitCode,
    exit_config_error,
    exit_invocation_error,
    exit_processing_error,
    exit_system_error,
    describe_exit_code,
    EXIT_CODE_DESCRIPTIONS
)
from cmdrvl_xew.flatten import run_flatten
from cmdrvl_xew.fetch import run_fetch
from cmdrvl_xew.verify import run_verify_pack


class TestExitCodes(unittest.TestCase):
    """Test cases for standardized exit codes."""

    def test_exit_code_constants(self):
        """Test that exit code constants are defined correctly."""
        self.assertEqual(ExitCode.SUCCESS, 0)
        self.assertEqual(ExitCode.CONFIG_ERROR, 1)
        self.assertEqual(ExitCode.INVOCATION_ERROR, 2)
        self.assertEqual(ExitCode.PROCESSING_ERROR, 3)
        self.assertEqual(ExitCode.SYSTEM_ERROR, 4)

    def test_exit_functions(self):
        """Test that exit functions call sys.exit with correct codes."""
        with self.assertRaises(SystemExit) as cm:
            exit_config_error("test config error")
        self.assertEqual(cm.exception.code, ExitCode.CONFIG_ERROR)

        with self.assertRaises(SystemExit) as cm:
            exit_invocation_error("test invocation error")
        self.assertEqual(cm.exception.code, ExitCode.INVOCATION_ERROR)

        with self.assertRaises(SystemExit) as cm:
            exit_processing_error("test processing error")
        self.assertEqual(cm.exception.code, ExitCode.PROCESSING_ERROR)

        with self.assertRaises(SystemExit) as cm:
            exit_system_error("test system error")
        self.assertEqual(cm.exception.code, ExitCode.SYSTEM_ERROR)

    def test_exit_code_descriptions(self):
        """Test exit code description mapping."""
        self.assertEqual(describe_exit_code(0), "Success")
        self.assertEqual(describe_exit_code(1), "Configuration/argument error")
        self.assertEqual(describe_exit_code(2), "Tool invocation error")
        self.assertEqual(describe_exit_code(3), "Processing/validation failure")
        self.assertEqual(describe_exit_code(4), "System/environment error")
        self.assertEqual(describe_exit_code(99), "Unknown exit code 99")

    def test_all_exit_codes_documented(self):
        """Test that all defined exit codes have descriptions."""
        for exit_code in [ExitCode.SUCCESS, ExitCode.CONFIG_ERROR, ExitCode.INVOCATION_ERROR,
                         ExitCode.PROCESSING_ERROR, ExitCode.SYSTEM_ERROR]:
            self.assertIn(exit_code, EXIT_CODE_DESCRIPTIONS)


class TestFlattenExitCodes(unittest.TestCase):
    """Test exit codes for flatten command."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_flatten_success(self):
        """Test flatten returns SUCCESS for valid input."""
        # Create valid EDGAR structure
        edgar_dir = self.temp_path / "edgar"
        edgar_dir.mkdir()
        form_dir = edgar_dir / "10-Q"
        form_dir.mkdir()
        (form_dir / "test.htm").write_text('<html><body>test</body></html>')

        out_dir = self.temp_path / "output"

        args = argparse.Namespace(
            edgar_dir=str(edgar_dir),
            out=str(out_dir),
            force=False
        )

        result = run_flatten(args)
        self.assertEqual(result, ExitCode.SUCCESS)

    def test_flatten_invocation_error_missing_edgar(self):
        """Test flatten exits with INVOCATION_ERROR for missing EDGAR directory."""
        out_dir = self.temp_path / "output"

        args = argparse.Namespace(
            edgar_dir="/nonexistent/path",
            out=str(out_dir),
            force=False
        )

        with self.assertRaises(SystemExit) as cm:
            run_flatten(args)
        self.assertEqual(cm.exception.code, ExitCode.INVOCATION_ERROR)

    def test_flatten_invocation_error_output_not_directory(self):
        """Test flatten exits with INVOCATION_ERROR when output path is a file."""
        # Create valid EDGAR structure
        edgar_dir = self.temp_path / "edgar"
        edgar_dir.mkdir()
        form_dir = edgar_dir / "10-Q"
        form_dir.mkdir()
        (form_dir / "test.htm").write_text('<html><body>test</body></html>')

        # Create a file instead of directory for output
        out_file = self.temp_path / "output.txt"
        out_file.write_text("not a directory")

        args = argparse.Namespace(
            edgar_dir=str(edgar_dir),
            out=str(out_file),
            force=False
        )

        with self.assertRaises(SystemExit) as cm:
            run_flatten(args)
        self.assertEqual(cm.exception.code, ExitCode.INVOCATION_ERROR)


class TestFetchExitCodes(unittest.TestCase):
    """Test exit codes for fetch command."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_fetch_invocation_error_missing_user_agent(self):
        """Test fetch exits with INVOCATION_ERROR for missing user agent."""
        out_dir = self.temp_path / "output"

        args = argparse.Namespace(
            cik="0000123456",
            accession="0000123456-12-345678",
            out=str(out_dir),
            user_agent="",  # Empty user agent should trigger error
            min_interval=0.2,
            force=False
        )

        with self.assertRaises(SystemExit) as cm:
            run_fetch(args)
        self.assertEqual(cm.exception.code, ExitCode.INVOCATION_ERROR)

    def test_fetch_invocation_error_output_not_directory(self):
        """Test fetch exits with INVOCATION_ERROR when output path is a file."""
        # Create a file instead of directory for output
        out_file = self.temp_path / "output.txt"
        out_file.write_text("not a directory")

        args = argparse.Namespace(
            cik="0000123456",
            accession="0000123456-12-345678",
            out=str(out_file),
            user_agent="Test/1.0",
            min_interval=0.2,
            force=False
        )

        with self.assertRaises(SystemExit) as cm:
            run_fetch(args)
        self.assertEqual(cm.exception.code, ExitCode.INVOCATION_ERROR)


class TestVerifyExitCodes(unittest.TestCase):
    """Test exit codes for verify-pack command."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_verify_processing_error_missing_manifest(self):
        """Test verify-pack exits with PROCESSING_ERROR for missing manifest."""
        pack_dir = self.temp_path / "empty_pack"
        pack_dir.mkdir()

        args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=False,
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=False
        )

        result = run_verify_pack(args)
        self.assertEqual(result, ExitCode.PROCESSING_ERROR)

    def test_verify_processing_error_malformed_manifest(self):
        """Test verify-pack exits with PROCESSING_ERROR for malformed manifest."""
        pack_dir = self.temp_path / "bad_manifest_pack"
        pack_dir.mkdir()
        manifest_path = pack_dir / "pack_manifest.json"
        manifest_path.write_text("invalid json {")

        args = argparse.Namespace(
            pack=str(pack_dir),
            validate_schema=False,
            quiet=True,
            verbose=False,
            check_only=False,
            fail_fast=False
        )

        result = run_verify_pack(args)
        self.assertEqual(result, ExitCode.PROCESSING_ERROR)


if __name__ == '__main__':
    unittest.main()