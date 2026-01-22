# SWE-bench Data Point Validator

A validation system that ensures the quality and correctness of SWE-bench data points before they are added to a repository. This tool uses SWE-bench's official evaluation harness to verify that golden patches correctly resolve issues.

## Overview

[SWE-bench](https://github.com/princeton-nlp/SWE-bench) is a benchmark dataset for evaluating large language models on real-world software engineering tasks. Each data point contains a GitHub issue along with its corresponding fix (patch) and test cases.

This validator automatically checks that:
- ✅ The patch applies cleanly to the repository at the specified commit
- ✅ All tests in `FAIL_TO_PASS` pass after applying the patch
- ✅ All tests in `PASS_TO_PASS` continue to pass (regression check)

## Features

- **Automated Validation**: Uses SWE-bench's Docker-based evaluation harness
- **CI/CD Integration**: GitHub Action automatically validates data points in pull requests
- **Detailed Error Reporting**: Clear, actionable error messages for failures
- **Selective Validation**: Only validates changed files for performance
- **Multiple Interfaces**: CLI tool and programmatic API

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage](#usage)
  - [Command Line](#command-line)
  - [GitHub Action](#github-action)
- [Project Structure](#project-structure)
- [Documentation](#documentation)
- [Requirements](#requirements)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## Installation

### Prerequisites

- **Python**: 3.10 or higher
- **Docker**: Docker Desktop or Docker Engine (with daemon running)
- **UV**: Python package manager (recommended) or pip
- **Disk Space**: At least 120GB free (for Docker images)
- **Memory**: 16GB RAM minimum, 32GB recommended

### Install UV (if not already installed)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Clone and Install

```bash
# Clone the repository
git clone <your-repo-url>
cd swe-bench-validator

# Install dependencies
uv sync

# Verify installation
uv run python -m swe_bench_validator --help
```

## Quick Start

### Validate a Single File

```bash
uv run python -m swe_bench_validator --file data_points/astropy__astropy-11693.json
```

### Validate All Files in Directory

```bash
uv run python -m swe_bench_validator --directory data_points/
```

### Validate with JSON Output

```bash
uv run python -m swe_bench_validator \
  --directory data_points/ \
  --json-output results.json
```

## Usage

### Command Line

The validator provides a CLI with multiple options:

```bash
uv run python -m swe_bench_validator [OPTIONS]
```

#### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--file PATH` | Validate a single JSON file | - |
| `--directory PATH` | Validate all JSON files in directory | - |
| `--files PATH` | Validate multiple specific files (repeatable) | - |
| `--timeout INT` | Timeout per instance in seconds | 900 (15 min) |
| `--cache-level LEVEL` | Docker cache level (none/base/env/instance) | env |
| `--max-workers INT` | Number of parallel workers | 1 |
| `--json-output PATH` | Save results to JSON file | - |
| `--no-details` | Hide detailed error messages | false |
| `-v, --verbose` | Enable verbose logging | false |

#### Examples

```bash
# Validate specific files
uv run python -m swe_bench_validator \
  --files data_points/file1.json \
  --files data_points/file2.json

# Validate with custom timeout (30 minutes)
uv run python -m swe_bench_validator \
  --file data_points/astropy__astropy-11693.json \
  --timeout 1800

# Validate with maximum Docker caching
uv run python -m swe_bench_validator \
  --directory data_points/ \
  --cache-level instance

# Quiet mode with JSON output only
uv run python -m swe_bench_validator \
  --directory data_points/ \
  --json-output results.json \
  --no-details
```

### GitHub Action

The repository includes a GitHub Action that automatically validates data points when they are added or modified in pull requests.

#### Workflow File

`.github/workflows/validate-datapoints.yml`

#### Triggers

The workflow runs when:
- Files matching `data_points/**/*.json` are pushed
- Pull requests modify files in `data_points/`

#### What It Does

1. Detects which data point files changed
2. Validates only the changed files (performance optimization)
3. Reports results as GitHub status checks
4. Comments on pull requests with detailed results
5. Fails the check if any data point is invalid

#### Status Check Examples

**Valid Data Point (Green Check)**:
```
✅ All data points validated successfully!
```

**Invalid Data Point (Red X)**:
```
❌ Validation failed for one or more data points

Failed data points:
  - astropy__astropy-11693-fail: test_failure - Tests did not pass as expected...
```

## Project Structure

```
.
├── .github/
│   └── workflows/
│       └── validate-datapoints.yml    # GitHub Action workflow
├── data_points/                       # SWE-bench data points (JSON files)
│   ├── astropy__astropy-11693.json   # Example: valid data point
│   └── astropy__astropy-11693-fail.json  # Example: invalid data point
├── swe_bench_downloader/              # Data point downloader utility
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   └── downloader.py
├── swe_bench_validator/               # Validator package (THIS IS NEW)
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                        # Command-line interface
│   ├── validator.py                  # Core validation logic
│   └── results.py                    # Result formatting
├── scripts/
│   └── download_swe_bench.sh         # Script to download more data points
├── swe-bench-docker-architecture.md  # Docker architecture documentation
├── pyproject.toml                     # Project dependencies
├── uv.lock                            # Lock file
└── README.md                          # This file
```

## Documentation

### SWE-bench Docker Architecture

See [swe-bench-docker-architecture.md](swe-bench-docker-architecture.md) for comprehensive documentation on:
- How SWE-bench uses Docker for evaluation
- The 3-layer Docker image system (Base → Environment → Instance)
- Test execution flow and result parsing
- When and where dependencies are installed

### Data Point Format

Each data point is a JSON file with the following structure:

```json
{
  "instance_id": "repo_owner__repo_name-issue_number",
  "repo": "owner/repo",
  "base_commit": "commit_hash",
  "patch": "unified_diff_patch",
  "test_patch": "test_additions_diff",
  "problem_statement": "bug_description",
  "FAIL_TO_PASS": ["test_path1", "test_path2"],
  "PASS_TO_PASS": ["test_path3", "test_path4"],
  "environment_setup_commit": "commit_hash"
}
```

#### Key Fields

- **`instance_id`**: Unique identifier for the data point
- **`patch`**: The code fix in unified diff format
- **`FAIL_TO_PASS`**: Tests that should pass after applying the patch
- **`PASS_TO_PASS`**: Tests that must continue passing (regression check)
- **`base_commit`**: Repository commit where the bug exists

## Requirements

### System Requirements

- **Operating System**: Linux (recommended), macOS, or Windows with WSL2
- **Docker**: Must be installed and running
- **CPU**: 4+ cores recommended for parallel evaluation
- **RAM**: 16GB minimum, 32GB recommended
- **Disk**: 120GB minimum free space
  - With `--cache-level env` (default): ~100GB after caching
  - With `--cache-level instance`: ~2TB for full caching

### Docker Configuration

For Docker Desktop users, configure:
- CPUs: 8+ (in Docker Desktop settings)
- Memory: 16GB+ (in Docker Desktop settings)
- Disk: Ensure sufficient space allocated

### Python Dependencies

Managed by `pyproject.toml`:
- `swebench>=4.0.4` - SWE-bench evaluation harness
- `docker>=7.1.0` - Docker Python client
- `click>=8.0.0` - CLI framework
- `rich>=12.0.0` - Rich terminal output
- Additional utilities (see `pyproject.toml`)

## Troubleshooting

### Docker Not Running

**Error**: `Failed to connect to Docker. Is Docker running?`

**Solution**:
```bash
# Check if Docker is running
docker ps

# Start Docker Desktop (macOS/Windows)
# or start Docker daemon (Linux)
sudo systemctl start docker
```

### Insufficient Disk Space

**Error**: `No space left on device`

**Solution**:
- Free up disk space
- Use `--cache-level none` to minimize space usage
- Clean Docker images: `docker system prune -a`

### Timeout Errors

**Error**: Evaluation times out after 15 minutes

**Solution**:
- Increase timeout: `--timeout 1800` (30 minutes)
- Some repositories have slow test suites

### Import Error: swebench

**Error**: `ModuleNotFoundError: No module named 'swebench'`

**Solution**:
```bash
# Reinstall dependencies
uv sync

# Or manually install
pip install swebench>=4.0.4
```

### Patch Apply Failures

**Error**: `patch_error: Patch failed to apply to repository`

**Causes**:
- Incorrect `base_commit` in data point
- Malformed patch (incorrect line numbers/context)
- Repository structure changed

**Solution**: Review and fix the data point JSON file

## Downloading More Data Points

Use the included downloader to fetch additional data points:

```bash
# Download specific instance
./scripts/download_swe_bench.sh --instance_id "django__django-10087"

# Download multiple instances from a repository
./scripts/download_swe_bench.sh --repo "django/django" --limit 5

# Download by difficulty
./scripts/download_swe_bench.sh --difficulty "easy" --limit 10
```

All downloaded data points are saved to `data_points/` directory.

## Testing Your Installation

### 1. Validate the Valid Example

```bash
uv run python -m swe_bench_validator \
  --file data_points/astropy__astropy-11693.json
```

Expected output: `✅ All data points are valid!`

### 2. Validate the Invalid Example

```bash
uv run python -m swe_bench_validator \
  --file data_points/astropy__astropy-11693-fail.json
```

Expected output: `❌ 1 data point(s) failed validation` with detailed error message

## Contributing

### Adding New Data Points

1. Add JSON file to `data_points/` directory
2. Create a pull request
3. GitHub Action will automatically validate
4. Review validation results in PR comments

### Validation Criteria

A data point is considered **valid** if:
1. ✅ JSON structure is correct (all required fields present)
2. ✅ Patch applies successfully to the repository
3. ✅ All `FAIL_TO_PASS` tests pass after applying the patch
4. ✅ All `PASS_TO_PASS` tests continue to pass

A data point is **invalid** if:
1. ❌ JSON is malformed or missing required fields
2. ❌ Patch fails to apply (merge conflicts, wrong commit, etc.)
3. ❌ Any `FAIL_TO_PASS` test still fails after applying the patch
4. ❌ Any `PASS_TO_PASS` test breaks after applying the patch

## Acknowledgments

- [SWE-bench](https://github.com/princeton-nlp/SWE-bench) - The official SWE-bench evaluation benchmark
- [UV](https://github.com/astral-sh/uv) - Fast Python package manager
- [Rich](https://github.com/Textualize/rich) - Beautiful terminal formatting

## License

This project is provided as-is for educational and evaluation purposes.

## Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review [swe-bench-docker-architecture.md](swe-bench-docker-architecture.md)
3. Open an issue in this repository
4. Consult [SWE-bench documentation](https://www.swebench.com/)
