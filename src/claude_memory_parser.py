"""
Claude memory file parser with import resolution.

This module implements parsing of CLAUDE.md files with support for:
- @path/to/import syntax detection and parsing
- Import resolution with relative and absolute paths
- Recursion protection (max 5 hops)
- Circular reference detection and prevention
- Home directory import support (~/.claude/ references)
- Error handling for missing files and malformed content

Follows TDD implementation pattern with comprehensive error handling.
"""

import os
import logging
from typing import Dict, List, Any, Optional, Set

logger = logging.getLogger(__name__)


def parse_claude_md_file(file_path: str) -> Dict[str, Any]:
    """
    Parse a CLAUDE.md file and extract content and imports.

    Args:
        file_path: Path to the CLAUDE.md file to parse

    Returns:
        Dictionary containing:
        - file_path: Original file path
        - content: Raw file content
        - imports: List of detected import paths
        - resolved_content: Content with imports resolved (initially same as content)

    Raises:
        FileNotFoundError: If file doesn't exist
        UnicodeDecodeError: If file contains binary content
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"CLAUDE.md file not found: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError as e:
        logger.error(f"Failed to decode file {file_path}: {e}")
        raise

    # Detect imports in content
    imports = detect_imports(content)

    return {
        "file_path": file_path,
        "content": content,
        "imports": imports,
        "resolved_content": content,  # Will be updated during import resolution
    }


def detect_imports(content: str) -> List[str]:
    """
    Detect @path/to/import syntax in content.

    Args:
        content: Text content to search for imports

    Returns:
        List of import paths found in content
    """
    # Pattern to match @path/to/file.md syntax
    # Must be at start of line or after whitespace, followed by path ending in .md
    # Excludes email addresses and social handles

    imports: List[str] = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("@") and line.endswith(".md"):
            # Extract path after @
            import_path = line[1:].strip()
            # Validate it's a file path, not email or social handle
            if (
                "/" in import_path
                or import_path.startswith("~")
                or import_path.startswith(".")
            ):
                imports.append(import_path)
            elif "@" not in import_path:  # Simple filename without @ symbols
                imports.append(import_path)

    return imports


def resolve_import_path(
    import_path: str,
    base_file: str,
    project_root: Optional[str] = None,
    user_home_override: Optional[str] = None,
) -> str:
    """
    Resolve import path to absolute file path.

    Args:
        import_path: Import path from @path/to/file syntax
        base_file: File containing the import (for relative resolution)
        project_root: Project root directory (for absolute imports)
        user_home_override: Override for user home directory (for testing)

    Returns:
        Absolute path to the imported file
    """
    # Handle home directory imports
    if import_path.startswith("~/"):
        if user_home_override:
            home_dir = user_home_override
        else:
            home_dir = os.path.expanduser("~")
        return os.path.join(home_dir, import_path[2:])

    # Handle relative imports
    if import_path.startswith("./") or import_path.startswith("../"):
        base_dir = os.path.dirname(base_file)
        return os.path.abspath(os.path.join(base_dir, import_path))

    # Handle absolute imports (relative to project root)
    if project_root and not os.path.isabs(import_path):
        return os.path.join(project_root, import_path)

    # Handle already absolute paths
    if os.path.isabs(import_path):
        return import_path

    # Default: treat as relative to base file directory
    base_dir = os.path.dirname(base_file)
    return os.path.abspath(os.path.join(base_dir, import_path))


def resolve_imports(
    file_path: str,
    project_root: Optional[str] = None,
    user_home_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve imports for a single CLAUDE.md file.

    Args:
        file_path: Path to the CLAUDE.md file
        project_root: Project root directory
        user_home_override: Override for user home directory

    Returns:
        Dictionary containing file info and resolved imports
    """
    parsed_file = parse_claude_md_file(file_path)

    resolved_imports: List[Dict[str, str]] = []

    for import_path in parsed_file["imports"]:
        try:
            resolved_path = resolve_import_path(
                import_path, file_path, project_root, user_home_override
            )

            # Read imported file content
            if os.path.isfile(resolved_path):
                with open(resolved_path, "r", encoding="utf-8") as f:
                    import_content = f.read()

                resolved_imports.append(
                    {
                        "import_path": import_path,
                        "resolved_path": resolved_path,
                        "content": import_content,
                    }
                )
            else:
                logger.warning(f"Imported file not found: {resolved_path}")

        except Exception as e:
            logger.warning(f"Failed to resolve import {import_path}: {e}")
            continue

    parsed_file["imports"] = resolved_imports
    return parsed_file


def resolve_imports_with_recursion_protection(
    file_path: str,
    project_root: Optional[str] = None,
    user_home_override: Optional[str] = None,
    max_depth: int = 5,
    visited_files: Optional[Set[str]] = None,
    current_depth: int = 0,
    call_stack: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Resolve imports with recursion protection and circular reference detection.

    Args:
        file_path: Path to the CLAUDE.md file
        project_root: Project root directory
        user_home_override: Override for user home directory
        max_depth: Maximum recursion depth (default 5)
        visited_files: Set of already visited files (for circular detection)
        current_depth: Current recursion depth
        call_stack: List to track call stack for circular detection

    Returns:
        Dictionary containing file info, imports, and protection metadata
    """
    if visited_files is None:
        visited_files = set()
    if call_stack is None:
        call_stack = []

    # Normalize file path for comparison
    normalized_path = os.path.abspath(file_path)

    # Check for circular reference (file already in call stack)
    if normalized_path in call_stack:
        return {
            "file_path": file_path,
            "circular_reference_detected": True,
            "circular_references": call_stack + [normalized_path],
            "max_depth_reached": current_depth,
            "recursion_limit_hit": False,
            "all_imports": [],
        }

    # Check recursion limit
    if current_depth >= max_depth:
        return {
            "file_path": file_path,
            "circular_reference_detected": False,
            "circular_references": [],
            "max_depth_reached": max_depth,
            "recursion_limit_hit": True,
            "all_imports": [],
        }

    # Add current file to call stack
    call_stack.append(normalized_path)

    try:
        # Parse current file
        parsed_file = parse_claude_md_file(file_path)

        all_imports: List[Dict[str, Any]] = []
        circular_detected: bool = False
        recursion_hit: bool = False
        max_depth_reached: int = current_depth
        circular_refs: List[str] = []

        # Resolve each import recursively
        for import_path in parsed_file["imports"]:
            try:
                resolved_path = resolve_import_path(
                    import_path, file_path, project_root, user_home_override
                )

                if os.path.isfile(resolved_path):
                    # Check if we can include this import (depth constraint)
                    if current_depth + 1 < max_depth:
                        # Normalize resolved path for comparison
                        # _normalized_resolved = os.path.abspath(resolved_path)  # Not used currently

                        # Read import content
                        with open(resolved_path, "r", encoding="utf-8") as f:
                            import_content = f.read()

                        import_info = {
                            "import_path": import_path,
                            "resolved_path": resolved_path,
                            "content": import_content,
                            "depth": current_depth + 1,
                        }

                        # Add import info for current level
                        all_imports.append(import_info)

                        # Update max depth reached
                        max_depth_reached = max(max_depth_reached, current_depth + 1)

                        # Recursively resolve imports from this file
                        nested_result = resolve_imports_with_recursion_protection(
                            resolved_path,
                            project_root,
                            user_home_override,
                            max_depth,
                            visited_files,  # Share visited files set
                            current_depth + 1,
                            call_stack.copy(),  # Copy call stack for each branch
                        )

                        # Merge results
                        if nested_result["circular_reference_detected"]:
                            circular_detected = True
                            circular_refs.extend(nested_result["circular_references"])
                        if nested_result["recursion_limit_hit"]:
                            recursion_hit = True
                        max_depth_reached = max(
                            max_depth_reached, nested_result["max_depth_reached"]
                        )

                        # Add nested imports (avoid duplicates based on resolved path)
                        for nested_import in nested_result["all_imports"]:
                            if not any(
                                imp["resolved_path"] == nested_import["resolved_path"]
                                for imp in all_imports
                            ):
                                all_imports.append(nested_import)
                    else:
                        # Hit recursion limit - cannot process this import
                        recursion_hit = True
                        max_depth_reached = max_depth

            except Exception as e:
                logger.warning(f"Failed to resolve import {import_path}: {e}")
                continue

        return {
            "file_path": file_path,
            "content": parsed_file["content"],
            "circular_reference_detected": circular_detected,
            "circular_references": circular_refs,
            "max_depth_reached": max_depth_reached,
            "recursion_limit_hit": recursion_hit,
            "all_imports": all_imports,
        }

    finally:
        # Remove current file from call stack
        call_stack.pop()


def resolve_imports_with_error_handling(
    file_path: str,
    project_root: Optional[str] = None,
    user_home_override: Optional[str] = None,
    visited_files: Optional[Set[str]] = None,
    max_depth: int = 5,
    current_depth: int = 0,
) -> Dict[str, Any]:
    """
    Resolve imports with comprehensive error handling and recursion.

    Args:
        file_path: Path to the CLAUDE.md file
        project_root: Project root directory
        user_home_override: Override for user home directory
        visited_files: Set of already visited files (for circular detection)
        max_depth: Maximum recursion depth
        current_depth: Current recursion depth

    Returns:
        Dictionary containing successful imports and error details
    """
    if visited_files is None:
        visited_files = set()

    # Normalize file path for comparison
    normalized_path = os.path.abspath(file_path)

    # Check for circular reference or recursion limit
    if normalized_path in visited_files or current_depth >= max_depth:
        return {
            "file_path": file_path,
            "content": "",
            "successful_imports": [],
            "import_errors": [],
        }

    visited_files.add(normalized_path)

    try:
        parsed_file = parse_claude_md_file(file_path)
    except Exception as e:
        return {
            "file_path": file_path,
            "successful_imports": [],
            "import_errors": [
                {
                    "import_path": file_path,
                    "error_type": "parse_error",
                    "error_message": str(e),
                }
            ],
        }

    successful_imports: List[Dict[str, str]] = []
    import_errors: List[Dict[str, str]] = []

    for import_path in parsed_file["imports"]:
        try:
            resolved_path = resolve_import_path(
                import_path, file_path, project_root, user_home_override
            )

            if not os.path.isfile(resolved_path):
                import_errors.append(
                    {
                        "import_path": import_path,
                        "resolved_path": resolved_path,
                        "error_type": "file_not_found",
                        "error_message": f"File not found: {resolved_path}",
                    }
                )
                continue

            try:
                with open(resolved_path, "r", encoding="utf-8") as f:
                    import_content = f.read()

                successful_imports.append(
                    {
                        "import_path": import_path,
                        "resolved_path": resolved_path,
                        "content": import_content,
                    }
                )

                # Recursively resolve nested imports
                if (
                    current_depth + 1 < max_depth
                    and os.path.abspath(resolved_path) not in visited_files
                ):
                    nested_result = resolve_imports_with_error_handling(
                        resolved_path,
                        project_root,
                        user_home_override,
                        visited_files.copy(),
                        max_depth,
                        current_depth + 1,
                    )

                    # Add nested successful imports
                    successful_imports.extend(nested_result["successful_imports"])
                    import_errors.extend(nested_result["import_errors"])

            except PermissionError as e:
                import_errors.append(
                    {
                        "import_path": import_path,
                        "resolved_path": resolved_path,
                        "error_type": "permission_denied",
                        "error_message": str(e),
                    }
                )
            except UnicodeDecodeError as e:
                import_errors.append(
                    {
                        "import_path": import_path,
                        "resolved_path": resolved_path,
                        "error_type": "encoding_error",
                        "error_message": str(e),
                    }
                )

        except Exception as e:
            import_errors.append(
                {
                    "import_path": import_path,
                    "error_type": "resolution_error",
                    "error_message": str(e),
                }
            )

    return {
        "file_path": file_path,
        "content": parsed_file["content"],
        "successful_imports": successful_imports,
        "import_errors": import_errors,
    }


def parse_claude_memory_with_imports(
    file_path: str,
    project_root: Optional[str] = None,
    user_home_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Complete Claude memory parsing with all features enabled.

    Combines recursion protection, error handling, and import resolution
    into a single comprehensive function.

    Args:
        file_path: Path to the CLAUDE.md file
        project_root: Project root directory
        user_home_override: Override for user home directory

    Returns:
        Dictionary containing complete parsing results with resolved content
    """
    # First, get recursion-protected results
    recursion_result = resolve_imports_with_recursion_protection(
        file_path, project_root, user_home_override
    )

    # Then, get error handling results
    error_result = resolve_imports_with_error_handling(
        file_path, project_root, user_home_override
    )

    # Build resolved content by combining original content with successful imports
    resolved_content = recursion_result.get("content", "")
    import_graph: Dict[str, List[str]] = {file_path: []}

    # Add import content to resolved content
    for import_info in recursion_result["all_imports"]:
        resolved_content += (
            f"\n\n<!-- IMPORTED FROM: {import_info['import_path']} -->\n"
        )
        resolved_content += import_info["content"]
        resolved_path: str = import_info["resolved_path"]
        import_graph[file_path].append(resolved_path)

    # Combine results
    return {
        "file_path": file_path,
        "content": recursion_result.get("content", ""),
        "resolved_content": resolved_content,
        "successful_imports": recursion_result["all_imports"],
        "import_errors": error_result["import_errors"],
        "circular_reference_detected": recursion_result["circular_reference_detected"],
        "circular_references": recursion_result["circular_references"],
        "recursion_limit_hit": recursion_result["recursion_limit_hit"],
        "max_depth_reached": recursion_result["max_depth_reached"],
        "import_graph": import_graph,
    }
