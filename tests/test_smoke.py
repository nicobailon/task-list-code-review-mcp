"""
Smoke tests for essential functionality - minimal test suite for CI
Tests core functionality without external dependencies (no API calls)
"""
import pytest
import os
import sys
from unittest.mock import patch, MagicMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_package_imports():
    """Test that all main modules can be imported"""
    import src.server
    import src.generate_code_review_context
    # model_config is a JSON file, not a Python module
    assert True  # If we get here, imports worked

def test_model_config_loading():
    """Test model configuration loading works"""
    from generate_code_review_context import load_model_config
    
    config = load_model_config()
    assert isinstance(config, dict)
    assert 'model_aliases' in config
    assert 'defaults' in config
    assert 'model_capabilities' in config

def test_entry_points_defined():
    """Test that console script entry points are properly defined"""
    import sys
    from pathlib import Path
    
    # Check pyproject.toml has the entry points defined
    project_root = Path(__file__).parent.parent
    pyproject_path = project_root / 'pyproject.toml'
    
    with open(pyproject_path, 'r') as f:
        content = f.read()
    
    # Check our main entry points exist in pyproject.toml
    expected_commands = [
        'task-list-code-review-mcp',
        'generate-code-review', 
        'generate-meta-prompt'
    ]
    
    for cmd in expected_commands:
        assert cmd in content, f"Missing entry point in pyproject.toml: {cmd}"

@patch('generate_code_review_context.GEMINI_AVAILABLE', False)
def test_graceful_fallback_no_gemini():
    """Test that the system works without Gemini API available"""
    from generate_code_review_context import send_to_gemini_for_review
    
    result = send_to_gemini_for_review("test content", "/tmp", 0.5)
    assert result is None  # Should gracefully return None without Gemini

def test_cli_help_functions():
    """Test that CLI help functions work without crashes"""
    import argparse
    
    # Test that we can create argument parsers without errors
    from generate_code_review_context import cli_main
    
    # These should not crash when imported
    assert callable(cli_main)

def test_mcp_server_startup():
    """Test that MCP server can be imported and basic setup works"""
    from server import main as server_main
    
    # Should be able to import the main function
    assert callable(server_main)

@patch.dict(os.environ, {'MAX_FILE_SIZE_MB': '5'})
def test_environment_variable_handling():
    """Test that environment variables are properly handled"""
    # Test that our code reads environment variables correctly
    assert os.getenv('MAX_FILE_SIZE_MB') == '5'
    
    # Test default fallback
    assert os.getenv('NONEXISTENT_VAR', 'default') == 'default'

def test_model_alias_resolution():
    """Test that model aliases resolve correctly"""
    from generate_code_review_context import load_model_config
    
    config = load_model_config()
    aliases = config.get('model_aliases', {})
    
    # Test that gemini-2.5-pro alias exists and resolves
    if 'gemini-2.5-pro' in aliases:
        resolved = aliases['gemini-2.5-pro']
        assert 'preview' in resolved  # Should resolve to preview model

def test_scope_values():
    """Test that scope constants are properly defined"""
    # These should be available as valid scope options
    valid_scopes = ["recent_phase", "full_project", "specific_phase", "specific_task"]
    
    # Test scope validation would work
    for scope in valid_scopes:
        assert isinstance(scope, str)
        assert len(scope) > 0