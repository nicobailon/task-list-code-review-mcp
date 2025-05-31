"""
🔴 TDD RED: Test for pure in-memory context generation.

This test defines the requirement: we need a function that generates 
context content in memory without ANY file system operations.
"""

import pytest
import tempfile
from pathlib import Path
import os


def test_in_memory_context_generation_exists():
    """🔴 RED: Test that we have an in-memory context generation function."""
    try:
        from src.server import generate_context_in_memory
        assert callable(generate_context_in_memory), "Function should be callable"
    except ImportError:
        pytest.fail("🔴 generate_context_in_memory function does not exist yet")


def test_in_memory_context_generation_no_files():
    """🔴 RED: Test that in-memory generation creates NO files."""
    from src.server import generate_context_in_memory
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Files before
        files_before = set(Path(temp_dir).glob("*"))
        
        # Generate context in memory
        context_content = generate_context_in_memory(
            github_pr_url="https://github.com/nicobailon/task-list-code-review-mcp/pull/5",
            project_path=temp_dir,
            include_claude_memory=True,
            include_cursor_rules=False,
            auto_prompt_content=None
        )
        
        # Files after
        files_after = set(Path(temp_dir).glob("*"))
        new_files = files_after - files_before
        
        # CRITICAL: NO files should be created
        assert len(new_files) == 0, f"🔴 In-memory generation created files: {new_files}"
        
        # Should return string content
        assert isinstance(context_content, str), f"Should return string, got {type(context_content)}"
        assert len(context_content) > 0, "Should return non-empty content"
        assert "# Code Review Context" in context_content, "Should contain context header"


def test_in_memory_context_content_quality():
    """🔴 RED: Test that in-memory generated content has expected structure."""
    from src.server import generate_context_in_memory
    
    with tempfile.TemporaryDirectory() as temp_dir:
        context_content = generate_context_in_memory(
            github_pr_url="https://github.com/nicobailon/task-list-code-review-mcp/pull/5",
            project_path=temp_dir,
            include_claude_memory=True,
            include_cursor_rules=False,
            auto_prompt_content="Custom meta prompt content"
        )
        
        # Should contain expected sections
        assert "# Code Review Context" in context_content
        assert "Custom meta prompt content" in context_content
        assert "GitHub PR Analysis" in context_content or "Pull Request" in context_content
        
        # Should be substantial content (not empty or minimal)
        assert len(context_content) > 1000, f"Content too short: {len(context_content)} chars"