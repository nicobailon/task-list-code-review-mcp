"""
FastMCP server for generating code review context from PRDs and git changes
"""

import os
import sys
from typing import Optional, Dict, Any, List

print("🚨 DEBUG: server.py module is being loaded!")

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

try:
    from fastmcp import FastMCP  # type: ignore
    from generate_code_review_context import (
        generate_code_review_context_main as generate_review_context,
        load_model_config,
        send_to_gemini_for_review,
    )
except ImportError as e:
    print(f"Required dependencies not available: {e}", file=sys.stderr)
    sys.exit(1)

# Create FastMCP server
# FastMCP is an external library without proper type stubs
mcp = FastMCP("MCP Server - Code Review Context Generator")

# Create alias for the app to match test expectations
app = mcp

# Create alias for generate_review_context function to match test expectations
generate_context = generate_review_context


def generate_context_in_memory(
    github_pr_url: Optional[str] = None,
    project_path: Optional[str] = None,
    include_claude_memory: bool = True,
    include_cursor_rules: bool = False,
    auto_prompt_content: Optional[str] = None,
    temperature: float = 0.5,
) -> str:
    """
    Generate code review context content in memory without creating any files.

    This function extracts the core context generation logic without file I/O operations.
    It's designed for the DEFAULT behavior where no files should be created.

    Args:
        github_pr_url: GitHub PR URL for analysis
        project_path: Project directory path
        include_claude_memory: Include CLAUDE.md files in context
        include_cursor_rules: Include Cursor rules files in context
        auto_prompt_content: Generated meta-prompt content to embed
        temperature: AI temperature setting

    Returns:
        Generated context content as string
    """
    try:
        # Import here to avoid circular imports
        from github_pr_integration import get_complete_pr_analysis
        from generate_code_review_context import (
            discover_project_configurations_with_fallback,
        )
        import datetime

        if not project_path:
            project_path = os.getcwd()

        # Generate timestamp for context header
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d at %H:%M:%S")

        # Start building context content
        context_parts: List[str] = []

        # Header
        context_parts.append("# Code Review Context - Review Mode: GitHub PR Analysis")
        context_parts.append(f"*Generated on {timestamp}*")
        context_parts.append("")

        # Add user instructions (meta prompt) if provided
        if auto_prompt_content:
            context_parts.append("<user_instructions>")
            context_parts.append(auto_prompt_content)
            context_parts.append("</user_instructions>")
            context_parts.append("")

        # Project summary
        project_name = os.path.basename(os.path.abspath(project_path))
        context_parts.append("<overall_prd_summary>")
        context_parts.append(
            f"Generate comprehensive code review for recent development changes focusing on code quality, security, performance, and best practices for project: {project_name}"
        )
        context_parts.append("</overall_prd_summary>")
        context_parts.append("")

        # GitHub PR Analysis
        if github_pr_url:
            try:
                context_parts.append("## GitHub Pull Request Analysis")
                context_parts.append(f"**PR URL:** {github_pr_url}")
                context_parts.append("")

                # Get PR data
                pr_analysis = get_complete_pr_analysis(github_pr_url)
                pr_data = pr_analysis.get("pr_data", {})
                file_changes = pr_analysis.get("file_changes", {})

                # PR metadata
                context_parts.append("### Pull Request Details")
                context_parts.append(f"- **Title:** {pr_data.get('title', 'N/A')}")
                context_parts.append(f"- **Author:** {pr_data.get('author', 'N/A')}")
                context_parts.append(
                    f"- **Source Branch:** {pr_data.get('source_branch', 'N/A')}"
                )
                context_parts.append(
                    f"- **Target Branch:** {pr_data.get('target_branch', 'N/A')}"
                )
                context_parts.append(f"- **Status:** {pr_data.get('state', 'N/A')}")
                context_parts.append("")

                if pr_data.get("body"):
                    context_parts.append("### PR Description")
                    context_parts.append(pr_data["body"])
                    context_parts.append("")

                # File changes summary
                summary = file_changes.get("summary", {})
                context_parts.append("### Changes Summary")
                context_parts.append(
                    f"- **Files Changed:** {summary.get('files_changed', 0)}"
                )
                context_parts.append(
                    f"- **Lines Added:** {summary.get('total_additions', 0)}"
                )
                context_parts.append(
                    f"- **Lines Deleted:** {summary.get('total_deletions', 0)}"
                )
                context_parts.append("")

                # File changes details
                changed_files = file_changes.get("changed_files", [])
                if changed_files:
                    context_parts.append("### File Changes")
                    for file_change in changed_files:
                        context_parts.append(f"#### {file_change['path']}")
                        context_parts.append(f"**Status:** {file_change['status']}")
                        context_parts.append(
                            f"**Changes:** +{file_change.get('additions', 0)} -{file_change.get('deletions', 0)}"
                        )

                        if file_change.get("patch"):
                            context_parts.append("```diff")
                            context_parts.append(file_change["patch"])
                            context_parts.append("```")
                        context_parts.append("")

            except Exception as e:
                context_parts.append(f"⚠️ Failed to fetch PR data: {str(e)}")
                context_parts.append("")

        # Configuration discovery (CLAUDE.md, Cursor rules, etc.)
        if include_claude_memory or include_cursor_rules:
            try:
                config_data = discover_project_configurations_with_fallback(
                    project_path
                )

                if include_claude_memory and config_data.get("claude_memory_files"):
                    context_parts.append("## Project Configuration - CLAUDE.md Files")
                    for memory_file in config_data["claude_memory_files"]:
                        context_parts.append(f"### {memory_file['path']}")
                        context_parts.append("```markdown")
                        context_parts.append(memory_file["content"])
                        context_parts.append("```")
                        context_parts.append("")

                if include_cursor_rules and config_data.get("cursor_rules"):
                    context_parts.append("## Project Configuration - Cursor Rules")
                    for rule in config_data["cursor_rules"]:
                        context_parts.append(f"### {rule['path']}")
                        context_parts.append("```")
                        context_parts.append(rule["content"])
                        context_parts.append("```")
                        context_parts.append("")

            except Exception as e:
                context_parts.append(f"⚠️ Configuration discovery failed: {str(e)}")
                context_parts.append("")

        # Footer
        context_parts.append("---")
        context_parts.append(
            f"*Context generated in-memory for project: {project_name}*"
        )

        return "\n".join(context_parts)

    except Exception as e:
        # Fallback minimal context
        import datetime

        return f"""# Code Review Context - Error Recovery

⚠️ Failed to generate full context: {str(e)}

## Basic Information
- **Project Path:** {project_path or 'Unknown'}
- **GitHub PR URL:** {github_pr_url or 'Not provided'}
- **Timestamp:** {datetime.datetime.now().strftime("%Y-%m-%d at %H:%M:%S")}

Please review the code changes manually or check the error above.
"""


# generate_branch_comparison_review MCP tool removed - use generate_pr_review with GitHub PR URLs instead


@mcp.tool()
async def generate_pr_review(
    github_pr_url: Optional[str] = None,
    project_path: Optional[str] = None,
    temperature: float = 0.5,
    enable_gemini_review: bool = True,
    include_claude_memory: bool = True,
    include_cursor_rules: bool = False,
    auto_meta_prompt: bool = True,
    use_templated_instructions: bool = False,
    create_context_file: bool = False,
    raw_context_only: bool = False,
    text_output: bool = False,
) -> str:
    """Generate code review for a GitHub Pull Request with configuration discovery.

    Args:
        github_pr_url: GitHub PR URL (e.g., 'https://github.com/owner/repo/pull/123')
        project_path: Optional local project path for context (default: current directory)
        temperature: Temperature for AI model (default: 0.5, range: 0.0-2.0)
        enable_gemini_review: Enable Gemini AI code review generation (default: true)
        include_claude_memory: Include CLAUDE.md files in context (default: true)
        include_cursor_rules: Include Cursor rules files in context (default: false)
        auto_meta_prompt: Automatically generate and embed meta prompt in user_instructions (default: true)
        use_templated_instructions: Use templated backup instructions instead of generated meta prompt (default: false)
        create_context_file: Save context to file and return context content (default: false)
        raw_context_only: Return raw context content without AI processing (default: false)
        text_output: Return content directly instead of saving to file (default: false)

    Returns:
        Default (text_output=False): Success message with AI feedback file path
        If text_output=True: AI review content directly as text string (NO files created)
        If raw_context_only=True: Context content or success message with context file path
    """
    try:
        # Validate required parameters per test expectations
        if not github_pr_url:
            return "ERROR: github_pr_url is required"

        # Use current directory if project_path not provided
        if not project_path:
            project_path = os.getcwd()

        if not os.path.isabs(project_path):
            return "ERROR: project_path must be an absolute path"

        if not os.path.exists(project_path):
            return f"ERROR: Project path does not exist: {project_path}"

        if not os.path.isdir(project_path):
            return f"ERROR: Project path must be a directory: {project_path}"

        # Initialize variables to avoid unbound variable issues
        context_content = ""
        output_file = None

        # Generate GitHub PR review
        import io
        from contextlib import redirect_stdout, redirect_stderr

        # Capture stdout to detect error messages
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            # Generate meta prompt if requested and not overridden by use_templated_instructions
            auto_prompt_content = None
            if auto_meta_prompt and not use_templated_instructions:
                try:
                    # Use optimized meta prompt generation without creating intermediate files
                    from meta_prompt_analyzer import generate_optimized_meta_prompt

                    meta_prompt_result = generate_optimized_meta_prompt(
                        project_path=project_path,
                        scope="recent_phase",  # Default scope for PR reviews
                        temperature=temperature,
                    )
                    auto_prompt_content = meta_prompt_result.get("generated_prompt")
                    if not auto_prompt_content:
                        # Fall back to templated instructions instead of failing
                        auto_prompt_content = None
                except Exception:
                    # Fall back to templated instructions instead of failing
                    auto_prompt_content = None

            # Handle raw_context_only mode first (overrides other settings)
            if raw_context_only:
                # Mode: Generate and save context file (for raw context requests)
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    output_file, _gemini_file = generate_review_context(
                        project_path=project_path,
                        enable_gemini_review=False,  # Don't generate AI review for raw context
                        temperature=temperature,
                        github_pr_url=github_pr_url,
                        include_claude_memory=include_claude_memory,
                        include_cursor_rules=include_cursor_rules,
                        auto_prompt_content=auto_prompt_content,
                    )
            elif create_context_file:
                # Mode: Create context file (for backward compatibility)
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    output_file, _gemini_file = generate_review_context(
                        project_path=project_path,
                        enable_gemini_review=False,  # Don't let it create AI feedback files
                        temperature=temperature,
                        github_pr_url=github_pr_url,
                        include_claude_memory=include_claude_memory,
                        include_cursor_rules=include_cursor_rules,
                        auto_prompt_content=auto_prompt_content,
                    )
            else:
                # DEFAULT behavior: Pure in-memory context generation (NO intermediate files created)
                try:
                    # Use our pure in-memory function that creates NO files at all
                    context_content = generate_context_in_memory(
                        github_pr_url=github_pr_url,
                        project_path=project_path,
                        include_claude_memory=include_claude_memory,
                        include_cursor_rules=include_cursor_rules,
                        auto_prompt_content=auto_prompt_content,
                        temperature=temperature,
                    )

                    # No files created - context is purely in memory
                    output_file = None

                except Exception as e:
                    return f"ERROR: Failed to generate context in memory: {str(e)}"

            # Check captured output for error indicators
            captured_output = stdout_capture.getvalue()
            if "❌ Failed to fetch PR data" in captured_output:
                # Extract the specific error message
                if "Invalid GitHub token" in captured_output:
                    error_msg = "Invalid GitHub token or insufficient permissions"
                elif "PR not found" in captured_output:
                    error_msg = "PR not found"
                elif "Invalid GitHub PR URL" in captured_output:
                    error_msg = "Invalid GitHub PR URL"
                else:
                    error_msg = "Failed to fetch PR data"

                return f"ERROR: GitHub PR review failed: {error_msg}"

        except ValueError as e:
            # This catches explicit errors from the generate_review_context function
            return f"ERROR: GitHub PR review failed: {str(e)}"

        # Handle different output modes based on parameters
        try:
            # Handle raw_context_only case first (highest priority)
            if raw_context_only:
                if output_file and os.path.exists(output_file):
                    with open(output_file, "r", encoding="utf-8") as f:
                        context_content = f.read()

                    if text_output:
                        # Return context content directly WITHOUT creating any files
                        return context_content
                    else:
                        # Save context to properly named file and return success message
                        import datetime

                        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                        context_filename = (
                            f"code-review-context-github-pr-{timestamp}.md"
                        )
                        context_filepath = os.path.join(project_path, context_filename)

                        with open(context_filepath, "w", encoding="utf-8") as f:
                            f.write(context_content)

                        return f"Code review context generated successfully: {context_filename}"
                else:
                    return "ERROR: Failed to generate context for raw_context_only mode"

            # Handle create_context_file case (backward compatibility)
            elif create_context_file:
                if output_file and os.path.exists(output_file):
                    with open(output_file, "r", encoding="utf-8") as f:
                        context_content = f.read()

                    # Save context to properly named file
                    import datetime

                    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                    context_filename = f"code-review-context-github-pr-{timestamp}.md"
                    context_filepath = os.path.join(project_path, context_filename)

                    with open(context_filepath, "w", encoding="utf-8") as f:
                        f.write(context_content)

                    return f"Code review context generated successfully: {context_filename}"
                else:
                    return "ERROR: Failed to generate context file"

            # DEFAULT case: Context already generated in memory
            else:
                # For default case, context_content should already be available from in-memory generation
                if "context_content" not in locals():
                    return "ERROR: No context content available - in-memory generation failed"

                # Generate AI feedback from context
                # Determine user instructions based on auto_meta_prompt setting
                if auto_prompt_content:
                    # Use generated meta prompt as user instructions
                    user_instructions = auto_prompt_content
                else:
                    # Use templated backup instructions
                    user_instructions = """Please provide a comprehensive code review analysis for the following GitHub PR context.

Focus on:
1. Code quality and best practices
2. Security vulnerabilities  
3. Performance optimizations
4. Maintainability improvements
5. Documentation suggestions

Provide specific, actionable feedback with examples where appropriate."""

                # Generate AI review from the context with proper user instructions
                ai_review_content = send_to_gemini_for_review(
                    context_content=f"""{user_instructions}

{context_content}""",
                    temperature=temperature,
                    return_text=True,  # Return text directly instead of saving to file
                )

                # Handle return based on text_output setting
                if ai_review_content:
                    if text_output:
                        # DEFAULT: Return AI content directly (NO files created)
                        return ai_review_content
                    else:
                        # text_output=False: Save to file and return success message
                        import datetime

                        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                        feedback_filename = f"pr-review-feedback-{timestamp}.md"
                        feedback_filepath = os.path.join(
                            project_path, feedback_filename
                        )

                        with open(feedback_filepath, "w", encoding="utf-8") as f:
                            f.write(ai_review_content)

                        return f"AI code review generated successfully: {feedback_filename}"
                else:
                    return "ERROR: Failed to generate AI review content"

        except Exception as e:
            return f"ERROR: Failed to generate AI review from context: {str(e)}"

        # If we get here, context generation failed
        return f"ERROR: Failed to generate context from GitHub PR: {github_pr_url}"

    except Exception as e:
        return f"ERROR: Failed to generate GitHub PR review: {str(e)}"


@mcp.tool()
def generate_code_review_context(
    project_path: str,
    scope: str = "recent_phase",
    phase_number: Optional[str] = None,
    task_number: Optional[str] = None,
    current_phase: Optional[str] = None,
    output_path: Optional[str] = None,
    enable_gemini_review: bool = False,
    temperature: float = 0.5,
    include_claude_memory: bool = True,
    include_cursor_rules: bool = False,
    raw_context_only: bool = False,
    text_output: bool = True,
    auto_meta_prompt: bool = True,
) -> str:
    """Generate code review context with flexible scope options and configuration discovery.

    Args:
        project_path: Absolute path to project root directory
        scope: Review scope - 'recent_phase' (default), 'full_project', 'specific_phase', 'specific_task'
        phase_number: Phase number for specific_phase scope (e.g., '2.0')
        task_number: Task number for specific_task scope (e.g., '1.2')
        current_phase: Legacy phase override (e.g., '2.0'). If not provided, auto-detects from task list
        output_path: Custom output file path. If not provided, uses default timestamped path
        enable_gemini_review: Enable Gemini AI code review generation (default: true)
        temperature: Temperature for AI model (default: 0.5, range: 0.0-2.0)
        include_claude_memory: Include CLAUDE.md files in context (default: true)
        include_cursor_rules: Include Cursor rules files in context (default: false)
        raw_context_only: Exclude default AI review instructions (default: false)
        text_output: Return text content directly instead of file info (default: true for AI agent chaining)
        auto_meta_prompt: Automatically generate and embed meta prompt in user_instructions (default: true)

    Returns:
        If text_output=True: Generated context content as text string
        If text_output=False: Success message with file paths (legacy mode)
    """

    # Comprehensive error handling to prevent TaskGroup issues
    try:
        # Validate project_path
        if not project_path:
            return "ERROR: project_path is required"

        if not os.path.isabs(project_path):
            return "ERROR: project_path must be an absolute path"

        if not os.path.exists(project_path):
            return f"ERROR: Project path does not exist: {project_path}"

        if not os.path.isdir(project_path):
            return f"ERROR: Project path must be a directory: {project_path}"

        # Handle temperature: MCP parameter takes precedence, then env var, then default 0.5
        if temperature == 0.5:  # Default value, check if env var should override
            temperature = float(os.getenv("GEMINI_TEMPERATURE", "0.5"))

        # Load model config to show capabilities info
        config = load_model_config()
        model_config = os.getenv("GEMINI_MODEL", config["defaults"]["model"])
        # Resolve model aliases to actual API model names
        resolved_model = config["model_aliases"].get(model_config, model_config)

        # Detect capabilities
        supports_url_context = (
            resolved_model in config["model_capabilities"]["url_context_supported"]
        )
        supports_grounding = (
            "gemini-1.5" in resolved_model
            or "gemini-2.0" in resolved_model
            or "gemini-2.5" in resolved_model
        )
        supports_thinking = (
            resolved_model in config["model_capabilities"]["thinking_mode_supported"]
        )

        # Check if features are actually enabled (considering disable flags)
        disable_url_context = (
            os.getenv("DISABLE_URL_CONTEXT", "false").lower() == "true"
        )
        disable_grounding = os.getenv("DISABLE_GROUNDING", "false").lower() == "true"
        disable_thinking = os.getenv("DISABLE_THINKING", "false").lower() == "true"

        actual_capabilities: List[str] = []
        if supports_url_context and not disable_url_context:
            actual_capabilities.append("URL context")
        if supports_grounding and not disable_grounding:
            actual_capabilities.append("web grounding")
        if supports_thinking and not disable_thinking:
            actual_capabilities.append("thinking mode")

        # Generate meta prompt if requested
        auto_prompt_content = None
        if auto_meta_prompt:
            try:
                # Use optimized meta prompt generation without creating intermediate files
                from meta_prompt_analyzer import generate_optimized_meta_prompt

                meta_prompt_result = generate_optimized_meta_prompt(
                    project_path=project_path, scope=scope
                )
                auto_prompt_content = meta_prompt_result.get("generated_prompt")
                if not auto_prompt_content:
                    return "ERROR: Meta prompt generation failed - no content generated"
            except Exception as e:
                return f"ERROR: Meta prompt generation failed: {str(e)}"

        # Generate review context using enhanced logic
        try:
            # Call the main function which now returns a tuple (context_file, gemini_file)
            output_file, gemini_file = generate_review_context(
                project_path=project_path,
                phase=current_phase,  # Legacy parameter
                output=output_path,
                enable_gemini_review=enable_gemini_review,
                scope=scope,
                phase_number=phase_number,
                task_number=task_number,
                temperature=temperature,
                include_claude_memory=include_claude_memory,
                include_cursor_rules=include_cursor_rules,
                raw_context_only=raw_context_only,
                auto_prompt_content=auto_prompt_content,
            )

            # Return response based on text_output setting
            if text_output:
                # Return text content directly for AI agent chaining
                try:
                    with open(output_file, "r", encoding="utf-8") as f:
                        context_content = f.read()
                    return context_content
                except Exception as e:
                    return f"ERROR: Could not read generated context file: {str(e)}"
            else:
                # Return user-friendly message with file paths (legacy mode)
                response_parts: List[str] = []
                response_parts.append(
                    f"🔍 Analyzed project: {os.path.basename(os.path.abspath(project_path))}"
                )
                response_parts.append(f"📊 Review scope: {scope}")
                if enable_gemini_review:
                    response_parts.append(f"🌡️ AI temperature: {temperature}")

                response_parts.append(
                    f"\n📝 Generated review context: {os.path.basename(output_file)}"
                )

                if enable_gemini_review:
                    response_parts.append(f"\n🤖 Using Gemini model: {resolved_model}")
                    if actual_capabilities:
                        response_parts.append(
                            f"✨ Enhanced features enabled: {', '.join(actual_capabilities)}"
                        )
                    else:
                        response_parts.append(
                            "⚡ Standard features: Basic text generation"
                        )

                    if gemini_file:
                        response_parts.append(
                            f"✅ AI code review completed: {os.path.basename(gemini_file)}"
                        )
                    else:
                        response_parts.append("⚠️ AI code review failed or was skipped")

                # List generated files
                files_generated: List[str] = [os.path.basename(output_file)]
                if gemini_file:
                    files_generated.append(os.path.basename(gemini_file))
                response_parts.append("\n🎉 Code review process completed!")
                response_parts.append(
                    f"📄 Files generated: {', '.join(files_generated)}"
                )

                # Add file paths for reference
                response_parts.append("\nOutput files:")
                response_parts.append(f"- Context: {output_file}")
                if gemini_file:
                    response_parts.append(f"- AI Review: {gemini_file}")

                return "\n".join(response_parts)

        except Exception as e:
            return f"ERROR: Error generating code review context: {str(e)}"

    except Exception as e:
        # Catch-all to ensure no exceptions escape the tool function
        return f"ERROR: Unexpected error: {str(e)}"


@mcp.tool()
def generate_ai_code_review(
    context_file_path: Optional[str] = None,
    context_content: Optional[str] = None,
    project_path: Optional[str] = None,
    scope: str = "recent_phase",
    phase_number: Optional[str] = None,
    task_number: Optional[str] = None,
    output_path: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.5,
    custom_prompt: Optional[str] = None,
    text_output: bool = True,
    auto_meta_prompt: bool = True,
    include_claude_memory: bool = True,
    include_cursor_rules: bool = False,
) -> str:
    """Generate AI-powered code review from context file, content, or project analysis.

    Args:
        context_file_path: Path to existing code review context file (.md)
        context_content: Direct context content (for AI agent chaining)
        project_path: Project path for direct analysis (generates context internally)
        scope: Review scope when using project_path - 'recent_phase', 'full_project', 'specific_phase', 'specific_task'
        phase_number: Phase number for specific_phase scope
        task_number: Task number for specific_task scope
        output_path: Custom output file path for AI review. If not provided, uses default timestamped path
        model: Optional Gemini model name (e.g., 'gemini-2.0-flash-exp', 'gemini-1.5-pro')
        temperature: Temperature for AI model (default: 0.5, range: 0.0-2.0)
        custom_prompt: Optional custom AI prompt to override default instructions
        text_output: Return text content directly instead of file info (default: true for AI agent chaining)
        auto_meta_prompt: Automatically generate and embed meta prompt (default: true)
        include_claude_memory: Include CLAUDE.md files in context (default: true)
        include_cursor_rules: Include Cursor rules files in context (default: false)

    Returns:
        If text_output=True: Generated AI review content as text string
        If text_output=False: Success message with file paths (legacy mode)
    """

    # Import the required function
    from generate_code_review_context import send_to_gemini_for_review

    # Comprehensive error handling
    try:
        # 🔍 DEBUG: Check if generate_ai_code_review is being called
        if project_path and "nicobailon" in str(project_path):
            return f"🔍 DEBUG: generate_ai_code_review() WAS CALLED with project_path={project_path}"

        # Validate input parameters - exactly one should be provided
        provided_params = sum(
            [
                context_file_path is not None,
                context_content is not None,
                project_path is not None,
            ]
        )

        if provided_params == 0:
            raise ValueError(
                "One of context_file_path, context_content, or project_path is required"
            )
        elif provided_params > 1:
            raise ValueError(
                "Only one of context_file_path, context_content, or project_path should be provided"
            )

        # Validate context_file_path if provided
        if context_file_path is not None:
            if not os.path.isabs(context_file_path):
                return "ERROR: context_file_path must be an absolute path"

            if not os.path.exists(context_file_path):
                return f"ERROR: Context file does not exist: {context_file_path}"

            if not os.path.isfile(context_file_path):
                return f"ERROR: Context file path must be a file: {context_file_path}"

        # Validate context_content if provided
        if context_content is not None:
            if not context_content.strip():
                return "ERROR: context_content cannot be empty"

        # Validate project_path if provided
        if project_path is not None:
            if not os.path.isabs(project_path):
                return "ERROR: project_path must be an absolute path"

            if not os.path.exists(project_path):
                return f"ERROR: Project path does not exist: {project_path}"

            if not os.path.isdir(project_path):
                return f"ERROR: Project path must be a directory: {project_path}"

        # Handle temperature: MCP parameter takes precedence, then env var, then default 0.5
        if temperature == 0.5:  # Default value, check if env var should override
            temperature = float(os.getenv("GEMINI_TEMPERATURE", "0.5"))

        # Generate AI review
        try:
            if context_file_path is not None:
                # Read context file content
                try:
                    with open(context_file_path, "r", encoding="utf-8") as f:
                        file_context_content = f.read().strip()
                except Exception as e:
                    return f"ERROR: Could not read context file: {str(e)}"

                # Generate AI review using Gemini directly
                if custom_prompt:
                    review_content = f"{custom_prompt}\n\n{file_context_content}"
                else:
                    # Use default AI review instructions
                    review_content = f"""Please provide a comprehensive code review analysis for the following code context:

{file_context_content}

Focus on:
1. Code quality and best practices
2. Security vulnerabilities
3. Performance optimizations
4. Maintainability improvements
5. Documentation suggestions

Provide specific, actionable feedback with code examples where appropriate."""

                # Generate AI review using Gemini
                ai_review_content = send_to_gemini_for_review(
                    context_content=review_content,
                    temperature=temperature,
                    model=model,
                    return_text=True,  # Return text directly instead of saving to file
                )

                if not ai_review_content:
                    return "ERROR: Gemini API failed to generate AI review"

                # Create AI review file if text_output=False, otherwise keep as None
                if not text_output:
                    # Generate timestamped filename for AI review
                    import datetime

                    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                    if output_path:
                        # Use custom output path if provided
                        output_file = output_path
                    else:
                        # Use default naming convention in context file directory
                        context_dir = os.path.dirname(context_file_path)
                        output_file = os.path.join(
                            context_dir, f"code-review-ai-feedback-{timestamp}.md"
                        )

                    # Save AI review content to file
                    try:
                        with open(output_file, "w", encoding="utf-8") as f:
                            f.write(ai_review_content)
                    except Exception as e:
                        return f"ERROR: Could not write AI review file: {str(e)}"
                else:
                    # Set output_file to None since we didn't create a file
                    output_file = None

            elif context_content is not None:
                # Handle direct context content mode
                if custom_prompt:
                    review_content = f"{custom_prompt}\n\n{context_content}"
                else:
                    # Use default AI review instructions
                    review_content = f"""Please provide a comprehensive code review analysis for the following code context:

{context_content}

Focus on:
1. Code quality and best practices
2. Security vulnerabilities
3. Performance optimizations
4. Maintainability improvements
5. Documentation suggestions

Provide specific, actionable feedback with code examples where appropriate."""

                # Generate AI review using Gemini
                ai_review_content = send_to_gemini_for_review(
                    context_content=review_content,
                    temperature=temperature,
                    model=model,
                    return_text=True,  # Return text directly instead of saving to file
                )

                if not ai_review_content:
                    return "ERROR: Gemini API failed to generate AI review"

                # Create AI review file if text_output=False, otherwise keep as None
                if not text_output:
                    # Generate timestamped filename for AI review
                    import datetime

                    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                    if output_path:
                        # Use custom output path if provided
                        output_file = output_path
                    else:
                        # Use default naming convention in current directory
                        output_file = f"code-review-ai-feedback-{timestamp}.md"

                    # Save AI review content to file
                    try:
                        with open(output_file, "w", encoding="utf-8") as f:
                            f.write(ai_review_content)
                    except Exception as e:
                        return f"ERROR: Could not write AI review file: {str(e)}"
                else:
                    # Set output_file to None since we didn't create a file
                    output_file = None

            else:
                # Generate context internally from project_path and clean up intermediate files
                from generate_code_review_context import (
                    generate_code_review_context_main,
                )
                from meta_prompt_analyzer import generate_optimized_meta_prompt
                import tempfile

                # Generate context internally with temporary file cleanup
                temp_context_file = None
                try:
                    # Generate meta prompt if enabled
                    if auto_meta_prompt and project_path:
                        meta_prompt_result = generate_optimized_meta_prompt(
                            project_path=project_path,
                            scope=scope,
                            temperature=temperature,
                        )
                        auto_prompt_content = meta_prompt_result.get("generated_prompt")
                    else:
                        auto_prompt_content = None

                    # Create temporary file for context generation
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".md", delete=False
                    ) as temp_file:
                        temp_context_file = temp_file.name

                    # Generate context using existing function with temporary file
                    context_file, _gemini_file = generate_code_review_context_main(
                        project_path=project_path,
                        scope=scope,
                        phase_number=phase_number,
                        task_number=task_number,
                        output=temp_context_file,
                        enable_gemini_review=False,  # We'll generate AI review ourselves
                        include_claude_memory=include_claude_memory,
                        include_cursor_rules=include_cursor_rules,
                        raw_context_only=False,
                        auto_prompt_content=auto_prompt_content,
                        temperature=temperature,
                    )

                    # Read the generated context content
                    with open(context_file, "r", encoding="utf-8") as f:
                        internal_context = f.read()

                    # Clean up the temporary context file
                    try:
                        os.unlink(context_file)
                        if temp_context_file and os.path.exists(temp_context_file):
                            os.unlink(temp_context_file)
                    except Exception:
                        pass  # Ignore cleanup errors

                    if not internal_context:
                        return "ERROR: Failed to generate context from project"

                    # Generate AI review using the internal context
                    if custom_prompt:
                        review_content = f"{custom_prompt}\n\n{internal_context}"
                    else:
                        # Use default AI review instructions
                        review_content = f"""Please provide a comprehensive code review analysis for the following code context:

{internal_context}

Focus on:
1. Code quality and best practices
2. Security vulnerabilities
3. Performance optimizations
4. Maintainability improvements
5. Documentation suggestions

Provide specific, actionable feedback with code examples where appropriate."""

                    # Generate AI review using Gemini
                    ai_review_content = send_to_gemini_for_review(
                        context_content=review_content,
                        temperature=temperature,
                        model=model,
                        return_text=True,  # Return text directly instead of saving to file
                    )

                    if not ai_review_content:
                        return "ERROR: Gemini API failed to generate AI review"

                    # Create AI review file if text_output=False, otherwise keep as None
                    if not text_output:
                        # Generate timestamped filename for AI review
                        import datetime

                        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                        if output_path:
                            # Use custom output path if provided
                            output_file = output_path
                        else:
                            # Use default naming convention in project directory
                            if project_path:
                                output_file = os.path.join(
                                    project_path,
                                    f"code-review-ai-feedback-{timestamp}.md",
                                )
                            else:
                                output_file = f"code-review-ai-feedback-{timestamp}.md"

                        # Save AI review content to file
                        try:
                            with open(output_file, "w", encoding="utf-8") as f:
                                f.write(ai_review_content)
                        except Exception as e:
                            return f"ERROR: Could not write AI review file: {str(e)}"
                    else:
                        # Set output_file to None since we didn't create a persistent file
                        output_file = None

                except Exception as e:
                    # Clean up any temporary files on error
                    if temp_context_file and os.path.exists(temp_context_file):
                        try:
                            os.unlink(temp_context_file)
                        except Exception:
                            pass
                    return f"ERROR: Failed to generate context from project: {str(e)}"

            # Return response based on text_output setting
            if text_output:
                # Return AI review content directly for AI agent chaining
                return ai_review_content
            else:
                # Return user-friendly message with file paths (legacy mode)
                if output_file:
                    return f"Successfully generated AI code review: {output_file}\n\n{ai_review_content}"
                else:
                    return f"Successfully generated AI code review from content:\n\n{ai_review_content}"

        except Exception as e:
            return f"ERROR: Error generating AI code review: {str(e)}"

    except Exception as e:
        # Catch-all to ensure no exceptions escape the tool function
        return f"ERROR: Unexpected error: {str(e)}"


@mcp.tool()
async def debug_mcp_params(
    test_bool: bool = False, test_string: str = "default"
) -> str:
    """Debug tool to see what parameters MCP is actually passing."""
    return f"🔍 MCP DEBUG: test_bool={test_bool}, test_string='{test_string}'"


@mcp.tool()
async def generate_meta_prompt(
    context_file_path: Optional[str] = None,
    context_content: Optional[str] = None,
    project_path: Optional[str] = None,
    scope: str = "recent_phase",
    custom_template: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate meta-prompt for AI code review based on completed work analysis.

    This MCP tool analyzes completed development work and project guidelines to create
    tailored meta-prompts that guide AI agents in providing contextually relevant code reviews.

    Template Priority (highest to lowest):
    1. custom_template parameter - Direct template string via MCP tool call
    2. META_PROMPT_TEMPLATE env var - Template via MCP client config (e.g., Claude Code/Cursor)
    3. Default template - From model_config.json

    MCP Client Environment Configuration Example:
    {
      "mcpServers": {
        "task-list-reviewer": {
          "command": "uvx",
          "args": ["task-list-code-review-mcp"],
          "env": {
            "GEMINI_API_KEY": "your_key_here",
            "META_PROMPT_TEMPLATE": "Your custom template with {configuration_context} and {context} placeholders"
          }
        }
      }
    }

    Args:
        context_file_path: Path to existing context file to analyze
        context_content: Direct context content to analyze
        project_path: Project path to generate context from first
        scope: Scope for context generation when using project_path
        custom_template: Custom meta-prompt template string (overrides environment and default)

    Returns:
        Dict containing generated_prompt, template_used, configuration_included, analysis_completed, and context_analyzed

    Raises:
        ValueError: If input validation fails
        FileNotFoundError: If context file doesn't exist
        Exception: If Gemini API fails
    """
    try:
        # Input validation - exactly one parameter should be provided
        provided_params = sum(
            [
                context_file_path is not None,
                context_content is not None,
                project_path is not None,
            ]
        )

        if provided_params == 0:
            raise ValueError("At least one input parameter must be provided")
        elif provided_params > 1:
            raise ValueError("Only one input parameter should be provided")

        # Initialize variables to avoid unbound variable issues
        content = ""
        analyzed_length = 0
        project_for_config = None

        # Get context content based on input type
        if context_content is not None:
            # Direct content provided
            content = context_content.strip()
            if not content:
                raise ValueError("Context content cannot be empty")
            analyzed_length = len(content)
            project_for_config = None  # No project path available for config discovery

        elif context_file_path is not None:
            # Read from file path
            if not os.path.exists(context_file_path):
                raise FileNotFoundError(f"Context file not found: {context_file_path}")

            with open(context_file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()

            if not content:
                raise ValueError("Context content cannot be empty")
            analyzed_length = len(content)
            project_for_config = os.path.dirname(
                context_file_path
            )  # Use parent directory for config discovery

        elif project_path is not None:
            # Generate context first, then analyze
            from generate_code_review_context import (
                generate_code_review_context_main as generate_context,
            )

            # Generate context with raw_context_only=True for clean prompt generation
            context_result = generate_context(
                project_path=project_path,
                scope=scope,
                enable_gemini_review=False,  # Don't need AI review, just context
                raw_context_only=True,  # Get raw context without AI instructions
            )

            # Read the generated context file
            if context_result and len(context_result) >= 1:
                context_file = context_result[0]
                with open(context_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                analyzed_length = len(content)
                project_for_config = project_path
            else:
                raise Exception("Failed to generate context from project path")

        # Discover project configuration (CLAUDE.md/cursor rules)
        configuration_context = ""
        if project_for_config:
            try:
                from generate_code_review_context import discover_project_configurations

                config_data = discover_project_configurations(project_for_config)

                if config_data and (
                    config_data.get("claude_memory_files")
                    or config_data.get("cursor_rules_files")
                ):
                    configuration_context = "\n# PROJECT CONFIGURATION GUIDELINES\n\n"

                    # Add CLAUDE.md content
                    claude_files = config_data.get("claude_memory_files", [])
                    if claude_files:
                        configuration_context += "## CLAUDE.md Guidelines:\n"
                        for claude_file in claude_files:
                            configuration_context += f"### {claude_file.file_path}:\n{claude_file.content}\n\n"

                    # Add cursor rules content
                    cursor_files = config_data.get("cursor_rules_files", [])
                    if cursor_files:
                        configuration_context += "## Cursor Rules:\n"
                        for cursor_file in cursor_files:
                            configuration_context += f"### {cursor_file.file_path}:\n{cursor_file.content}\n\n"

            except Exception as e:
                print(f"Warning: Could not discover project configuration: {e}")
                configuration_context = ""

        # Load meta-prompt template (priority: custom_template > env var > default)
        if custom_template:
            # Use custom template provided by MCP client via parameter
            template = {
                "name": "Custom Meta-Prompt Template",
                "template": custom_template,
            }
            template_used = "custom"
        else:
            # Check for environment variable override
            env_template = os.getenv("META_PROMPT_TEMPLATE")
            if env_template:
                # Use template from environment variable (MCP client config)
                template = {
                    "name": "Environment Meta-Prompt Template",
                    "template": env_template,
                }
                template_used = "environment"
            else:
                # Load the default meta-prompt template
                from generate_code_review_context import get_meta_prompt_template

                template = get_meta_prompt_template("default")
                if not template:
                    raise ValueError(
                        "Default meta-prompt template not found in configuration"
                    )
                template_used = "default"

        # Handle large content (truncate if needed to avoid API limits)
        MAX_CONTEXT_SIZE = 80000  # Leave room for template and config content
        if len(content) > MAX_CONTEXT_SIZE:
            content = content[:MAX_CONTEXT_SIZE]
            analyzed_length = MAX_CONTEXT_SIZE

        # Generate meta-prompt using template
        template_content = template["template"]

        # Replace placeholders in template
        meta_prompt = template_content.format(
            context=content, configuration_context=configuration_context
        )

        # Use Gemini API to generate the final meta-prompt
        try:
            from generate_code_review_context import send_to_gemini_for_review

            # Use enhanced Gemini function to get response text directly
            generated_prompt = send_to_gemini_for_review(
                context_content=meta_prompt,
                temperature=0.3,  # Lower temperature for more consistent meta-prompt generation
                return_text=True,  # Return text directly instead of saving to file
                include_formatting=False,  # Return raw response without headers/footers for auto-prompt
            )

            if not generated_prompt:
                raise Exception("Gemini API failed to generate response")

        except Exception as e:
            raise Exception(f"Failed to generate meta-prompt: {str(e)}")

        return {
            "generated_prompt": generated_prompt,
            "template_used": template_used,
            "configuration_included": len(configuration_context) > 0,
            "analysis_completed": True,
            "context_analyzed": analyzed_length,
        }

    except Exception:
        # Re-raise with proper error handling for tests
        raise


def get_mcp_tools():
    """Get list of available MCP tools for testing."""
    return [
        "generate_code_review_context",
        "generate_ai_code_review",
        "generate_pr_review",
        "generate_meta_prompt",
    ]


def get_mcp_tool_schema(tool_name: str):
    """Get MCP tool schema for testing."""
    if tool_name == "generate_meta_prompt":
        return {
            "parameters": {
                "properties": {
                    "context_file_path": {"type": "string"},
                    "context_content": {"type": "string"},
                    "project_path": {"type": "string"},
                    "scope": {"type": "string", "default": "recent_phase"},
                    "custom_template": {"type": "string"},
                }
            }
        }
    else:
        raise ValueError(f"Unknown tool: {tool_name}")


def main():
    """Entry point for uvx execution"""
    # FastMCP handles all the server setup, protocol, and routing
    # Default transport is stdio (best for local tools and command-line scripts)
    mcp.run()


if __name__ == "__main__":
    main()
