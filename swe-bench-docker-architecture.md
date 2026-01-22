# SWE-bench Docker Architecture

This document explains how SWE-bench uses Docker containers to evaluate model-generated patches for software engineering tasks in isolated, reproducible environments.

## Table of Contents
1. [Overview](#overview)
2. [Three-Layer Docker System](#three-layer-docker-system)
3. [Image Building Process](#image-building-process)
4. [Test Execution Flow](#test-execution-flow)
5. [Concrete Execution Example](#concrete-execution-example)
6. [Integration with Validator](#integration-with-validator)
7. [Resource Requirements](#resource-requirements)

---

## Overview

SWE-bench implements a **hierarchical Docker containerization system** to evaluate patches against real-world GitHub repositories. The system uses three distinct image layers to maximize caching efficiency while maintaining complete isolation for each evaluation task.

### Why Docker?

Docker containerization provides:
- **Reproducibility**: Same environment across all machines
- **Isolation**: Each evaluation runs independently without conflicts
- **Clean State**: Fresh environment for every test
- **Version Control**: Exact dependency versions from historical commits
- **Security**: Sandboxed execution prevents system contamination

---

## Three-Layer Docker System

SWE-bench builds Docker images hierarchically, with each layer serving a specific purpose:

```
┌─────────────────────────────────────────┐
│         Instance Image (2000+)          │  ← Specific task: repo@commit + deps
│  - Clones repository at base_commit     │
│  - Installs task-specific dependencies  │
│  - Applies test patches if needed       │
└─────────────────────────────────────────┘
                    ↑ inherits from
┌─────────────────────────────────────────┐
│       Environment Image (~60)           │  ← Python environment configs
│  - Python version (3.7, 3.8, 3.9, etc.) │
│  - Common pip/conda packages            │
│  - Testing frameworks (pytest, unittest)│
└─────────────────────────────────────────┘
                    ↑ inherits from
┌─────────────────────────────────────────┐
│          Base Image (1)                 │  ← OS + system packages
│  - Ubuntu 20.04 or 22.04                │
│  - System dependencies (gcc, git, etc.) │
│  - Docker-in-docker utilities           │
└─────────────────────────────────────────┘
```

### Layer 1: Base Image

**Purpose**: Provides the operating system foundation and system-level dependencies common to all evaluations.

**Contains**:
- Ubuntu Linux (typically 20.04 or 22.04)
- System packages: `gcc`, `g++`, `make`, `git`, `curl`, `wget`
- Build tools for compiling native extensions
- Docker utilities for container management
- Basic shell environment

**Built**: Once per operating system version.

**Size**: ~1-2 GB

**Example Dockerfile snippet**:
```dockerfile
FROM ubuntu:20.04
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*
```

---

### Layer 2: Environment Image

**Purpose**: Configures the Python environment and installs testing framework dependencies that are shared across multiple instances.

**Contains**:
- Specific Python version (3.7, 3.8, 3.9, 3.10, 3.11, etc.)
- Package managers: `pip`, `conda`
- Testing frameworks: `pytest`, `unittest`, `nose`, `tox`
- Common scientific libraries: `numpy`, `scipy`, `pandas` (if needed by multiple tasks)
- Virtual environment tools

**Built**: ~60 images total (one per Python version + common dependency combination)

**Size**: ~1.5-2 GB per environment

**When built**:
- First time an instance with that Python version is evaluated
- Cached for subsequent uses with `--cache_level env` (default)

**Example configuration**:
```dockerfile
FROM swebench_base:latest
RUN conda create -n testbed python=3.9 -y
RUN conda install -n testbed pytest pytest-cov pytest-xdist -y
```

**Why 60 images?**
Different repositories require different Python versions and testing setups:
- Django (Python 3.8, 3.9, 3.10)
- Matplotlib (Python 3.7, 3.8, 3.9 with numpy)
- scikit-learn (Python 3.8, 3.9 with scipy/numpy)
- etc.

---

### Layer 3: Instance Image

**Purpose**: Creates a task-specific container for evaluating a single data point with its exact repository state and dependencies.

**Contains**:
- Repository cloned at `base_commit` (the commit where the bug exists)
- Task-specific dependencies installed from `requirements.txt`, `setup.py`, or `pyproject.toml`
- Test files (potentially including `test_patch` additions)
- Environment variables specific to the task
- Working directory set to repository root

**Built**: One per evaluation task (2000+ for full SWE-bench)

**Size**: 100 MB - 2 GB per instance (depending on repository size)

**When built**:
- On-demand when evaluating each instance
- Only cached with `--cache_level instance` (requires ~2 TB storage)

**Build process**:
1. Start from appropriate environment image (e.g., `python3.9_pytest`)
2. Clone repository: `git clone https://github.com/{repo}.git`
3. Checkout base commit: `git checkout {base_commit}`
4. Install repository dependencies: `pip install -e .` or equivalent
5. Apply test patch if present (adds new test cases)
6. Set working directory and entry point

**Example build**:
```dockerfile
FROM swebench_env_python3.9:latest
WORKDIR /testbed
RUN git clone https://github.com/astropy/astropy.git .
RUN git checkout 3832210580d516365ddae1a62071001faf94d416
RUN pip install -e .[test]
```

---

## Image Building Process

### Build Triggers

Images are built **lazily** (on-demand) when first needed:

1. **Base Image**: Built once when first running evaluation
2. **Environment Image**: Built when encountering a new Python version + dependency combination
3. **Instance Image**: Built for each unique `instance_id` being evaluated

### Caching Strategy

The `--cache_level` parameter controls which layers persist after evaluation:

| Cache Level | What's Cached | Disk Usage | Speed | Use Case |
|-------------|---------------|------------|-------|----------|
| `none` | Nothing | ~120 GB | Slowest | One-time evaluation, limited storage |
| `base` | Base image only | ~150 GB | Slow | Rare evaluations |
| `env` | Base + Environment | ~100 GB | **Fast** (default) | Regular evaluations |
| `instance` | All layers | ~2000 GB | Fastest | High-volume evaluations |

**Default recommendation**: Use `--cache_level env` for best balance.

### Dependency Installation

**Where dependencies are installed**:

1. **System dependencies** (gcc, make, git) → **Base Image**
   ```bash
   apt-get install build-essential
   ```

2. **Python version & testing frameworks** → **Environment Image**
   ```bash
   conda create -n testbed python=3.9
   conda install pytest
   ```

3. **Repository-specific dependencies** → **Instance Image**
   ```bash
   # From data point's repository at base_commit
   pip install -e .
   # Or from requirements.txt, setup.py, etc.
   ```

**Example for `astropy__astropy-11693`**:
- System deps (Base): gcc, gfortran (for numpy/scipy compilation)
- Environment (Env): Python 3.9 + pytest 6.x
- Astropy deps (Instance): numpy, scipy, matplotlib, pytest-astropy, extension-helpers

---

## Test Execution Flow

Once the instance image is built, SWE-bench executes tests through the following pipeline:

### Step 1: Start Container

```bash
docker run -it \
  --name swebench_{instance_id} \
  --rm \
  -v /results:/results \
  swebench_instance_{instance_id}:latest \
  /bin/bash -c "evaluation_script.sh"
```

### Step 2: Apply Model Patch

Inside the container:

```bash
cd /testbed
# Save patch to file
cat > /tmp/model.patch << 'EOF'
{model_patch content}
EOF

# Apply patch (exits with error if patch fails)
git apply --check /tmp/model.patch  # Dry run first
git apply /tmp/model.patch          # Actually apply
```

**If patch fails to apply**: Evaluation stops, result marked as `"patch_failed"`.

### Step 3: Run Tests

Execute tests specified in the data point:

```bash
# Run FAIL_TO_PASS tests (should now pass after patch)
pytest astropy/wcs/wcsapi/tests/test_fitswcs.py::test_non_convergence_warning -xvs

# Run PASS_TO_PASS tests (should still pass, regression check)
pytest astropy/wcs/wcsapi/tests/test_fitswcs.py::test_empty -xvs
pytest astropy/wcs/wcsapi/tests/test_fitswcs.py::test_simple_celestial -xvs
# ... (all PASS_TO_PASS tests)
```

**Timeout handling**: Each test run has a timeout (default: 900 seconds = 15 minutes)

```bash
timeout 900 pytest {test_path}
EXIT_CODE=$?

if [ $EXIT_CODE -eq 124 ]; then
  echo "TIMEOUT: Test exceeded 900s limit"
fi
```

### Step 4: Parse Output

The harness captures:
- **Exit code**: 0 = pass, non-zero = fail
- **STDOUT/STDERR**: Test output, error messages
- **Test result markers**: `PASSED`, `FAILED`, `ERROR`, `SKIPPED`

**Example pytest output**:
```
============================= test session starts ==============================
test_fitswcs.py::test_non_convergence_warning PASSED                     [100%]
============================== 1 passed in 2.45s ===============================
```

Parsed to:
```json
{
  "test": "astropy/wcs/wcsapi/tests/test_fitswcs.py::test_non_convergence_warning",
  "status": "PASSED",
  "duration": 2.45
}
```

### Step 5: Determine Resolution

A patch **resolves the issue** if and only if:

✅ **ALL** tests in `FAIL_TO_PASS` now **PASS**
✅ **ALL** tests in `PASS_TO_PASS` still **PASS**

Any other outcome (test failures, patch apply failures, timeouts, errors) → **NOT RESOLVED**

### Step 6: Cleanup

```bash
docker stop swebench_{instance_id}
docker rm swebench_{instance_id}

# If --clean flag set:
docker rmi swebench_instance_{instance_id}:latest
```

---

## Concrete Execution Example

Let's walk through evaluating `astropy__astropy-11693` with a golden patch:

### Data Point Summary

```json
{
  "instance_id": "astropy__astropy-11693",
  "repo": "astropy/astropy",
  "base_commit": "3832210580d516365ddae1a62071001faf94d416",
  "FAIL_TO_PASS": ["astropy/wcs/wcsapi/tests/test_fitswcs.py::test_non_convergence_warning"],
  "PASS_TO_PASS": ["astropy/wcs/wcsapi/tests/test_fitswcs.py::test_empty", "...17 more tests..."]
}
```

### Execution Timeline

**T=0s**: Load prediction
```python
prediction = {
    "instance_id": "astropy__astropy-11693",
    "model_patch": "<patch content from data point>",
    "model_name_or_path": "golden"
}
```

**T=5s**: Build instance image (if not cached)
```bash
# Uses cached python3.9 environment image
docker build -t swebench_astropy__astropy-11693 .
```
```dockerfile
FROM swebench_env_python3.9
RUN git clone https://github.com/astropy/astropy.git /testbed
WORKDIR /testbed
RUN git checkout 3832210580d516365ddae1a62071001faf94d416
RUN pip install -e .[test]
```

**T=45s**: Start container and apply patch
```bash
docker run swebench_astropy__astropy-11693 /bin/bash -c '
  cd /testbed
  git apply <<EOF
diff --git a/astropy/wcs/wcsapi/fitswcs.py b/astropy/wcs/wcsapi/fitswcs.py
--- a/astropy/wcs/wcsapi/fitswcs.py
+++ b/astropy/wcs/wcsapi/fitswcs.py
@@ -323,7 +323,17 @@ def pixel_to_world_values(self, *pixel_arrays):
     def world_to_pixel_values(self, *world_arrays):
-        pixel = self.all_world2pix(*world_arrays, 0)
+        from astropy.wcs.wcs import NoConvergence
+        try:
+            pixel = self.all_world2pix(*world_arrays, 0)
+        except NoConvergence as e:
+            warnings.warn(str(e))
+            pixel = self._array_converter(lambda *args: e.best_solution,
+                                          'input', *world_arrays, 0)
EOF
'
```

**T=47s**: Run FAIL_TO_PASS test (should now pass)
```bash
pytest astropy/wcs/wcsapi/tests/test_fitswcs.py::test_non_convergence_warning -xvs
# Output:
# test_non_convergence_warning PASSED ✅
```

**T=50s**: Run PASS_TO_PASS tests (should still pass)
```bash
pytest astropy/wcs/wcsapi/tests/test_fitswcs.py::test_empty -xvs
# Output: test_empty PASSED ✅

pytest astropy/wcs/wcsapi/tests/test_fitswcs.py::test_simple_celestial -xvs
# Output: test_simple_celestial PASSED ✅

# ... continues for all 17 PASS_TO_PASS tests ...
```

**T=125s**: All tests complete
```
FAIL_TO_PASS: 1/1 PASSED ✅
PASS_TO_PASS: 17/17 PASSED ✅
RESULT: RESOLVED ✅
```

**T=130s**: Cleanup
```bash
docker stop swebench_astropy__astropy-11693
# Image remains cached (using --cache_level instance)
```

### Final Result

```json
{
  "instance_id": "astropy__astropy-11693",
  "resolved": true,
  "test_results": {
    "FAIL_TO_PASS": {"passed": 1, "failed": 0, "total": 1},
    "PASS_TO_PASS": {"passed": 17, "failed": 0, "total": 17}
  },
  "patch_applied": true,
  "error": null,
  "duration": 130.5
}
```

---

## Integration with Validator

Our validator integrates with this Docker infrastructure as follows:

### Validator's Role

```
┌──────────────────────────────────────────────┐
│         Validator Script                     │
│  1. Load JSON data points                    │
│  2. Convert to prediction format             │
│  3. Call run_evaluation()                    │
│  4. Parse and validate results               │
└──────────────────────────────────────────────┘
                    ↓ calls
┌──────────────────────────────────────────────┐
│      swebench.harness.run_evaluation()       │
│  - Manages all Docker operations             │
│  - Builds images (3 layers)                  │
│  - Executes tests in containers              │
│  - Returns results                           │
└──────────────────────────────────────────────┘
```

### Validator Does NOT:
- ❌ Manage Docker containers directly
- ❌ Build or cache images manually
- ❌ Execute git/pytest commands directly
- ❌ Parse test output formats

### Validator DOES:
- ✅ Load data point JSON files
- ✅ Convert to SWE-bench prediction format
- ✅ Call `run_evaluation()` with appropriate parameters
- ✅ Validate that FAIL_TO_PASS tests pass
- ✅ Validate that PASS_TO_PASS tests still pass
- ✅ Report errors clearly to users

### Code Integration

```python
from swebench.harness.run_evaluation import run_evaluation

# Validator loads data point
data_point = json.load(open("astropy__astropy-11693.json"))

# Convert to prediction format
prediction = {
    "instance_id": data_point["instance_id"],
    "model_patch": data_point["patch"],  # Use golden patch
    "model_name_or_path": "golden_validator"
}

# Call SWE-bench evaluation (handles all Docker operations)
results = run_evaluation(
    predictions=[prediction],
    dataset_name="princeton-nlp/SWE-bench",
    cache_level="env",  # Cache environment images
    max_workers=1,      # Validate one at a time
    run_id=f"validate_{data_point['instance_id']}"
)

# Validator checks results
if results[0]["resolved"] == True:
    print(f"✅ VALID: {data_point['instance_id']}")
else:
    print(f"❌ INVALID: {data_point['instance_id']}")
    print(f"Error: {results[0]['error']}")
```

### Dependency Installation Location

For `astropy__astropy-11693`:

1. **Base Image** (Ubuntu 20.04):
   - gcc, gfortran → Compile numpy/scipy C extensions

2. **Environment Image** (Python 3.9):
   - pytest 6.2.x → Testing framework
   - pytest-astropy → Astropy-specific test utilities

3. **Instance Image** (astropy at commit 383221):
   - Astropy source code → `git clone && git checkout`
   - numpy, scipy, matplotlib → From `pip install -e .[test]`
   - astropy test dependencies → From setup.cfg `[options.extras_require]`

---

## Resource Requirements

### Disk Space

| Cache Level | During Execution | After Cleanup | Recommended |
|-------------|------------------|---------------|-------------|
| none | ~120 GB | ~0 GB | One-time use |
| env | ~120 GB | ~100 GB | **Regular use** ✅ |
| instance | ~2000 GB | ~2000 GB | High-volume |

### Memory

- Minimum: 16 GB RAM
- Recommended: 32 GB RAM (for parallel evaluation)
- Docker allocation: 8+ CPUs, 16+ GB RAM

### Time

Per instance evaluation:
- First run (build all layers): 2-5 minutes
- Cached environment: 30-90 seconds
- Cached instance: 10-30 seconds

Full SWE-bench (2294 instances):
- Sequential: ~50-100 hours
- 8 workers with caching: ~10-15 hours

---

## Summary

SWE-bench's Docker architecture provides:

1. **Three-layer caching** → Fast re-evaluation
2. **Complete isolation** → No cross-contamination between tasks
3. **Reproducibility** → Identical environment everywhere
4. **Automated management** → Validators just call `run_evaluation()`

The validator's job is simple: Load data points, call the evaluation harness, and check if all required tests pass. Docker complexity is entirely handled by the SWE-bench library.
