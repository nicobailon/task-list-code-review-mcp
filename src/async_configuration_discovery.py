"""
Async-optimized configuration discovery module for improved performance.

This module provides async/concurrent versions of configuration discovery functions
to address performance bottlenecks in file system traversal and markdown parsing.

Key optimizations:
- Concurrent file system operations using asyncio
- Parallel file reading with ThreadPoolExecutor
- Batched glob operations for .mdc files
- Async-safe error handling with graceful degradation
"""

import asyncio
import os
import logging
import platform
import glob
from typing import Dict, List, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Try to import yaml, fallback if not available
yaml = None  # type: ignore

try:
    import yaml  # type: ignore
except ImportError:
    logger.warning("PyYAML not available. MDC frontmatter parsing will be limited.")

HAS_YAML = yaml is not None


def _read_file_sync(file_path: str) -> Optional[Tuple[str, str]]:
    """
    Synchronous file reader for thread pool execution.

    Args:
        file_path: Path to file to read

    Returns:
        Tuple of (file_path, content) if successful, None if failed
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return (file_path, content)
    except (IOError, OSError, PermissionError, UnicodeDecodeError) as e:
        logger.warning(f"Could not read file {file_path}: {e}")
        return None


async def async_read_files(
    file_paths: List[str], max_workers: int = 10
) -> Dict[str, str]:
    """
    Asynchronously read multiple files using thread pool.

    Args:
        file_paths: List of file paths to read
        max_workers: Maximum number of concurrent file operations

    Returns:
        Dictionary mapping file paths to their content
    """
    file_contents: Dict[str, str] = {}

    # Use ThreadPoolExecutor for I/O operations
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all file read tasks
        future_to_path = {
            executor.submit(_read_file_sync, file_path): file_path
            for file_path in file_paths
        }

        # Process completed tasks as they finish
        for future in as_completed(future_to_path):
            result = future.result()
            if result:
                file_path, content = result
                file_contents[file_path] = content

    return file_contents


async def async_discover_claude_md_files(project_path: str) -> List[Dict[str, Any]]:
    """
    Async version of CLAUDE.md file discovery with concurrent file operations.

    Args:
        project_path: Starting directory path for discovery

    Returns:
        List of dictionaries containing file information
    """
    if not os.path.exists(project_path):
        raise ValueError(f"Project path does not exist: {project_path}")

    if not os.path.isdir(project_path):
        raise ValueError(f"Project path must be a directory: {project_path}")

    claude_files: List[str] = []
    visited_paths: set[str] = set()

    # Hierarchical traversal up the directory tree
    current_path = os.path.abspath(project_path)
    root_reached = False

    while not root_reached:
        visited_paths.add(current_path)

        # Check for CLAUDE.md in current directory
        claude_file = os.path.join(current_path, "CLAUDE.md")
        if os.path.isfile(claude_file):
            claude_files.append(claude_file)

        # Move up one directory
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:  # Reached filesystem root
            root_reached = True
        else:
            current_path = parent_path

    # Concurrent subdirectory traversal
    subdirectory_files = await async_discover_claude_md_in_subdirectories(
        project_path, visited_paths
    )
    claude_files.extend(subdirectory_files)

    # Read all files concurrently
    if claude_files:
        file_contents = await async_read_files(claude_files)

        # Build result list
        result: List[Dict[str, Any]] = []
        for file_path in claude_files:
            if file_path in file_contents:
                result.append(
                    {
                        "file_path": file_path,
                        "scope": "project",
                        "content": file_contents[file_path],
                    }
                )

        return result

    return []


async def async_discover_claude_md_in_subdirectories(
    project_path: str, visited_paths: set[str]
) -> List[str]:
    """
    Async discovery of CLAUDE.md files in subdirectories.

    Args:
        project_path: Root directory to search
        visited_paths: Set of already-visited paths to skip

    Returns:
        List of CLAUDE.md file paths found in subdirectories
    """
    claude_files: List[str] = []

    def _walk_directories() -> List[str]:
        """Synchronous directory walking for thread execution."""
        found_files: List[str] = []
        for root, _dirs, files in os.walk(project_path, followlinks=False):
            # Skip if already processed in hierarchical traversal
            if os.path.abspath(root) in visited_paths:
                continue

            if "CLAUDE.md" in files:
                claude_file = os.path.join(root, "CLAUDE.md")
                if os.path.isfile(claude_file):
                    found_files.append(claude_file)
        return found_files

    # Run directory walking in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=2) as executor:
        claude_files = await loop.run_in_executor(executor, _walk_directories)

    return claude_files


async def async_discover_modern_cursor_rules(project_path: str) -> List[Dict[str, Any]]:
    """
    Async discovery of modern .cursor/rules/*.mdc files with concurrent processing.

    Args:
        project_path: Project directory to search in

    Returns:
        List of dictionaries containing modern rule information
    """
    rules: List[Dict[str, Any]] = []

    def _find_mdc_files() -> List[str]:
        """Find all .mdc files using glob patterns."""
        cursor_rules_dir = os.path.join(project_path, ".cursor", "rules")

        if not os.path.isdir(cursor_rules_dir):
            return []

        # Use glob for efficient pattern matching
        mdc_pattern = os.path.join(cursor_rules_dir, "**", "*.mdc")
        return glob.glob(mdc_pattern, recursive=True)

    # Find .mdc files in thread pool
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=2) as executor:
        mdc_files = await loop.run_in_executor(executor, _find_mdc_files)

    if not mdc_files:
        return rules

    # Read all .mdc files concurrently
    file_contents = await async_read_files(mdc_files, max_workers=5)

    # Process each file
    for file_path, content in file_contents.items():
        try:
            from .cursor_rules_parser import parse_mdc_file

            rule_data = parse_mdc_file(file_path)
            if rule_data:
                rules.append(
                    {
                        "file_path": file_path,
                        "type": "modern",
                        "format": "mdc",
                        "content": content,
                        "parsed_data": rule_data,
                    }
                )
        except Exception as e:
            logger.warning(f"Could not parse MDC file {file_path}: {e}")
            continue

    return rules


async def async_discover_all_configurations(
    project_path: str,
    include_claude_memory: bool = True,
    include_cursor_rules: bool = False,
    max_workers: int = 10,
) -> Dict[str, Any]:
    """
    Async discovery of all configuration files with concurrent processing.

    Args:
        project_path: Project directory to search
        include_claude_memory: Whether to discover CLAUDE.md files
        include_cursor_rules: Whether to discover Cursor rules
        max_workers: Maximum concurrent workers for file operations

    Returns:
        Dictionary containing all discovered configurations
    """
    result: Dict[str, Any] = {
        "claude_memory_files": [],
        "cursor_rules": [],
        "performance_stats": {"total_files_read": 0, "discovery_time_ms": 0},
    }

    import time

    start_time = time.time()

    # Create concurrent tasks
    tasks: List[Any] = []

    if include_claude_memory:
        # Claude memory discovery tasks
        claude_task = async_discover_claude_md_files(project_path)
        tasks.append(("claude_memory", claude_task))

        # User-level CLAUDE.md (async)
        user_task = async_discover_user_claude_md()
        tasks.append(("user_claude", user_task))

        # Enterprise-level CLAUDE.md (async)
        enterprise_task = async_discover_enterprise_claude_md()
        tasks.append(("enterprise_claude", enterprise_task))

    if include_cursor_rules:
        # Cursor rules discovery
        cursor_task = async_discover_modern_cursor_rules(project_path)
        tasks.append(("cursor_rules", cursor_task))

        # Legacy cursorrules
        legacy_task = async_discover_legacy_cursorrules(project_path)
        tasks.append(("legacy_cursor", legacy_task))

    # Execute all tasks concurrently
    if tasks:
        task_names, task_coroutines = zip(*tasks)
        results = await asyncio.gather(*task_coroutines, return_exceptions=True)

        # Process results
        for task_name, task_result in zip(task_names, results):
            if isinstance(task_result, Exception):
                logger.warning(f"Task {task_name} failed: {task_result}")
                continue

            if task_name in ["claude_memory", "user_claude", "enterprise_claude"]:
                if task_result:
                    if isinstance(task_result, list):
                        result["claude_memory_files"].extend(task_result)
                    elif task_result is not None:
                        result["claude_memory_files"].append(task_result)
            elif task_name in ["cursor_rules", "legacy_cursor"]:
                if task_result:
                    if isinstance(task_result, list):
                        result["cursor_rules"].extend(task_result)
                    elif task_result is not None:
                        result["cursor_rules"].append(task_result)

    # Calculate performance stats
    end_time = time.time()
    result["performance_stats"]["discovery_time_ms"] = int(
        (end_time - start_time) * 1000
    )
    result["performance_stats"]["total_files_read"] = len(
        result["claude_memory_files"]
    ) + len(result["cursor_rules"])

    return result


async def async_discover_user_claude_md() -> Optional[Dict[str, Any]]:
    """Async discovery of user-level CLAUDE.md file."""
    try:
        user_home = os.path.expanduser("~")
        user_claude_file = os.path.join(user_home, ".claude", "CLAUDE.md")

        if os.path.isfile(user_claude_file):
            file_contents = await async_read_files([user_claude_file])
            if user_claude_file in file_contents:
                return {
                    "file_path": user_claude_file,
                    "scope": "user",
                    "content": file_contents[user_claude_file],
                }
    except Exception as e:
        logger.warning(f"Error discovering user-level CLAUDE.md: {e}")

    return None


async def async_discover_enterprise_claude_md() -> Optional[Dict[str, Any]]:
    """Async discovery of enterprise-level CLAUDE.md file."""
    try:
        # Get enterprise directories (platform-specific)
        enterprise_dirs = _get_enterprise_directories()

        # Check each directory for CLAUDE.md
        candidate_files: List[str] = []
        for directory in enterprise_dirs:
            enterprise_claude_file = os.path.join(directory, "CLAUDE.md")
            if os.path.isfile(enterprise_claude_file):
                candidate_files.append(enterprise_claude_file)

        if candidate_files:
            # Read the first found file
            file_contents = await async_read_files([candidate_files[0]])
            if candidate_files[0] in file_contents:
                return {
                    "file_path": candidate_files[0],
                    "scope": "enterprise",
                    "content": file_contents[candidate_files[0]],
                }
    except Exception as e:
        logger.warning(f"Error discovering enterprise-level CLAUDE.md: {e}")

    return None


async def async_discover_legacy_cursorrules(
    project_path: str,
) -> Optional[Dict[str, Any]]:
    """Async discovery of legacy .cursorrules file."""
    try:
        cursorrules_file = os.path.join(project_path, ".cursorrules")

        if os.path.isfile(cursorrules_file):
            file_contents = await async_read_files([cursorrules_file])
            if cursorrules_file in file_contents:
                return {
                    "file_path": cursorrules_file,
                    "type": "legacy",
                    "format": "cursorrules",
                    "content": file_contents[cursorrules_file],
                }
    except Exception as e:
        logger.warning(f"Error discovering legacy .cursorrules: {e}")

    return None


def _get_enterprise_directories() -> List[str]:
    """Get platform-specific enterprise directories."""
    directories: List[str] = []
    system_name = platform.system().lower()

    if system_name == "windows":
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
        directories.extend(
            [
                "/Library/Application Support/Claude",
                "/Library/Application Support/Anthropic/Claude",
                "/usr/local/etc/claude",
                "/opt/claude",
            ]
        )
    else:  # Linux and other Unix-like systems
        directories.extend(
            [
                "/etc/claude",
                "/etc/anthropic/claude",
                "/usr/local/etc/claude",
                "/opt/claude",
            ]
        )

    return directories


# Default high-performance discovery function
def discover_all_configurations(
    project_path: str,
    include_claude_memory: bool = True,
    include_cursor_rules: bool = False,
) -> Dict[str, Any]:
    """
    High-performance configuration discovery with bulletproof fallbacks.

    This is the main entry point for configuration discovery, using async
    operations by default with multiple fallback layers for maximum reliability.

    Args:
        project_path: Project directory to search
        include_claude_memory: Whether to discover CLAUDE.md files
        include_cursor_rules: Whether to discover Cursor rules

    Returns:
        Dictionary containing all discovered configurations with performance stats
    """
    import time

    start_time = time.time()

    # Strategy 1: Try async discovery (fastest)
    try:
        # Handle existing event loop scenarios
        try:
            loop = asyncio.get_running_loop()
            # We're in an existing event loop - create a new thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    _run_async_discovery_in_new_loop,
                    project_path,
                    include_claude_memory,
                    include_cursor_rules,
                )
                result = future.result(timeout=30)  # 30 second timeout
                logger.info(
                    f"Async configuration discovery completed in "
                    f"{result['performance_stats']['discovery_time_ms']}ms"
                )
                return result
        except RuntimeError:
            # No event loop running - create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    async_discover_all_configurations(
                        project_path, include_claude_memory, include_cursor_rules
                    )
                )
                logger.info(
                    f"Async configuration discovery completed in "
                    f"{result['performance_stats']['discovery_time_ms']}ms"
                )
                return result
            finally:
                loop.close()

    except Exception as async_error:
        logger.warning(
            f"Async discovery failed ({type(async_error).__name__}: {async_error}), "
            f"trying threaded approach"
        )

        # Strategy 2: Try threaded synchronous discovery (medium speed)
        try:
            result = _threaded_sync_discovery(
                project_path, include_claude_memory, include_cursor_rules
            )
            end_time = time.time()
            result["performance_stats"]["discovery_time_ms"] = int(
                (end_time - start_time) * 1000
            )
            result["performance_stats"]["fallback_method"] = "threaded_sync"
            logger.info(
                f"Threaded configuration discovery completed in "
                f"{result['performance_stats']['discovery_time_ms']}ms"
            )
            return result

        except Exception as threaded_error:
            logger.warning(
                f"Threaded discovery failed ({type(threaded_error).__name__}: "
                f"{threaded_error}), using basic fallback"
            )

            # Strategy 3: Basic synchronous fallback (slowest but bulletproof)
            try:
                result = _basic_sync_discovery(
                    project_path, include_claude_memory, include_cursor_rules
                )
                end_time = time.time()
                result["performance_stats"]["discovery_time_ms"] = int(
                    (end_time - start_time) * 1000
                )
                result["performance_stats"]["fallback_method"] = "basic_sync"
                logger.info(
                    f"Basic configuration discovery completed in "
                    f"{result['performance_stats']['discovery_time_ms']}ms"
                )
                return result

            except Exception as basic_error:
                logger.error(f"All discovery methods failed. Last error: {basic_error}")

                # Strategy 4: Emergency minimal result (always works)
                end_time = time.time()
                return {
                    "claude_memory_files": [],
                    "cursor_rules": [],
                    "performance_stats": {
                        "total_files_read": 0,
                        "discovery_time_ms": int((end_time - start_time) * 1000),
                        "fallback_method": "emergency",
                        "error": str(basic_error),
                    },
                }


def _run_async_discovery_in_new_loop(
    project_path: str, include_claude_memory: bool, include_cursor_rules: bool
) -> Dict[str, Any]:
    """Run async discovery in a new event loop (for thread execution)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            async_discover_all_configurations(
                project_path, include_claude_memory, include_cursor_rules
            )
        )
    finally:
        loop.close()


def _threaded_sync_discovery(
    project_path: str, include_claude_memory: bool, include_cursor_rules: bool
) -> Dict[str, Any]:
    """Threaded synchronous discovery for medium performance."""
    import concurrent.futures

    result: Dict[str, Any] = {
        "claude_memory_files": [],
        "cursor_rules": [],
        "performance_stats": {"total_files_read": 0, "discovery_time_ms": 0},
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures: List[Any] = []

        if include_claude_memory:
            # Submit Claude memory discovery tasks
            futures.append(executor.submit(_discover_claude_files_sync, project_path))
            futures.append(executor.submit(_discover_user_claude_sync))
            futures.append(executor.submit(_discover_enterprise_claude_sync))

        if include_cursor_rules:
            # Submit Cursor rules discovery tasks
            futures.append(executor.submit(_discover_cursor_rules_sync, project_path))

        # Collect results
        for future in concurrent.futures.as_completed(futures, timeout=20):
            try:
                task_result = future.result()
                if task_result:
                    if "claude_memory" in str(task_result):
                        result["claude_memory_files"].extend(
                            task_result.get("files", [])
                        )
                    elif "cursor" in str(task_result):
                        result["cursor_rules"].extend(task_result.get("files", []))
            except Exception as e:
                logger.warning(f"Threaded task failed: {e}")

    result["performance_stats"]["total_files_read"] = len(
        result["claude_memory_files"]
    ) + len(result["cursor_rules"])
    return result


def _basic_sync_discovery(
    project_path: str, include_claude_memory: bool, include_cursor_rules: bool
) -> Dict[str, Any]:
    """Basic synchronous discovery using original functions."""
    from .configuration_discovery import (
        discover_all_claude_md_files,
        discover_all_cursor_rules,
    )

    result: Dict[str, Any] = {
        "claude_memory_files": [],
        "cursor_rules": [],
        "performance_stats": {"total_files_read": 0, "discovery_time_ms": 0},
    }

    try:
        if include_claude_memory:
            result["claude_memory_files"] = discover_all_claude_md_files(project_path)
    except Exception as e:
        logger.warning(f"Claude memory discovery failed: {e}")

    try:
        if include_cursor_rules:
            result["cursor_rules"] = discover_all_cursor_rules(project_path)
    except Exception as e:
        logger.warning(f"Cursor rules discovery failed: {e}")

    result["performance_stats"]["total_files_read"] = len(
        result["claude_memory_files"]
    ) + len(result["cursor_rules"])
    return result


def _discover_claude_files_sync(project_path: str) -> Dict[str, Any]:
    """Sync Claude files discovery for thread execution."""
    try:
        from .configuration_discovery import discover_claude_md_files

        files = discover_claude_md_files(project_path)
        return {"claude_memory": True, "files": files}
    except Exception:
        return {"claude_memory": True, "files": []}


def _discover_user_claude_sync() -> Dict[str, Any]:
    """Sync user Claude discovery for thread execution."""
    try:
        from .configuration_discovery import discover_user_level_claude_md

        file_info = discover_user_level_claude_md()
        return {"claude_memory": True, "files": [file_info] if file_info else []}
    except Exception:
        return {"claude_memory": True, "files": []}


def _discover_enterprise_claude_sync() -> Dict[str, Any]:
    """Sync enterprise Claude discovery for thread execution."""
    try:
        from .configuration_discovery import discover_enterprise_level_claude_md

        file_info = discover_enterprise_level_claude_md()
        return {"claude_memory": True, "files": [file_info] if file_info else []}
    except Exception:
        return {"claude_memory": True, "files": []}


def _discover_cursor_rules_sync(project_path: str) -> Dict[str, Any]:
    """Sync Cursor rules discovery for thread execution."""
    try:
        from .configuration_discovery import discover_all_cursor_rules

        files = discover_all_cursor_rules(project_path)
        return {"cursor": True, "files": files}
    except Exception:
        return {"cursor": True, "files": []}


# Make this the default import
__all__ = ["discover_all_configurations", "async_discover_all_configurations"]
