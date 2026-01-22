"""Command-line interface for SWE-bench data point validator."""

import sys
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console

from .validator import SWEBenchValidator, ValidationResult
from .results import ResultFormatter


@click.command()
@click.option(
    "--file",
    type=click.Path(exists=True, path_type=Path),
    help="Validate a single JSON file",
)
@click.option(
    "--directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Validate all JSON files in directory",
)
@click.option(
    "--files",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Validate multiple specific files (can be used multiple times)",
)
@click.option(
    "--timeout",
    type=int,
    default=900,
    help="Timeout per instance in seconds (default: 900 = 15 min)",
)
@click.option(
    "--cache-level",
    type=click.Choice(["none", "base", "env", "instance"]),
    default="env",
    help="Docker cache level (default: env)",
)
@click.option(
    "--max-workers",
    type=int,
    default=1,
    help="Number of parallel workers (default: 1)",
)
@click.option(
    "--json-output",
    type=click.Path(path_type=Path),
    help="Save results to JSON file",
)
@click.option(
    "--no-details",
    is_flag=True,
    help="Hide detailed error messages",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
def main(
    file: Optional[Path],
    directory: Optional[Path],
    files: tuple,
    timeout: int,
    cache_level: str,
    max_workers: int,
    json_output: Optional[Path],
    no_details: bool,
    verbose: bool,
):
    """
    Validate SWE-bench data points using the official evaluation harness.

    Examples:

      # Validate a single file
      swe-bench-validator --file data_points/astropy__astropy-11693.json

      # Validate all files in directory
      swe-bench-validator --directory data_points/

      # Validate multiple specific files
      swe-bench-validator --files file1.json --files file2.json

      # Validate with JSON output
      swe-bench-validator --directory data_points/ --json-output results.json
    """
    console = Console()

    # Check that at least one input option is provided
    if not file and not directory and not files:
        console.print("[red]Error: Must specify --file, --directory, or --files[/red]")
        console.print("Run with --help for usage information")
        sys.exit(1)

    # Check for conflicting options
    options_count = sum([bool(file), bool(directory), bool(files)])
    if options_count > 1:
        console.print(
            "[red]Error: Cannot use --file, --directory, and --files together[/red]"
        )
        console.print("Please specify only one input method")
        sys.exit(1)

    # Create validator
    console.print("[cyan]Initializing SWE-bench validator...[/cyan]")
    validator = SWEBenchValidator(
        timeout=timeout,
        cache_level=cache_level,
        max_workers=max_workers,
        verbose=verbose,
    )

    # Collect files to validate
    files_to_validate: List[Path] = []

    if file:
        files_to_validate = [file]
        console.print(f"[cyan]Validating single file: {file.name}[/cyan]")
    elif directory:
        console.print(f"[cyan]Scanning directory: {directory}[/cyan]")
        json_files = sorted(directory.glob("*.json"))
        if not json_files:
            console.print(f"[yellow]No JSON files found in {directory}[/yellow]")
            sys.exit(0)
        files_to_validate = json_files
        console.print(f"[cyan]Found {len(files_to_validate)} JSON files[/cyan]")
    elif files:
        files_to_validate = [Path(f) for f in files]
        console.print(f"[cyan]Validating {len(files_to_validate)} files[/cyan]")

    console.print()

    # Run validation
    try:
        with console.status(
            "[bold green]Running validation (this may take several minutes)..."
        ):
            results = validator.validate_files(files_to_validate)
    except KeyboardInterrupt:
        console.print("\n[yellow]Validation interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Validation failed with error:[/red]")
        console.print(f"[red]{str(e)}[/red]")
        if verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)

    # Format and display results
    formatter = ResultFormatter(console=console)
    formatter.format_results(results, show_details=not no_details)

    # Save JSON output if requested
    if json_output:
        formatter.save_json(results, str(json_output))

    # Exit with appropriate code
    exit_code = formatter.get_exit_code(results)
    if exit_code == 0:
        console.print("[bold green]✓ All data points are valid![/bold green]")
    else:
        console.print(
            f"[bold red]✗ {sum(1 for r in results if not r.is_valid)} data point(s) failed validation[/bold red]"
        )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
