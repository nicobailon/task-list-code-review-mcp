#!/usr/bin/env python3
"""
Generate code review context by parsing PRD, task lists, and git changes.

The script should:
1. Read PRD files (prd-*.md) from /tasks/ directory
2. Read task list files (tasks-prd-*.md) from /tasks/ directory
3. Parse current phase and progress from task list
4. Extract or generate PRD summary (2-3 sentences)
5. Get git diff for changed files
6. Generate ASCII file tree
7. Format everything into markdown template
8. Save to /tasks/review-context-{timestamp}.md
"""

import re
import os
import sys
import subprocess
import argparse
import glob
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, cast, TypedDict, TypeGuard
from dataclasses import dataclass
import logging

# Git branch comparison functionality removed - use GitHub PR integration instead

# Import GitHub PR integration functionality
try:
    from .github_pr_integration import parse_github_pr_url, get_complete_pr_analysis
except ImportError:
    try:
        from github_pr_integration import parse_github_pr_url, get_complete_pr_analysis
    except ImportError:
        print("⚠️  GitHub PR integration not available")
        parse_github_pr_url = None
        get_complete_pr_analysis = None

# Note: AI code review functionality import disabled to avoid circular import
# The generate_ai_code_review function is available via MCP server tools
# Load environment variables from .env file (optional)
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:
    pass  # dotenv not available, continue without it

# Optional Gemini import
genai: Any = None
types: Any = None

try:
    import google.genai as genai  # type: ignore
    from google.genai import types  # type: ignore
except ImportError:
    pass

GEMINI_AVAILABLE = genai is not None

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Type definitions for task list data structures
class SubtaskData(TypedDict):
    number: str
    description: str
    complete: bool


class PhaseData(TypedDict):
    number: str
    description: str
    subtasks: List[SubtaskData]
    subtasks_complete: bool
    subtasks_completed: List[str]


class TaskData(TypedDict, total=False):
    phases: List[PhaseData]
    current_phase_number: str
    current_phase_description: str
    previous_phase_completed: str
    next_phase: str
    subtasks_completed: List[str]


def is_phase_data(obj: Any) -> TypeGuard[PhaseData]:
    """Type guard to check if an object is a valid PhaseData."""
    return isinstance(obj, dict) and "number" in obj and isinstance(obj["number"], str)


def load_model_config() -> Dict[str, Any]:
    """Load model configuration from JSON file with fallback defaults."""
    config_path = os.path.join(os.path.dirname(__file__), "model_config.json")

    # Default configuration as fallback
    default_config = {
        "model_aliases": {
            "gemini-2.5-pro": "gemini-2.5-pro-preview-05-06",
            "gemini-2.5-flash": "gemini-2.5-flash-preview-05-20",
        },
        "model_capabilities": {
            "url_context_supported": [
                "gemini-2.5-pro-preview-05-06",
                "gemini-2.5-flash-preview-05-20",
                "gemini-2.0-flash",
                "gemini-2.0-flash-live-001",
                "gemini-2.5-flash",
            ],
            "thinking_mode_supported": [
                "gemini-2.5-pro-preview-05-06",
                "gemini-2.5-flash-preview-05-20",
            ],
        },
        "defaults": {
            "model": "gemini-2.0-flash",
            "summary_model": "gemini-2.0-flash-lite",
            "default_prompt": "Generate comprehensive code review for recent development changes focusing on code quality, security, performance, and best practices.",
        },
    }

    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
                # Merge with defaults to ensure all keys exist
                for key in default_config:
                    if key not in config:
                        config[key] = default_config[key]
                return config
        else:
            logger.warning(
                f"Model config file not found at {config_path}, using defaults"
            )
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load model config: {e}, using defaults")

    return default_config


def load_meta_prompt_templates(
    config_path: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Load meta-prompt templates from model_config.json with robust error handling.

    Args:
        config_path: Optional path to config file (defaults to model_config.json)

    Returns:
        Dictionary of validated meta-prompt templates

    Raises:
        ValueError: If config file is invalid or templates fail validation
        FileNotFoundError: If specified config file doesn't exist
    """
    try:
        if config_path is None:
            config = load_model_config()
        else:
            # Validate config file exists and is readable
            if not os.path.exists(config_path):
                raise FileNotFoundError(f"Config file not found: {config_path}")

            if not os.access(config_path, os.R_OK):
                raise PermissionError(f"Config file not readable: {config_path}")

            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config: Any = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in config file {config_path}: {e}")
            except UnicodeDecodeError as e:
                raise ValueError(f"Config file encoding error {config_path}: {e}")
            except IOError as e:
                raise ValueError(f"Failed to read config file {config_path}: {e}")

        # Validate config structure
        if not isinstance(config, dict):
            raise ValueError("Config file must contain a JSON object")

        # Get meta_prompt_templates section, fallback to empty dict
        config_dict = cast(Dict[str, Any], config)
        templates: Dict[str, Any] = config_dict.get("meta_prompt_templates", {})

        # Validate each template with detailed error reporting
        validation_errors: List[str] = []
        for template_name, template_data in templates.items():
            try:
                validation_result = validate_meta_prompt_template(template_data)
                if not validation_result["valid"]:
                    validation_errors.append(
                        f"Template '{template_name}': {', '.join(validation_result['errors'])}"
                    )
            except Exception as e:
                validation_errors.append(
                    f"Template '{template_name}': Validation failed - {e}"
                )

        if validation_errors:
            raise ValueError(
                "Template validation failed:\n- " + "\n- ".join(validation_errors)
            )

        return templates

    except Exception as e:
        # Log the error for debugging while preserving the original exception
        logger.warning(f"Failed to load meta-prompt templates: {e}")
        raise


def validate_meta_prompt_template(template: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate meta-prompt template structure and content with comprehensive edge case handling.

    Args:
        template: Template dictionary to validate

    Returns:
        Dictionary with 'valid', 'errors', and 'placeholders' keys
    """
    errors: List[str] = []

    # Handle None or non-dict input
    if template is None:
        errors.append("Template cannot be None")
        return {"valid": False, "errors": errors, "placeholders": []}

    # At this point template is guaranteed to be a dict by type annotation

    # Check required fields with proper None handling
    required_fields = ["name", "template"]
    for field in required_fields:
        if field not in template:
            errors.append(f"Missing required field: {field}")
        elif template[field] is None:
            errors.append(f"Field '{field}' cannot be None")
        elif isinstance(template[field], str) and not template[field].strip():
            errors.append(f"Field '{field}' cannot be empty or whitespace-only")
        elif not template[field]:  # handles empty containers
            errors.append(f"Field '{field}' cannot be empty")

    # Validate name field with edge cases
    if "name" in template and template["name"] is not None:
        if not isinstance(template["name"], str):
            errors.append("Field 'name' must be a string")
        elif len(template["name"].strip()) == 0:
            errors.append("Template name cannot be empty or whitespace-only")
        elif len(template["name"]) > 100:
            errors.append("Template name is too long (maximum 100 characters)")

    # Validate template field with comprehensive checks
    if "template" in template and template["template"] is not None:
        if not isinstance(template["template"], str):
            errors.append("Field 'template' must be a string")
        else:
            template_content = template["template"].strip()
            if len(template_content) == 0:
                errors.append("Template content cannot be empty or whitespace-only")
            elif len(template_content) < 50:
                errors.append("Template content is too short (minimum 50 characters)")
            elif len(template_content) > 10000:
                errors.append(
                    "Template content is too long (maximum 10,000 characters)"
                )

    # Validate focus_areas with edge case handling
    if "focus_areas" in template:
        focus_areas = template["focus_areas"]
        if focus_areas is None:
            errors.append("Field 'focus_areas' cannot be None")
        elif not isinstance(focus_areas, list):
            errors.append("Field 'focus_areas' must be a list")
        else:
            # Cast to List[Any] since we've confirmed it's a list
            focus_areas_list = cast(List[Any], focus_areas)
            if len(focus_areas_list) == 0:
                errors.append("Field 'focus_areas' cannot be empty")
            else:
                # Validate each focus area
                for i, area in enumerate(focus_areas_list):
                    if not isinstance(area, str):
                        errors.append(f"Focus area {i} must be a string")
                    elif not area.strip():
                        errors.append(
                            f"Focus area {i} cannot be empty or whitespace-only"
                        )

    # Validate output_format with edge cases
    if "output_format" in template:
        output_format = template["output_format"]
        if output_format is not None and not isinstance(output_format, str):
            errors.append("Field 'output_format' must be a string")
        elif isinstance(output_format, str) and not output_format.strip():
            errors.append("Field 'output_format' cannot be empty or whitespace-only")

    # Check for placeholder variables with error handling
    placeholders: List[str] = []
    if "template" in template and isinstance(template["template"], str):
        try:
            import re

            placeholders = re.findall(r"\{(\w+)\}", template["template"])
            # Remove duplicates while preserving order
            placeholders = list(dict.fromkeys(placeholders))
        except Exception as e:
            errors.append(f"Failed to parse template placeholders: {e}")

    result = {"valid": len(errors) == 0, "errors": errors, "placeholders": placeholders}

    return result


def get_meta_prompt_template(
    template_name: str, config_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get a specific meta-prompt template by name."""
    try:
        templates = load_meta_prompt_templates(config_path)
        return templates.get(template_name)
    except Exception:
        return None


def list_meta_prompt_templates(config_path: Optional[str] = None) -> List[str]:
    """List all available meta-prompt template names."""
    try:
        templates = load_meta_prompt_templates(config_path)
        return list(templates.keys())
    except Exception:
        return []


def load_meta_prompt_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load meta-prompt configuration section from model_config.json."""
    if config_path is None:
        config = load_model_config()
    else:
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise ValueError(f"Failed to load config from {config_path}: {e}")

    # Default meta-prompt config
    default_meta_config = {
        "default_template": "default",
        "max_context_size": 100000,
        "analysis_depth": "comprehensive",
        "include_examples": True,
        "technology_specific": True,
    }

    # Get meta_prompt_config section, merge with defaults
    meta_config = config.get("meta_prompt_config", {})
    for key, value in default_meta_config.items():
        if key not in meta_config:
            meta_config[key] = value

    return meta_config


def validate_meta_prompt_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate meta-prompt configuration."""
    errors: List[str] = []

    # Validate analysis_depth
    if "analysis_depth" in config:
        valid_depths = ["basic", "comprehensive", "advanced"]
        if config["analysis_depth"] not in valid_depths:
            errors.append(f"analysis_depth must be one of {valid_depths}")

    # Validate max_context_size
    if "max_context_size" in config:
        if (
            not isinstance(config["max_context_size"], int)
            or config["max_context_size"] <= 0
        ):
            errors.append("max_context_size must be a positive integer")

    # Validate boolean fields
    bool_fields = ["include_examples", "technology_specific"]
    for field in bool_fields:
        if field in config and not isinstance(config[field], bool):
            errors.append(f"Field '{field}' must be a boolean")

    return {"valid": len(errors) == 0, "errors": errors}


def merge_template_overrides(
    base_templates: Dict[str, Dict[str, Any]], config_path: str
) -> Dict[str, Dict[str, Any]]:
    """Merge template overrides from config file with base templates."""
    try:
        with open(config_path, "r") as f:
            override_config = json.load(f)
    except (json.JSONDecodeError, IOError):
        return base_templates

    override_templates = override_config.get("meta_prompt_templates", {})
    merged_templates = base_templates.copy()

    for template_name, override_data in override_templates.items():
        if template_name in merged_templates:
            # Merge override with base template
            merged_template = merged_templates[template_name].copy()
            merged_template.update(override_data)
            merged_templates[template_name] = merged_template
        else:
            # Add new template
            merged_templates[template_name] = override_data

    return merged_templates


def load_meta_prompt_templates_from_env() -> Dict[str, Dict[str, Any]]:
    """Load meta-prompt templates from environment variable path."""
    env_config_path = os.getenv("META_PROMPT_CONFIG_PATH")
    if env_config_path and os.path.exists(env_config_path):
        return load_meta_prompt_templates(env_config_path)
    else:
        return load_meta_prompt_templates()


def load_meta_prompt_with_precedence(
    config_path: Optional[str] = None, cli_overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Dict[str, Any]]:
    """Load meta-prompt templates with precedence: CLI > Environment > Config File > Defaults."""
    # Start with base config
    templates = load_meta_prompt_templates(config_path)

    # Apply environment overrides
    env_config_path = os.getenv("META_PROMPT_CONFIG_PATH")
    if env_config_path and os.path.exists(env_config_path):
        env_templates = load_meta_prompt_templates(env_config_path)
        templates.update(env_templates)

    # Apply CLI overrides (highest precedence)
    if cli_overrides:
        for template_name, override_data in cli_overrides.items():
            if template_name in templates:
                templates[template_name].update(override_data)
            else:
                templates[template_name] = override_data

    return templates


def get_default_meta_prompt_template(
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Get the default meta-prompt template based on configuration."""
    meta_config = load_meta_prompt_config(config_path)
    default_template_name = meta_config.get("default_template", "default")

    template = get_meta_prompt_template(default_template_name, config_path)
    if template is None:
        # Fallback to 'default' template if specified default doesn't exist
        template = get_meta_prompt_template("default", config_path)

    # If still None, return a basic fallback template
    if template is None:
        return {
            "name": "fallback",
            "description": "Basic fallback template",
            "template": "Please review the following code:\n\n{context}",
        }

    return template


def analyze_project_completion_status(task_list_content: str) -> Dict[str, Any]:
    """Analyze project completion status from task list content."""
    lines = task_list_content.split("\n")

    completed_phases: List[str] = []
    current_phase = None
    next_priorities: List[str] = []
    total_tasks = 0
    completed_tasks = 0

    # Parse task list for completion status
    for line in lines:
        line = line.strip()

        # Look for main phase tasks (e.g., "- [x] 1.0 Authentication System")
        if re.match(r"- \[(x| )\] (\d+\.\d+)", line):
            total_tasks += 1
            if "[x]" in line:
                completed_tasks += 1
                # Extract phase number
                phase_match = re.search(r"(\d+\.\d+)", line)
                if phase_match:
                    completed_phases.append(phase_match.group(1))
            else:
                # This is an incomplete phase
                if current_phase is None:
                    phase_match = re.search(r"(\d+\.\d+)", line)
                    if phase_match:
                        current_phase = phase_match.group(1)
                        # Extract priority from phase name
                        if "security" in line.lower():
                            next_priorities.append("security")
                        if "performance" in line.lower():
                            next_priorities.append("performance")
                        if "testing" in line.lower():
                            next_priorities.append("testing")

    completion_percentage = (
        (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
    )

    return {
        "completed_phases": completed_phases,
        "current_phase": current_phase,
        "next_priorities": next_priorities,
        "completion_percentage": completion_percentage,
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
    }


def validate_meta_prompt_config_file(config_path: str) -> Dict[str, Any]:
    """Validate entire meta-prompt configuration file."""
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return {"valid": False, "errors": [f"Invalid JSON: {e}"]}
    except IOError as e:
        return {"valid": False, "errors": [f"File error: {e}"]}

    errors: List[str] = []

    # Validate templates section
    if "meta_prompt_templates" in config:
        templates = config["meta_prompt_templates"]
        for template_name, template_data in templates.items():
            validation_result = validate_meta_prompt_template(template_data)
            if not validation_result["valid"]:
                errors.extend(
                    [
                        f"Template {template_name}: {error}"
                        for error in validation_result["errors"]
                    ]
                )

    # Validate config section
    if "meta_prompt_config" in config:
        config_validation = validate_meta_prompt_config(config["meta_prompt_config"])
        if not config_validation["valid"]:
            errors.extend(config_validation["errors"])

    return {"valid": len(errors) == 0, "errors": errors}


def load_meta_prompt_templates_with_fallback(
    config_path: str,
) -> Dict[str, Dict[str, Any]]:
    """Load meta-prompt templates with fallback to defaults on error."""
    try:
        return load_meta_prompt_templates(config_path)
    except Exception:
        # Fallback to default templates
        return load_meta_prompt_templates()


def load_api_key() -> Optional[str]:
    """Load API key with multiple fallback strategies for uvx compatibility"""
    from pathlib import Path

    # Strategy 1: Direct environment variables
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        logger.debug("API key loaded from environment variable")
        return api_key

    # Strategy 2: .env file in current directory
    env_file = Path(".env")
    if env_file.exists():
        try:
            from dotenv import load_dotenv  # type: ignore

            load_dotenv(env_file)
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                logger.debug("API key loaded from .env file")
                return api_key
        except ImportError:
            logger.debug("python-dotenv not available, skipping .env file")

    # Strategy 3: User's home directory .env file
    home_env = Path.home() / ".task-list-code-review-mcp.env"
    if home_env.exists():
        try:
            api_key = home_env.read_text().strip()
            if api_key:
                logger.debug(f"API key loaded from {home_env}")
                return api_key
        except IOError:
            pass

    return None


def suggest_path_corrections(provided_path: str, expected_type: str = "project") -> str:
    """
    Generate helpful path correction suggestions based on common mistakes.

    Args:
        provided_path: The path the user provided
        expected_type: Type of path expected ("project", "file", "directory")

    Returns:
        String with suggestion messages
    """
    suggestions: List[str] = []
    current_dir = os.getcwd()

    # Check if path exists but is wrong type
    if os.path.exists(provided_path):
        if expected_type == "project" and os.path.isfile(provided_path):
            parent_dir = os.path.dirname(provided_path)
            suggestions.append(
                "  # You provided a file, try the parent directory instead:"
            )
            suggestions.append(
                f"  generate-code-review {parent_dir if parent_dir else '.'}"
            )
    else:
        # Path doesn't exist - suggest common corrections
        abs_path = os.path.abspath(provided_path)
        parent_dir = os.path.dirname(abs_path)

        # Check if parent exists
        if os.path.exists(parent_dir):
            suggestions.append("  # Parent directory exists. Maybe there's a typo?")
            similar_items: List[str] = []
            try:
                for item in os.listdir(parent_dir):
                    if item.lower().startswith(
                        os.path.basename(provided_path).lower()[:3]
                    ):
                        similar_items.append(item)
                if similar_items:
                    suggestions.append(
                        f"  # Similar items found: {', '.join(similar_items[:3])}"
                    )
                    suggestions.append(
                        f"  generate-code-review {os.path.join(parent_dir, similar_items[0])}"
                    )
            except PermissionError:
                suggestions.append(f"  # Permission denied accessing {parent_dir}")

        # Check if it's a relative path issue
        basename = os.path.basename(provided_path)
        for root, dirs, _ in os.walk(current_dir):
            if basename in dirs:
                rel_path = os.path.relpath(os.path.join(root, basename), current_dir)
                suggestions.append("  # Found similar directory:")
                suggestions.append(f"  generate-code-review {rel_path}")
                break
            if len(suggestions) > 6:  # Limit suggestions
                break

        # Common path corrections
        if provided_path.startswith("/"):
            suggestions.append("  # Try relative path instead:")
            suggestions.append(
                f"  generate-code-review ./{os.path.basename(provided_path)}"
            )
        else:
            suggestions.append("  # Try absolute path:")
            suggestions.append(f"  generate-code-review {abs_path}")

    # Check for common project structure issues
    if expected_type == "project":
        tasks_path = (
            os.path.join(provided_path, "tasks")
            if os.path.exists(provided_path)
            else None
        )
        if tasks_path and not os.path.exists(tasks_path):
            suggestions.append("  # Directory exists but missing tasks/ folder:")
            suggestions.append(f"  mkdir {tasks_path}")
            suggestions.append("  # Then add PRD and task files to tasks/")

    return "\n".join(suggestions) if suggestions else "  # Check the path and try again"


def require_api_key():
    """Ensure API key is available with uvx-specific guidance"""
    api_key = load_api_key()

    if not api_key:
        error_msg = """
🔑 GEMINI_API_KEY not found. Choose the setup method that works for your environment:

📋 QUICKSTART (Recommended):
   # 1. Get API key: https://ai.google.dev/gemini-api/docs/api-key
   # 2. Set environment variable:
   export GEMINI_API_KEY=your_key_here
   
   # 3. Run tool:
   generate-code-review .

🔧 FOR UVX USERS:
   # Method 1: Environment variable prefix (most reliable)
   GEMINI_API_KEY=your_key uvx task-list-code-review-mcp generate-code-review .
   
   # Method 2: Create project .env file
   echo "GEMINI_API_KEY=your_key_here" > .env
   uvx task-list-code-review-mcp generate-code-review .
   
   # Method 3: Global user config
   echo "GEMINI_API_KEY=your_key_here" > ~/.task-list-code-review-mcp.env
   uvx task-list-code-review-mcp generate-code-review .

📝 FOR MCP SERVER USERS:
   Add to your Claude Desktop configuration:
   {
     "mcpServers": {
       "task-list-reviewer": {
         "command": "uvx",
         "args": ["task-list-code-review-mcp"],
         "env": {
           "GEMINI_API_KEY": "your_key_here"
         }
       }
     }
   }

🚨 TROUBLESHOOTING:
   # Check if environment variable is set:
   echo $GEMINI_API_KEY
   
   # Test API key with minimal command:
   GEMINI_API_KEY=your_key uvx task-list-code-review-mcp generate-code-review . --no-gemini
   
   # Verify current directory structure:
   ls -la tasks/

🌐 Get your API key: https://ai.google.dev/gemini-api/docs/api-key
"""
        logger.error(error_msg)
        raise ValueError(error_msg)

    return api_key


def parse_task_list(content: str) -> TaskData:
    """
    Parse task list content and extract phase information.

    Args:
        content: Raw markdown content of task list

    Returns:
        Dictionary with phase information
    """
    lines = content.strip().split("\n")
    phases: List[PhaseData] = []
    current_phase: Optional[PhaseData] = None

    # Phase pattern: ^- \[([ x])\] (\d+\.\d+) (.+)$
    phase_pattern = r"^- \[([ x])\] (\d+\.\d+) (.+)$"
    # Subtask pattern: ^  - \[([ x])\] (\d+\.\d+) (.+)$
    subtask_pattern = r"^  - \[([ x])\] (\d+\.\d+) (.+)$"

    for line in lines:
        phase_match = re.match(phase_pattern, line)
        if phase_match:
            completed = phase_match.group(1) == "x"
            number = phase_match.group(2)
            description = phase_match.group(3).strip()

            current_phase_dict: PhaseData = {
                "number": number,
                "description": description,
                "subtasks": [],
                "subtasks_complete": False,
                "subtasks_completed": [],
            }
            current_phase = current_phase_dict
            phases.append(current_phase)
            continue

        subtask_match = re.match(subtask_pattern, line)
        if subtask_match and current_phase:
            completed = subtask_match.group(1) == "x"
            number = subtask_match.group(2)
            description = subtask_match.group(3).strip()

            subtask: SubtaskData = {"number": number, "description": description, "complete": completed}
            current_phase["subtasks"].append(subtask)

            if completed:
                current_phase["subtasks_completed"].append(f"{number} {description}")

    # Determine if each phase is complete (all subtasks complete)
    for phase in phases:
        if phase["subtasks"]:
            phase["subtasks_complete"] = all(
                st["complete"] for st in phase["subtasks"]
            )
        else:
            phase["subtasks_complete"] = True

    result: TaskData = {
        "phases": phases,
        **detect_current_phase(phases),
    }
    return result


def detect_current_phase(phases: List[PhaseData]) -> Dict[str, str]:
    """
    Detect the most recently completed phase for code review.

    The logic prioritizes reviewing completed phases over in-progress ones:
    1. Find the most recently completed phase (all subtasks done)
    2. If no phases are complete, fall back to the current in-progress phase
    3. If all phases are complete, use the last phase

    Args:
        phases: List of phase dictionaries

    Returns:
        Dictionary with phase information for code review
    """
    if not phases:
        return {
            "current_phase_number": "",
            "current_phase_description": "",
            "previous_phase_completed": "",
            "next_phase": "",
            "subtasks_completed": [],
        }

    # Find the most recently completed phase (all subtasks complete)
    review_phase = None
    for i in range(len(phases) - 1, -1, -1):  # Start from the end
        phase = phases[i]
        if phase["subtasks_complete"] and phase["subtasks"]:
            review_phase = phase
            break

    # If no completed phases found, find first phase with incomplete subtasks
    if review_phase is None:
        for phase in phases:
            if not phase["subtasks_complete"]:
                review_phase = phase
                break

    # If all phases complete or no phases found, use last phase
    if review_phase is None:
        review_phase = phases[-1]

    # Find the index of the review phase
    review_idx = None
    for i, phase in enumerate(phases):
        if phase["number"] == review_phase["number"]:
            review_idx = i
            break

    # Find previous completed phase
    previous_phase_completed = ""
    if review_idx is not None and review_idx > 0:
        prev_phase = phases[review_idx - 1]
        previous_phase_completed = f"{prev_phase['number']} {prev_phase['description']}"

    # Find next phase
    next_phase = ""
    if review_idx is not None and review_idx < len(phases) - 1:
        next_phase_obj = phases[review_idx + 1]
        next_phase = f"{next_phase_obj['number']} {next_phase_obj['description']}"

    return {
        "current_phase_number": review_phase["number"],
        "current_phase_description": review_phase["description"],
        "previous_phase_completed": previous_phase_completed,
        "next_phase": next_phase,
        "subtasks_completed": review_phase["subtasks_completed"],
    }


def generate_prd_summary_from_task_list(task_data: TaskData) -> str:
    """
    Generate a PRD-style summary from task list content.

    Args:
        task_data: Parsed task list data

    Returns:
        Generated project summary string
    """
    phases_data = task_data.get("phases", [])
    phases: List[PhaseData] = []
    if isinstance(phases_data, list):
        for item in phases_data:
            if is_phase_data(item):
                phases.append(item)
    if not phases:
        return "Development project focused on code quality and feature implementation."

    # Extract high-level goals from phase descriptions
    phase_descriptions: List[str] = [p.get("description", "") for p in phases]

    # Create a coherent summary
    if len(phases) == 1:
        summary = f"Development project focused on {phase_descriptions[0].lower()}."
    elif len(phases) <= 3:
        summary = f"Development project covering: {', '.join(phase_descriptions[:-1]).lower()}, and {phase_descriptions[-1].lower()}."
    else:
        key_phases: List[str] = phase_descriptions[:3]
        summary = f"Multi-phase development project including {', '.join(key_phases).lower()}, and {len(phases) - 3} additional phases."

    return summary


def extract_prd_summary(content: str) -> str:
    """
    Extract PRD summary using multiple strategies.

    Args:
        content: Raw markdown content of PRD

    Returns:
        Extracted or generated summary
    """
    # Strategy 1: Look for explicit summary sections
    summary_patterns = [
        r"## Summary\n(.+?)(?=\n##|\Z)",
        r"## Overview\n(.+?)(?=\n##|\Z)",
        r"### Summary\n(.+?)(?=\n###|\Z)",
        r"## Executive Summary\n(.+?)(?=\n##|\Z)",
    ]

    for pattern in summary_patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            summary = match.group(1).strip()
            # Clean up the summary (remove extra whitespace, newlines)
            summary = re.sub(r"\s+", " ", summary)
            return summary

    # Strategy 2: Use Gemini if available and API key provided
    if GEMINI_AVAILABLE:
        try:
            api_key = load_api_key()
        except Exception:
            api_key = None
    else:
        api_key = None

    if GEMINI_AVAILABLE and api_key and genai is not None:
        try:
            client = genai.Client(api_key=api_key)
            first_2000_chars = content[:2000]

            # Use configurable model for PRD summarization
            config = load_model_config()
            summary_model = os.getenv(
                "GEMINI_SUMMARY_MODEL", config["defaults"]["summary_model"]
            )

            response = client.models.generate_content(
                model=summary_model,
                contents=[
                    f"Summarize this PRD in 2-3 sentences focusing on the main goal and key deliverables:\\n\\n{first_2000_chars}"
                ],
                config=(
                    types.GenerateContentConfig(max_output_tokens=150, temperature=0.1)
                    if types is not None
                    else None
                ),
            )

            return response.text.strip() if response.text else ""
        except Exception as e:
            logger.warning(f"Failed to generate LLM summary: {e}")

    # Strategy 3: Fallback - use first paragraph or first 200 characters
    lines = content.split("\n")
    content_lines = [
        line.strip() for line in lines if line.strip() and not line.startswith("#")
    ]

    if content_lines:
        first_paragraph = content_lines[0]
        if len(first_paragraph) > 200:
            first_paragraph = first_paragraph[:200] + "..."
        return first_paragraph

    # Ultimate fallback
    return "No summary available."


def get_changed_files(project_path: str) -> List[Dict[str, str]]:
    """
    Get changed files from git with their content.

    Args:
        project_path: Path to project root

    Returns:
        List of changed file dictionaries
    """
    try:
        changed_files: List[Dict[str, str]] = []
        max_lines_env = os.getenv("MAX_FILE_CONTENT_LINES", "500")
        max_lines = int(max_lines_env) if max_lines_env else 500
        debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"

        if debug_mode:
            logger.info(
                f"Debug mode enabled. Processing max {max_lines} lines per file."
            )

        # Get all types of changes: staged, unstaged, and untracked
        all_files: Dict[str, List[str]] = {}

        # 1. Staged changes (index vs HEAD)
        result = subprocess.run(
            ["git", "diff", "--name-status", "--cached"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    status, file_path = parts
                    if file_path not in all_files:
                        all_files[file_path] = []
                    all_files[file_path].append(f"staged-{status}")

        # 2. Unstaged changes (working tree vs index)
        result = subprocess.run(
            ["git", "diff", "--name-status"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    status, file_path = parts
                    if file_path not in all_files:
                        all_files[file_path] = []
                    all_files[file_path].append(f"unstaged-{status}")

        # 3. Untracked files
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            if line:
                if line not in all_files:
                    all_files[line] = []
                all_files[line].append("untracked")

        # Process all collected files
        for file_path, statuses in all_files.items():
            absolute_path = os.path.abspath(os.path.join(project_path, file_path))

            # Check if this is a deleted file
            is_deleted = any("D" in status for status in statuses)

            if is_deleted:
                content = "[File deleted]"
            else:
                # Get file content from working directory
                try:
                    if os.path.exists(absolute_path):
                        # Check file size to avoid memory issues with very large files
                        file_size = os.path.getsize(absolute_path)
                        max_file_size = (
                            int(os.getenv("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024
                        )  # Default 10MB

                        if file_size > max_file_size:
                            content = f"[File too large: {file_size / (1024 * 1024):.1f}MB, limit is {max_file_size / (1024 * 1024)}MB]"
                        else:
                            with open(absolute_path, "r", encoding="utf-8") as f:
                                content_lines = f.readlines()

                            if len(content_lines) > max_lines:
                                content = "".join(content_lines[:max_lines])
                                content += f"\n... (truncated, showing first {max_lines} lines)"
                            else:
                                content = "".join(content_lines).rstrip("\n")
                    else:
                        content = "[File not found in working directory]"

                except (UnicodeDecodeError, PermissionError, OSError):
                    # Handle binary files or other errors
                    content = "[Binary file or content not available]"

            changed_files.append(
                {
                    "path": absolute_path,
                    "status": ", ".join(statuses),
                    "content": content,
                }
            )

        return changed_files

    except (subprocess.CalledProcessError, FileNotFoundError):
        # Not a git repository or git not available
        logger.warning("Git not available or not in a git repository")
        return []


def generate_file_tree(project_path: str, max_depth: Optional[int] = None) -> str:
    """
    Generate ASCII file tree representation.

    Args:
        project_path: Path to project root
        max_depth: Maximum depth to traverse

    Returns:
        ASCII file tree string
    """
    if max_depth is None:
        max_depth = int(os.getenv("MAX_FILE_TREE_DEPTH", "5"))

    # Default ignore patterns
    ignore_patterns = {
        ".git",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        "*.pyc",
        ".DS_Store",
        ".vscode",
        ".idea",
    }

    # Read .gitignore if it exists
    gitignore_path = os.path.join(project_path, ".gitignore")
    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        ignore_patterns.add(line)
        except Exception as e:
            logger.warning(f"Failed to read .gitignore: {e}")

    def should_ignore(name: str, path: str) -> bool:
        """Check if file/directory should be ignored."""
        for pattern in ignore_patterns:
            if pattern == name or pattern in path:
                return True
            # Simple glob pattern matching
            if "*" in pattern:
                import fnmatch

                if fnmatch.fnmatch(name, pattern):
                    return True
        return False

    def build_tree(current_path: str, prefix: str = "", depth: int = 0) -> List[str]:
        """Recursively build tree structure."""
        if depth >= max_depth:
            return []

        try:
            items = os.listdir(current_path)
        except PermissionError:
            return []

        # Filter out ignored items
        items = [
            item
            for item in items
            if not should_ignore(item, os.path.join(current_path, item))
        ]

        # Sort: directories first, then files, both alphabetically
        dirs = sorted(
            [item for item in items if os.path.isdir(os.path.join(current_path, item))]
        )
        files = sorted(
            [item for item in items if os.path.isfile(os.path.join(current_path, item))]
        )

        tree_lines: List[str] = []
        all_items = dirs + files

        for i, item in enumerate(all_items):
            is_last = i == len(all_items) - 1
            item_path = os.path.join(current_path, item)

            if os.path.isdir(item_path):
                connector = "└── " if is_last else "├── "
                tree_lines.append(f"{prefix}{connector}{item}/")

                extension = "    " if is_last else "│   "
                subtree = build_tree(item_path, prefix + extension, depth + 1)
                tree_lines.extend(subtree)
            else:
                connector = "└── " if is_last else "├── "
                tree_lines.append(f"{prefix}{connector}{item}")

        return tree_lines

    tree_lines = [project_path]
    tree_lines.extend(build_tree(project_path))
    return "\n".join(tree_lines)


def extract_clean_prompt_content(auto_prompt_content: str) -> str:
    """
    Extract clean prompt content from auto-generated prompt response.

    Since auto-prompt generation now returns raw content without headers/footers,
    this function primarily handles basic cleanup and formatting.

    Args:
        auto_prompt_content: Auto-prompt response (should be clean already)

    Returns:
        Clean prompt content suitable for user_instructions
    """
    # Basic cleanup - remove any extra whitespace
    content = auto_prompt_content.strip()

    # Remove any remaining code block markers if present (just in case)
    if content.startswith("```") and content.endswith("```"):
        lines = content.split("\n")
        if len(lines) > 2:
            content = "\n".join(lines[1:-1]).strip()

    # Collapse multiple blank lines
    import re

    content = re.sub(r"\n\n\n+", "\n\n", content)

    return content


def format_review_template(data: Dict[str, Any]) -> str:
    """
    Format the final review template.

    Args:
        data: Dictionary containing all template data

    Returns:
        Formatted markdown template
    """
    # Add scope information to header
    review_mode = data.get("review_mode", "task_list_based")
    if review_mode == "github_pr":
        scope_info = "Review Mode: GitHub PR Analysis"
    else:
        scope_info = f"Review Scope: {data['scope']}"
        if data.get("phase_number"):
            scope_info += f" (Phase: {data['phase_number']})"
        elif data.get("task_number"):
            scope_info += f" (Task: {data['task_number']})"

    template = f"""# Code Review Context - {scope_info}

<overall_prd_summary>
{data['prd_summary']}
</overall_prd_summary>

<total_phases>
{data['total_phases']}
</total_phases>

<current_phase_number>
{data['current_phase_number']}
</current_phase_number>
"""

    # Only add previous phase if it exists
    if data["previous_phase_completed"]:
        template += f"""
<previous_phase_completed>
{data['previous_phase_completed']}
</previous_phase_completed>
"""

    # Only add next phase if it exists
    if data["next_phase"]:
        template += f"""
<next_phase>
{data['next_phase']}
</next_phase>
"""

    template += f"""<current_phase_description>
{data['current_phase_description']}
</current_phase_description>

<subtasks_completed>
{chr(10).join(f"- {subtask}" for subtask in data['subtasks_completed'])}
</subtasks_completed>"""

    # Add GitHub PR metadata if available
    branch_data = data.get("branch_comparison_data")
    if branch_data and branch_data["mode"] == "github_pr":
        pr_data = branch_data["pr_data"]
        summary = branch_data.get("summary", {})
        template += f"""
<github_pr_metadata>
Repository: {branch_data['repository']}
PR Number: {pr_data['pr_number']}
Title: {pr_data['title']}
Author: {pr_data['author']}
Source Branch: {pr_data['source_branch']}
Target Branch: {pr_data['target_branch']}
Source SHA: {pr_data.get('source_sha', 'N/A')[:8]}...
Target SHA: {pr_data.get('target_sha', 'N/A')[:8]}...
State: {pr_data['state']}
Created: {pr_data['created_at']}
Updated: {pr_data['updated_at']}
Files Changed: {summary.get('files_changed', 'N/A')}
Files Added: {summary.get('files_added', 'N/A')}
Files Modified: {summary.get('files_modified', 'N/A')}
Files Deleted: {summary.get('files_deleted', 'N/A')}"""
        if pr_data.get("body") and pr_data["body"].strip():
            # Show first 200 chars of PR description
            description = pr_data["body"].strip()[:200]
            if len(pr_data["body"]) > 200:
                description += "..."
            template += f"""
Description: {description}"""
        template += """
</github_pr_metadata>"""

    template += f"""
<project_path>
{data['project_path']}
</project_path>"""

    # Add configuration content section if available
    if data.get("configuration_content"):
        template += f"""
<configuration_context>
{data['configuration_content']}
</configuration_context>"""

        # Add applicable rules summary if available
        applicable_rules = data.get("applicable_rules", [])
        if applicable_rules:
            template += f"""
<applicable_configuration_rules>
The following configuration rules apply to the changed files:
{chr(10).join(f"- {rule.description} (from {rule.file_path})" for rule in applicable_rules)}
</applicable_configuration_rules>"""

    template += f"""
<file_tree>
{data['file_tree']}
</file_tree>

<files_changed>"""

    for file_info in data["changed_files"]:
        file_ext = os.path.splitext(file_info["path"])[1].lstrip(".")
        if not file_ext:
            file_ext = "txt"

        template += f"""
File: {file_info['path']} ({file_info['status']})
```{file_ext}
{file_info['content']}
```"""

    template += """
</files_changed>"""

    # Add AI review instructions only if not raw_context_only
    if not data.get("raw_context_only", False):
        template += """

<user_instructions>"""

        # Check if auto-generated meta-prompt should be used
        auto_prompt_content = data.get("auto_prompt_content")
        if auto_prompt_content:
            # Extract clean prompt content (remove headers, metadata, and formatting)
            clean_prompt = extract_clean_prompt_content(auto_prompt_content)
            # Use the auto-generated meta-prompt as user instructions
            template += clean_prompt
        else:
            # Use default template-based instructions
            # Customize instructions based on review mode and scope
            review_mode = data.get("review_mode", "task_list_based")
            branch_data = data.get("branch_comparison_data")

            if review_mode == "github_pr" and branch_data:
                config_note = ""
                if data.get("configuration_content"):
                    config_note = "\n\nPay special attention to the configuration context (Claude memory and Cursor rules) provided above, which contains project-specific guidelines and coding standards that should be followed."

                template += f"""You are reviewing a GitHub Pull Request that contains changes from branch '{branch_data['pr_data']['source_branch']}' to '{branch_data['pr_data']['target_branch']}'.

The PR "{branch_data['pr_data']['title']}" by {branch_data['pr_data']['author']} includes {branch_data['summary']['files_changed']} changed files with {branch_data['summary']['files_added']} additions, {branch_data['summary']['files_modified']} modifications, and {branch_data['summary']['files_deleted']} deletions.{config_note}

Based on the PR metadata, commit history, and file changes shown above, conduct a comprehensive code review focusing on:
1. Code quality and best practices
2. Security implications of the changes
3. Performance considerations
4. Testing coverage and approach
5. Documentation completeness
6. Integration and compatibility issues

Identify specific lines, files, or patterns that are concerning and provide actionable feedback."""
            elif data["scope"] == "full_project":
                config_note = ""
                if data.get("configuration_content"):
                    config_note = "\n\nImportant: Refer to the configuration context (Claude memory and Cursor rules) provided above for project-specific guidelines and coding standards that should be followed throughout the project."

                template += f"""We have completed all phases (and subtasks within) of this project: {data['current_phase_description']}.{config_note}

Based on the PRD, all completed phases, all subtasks that were finished across the entire project, and the files changed in the working directory, your job is to conduct a comprehensive code review and output your code review feedback for the entire project. Identify specific lines or files that are concerning when appropriate."""
            elif data["scope"] == "specific_task":
                config_note = ""
                if data.get("configuration_content"):
                    config_note = "\n\nImportant: Refer to the configuration context (Claude memory and Cursor rules) provided above for project-specific guidelines and coding standards."

                template += f"""We have just completed task #{data['current_phase_number']}: "{data['current_phase_description']}".{config_note}

Based on the PRD, the completed task, and the files changed in the working directory, your job is to conduct a code review and output your code review feedback for this specific task. Identify specific lines or files that are concerning when appropriate."""
            else:
                config_note = ""
                if data.get("configuration_content"):
                    config_note = "\n\nImportant: Refer to the configuration context (Claude memory and Cursor rules) provided above for project-specific guidelines and coding standards."

                template += f"""We have just completed phase #{data['current_phase_number']}: "{data['current_phase_description']}".{config_note}

Based on the PRD, the completed phase, all subtasks that were finished in that phase, and the files changed in the working directory, your job is to conduct a code review and output your code review feedback for the completed phase. Identify specific lines or files that are concerning when appropriate."""

        template += """
</user_instructions>"""

    return template


def find_project_files(
    project_path: str, task_list_name: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """
    Find PRD and task list files in the project. PRD files are now optional.

    Args:
        project_path: Path to project root
        task_list_name: Optional specific task list file name (e.g., 'tasks-feature-x.md')

    Returns:
        Tuple of (prd_file_path, task_list_path). prd_file_path may be None.
    """
    tasks_dir = os.path.join(project_path, "tasks")

    # Create tasks directory if it doesn't exist (for new projects)
    if not os.path.exists(tasks_dir):
        logger.info(
            f"Tasks directory not found: {tasks_dir}. This is OK - the tool can work without task lists."
        )
        return None, None

    # Find PRD files (optional)
    prd_file = None
    prd_files = glob.glob(os.path.join(tasks_dir, "prd-*.md"))
    if not prd_files:
        # Also check root directory
        prd_files = glob.glob(os.path.join(project_path, "prd.md"))

    if prd_files:
        # Use most recently modified if multiple
        prd_file = max(prd_files, key=os.path.getmtime)
        logger.info(f"Found PRD file: {os.path.basename(prd_file)}")
    else:
        print(
            "ℹ️  No PRD files found - using task list or default prompt for context generation"
        )

    # Find task list files
    task_file = None

    if task_list_name:
        # User specified exact task list file
        if not task_list_name.endswith(".md"):
            task_list_name += ".md"

        specified_path = os.path.join(tasks_dir, task_list_name)
        if os.path.exists(specified_path):
            task_file = specified_path
            logger.info(f"Using specified task list: {task_list_name}")
        else:
            # Try to find similar files
            available_files = [
                f
                for f in os.listdir(tasks_dir)
                if f.startswith("tasks-") and f.endswith(".md")
            ]
            error_msg = f"""Specified task list not found: {task_list_name}

Available task lists in {tasks_dir}:
{chr(10).join(f'  - {f}' for f in available_files) if available_files else '  (no task list files found)'}

Working examples:
  # Use specific task list
  generate-code-review . --task-list tasks-feature-auth.md
  
  # Let tool auto-select most recent task list
  generate-code-review ."""
            raise FileNotFoundError(error_msg)
    else:
        # Auto-discover task list files
        task_files = glob.glob(os.path.join(tasks_dir, "tasks-*.md"))

        if task_files:
            # Use most recently modified if multiple
            task_file = max(task_files, key=os.path.getmtime)
            if len(task_files) > 1:
                available_files = [os.path.basename(f) for f in task_files]
                logger.info(f"Multiple task lists found: {', '.join(available_files)}")
                logger.info(f"Auto-selected most recent: {os.path.basename(task_file)}")
            else:
                logger.info(f"Found task list: {os.path.basename(task_file)}")
        else:
            logger.info(
                "No task list files found. Will use default prompt for code review."
            )

    return prd_file, task_file


def send_to_gemini_for_review(
    context_content: str,
    project_path: Optional[str] = None,
    temperature: float = 0.5,
    model: Optional[str] = None,
    return_text: bool = False,
    include_formatting: bool = True,
) -> Optional[str]:
    """
    Send review context to Gemini for comprehensive code review with advanced features.

    Features enabled by default:
    - Thinking mode (for supported models)
    - URL context (for supported models)
    - Google Search grounding (for supported models)

    Args:
        context_content: The formatted review context content
        project_path: Path to project root for saving output (optional if return_text=True)
        temperature: Temperature for AI model (default: 0.5)
        model: Optional model override (default: uses GEMINI_MODEL env var or config default)
        return_text: If True, return generated text directly; if False, save to file and return file path
        include_formatting: If True, include headers and metadata; if False, return raw response (default: True)

    Returns:
        Generated text (if return_text=True) or path to saved file (if return_text=False), or None if failed
    """
    # Check if Gemini is available first
    if not GEMINI_AVAILABLE or genai is None:
        logger.warning("Gemini API not available. Skipping Gemini review.")
        return None

    # Use enhanced API key loading with multiple strategies
    try:
        api_key = require_api_key()
    except ValueError as e:
        logger.warning(f"API key not found: {e}")
        return None

    try:
        client = genai.Client(api_key=api_key)

        # Load model configuration from JSON file
        config = load_model_config()

        # Configure model selection with precedence: parameter > env var > config default
        model_config = model or os.getenv("GEMINI_MODEL", config["defaults"]["model"])

        # Resolve model aliases to actual API model names
        model_config = config["model_aliases"].get(model_config, model_config)

        # Model capability detection using configuration
        supports_url_context = (
            model_config in config["model_capabilities"]["url_context_supported"]
        )
        supports_grounding = (
            "gemini-1.5" in model_config
            or "gemini-2.0" in model_config
            or "gemini-2.5" in model_config
        )
        supports_thinking = (
            model_config in config["model_capabilities"]["thinking_mode_supported"]
        )

        # Determine what features will actually be enabled (considering disable flags)
        actual_capabilities: List[str] = []
        disable_url_context = (
            os.getenv("DISABLE_URL_CONTEXT", "false").lower() == "true"
        )
        disable_grounding = os.getenv("DISABLE_GROUNDING", "false").lower() == "true"
        disable_thinking = os.getenv("DISABLE_THINKING", "false").lower() == "true"

        # Check what will actually be enabled
        url_context_enabled = supports_url_context and not disable_url_context
        grounding_enabled = supports_grounding and not disable_grounding
        thinking_enabled = supports_thinking and not disable_thinking

        # Build capabilities list for user feedback
        if url_context_enabled:
            actual_capabilities.append("URL context")
        if grounding_enabled:
            actual_capabilities.append("web grounding")
        if thinking_enabled:
            actual_capabilities.append("thinking mode")

        # Enhanced user feedback for CLI
        print(f"🤖 Using Gemini model: {model_config}")
        if actual_capabilities:
            print(f"✨ Enhanced features enabled: {', '.join(actual_capabilities)}")
            if thinking_enabled:
                thinking_budget = os.getenv("THINKING_BUDGET")
                budget_info = (
                    f" (budget: {thinking_budget} tokens)"
                    if thinking_budget
                    else " (auto-budget)"
                )
                print(f"   💭 Thinking mode: Deep reasoning{budget_info}")
            if grounding_enabled:
                print("   🌐 Web grounding: Real-time information lookup")
            if url_context_enabled:
                print("   🔗 URL context: Enhanced web content understanding")
        else:
            print("⚡ Standard features: Basic text generation")

        # Log for debugging (less verbose than user output)
        capabilities_text = (
            f" (features: {', '.join(actual_capabilities)})"
            if actual_capabilities
            else " (basic)"
        )
        logger.info(f"Gemini configuration: {model_config}{capabilities_text}")

        # Configure tools (enabled by default with opt-out)
        tools: List[Any] = []

        # URL Context - enabled by default for supported models
        if url_context_enabled and types is not None:
            try:
                tools.append(types.Tool(url_context=types.UrlContext()))
            except (AttributeError, TypeError) as e:
                logger.warning(f"URL context configuration failed: {e}")

        # Google Search Grounding - enabled by default for supported models
        if grounding_enabled and types is not None:
            try:
                # Use GoogleSearch for newer models (Gemini 2.0+, 2.5+)
                if "gemini-2.0" in model_config or "gemini-2.5" in model_config:
                    google_search_tool = types.Tool(google_search=types.GoogleSearch())
                    tools.append(google_search_tool)
                else:
                    # Fallback to GoogleSearchRetrieval for older models
                    grounding_config = types.GoogleSearchRetrieval()
                    tools.append(types.Tool(google_search_retrieval=grounding_config))
            except (AttributeError, TypeError) as e:
                logger.warning(f"Grounding configuration failed: {e}")

        # Configure thinking mode - enabled by default for supported models
        thinking_config = None
        thinking_budget = os.getenv(
            "THINKING_BUDGET"
        )  # Let model auto-adjust if not specified
        include_thoughts = os.getenv("INCLUDE_THOUGHTS", "true").lower() == "true"

        if thinking_enabled:
            try:
                if "gemini-2.5-flash" in model_config:
                    # Full thinking support with optional budget control
                    config_params = {"include_thoughts": include_thoughts}
                    if thinking_budget and thinking_budget.strip():
                        try:
                            # budget_val = int(thinking_budget)  # Not used currently
                            # Note: thinking_budget parameter not supported in current API
                            # budget_msg = f"budget: {min(budget_val, 24576)}"  # Not used currently
                            pass
                        except (ValueError, TypeError):
                            # Invalid budget value, use auto-adjust
                            # budget_msg = "budget: auto-adjust"  # Not used currently
                            pass
                    else:
                        # budget_msg = "budget: auto-adjust"  # Not used currently
                        pass
                    thinking_config = (
                        types.ThinkingConfig(**config_params)
                        if types is not None
                        else None
                    )
                elif "gemini-2.5-pro" in model_config:
                    # Pro models support summaries only
                    thinking_config = (
                        types.ThinkingConfig(include_thoughts=include_thoughts)
                        if types is not None
                        else None
                    )
                    # budget_msg = "budget: N/A (Pro model)"  # Not used currently
            except (AttributeError, TypeError) as e:
                logger.warning(f"Thinking configuration failed: {e}")

        # Use the provided temperature (from CLI arg or function parameter)
        # Environment variable is handled at the caller level

        # Build configuration parameters
        config_params: Dict[str, Any] = {"max_output_tokens": 8000, "temperature": temperature}

        if tools:
            config_params["tools"] = tools

        if thinking_config:
            config_params["thinking_config"] = thinking_config

        if types is not None:
            config = types.GenerateContentConfig(**config_params)
        else:
            config = None

        # Create comprehensive review prompt
        review_prompt = f"""You are an expert code reviewer conducting a comprehensive code review. Based on the provided context, please provide detailed feedback.

{context_content}

Please provide a thorough code review that includes:
1. **Overall Assessment** - High-level evaluation of the implementation
2. **Code Quality & Best Practices** - Specific line-by-line feedback where applicable
3. **Architecture & Design** - Comments on system design and patterns
4. **Security Considerations** - Any security concerns or improvements
5. **Performance Implications** - Performance considerations and optimizations
6. **Testing & Maintainability** - Suggestions for testing and long-term maintenance
7. **Next Steps** - Recommendations for future work or improvements

Focus on being specific and actionable. When referencing files, include line numbers where relevant."""

        # Generate review
        logger.info("Sending context to Gemini for code review...")
        response = client.models.generate_content(
            model=model_config, contents=[review_prompt], config=config
        )

        # Format response metadata
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        # Format the response with metadata
        enabled_features: List[str] = []
        if supports_url_context and not disable_url_context and tools:
            # Check if URL context tool was actually added
            if any(hasattr(tool, "url_context") for tool in tools):
                enabled_features.append("URL context")
        if supports_grounding and not disable_grounding and tools:
            # Check if grounding tool was actually added
            if any(
                hasattr(tool, "google_search")
                or hasattr(tool, "google_search_retrieval")
                for tool in tools
            ):
                enabled_features.append("web grounding")
        if thinking_config:
            enabled_features.append("thinking mode")

        features_text = (
            ", ".join(enabled_features) if enabled_features else "basic capabilities"
        )

        # Format response based on include_formatting parameter
        response_text = response.text or "No response generated"
        if include_formatting:
            formatted_response = f"""# Comprehensive Code Review Feedback
*Generated on {datetime.now().strftime("%Y-%m-%d at %H:%M:%S")} using {model_config}*

{response_text}

---
*Review conducted by Gemini AI with {features_text}*
"""
        else:
            # Return raw response without headers/footers
            formatted_response = response_text

        # Return text directly or save to file based on return_text parameter
        if return_text:
            return formatted_response
        else:
            # Validate project_path is provided when saving to file
            if not project_path:
                raise ValueError("project_path is required when return_text=False")

            # Define output file path only when saving to file
            output_file = os.path.join(
                project_path, f"code-review-comprehensive-feedback-{timestamp}.md"
            )

            with open(output_file, "w", encoding="utf-8") as f:
                f.write(formatted_response)

            logger.info(f"Gemini review saved to: {output_file}")
            return output_file

    except Exception as e:
        logger.error(f"Failed to generate Gemini review: {e}")
        return None


class ConfigurationCache:
    """Cache for configuration discovery to improve performance."""

    def __init__(self):
        self.cache: Dict[str, Any] = {}
        self.mtimes: Dict[str, float] = {}

    def get_configurations(self, project_path: str) -> Optional[Dict[str, Any]]:
        """Get cached configurations if they exist and are up to date, otherwise discover and cache."""
        # Check if we have cached data
        if project_path not in self.cache:
            # No cached data, discover configurations
            configurations = _discover_project_configurations_uncached(project_path)
            self.set_configurations(project_path, configurations)
            return configurations

        # Check if any configuration files have been modified
        current_mtime = self._get_max_config_mtime(project_path)
        cached_mtime = self.mtimes.get(project_path, 0)

        if current_mtime > cached_mtime:
            # Configuration files have been modified, invalidate cache and rediscover
            self.invalidate(project_path)
            configurations = _discover_project_configurations_uncached(project_path)
            self.set_configurations(project_path, configurations)
            return configurations

        return self.cache[project_path]

    def set_configurations(self, project_path: str, configurations: Dict[str, Any]):
        """Cache configurations for a project."""
        self.cache[project_path] = configurations
        self.mtimes[project_path] = self._get_max_config_mtime(project_path)

    def invalidate(self, project_path: str):
        """Invalidate cache for a project."""
        if project_path in self.cache:
            del self.cache[project_path]
        if project_path in self.mtimes:
            del self.mtimes[project_path]

    def _get_max_config_mtime(self, project_path: str) -> float:
        """Get the maximum modification time of configuration files."""
        max_mtime = 0

        # Check CLAUDE.md files
        for claude_pattern in ["CLAUDE.md", "*/CLAUDE.md", "**/CLAUDE.md"]:
            claude_files = glob.glob(os.path.join(project_path, claude_pattern))
            for claude_file in claude_files:
                if os.path.isfile(claude_file):
                    max_mtime = max(max_mtime, os.path.getmtime(claude_file))

        # Check cursor rules
        cursorrules_file = os.path.join(project_path, ".cursorrules")
        if os.path.isfile(cursorrules_file):
            max_mtime = max(max_mtime, os.path.getmtime(cursorrules_file))

        cursor_rules_dir = os.path.join(project_path, ".cursor", "rules")
        if os.path.isdir(cursor_rules_dir):
            for root, _, files in os.walk(cursor_rules_dir):
                for file in files:
                    if file.endswith(".mdc"):
                        file_path = os.path.join(root, file)
                        max_mtime = max(max_mtime, os.path.getmtime(file_path))

        return max_mtime


# Global cache instance
_config_cache = ConfigurationCache()


def _discover_project_configurations_uncached(project_path: str) -> Dict[str, Any]:
    """
    High-performance discovery of Claude memory files and Cursor rules from project.

    Uses async/concurrent operations by default with bulletproof fallbacks.

    Args:
        project_path: Path to project root

    Returns:
        Dictionary with discovered configurations, performance stats, and any errors
    """

    try:
        # Import configuration modules (relative imports for same package)
        try:
            # Try importing from same directory first
            import sys
            import os

            current_dir = os.path.dirname(__file__)
            if current_dir not in sys.path:
                sys.path.insert(0, current_dir)

            from async_configuration_discovery import discover_all_configurations
            from claude_memory_parser import parse_claude_memory_with_imports
            from cursor_rules_parser import parse_cursor_rules_directory
            from configuration_context import ClaudeMemoryFile, CursorRule
        except ImportError:
            # Fallback: try absolute imports
            from src.async_configuration_discovery import discover_all_configurations
            from src.claude_memory_parser import parse_claude_memory_with_imports
            from src.cursor_rules_parser import parse_cursor_rules_directory
            from src.configuration_context import ClaudeMemoryFile, CursorRule

        claude_memory_files: List[Any] = []
        cursor_rules: List[Any] = []
        discovery_errors: List[Dict[str, Any]] = []

        # Use high-performance discovery (includes performance stats)
        discovery_result = discover_all_configurations(
            project_path, include_claude_memory=True, include_cursor_rules=True
        )

        # Log performance stats
        perf_stats = discovery_result.get("performance_stats", {})
        discovery_time = perf_stats.get("discovery_time_ms", 0)
        files_count = perf_stats.get("total_files_read", 0)
        fallback_method = perf_stats.get("fallback_method", "async")

        if discovery_time > 0:
            logger.info(
                f"🚀 Configuration discovery completed in {discovery_time}ms "
                f"({files_count} files) using {fallback_method} method"
            )

        # Process Claude memory files with improved error handling
        try:
            claude_files_data = discovery_result.get("claude_memory_files", [])

            for claude_file_data in claude_files_data:
                try:
                    # Validate file content before parsing
                    content = claude_file_data.get("content", "")

                    # Check for binary content (null bytes indicate binary)
                    if "\x00" in content:
                        raise ValueError(
                            f"Binary content detected in CLAUDE.md file: {claude_file_data['file_path']}"
                        )

                    # Parse with import resolution
                    parsed_data = parse_claude_memory_with_imports(
                        claude_file_data["file_path"], project_root=project_path
                    )

                    # Determine hierarchy level
                    hierarchy_level = claude_file_data.get("scope", "project")

                    # Create ClaudeMemoryFile object
                    memory_file = ClaudeMemoryFile(
                        file_path=claude_file_data["file_path"],
                        content=parsed_data["content"],
                        hierarchy_level=hierarchy_level,
                        imports=parsed_data.get("successful_imports", []),
                        resolved_content=parsed_data.get(
                            "resolved_content", parsed_data["content"]
                        ),
                    )

                    claude_memory_files.append(memory_file)

                    # Add any import errors to discovery errors
                    discovery_errors.extend(parsed_data.get("import_errors", []))

                except Exception as e:
                    discovery_errors.append(
                        {
                            "file_path": claude_file_data["file_path"],
                            "error_type": "claude_parsing_error",
                            "error_message": str(e),
                        }
                    )

        except Exception as e:
            discovery_errors.append(
                {"error_type": "claude_discovery_error", "error_message": str(e)}
            )

        # Process Cursor rules from high-performance discovery
        try:
            cursor_files_data = discovery_result.get("cursor_rules", [])

            for cursor_file_data in cursor_files_data:
                try:
                    # Handle both legacy and modern formats
                    if cursor_file_data.get("format") == "cursorrules":
                        # Legacy .cursorrules file
                        legacy_rule = CursorRule(
                            file_path=cursor_file_data["file_path"],
                            content=cursor_file_data["content"],
                            rule_type="legacy",
                            precedence=1000,  # Lower precedence than modern rules
                            description="Legacy cursorrules file",
                            globs=["**/*"],  # Apply to all files by default
                            always_apply=True,
                            metadata={"source": "legacy_cursorrules"},
                        )
                        cursor_rules.append(legacy_rule)

                    elif cursor_file_data.get("format") == "mdc":
                        # Modern .mdc file
                        parsed_data = cursor_file_data.get("parsed_data", {})

                        modern_rule = CursorRule(
                            file_path=cursor_file_data["file_path"],
                            content=cursor_file_data["content"],
                            rule_type="modern",
                            precedence=parsed_data.get("precedence", 500),
                            description=parsed_data.get(
                                "description", "Modern MDC rule"
                            ),
                            globs=parsed_data.get("globs", ["**/*"]),
                            always_apply=parsed_data.get("alwaysApply", False),
                            metadata=parsed_data.get("metadata", {}),
                        )
                        cursor_rules.append(modern_rule)

                except Exception as e:
                    discovery_errors.append(
                        {
                            "file_path": cursor_file_data.get("file_path", "unknown"),
                            "error_type": "cursor_parsing_error",
                            "error_message": str(e),
                        }
                    )

            # Legacy fallback: use original parser if new format doesn't work
            if not cursor_files_data:
                cursor_data = parse_cursor_rules_directory(project_path)

                # Add any parsing errors to discovery errors
                discovery_errors.extend(cursor_data.get("parse_errors", []))

                # Convert legacy rules
                if cursor_data.get("legacy_rules"):
                    legacy_data = cursor_data["legacy_rules"]
                    legacy_rule = CursorRule(
                        file_path=legacy_data["file_path"],
                        content=legacy_data["content"],
                        rule_type=legacy_data["type"],
                        precedence=legacy_data["precedence"],
                        description=legacy_data["description"],
                        globs=legacy_data["globs"],
                        always_apply=legacy_data["always_apply"],
                        metadata=legacy_data["metadata"],
                    )
                    cursor_rules.append(legacy_rule)

                # Convert modern rules
                for modern_data in cursor_data.get("modern_rules", []):
                    modern_rule = CursorRule(
                        file_path=modern_data["file_path"],
                        content=modern_data["content"],
                        rule_type=modern_data["type"],
                        precedence=modern_data["precedence"],
                        description=modern_data["description"],
                        globs=modern_data["globs"],
                        always_apply=modern_data["always_apply"],
                        metadata=modern_data["metadata"],
                    )
                    cursor_rules.append(modern_rule)

        except Exception as e:
            discovery_errors.append(
                {"error_type": "cursor_discovery_error", "error_message": str(e)}
            )

        result = {
            "claude_memory_files": claude_memory_files,
            "cursor_rules": cursor_rules,
            "discovery_errors": discovery_errors,
            "performance_stats": perf_stats,  # Include performance metrics
        }

        return result

    except ImportError as e:
        # Configuration modules not available - return empty result
        logger.warning(f"Configuration discovery modules not available: {e}")
        return {
            "claude_memory_files": [],
            "cursor_rules": [],
            "discovery_errors": [
                {"error_type": "module_import_error", "error_message": str(e)}
            ],
        }


def discover_project_configurations(project_path: str) -> Dict[str, Any]:
    """
    Discover Claude memory files and Cursor rules from project (cached version).

    Args:
        project_path: Path to project root

    Returns:
        Dictionary with discovered configurations and any errors
    """
    # Use cache for performance
    configurations = _config_cache.get_configurations(project_path)
    if configurations is None:
        # Fallback if cache returns None
        return {
            "claude_memory": [],
            "cursor_rules": [],
            "discovery_errors": [
                {
                    "error_type": "cache_error",
                    "error_message": "Failed to get configurations from cache",
                }
            ],
        }
    return configurations


def discover_project_configurations_with_fallback(project_path: str) -> Dict[str, Any]:
    """
    Discover configurations with comprehensive error handling and fallback.

    Args:
        project_path: Path to project root

    Returns:
        Dictionary with discovered configurations, always includes empty lists on failure
    """
    try:
        return discover_project_configurations(project_path)
    except Exception as e:
        logger.warning(f"Configuration discovery failed: {e}")
        return {
            "claude_memory_files": [],
            "cursor_rules": [],
            "discovery_errors": [
                {"error_type": "discovery_failure", "error_message": str(e)}
            ],
        }


def discover_project_configurations_with_flags(
    project_path: str,
    include_claude_memory: bool = True,
    include_cursor_rules: bool = False,
) -> Dict[str, Any]:
    """
    Discover configurations with flag-based inclusion control.

    Args:
        project_path: Path to project root
        include_claude_memory: Whether to include CLAUDE.md files
        include_cursor_rules: Whether to include Cursor rules files

    Returns:
        Dictionary with discovered configurations based on flags
    """
    try:
        # Start with empty configuration
        result: Dict[str, Any] = {"claude_memory_files": [], "cursor_rules": [], "discovery_errors": []}

        # Import configuration modules
        try:
            from configuration_discovery import (
                discover_all_claude_md_files,
                discover_all_cursor_rules,
            )
            from claude_memory_parser import parse_claude_memory_with_imports
            from cursor_rules_parser import parse_cursor_rules_directory
            from configuration_context import ClaudeMemoryFile, CursorRule
        except ImportError:
            try:
                from src.configuration_discovery import (
                    discover_all_claude_md_files,
                    discover_all_cursor_rules,
                )
                from src.claude_memory_parser import parse_claude_memory_with_imports
                from src.cursor_rules_parser import parse_cursor_rules_directory
                from src.configuration_context import ClaudeMemoryFile, CursorRule
            except ImportError as e:
                logger.warning(f"Failed to import configuration modules: {e}")
                return result

        # Discover Claude memory files if enabled
        if include_claude_memory:
            try:
                claude_files = discover_all_claude_md_files(project_path)
                for file_info in claude_files:
                    try:
                        file_path = file_info["file_path"]
                        parsed_data = parse_claude_memory_with_imports(
                            file_path, project_path
                        )

                        # Create proper ClaudeMemoryFile object
                        memory_file = ClaudeMemoryFile(
                            file_path=file_path,
                            content=parsed_data.get("content", ""),
                            hierarchy_level=file_info.get("scope", "project"),
                            imports=parsed_data.get("successful_imports", []),
                            resolved_content=parsed_data.get(
                                "resolved_content", parsed_data.get("content", "")
                            ),
                        )
                        result["claude_memory_files"].append(memory_file)
                    except Exception as e:
                        file_path = file_info.get("file_path", "unknown")
                        logger.warning(
                            f"Failed to parse Claude memory file {file_path}: {e}"
                        )
                        result["discovery_errors"].append(
                            {
                                "error_type": "claude_parsing_error",
                                "file_path": file_path,
                                "error_message": str(e),
                            }
                        )
            except Exception as e:
                logger.warning(f"Failed to discover Claude memory files: {e}")
                result["discovery_errors"].append(
                    {"error_type": "claude_discovery_error", "error_message": str(e)}
                )

        # Discover Cursor rules if enabled
        if include_cursor_rules:
            try:
                cursor_files = discover_all_cursor_rules(project_path)
                for file_path in cursor_files:
                    try:
                        # Parse cursor rules directory to get structured rules
                        rules_data = parse_cursor_rules_directory(project_path)

                        # Add legacy rules
                        if rules_data.get("legacy_rules"):
                            legacy_data = rules_data["legacy_rules"]
                            rule = CursorRule(
                                file_path=legacy_data["file_path"],
                                content=legacy_data["content"],
                                rule_type=legacy_data["type"],
                                precedence=legacy_data["precedence"],
                                description=legacy_data["description"],
                                globs=legacy_data["globs"],
                                always_apply=legacy_data["always_apply"],
                                metadata=legacy_data["metadata"],
                            )
                            result["cursor_rules"].append(rule)

                        # Add modern rules
                        for modern_data in rules_data.get("modern_rules", []):
                            rule = CursorRule(
                                file_path=modern_data["file_path"],
                                content=modern_data["content"],
                                rule_type=modern_data["type"],
                                precedence=modern_data["precedence"],
                                description=modern_data["description"],
                                globs=modern_data["globs"],
                                always_apply=modern_data["always_apply"],
                                metadata=modern_data["metadata"],
                            )
                            result["cursor_rules"].append(rule)

                        # Add parsing errors
                        result["discovery_errors"].extend(
                            rules_data.get("parse_errors", [])
                        )

                        # Break after processing the directory
                        break

                    except Exception as e:
                        logger.warning(f"Failed to parse Cursor rules: {e}")
                        result["discovery_errors"].append(
                            {
                                "error_type": "cursor_parsing_error",
                                "file_path": file_path,
                                "error_message": str(e),
                            }
                        )
            except Exception as e:
                logger.warning(f"Failed to discover Cursor rules: {e}")
                result["discovery_errors"].append(
                    {"error_type": "cursor_discovery_error", "error_message": str(e)}
                )

        return result

    except Exception as e:
        logger.warning(f"Configuration discovery with flags failed: {e}")
        return {
            "claude_memory_files": [],
            "cursor_rules": [],
            "discovery_errors": [
                {"error_type": "discovery_failure", "error_message": str(e)}
            ],
        }


def merge_configurations_into_context(
    existing_context: Dict[str, Any],
    claude_memory_files: List[Any],
    cursor_rules: List[Any],
) -> Dict[str, Any]:
    """
    Merge discovered configurations into existing review context.

    Args:
        existing_context: Existing context dictionary
        claude_memory_files: List of ClaudeMemoryFile objects
        cursor_rules: List of CursorRule objects

    Returns:
        Enhanced context dictionary with configuration content
    """
    try:
        try:
            from configuration_context import create_configuration_context
        except ImportError:
            from src.configuration_context import create_configuration_context

        # Create configuration context
        config_context = create_configuration_context(claude_memory_files, cursor_rules)

        # Enhanced context with configuration data
        enhanced_context = existing_context.copy()
        enhanced_context.update(
            {
                "configuration_content": config_context["merged_content"],
                "claude_memory_files": claude_memory_files,
                "cursor_rules": cursor_rules,
                "auto_apply_rules": config_context["auto_apply_rules"],
                "configuration_errors": config_context["error_summary"],
            }
        )

        return enhanced_context

    except Exception as e:
        logger.warning(f"Failed to merge configurations: {e}")
        # Return original context with empty configuration sections
        enhanced_context = existing_context.copy()
        enhanced_context.update(
            {
                "configuration_content": "",
                "claude_memory_files": claude_memory_files,
                "cursor_rules": cursor_rules,
                "auto_apply_rules": [],
                "configuration_errors": [
                    {"error_type": "merge_error", "error_message": str(e)}
                ],
            }
        )
        return enhanced_context


def format_configuration_context_for_ai(
    claude_memory_files: List[Any], cursor_rules: List[Any]
) -> str:
    """
    Format configuration context for optimal AI consumption.

    Args:
        claude_memory_files: List of ClaudeMemoryFile objects
        cursor_rules: List of CursorRule objects

    Returns:
        Formatted configuration content string
    """
    try:
        try:
            from configuration_context import (
                merge_claude_memory_content,
                merge_cursor_rules_content,
            )
        except ImportError:
            from src.configuration_context import (
                merge_claude_memory_content,
                merge_cursor_rules_content,
            )

        # Format Claude memory content
        claude_content = merge_claude_memory_content(claude_memory_files)

        # Format Cursor rules content
        cursor_content = merge_cursor_rules_content(cursor_rules)

        # Combine with clear sections
        sections: List[str] = []

        if claude_content:
            sections.append("# Claude Memory Configuration\n\n" + claude_content)

        if cursor_content:
            sections.append("# Cursor Rules Configuration\n\n" + cursor_content)

        return "\n\n".join(sections)

    except Exception as e:
        logger.warning(f"Failed to format configuration context: {e}")
        return ""


def get_applicable_rules_for_files(
    cursor_rules: List[Any], changed_files: List[str]
) -> List[Any]:
    """
    Get Cursor rules applicable to changed files.

    Args:
        cursor_rules: List of CursorRule objects
        changed_files: List of changed file paths

    Returns:
        List of applicable CursorRule objects
    """
    try:
        try:
            from configuration_context import get_all_cursor_rules
        except ImportError:
            from src.configuration_context import get_all_cursor_rules

        # Simplified approach: return all cursor rules
        return get_all_cursor_rules(cursor_rules)

    except Exception as e:
        logger.warning(f"Failed to get applicable rules: {e}")
        return []


def generate_enhanced_review_context(
    project_path: str,
    scope: str = "recent_phase",
    changed_files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Generate enhanced review context with configuration discovery.

    Args:
        project_path: Path to project root
        scope: Review scope
        changed_files: Optional list of changed file paths

    Returns:
        Enhanced context dictionary with configuration data
    """
    # Discover configurations
    configurations = discover_project_configurations_with_fallback(project_path)

    # Get changed files if not provided
    if changed_files is None:
        git_changed_files = get_changed_files(project_path)
        changed_files = [f["path"] for f in git_changed_files]

    # Ensure we have valid data for rule processing
    cursor_rules: List[Any] = configurations.get("cursor_rules", []) or []
    changed_files = changed_files or []

    # Get applicable rules for changed files
    applicable_rules = get_applicable_rules_for_files(cursor_rules, changed_files)

    # Create basic context structure
    basic_context = {
        "prd_summary": "Enhanced code review with configuration context",
        "current_phase_number": "1.0",
        "current_phase_description": "Configuration-enhanced review",
        "changed_files": changed_files,
        "project_path": project_path,
    }

    # Merge configurations
    enhanced_context = merge_configurations_into_context(
        basic_context,
        configurations["claude_memory_files"],
        configurations["cursor_rules"],
    )

    # Add applicable rules
    enhanced_context["applicable_rules"] = applicable_rules

    return enhanced_context


@dataclass
class CodeReviewConfig:
    """Configuration for code review generation."""

    project_path: Optional[str] = None
    phase: Optional[str] = None  # Legacy parameter
    output: Optional[str] = None
    enable_gemini_review: bool = True
    scope: str = "recent_phase"
    phase_number: Optional[str] = None
    task_number: Optional[str] = None
    temperature: float = 0.5
    task_list: Optional[str] = None
    default_prompt: Optional[str] = None
    compare_branch: Optional[str] = None
    target_branch: Optional[str] = None
    github_pr_url: Optional[str] = None
    include_claude_memory: bool = True
    include_cursor_rules: bool = False
    raw_context_only: bool = False
    auto_prompt_content: Optional[str] = None


def generate_code_review_context_main(
    project_path: Optional[str] = None,
    phase: Optional[str] = None,
    output: Optional[str] = None,
    enable_gemini_review: bool = True,
    scope: str = "recent_phase",
    phase_number: Optional[str] = None,
    task_number: Optional[str] = None,
    temperature: float = 0.5,
    task_list: Optional[str] = None,
    default_prompt: Optional[str] = None,
    compare_branch: Optional[str] = None,
    target_branch: Optional[str] = None,
    github_pr_url: Optional[str] = None,
    include_claude_memory: bool = True,
    include_cursor_rules: bool = False,
    raw_context_only: bool = False,
    auto_prompt_content: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """
    Main function to generate code review context with enhanced scope support.

    Args:
        project_path: Path to project root
        phase: Override current phase detection (legacy parameter)
        output: Custom output file path
        enable_gemini_review: Whether to generate AI review
        scope: Review scope - "recent_phase", "full_project", "specific_phase", "specific_task"
        phase_number: Phase number for specific_phase scope (e.g., "2.0")
        task_number: Task number for specific_task scope (e.g., "1.2")
        temperature: Temperature for AI model (0.0-2.0)
        task_list: Custom task list filename
        default_prompt: Default prompt when no task list found
        compare_branch: Source branch for comparison (deprecated - use GitHub PR)
        target_branch: Target branch for comparison (deprecated - use GitHub PR)
        github_pr_url: GitHub PR URL for analysis
        include_claude_memory: Whether to include CLAUDE.md files (default: True)
        include_cursor_rules: Whether to include Cursor rules files (default: False)
        raw_context_only: Exclude default AI review instructions (default: False)
        auto_prompt_content: Generated meta-prompt to embed in user_instructions (default: None)

    Returns:
        Tuple of (context_file_path, gemini_review_path). gemini_review_path is None if not generated.
    """
    # Create config object for internal use (better maintainability)
    config = CodeReviewConfig(
        project_path=project_path,
        phase=phase,
        output=output,
        enable_gemini_review=enable_gemini_review,
        scope=scope,
        phase_number=phase_number,
        task_number=task_number,
        temperature=temperature,
        task_list=task_list,
        default_prompt=default_prompt,
        compare_branch=compare_branch,
        target_branch=target_branch,
        github_pr_url=github_pr_url,
        include_claude_memory=include_claude_memory,
        include_cursor_rules=include_cursor_rules,
        raw_context_only=raw_context_only,
        auto_prompt_content=auto_prompt_content,
    )

    return _generate_code_review_context_impl(config)


def _generate_code_review_context_impl(
    config: CodeReviewConfig,
) -> tuple[str, Optional[str]]:
    """
    Internal implementation of code review context generation.

    Args:
        config: CodeReviewConfig object containing all configuration parameters

    Returns:
        Tuple of (context_file_path, gemini_review_path). gemini_review_path is None if not generated.
    """
    if config.project_path is None:
        config.project_path = os.getcwd()

    # Detect and validate review mode
    review_modes: List[str] = []
    if config.github_pr_url:
        review_modes.append("github_pr")
    if not review_modes:
        review_modes.append("task_list_based")

    # Validate mutually exclusive modes
    if len(review_modes) > 1:
        error_msg = """Multiple review modes detected. Please use only one:

Working examples:
  # Task list based review (default)
  generate-code-review .
  
  # Branch comparison review
  generate-code-review . --compare-branch feature/auth
  
  # GitHub PR review  
  generate-code-review --github-pr-url https://github.com/owner/repo/pull/123
  
  # NOT valid - conflicting modes
  generate-code-review . --compare-branch feature/auth --github-pr-url https://github.com/owner/repo/pull/123"""
        raise ValueError(error_msg)

    # Validate scope parameter
    valid_scopes = ["recent_phase", "full_project", "specific_phase", "specific_task"]
    if config.scope not in valid_scopes:
        raise ValueError(
            f"Invalid scope '{config.scope}'. Must be one of: {', '.join(valid_scopes)}"
        )

    # Validate scope-specific parameters
    if config.scope == "specific_phase":
        if not config.phase_number:
            error_msg = """phase_number is required when scope is 'specific_phase'

Working examples:
  # Review a specific phase
  generate-code-review . --scope specific_phase --phase-number 2.0
  
  # Review first phase
  generate-code-review . --scope specific_phase --phase-number 1.0
  
  # Use environment variable for API key
  GEMINI_API_KEY=your_key generate-code-review . --scope specific_phase --phase-number 3.0"""
            raise ValueError(error_msg)
        if not re.match(r"^\d+\.0$", config.phase_number):
            error_msg = f"""Invalid phase_number format '{config.phase_number}'. Must be in format 'X.0'

Working examples:
  # Correct formats
  generate-code-review . --scope specific_phase --phase-number 1.0
  generate-code-review . --scope specific_phase --phase-number 2.0
  generate-code-review . --scope specific_phase --phase-number 10.0
  
  # Incorrect formats
  --phase-number 1    ❌ (missing .0)
  --phase-number 1.1  ❌ (phases end in .0)
  --phase-number v1.0 ❌ (no prefix allowed)"""
            raise ValueError(error_msg)

    if config.scope == "specific_task":
        if not config.task_number:
            error_msg = """task_number is required when scope is 'specific_task'

Working examples:
  # Review a specific task
  generate-code-review . --scope specific_task --task-number 1.2
  
  # Review first subtask of phase 2
  generate-code-review . --scope specific_task --task-number 2.1
  
  # Use with custom temperature
  generate-code-review . --scope specific_task --task-number 3.4 --temperature 0.3"""
            raise ValueError(error_msg)
        if not re.match(
            r"^\d+\.\d+$", config.task_number
        ) or config.task_number.endswith(".0"):
            error_msg = f"""Invalid task_number format '{config.task_number}'. Must be in format 'X.Y'

Working examples:
  # Correct formats
  generate-code-review . --scope specific_task --task-number 1.1
  generate-code-review . --scope specific_task --task-number 2.3
  generate-code-review . --scope specific_task --task-number 10.15
  
  # Incorrect formats
  --task-number 1     ❌ (missing subtask number)
  --task-number 1.0   ❌ (use specific_phase for X.0)
  --task-number 1.a   ❌ (must be numeric)"""
            raise ValueError(error_msg)

    # Validate GitHub PR URL if provided
    if config.github_pr_url:
        try:
            # Import here to avoid circular imports
            # Check if GitHub PR integration is available
            if not parse_github_pr_url:
                raise ImportError("GitHub PR integration not available")
            parse_github_pr_url(
                config.github_pr_url
            )  # This will raise ValueError if invalid
        except ValueError as e:
            error_msg = f"""Invalid GitHub PR URL: {e}

Working examples:
  # Standard GitHub PR
  generate-code-review --github-pr-url https://github.com/microsoft/vscode/pull/123
  
  # GitHub Enterprise
  generate-code-review --github-pr-url https://github.company.com/team/project/pull/456
  
  # With additional parameters
  generate-code-review --github-pr-url https://github.com/owner/repo/pull/789 --temperature 0.3"""
            raise ValueError(error_msg)

    try:
        # Initial user feedback
        print(
            f"🔍 Analyzing project: {os.path.basename(os.path.abspath(config.project_path))}"
        )

        # Display review mode
        current_mode = review_modes[0]
        if current_mode == "github_pr":
            print("🔗 Review mode: GitHub PR analysis")
            print(f"🌐 PR URL: {config.github_pr_url}")
        else:
            print(f"📊 Review scope: {config.scope}")

        if config.enable_gemini_review:
            print(f"🌡️  AI temperature: {config.temperature}")

        # Load model config for default prompt
        model_config = load_model_config()

        # Find project files (PRD is now optional)
        prd_file, task_file = find_project_files(config.project_path, config.task_list)

        # Handle different scenarios
        prd_summary = None
        task_data: Optional[Dict[str, Any]] = None

        if task_file:
            # We have a task list - read and parse it
            with open(task_file, "r", encoding="utf-8") as f:
                task_content = f.read()
            task_data = parse_task_list(task_content)

            if prd_file:
                # We have both PRD and task list - use PRD summary
                with open(prd_file, "r", encoding="utf-8") as f:
                    prd_content = f.read()
                prd_summary = extract_prd_summary(prd_content)
            else:
                # Generate summary from task list
                prd_summary = generate_prd_summary_from_task_list(task_data)
        else:
            # No task list - use default prompt
            if config.default_prompt:
                prd_summary = config.default_prompt
            else:
                prd_summary = model_config["defaults"]["default_prompt"]

            # Create minimal task data for template
            task_data = {
                "total_phases": 0,
                "current_phase_number": "General Review",
                "current_phase_description": "Code review without specific task context",
                "previous_phase_completed": "",
                "next_phase": "",
                "subtasks_completed": [],
                "phases": [],
            }

        # Handle scope-based review logic
        if config.scope == "recent_phase":
            # Smart defaulting: if ALL phases are complete, automatically review full project
            phases: List[PhaseData] = task_data.get("phases", []) if task_data else []
            all_phases_complete = all(p.get("subtasks_complete", False) for p in phases)

            if all_phases_complete and phases:
                # All phases complete - automatically switch to full project review
                completed_phases: List[PhaseData] = [
                    p for p in phases if p.get("subtasks_complete", False)
                ]
                all_completed_subtasks: List[Any] = []
                phase_descriptions: List[str] = []
                for p in completed_phases:
                    all_completed_subtasks.extend(p["subtasks_completed"])
                    phase_descriptions.append(f"{p['number']} {p['description']}")

                task_data.update(
                    {
                        "current_phase_number": f"Full Project ({len(completed_phases)} phases)",
                        "current_phase_description": f"Analysis of all completed phases: {', '.join(phase_descriptions)}",
                        "previous_phase_completed": "",
                        "next_phase": "",
                        "subtasks_completed": all_completed_subtasks,
                    }
                )
                # Update scope to reflect the automatic expansion
                config.scope = "full_project"
            else:
                # Use default behavior (already parsed by detect_current_phase)
                # Override with legacy phase parameter if provided
                if config.phase:
                    # Find the specified phase
                    phases: List[PhaseData] = task_data.get("phases", []) if task_data else []
                    for i, p in enumerate(phases):
                        if p["number"] == config.phase:
                            # Find previous completed phase
                            previous_phase_completed = ""
                            if i > 0:
                                prev_phase = phases[i - 1]
                                previous_phase_completed = f"{prev_phase['number']} {prev_phase['description']}"

                            # Find next phase
                            next_phase = ""
                            if i < len(phases) - 1:
                                next_phase_obj = phases[i + 1]
                                next_phase = f"{next_phase_obj['number']} {next_phase_obj['description']}"

                            # Override the detected phase data
                            task_data.update(
                                {
                                    "current_phase_number": p["number"],
                                    "current_phase_description": p["description"],
                                    "previous_phase_completed": previous_phase_completed,
                                    "next_phase": next_phase,
                                    "subtasks_completed": p["subtasks_completed"],
                                }
                            )
                            break

        elif config.scope == "full_project":
            # Analyze all completed phases
            phases: List[PhaseData] = task_data.get("phases", []) if task_data else []
            completed_phases = [p for p in phases if p.get("subtasks_complete", False)]
            if completed_phases:
                # Use summary information for all completed phases
                all_completed_subtasks = []
                phase_descriptions = []
                for p in completed_phases:
                    all_completed_subtasks.extend(p["subtasks_completed"])
                    phase_descriptions.append(f"{p['number']} {p['description']}")

                task_data.update(
                    {
                        "current_phase_number": f"Full Project ({len(completed_phases)} phases)",
                        "current_phase_description": f"Analysis of all completed phases: {', '.join(phase_descriptions)}",
                        "previous_phase_completed": "",
                        "next_phase": "",
                        "subtasks_completed": all_completed_subtasks,
                    }
                )
            else:
                # No completed phases, use default behavior
                pass

        elif config.scope == "specific_phase":
            # Find and validate the specified phase
            target_phase = None
            phases: List[PhaseData] = task_data.get("phases", []) if task_data else []
            for i, p in enumerate(phases):
                if p["number"] == config.phase_number:
                    target_phase = (i, p)
                    break

            if target_phase is None:
                available_phases = [p["number"] for p in phases]
                error_msg = f"""Phase {config.phase_number} not found in task list

Available phases: {', '.join(available_phases) if available_phases else 'none found'}

Working examples:
  # Use an available phase number
  {f'generate-code-review . --scope specific_phase --phase-number {available_phases[0]}' if available_phases else 'generate-code-review . --scope recent_phase  # Use default scope instead'}
  
  # List all phases
  generate-code-review . --scope full_project
  
  # Use default scope (most recent incomplete phase)
  generate-code-review ."""
                raise ValueError(error_msg)

            i, p = target_phase
            # Find previous completed phase
            previous_phase_completed = ""
            if i > 0:
                prev_phase = phases[i - 1]
                previous_phase_completed = (
                    f"{prev_phase['number']} {prev_phase['description']}"
                )

            # Find next phase
            next_phase = ""
            if i < len(phases) - 1:
                next_phase_obj = phases[i + 1]
                next_phase = (
                    f"{next_phase_obj['number']} {next_phase_obj['description']}"
                )

            # Override with specific phase data
            task_data.update(
                {
                    "current_phase_number": p["number"],
                    "current_phase_description": p["description"],
                    "previous_phase_completed": previous_phase_completed,
                    "next_phase": next_phase,
                    "subtasks_completed": p["subtasks_completed"],
                }
            )

        elif config.scope == "specific_task":
            # Find and validate the specified task
            target_task = None
            target_phase = None
            phases: List[PhaseData] = task_data.get("phases", []) if task_data else []
            for i, p in enumerate(phases):
                for subtask in p["subtasks"]:
                    if subtask["number"] == config.task_number:
                        target_task = subtask
                        target_phase = (i, p)
                        break
                if target_task:
                    break

            if target_task is None or target_phase is None:
                # Get available tasks from all phases
                available_tasks: List[str] = []
                for phase in phases:
                    subtasks = phase.get("subtasks", [])
                    for subtask in subtasks:
                        available_tasks.append(subtask["number"])

                error_msg = f"""Task {config.task_number} not found in task list

Available tasks: {', '.join(available_tasks[:10]) if available_tasks else 'none found'}{' (showing first 10)' if len(available_tasks) > 10 else ''}

Working examples:
  # Use an available task number
  {f'generate-code-review . --scope specific_task --task-number {available_tasks[0]}' if available_tasks else 'generate-code-review . --scope recent_phase  # Use default scope instead'}
  
  # Review entire phase instead
  generate-code-review . --scope specific_phase --phase-number {config.task_number.split('.')[0] if config.task_number else '1'}.0
  
  # Use default scope (most recent incomplete phase)
  generate-code-review ."""
                raise ValueError(error_msg)

            # Type guard: At this point we know target_phase is not None and is a tuple
            assert (
                target_phase is not None
            ), "target_phase should not be None after validation"
            i, p = target_phase
            # Override with specific task data
            task_data.update(
                {
                    "current_phase_number": target_task["number"],
                    "current_phase_description": f"Specific task: {target_task['description']} (from {p['number']} {p['description']})",
                    "previous_phase_completed": "",
                    "next_phase": "",
                    "subtasks_completed": [
                        f"{target_task['number']} {target_task['description']}"
                    ],
                }
            )

        # Discover configurations early for integration
        config_types: List[str] = []
        if config.include_claude_memory:
            config_types.append("Claude memory")
        if config.include_cursor_rules:
            config_types.append("Cursor rules")

        if config_types:
            print(f"🔍 Discovering {' and '.join(config_types)}...")
            configurations: Dict[str, Any] = discover_project_configurations_with_flags(
                config.project_path,
                config.include_claude_memory,
                config.include_cursor_rules,
            )
        else:
            print("ℹ️  Configuration discovery disabled")
            configurations: Dict[str, Any] = {
                "claude_memory_files": [],
                "cursor_rules": [],
                "discovery_errors": [],
            }

        claude_memory_files_raw = configurations.get("claude_memory_files", [])
        cursor_rules_raw = configurations.get("cursor_rules", [])
        discovery_errors_raw = configurations.get("discovery_errors", [])
        
        # Import types at the top of the function
        try:
            from configuration_context import ClaudeMemoryFile, CursorRule
        except ImportError:
            from src.configuration_context import ClaudeMemoryFile, CursorRule
        
        claude_memory_files: List[ClaudeMemoryFile] = claude_memory_files_raw if isinstance(claude_memory_files_raw, list) else []
        cursor_rules: List[CursorRule] = cursor_rules_raw if isinstance(cursor_rules_raw, list) else []
        discovery_errors: List[Dict[str, Any]] = discovery_errors_raw if isinstance(discovery_errors_raw, list) else []
        
        claude_files_count = len(claude_memory_files)
        cursor_rules_count = len(cursor_rules)
        errors_count = len(discovery_errors)

        if claude_files_count > 0 or cursor_rules_count > 0:
            print(
                f"✅ Found {claude_files_count} Claude memory files, {cursor_rules_count} Cursor rules"
            )
        else:
            print("ℹ️  No configuration files found (this is optional)")

        if errors_count > 0:
            print(f"⚠️  {errors_count} configuration discovery errors (will continue)")

        # Get git changes based on review mode
        changed_files: List[Dict[str, Any]] = []
        pr_data: Optional[Dict[str, Any]] = None

        if current_mode == "github_pr":
            # GitHub PR analysis mode
            print("🔄 Fetching PR data from GitHub...")
            try:
                # Check if GitHub PR integration is available
                if get_complete_pr_analysis is None:
                    raise ImportError("GitHub PR integration not available")

                # Type guard: Ensure github_pr_url is not None
                if config.github_pr_url is None:
                    raise ValueError("GitHub PR URL is required for PR analysis mode")

                pr_analysis = get_complete_pr_analysis(config.github_pr_url)

                # Convert PR file changes to our expected format
                for file_change in pr_analysis["file_changes"]["changed_files"]:
                    changed_files.append(
                        {
                            "path": os.path.join(
                                config.project_path, file_change["path"]
                            ),
                            "status": f"PR-{file_change['status']}",
                            "content": file_change.get(
                                "patch", "[Content not available]"
                            ),
                        }
                    )

                # Store PR metadata for template
                pr_data = {
                    "mode": "github_pr",
                    "pr_data": pr_analysis["pr_data"],
                    "summary": pr_analysis["file_changes"]["summary"],
                    "repository": pr_analysis["repository"],
                }

                print(f"✅ Found {len(changed_files)} changed files in PR")
                print(
                    f"📊 Files: +{pr_data['summary']['files_added']} "
                    f"~{pr_data['summary']['files_modified']} "
                    f"-{pr_data['summary']['files_deleted']}"
                )

            except Exception as e:
                print(f"❌ Failed to fetch PR data: {e}")
                # Fallback to task list mode
                changed_files = get_changed_files(config.project_path)

        else:
            # Task list based mode (default)
            changed_files = get_changed_files(config.project_path)

        # Generate file tree
        file_tree = generate_file_tree(config.project_path)

        # Get applicable configuration rules for changed files
        changed_file_paths = [f["path"] for f in changed_files]
        applicable_rules = get_applicable_rules_for_files(
            cursor_rules, changed_file_paths
        )

        # Format configuration content for AI consumption
        configuration_content = format_configuration_context_for_ai(
            claude_memory_files, cursor_rules
        )

        # Prepare template data with enhanced configuration support
        template_data: Dict[str, Any] = {
            "prd_summary": prd_summary,
            "total_phases": task_data["total_phases"],
            "current_phase_number": task_data["current_phase_number"],
            "previous_phase_completed": task_data["previous_phase_completed"],
            "next_phase": task_data["next_phase"],
            "current_phase_description": task_data["current_phase_description"],
            "subtasks_completed": task_data["subtasks_completed"],
            "project_path": config.project_path,
            "file_tree": file_tree,
            "changed_files": changed_files,
            "scope": config.scope,
            "phase_number": (
                config.phase_number if config.scope == "specific_phase" else None
            ),
            "task_number": (
                config.task_number if config.scope == "specific_task" else None
            ),
            "branch_comparison_data": pr_data,
            "review_mode": current_mode,
            # Enhanced configuration data
            "configuration_content": configuration_content,
            "claude_memory_files": configurations["claude_memory_files"],
            "cursor_rules": configurations["cursor_rules"],
            "applicable_rules": applicable_rules,
            "configuration_errors": configurations["discovery_errors"],
            "raw_context_only": config.raw_context_only,
            "auto_prompt_content": config.auto_prompt_content,
        }

        # Format template
        review_context = format_review_template(template_data)

        # Save output with scope-based naming
        if config.output is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

            # Generate mode and scope-specific filename
            if current_mode == "github_pr":
                mode_prefix = "github-pr"
            else:
                # Task list based mode - use scope-specific naming
                if config.scope == "recent_phase":
                    mode_prefix = "recent-phase"
                elif config.scope == "full_project":
                    mode_prefix = "full-project"
                elif config.scope == "specific_phase":
                    if config.phase_number is None:
                        raise ValueError(
                            "Phase number is required for specific_phase scope"
                        )
                    phase_safe = config.phase_number.replace(".", "-")
                    mode_prefix = f"phase-{phase_safe}"
                elif config.scope == "specific_task":
                    if config.task_number is None:
                        raise ValueError(
                            "Task number is required for specific_task scope"
                        )
                    task_safe = config.task_number.replace(".", "-")
                    mode_prefix = f"task-{task_safe}"
                else:
                    mode_prefix = "unknown"

            config.output = os.path.join(
                config.project_path, f"code-review-context-{mode_prefix}-{timestamp}.md"
            )

        with open(config.output, "w", encoding="utf-8") as f:
            f.write(review_context)

        print(f"📝 Generated review context: {os.path.basename(config.output)}")

        # Send to Gemini for comprehensive review if enabled
        gemini_output = None
        if config.enable_gemini_review:
            print("🔄 Sending to Gemini for AI code review...")
            gemini_output = send_to_gemini_for_review(
                review_context, config.project_path, config.temperature
            )
            if gemini_output:
                print(f"✅ AI code review completed: {os.path.basename(gemini_output)}")
            else:
                print(
                    "⚠️  AI code review failed or was skipped (check API key and model availability)"
                )

        return config.output, gemini_output

    except Exception as e:
        logger.error(f"Error generating review context: {e}")
        raise


def create_argument_parser():
    """Create and configure the argument parser for CLI."""
    parser = argparse.ArgumentParser(
        description="Generate code review context with enhanced scope options",
        epilog="""
🚀 QUICK START:
  # Most common usage - analyze current project
  generate-code-review .
  
  # With environment variable for API key
  export GEMINI_API_KEY=your_key && generate-code-review .

📋 SCOPE OPTIONS:
  # Auto-detect most recent incomplete phase (default)
  generate-code-review /path/to/project
  
  # Review entire completed project
  generate-code-review . --scope full_project
  
  # Review specific phase only
  generate-code-review . --scope specific_phase --phase-number 2.0
  
  # Review individual task
  generate-code-review . --scope specific_task --task-number 1.3

🤖 AUTO-PROMPT GENERATION:
  # Generate optimized prompt using Gemini analysis and use it for review
  generate-code-review . --auto-prompt
  
  # Only generate the optimized prompt (no code review)
  generate-code-review . --generate-prompt-only
  
  # Combine with other options
  generate-code-review . --auto-prompt --temperature 0.3 --scope full_project

🔀 GIT BRANCH COMPARISON:
  # Compare current branch against main/master
  generate-code-review . --compare-branch feature/auth-system
  
  # Compare specific branches
  generate-code-review . --compare-branch feature/payment --target-branch develop
  
  # Review GitHub Pull Request
  generate-code-review --github-pr-url https://github.com/owner/repo/pull/123
  
  # Combined with existing features
  generate-code-review . --compare-branch feature/new-ui --temperature 0.3

🎛️ TEMPERATURE CONTROL:
  # Focused/deterministic review (good for production code)
  generate-code-review . --temperature 0.0
  
  # Balanced review (default, recommended)
  generate-code-review . --temperature 0.5
  
  # Creative review (good for early development)
  generate-code-review . --temperature 1.0

⚙️ ENVIRONMENT SETUP:
  # Using uvx (recommended for latest version)
  GEMINI_API_KEY=your_key uvx task-list-code-review-mcp generate-code-review .
  
  # With .env file (project-specific)
  echo "GEMINI_API_KEY=your_key" > .env && generate-code-review .
  
  # Global config (~/.task-list-code-review-mcp.env)
  echo "GEMINI_API_KEY=your_key" > ~/.task-list-code-review-mcp.env

🛠️ ADVANCED OPTIONS:
  # Generate context only (no AI review)
  generate-code-review . --context-only --output /custom/path/review.md
  
  # Custom model via environment variable
  GEMINI_MODEL=gemini-2.5-pro-preview generate-code-review .
  
  # Override temperature via environment
  GEMINI_TEMPERATURE=0.3 generate-code-review .

📁 PROJECT STRUCTURE OPTIONS:
  
  # With task list (recommended)
  your-project/
  ├── tasks/
  │   ├── prd-feature.md       # Optional: Product Requirements Document  
  │   └── tasks-feature.md     # Task list file (auto-selected if multiple)
  └── ... (your source code)
  
  # Without task lists (uses default prompt)
  your-project/
  └── ... (your source code)

📋 TASK LIST DISCOVERY:
  # Auto-selects most recent tasks-*.md file
  generate-code-review .
  
  # Use specific task list
  generate-code-review . --task-list tasks-auth-system.md
  
  # Multiple task lists found? Tool shows which was selected:
  # "Multiple task lists found: tasks-auth.md, tasks-payment.md"
  # "Auto-selected most recent: tasks-payment.md"

🌐 GET API KEY: https://ai.google.dev/gemini-api/docs/api-key
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project_path", nargs="?", default=None, help="Path to project root"
    )
    parser.add_argument(
        "--phase", help="Override current phase detection (legacy parameter)"
    )
    parser.add_argument("--output", help="Custom output file path")
    parser.add_argument(
        "--context-only",
        action="store_true",
        help="Generate only the review context, skip AI review generation",
    )
    # Keep --no-gemini for backward compatibility (deprecated)
    parser.add_argument(
        "--no-gemini", action="store_true", help=argparse.SUPPRESS
    )  # Hidden deprecated option

    # Auto-prompt generation flags
    parser.add_argument(
        "--auto-prompt",
        action="store_true",
        help="Generate optimized prompt using Gemini analysis and use it for AI code review",
    )
    parser.add_argument(
        "--generate-prompt-only",
        action="store_true",
        help="Only generate the optimized prompt, do not run code review",
    )

    # New scope-based parameters
    parser.add_argument(
        "--scope",
        default="recent_phase",
        choices=["recent_phase", "full_project", "specific_phase", "specific_task"],
        help="Review scope: recent_phase (default), full_project, specific_phase, specific_task",
    )
    parser.add_argument(
        "--phase-number", help="Phase number for specific_phase scope (e.g., '2.0')"
    )
    parser.add_argument(
        "--task-number", help="Task number for specific_task scope (e.g., '1.2')"
    )
    parser.add_argument(
        "--task-list",
        help="Specify which task list file to use (e.g., 'tasks-feature-x.md')",
    )
    parser.add_argument(
        "--default-prompt", help="Custom default prompt when no task list exists"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.5,
        help="Temperature for AI model (default: 0.5, range: 0.0-2.0)",
    )

    # Git branch comparison parameters
    parser.add_argument(
        "--compare-branch",
        help="Compare this branch against target branch (default: current branch)",
    )
    parser.add_argument(
        "--target-branch",
        help="Target branch for comparison (default: auto-detect main/master)",
    )
    parser.add_argument(
        "--github-pr-url",
        help="GitHub PR URL to review (e.g., 'https://github.com/owner/repo/pull/123')",
    )

    # Configuration inclusion parameters
    parser.add_argument(
        "--no-claude-memory",
        action="store_true",
        help="Disable CLAUDE.md file inclusion (enabled by default)",
    )
    parser.add_argument(
        "--include-cursor-rules",
        action="store_true",
        help="Include Cursor rules files (.cursorrules and .cursor/rules/*.mdc)",
    )

    return parser


def validate_cli_arguments(args: Any):
    """Validate CLI arguments and check for conflicts."""

    # Check for mutually exclusive auto-prompt flags
    if args.auto_prompt and args.generate_prompt_only:
        raise ValueError(
            "--auto-prompt and --generate-prompt-only are mutually exclusive. "
            "Use --auto-prompt to generate a prompt and run code review, or "
            "--generate-prompt-only to only generate the prompt."
        )

    # Check for conflicts with context-only
    if args.generate_prompt_only and args.context_only:
        raise ValueError(
            "--generate-prompt-only and --context-only are mutually exclusive. "
            "Use --generate-prompt-only to generate optimized prompts, or "
            "--context-only to generate raw context without AI review."
        )

    # Validate project path
    if args.project_path is None:
        raise ValueError(
            "project_path is required. Please specify a path to your project directory."
        )

    # Validate temperature range
    if args.temperature < 0.0 or args.temperature > 2.0:
        raise ValueError("Temperature must be between 0.0 and 2.0")

    # Validate scope-specific parameters
    if args.scope == "specific_phase" and not args.phase_number:
        raise ValueError("--phase-number is required when using --scope specific_phase")

    if args.scope == "specific_task" and not args.task_number:
        raise ValueError("--task-number is required when using --scope specific_task")


def execute_auto_prompt_workflow(
    project_path: str,
    scope: str = "recent_phase",
    temperature: float = 0.5,
    auto_prompt: bool = False,
    generate_prompt_only: bool = False,
    **kwargs: Any,
) -> str:
    """Execute auto-prompt generation workflow with optimized single-file approach."""
    try:
        # Use optimized meta prompt generation without creating intermediate files
        try:
            from .meta_prompt_analyzer import generate_optimized_meta_prompt
        except ImportError:
            from meta_prompt_analyzer import generate_optimized_meta_prompt

        # Step 1: Generate optimized prompt using project analysis (no intermediate files)
        print("🤖 Generating optimized prompt using Gemini analysis...")

        prompt_result = generate_optimized_meta_prompt(
            project_path=project_path, scope=scope
        )

        if not prompt_result.get("analysis_completed"):
            raise Exception("Auto-prompt generation failed")

        generated_prompt = prompt_result["generated_prompt"]
        # context_analyzed = prompt_result["context_analyzed"]  # Not used currently

        # Format output for prompt-only mode
        if generate_prompt_only:
            return format_auto_prompt_output(prompt_result, auto_prompt_mode=False)

        # Step 2: For auto-prompt mode, also run AI code review with custom prompt
        if auto_prompt:
            print("🔍 Running AI code review with generated prompt...")

            # First generate context (needed for AI review)
            # Filter kwargs to only include parameters that the function accepts, excluding None values
            context_kwargs: Dict[str, Any] = {
                k: v
                for k, v in kwargs.items()
                if k
                in [
                    "phase",
                    "output",
                    "phase_number",
                    "task_number",
                    "task_list",
                    "default_prompt",
                    "compare_branch",
                    "target_branch",
                    "github_pr_url",
                    "include_claude_memory",
                    "include_cursor_rules",
                    "raw_context_only",
                ]
                and v is not None
            }

            generate_code_review_context_main(
                project_path=project_path,
                scope=scope,
                enable_gemini_review=False,  # Don't run default AI review
                temperature=temperature,
                auto_prompt_content=generated_prompt,  # Pass the meta-prompt to embed in context
                **context_kwargs,
            )
            # context_file = context_result[0]  # Not used currently

            # Run AI review with custom prompt
            # Convert to absolute path if needed
            # absolute_context_file = os.path.abspath(context_file)  # Not used currently
            # Note: AI code review generation has been disabled to avoid circular imports
            # The auto-prompt workflow now only generates context + meta prompt
            # AI review should be handled separately via the MCP server tools
            print(
                "ℹ️  Auto-prompt workflow complete - use generate_ai_code_review MCP tool for AI review"
            )
            ai_review_result = None

            return format_auto_prompt_output(
                prompt_result, auto_prompt_mode=True, ai_review_file=ai_review_result
            )

        return format_auto_prompt_output(prompt_result, auto_prompt_mode=False)

    except Exception as e:
        raise Exception(f"Auto-prompt workflow failed: {str(e)}")


def format_auto_prompt_output(
    prompt_result: Dict[str, Any],
    auto_prompt_mode: bool = False,
    ai_review_file: Optional[str] = None,
) -> str:
    """Format output for auto-prompt generation results."""
    output_parts: List[str] = []

    # Header
    if auto_prompt_mode:
        output_parts.append("🤖 Auto-Prompt Code Review Complete!")
    else:
        output_parts.append("🤖 Optimized Prompt Generated!")

    # Prompt analysis info
    context_size = prompt_result.get("context_analyzed", 0)
    output_parts.append(f"📊 Context analyzed: {context_size:,} characters")

    # Generated prompt
    generated_prompt = prompt_result.get("generated_prompt", "")
    output_parts.append("\n📝 Generated Prompt:")
    output_parts.append("=" * 50)
    output_parts.append(generated_prompt)
    output_parts.append("=" * 50)

    # AI review info (if applicable)
    if auto_prompt_mode and ai_review_file:
        output_parts.append(
            f"\n✅ AI code review completed: {os.path.basename(ai_review_file)}"
        )
        output_parts.append(f"📄 Review file: {ai_review_file}")

    # Success message
    if auto_prompt_mode:
        output_parts.append("\n🎉 Auto-prompt code review workflow completed!")
    else:
        output_parts.append("\n🎉 Prompt generation completed!")
        output_parts.append(
            "💡 Use this prompt with --custom-prompt for targeted code reviews"
        )

    return "\n".join(output_parts)


def detect_execution_mode():
    """Detect if running in development or installed mode."""
    import __main__

    if hasattr(__main__, "__file__") and __main__.__file__:
        if "src/" in str(__main__.__file__) or "-m" in sys.argv[0]:
            return "development"
    return "installed"


def cli_main():
    """CLI entry point for generate-code-review command."""
    # Show execution mode for clarity in development
    mode = detect_execution_mode()
    if mode == "development":
        print("🔧 Development mode", file=sys.stderr)

    parser = create_argument_parser()
    args = parser.parse_args()

    # Validate arguments
    try:
        validate_cli_arguments(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    try:
        # Validate and improve argument handling

        # Validate project path early
        if args.project_path:
            if not os.path.exists(args.project_path):
                suggestions = suggest_path_corrections(args.project_path, "project")
                error_msg = f"""Project path does not exist: {args.project_path}

💡 PATH SUGGESTIONS:
{suggestions}

📋 WORKING EXAMPLES:
  # Use current directory (if it has tasks/ folder)
  generate-code-review .
  
  # Use absolute path
  generate-code-review /path/to/your/project
  
  # Use relative path
  generate-code-review ../my-project
  
  # Auto-detect from current location
  generate-code-review"""
                raise FileNotFoundError(error_msg)

            if not os.path.isdir(args.project_path):
                suggestions = suggest_path_corrections(args.project_path, "project")
                error_msg = f"""Project path must be a directory: {args.project_path}

💡 PATH SUGGESTIONS:
{suggestions}

📋 WORKING EXAMPLES:
  # Point to directory, not file
  generate-code-review /path/to/project/  ✓
  generate-code-review /path/to/file.md   ✗
  
  # Use parent directory if you're pointing to a file
  generate-code-review {os.path.dirname(args.project_path) if os.path.dirname(args.project_path) else '.'}"""
                raise NotADirectoryError(error_msg)

        # Validate temperature range
        if not (0.0 <= args.temperature <= 2.0):
            error_msg = f"""Temperature must be between 0.0 and 2.0, got {args.temperature}

Working examples:
  # Deterministic/focused (good for code review)
  generate-code-review . --temperature 0.0
  
  # Balanced (default)
  generate-code-review . --temperature 0.5
  
  # Creative (good for brainstorming)
  generate-code-review . --temperature 1.0
  
  # Very creative (experimental)
  generate-code-review . --temperature 1.5
  
  # Use environment variable
  GEMINI_TEMPERATURE=0.3 generate-code-review ."""
            raise ValueError(error_msg)

        # Validate output path if provided
        if args.output:
            output_dir = os.path.dirname(args.output)
            if output_dir and not os.path.exists(output_dir):
                error_msg = f"""Output directory does not exist: {output_dir}

Working examples:
  # Use existing directory
  generate-code-review . --output /tmp/review.md
  
  # Use relative path
  generate-code-review . --output ./output/review.md
  
  # Create directory first
  mkdir -p /path/to/output && generate-code-review . --output /path/to/output/review.md
  
  # Or let tool auto-generate in project
  generate-code-review .  # creates in project/tasks/"""
                raise FileNotFoundError(error_msg)

        # Handle both new and legacy flags (prioritize new flag)
        enable_gemini = not (args.context_only or args.no_gemini)

        # Handle temperature: CLI arg takes precedence, then env var, then default 0.5
        temperature = args.temperature
        if temperature == 0.5:  # Default value, check if env var should override
            try:
                temperature = float(os.getenv("GEMINI_TEMPERATURE", "0.5"))
                if not (0.0 <= temperature <= 2.0):
                    logger.warning(
                        f"Invalid GEMINI_TEMPERATURE={temperature}, using default 0.5"
                    )
                    temperature = 0.5
            except ValueError:
                logger.warning("Invalid GEMINI_TEMPERATURE format, using default 0.5")
                temperature = 0.5

        # Handle auto-prompt workflows (new functionality)
        if args.auto_prompt or args.generate_prompt_only:
            try:
                # Prepare kwargs for workflow
                workflow_kwargs = {
                    "phase": args.phase,
                    "output": args.output,
                    "phase_number": getattr(args, "phase_number"),
                    "task_number": getattr(args, "task_number"),
                    "task_list": getattr(args, "task_list"),
                    "default_prompt": getattr(args, "default_prompt"),
                    "compare_branch": getattr(args, "compare_branch"),
                    "target_branch": getattr(args, "target_branch"),
                    "github_pr_url": getattr(args, "github_pr_url"),
                    "include_claude_memory": not args.no_claude_memory,
                    "include_cursor_rules": args.include_cursor_rules,
                }

                # Execute auto-prompt workflow
                result = execute_auto_prompt_workflow(
                    project_path=args.project_path,
                    scope=args.scope,
                    temperature=temperature,
                    auto_prompt=args.auto_prompt,
                    generate_prompt_only=args.generate_prompt_only,
                    **workflow_kwargs,
                )

                # Print the formatted result
                print(result)
                return  # Exit early for auto-prompt workflows

            except Exception as e:
                print(f"Error in auto-prompt workflow: {e}", file=sys.stderr)
                sys.exit(1)

        # Standard workflow (existing functionality)
        output_path, gemini_path = generate_code_review_context_main(
            project_path=args.project_path,
            phase=args.phase,
            output=args.output,
            enable_gemini_review=enable_gemini,
            scope=args.scope,
            phase_number=getattr(args, "phase_number"),
            task_number=getattr(args, "task_number"),
            temperature=temperature,
            task_list=getattr(args, "task_list"),
            default_prompt=getattr(args, "default_prompt"),
            compare_branch=getattr(args, "compare_branch"),
            target_branch=getattr(args, "target_branch"),
            github_pr_url=getattr(args, "github_pr_url"),
            include_claude_memory=not args.no_claude_memory,
            include_cursor_rules=args.include_cursor_rules,
        )

        print("\n🎉 Code review process completed!")
        files_generated = [os.path.basename(output_path)]
        if gemini_path:
            files_generated.append(os.path.basename(gemini_path))
        print(f"📄 Files generated: {', '.join(files_generated)}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Entry point for installed package."""
    cli_main()


if __name__ == "__main__":
    cli_main()
