"""Result formatting and reporting for validation results."""

import json
from typing import List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .validator import ValidationResult


class ResultFormatter:
    """Formats validation results for display."""

    def __init__(self, console: Console = None):
        """Initialize formatter with optional Rich console."""
        self.console = console or Console()

    def format_results(self, results: List[ValidationResult], show_details: bool = True) -> None:
        """
        Format and print validation results to console.

        Args:
            results: List of validation results
            show_details: Whether to show detailed error messages
        """
        if not results:
            self.console.print("[yellow]No validation results to display[/yellow]")
            return

        # Summary statistics
        total = len(results)
        valid = sum(1 for r in results if r.is_valid)
        invalid = total - valid

        # Print summary panel
        summary_text = Text()
        summary_text.append(f"Total: {total}  ", style="bold")
        summary_text.append(f"Valid: {valid}  ", style="bold green")
        summary_text.append(f"Invalid: {invalid}", style="bold red")

        self.console.print(
            Panel(summary_text, title="[bold]Validation Summary[/bold]", border_style="blue")
        )
        self.console.print()

        # Create results table
        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("Instance ID", style="cyan", no_wrap=True)
        table.add_column("File", style="dim")
        table.add_column("Status", justify="center")
        table.add_column("Error Type", style="yellow")

        for result in results:
            status = "[green]✓ VALID[/green]" if result.is_valid else "[red]✗ INVALID[/red]"
            error_type = result.error_type or "-"

            table.add_row(
                result.instance_id,
                str(result.file_path.split("/")[-1] if "/" in result.file_path else result.file_path),
                status,
                error_type,
            )

        self.console.print(table)
        self.console.print()

        # Show detailed error messages for invalid results
        if show_details and invalid > 0:
            self.console.print("[bold]Detailed Error Messages:[/bold]")
            self.console.print()

            for result in results:
                if not result.is_valid:
                    self._print_detailed_error(result)

    def _print_detailed_error(self, result: ValidationResult) -> None:
        """Print detailed error information for a failed validation."""
        self.console.print(f"[bold red]✗ {result.instance_id}[/bold red]")
        self.console.print(f"  File: {result.file_path}")
        self.console.print(f"  Error Type: {result.error_type}")
        self.console.print(f"  Message: {result.error_message}")

        if result.fail_to_pass_results:
            self.console.print("  FAIL_TO_PASS results:")
            for test, status in result.fail_to_pass_results.items():
                status_icon = "✓" if status == "PASSED" else "✗"
                status_color = "green" if status == "PASSED" else "red"
                self.console.print(f"    [{status_color}]{status_icon}[/{status_color}] {test}: {status}")

        if result.pass_to_pass_results:
            self.console.print("  PASS_TO_PASS results:")
            for test, status in result.pass_to_pass_results.items():
                status_icon = "✓" if status == "PASSED" else "✗"
                status_color = "green" if status == "PASSED" else "red"
                self.console.print(f"    [{status_color}]{status_icon}[/{status_color}] {test}: {status}")

        self.console.print()

    def format_json(self, results: List[ValidationResult]) -> str:
        """
        Format results as JSON string.

        Args:
            results: List of validation results

        Returns:
            JSON string
        """
        return json.dumps(
            {
                "total": len(results),
                "valid": sum(1 for r in results if r.is_valid),
                "invalid": sum(1 for r in results if not r.is_valid),
                "results": [r.to_dict() for r in results],
            },
            indent=2,
        )

    def save_json(self, results: List[ValidationResult], output_path: str) -> None:
        """
        Save results to JSON file.

        Args:
            results: List of validation results
            output_path: Path to output JSON file
        """
        with open(output_path, "w") as f:
            f.write(self.format_json(results))

        self.console.print(f"[green]Results saved to {output_path}[/green]")

    def get_exit_code(self, results: List[ValidationResult]) -> int:
        """
        Get exit code based on validation results.

        Returns:
            0 if all valid, 1 if any invalid
        """
        return 0 if all(r.is_valid for r in results) else 1
