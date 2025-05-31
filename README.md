# Task List Code Review MCP Server & CLI Tool

An MCP server designed for **AI coding agents** (Cursor, Claude Code, etc.) with **standalone CLI support** to automatically generate comprehensive code review context when completing development phases.

**Version**: 0.3.9 - Enhanced with optimized auto meta prompt generation (default enabled), multi-mode AI review support, MCP text response chaining, and streamlined command structure.

## 🎯 Usage Options

**🤖 MCP Server** (Primary): Integration with AI agents (Claude Code, Cursor)  
**🖥️ Standalone CLI**: Direct command-line usage for manual code reviews + auto-prompt generation  
**⚠️ Note**: Use development commands if getting cached/old versions  
**🔗 Hybrid**: Use CLI for testing/auto-prompts, then integrate as MCP server for AI workflows

**📊 [Workflow Diagrams](./WORKFLOW_DIAGRAMS.md)**: Visual ASCII flow diagrams for all tools and commands

## 🚀 Quick Start

> **💡 Most Common Use**: MCP Server integration with AI agents (Claude Code, Cursor)

### 🤖 MCP Server Integration (Primary Usage)

**Recommended**: Use as MCP server with AI coding agents:

```bash
# Set your Gemini API key (get one at https://ai.google.dev/gemini-api/docs/api-key)
export GEMINI_API_KEY=your_key_here

# Add MCP server to Claude Code
claude mcp add task-list-reviewer -e GEMINI_API_KEY=your_key_here -- uvx task-list-code-review-mcp

# Or use with Cursor via .cursorrules or similar AI agent integration
```

### 🖥️ Standalone CLI Usage

**For direct command-line usage:**

```bash
# 🔧 Development/Local Testing (always works)
python -m src.generate_code_review_context /path/to/project --scope full_project
python -m src.meta_prompt_generator --project-path /path/to/project

# 📦 After installing globally
pip install task-list-code-review-mcp
generate-code-review /path/to/your/project
generate-meta-prompt --context-file tasks/context.md
```

### Install Options

```bash
# Option 1: Use with uvx (no installation, MCP server only)
uvx task-list-code-review-mcp  # Starts MCP server

# Option 2: Install globally for CLI tools
pip install task-list-code-review-mcp
generate-code-review --help
generate-meta-prompt --help
```

## ✨ Key Features

### 🎯 Meta-Prompt Generation (Enhanced & Optimized!)
- **🤖 MCP Tool**: `generate_meta_prompt` → Creates AI-optimized review prompts from completed work
- **🖥️ Standalone CLI**: `generate-meta-prompt` → Command-line meta-prompt generation
- **⚡ Auto-Enabled**: `auto_meta_prompt=true` by default in context generation (v0.3.9+)
- **🚀 Optimized**: No intermediate files created - direct project analysis and generation
- **📄 File Output**: Saves formatted meta-prompts to timestamped .md files (default: current directory)
- **📡 Stream Output**: `--stream` flag outputs prompts directly to stdout
- **🎨 Custom Templates**: Support for custom meta-prompt templates
- **🧠 Intelligent Analysis**: Analyzes codebase context to create targeted review prompts

### Smart Scope Detection
- **All phases complete** → Automatically generates comprehensive full-project review
- **Phases in progress** → Reviews most recently completed phase
- **Manual override** → Target specific phases or tasks

### AI-Powered Code Review
- **Smart Model Selection**: Auto-detects and displays enabled capabilities
- **Enhanced Features**: Thinking mode, web grounding, URL context (when available)
- **Real-time Feedback**: Shows model name and active features during execution
- **Comprehensive Analysis**: Security, performance, testing, maintainability

### Flexible Architecture
- **Context Generation**: Creates structured review context from git changes and task progress
- **AI Review**: Separate tool for generating AI-powered feedback from context files
- **Model Configuration**: Easy model switching and alias management via JSON config

## 📖 Usage Guide

### 🚀 Essential Commands (80% Use Cases)

> **⚡ Quick Reference**:
> - **MCP Server**: Used via AI agents (Claude Code, Cursor) - no direct CLI
> - **CLI Tools**: `generate-code-review .` - Smart review current project  
> - **CLI Tools**: `generate-meta-prompt --project-path .` - Just the meta-prompt

```bash
# 🤖 MCP Server Usage (Primary)
# Use through AI agents like Claude Code:
# Human: "Generate a code review for my project"
# Claude: [Uses MCP tools automatically]

# 🖥️ CLI Usage (Development/Testing)
# Direct command-line usage:
python -m src.generate_code_review_context /path/to/project
# 🔍 Auto-detects completion status → 🤖 Model capabilities → 📄 Generated files

# After pip install:
generate-code-review /path/to/project --scope full_project
generate-meta-prompt --project-path /path/to/project
```

### 🔧 Advanced CLI Usage

```bash
# 🎯 META-PROMPT GENERATION

# Generate optimized meta-prompt for your completed work
python -m src.meta_prompt_generator --project-path /path/to/project --stream
# Outputs to console for copy/paste

generate-meta-prompt --context-file tasks/context.md
# Saves to meta-prompt-YYYYMMDD-HHMMSS.md (after pip install)

# 📊 SCOPE CONTROL

# Review specific phase
generate-code-review /path/to/project --scope specific_phase --phase-number 2.0

# Use specific task list (when multiple exist)
generate-code-review /path/to/project --task-list tasks-auth-system.md

# Context generation only (no AI review)
generate-code-review /path/to/project --context-only

# 🤖 MODEL SELECTION

# Use different Gemini model
GEMINI_MODEL=gemini-2.5-pro generate-code-review /path/to/project

# Works without task lists
generate-code-review /path/to/project --default-prompt "Review security and performance"
```

### Task List Discovery

**How the tool finds task lists:**

- **Auto-discovery**: Searches `/tasks/` directory for `tasks-*.md` files
- **Multiple files**: Uses most recently modified task list
- **Specific selection**: Use `--task-list filename.md` to choose exact file  
- **No task lists**: Falls back to intelligent default prompts
- **Logging**: Shows which task list was selected when multiple exist

**Examples:**
```bash
# Multiple task lists in /tasks/:
# - tasks-auth-system.md (modified yesterday)
# - tasks-payment-flow.md (modified today) ← Auto-selected

# Tool output: "Auto-selected most recent: tasks-payment-flow.md"

# Override auto-selection:
uvx task-list-code-review-mcp generate-code-review . --task-list tasks-auth-system.md
```

### MCP Server Integration

#### Cursor Configuration
**Setup** (`.cursorrules` or `.cursor/rules/*.mdc`):
The MCP server automatically discovers and includes Cursor rules in code reviews when `--include-cursor-rules` is used.

**For GitHub PR Review Support**: Add your GitHub token to enable `generate_pr_review` tool.
Create token at: https://github.com/settings/tokens (scopes: `repo` or `public_repo`)

#### Claude Code CLI Integration

**Add this MCP server to Claude Code:**
```bash
# Add the MCP server with environment variables
claude mcp add task-list-reviewer -e GEMINI_API_KEY=your_key_here -e GITHUB_TOKEN=your_github_token_here -- uvx task-list-code-review-mcp

# Verify it's added
claude mcp list

# Optional: Check server details
claude mcp get task-list-reviewer
```

**Server Scope Options:**
- `--scope local` (default): Project-specific server
- `--scope project`: Shared via `.mcp.json` 
- `--scope user`: Available across all projects

**Usage in Claude Code:**
```
Human: Generate a code review for my current project

Claude: I'll analyze your project and generate a comprehensive code review.

[Tool Use: generate_code_review_context]
{
  "project_path": "/Users/myname/projects/my-app"
}

[Tool Result] Generated: code-review-context-full-project-20241201-143052.md
```

**Branch Comparison Review:**
```
Human: Compare my feature branch against main and generate a review

Claude: I'll compare your feature branch changes against the main branch.

[Tool Use: generate_pr_review]
{
  "project_path": "/Users/myname/projects/my-app",
  "compare_branch": "feature/auth-system",
  "target_branch": "main"
}

[Tool Result] 🔍 Analyzed project: my-app
🌿 Branch comparison: feature/auth-system → main
📝 Generated review context: code-review-branch-comparison-20241201-143052.md
```

**GitHub PR Review:**
```
Human: Review this GitHub PR: https://github.com/owner/repo/pull/123

Claude: I'll fetch the PR data and generate a comprehensive review.

[Tool Use: generate_pr_review]
{
  "github_pr_url": "https://github.com/owner/repo/pull/123"
}

[Tool Result] 🔍 Analyzed project: repo
🔗 GitHub PR: owner/repo/pull/123
📝 Generated review context: code-review-github-pr-20241201-143052.md
```

**MCP Server Management:**
```bash
# List all MCP servers
claude mcp list

# Get server details
claude mcp get task-list-reviewer

# Remove server if needed
claude mcp remove task-list-reviewer
```

## 🖥️ CLI Commands Reference

### 📄 CLI Commands Overview

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `uvx task-list-code-review-mcp generate-code-review` | **Primary CLI** - Complete code review workflow (context + AI feedback) | Most common use case |
| `uvx task-list-code-review-mcp generate-code-review --auto-prompt` | **Code review with meta-prompt** - Includes generated meta-prompt in context | For optimized reviews |
| `uvx generate-meta-prompt` | **Meta-prompt only** - Creates optimized review prompts | When you need just the prompt |

**Note**: These commands work via uvx for easy access without installation.


## 🎯 Meta-Prompt Generation CLI

**NEW**: Dedicated CLI tool for generating meta-prompts from completed development work.

### 📋 Available Flags

**Input Sources** (exactly one required):
- `--context-file PATH` - Use existing context file
- `--context-content TEXT` - Direct content string  
- `--project-path PATH` - Generate from project (with optional `--scope`)

**Output Control**:
- `--output-dir DIR` - Save location (default: current directory)
- `--stream` - Output to stdout instead of file

**Customization**:
- `--custom-template TEMPLATE` - Override template (use `{context}` placeholder)
- `--scope SCOPE` - For `--project-path` only: `recent_phase`, `full_project`, `specific_phase`, `specific_task`

### 🚀 Quick Examples

```bash
# From context file → saves to current directory
uvx generate-meta-prompt --context-file tasks/context.md

# From project → stream to stdout
uvx generate-meta-prompt --project-path /path/to/project --stream

# Custom directory + template
uvx generate-meta-prompt --project-path . --output-dir ./prompts --custom-template "Security focus: {context}"

# Specific scope
uvx generate-meta-prompt --project-path . --scope full_project
```

### 📄 Output Modes

**File Mode (Default)**:
- Location: Current directory (or `--output-dir`)
- Format: `meta-prompt-YYYYMMDD-HHMMSS.md`
- Content: Formatted with metadata headers

**Stream Mode (`--stream`)**:
- Output: Raw prompt content to stdout
- Use case: Pipe to tools or copy/paste

### 🔗 Workflow Integration

```bash
# CLI generation → MCP usage
uvx generate-meta-prompt --project-path . --output-dir ./prompts
# Creates: ./prompts/meta-prompt-20241201-143052.md

# Then use in MCP tools:
# [Tool Use: generate_ai_code_review]
# {"context_file_path": "./prompts/meta-prompt-20241201-143052.md"}
```

## 🔧 MCP Tools Quick Reference

**📊 [Complete Workflow Diagrams](./WORKFLOW_DIAGRAMS.md)** - Visual ASCII flow diagrams

### 🎯 `generate_meta_prompt`
**Creates optimized prompts from completed work**

```javascript
await use_mcp_tool({
  server_name: "task-list-code-review-mcp",
  tool_name: "generate_meta_prompt",
  arguments: {
    project_path: "/path/to/project",
    text_output: true  // Returns content directly for AI chaining
  }
});
```

### 📋 `generate_code_review_context`
**Primary context generation tool (with auto meta prompt enabled by default)**

```javascript
await use_mcp_tool({
  server_name: "task-list-code-review-mcp",
  tool_name: "generate_code_review_context",
  arguments: {
    project_path: "/path/to/project",
    scope: "recent_phase",  // or full_project, specific_phase
    auto_meta_prompt: true,  // Default: true - generates project-aware meta prompts
    text_output: true,       // Default: true - returns content for AI chaining
    raw_context_only: false
  }
});
```

### 🤖 `generate_ai_code_review`
**AI-powered feedback with multi-mode support (file/content/project)**

```javascript
// Mode 1: From existing context file
await use_mcp_tool({
  server_name: "task-list-code-review-mcp",
  tool_name: "generate_ai_code_review",
  arguments: {
    context_file_path: "/path/to/context.md",
    custom_prompt: "Focus on security vulnerabilities...",
    text_output: true  // Default: true - returns content for AI chaining
  }
});

// Mode 2: From direct content (AI chaining)
await use_mcp_tool({
  server_name: "task-list-code-review-mcp",
  tool_name: "generate_ai_code_review",
  arguments: {
    context_content: "Context content here...",
    custom_prompt: "Focus on performance...",
    text_output: true
  }
});

// Mode 3: Direct project analysis (one-shot)
await use_mcp_tool({
  server_name: "task-list-code-review-mcp",
  tool_name: "generate_ai_code_review",
  arguments: {
    project_path: "/path/to/project",
    auto_meta_prompt: true,  // Default: true - generates meta prompts
    scope: "recent_phase",   // Scope for project analysis
    text_output: true        // Returns content directly
  }
});
```

### 🌿 Branch Comparison (Deprecated)
**Use GitHub PR integration instead**

Branch comparison functionality has been consolidated into GitHub PR integration. Create a GitHub PR and use `generate_pr_review` for comprehensive analysis.

### 🔗 `generate_pr_review`
**GitHub PR analysis (requires `GITHUB_TOKEN`)**

```javascript
await use_mcp_tool({
  server_name: "task-list-code-review-mcp",
  tool_name: "generate_pr_review",
  arguments: {
    github_pr_url: "https://github.com/owner/repo/pull/123",
    project_path: "/absolute/path/to/project"  // Optional
  }
});
```

**Example output:**
```
🔍 Analyzed project: my-app
🔗 GitHub PR: owner/repo/pull/123
📝 Generated review context: code-review-github-pr-20241201-143052.md
✅ AI code review completed: code-review-comprehensive-feedback-20241201-143052.md
```

### 📊 Legacy Tools
- **`generate_review_context`** & **`generate_ai_review`** - Backward compatibility aliases

---

## 🚀 MCP Workflow Patterns

### Pattern 1: Enhanced Default Workflow (Recommended)
**Auto meta prompt enabled by default → Intelligent review**

```bash
# Single tool call with auto meta prompt enabled by default
Human: Generate a comprehensive review for my authentication system

[Tool Use: generate_code_review_context]
{
  "project_path": "/Users/dev/auth-service",
  "scope": "recent_phase",
  "auto_meta_prompt": true,  // Default: enabled
  "text_output": true        // Returns content for AI chaining
}
# AI returns: Enhanced context with project-aware meta prompt embedded

# Optional: Follow up with AI review if needed
[Tool Use: generate_ai_code_review]
{
  "context_content": "Enhanced context content...",
  "text_output": true
}
```

### Pattern 2: Traditional Comprehensive Review
**Standard project analysis**

```bash
# Direct context generation + AI review
Human: Generate a comprehensive review of my recent work

[Tool Use: generate_code_review_context]
{
  "project_path": "/Users/dev/my-app",
  "scope": "recent_phase",
  "temperature": 0.3
}

# Specialized workflows:
# - GitHub PR analysis: generate_pr_review
# - GitHub PR review: generate_pr_review  
# - Context-only generation: raw_context_only: true
```

---

## 🛠 Advanced Configuration

### Environment Variables Reference

| Variable | Required | Default | Description | Example |
|----------|----------|---------|-------------|---------|
| `GEMINI_API_KEY` | **Yes** | None | Google Gemini API key | `export GEMINI_API_KEY=your_key` |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | Model selection | `gemini-2.5-pro`, `gemini-2.5-flash` |
| `GEMINI_TEMPERATURE` | No | `0.5` | AI creativity (0.0-2.0) | `0.3` for focused, `0.7` for creative |
| `GITHUB_TOKEN` | No | None | GitHub API access for PR reviews | `ghp_...` (repo scope) |
| `MAX_FILE_SIZE_MB` | No | `10` | File size limit for analysis | `20` |
| `DISABLE_THINKING` | No | `false` | Disable thinking mode | `true`/`false` |
| `DISABLE_GROUNDING` | No | `false` | Disable web grounding | `true`/`false` |

**Quick Setup:**
```bash
# Essential
export GEMINI_API_KEY=your_key_here

# Optional model selection  
export GEMINI_MODEL=gemini-2.5-pro

# For GitHub PR reviews
export GITHUB_TOKEN=your_github_token
```

### 📋 Configuration File Integration

**The tool can automatically discover and include project configuration files in code reviews.**

#### 🔧 CLAUDE.md Files (Default: **ENABLED**)
- **Project-level**: `/project/CLAUDE.md` - Project-specific guidelines
- **User-level**: `~/.claude/CLAUDE.md` - Personal coding preferences  
- **Enterprise-level**: System-wide policies (platform-specific)
- **With imports**: Supports `@path/to/file.md` import syntax

#### ⚙️ Cursor Rules (Default: **DISABLED**)
- **Legacy format**: `.cursorrules` - Simple text rules
- **Modern format**: `.cursor/rules/*.mdc` - Rich metadata with frontmatter
- **Monorepo support**: Recursive discovery in nested directories

#### 🎛️ Control Flags

```bash
# Default behavior (CLAUDE.md enabled, Cursor rules disabled)
uvx task-list-code-review-mcp generate-code-review /path/to/project

# Disable CLAUDE.md inclusion
uvx task-list-code-review-mcp generate-code-review /path/to/project --no-claude-memory

# Enable Cursor rules inclusion  
uvx task-list-code-review-mcp generate-code-review /path/to/project --include-cursor-rules

# Enable both configuration types
uvx task-list-code-review-mcp generate-code-review /path/to/project --include-cursor-rules

# Disable all configurations
uvx task-list-code-review-mcp generate-code-review /path/to/project --no-claude-memory
```

#### 🎯 Smart Features
- **Deduplication**: Handles `.gitignore` cases (tracked vs untracked files)
- **Hierarchy**: Project configs override user configs override enterprise
- **Caching**: File modification time tracking for performance
- **Error handling**: Graceful degradation when files are malformed/missing

### Security Best Practices

**Environment Setup:**
```bash
# Copy the example file and fill in your values
cp .env.example .env

# Secure .env file permissions
chmod 600 .env

# Never commit .env files to version control (already in .gitignore)
```

**API Key Protection:**
- Get your Gemini API key at: https://ai.google.dev/gemini-api/docs/api-key
- Create GitHub token at: https://github.com/settings/tokens (scopes: `repo` or `public_repo`)
- Use separate API keys for development and production
- Regularly rotate your API keys for security

### Model Configuration

**Auto-Detection**: The tool automatically detects and displays model capabilities:
- **Thinking Mode**: Deep reasoning (gemini-2.5 models)
- **Web Grounding**: Real-time information lookup (gemini-2.0+)
- **URL Context**: Enhanced web understanding (supported models)

**Simple Usage:**
```bash
# Use friendly aliases instead of preview model names
GEMINI_MODEL=gemini-2.5-pro uvx task-list-code-review-mcp /project
GEMINI_MODEL=gemini-2.5-flash uvx task-list-code-review-mcp /project
```

**Configuration File**: `src/model_config.json` manages aliases and capabilities. Updates automatically when Google releases new models.

## 📋 Enhanced Review Context Formats

### GitHub PR Context

When using `generate_pr_review`, the generated context includes:

**Enhanced Metadata Sections:**
- **GitHub PR Metadata**: Repository, PR number, title, author, SHA hashes, timestamps
- **PR Description**: First 200 characters of the PR description
- **File Change Statistics**: Detailed breakdown of additions, modifications, deletions
- **Specialized Instructions**: PR-specific review guidance focusing on quality and security

**Filename Format:** `code-review-context-github-pr-YYYYMMDD-HHMMSS.md`

### Task-Based Context (Traditional)

Standard task list reviews include:
- **Phase/Task Metadata**: Current phase, completed subtasks, next steps
- **Working Directory Changes**: Git status and modified files
- **PRD Context**: Project requirements and scope information

**Filename Formats:**
- `code-review-context-recent-phase-YYYYMMDD-HHMMSS.md`
- `code-review-context-full-project-YYYYMMDD-HHMMSS.md`
- `code-review-context-phase-X-Y-YYYYMMDD-HHMMSS.md`

## 🔄 Workflow Integration for AI Agents

### Smart Completion Detection

The tool automatically detects project completion status:

**Project Complete Workflow:**
```
Human: "Generate a code review for my completed project"
AI Agent: I'll analyze your project and generate a comprehensive review.
Tool detects: All phases (1.0-7.0) complete → Full project review
Output: code-review-context-full-project-{timestamp}.md
```

**Mid-Development Workflow:**
```
Human: "I just finished Phase 2.0, can you review what I've done?"
AI Agent: I'll review your recent work using the MCP server.
Tool detects: Phases in progress → Recent completed phase
Output: code-review-context-recent-phase-{timestamp}.md
```

### Compatible Format Specifications

**PRDs (Optional)**: Based on [create-prd.mdc](https://github.com/snarktank/ai-dev-tasks/blob/main/create-prd.mdc)
- File naming: `prd-[feature-name].md` in `/tasks/` directory
- Structured markdown with Goals, User Stories, Functional Requirements
- **Not required**: Tool works without PRD files

**Task Lists**: Based on [generate-tasks.mdc](https://github.com/snarktank/ai-dev-tasks/blob/main/generate-tasks.mdc)
- File naming: `tasks-[feature-name].md` in `/tasks/` directory
- Hierarchical phases (1.0, 2.0) with sub-tasks (1.1, 1.2)
- Checkbox progress tracking (`- [ ]` / `- [x]`)
- **Flexible**: Multiple task lists supported, auto-discovery available

## 🆘 Troubleshooting

> **🔑 Quick Fixes**: Missing API key? → https://ai.google.dev/gemini-api/docs/api-key | Old version? → `uv cache clean`

### 🚨 Common Issues

**⚠️ "MCP server started" instead of CLI output**
```bash
# Problem: Used server command instead of CLI
python -m src.server  # ❌ Starts MCP server

# Solution: Use CLI command
python -m src.generate_code_review_context /path/to/project  # ✅ Runs CLI
```

**⚠️ "uvx giving old version errors"**
```bash
# Problem: Cached old version
uvx task-list-code-review-mcp  # May use cached v0.2.0

# Solutions:
uv cache clean  # Clear cache, then retry
# OR use development mode:
python -m src.generate_code_review_context /path/to/project
```

**⚠️ "TypeError: unexpected keyword argument 'log_level'"**
```bash
# Problem: Old cached package version
# Solution: Clear cache and reinstall
uv cache clean
uvx --force task-list-code-review-mcp /path/to/project
```

**⚠️ "Module not found" errors**
```bash
# Problem: Missing dependencies in development
# Solution: Install package in development mode
pip install -e .
# OR use uvx for isolated environment
uvx task-list-code-review-mcp /path/to/project
```

### 🔑 Quick Solutions

**Missing API key?** Get one at: https://ai.google.dev/gemini-api/docs/api-key  
**Error messages?** The tool provides specific solutions for each issue  
**Still stuck?** Use development commands: `python -m src.generate_code_review_context`  
**Diagnostic help?** Run: `python scripts/check-cli.py` (shows available commands)  
**MCP testing?** Check the [MCP Inspector Guide](./MCP_INSPECTOR_GUIDE.md)

## 📋 What This Tool Generates

- **Phase Progress Summary** - Completed phases and sub-tasks
- **PRD Context** - Original requirements (auto-summarized with Gemini)
- **Git Changes** - Detailed diff of all modified/added/deleted files
- **File Tree** - ASCII project structure representation
- **File Content** - Full content of changed files for review
- **AI Code Review** - Comprehensive feedback using Gemini 2.5
- **Structured Output** - Professional markdown ready for human review

## 📦 Development

### 🚀 Quick Setup

```bash
# Clone and install in development mode
git clone <repository-url>
cd task-list-code-review-mcp
pip install -e .

# 🎯 Test CLI commands (recommended)
python -m src.generate_code_review_context . --scope full_project
python -m src.meta_prompt_generator --project-path .

# 🧹 Or use Makefile
make test
```

### 🔧 Development Commands

```bash
# Direct module execution (always works)
python -m src.generate_code_review_context . --scope full_project
python -m src.meta_prompt_generator --project-path .

# Run tests and diagnostics
pytest
python scripts/check-cli.py  # CLI diagnostic tool
make test-cli  # Test CLI functionality
```

## 📄 Project Structure

- `src/generate_code_review_context.py` - Core context generation
- `src/meta_prompt_generator.py` - **NEW**: Meta-prompt generation CLI and MCP tool
- `src/server.py` - MCP server wrapper
- `src/model_config.json` - Model configuration and aliases
- `tests/` - Comprehensive test suite including TDD for auto-prompt features
- `pyproject.toml` - Project configuration and entry points