"""
Standardized exit codes for cmdrvl-xew CLI commands.

This module defines stable exit codes that automation systems can rely on
to determine the nature of failures across all CLI commands.
"""

from __future__ import annotations

import sys
from typing import NoReturn


class ExitCode:
    """Standard exit codes for cmdrvl-xew CLI commands."""

    # Success
    SUCCESS = 0

    # Configuration/argument errors
    CONFIG_ERROR = 1        # Invalid arguments, missing required parameters

    # Tool invocation errors
    INVOCATION_ERROR = 2    # Missing files, invalid paths, malformed inputs

    # Processing/validation failures
    PROCESSING_ERROR = 3    # Pack generation failed, verification failed, detection errors

    # System/environment errors
    SYSTEM_ERROR = 4        # I/O errors, permission denied, network failures


def exit_with_error(exit_code: int, message: str) -> NoReturn:
    """
    Print error message to stderr and exit with specified code.

    Args:
        exit_code: One of the ExitCode constants
        message: Error message to display
    """
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(exit_code)


def exit_config_error(message: str) -> NoReturn:
    """Exit with configuration error code and message."""
    exit_with_error(ExitCode.CONFIG_ERROR, message)


def exit_invocation_error(message: str) -> NoReturn:
    """Exit with invocation error code and message."""
    exit_with_error(ExitCode.INVOCATION_ERROR, message)


def exit_processing_error(message: str) -> NoReturn:
    """Exit with processing error code and message."""
    exit_with_error(ExitCode.PROCESSING_ERROR, message)


def exit_system_error(message: str) -> NoReturn:
    """Exit with system error code and message."""
    exit_with_error(ExitCode.SYSTEM_ERROR, message)


# Mapping of exit codes to human-readable descriptions
EXIT_CODE_DESCRIPTIONS = {
    ExitCode.SUCCESS: "Success",
    ExitCode.CONFIG_ERROR: "Configuration/argument error",
    ExitCode.INVOCATION_ERROR: "Tool invocation error",
    ExitCode.PROCESSING_ERROR: "Processing/validation failure",
    ExitCode.SYSTEM_ERROR: "System/environment error",
}


def describe_exit_code(exit_code: int) -> str:
    """Get human-readable description of exit code."""
    return EXIT_CODE_DESCRIPTIONS.get(exit_code, f"Unknown exit code {exit_code}")