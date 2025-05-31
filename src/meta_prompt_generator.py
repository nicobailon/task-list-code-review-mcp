"""Core module for auto-prompt generation for AI code review.

This module provides CLI support for auto-prompt generation that creates meta-prompts
for AI code review based on completed development work and project guidelines.

Supports both file output (default) and streaming output modes.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional, List


def validate_prompt(prompt: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a generated prompt for completeness and quality.

    Args:
        prompt: Prompt dictionary to validate

    Returns:
        Validation result with valid flag and error list
    """
    # Implementation will make tests pass
    raise NotImplementedError("validate_prompt function not yet implemented")


# Deferred import to avoid loading server module during module import
_generate_meta_prompt: Optional[Any] = None


def _get_generate_meta_prompt() -> Any:
    """Get generate_meta_prompt function, importing it if needed."""
    global _generate_meta_prompt
    if _generate_meta_prompt is None:
        try:
            from .server import generate_meta_prompt

            _generate_meta_prompt = generate_meta_prompt
        except ImportError:
            try:
                from server import generate_meta_prompt

                _generate_meta_prompt = generate_meta_prompt
            except (ImportError, SystemExit):
                # Import failed - implement the functionality directly
                from .generate_code_review_context import (
                    generate_code_review_context_main,
                    load_model_config,
                )

                async def generate_meta_prompt(*args: Any, **kwargs: Any) -> Dict[str, Any]:
                    """Generate meta-prompt directly without server dependency."""
                    # Get project context first
                    project_path: Optional[str] = kwargs.get("project_path")
                    scope: str = kwargs.get("scope", "recent_phase")

                    if not project_path:
                        raise ValueError("project_path is required")

                    # Generate context using existing function
                    context_file, _ = generate_code_review_context_main(
                        project_path=project_path,
                        scope=scope,
                        enable_gemini_review=False,  # Context only
                        raw_context_only=True,
                    )

                    # Read the generated context
                    with open(context_file, "r", encoding="utf-8") as f:
                        context_content = f.read()

                    # Load model config for template
                    model_config = load_model_config()
                    default_template = model_config.get("meta_prompt_template", {}).get(
                        "default",
                        "You are an expert code reviewer. Review the following code changes with extreme thoroughness: {context}",
                    )

                    # Use custom template if provided, otherwise use default
                    template = kwargs.get("custom_template", default_template)

                    # Generate the meta-prompt by filling the template
                    generated_prompt = template.format(
                        context=context_content,
                        configuration_context=context_content,  # For backward compatibility
                    )

                    return {
                        "generated_prompt": generated_prompt,
                        "template_used": (
                            "default" if not kwargs.get("custom_template") else "custom"
                        ),
                        "configuration_included": True,
                        "analysis_completed": True,
                        "context_analyzed": len(context_content),
                    }

                _generate_meta_prompt = generate_meta_prompt
    return _generate_meta_prompt


def generate_output_filename(prefix: str = "meta-prompt") -> str:
    """Generate timestamped output filename.

    Args:
        prefix: Filename prefix (default: "meta-prompt")

    Returns:
        Timestamped filename with .md extension
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{timestamp}.md"


def format_meta_prompt_output(prompt_data: Dict[str, Any]) -> str:
    """Format meta-prompt data for file output.

    Args:
        prompt_data: Generated prompt data from generate_meta_prompt

    Returns:
        Clean meta-prompt content only
    """
    # Return just the meta-prompt content without any wrapper formatting
    return prompt_data["generated_prompt"]


def format_meta_prompt_stream(prompt_data: Dict[str, Any]) -> str:
    """Format meta-prompt data for stream output.

    Args:
        prompt_data: Generated prompt data from generate_meta_prompt

    Returns:
        Just the generated prompt content for streaming
    """
    return prompt_data["generated_prompt"]


def validate_cli_arguments(args_dict: Dict[str, Any]) -> None:
    """Validate CLI arguments (same validation as MCP tool).

    Args:
        args_dict: Dictionary of parsed arguments

    Raises:
        ValueError: If validation fails
    """
    input_params = [
        args_dict.get("context_file_path"),
        args_dict.get("context_content"),
        args_dict.get("project_path"),
    ]

    provided_count = sum(1 for param in input_params if param is not None)

    if provided_count == 0:
        raise ValueError("At least one input parameter must be provided")
    elif provided_count > 1:
        raise ValueError("Only one input parameter should be provided")


async def cli_generate_meta_prompt(
    context_file_path: Optional[str] = None,
    context_content: Optional[str] = None,
    project_path: Optional[str] = None,
    scope: str = "recent_phase",
    custom_template: Optional[str] = None,
    output_dir: Optional[str] = None,
    stream_output: bool = False,
) -> Dict[str, Any]:
    """CLI wrapper for generate_meta_prompt with file/stream output options.

    Args:
        context_file_path: Path to existing context file
        context_content: Direct context content
        project_path: Project path to generate context from
        scope: Scope for context generation
        custom_template: Custom template string
        output_dir: Directory for file output (ignored if stream_output=True)
        stream_output: If True, return content directly; if False, save to file

    Returns:
        Success/error status with output_file or streamed_content
    """
    try:
        # Validate arguments (same as MCP tool)
        args_dict = {
            "context_file_path": context_file_path,
            "context_content": context_content,
            "project_path": project_path,
        }
        validate_cli_arguments(args_dict)

        # Validate file paths
        if context_file_path and not os.path.exists(context_file_path):
            return {
                "status": "error",
                "error": f"Context file not found: {context_file_path}",
            }

        # Validate output directory for file mode
        if not stream_output and output_dir:
            if not os.path.exists(output_dir):
                return {
                    "status": "error",
                    "error": f"Output directory does not exist or permission denied: {output_dir}",
                }

        # Call the underlying generate_meta_prompt function
        generate_meta_prompt = _get_generate_meta_prompt()
        prompt_result = await generate_meta_prompt(
            context_file_path=context_file_path,
            context_content=context_content,
            project_path=project_path,
            scope=scope,
            custom_template=custom_template,
        )

        if stream_output:
            # Return content directly for streaming
            return {
                "status": "success",
                "streamed_content": format_meta_prompt_stream(prompt_result),
            }
        else:
            # Save to file
            output_filename = generate_output_filename()
            if output_dir:
                output_path = os.path.join(output_dir, output_filename)
            else:
                # Default: current working directory
                output_path = os.path.join(os.getcwd(), output_filename)

            formatted_content = format_meta_prompt_output(prompt_result)

            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(formatted_content)

                return {"status": "success", "output_file": output_path}
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to write output file: {str(e)}",
                }

    except Exception as e:
        return {"status": "error", "error": str(e)}


def create_argument_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser for auto-prompt generation.

    Returns:
        Configured argument parser
    """
    parser = argparse.ArgumentParser(
        description="Generate meta-prompt for AI code review from completed development work",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
DEVELOPMENT NOTE:
  If installed package isn't working, use: python -m src.meta_prompt_generator
  
EXAMPLES:
  # Generate meta-prompt from context file (saves to current directory by default)
  generate-meta-prompt --context-file tasks/context.md
  
  # Generate meta-prompt from project (saves to current directory)
  generate-meta-prompt --project-path /path/to/project
  
  # Save to custom directory
  generate-meta-prompt --project-path . --output-dir ./prompts
  
  # Stream meta-prompt directly to stdout
  generate-meta-prompt --context-content "Direct context" --stream
  
  # Use custom template
  generate-meta-prompt --project-path . --custom-template "Focus on: {context}"
  
  # Generate from specific scope
  generate-meta-prompt --project-path . --scope full_project

OUTPUT MODES:
  Default: Saves formatted meta-prompt to timestamped .md file in current directory
  --output-dir: Override output directory
  --stream: Outputs just the meta-prompt content to stdout (no file created)

FILE FORMAT:
  Generated files include the meta-prompt, template info, and analysis summary
  aligned with existing MCP tool output formatting.
        """,
    )

    # Input source (mutually exclusive group)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--context-file", help="Path to existing code review context file (.md)"
    )
    input_group.add_argument(
        "--context-content", help="Direct context content as string"
    )
    input_group.add_argument(
        "--project-path", help="Project path to generate context from first"
    )

    # Output options
    parser.add_argument(
        "--output-dir",
        help="Directory for output file (default: current working directory)",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream meta-prompt directly to stdout instead of saving to file",
    )

    # Template options
    parser.add_argument(
        "--custom-template",
        help="Custom meta-prompt template string (overrides environment and default)",
    )
    parser.add_argument(
        "--scope",
        default="recent_phase",
        choices=["recent_phase", "full_project", "specific_phase", "specific_task"],
        help="Scope for context generation when using --project-path (default: recent_phase)",
    )

    # Utility options
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="task-list-code-review-mcp 0.3.0 (auto-prompt-generator)",
    )

    return parser


def parse_cli_arguments(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        args: List of arguments (default: sys.argv)

    Returns:
        Parsed arguments namespace
    """
    parser = create_argument_parser()
    return parser.parse_args(args if args is not None else None)


def detect_execution_mode():
    """Detect if running in development or installed mode."""
    import __main__

    if hasattr(__main__, "__file__") and __main__.__file__:
        if "src/" in str(__main__.__file__) or "-m" in sys.argv[0]:
            return "development"
    return "installed"


def main() -> None:
    """Main CLI entry point for auto-prompt generation."""
    args = None
    try:
        # Show execution mode for clarity in development
        mode = detect_execution_mode()
        if mode == "development":
            print("🔧 Development mode", file=sys.stderr)

        args = parse_cli_arguments()

        # Convert argparse namespace to function parameters
        kwargs = {
            "context_file_path": args.context_file,
            "context_content": args.context_content,
            "project_path": args.project_path,
            "scope": args.scope,
            "custom_template": args.custom_template,
            "output_dir": args.output_dir,
            "stream_output": args.stream,
        }

        # Run async function
        result = asyncio.run(cli_generate_meta_prompt(**kwargs))

        if result["status"] == "success":
            if "output_file" in result:
                print(f"Meta-prompt generated: {result['output_file']}")
            elif "streamed_content" in result:
                print(result["streamed_content"])
        else:
            print(f"Error: {result['error']}", file=sys.stderr)
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if args and hasattr(args, 'verbose') and args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


# Alias for test compatibility
def generate_meta_prompt(*args: Any, **kwargs: Any) -> Any:
    """Alias to the server's generate_meta_prompt function."""
    return _get_generate_meta_prompt()(*args, **kwargs)


# Ensure the function is available at module level
__all__ = [
    "generate_meta_prompt",
    "validate_prompt",
    "cli_generate_meta_prompt",
    "main",
]
