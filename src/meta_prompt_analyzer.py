"""
Meta prompt analyzer that generates meta prompts without creating intermediate files.

This module provides optimized meta prompt generation that analyzes project
structure and configuration without creating temporary context files.
"""

import os
from typing import Dict, Any, Optional, List
from pathlib import Path


def analyze_project_for_meta_prompt(
    project_path: str, scope: str = "recent_phase"
) -> Dict[str, Any]:
    """
    Analyze project structure and configuration for meta prompt generation
    without creating intermediate context files.

    Args:
        project_path: Absolute path to project root directory
        scope: Analysis scope (recent_phase, full_project, etc.)

    Returns:
        Dict containing project analysis data for meta prompt generation

    Raises:
        ValueError: If project_path is invalid
        Exception: If analysis fails
    """
    try:
        # Validate project path
        if not os.path.isabs(project_path):
            raise ValueError("project_path must be an absolute path")

        if not os.path.exists(project_path):
            raise ValueError(f"Project path does not exist: {project_path}")

        if not os.path.isdir(project_path):
            raise ValueError(f"Project path must be a directory: {project_path}")

        # Collect project analysis data without creating files
        project_data = {
            "project_path": project_path,
            "project_name": os.path.basename(os.path.abspath(project_path)),
            "scope": scope,
            "configuration_context": "",
            "file_structure_summary": "",
            "git_context": "",
            "analysis_completed": True,
        }

        # Discover project configuration (CLAUDE.md/cursor rules)
        try:
            from .generate_code_review_context import discover_project_configurations

            config_data = discover_project_configurations(project_path)

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
                        configuration_context += (
                            f"### {claude_file.file_path}:\n{claude_file.content}\n\n"
                        )

                # Add cursor rules content
                cursor_files = config_data.get("cursor_rules_files", [])
                if cursor_files:
                    configuration_context += "## Cursor Rules:\n"
                    for cursor_file in cursor_files:
                        configuration_context += (
                            f"### {cursor_file.file_path}:\n{cursor_file.content}\n\n"
                        )

                project_data["configuration_context"] = configuration_context
        except Exception as e:
            print(f"Warning: Could not discover project configuration: {e}")
            project_data["configuration_context"] = ""

        # Generate basic file structure summary (without full file tree)
        try:
            project_data["file_structure_summary"] = (
                _generate_lightweight_structure_summary(project_path)
            )
        except Exception as e:
            print(f"Warning: Could not generate file structure summary: {e}")
            project_data["file_structure_summary"] = ""

        # Get basic git context (without full diffs)
        try:
            project_data["git_context"] = _get_lightweight_git_context(project_path)
        except Exception as e:
            print(f"Warning: Could not get git context: {e}")
            project_data["git_context"] = ""

        return project_data

    except Exception as e:
        raise Exception(f"Failed to analyze project for meta prompt: {str(e)}")


def _generate_lightweight_structure_summary(project_path: str) -> str:
    """Generate a lightweight summary of project structure."""
    try:
        structure_info: List[str] = []

        # Check for common directories and files
        common_dirs = ["src", "lib", "tests", "test", "docs", "scripts", "examples"]
        common_files = [
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "Cargo.toml",
            "go.mod",
            "README.md",
            "CLAUDE.md",
        ]

        project_root = Path(project_path)

        # Count directories
        for dir_name in common_dirs:
            dir_path = project_root / dir_name
            if dir_path.exists() and dir_path.is_dir():
                # Count files in directory
                try:
                    file_count = len([f for f in dir_path.rglob("*") if f.is_file()])
                    structure_info.append(f"📁 {dir_name}/ ({file_count} files)")
                except Exception:
                    structure_info.append(f"📁 {dir_name}/")

        # Check for important files
        for file_name in common_files:
            file_path = project_root / file_name
            if file_path.exists() and file_path.is_file():
                structure_info.append(f"📄 {file_name}")

        if structure_info:
            return "Project structure:\n" + "\n".join(structure_info)
        else:
            return "Basic project structure detected"

    except Exception:
        return "Could not analyze project structure"


def _get_lightweight_git_context(project_path: str) -> str:
    """Get lightweight git context without full diffs."""
    try:
        import subprocess
        from pathlib import Path

        # Validate and resolve project path for security
        try:
            validated_path = Path(project_path).resolve()
            if not validated_path.exists() or not validated_path.is_dir():
                return "Invalid project path"
        except (OSError, ValueError):
            return "Invalid project path"

        # Check if git is available and this is a git repo
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(validated_path),
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return "Not a git repository or git not available"

        git_info: List[str] = []

        # Get current branch
        try:
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if branch_result.returncode == 0:
                branch = branch_result.stdout.strip()
                git_info.append(f"Current branch: {branch}")
        except Exception:
            pass

        # Get changed files count
        status_output = result.stdout.strip()
        if status_output:
            changed_files = len(status_output.split("\n"))
            git_info.append(f"Modified files: {changed_files}")
        else:
            git_info.append("Working directory clean")

        # Get recent commit count
        try:
            commit_result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if commit_result.returncode == 0:
                commit_count = commit_result.stdout.strip()
                git_info.append(f"Total commits: {commit_count}")
        except Exception:
            pass

        return (
            "Git context:\n" + "\n".join(git_info)
            if git_info
            else "Git repository detected"
        )

    except Exception:
        return "No git context available"


def generate_meta_prompt_from_analysis(
    project_data: Dict[str, Any],
    custom_template: Optional[str] = None,
    temperature: float = 0.5,
) -> Dict[str, Any]:
    """
    Generate meta prompt from project analysis data.

    Args:
        project_data: Project analysis data from analyze_project_for_meta_prompt
        custom_template: Optional custom template string
        temperature: Temperature for AI model (default: 0.5, range: 0.0-2.0)

    Returns:
        Dict containing generated_prompt and metadata

    Raises:
        Exception: If meta prompt generation fails
    """
    try:
        # Load meta-prompt template (priority: custom_template > env var > default)
        if custom_template:
            template = {
                "name": "Custom Meta-Prompt Template",
                "template": custom_template,
            }
            template_used = "custom"
        else:
            # Check for environment variable override
            env_template = os.getenv("META_PROMPT_TEMPLATE")
            if env_template:
                template = {
                    "name": "Environment Meta-Prompt Template",
                    "template": env_template,
                }
                template_used = "environment"
            else:
                # Load the default meta-prompt template
                from .generate_code_review_context import get_meta_prompt_template

                template = get_meta_prompt_template("default")
                if not template:
                    raise ValueError(
                        "Default meta-prompt template not found in configuration"
                    )
                template_used = "default"

        # Create context content from project analysis
        context_content = f"""# Project Analysis for {project_data['project_name']}

{project_data['configuration_context']}

{project_data['file_structure_summary']}

{project_data['git_context']}

Scope: {project_data['scope']}
"""

        # Generate meta-prompt using template
        template_content = template["template"]

        # Replace placeholders in template
        meta_prompt = template_content.format(
            context=context_content,
            configuration_context=project_data["configuration_context"],
        )

        # Use Gemini API to generate the final meta-prompt
        try:
            from .generate_code_review_context import send_to_gemini_for_review

            generated_prompt = send_to_gemini_for_review(
                context_content=meta_prompt,
                temperature=temperature,
                return_text=True,  # Return text directly instead of saving to file
                include_formatting=False,  # Return raw response without headers/footers
            )

            if not generated_prompt:
                raise Exception("Gemini API failed to generate response")

        except Exception as e:
            raise Exception(f"Failed to generate meta-prompt: {str(e)}")

        return {
            "generated_prompt": generated_prompt,
            "template_used": template_used,
            "configuration_included": len(project_data["configuration_context"]) > 0,
            "analysis_completed": True,
            "context_analyzed": len(context_content),
        }

    except Exception as e:
        raise Exception(f"Meta prompt generation failed: {str(e)}")


def generate_optimized_meta_prompt(
    project_path: str,
    scope: str = "recent_phase",
    custom_template: Optional[str] = None,
    temperature: float = 0.5,
) -> Dict[str, Any]:
    """
    Generate meta prompt with optimized single-pass analysis.

    This function analyzes the project and generates a meta prompt without
    creating any intermediate context files.

    Args:
        project_path: Absolute path to project root directory
        scope: Analysis scope
        custom_template: Optional custom template string
        temperature: Temperature for AI model (default: 0.5, range: 0.0-2.0)

    Returns:
        Dict containing generated_prompt and metadata

    Raises:
        Exception: If analysis or generation fails
    """
    try:
        # Step 1: Analyze project without creating files
        project_data = analyze_project_for_meta_prompt(project_path, scope)

        # Step 2: Generate meta prompt from analysis
        meta_prompt_result = generate_meta_prompt_from_analysis(
            project_data, custom_template, temperature
        )

        return meta_prompt_result

    except Exception as e:
        raise Exception(f"Optimized meta prompt generation failed: {str(e)}")
