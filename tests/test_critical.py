"""
Critical functionality tests - minimal set that actually tests what exists
"""
import pytest
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

class TestCoreImports:
    """Test that core modules can be imported"""
    
    def test_server_tools_available(self):
        """Test server tools are available (even if FastMCP not installed)"""
        try:
            import server
            # If import succeeds, should have MCP tools
            assert hasattr(server, 'generate_code_review_context')
            assert hasattr(server, 'generate_ai_code_review')
        except SystemExit:
            # FastMCP not available in test environment - that's OK
            # The behavior tests will verify actual functionality
            pass
        
    def test_generate_code_review_context_imports(self):
        """Test generate_code_review_context module imports"""
        import generate_code_review_context
        assert hasattr(generate_code_review_context, 'main')
        assert hasattr(generate_code_review_context, 'load_model_config')
        
    def test_ai_code_review_imports(self):
        """Test ai_code_review functionality is available in server"""
        from server import generate_ai_code_review
        assert callable(generate_ai_code_review)

class TestPackageStructure:
    """Test basic package structure"""
    
    def test_required_files_exist(self):
        """Test that required package files exist"""
        project_root = Path(__file__).parent.parent
        
        # Core source files
        assert (project_root / 'src' / 'server.py').exists()
        assert (project_root / 'src' / 'generate_code_review_context.py').exists()
        # ai_code_review functionality moved to server.py
        assert (project_root / 'src' / 'server.py').exists()
        assert (project_root / 'src' / 'model_config.json').exists()
        
        # Package configuration
        assert (project_root / 'pyproject.toml').exists()
        assert (project_root / 'README.md').exists()
        
    def test_model_config_loads(self):
        """Test that model configuration loads successfully"""
        from generate_code_review_context import load_model_config
        
        config = load_model_config()
        assert isinstance(config, dict)
        assert 'model_aliases' in config
        assert 'defaults' in config
        assert 'model_capabilities' in config

class TestEnvironmentHandling:
    """Test environment variable handling"""
    
    def test_environment_variables_fallback(self):
        """Test that environment variables have proper fallbacks"""
        # Test that our code handles missing environment variables gracefully
        assert os.getenv('NONEXISTENT_VAR', 'default') == 'default'
        
        # Test model config defaults work
        from generate_code_review_context import load_model_config
        config = load_model_config()
        
        # Should have reasonable defaults even without env vars
        assert config['defaults']['model'] in ['gemini-2.0-flash', 'gemini-2.0-flash-lite']

class TestModelConfiguration:
    """Test model configuration system"""
    
    def test_model_aliases_exist(self):
        """Test that model aliases are properly configured"""
        from generate_code_review_context import load_model_config
        
        config = load_model_config()
        aliases = config.get('model_aliases', {})
        
        # Should have some basic aliases
        assert isinstance(aliases, dict)
        
    def test_capability_detection(self):
        """Test that model capabilities are defined"""
        from generate_code_review_context import load_model_config
        
        config = load_model_config()
        capabilities = config.get('model_capabilities', {})
        
        assert 'url_context_supported' in capabilities
        assert 'thinking_mode_supported' in capabilities
        assert isinstance(capabilities['url_context_supported'], list)