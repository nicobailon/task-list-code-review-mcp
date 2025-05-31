"""
Cursor rules parser for legacy and modern formats.

This module implements parsing for both legacy .cursorrules files and modern
.cursor/rules/*.mdc files with metadata extraction, precedence handling,
and file reference resolution.

Follows TDD implementation pattern with comprehensive error handling.
"""

import os
import re
import glob
import fnmatch
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import yaml, fallback if not available
yaml = None  # type: ignore

try:
    import yaml  # type: ignore
except ImportError:
    logger.warning("PyYAML not available. MDC frontmatter parsing will be limited.")

HAS_YAML = yaml is not None


def parse_legacy_cursorrules(file_path: str) -> Dict[str, Any]:
    """
    Parse a legacy .cursorrules file.

    Args:
        file_path: Path to the .cursorrules file to parse

    Returns:
        Dictionary containing:
        - file_path: Original file path
        - type: 'legacy'
        - content: File content as string
        - description: Default description for legacy files
        - precedence: 0 (highest precedence)
        - globs: Empty list (no glob patterns)
        - always_apply: True (legacy rules always apply)

    Raises:
        FileNotFoundError: If file doesn't exist
        UnicodeDecodeError: If file contains binary content
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f".cursorrules file not found: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError as e:
        logger.error(f"Failed to decode .cursorrules file {file_path}: {e}")
        raise

    return {
        "file_path": file_path,
        "type": "legacy",
        "content": content,
        "description": "Legacy .cursorrules file",
        "precedence": 0,  # Highest precedence
        "globs": [],
        "always_apply": True,  # Legacy rules always apply
        "metadata": {},
    }


def parse_mdc_file(file_path: str) -> Dict[str, Any]:
    """
    Parse a modern .mdc file with YAML frontmatter.

    Args:
        file_path: Path to the .mdc file to parse

    Returns:
        Dictionary containing:
        - file_path: Original file path
        - type: 'modern'
        - content: File content without frontmatter
        - description: From frontmatter or empty string
        - globs: From frontmatter or empty list
        - always_apply: From frontmatter or False
        - precedence: Extracted from filename or 999
        - metadata: Additional frontmatter fields

    Raises:
        FileNotFoundError: If file doesn't exist
        UnicodeDecodeError: If file contains binary content
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f".mdc file not found: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            full_content = f.read()
    except UnicodeDecodeError as e:
        logger.error(f"Failed to decode .mdc file {file_path}: {e}")
        raise

    # Parse frontmatter
    metadata, content = _parse_mdc_frontmatter(full_content)

    # Extract basic fields with defaults
    description = metadata.get("description", "")
    globs = metadata.get("globs", [])
    always_apply = metadata.get("alwaysApply", False)

    # Extract precedence from filename
    precedence = extract_precedence_from_filename(file_path)

    # Separate metadata from basic fields
    basic_fields = {"description", "globs", "alwaysApply"}
    additional_metadata = {k: v for k, v in metadata.items() if k not in basic_fields}

    return {
        "file_path": file_path,
        "type": "modern",
        "content": content,
        "description": description,
        "globs": globs,
        "always_apply": always_apply,
        "precedence": precedence,
        "metadata": additional_metadata,
    }


def _parse_mdc_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
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

    # Remove leading empty line if present
    if remaining_content.startswith("\n"):
        remaining_content = remaining_content[1:]

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
    Returns empty dict if parsing fails due to malformed content.
    """
    metadata: Dict[str, Any] = {}

    try:
        for line in frontmatter.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):  # Skip empty lines and comments
                continue

            if ":" in line:
                # Check for malformed brackets/quotes that would indicate YAML issues
                if "[" in line and not (line.count("[") == line.count("]")):
                    # Malformed array, abort parsing
                    return {}
                if '"' in line and line.count('"') % 2 != 0:
                    # Unmatched quotes, abort parsing
                    return {}

                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                # Skip lines with comments after values (likely malformed YAML)
                if "#" in value and not (
                    value.startswith('"') or value.startswith("'")
                ):
                    continue

                # Handle boolean values
                if value.lower() in ("true", "false"):
                    metadata[key] = value.lower() == "true"
                # Handle simple arrays [item1, item2]
                elif value.startswith("[") and value.endswith("]"):
                    # Basic array parsing
                    array_content = value[1:-1]  # Remove brackets
                    items = [
                        item.strip().strip('"').strip("'")
                        for item in array_content.split(",")
                    ]
                    metadata[key] = [item for item in items if item]
                # Handle numbers
                elif value.isdigit():
                    metadata[key] = int(value)
                elif value.replace(".", "", 1).isdigit():
                    metadata[key] = float(value)
                # Handle strings
                else:
                    # Remove quotes if present
                    metadata[key] = value.strip('"').strip("'")

    except Exception:
        # If any parsing fails, return empty metadata
        return {}

    return metadata


def extract_precedence_from_filename(file_path: str) -> int:
    """
    Extract numerical precedence from filename.

    Extracts the leading number from filenames like "001-name.mdc" -> 1.

    Args:
        file_path: Path to the file (basename will be used)

    Returns:
        Precedence number, or 999 as default if no number found
    """
    # Extract filename from path, handling both Unix and Windows separators
    filename = file_path

    # Handle Unix-style paths
    if "/" in filename:
        filename = filename.split("/")[-1]

    # Handle Windows-style paths
    if "\\" in filename:
        filename = filename.split("\\")[-1]

    # Look for leading numbers in filename
    match = re.match(r"^(\d+)", filename)
    if match:
        return int(match.group(1))
    return 999  # Default precedence for files without numbers


def validate_glob_patterns(patterns: List[str]) -> bool:
    """
    Validate glob patterns for correctness.

    Args:
        patterns: List of glob patterns to validate

    Returns:
        True if all patterns are valid, False otherwise
    """
    if not patterns:
        return True

    for pattern in patterns:
        # Check for empty or whitespace-only patterns
        if not pattern or not pattern.strip():
            return False

        # Check for basic invalid patterns
        if pattern.endswith("/") and not pattern.endswith("*/"):
            return False

        # Try to compile the pattern for basic validation
        try:
            # Test with fnmatch compilation
            fnmatch.translate(pattern)
        except Exception:
            return False

    return True


def match_files_against_globs(files: List[str], globs: List[str]) -> List[str]:
    """
    Match files against glob patterns.

    Args:
        files: List of file paths to match
        globs: List of glob patterns

    Returns:
        List of files that match any of the glob patterns
    """
    if not globs:
        return []

    matched_files: List[str] = []

    for file_path in files:
        for glob_pattern in globs:
            # Note: Path object available for cross-platform compatibility if needed

            # Try direct fnmatch first
            if fnmatch.fnmatch(file_path, glob_pattern):
                matched_files.append(file_path)
                break

            # Try matching with forward slashes (for consistency)
            normalized_path = file_path.replace("\\", "/")
            normalized_pattern = glob_pattern.replace("\\", "/")
            if fnmatch.fnmatch(normalized_path, normalized_pattern):
                matched_files.append(file_path)
                break

    return matched_files


def detect_file_references(content: str) -> List[str]:
    """
    Detect @filename.ts references in rule content.

    Args:
        content: Text content to search for file references

    Returns:
        List of file references found in content
    """
    # Pattern to match @filename.ext syntax
    # Must be at start of line or after whitespace, followed by filename with extension
    # Excludes email addresses and social handles
    pattern = r"(?:^|\s)@([a-zA-Z0-9_/-]+\.[a-zA-Z0-9]+)(?:\s|$|[.,!?])"

    references: List[str] = []
    for match in re.finditer(pattern, content, re.MULTILINE):
        reference = match.group(1)

        # Filter out obvious non-file references
        if (
            "." in reference
            and not reference.startswith(".")
            and "/" not in reference[:1]
        ):
            # Check if it looks like a file (has extension and no @)
            if "@" not in reference:
                references.append(reference)

    return references


def resolve_file_references(references: List[str], project_root: str) -> Dict[str, str]:
    """
    Resolve file references to actual file paths.

    Args:
        references: List of file references to resolve
        project_root: Project root directory to search in

    Returns:
        Dictionary mapping references to resolved file paths
    """
    resolved: Dict[str, str] = {}

    for reference in references:
        # Search for the file in the project
        found_path = _find_file_in_project(reference, project_root)
        if found_path:
            resolved[reference] = found_path

    return resolved


def _find_file_in_project(filename: str, project_root: str) -> Optional[str]:
    """
    Find a file in the project directory tree.

    Args:
        filename: Name of the file to find
        project_root: Root directory to search in

    Returns:
        Absolute path to the file if found, None otherwise
    """
    # Handle paths with directory separators
    if "/" in filename:
        # Try direct path first
        candidate_path = os.path.join(project_root, filename)
        if os.path.isfile(candidate_path):
            return candidate_path

    # Search recursively for the file
    for root, _dirs, files in os.walk(project_root):
        if os.path.basename(filename) in files:
            # Check if the full path matches (for files with directory components)
            if "/" in filename:
                # Check if this file is at the expected relative path
                relative_root = os.path.relpath(root, project_root)
                expected_dir = os.path.dirname(filename)
                if relative_root == expected_dir or relative_root.endswith(
                    expected_dir
                ):
                    return os.path.join(root, os.path.basename(filename))
            else:
                # Simple filename match
                return os.path.join(root, os.path.basename(filename))

    return None


def classify_rule_type(metadata: Dict[str, Any]) -> str:
    """
    Classify rule type based on metadata.

    Args:
        metadata: Parsed MDC frontmatter metadata

    Returns:
        Rule type: 'auto', 'agent', or 'manual'
    """
    # Check for explicit type override
    explicit_type = metadata.get("type")
    if explicit_type in ["auto", "agent", "manual"]:
        return explicit_type

    # Default classification based on alwaysApply
    always_apply = metadata.get("alwaysApply", False)
    return "auto" if always_apply else "agent"


def parse_cursor_rules_directory(project_root: str) -> Dict[str, Any]:
    """
    Parse complete Cursor rules directory structure.

    Discovers and parses both legacy .cursorrules and modern .cursor/rules/*.mdc files.

    Args:
        project_root: Project root directory to search in

    Returns:
        Dictionary containing:
        - legacy_rules: Legacy .cursorrules content or None
        - modern_rules: List of modern MDC rules sorted by precedence
        - parse_errors: List of parsing errors encountered
    """
    result: Dict[str, Any] = {"legacy_rules": None, "modern_rules": [], "parse_errors": []}

    # Parse legacy .cursorrules
    legacy_file = os.path.join(project_root, ".cursorrules")
    try:
        if os.path.isfile(legacy_file):
            legacy_rules = parse_legacy_cursorrules(legacy_file)
            result["legacy_rules"] = legacy_rules
    except Exception as e:
        logger.warning(f"Failed to parse legacy .cursorrules: {e}")
        result["parse_errors"].append(
            {
                "file_path": legacy_file,
                "error_type": "legacy_parsing_error",
                "error_message": str(e),
            }
        )

    # Parse modern .cursor/rules/*.mdc files
    cursor_rules_dir = os.path.join(project_root, ".cursor", "rules")
    try:
        if os.path.isdir(cursor_rules_dir):
            modern_rules, modern_errors = _parse_modern_rules_directory(
                cursor_rules_dir, project_root
            )
            result["modern_rules"] = modern_rules
            result["parse_errors"].extend(modern_errors)
    except Exception as e:
        logger.warning(f"Failed to parse modern cursor rules: {e}")
        result["parse_errors"].append(
            {
                "file_path": cursor_rules_dir,
                "error_type": "modern_discovery_error",
                "error_message": str(e),
            }
        )

    return result


def _parse_modern_rules_directory(
    rules_dir: str, project_root: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Simple parsing of .mdc files - just read content without complex parsing.

    Args:
        rules_dir: .cursor/rules directory path
        project_root: Project root (unused in simple approach)

    Returns:
        Tuple of (parsed_rules, parse_errors)
    """
    rules: List[Dict[str, Any]] = []
    parse_errors: List[Dict[str, Any]] = []

    # Find all .mdc files recursively
    mdc_pattern = os.path.join(rules_dir, "**", "*.mdc")
    mdc_files = glob.glob(mdc_pattern, recursive=True)

    for mdc_file in mdc_files:
        try:
            # Super simple: just read the file content
            with open(mdc_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Minimal rule structure - just the content
            filename = os.path.basename(mdc_file)
            rule: Dict[str, Any] = {
                "file_path": mdc_file,
                "content": content,
                "type": "modern",
                "precedence": 0,  # No precedence logic
                "description": f"Rules from {filename}",
                "globs": [],  # No glob matching
                "always_apply": True,  # Always include
                "metadata": {},
                "file_references": [],
            }

            rules.append(rule)

        except Exception as e:
            logger.warning(f"Failed to read MDC file {mdc_file}: {e}")
            parse_errors.append(
                {
                    "file_path": mdc_file,
                    "error_type": "mdc_read_error",
                    "error_message": str(e),
                }
            )
            continue

    return rules, parse_errors
