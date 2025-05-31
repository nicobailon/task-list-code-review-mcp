"""
Configuration discovery module for Claude memory and Cursor rules files.

This module implements file system traversal and discovery functionality for:
- CLAUDE.md files across project hierarchy
- User-level and enterprise-level configurations
- Cursor rules files (legacy and modern formats)

Follows TDD implementation pattern with comprehensive error handling.
"""

import os
import logging
import platform
import re
import glob
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import yaml, fallback if not available
yaml = None  # type: ignore

try:
    import yaml  # type: ignore
except ImportError:
    logger.warning("PyYAML not available. MDC frontmatter parsing will be limited.")

HAS_YAML = yaml is not None


def discover_claude_md_files(project_path: str) -> List[Dict[str, Any]]:
    """
    Discover CLAUDE.md files in project hierarchy.

    Searches for CLAUDE.md files starting from the given directory and traversing
    up the directory tree. Returns file information with content and metadata.

    Args:
        project_path: Starting directory path for discovery

    Returns:
        List of dictionaries containing file information:
        - file_path: Absolute path to the CLAUDE.md file
        - scope: 'project' for project-level files
        - content: File content as string

    Raises:
        ValueError: If project_path doesn't exist or is invalid
    """
    if not os.path.exists(project_path):
        raise ValueError(f"Directory does not exist: {project_path}")

    if not os.path.isdir(project_path):
        raise ValueError(f"Path is not a directory: {project_path}")

    discovered_files: List[Dict[str, Any]] = []

    # Start from project_path and traverse up to find CLAUDE.md files
    current_path = os.path.abspath(project_path)
    visited_paths: set[str] = set()

    while current_path not in visited_paths:
        visited_paths.add(current_path)

        # Check for CLAUDE.md in current directory
        claude_file = os.path.join(current_path, "CLAUDE.md")
        if os.path.isfile(claude_file):
            try:
                # Read file content safely
                with open(claude_file, "r", encoding="utf-8") as f:
                    content = f.read()

                file_info = {
                    "file_path": claude_file,
                    "scope": "project",
                    "content": content,
                }
                discovered_files.append(file_info)

            except (IOError, OSError, PermissionError, UnicodeDecodeError) as e:
                # Log error but don't crash - skip malformed/unreadable files
                logger.warning(f"Could not read CLAUDE.md file {claude_file}: {e}")
                continue

        # Move up one directory
        parent_path = os.path.dirname(current_path)

        # Stop if we've reached the filesystem root
        if parent_path == current_path:
            break

        current_path = parent_path

    # Also discover CLAUDE.md files in nested directories within project
    if os.path.exists(project_path) and os.path.isdir(project_path):
        _discover_nested_claude_files(project_path, discovered_files, visited_paths)

    return discovered_files


def _discover_nested_claude_files(
    project_path: str, discovered_files: List[Dict[str, Any]], visited_paths: set[str]
) -> None:
    """
    Discover CLAUDE.md files in nested directories within the project.

    Args:
        project_path: Project root directory to search within
        discovered_files: List to append discovered files to
        visited_paths: Set of already visited paths to avoid duplicates
    """
    try:
        for root, _dirs, files in os.walk(project_path, followlinks=False):
            # Skip if we already processed this directory in hierarchical traversal
            if os.path.abspath(root) in visited_paths:
                continue

            if "CLAUDE.md" in files:
                claude_file = os.path.join(root, "CLAUDE.md")

                # Skip if already found in hierarchical traversal
                if any(item["file_path"] == claude_file for item in discovered_files):
                    continue

                try:
                    with open(claude_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    file_info = {
                        "file_path": claude_file,
                        "scope": "project",
                        "content": content,
                    }
                    discovered_files.append(file_info)

                except (IOError, OSError, PermissionError, UnicodeDecodeError) as e:
                    # Log error but continue - skip malformed/unreadable files
                    logger.warning(f"Could not read CLAUDE.md file {claude_file}: {e}")
                    continue

    except (OSError, PermissionError) as e:
        # Log error but don't crash if directory traversal fails
        logger.warning(f"Could not traverse directory {project_path}: {e}")


def discover_user_level_claude_md(
    user_home_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Discover user-level CLAUDE.md configuration file.

    Searches for ~/.claude/CLAUDE.md in the user's home directory.

    Args:
        user_home_override: Optional override for user home directory (for testing)

    Returns:
        Dictionary with file information if found, None otherwise:
        - file_path: Absolute path to the user CLAUDE.md file
        - scope: 'user' for user-level files
        - content: File content as string

    Returns None if file doesn't exist or cannot be read.
    """
    try:
        if user_home_override:
            user_home = user_home_override
        else:
            user_home = os.path.expanduser("~")

        claude_dir = os.path.join(user_home, ".claude")
        user_claude_file = os.path.join(claude_dir, "CLAUDE.md")

        if not os.path.isfile(user_claude_file):
            return None

        try:
            with open(user_claude_file, "r", encoding="utf-8") as f:
                content = f.read()

            return {"file_path": user_claude_file, "scope": "user", "content": content}

        except (IOError, OSError, PermissionError, UnicodeDecodeError) as e:
            # Log error but don't crash - return None for unreadable files
            logger.warning(
                f"Could not read user-level CLAUDE.md file {user_claude_file}: {e}"
            )
            return None

    except Exception as e:
        # Log unexpected errors but don't crash
        logger.warning(f"Unexpected error discovering user-level CLAUDE.md: {e}")
        return None


def get_platform_specific_enterprise_directories() -> List[str]:
    """
    Get platform-specific enterprise-level configuration directories.

    Returns standard system directories where enterprise policies
    and configurations are typically stored.

    Returns:
        List of platform-appropriate directory paths for enterprise configurations.
    """
    directories: List[str] = []

    system_name = platform.system().lower()

    if system_name == "windows":
        # Windows enterprise directories
        program_data = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        directories.extend(
            [
                os.path.join(program_data, "Claude"),
                os.path.join(program_data, "Anthropic", "Claude"),
                "C:\\Program Files\\Claude",
                "C:\\Program Files\\Anthropic\\Claude",
            ]
        )
    elif system_name == "darwin":  # macOS
        # macOS enterprise directories
        directories.extend(
            [
                "/Library/Application Support/Claude",
                "/Library/Application Support/Anthropic/Claude",
                "/usr/local/etc/claude",
                "/opt/claude",
            ]
        )
    else:  # Linux and other Unix-like systems
        # Linux/Unix enterprise directories
        directories.extend(
            [
                "/etc/claude",
                "/etc/anthropic/claude",
                "/usr/local/etc/claude",
                "/opt/claude/etc",
                "/usr/share/claude",
            ]
        )

    return directories


def discover_enterprise_level_claude_md(
    enterprise_dir_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Discover enterprise-level CLAUDE.md configuration file.

    Searches for CLAUDE.md in platform-specific enterprise directories.

    Args:
        enterprise_dir_override: Optional override for enterprise directory (for testing)

    Returns:
        Dictionary with file information if found, None otherwise:
        - file_path: Absolute path to the enterprise CLAUDE.md file
        - scope: 'enterprise' for enterprise-level files
        - content: File content as string

    Returns None if file doesn't exist or cannot be read.
    """
    try:
        if enterprise_dir_override:
            # Use override directory for testing
            enterprise_directories = [enterprise_dir_override]
        else:
            # Use platform-specific directories
            enterprise_directories = get_platform_specific_enterprise_directories()

        # Check each enterprise directory for CLAUDE.md
        for enterprise_dir in enterprise_directories:
            enterprise_claude_file = os.path.join(enterprise_dir, "CLAUDE.md")

            if not os.path.isfile(enterprise_claude_file):
                continue

            try:
                with open(enterprise_claude_file, "r", encoding="utf-8") as f:
                    content = f.read()

                return {
                    "file_path": enterprise_claude_file,
                    "scope": "enterprise",
                    "content": content,
                }

            except (IOError, OSError, PermissionError, UnicodeDecodeError) as e:
                # Log error but continue searching other directories
                logger.warning(
                    f"Could not read enterprise-level CLAUDE.md file {enterprise_claude_file}: {e}"
                )
                continue

        # No enterprise file found
        return None

    except Exception as e:
        # Log unexpected errors but don't crash
        logger.warning(f"Unexpected error discovering enterprise-level CLAUDE.md: {e}")
        return None


def discover_all_claude_md_files(
    project_path: str,
    user_home_override: Optional[str] = None,
    enterprise_dir_override: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Discover all CLAUDE.md files from project, user, and enterprise-level sources.

    Combines project-level CLAUDE.md discovery with user-level and enterprise-level configurations.

    Args:
        project_path: Starting directory path for project discovery
        user_home_override: Optional override for user home directory (for testing)
        enterprise_dir_override: Optional override for enterprise directory (for testing)

    Returns:
        List of dictionaries containing all discovered CLAUDE.md files,
        combining project, user, and enterprise-level configurations.
    """
    all_files: List[Dict[str, Any]] = []

    # Discover project-level CLAUDE.md files
    try:
        project_files = discover_claude_md_files(project_path)
        all_files.extend(project_files)
    except Exception as e:
        logger.error(f"Failed to discover project-level CLAUDE.md files: {e}")
        # Continue with empty project files - graceful degradation

    # Discover user-level CLAUDE.md file
    try:
        user_file = discover_user_level_claude_md(user_home_override)
        if user_file is not None:
            all_files.append(user_file)
    except Exception as e:
        logger.error(f"Failed to discover user-level CLAUDE.md file: {e}")
        # Continue without user file - graceful degradation

    # Discover enterprise-level CLAUDE.md file
    try:
        enterprise_file = discover_enterprise_level_claude_md(enterprise_dir_override)
        if enterprise_file is not None:
            all_files.append(enterprise_file)
    except Exception as e:
        logger.error(f"Failed to discover enterprise-level CLAUDE.md file: {e}")
        # Continue without enterprise file - graceful degradation

    return all_files


def discover_configuration_files(
    project_path: str,
    user_home_override: Optional[str] = None,
    enterprise_dir_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main configuration discovery function that orchestrates all discovery types.

    Discovers and returns all configuration files including Claude memory files,
    Cursor rules, and other relevant configuration sources from project,
    user-level, and enterprise-level sources.

    Args:
        project_path: Starting directory path for discovery
        user_home_override: Optional override for user home directory (for testing)
        enterprise_dir_override: Optional override for enterprise directory (for testing)

    Returns:
        Dictionary containing discovered configurations:
        - claude_memory_files: List of discovered CLAUDE.md files (project + user + enterprise)
        - cursor_rules: List of discovered Cursor rules (placeholder for future implementation)
        - legacy_cursorrules: Legacy .cursorrules content (placeholder for future implementation)
    """
    result: Dict[str, Any] = {"claude_memory_files": [], "cursor_rules": [], "legacy_cursorrules": None}

    # Discover all Claude memory files (project + user-level + enterprise-level)
    try:
        claude_files = discover_all_claude_md_files(
            project_path, user_home_override, enterprise_dir_override
        )
        result["claude_memory_files"] = claude_files
    except Exception as e:
        logger.error(f"Failed to discover Claude memory files: {e}")
        # Continue with empty list - graceful degradation

    # TODO: Add Cursor rules discovery in future iterations
    # result['cursor_rules'] = discover_cursor_rules(project_path)
    # result['legacy_cursorrules'] = discover_legacy_cursorrules(project_path)

    return result


def parse_mdc_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    Parse MDC file frontmatter and content.

    Extracts YAML frontmatter from MDC files and separates it from the main content.

    Args:
        content: Full MDC file content including frontmatter

    Returns:
        Tuple of (metadata_dict, content_without_frontmatter)
    """
    # Check if content starts with frontmatter delimiter
    if not content.strip().startswith("---"):
        return {}, content

    # Find the end of frontmatter
    lines = content.split("\n")
    if len(lines) < 3:  # Need at least ---, content, ---
        return {}, content

    # Find closing --- delimiter
    end_index = None
    for i, line in enumerate(lines[1:], 1):  # Start from line 1 (skip opening ---)
        if line.strip() == "---":
            end_index = i
            break

    if end_index is None:
        # No closing delimiter found, treat as regular content
        return {}, content

    # Extract frontmatter and content
    frontmatter_lines = lines[1:end_index]  # Skip opening --- and closing ---
    content_lines = lines[end_index + 1 :]  # Content after closing ---

    frontmatter_yaml = "\n".join(frontmatter_lines)
    remaining_content = "\n".join(content_lines)

    # Parse YAML frontmatter
    metadata: Dict[str, Any] = {}
    if HAS_YAML and yaml is not None and frontmatter_yaml.strip():
        try:
            metadata = yaml.safe_load(frontmatter_yaml) or {}
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse MDC frontmatter: {e}")
            metadata = {}
    elif frontmatter_yaml.strip():
        # Basic fallback parsing without YAML
        logger.warning("PyYAML not available, using basic frontmatter parsing")
        metadata = _basic_frontmatter_parse(frontmatter_yaml)

    return metadata, remaining_content


def _basic_frontmatter_parse(frontmatter: str) -> Dict[str, Any]:
    """
    Basic frontmatter parsing fallback when PyYAML is not available.

    Handles simple key: value pairs and basic arrays.
    """
    metadata: Dict[str, Any] = {}

    for line in frontmatter.split("\n"):
        line = line.strip()
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Handle boolean values
            if value.lower() in ("true", "false"):
                metadata[key] = value.lower() == "true"
            # Handle simple arrays [item1, item2]
            elif value.startswith("[") and value.endswith("]"):
                # Basic array parsing
                array_content = value[1:-1]  # Remove brackets
                items = [item.strip().strip("\"'") for item in array_content.split(",")]
                metadata[key] = [item for item in items if item]
            # Handle strings
            else:
                # Remove quotes if present
                metadata[key] = value.strip("\"'")

    return metadata


def determine_rule_type_from_metadata(metadata: Dict[str, Any]) -> str:
    """
    Determine rule type from MDC metadata.

    Args:
        metadata: Parsed MDC frontmatter metadata

    Returns:
        Rule type: 'auto' for always-apply rules, 'agent' for others
    """
    always_apply = metadata.get("alwaysApply", False)
    return "auto" if always_apply else "agent"


def extract_precedence_from_filename(filename: str) -> int:
    """
    Extract numerical precedence from filename.

    Extracts the leading number from filenames like "001-name.mdc" -> 1.

    Args:
        filename: MDC filename

    Returns:
        Precedence number, or 999 as default if no number found
    """
    # Look for leading numbers in filename
    match = re.match(r"^(\d+)", os.path.basename(filename))
    if match:
        return int(match.group(1))
    return 999  # Default precedence for files without numbers


def discover_legacy_cursorrules(project_path: str) -> Optional[Dict[str, Any]]:
    """
    Discover legacy .cursorrules file in project root.

    Args:
        project_path: Project directory to search in

    Returns:
        Dictionary with rule information if found, None otherwise
    """
    try:
        cursorrules_file = os.path.join(project_path, ".cursorrules")

        if not os.path.isfile(cursorrules_file):
            return None

        try:
            with open(cursorrules_file, "r", encoding="utf-8") as f:
                content = f.read()

            return {
                "file_path": cursorrules_file,
                "type": "legacy",
                "description": "Legacy .cursorrules file",
                "content": content,
                "globs": [],  # Legacy files don't have glob patterns
                "precedence": 0,  # Legacy files have highest precedence
                "referenced_files": [],
            }

        except (IOError, OSError, PermissionError, UnicodeDecodeError) as e:
            logger.warning(
                f"Could not read legacy .cursorrules file {cursorrules_file}: {e}"
            )
            return None

    except Exception as e:
        logger.warning(f"Unexpected error discovering legacy .cursorrules: {e}")
        return None


def discover_modern_cursor_rules(project_path: str) -> List[Dict[str, Any]]:
    """
    Discover modern .cursor/rules/*.mdc files.

    Args:
        project_path: Project directory to search in

    Returns:
        List of dictionaries containing modern rule information
    """
    rules: List[Dict[str, Any]] = []

    try:
        cursor_rules_dir = os.path.join(project_path, ".cursor", "rules")

        if not os.path.isdir(cursor_rules_dir):
            return rules

        # Find all .mdc files recursively in the rules directory and subdirectories
        mdc_pattern = os.path.join(cursor_rules_dir, "**", "*.mdc")
        mdc_files = glob.glob(mdc_pattern, recursive=True)

        for mdc_file in mdc_files:
            try:
                with open(mdc_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # Parse frontmatter
                metadata, rule_content = parse_mdc_frontmatter(content)

                # Skip files without valid frontmatter or description
                if not metadata or "description" not in metadata:
                    logger.warning(
                        f"Skipping malformed MDC file {mdc_file}: no description in frontmatter"
                    )
                    continue

                # Build rule information
                rule_info: Dict[str, Any] = {
                    "file_path": mdc_file,
                    "type": determine_rule_type_from_metadata(metadata),
                    "description": metadata.get("description", ""),
                    "content": rule_content,
                    "globs": metadata.get("globs", []),
                    "precedence": extract_precedence_from_filename(mdc_file),
                    "referenced_files": [],  # TODO: Extract @filename.ts references
                }

                rules.append(rule_info)

            except (IOError, OSError, PermissionError, UnicodeDecodeError) as e:
                logger.warning(f"Could not read MDC file {mdc_file}: {e}")
                continue

        # Sort by precedence (lower numbers first)
        rules.sort(key=lambda r: r["precedence"])  # type: ignore

    except Exception as e:
        logger.warning(f"Unexpected error discovering modern cursor rules: {e}")

    return rules


def discover_cursor_rules(project_path: str) -> Dict[str, Any]:
    """
    Discover all Cursor rules (legacy and modern) in project.

    Args:
        project_path: Project directory to search in

    Returns:
        Dictionary containing both legacy and modern rules:
        - legacy_cursorrules: Legacy .cursorrules content or None
        - modern_rules: List of modern MDC rules
    """
    result: Dict[str, Any] = {"legacy_cursorrules": None, "modern_rules": []}

    # Discover legacy .cursorrules
    try:
        legacy_rule = discover_legacy_cursorrules(project_path)
        result["legacy_cursorrules"] = legacy_rule
    except Exception as e:
        logger.error(f"Failed to discover legacy .cursorrules: {e}")

    # Discover modern .cursor/rules/*.mdc files
    try:
        modern_rules = discover_modern_cursor_rules(project_path)
        result["modern_rules"] = modern_rules
    except Exception as e:
        logger.error(f"Failed to discover modern cursor rules: {e}")

    return result


def discover_all_cursor_rules(project_path: str) -> List[Dict[str, Any]]:
    """
    Discover all Cursor rules and convert to unified format.

    Args:
        project_path: Project directory to search in

    Returns:
        List of all cursor rules (legacy and modern) in unified format
    """
    all_rules: List[Dict[str, Any]] = []

    # Get cursor rules
    cursor_data = discover_cursor_rules(project_path)

    # Add legacy rule if present
    if cursor_data.get("legacy_cursorrules"):
        legacy_rule = cursor_data["legacy_cursorrules"]
        # Add hierarchy level for consistency with Claude memory files
        legacy_rule["hierarchy_level"] = "project"
        all_rules.append(legacy_rule)

    # Add modern rules
    for modern_rule in cursor_data.get("modern_rules", []):
        # Add hierarchy level for consistency
        modern_rule["hierarchy_level"] = "project"
        all_rules.append(modern_rule)

    return all_rules
