"""Core validation logic for SWE-bench data points."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating a single data point."""

    instance_id: str
    file_path: str
    is_valid: bool
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    fail_to_pass_results: Optional[Dict[str, str]] = None
    pass_to_pass_results: Optional[Dict[str, str]] = None
    resolved: Optional[bool] = None
    patch_applied: Optional[bool] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "instance_id": self.instance_id,
            "file_path": str(self.file_path),
            "is_valid": self.is_valid,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "fail_to_pass_results": self.fail_to_pass_results,
            "pass_to_pass_results": self.pass_to_pass_results,
            "resolved": self.resolved,
            "patch_applied": self.patch_applied,
        }


class SWEBenchValidator:
    """Validates SWE-bench data points using the official evaluation harness."""

    def __init__(
        self,
        timeout: int = 900,
        cache_level: str = "env",
        max_workers: int = 1,
        verbose: bool = False,
    ):
        """
        Initialize validator.

        Args:
            timeout: Timeout per instance in seconds (default: 900 = 15 min)
            cache_level: Docker cache level (none/base/env/instance)
            max_workers: Number of parallel workers
            verbose: Enable verbose logging
        """
        self.timeout = timeout
        self.cache_level = cache_level
        self.max_workers = max_workers
        self.verbose = verbose

        if verbose:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)

    def validate_file(self, json_path: Union[str, Path]) -> ValidationResult:
        """
        Validate a single data point JSON file.

        Args:
            json_path: Path to JSON file containing data point

        Returns:
            ValidationResult with validation outcome
        """
        json_path = Path(json_path)
        logger.info(f"Validating data point: {json_path.name}")

        try:
            # Load data point
            data_point = self._load_data_point(json_path)

            # Validate structure
            validation_error = self._validate_structure(data_point)
            if validation_error:
                return ValidationResult(
                    instance_id=data_point.get("instance_id", "unknown"),
                    file_path=str(json_path),
                    is_valid=False,
                    error_type="structural_error",
                    error_message=validation_error,
                )

            # Convert to prediction format
            prediction = self._convert_to_prediction(data_point)

            # Run evaluation using SWE-bench harness
            try:
                eval_result = self._run_evaluation(prediction, data_point)
            except Exception as e:
                logger.error(f"Evaluation failed: {e}")
                return ValidationResult(
                    instance_id=data_point["instance_id"],
                    file_path=str(json_path),
                    is_valid=False,
                    error_type="evaluation_error",
                    error_message=str(e),
                )

            # Check test results
            return self._check_test_results(eval_result, data_point, json_path)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            return ValidationResult(
                instance_id="unknown",
                file_path=str(json_path),
                is_valid=False,
                error_type="json_error",
                error_message=f"Invalid JSON format: {str(e)}",
            )
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return ValidationResult(
                instance_id="unknown",
                file_path=str(json_path),
                is_valid=False,
                error_type="unexpected_error",
                error_message=str(e),
            )

    def validate_files(self, json_paths: List[Union[str, Path]]) -> List[ValidationResult]:
        """
        Validate multiple data point files.

        Args:
            json_paths: List of paths to JSON files

        Returns:
            List of ValidationResult objects
        """
        results = []
        for json_path in json_paths:
            result = self.validate_file(json_path)
            results.append(result)
        return results

    def validate_directory(self, dir_path: Union[str, Path]) -> List[ValidationResult]:
        """
        Validate all JSON files in a directory.

        Args:
            dir_path: Path to directory containing JSON files

        Returns:
            List of ValidationResult objects
        """
        dir_path = Path(dir_path)
        json_files = sorted(dir_path.glob("*.json"))

        if not json_files:
            logger.warning(f"No JSON files found in {dir_path}")
            return []

        logger.info(f"Found {len(json_files)} JSON files in {dir_path}")
        return self.validate_files(json_files)

    def _load_data_point(self, path: Path) -> dict:
        """Load data point from JSON file."""
        with open(path, "r") as f:
            return json.load(f)

    def _validate_structure(self, data_point: dict) -> Optional[str]:
        """
        Validate that data point has required fields.

        Returns:
            Error message if invalid, None if valid
        """
        required_fields = [
            "instance_id",
            "repo",
            "base_commit",
            "patch",
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
        ]

        missing_fields = [f for f in required_fields if f not in data_point]

        if missing_fields:
            return f"Missing required fields: {', '.join(missing_fields)}"

        # Validate FAIL_TO_PASS and PASS_TO_PASS are lists
        if not isinstance(data_point["FAIL_TO_PASS"], (list, str)):
            return "FAIL_TO_PASS must be a list or JSON string"

        if not isinstance(data_point["PASS_TO_PASS"], (list, str)):
            return "PASS_TO_PASS must be a list or JSON string"

        return None

    def _convert_to_prediction(self, data_point: dict) -> dict:
        """
        Convert data point to SWE-bench prediction format.

        Uses the golden patch from the data point.
        """
        return {
            "instance_id": data_point["instance_id"],
            "model_patch": data_point["patch"],
            "model_name_or_path": "golden_validator",
        }

    def _run_evaluation(self, prediction: dict, data_point: dict) -> dict:
        """
        Run SWE-bench evaluation harness on the prediction.

        Args:
            prediction: Prediction in SWE-bench format
            data_point: Original data point (for reference)

        Returns:
            Evaluation result dictionary
        """
        try:
            import docker
            from swebench.harness.docker_build import build_env_images, build_instance_images
            from swebench.harness.run_evaluation import run_instances
        except ImportError as e:
            raise ImportError(
                "SWE-bench library or docker not found. Install with: pip install swebench docker"
            ) from e

        logger.info(f"Running evaluation for {prediction['instance_id']}")

        # Create Docker client
        try:
            client = docker.from_env()
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Docker. Is Docker running? Error: {e}"
            ) from e

        # Build environment image (repo-level dependencies)
        logger.info(f"Building environment image for {data_point['repo']}")
        try:
            build_env_images(
                client=client,
                dataset=[data_point],
                force_rebuild=False,
                max_workers=1,
            )
        except Exception as e:
            logger.warning(f"Failed to build environment image: {e}")
            # Continue anyway, might still work

        # Build instance image (specific commit + test setup)
        logger.info(f"Building instance image for {prediction['instance_id']}")
        try:
            build_instance_images(
                client=client,
                dataset=[data_point],
                force_rebuild=False,
                max_workers=1,
                namespace="swebench",
                tag="latest",
            )
        except Exception as e:
            logger.warning(f"Failed to build instance image: {e}")
            # Continue anyway

        # Generate unique run ID
        run_id = f"validate_{prediction['instance_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Run evaluation using run_instances (plural)
        logger.info("Running evaluation in Docker container")
        try:
            run_instances(
                predictions={data_point["instance_id"]: prediction},
                instances=[data_point],
                cache_level=self.cache_level,
                clean=False,
                force_rebuild=False,
                max_workers=1,
                run_id=run_id,
                timeout=self.timeout,
                namespace="swebench",
                instance_image_tag="latest",
            )
        except Exception as e:
            logger.error(f"Evaluation execution failed: {e}", exc_info=True)
            raise RuntimeError(f"Failed to run evaluation: {e}") from e

        # Read the report from disk (run_instances writes to logs/)
        report_path = (
            Path("logs")
            / "run_evaluation"
            / run_id
            / prediction["model_name_or_path"]
            / data_point["instance_id"]
            / "report.json"
        )

        if not report_path.exists():
            raise RuntimeError(f"Evaluation report not found at {report_path}")

        logger.info(f"Reading evaluation report from {report_path}")
        with open(report_path) as f:
            full_report = json.load(f)

        # Extract the report for this specific instance
        if data_point["instance_id"] not in full_report:
            raise RuntimeError(
                f"Instance {data_point['instance_id']} not found in report"
            )

        return full_report[data_point["instance_id"]]

    def _check_test_results(
        self, eval_result: dict, data_point: dict, json_path: Path
    ) -> ValidationResult:
        """
        Check if test results indicate a valid data point.

        A data point is valid if:
        - Patch applied successfully
        - ALL FAIL_TO_PASS tests now pass
        - ALL PASS_TO_PASS tests still pass
        """
        instance_id = data_point["instance_id"]

        # Check if patch was applied
        patch_applied = eval_result.get("patch_successfully_applied", False)
        if not patch_applied:
            return ValidationResult(
                instance_id=instance_id,
                file_path=str(json_path),
                is_valid=False,
                error_type="patch_error",
                error_message="Patch failed to apply to repository",
                patch_applied=False,
            )

        # Check if evaluation resolved the issue
        resolved = eval_result.get("resolved", False)

        # Parse test results
        fail_to_pass_list = self._parse_test_list(data_point["FAIL_TO_PASS"])
        pass_to_pass_list = self._parse_test_list(data_point["PASS_TO_PASS"])

        # Get actual test results from evaluation
        tests_status = eval_result.get("tests_status", {})

        # Extract failure information
        fail_to_pass_status = tests_status.get("FAIL_TO_PASS", {})
        fail_to_pass_failures = fail_to_pass_status.get("failure", [])

        pass_to_pass_status = tests_status.get("PASS_TO_PASS", {})
        pass_to_pass_failures = pass_to_pass_status.get("failure", [])

        fail_to_pass_results = {}
        pass_to_pass_results = {}

        # If resolved is False, determine why
        if not resolved:
            error_message = self._build_error_message(
                eval_result, fail_to_pass_list, pass_to_pass_list,
                fail_to_pass_failures, pass_to_pass_failures
            )

            # Build detailed test results
            for test in fail_to_pass_list:
                fail_to_pass_results[test] = "FAILED" if test in fail_to_pass_failures else "PASSED"

            for test in pass_to_pass_list:
                pass_to_pass_results[test] = "FAILED" if test in pass_to_pass_failures else "PASSED"

            return ValidationResult(
                instance_id=instance_id,
                file_path=str(json_path),
                is_valid=False,
                error_type="test_failure",
                error_message=error_message,
                fail_to_pass_results=fail_to_pass_results,
                pass_to_pass_results=pass_to_pass_results,
                resolved=False,
                patch_applied=True,
            )

        # All tests passed
        return ValidationResult(
            instance_id=instance_id,
            file_path=str(json_path),
            is_valid=True,
            resolved=True,
            patch_applied=True,
            fail_to_pass_results={t: "PASSED" for t in fail_to_pass_list},
            pass_to_pass_results={t: "PASSED" for t in pass_to_pass_list},
        )

    def _parse_test_list(self, test_spec: Union[str, List[str]]) -> List[str]:
        """Parse test specification (can be JSON string or list)."""
        if isinstance(test_spec, str):
            try:
                return json.loads(test_spec)
            except json.JSONDecodeError:
                return [test_spec]
        return test_spec

    def _build_error_message(
        self,
        eval_result: dict,
        fail_to_pass: List[str],
        pass_to_pass: List[str],
        fail_to_pass_failures: List[str],
        pass_to_pass_failures: List[str],
    ) -> str:
        """Build detailed error message from evaluation results."""
        messages = []

        # Check for general errors
        if "error" in eval_result and eval_result["error"]:
            messages.append(f"Evaluation error: {eval_result['error']}")

        # Analyze test failures
        if fail_to_pass_failures:
            messages.append(
                f"FAIL_TO_PASS tests still failing: {len(fail_to_pass_failures)}/{len(fail_to_pass)}"
            )
            for test in fail_to_pass_failures[:3]:  # Show first 3
                messages.append(f"  - {test}")
            if len(fail_to_pass_failures) > 3:
                messages.append(f"  ... and {len(fail_to_pass_failures) - 3} more")

        if pass_to_pass_failures:
            messages.append(
                f"PASS_TO_PASS tests broken: {len(pass_to_pass_failures)}/{len(pass_to_pass)}"
            )
            for test in pass_to_pass_failures[:3]:  # Show first 3
                messages.append(f"  - {test}")
            if len(pass_to_pass_failures) > 3:
                messages.append(f"  ... and {len(pass_to_pass_failures) - 3} more")

        if not fail_to_pass_failures and not pass_to_pass_failures:
            messages.append(
                f"Tests did not pass as expected. "
                f"Expected {len(fail_to_pass)} FAIL_TO_PASS tests to pass and "
                f"{len(pass_to_pass)} PASS_TO_PASS tests to remain passing."
            )

        return " ".join(messages)
