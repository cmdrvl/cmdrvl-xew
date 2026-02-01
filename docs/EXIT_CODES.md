# cmdrvl-xew Exit Codes

This document defines the standardized exit codes for all `cmdrvl-xew` CLI commands.

## Exit Code Standards

The `cmdrvl-xew` CLI uses the following standardized exit codes across all commands (`pack`, `verify-pack`, `flatten`, `fetch`):

| Exit Code | Constant | Meaning | Examples |
|-----------|----------|---------|----------|
| 0 | `SUCCESS` | Command completed successfully | Pack generated, verification passed, files flattened |
| 1 | `CONFIG_ERROR` | Configuration/argument error | Invalid arguments, missing required parameters, mutually exclusive flags |
| 2 | `INVOCATION_ERROR` | Tool invocation error | Missing files, invalid paths, malformed inputs, directory access issues |
| 3 | `PROCESSING_ERROR` | Processing/validation failure | Pack generation failed, verification failed, detection errors |
| 4 | `SYSTEM_ERROR` | System/environment error | I/O errors, permission denied, network failures |

## Command-Specific Exit Scenarios

### `cmdrvl-xew pack`

| Exit Code | Scenario |
|-----------|----------|
| 0 | Evidence Pack generated successfully |
| 1 | Invalid CIK format, missing required arguments, invalid form type |
| 2 | Primary file not found, output directory invalid, EDGAR structure missing |
| 3 | XBRL parsing failed, detector execution failed, pack generation errors |
| 4 | File I/O errors, permission denied on output directory |

### `cmdrvl-xew verify-pack`

| Exit Code | Scenario |
|-----------|----------|
| 0 | Evidence Pack verification passed |
| 1 | Invalid arguments, conflicting flags (--quiet and --verbose) |
| 2 | Pack directory missing, manifest not found, malformed manifest |
| 3 | Hash verification failed, schema validation failed, file corruption |
| 4 | Cannot read pack files, permission denied |

### `cmdrvl-xew flatten`

| Exit Code | Scenario |
|-----------|----------|
| 0 | EDGAR directory flattened successfully |
| 1 | Invalid arguments, missing required parameters |
| 2 | EDGAR directory not found, output path issues, no primary iXBRL found |
| 4 | Cannot create output directory, file I/O errors |

### `cmdrvl-xew fetch`

| Exit Code | Scenario |
|-----------|----------|
| 0 | Artifacts downloaded successfully |
| 1 | Missing user-agent, invalid arguments |
| 2 | Invalid CIK/accession format, output directory issues |
| 4 | Network errors, SEC access denied, download failures |

## Usage in Automation

These exit codes are designed for reliable automation and CI/CD integration:

```bash
# Success handling
if cmdrvl-xew pack --pack-id test --out ./pack ...; then
    echo "Pack generation successful"
    cmdrvl-xew verify-pack --pack ./pack --validate-schema
fi

# Error handling by category
case $? in
    0) echo "Success" ;;
    1) echo "Configuration error - fix arguments" ;;
    2) echo "Invocation error - check inputs" ;;
    3) echo "Processing failed - check data" ;;
    4) echo "System error - check environment" ;;
    *) echo "Unknown exit code" ;;
esac
```

## Error Message Format

All error messages follow a consistent format:

```
Error: <descriptive message>
```

Examples:
- `Error: CIK must contain only digits`
- `Error: Evidence Pack directory does not exist: /path/to/pack`
- `Error: SHA256 mismatch: file.xml: expected abc123, got def456`

## Implementation

Exit codes are implemented using the `src/cmdrvl_xew/exit_codes.py` module, which provides:

- `ExitCode` class with standardized constants
- `exit_with_error()` helper function
- Specialized exit functions: `exit_config_error()`, `exit_invocation_error()`, etc.
- Exit code descriptions for debugging

This standardization ensures predictable behavior across all CLI commands and enables reliable automation workflows.