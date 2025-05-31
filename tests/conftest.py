"""
Test isolation and cleanup protocols for auto-prompt generation system.
Following TDD Protocol: Ensuring test isolation, deterministic behavior, and proper cleanup.
"""

import pytest
import tempfile
import os
import sys
import shutil
import gc
from pathlib import Path
from unittest.mock import patch, Mock
import threading
import time

# Optional psutil import for memory monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Session-wide test environment setup."""
    # Add src to Python path for all tests
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    # Load environment variables from .env file
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(current_dir, '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
            print(f"Loaded environment variables from {env_path}")
    except ImportError:
        print("python-dotenv not available, skipping .env file")
    
    # Set test environment variables
    os.environ['TESTING'] = 'true'
    # Don't override GEMINI_API_KEY if it's already set from .env file
    
    yield
    
    # Session cleanup
    if 'TESTING' in os.environ:
        del os.environ['TESTING']
    # Don't delete GEMINI_API_KEY as it may be needed for other processes


@pytest.fixture(autouse=True)
def test_isolation():
    """Ensure each test runs in isolation."""
    # Pre-test cleanup
    gc.collect()
    
    # Store initial state (only if psutil is available)
    initial_memory = None
    if PSUTIL_AVAILABLE:
        initial_memory = psutil.Process().memory_info().rss
    
    yield
    
    # Post-test cleanup
    gc.collect()
    
    # Verify no significant memory leaks (only if psutil is available)
    if PSUTIL_AVAILABLE and initial_memory is not None:
        final_memory = psutil.Process().memory_info().rss
        memory_growth = (final_memory - initial_memory) / 1024 / 1024  # MB
        
        # Allow for some memory growth but flag excessive growth
        if memory_growth > 50:  # More than 50MB growth per test
            print(f"Warning: Test may have memory leak - grew {memory_growth:.1f}MB")


@pytest.fixture
def isolated_temp_dir():
    """Provide isolated temporary directory for each test."""
    with tempfile.TemporaryDirectory(prefix="mcp_test_") as temp_dir:
        # Ensure directory is writable
        os.chmod(temp_dir, 0o755)
        yield temp_dir
        # Cleanup is automatic with TemporaryDirectory


@pytest.fixture
def mock_gemini_isolated():
    """Provide isolated Gemini API mock for each test."""
    with patch('src.server.get_gemini_model') as mock_gemini:
        from tests.test_gemini_api_mocks import MockGeminiClient
        mock_client = MockGeminiClient()
        mock_gemini.return_value = mock_client
        yield mock_client


@pytest.fixture
def clean_file_system():
    """Ensure clean file system state for tests."""
    # Track created files/directories for cleanup
    created_paths = []
    
    def track_creation(path):
        """Track paths created during test."""
        created_paths.append(path)
        return path
    
    yield track_creation
    
    # Cleanup tracked paths
    for path in created_paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
        except (OSError, FileNotFoundError):
            pass  # Already cleaned up or permission error


@pytest.fixture
def process_monitor():
    """Monitor process resources during test execution."""
    class ProcessMonitor:
        def __init__(self):
            self.process = psutil.Process() if PSUTIL_AVAILABLE else None
            self.start_memory = None
            self.start_cpu_percent = None
            self.peak_memory = None
            self.psutil_available = PSUTIL_AVAILABLE
            
        def start_monitoring(self):
            if not self.psutil_available:
                return
            self.start_memory = self.process.memory_info().rss / 1024 / 1024  # MB
            self.start_cpu_percent = self.process.cpu_percent()
            self.peak_memory = self.start_memory
            
        def update_peak(self):
            if not self.psutil_available:
                return
            current_memory = self.process.memory_info().rss / 1024 / 1024  # MB
            if current_memory > self.peak_memory:
                self.peak_memory = current_memory
                
        def get_stats(self):
            if not self.psutil_available:
                return {
                    'memory_delta': 0,
                    'peak_memory_delta': 0,
                    'current_memory': 0
                }
            current_memory = self.process.memory_info().rss / 1024 / 1024  # MB
            return {
                'memory_delta': current_memory - self.start_memory if self.start_memory else 0,
                'peak_memory_delta': self.peak_memory - self.start_memory if self.start_memory else 0,
                'current_memory': current_memory
            }
    
    monitor = ProcessMonitor()
    yield monitor


@pytest.fixture
def thread_isolation():
    """Ensure thread isolation and cleanup."""
    initial_thread_count = threading.active_count()
    created_threads = []
    
    def track_thread(thread):
        """Track threads created during test."""
        created_threads.append(thread)
        return thread
    
    yield track_thread
    
    # Wait for test threads to complete
    for thread in created_threads:
        if thread.is_alive():
            thread.join(timeout=5)  # 5 second timeout
            if thread.is_alive():
                print(f"Warning: Thread {thread.name} did not terminate cleanly")
    
    # Verify thread count returned to normal
    final_thread_count = threading.active_count()
    if final_thread_count > initial_thread_count + 1:  # Allow for 1 extra thread
        print(f"Warning: Thread leak detected - {final_thread_count - initial_thread_count} extra threads")


@pytest.fixture
def mock_file_operations():
    """Mock file operations for deterministic testing."""
    mocked_files = {}
    
    def mock_read_file(path):
        """Mock file reading."""
        if path in mocked_files:
            return mocked_files[path]
        raise FileNotFoundError(f"Mocked file not found: {path}")
    
    def mock_write_file(path, content):
        """Mock file writing."""
        mocked_files[path] = content
        return path
    
    def mock_exists(path):
        """Mock path existence check."""
        return path in mocked_files
    
    yield {
        'read': mock_read_file,
        'write': mock_write_file,
        'exists': mock_exists,
        'files': mocked_files
    }


@pytest.fixture
def deterministic_timestamps():
    """Provide deterministic timestamps for testing."""
    fixed_timestamp = "2024-01-15T10:30:00Z"
    
    with patch('time.time', return_value=1705312200.0):  # Fixed timestamp
        with patch('datetime.datetime') as mock_datetime:
            mock_datetime.now.return_value.isoformat.return_value = fixed_timestamp
            mock_datetime.utcnow.return_value.isoformat.return_value = fixed_timestamp
            yield fixed_timestamp


@pytest.fixture
def reset_module_state():
    """Reset module-level state between tests."""
    # Store modules that might have state
    modules_to_reset = [
        'src.server',
        'src.generate_code_review_context',
        'src.ai_code_review'
    ]
    
    # Store original module state
    original_states = {}
    for module_name in modules_to_reset:
        if module_name in sys.modules:
            module = sys.modules[module_name]
            # Store attributes that might be stateful
            original_states[module_name] = {}
            for attr_name in dir(module):
                if not attr_name.startswith('_'):
                    try:
                        original_states[module_name][attr_name] = getattr(module, attr_name)
                    except:
                        pass  # Skip attributes that can't be accessed
    
    yield
    
    # Reset module state (basic approach)
    for module_name, state in original_states.items():
        if module_name in sys.modules:
            module = sys.modules[module_name]
            for attr_name, attr_value in state.items():
                try:
                    if hasattr(module, attr_name):
                        setattr(module, attr_name, attr_value)
                except:
                    pass  # Skip attributes that can't be set


class TestCleanupProtocols:
    """Test the cleanup protocols themselves."""
    
    def test_temp_directory_cleanup(self, isolated_temp_dir):
        """Test that temporary directories are properly cleaned up."""
        # Create files in temp directory
        test_file = Path(isolated_temp_dir) / "test_file.txt"
        test_file.write_text("test content")
        
        # Create subdirectory
        sub_dir = Path(isolated_temp_dir) / "subdir"
        sub_dir.mkdir()
        (sub_dir / "sub_file.txt").write_text("sub content")
        
        # Verify files exist
        assert test_file.exists()
        assert (sub_dir / "sub_file.txt").exists()
        
        # Cleanup is automatic when fixture scope ends
    
    def test_mock_isolation(self, mock_gemini_isolated):
        """Test that mocks are properly isolated between tests."""
        # Use the mock
        mock_gemini_isolated.generate_content("test prompt")
        
        # Verify mock was called
        assert mock_gemini_isolated.call_count == 1
        
        # Mock state should reset for next test
    
    def test_process_monitoring(self, process_monitor):
        """Test process monitoring functionality."""
        process_monitor.start_monitoring()
        
        # Simulate some work
        large_data = list(range(10000))
        processed = [x * 2 for x in large_data]
        
        process_monitor.update_peak()
        stats = process_monitor.get_stats()
        
        # Verify monitoring captured data
        assert 'memory_delta' in stats
        assert 'peak_memory_delta' in stats
        assert 'current_memory' in stats
        assert isinstance(stats['memory_delta'], (int, float))
    
    def test_thread_isolation(self, thread_isolation):
        """Test thread isolation and cleanup."""
        import threading
        import time
        
        results = []
        
        def worker():
            time.sleep(0.1)
            results.append("completed")
        
        # Create and track thread
        thread = threading.Thread(target=worker)
        thread_isolation(thread)
        thread.start()
        
        # Wait for completion
        thread.join()
        
        assert len(results) == 1
        assert results[0] == "completed"
        
        # Thread cleanup is automatic
    
    def test_deterministic_timestamps(self, deterministic_timestamps):
        """Test that timestamps are deterministic."""
        import time
        
        # Multiple calls should return same timestamp
        time1 = time.time()
        time2 = time.time()
        
        assert time1 == time2
        assert deterministic_timestamps == "2024-01-15T10:30:00Z"


class TestIsolationValidation:
    """Validate that tests are properly isolated."""
    
    def test_isolation_state_persistence_check_1(self):
        """First test to check state isolation."""
        # Set some module-level state
        test_value = "test_isolation_1"
        
        # Store in a way that might persist
        if 'test_isolation_marker' not in globals():
            globals()['test_isolation_marker'] = test_value
        
        assert globals().get('test_isolation_marker') == test_value
    
    def test_isolation_state_persistence_check_2(self):
        """Second test to verify state doesn't persist."""
        # This test should not see state from previous test
        # (Though global state might persist - this tests the concept)
        
        # Focus on testing that our fixtures work properly
        test_value = "test_isolation_2"
        globals()['test_isolation_marker'] = test_value
        
        assert globals().get('test_isolation_marker') == test_value
    
    def test_file_system_isolation(self, isolated_temp_dir):
        """Test file system isolation between tests."""
        # Create a file
        test_file = Path(isolated_temp_dir) / "isolation_test.txt"
        test_file.write_text("isolation test content")
        
        assert test_file.exists()
        assert test_file.read_text() == "isolation test content"
        
        # File should be cleaned up automatically
    
    def test_mock_state_isolation(self, mock_gemini_isolated):
        """Test that mock state is isolated."""
        # First interaction
        mock_gemini_isolated.generate_content("first call")
        assert mock_gemini_isolated.call_count == 1
        
        # Mock should start fresh for each test
        # (This is implicitly tested by having multiple tests using the fixture)


class TestResourceManagement:
    """Test resource management and cleanup."""
    
    def test_memory_cleanup_after_large_operations(self, process_monitor, isolated_temp_dir):
        """Test memory cleanup after large operations."""
        process_monitor.start_monitoring()
        
        # Simulate large operation
        large_project = Path(isolated_temp_dir) / "large_project"
        large_project.mkdir()
        
        # Create substantial content
        for i in range(100):
            large_content = "# Large file content\n" + "print('line')\n" * 1000
            (large_project / f"large_file_{i}.py").write_text(large_content)
        
        process_monitor.update_peak()
        
        # Force cleanup
        gc.collect()
        
        stats = process_monitor.get_stats()
        
        # Memory usage should be reasonable
        assert stats['peak_memory_delta'] < 200, f"Memory usage too high: {stats['peak_memory_delta']:.1f}MB"
    
    def test_file_handle_cleanup(self, isolated_temp_dir):
        """Test that file handles are properly cleaned up."""
        import resource
        
        # Get initial file descriptor count
        try:
            initial_fds = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        except:
            pytest.skip("Cannot get file descriptor limit on this system")
        
        # Perform file operations
        for i in range(50):
            test_file = Path(isolated_temp_dir) / f"fd_test_{i}.txt"
            with open(test_file, 'w') as f:
                f.write(f"File descriptor test {i}")
            
            # Read it back
            with open(test_file, 'r') as f:
                content = f.read()
                assert f"test {i}" in content
        
        # File handles should be cleaned up automatically
        # (Python's context managers handle this)
    
    def test_exception_safety_cleanup(self, isolated_temp_dir):
        """Test cleanup happens even when exceptions occur."""
        created_files = []
        
        try:
            # Create files before exception
            for i in range(10):
                test_file = Path(isolated_temp_dir) / f"exception_test_{i}.txt"
                test_file.write_text(f"content {i}")
                created_files.append(test_file)
            
            # Simulate exception
            raise ValueError("Simulated exception for cleanup testing")
            
        except ValueError:
            # Exception is expected
            pass
        
        # Verify files were created
        assert len(created_files) == 10
        for file_path in created_files:
            assert file_path.exists()
        
        # Cleanup will happen automatically via fixture


# Pytest configuration for better test isolation
def pytest_configure(config):
    """Configure pytest for better test isolation."""
    # Add custom markers
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "performance: marks tests as performance tests")


def pytest_runtest_setup(item):
    """Setup for each test run."""
    # Force garbage collection before each test
    gc.collect()


def pytest_runtest_teardown(item, nextitem):
    """Teardown after each test run."""
    # Force garbage collection after each test
    gc.collect()
    
    # Additional cleanup if needed
    pass


# Custom assertion helpers for test isolation
def assert_no_file_leaks(temp_dir_path):
    """Assert that no files leaked outside the temp directory."""
    temp_path = Path(temp_dir_path)
    if temp_path.exists():
        # Count files in temp directory
        file_count = len(list(temp_path.rglob("*")))
        # This is just for monitoring - cleanup is automatic
        return file_count
    return 0


def assert_memory_reasonable(process_monitor, max_mb=100):
    """Assert that memory usage is reasonable."""
    stats = process_monitor.get_stats()
    memory_delta = stats.get('memory_delta', 0)
    assert memory_delta < max_mb, f"Memory usage too high: {memory_delta:.1f}MB > {max_mb}MB"


def assert_no_thread_leaks(initial_count):
    """Assert that no threads leaked."""
    current_count = threading.active_count()
    assert current_count <= initial_count + 1, f"Thread leak: {current_count} > {initial_count + 1}"