# Task List Code Review MCP - Development Makefile
# Provides simple commands for common development tasks

.PHONY: help review prompt ai-review install test clean

help:  ## Show this help message
	@echo "🔧 Development Commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "💡 Examples:"
	@echo "  make review PROJECT=."
	@echo "  make review PROJECT=. SCOPE=full_project"
	@echo "  make prompt PROJECT=."
	@echo "  make prompt PROJECT=. STREAM=1"
	@echo "  make test"

review:  ## Generate code review context + AI feedback (use: make review PROJECT=/path SCOPE=full_project)
	@if [ "$(PROJECT)" = "" ]; then \
		echo "Usage: make review PROJECT=/path/to/project [SCOPE=full_project]"; \
		echo "Examples:"; \
		echo "  make review PROJECT=."; \
		echo "  make review PROJECT=. SCOPE=full_project"; \
		echo "  make review PROJECT=/path/to/project SCOPE=recent_phase"; \
		exit 1; \
	fi
	@if [ "$(SCOPE)" != "" ]; then \
		python3 -m src.generate_code_review_context $(PROJECT) --scope $(SCOPE); \
	else \
		python3 -m src.generate_code_review_context $(PROJECT); \
	fi

prompt:  ## Generate meta-prompt for AI code review (use: make prompt PROJECT=/path STREAM=1)
	@if [ "$(PROJECT)" = "" ] && [ "$(CONTEXT_FILE)" = "" ]; then \
		echo "Usage: make prompt PROJECT=/path/to/project [STREAM=1]"; \
		echo "   or: make prompt CONTEXT_FILE=context.md [STREAM=1]"; \
		echo "Examples:"; \
		echo "  make prompt PROJECT=."; \
		echo "  make prompt PROJECT=. STREAM=1"; \
		echo "  make prompt CONTEXT_FILE=context.md"; \
		exit 1; \
	fi
	@if [ "$(PROJECT)" != "" ]; then \
		if [ "$(STREAM)" = "1" ]; then \
			python3 -m src.auto_prompt_generator --project-path $(PROJECT) --stream; \
		else \
			python3 -m src.auto_prompt_generator --project-path $(PROJECT); \
		fi; \
	elif [ "$(CONTEXT_FILE)" != "" ]; then \
		if [ "$(STREAM)" = "1" ]; then \
			python3 -m src.auto_prompt_generator --context-file $(CONTEXT_FILE) --stream; \
		else \
			python3 -m src.auto_prompt_generator --context-file $(CONTEXT_FILE); \
		fi; \
	fi

ai-review:  ## Run AI review on existing context file (use: make ai-review CONTEXT_FILE=file.md)
	@if [ "$(CONTEXT_FILE)" = "" ]; then \
		echo "Usage: make ai-review CONTEXT_FILE=/path/to/context-file.md"; \
		echo "Example: make ai-review CONTEXT_FILE=code-review-context-20241201.md"; \
		exit 1; \
	fi
	python3 -m src.ai_code_review $(CONTEXT_FILE)

install:  ## Install package in development mode
	pip3 install -e .

install-deps:  ## Install development dependencies
	pip3 install -e ".[dev]"

test:  ## Run tests
	python3 -m pytest tests/ -v

test-cli:  ## Test CLI functionality
	python3 scripts/check-cli.py

lint:  ## Run code linting
	python3 -m black src/ tests/
	python3 -m isort src/ tests/
	python3 -m flake8 src/ tests/

clean:  ## Clean generated files
	rm -f code-review-*.md
	rm -f meta-prompt-*.md
	rm -rf __pycache__
	rm -rf src/__pycache__
	rm -rf tests/__pycache__
	rm -rf *.egg-info
	rm -rf dist/
	rm -rf build/

build:  ## Build package
	python3 -m build

# Prevent make from interpreting command line arguments as targets
%:
	@: