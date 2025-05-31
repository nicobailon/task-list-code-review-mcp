"""
Configuration context data models and merging logic.

This module provides data models and algorithms for merging Claude memory files
and Cursor rules with proper precedence handling, content deduplication,
and conflict resolution.

Following TDD implementation pattern with comprehensive error handling.
"""

import os
import re
import logging
from dataclasses import dataclass
from typing import Dict, List, Any, TypedDict

logger = logging.getLogger(__name__)


@dataclass
class ImportInfo:
    """Data model for import information in Claude memory files."""

    import_path: str
    resolved_path: str
    content: str
    depth: int


@dataclass
class ClaudeMemoryFile:
    """Data model for Claude memory file with resolved imports."""

    file_path: str
    content: str
    hierarchy_level: str  # "project", "user", "enterprise"
    imports: List[ImportInfo]
    resolved_content: str


@dataclass
class CursorRule:
    """Data model for Cursor rule (legacy or modern format)."""

    file_path: str
    content: str
    rule_type: str  # "legacy" or "modern"
    precedence: int
    description: str
    globs: List[str]
    always_apply: bool
    metadata: Dict[str, Any]


@dataclass
class ConfigurationContext:
    """Data model for complete configuration context."""

    claude_memory_files: List[ClaudeMemoryFile]
    cursor_rules: List[CursorRule]
    merged_content: str
    auto_apply_rules: List[CursorRule]
    error_summary: List[Dict[str, Any]]


class ConfigurationContextDict(TypedDict):
    """TypedDict for configuration context dictionary representation."""
    
    claude_memory_files: List[ClaudeMemoryFile]
    cursor_rules: List[CursorRule]
    merged_content: str
    auto_apply_rules: List[CursorRule]
    error_summary: List[Dict[str, Any]]


def sort_claude_memory_by_precedence(
    memory_files: List[ClaudeMemoryFile],
) -> List[ClaudeMemoryFile]:
    """
    Sort Claude memory files by hierarchy precedence.

    Precedence order: project > user > enterprise

    Args:
        memory_files: List of ClaudeMemoryFile objects to sort

    Returns:
        List of ClaudeMemoryFile objects sorted by precedence
    """
    precedence_order = {"project": 1, "user": 2, "enterprise": 3}

    def get_precedence(memory_file: ClaudeMemoryFile) -> int:
        return precedence_order.get(memory_file.hierarchy_level, 999)

    return sorted(memory_files, key=get_precedence)


def sort_cursor_rules_by_precedence(cursor_rules: List[CursorRule]) -> List[CursorRule]:
    """
    Sort Cursor rules by numerical precedence.

    Lower numbers = higher precedence. Legacy rules have precedence 0.

    Args:
        cursor_rules: List of CursorRule objects to sort

    Returns:
        List of CursorRule objects sorted by precedence
    """
    return sorted(cursor_rules, key=lambda rule: rule.precedence)


def merge_claude_memory_content(memory_files: List[ClaudeMemoryFile]) -> str:
    """
    Merge Claude memory file content respecting hierarchy precedence.

    Args:
        memory_files: List of ClaudeMemoryFile objects to merge

    Returns:
        Merged content as string with hierarchy sections
    """
    if not memory_files:
        return ""

    # Sort by precedence
    sorted_files = sort_claude_memory_by_precedence(memory_files)

    merged_parts: List[str] = []

    for memory_file in sorted_files:
        # Add section header for clarity
        section_header = (
            f"<!-- CLAUDE MEMORY: {memory_file.hierarchy_level.upper()} LEVEL -->"
        )
        section_content = (
            f"<!-- Source: {memory_file.file_path} -->\n{memory_file.resolved_content}"
        )

        merged_parts.append(section_header)
        merged_parts.append(section_content)
        merged_parts.append("")  # Add spacing between sections

    return "\n".join(merged_parts).strip()


def merge_cursor_rules_content(cursor_rules: List[CursorRule]) -> str:
    """
    Merge Cursor rules content respecting numerical precedence.

    Args:
        cursor_rules: List of CursorRule objects to merge

    Returns:
        Merged content as string with precedence sections
    """
    if not cursor_rules:
        return ""

    # Sort by precedence
    sorted_rules = sort_cursor_rules_by_precedence(cursor_rules)

    merged_parts: List[str] = []

    for rule in sorted_rules:
        # Add section header for clarity
        rule_type_display = rule.rule_type.upper()
        section_header = (
            f"<!-- CURSOR RULE: {rule_type_display} (Precedence: {rule.precedence}) -->"
        )

        rule_metadata: List[str] = []
        if rule.description:
            rule_metadata.append(f"Description: {rule.description}")
        if rule.globs:
            rule_metadata.append(f"Applies to: {', '.join(rule.globs)}")
        if rule.always_apply:
            rule_metadata.append("Always Apply: Yes")

        metadata_content = ""
        if rule_metadata:
            metadata_content = f"<!-- {' | '.join(rule_metadata)} -->\n"

        section_content = (
            f"<!-- Source: {rule.file_path} -->\n{metadata_content}{rule.content}"
        )

        merged_parts.append(section_header)
        merged_parts.append(section_content)
        merged_parts.append("")  # Add spacing between sections

    return "\n".join(merged_parts).strip()


def deduplicate_claude_memory_files(
    memory_files: List[ClaudeMemoryFile],
) -> List[ClaudeMemoryFile]:
    """
    Deduplicate Claude memory files by canonical path to handle .gitignore cases.

    Args:
        memory_files: List of ClaudeMemoryFile objects that may contain duplicates

    Returns:
        List of unique ClaudeMemoryFile objects (keeps first occurrence)
    """
    seen_paths: set[str] = set()
    unique_files: List[ClaudeMemoryFile] = []

    for memory_file in memory_files:
        # Canonicalize the path to handle symlinks and resolve absolute paths
        try:
            canonical_path = os.path.realpath(memory_file.file_path)
        except (OSError, AttributeError):
            canonical_path = memory_file.file_path

        if canonical_path not in seen_paths:
            seen_paths.add(canonical_path)
            unique_files.append(memory_file)

    return unique_files


def deduplicate_cursor_rules(cursor_rules: List[CursorRule]) -> List[CursorRule]:
    """
    Deduplicate Cursor rules by canonical path to handle .gitignore cases.

    Args:
        cursor_rules: List of CursorRule objects that may contain duplicates

    Returns:
        List of unique CursorRule objects (keeps first occurrence)
    """
    seen_paths: set[str] = set()
    unique_rules: List[CursorRule] = []

    for rule in cursor_rules:
        # Canonicalize the path to handle symlinks and resolve absolute paths
        try:
            canonical_path = os.path.realpath(rule.file_path)
        except (OSError, AttributeError):
            canonical_path = rule.file_path

        if canonical_path not in seen_paths:
            seen_paths.add(canonical_path)
            unique_rules.append(rule)

    return unique_rules


def merge_with_deduplication(content_parts: List[str]) -> str:
    """
    Merge content parts with deduplication of identical sections.

    Args:
        content_parts: List of content strings to merge

    Returns:
        Merged content with duplicates removed
    """
    if not content_parts:
        return ""

    # Keep track of seen content to avoid duplicates
    seen_content: set[str] = set()
    unique_parts: List[str] = []

    for content in content_parts:
        # Normalize content for comparison (remove extra whitespace)
        normalized = re.sub(r"\s+", " ", content.strip())

        if normalized and normalized not in seen_content:
            seen_content.add(normalized)
            unique_parts.append(content)

    return "\n\n".join(unique_parts)


def resolve_content_conflicts(conflicting_contents: List[str]) -> str:
    """
    Resolve conflicts between multiple content sections.

    Uses first-wins strategy (highest precedence wins).

    Args:
        conflicting_contents: List of conflicting content strings

    Returns:
        Resolved content (first item in list)
    """
    if not conflicting_contents:
        return ""

    # First content wins (highest precedence)
    return conflicting_contents[0]


def get_all_cursor_rules(cursor_rules: List[CursorRule]) -> List[CursorRule]:
    """
    Return all cursor rules (simplified approach - no filtering).

    Args:
        cursor_rules: List of CursorRule objects

    Returns:
        All CursorRule objects unchanged
    """
    return cursor_rules


def get_applicable_cursor_rules_for_files(
    cursor_rules: List[CursorRule], changed_files: List[str]
) -> List[CursorRule]:
    """
    Return all cursor rules (simplified approach - no file matching).

    Args:
        cursor_rules: List of CursorRule objects
        changed_files: List of file paths (unused in simplified approach)

    Returns:
        All CursorRule objects unchanged
    """
    return cursor_rules


def create_configuration_context(
    claude_memory_files: List[ClaudeMemoryFile], cursor_rules: List[CursorRule]
) -> ConfigurationContextDict:
    """
    Create configuration context from Claude memory files and Cursor rules.

    Args:
        claude_memory_files: List of discovered Claude memory files
        cursor_rules: List of discovered Cursor rules

    Returns:
        Dictionary containing complete configuration context
    """
    # Deduplicate files to handle .gitignore cases
    unique_claude_files = deduplicate_claude_memory_files(claude_memory_files)
    unique_cursor_rules = deduplicate_cursor_rules(cursor_rules)

    # Merge Claude memory content
    claude_content = merge_claude_memory_content(unique_claude_files)

    # Merge Cursor rules content
    cursor_content = merge_cursor_rules_content(unique_cursor_rules)

    # Combine all content
    all_content_parts: List[str] = []
    if claude_content:
        all_content_parts.append("# Claude Memory Configuration\n\n" + claude_content)
    if cursor_content:
        all_content_parts.append("# Cursor Rules Configuration\n\n" + cursor_content)

    merged_content = merge_with_deduplication(all_content_parts)

    # Get all cursor rules (simplified approach)
    auto_apply_rules = get_all_cursor_rules(unique_cursor_rules)

    result: ConfigurationContextDict = {
        "claude_memory_files": unique_claude_files,
        "cursor_rules": unique_cursor_rules,
        "merged_content": merged_content,
        "auto_apply_rules": auto_apply_rules,
        "error_summary": [],
    }
    return result


def create_configuration_context_for_files(
    claude_memory_files: List[ClaudeMemoryFile],
    cursor_rules: List[CursorRule],
    changed_files: List[str],
) -> Dict[str, Any]:
    """
    Create configuration context with file-specific rule matching.

    Args:
        claude_memory_files: List of discovered Claude memory files
        cursor_rules: List of discovered Cursor rules
        changed_files: List of files that changed (for rule matching)

    Returns:
        Dictionary containing configuration context with applicable rules
    """
    # Simplified: just use all cursor rules
    applicable_rules = cursor_rules

    # Create context with all rules
    base_context = create_configuration_context(claude_memory_files, cursor_rules)
    extended_context: Dict[str, Any] = dict(base_context)
    extended_context["applicable_rules"] = applicable_rules
    extended_context["all_cursor_rules"] = cursor_rules
    extended_context["changed_files"] = changed_files

    return extended_context


def create_configuration_context_with_error_handling(
    claude_memory_files: List[ClaudeMemoryFile],
    cursor_rules: List[CursorRule],
    import_errors: List[Dict[str, Any]],
) -> ConfigurationContextDict:
    """
    Create configuration context with comprehensive error handling.

    Args:
        claude_memory_files: List of discovered Claude memory files
        cursor_rules: List of discovered Cursor rules
        import_errors: List of import/parsing errors

    Returns:
        Dictionary containing configuration context with error summary
    """
    try:
        context = create_configuration_context(claude_memory_files, cursor_rules)
        context["error_summary"] = import_errors
        return context

    except Exception as e:
        logger.error(f"Failed to create configuration context: {e}")

        # Return minimal context with error information
        result: ConfigurationContextDict = {
            "claude_memory_files": claude_memory_files,
            "cursor_rules": cursor_rules,
            "merged_content": "# Configuration Context Error\n\nFailed to merge configuration content.",
            "auto_apply_rules": [],
            "error_summary": import_errors
            + [{"error_type": "context_creation_error", "error_message": str(e)}],
        }
        return result


def validate_configuration_context(context: Dict[str, Any]) -> List[str]:
    """
    Validate configuration context for completeness and correctness.

    Args:
        context: Configuration context dictionary to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: List[str] = []

    # Check required fields
    required_fields = [
        "claude_memory_files",
        "cursor_rules",
        "merged_content",
        "auto_apply_rules",
        "error_summary",
    ]
    for field in required_fields:
        if field not in context:
            errors.append(f"Missing required field: {field}")

    # Validate field types
    if "claude_memory_files" in context and not isinstance(
        context["claude_memory_files"], list
    ):
        errors.append("claude_memory_files must be a list")

    if "cursor_rules" in context and not isinstance(context["cursor_rules"], list):
        errors.append("cursor_rules must be a list")

    if "merged_content" in context and not isinstance(context["merged_content"], str):
        errors.append("merged_content must be a string")

    if "auto_apply_rules" in context and not isinstance(
        context["auto_apply_rules"], list
    ):
        errors.append("auto_apply_rules must be a list")

    if "error_summary" in context and not isinstance(context["error_summary"], list):
        errors.append("error_summary must be a list")

    # Validate that auto_apply_rules are a subset of cursor_rules
    if "auto_apply_rules" in context and "cursor_rules" in context:
        auto_apply_rules_data = context["auto_apply_rules"]
        cursor_rules_data = context["cursor_rules"]
        
        if isinstance(auto_apply_rules_data, list) and isinstance(cursor_rules_data, list):
            # Type guard to ensure we have CursorRule objects
            auto_apply_rules: List[CursorRule] = []
            cursor_rules: List[CursorRule] = []
            
            for rule in auto_apply_rules_data:
                # CursorRule objects from dataclass have file_path attribute
                if isinstance(rule, CursorRule):
                    auto_apply_rules.append(rule)
            
            for rule in cursor_rules_data:
                # CursorRule objects from dataclass have file_path attribute
                if isinstance(rule, CursorRule):
                    cursor_rules.append(rule)
            auto_paths: set[str] = {rule.file_path for rule in auto_apply_rules}
            all_paths: set[str] = {rule.file_path for rule in cursor_rules}

            if not auto_paths.issubset(all_paths):
                errors.append("auto_apply_rules contains rules not found in cursor_rules")

    return errors


def get_configuration_summary(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get summary statistics for configuration context.

    Args:
        context: Configuration context dictionary

    Returns:
        Dictionary containing summary statistics
    """
    summary: Dict[str, Any] = {
        "claude_memory_count": len(context.get("claude_memory_files", [])),
        "cursor_rules_count": len(context.get("cursor_rules", [])),
        "auto_apply_rules_count": len(context.get("auto_apply_rules", [])),
        "error_count": len(context.get("error_summary", [])),
        "merged_content_length": len(context.get("merged_content", "")),
        "hierarchy_levels": [],
        "rule_types": [],
        "precedence_range": {"min": None, "max": None},
    }

    # Analyze Claude memory hierarchy levels
    for memory_file in context.get("claude_memory_files", []):
        if memory_file.hierarchy_level not in summary["hierarchy_levels"]:
            summary["hierarchy_levels"].append(memory_file.hierarchy_level)

    # Analyze Cursor rule types and precedence
    precedences: List[int] = []
    for rule in context.get("cursor_rules", []):
        if rule.rule_type not in summary["rule_types"]:
            summary["rule_types"].append(rule.rule_type)
        precedences.append(rule.precedence)

    if precedences:
        summary["precedence_range"]["min"] = min(precedences)
        summary["precedence_range"]["max"] = max(precedences)

    return summary
