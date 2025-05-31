"""
GitHub Pull Request Integration Module

Provides functionality for parsing GitHub PR URLs, fetching PR data via API,
and retrieving file changes for code review.
"""

import os
import subprocess
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse
import requests


def parse_github_pr_url(url: str) -> Dict[str, Any]:
    """
    Parse GitHub PR URL and extract owner, repo, and PR number.

    Args:
        url: GitHub PR URL (e.g., 'https://github.com/owner/repo/pull/123')

    Returns:
        Dictionary containing parsed URL components

    Raises:
        ValueError: If URL format is invalid or not a GitHub PR URL
    """
    if not url or url.strip() == "":
        raise ValueError("URL cannot be empty")

    try:
        parsed = urlparse(url)

        # Check if it's a GitHub-like domain
        if not (parsed.hostname and ("github" in parsed.hostname)):
            raise ValueError("Invalid GitHub PR URL: Must be a GitHub domain")

        # Parse path components
        path_parts = [part for part in parsed.path.split("/") if part]

        # Expected format: /owner/repo/pull/number
        if len(path_parts) < 4:
            raise ValueError("Invalid GitHub PR URL: Missing path components")

        if path_parts[2] != "pull":
            raise ValueError(
                "Invalid GitHub PR URL: Must be a pull request URL (not issue or other)"
            )

        owner = path_parts[0]
        repo = path_parts[1]

        # Parse PR number
        try:
            pr_number = int(path_parts[3])
        except ValueError:
            raise ValueError("Invalid GitHub PR URL: PR number must be numeric")

        # Construct base URL for API calls
        base_url = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            base_url += f":{parsed.port}"

        return {
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "base_url": base_url,
        }

    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"Invalid GitHub PR URL: {e}")


def get_github_token() -> Optional[str]:
    """
    Get GitHub authentication token from various sources.

    Returns:
        GitHub token if found, None otherwise
    """
    # Strategy 1: Environment variables
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_API_TOKEN")
    if token:
        return token.strip()

    # Strategy 2: Git config
    try:
        result = subprocess.run(
            ["git", "config", "--global", "github.token"],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return None


def validate_github_token(token: str, base_url: str = "https://api.github.com") -> bool:
    """
    Validate GitHub authentication token.

    Args:
        token: GitHub token to validate
        base_url: Base URL for GitHub API (default: public GitHub)

    Returns:
        True if token is valid, False otherwise
    """
    try:
        # Use /user endpoint to validate token
        api_url = (
            f"{base_url}/user" if "api." in base_url else f"{base_url}/api/v3/user"
        )

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        response = requests.get(api_url, headers=headers, timeout=10)
        return response.status_code == 200

    except Exception:
        return False


def fetch_pr_data(
    owner: str,
    repo: str,
    pr_number: int,
    token: Optional[str] = None,
    base_url: str = "https://api.github.com",
) -> Dict[str, Any]:
    """
    Fetch PR metadata from GitHub API.

    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number
        token: GitHub authentication token (optional for public repos, required for private repos)
        base_url: Base URL for GitHub API

    Returns:
        Dictionary containing PR metadata

    Raises:
        ValueError: If API request fails or PR not found
    """
    try:
        # Construct API URL
        if "api." in base_url:
            api_url = f"{base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        else:
            api_url = f"{base_url}/api/v3/repos/{owner}/{repo}/pulls/{pr_number}"

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "task-list-code-review-mcp",
        }

        response = requests.get(api_url, headers=headers, timeout=30)

        # Handle different error cases
        if response.status_code == 404:
            raise ValueError(f"PR not found: {owner}/{repo}/pull/{pr_number}")
        elif response.status_code == 403:
            if response.headers.get("X-RateLimit-Remaining") == "0":
                raise ValueError(
                    "Rate limit exceeded. Please wait before making more requests."
                )
            else:
                raise ValueError(
                    "Access forbidden. Check your GitHub token permissions."
                )
        elif response.status_code != 200:
            raise ValueError(
                f"GitHub API error: {response.status_code} - {response.text}"
            )

        data = response.json()

        # Extract and normalize PR data
        return {
            "pr_number": data["number"],
            "title": data["title"],
            "body": data.get("body", ""),
            "state": data["state"],
            "author": data["user"]["login"],
            "source_branch": data["head"]["ref"],
            "target_branch": data["base"]["ref"],
            "source_sha": data["head"]["sha"],
            "target_sha": data["base"]["sha"],
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "url": data["html_url"],
        }

    except requests.Timeout:
        raise ValueError("Network timeout while fetching PR data")
    except requests.ConnectionError:
        raise ValueError("Network connection failed while fetching PR data")
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"Failed to fetch PR data: {e}")


def get_pr_file_changes(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
    base_url: str = "https://api.github.com",
) -> Dict[str, Any]:
    """
    Get file changes for a PR from GitHub API.

    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number
        token: GitHub authentication token
        base_url: Base URL for GitHub API

    Returns:
        Dictionary containing file changes and statistics

    Raises:
        ValueError: If API request fails
    """
    try:
        # Construct API URL for PR files
        if "api." in base_url:
            api_url = f"{base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        else:
            api_url = f"{base_url}/api/v3/repos/{owner}/{repo}/pulls/{pr_number}/files"

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "task-list-code-review-mcp",
        }

        response = requests.get(api_url, headers=headers, timeout=30)

        if response.status_code != 200:
            raise ValueError(
                f"Failed to fetch PR file changes: {response.status_code} - {response.text}"
            )

        files_data = response.json()

        # Process file changes
        changed_files: List[Dict[str, Any]] = []
        files_added = 0
        files_modified = 0
        files_deleted = 0
        total_additions = 0
        total_deletions = 0

        for file_data in files_data:
            status = file_data["status"]

            # Map GitHub status to our expected format
            if status == "added":
                files_added += 1
            elif status == "modified":
                files_modified += 1
            elif status == "removed":
                files_deleted += 1

            # Handle patch data - pass through what GitHub API provides
            patch = file_data.get("patch")
            if patch is None:
                # Only replace None patches for binary files, not deleted files
                # Real GitHub API provides patch data for deleted files
                patch = "[Binary file]"

            total_additions += file_data.get("additions", 0)
            total_deletions += file_data.get("deletions", 0)

            changed_files.append(
                {
                    "path": file_data["filename"],
                    "status": status,
                    "additions": file_data.get("additions", 0),
                    "deletions": file_data.get("deletions", 0),
                    "changes": file_data.get("changes", 0),
                    "patch": patch,
                }
            )

        return {
            "changed_files": changed_files,
            "summary": {
                "files_changed": len(changed_files),
                "files_added": files_added,
                "files_modified": files_modified,
                "files_deleted": files_deleted,
                "total_additions": total_additions,
                "total_deletions": total_deletions,
            },
        }

    except requests.Timeout:
        raise ValueError("Network timeout while fetching PR file changes")
    except requests.ConnectionError:
        raise ValueError("Network connection failed while fetching PR file changes")
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"Failed to fetch PR file changes: {e}")


def get_complete_pr_analysis(
    pr_url: str, token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Complete analysis workflow for a GitHub PR.

    Args:
        pr_url: GitHub PR URL
        token: GitHub authentication token (auto-detected if None)

    Returns:
        Dictionary containing complete PR analysis

    Raises:
        ValueError: If URL is invalid, token is missing, or API requests fail
    """
    # Parse PR URL
    parsed = parse_github_pr_url(pr_url)

    # Get authentication token
    if token is None:
        token = get_github_token()
        if token is None:
            raise ValueError(
                "GitHub token required. Set GITHUB_TOKEN environment variable."
            )

    # Determine API base URL
    api_base_url = "https://api.github.com"
    if parsed["base_url"] != "https://github.com":
        # GitHub Enterprise
        api_base_url = f"{parsed['base_url']}/api/v3"

    # Validate token
    if not validate_github_token(token, api_base_url):
        raise ValueError("Invalid GitHub token or insufficient permissions")

    # Fetch PR data and file changes
    pr_data = fetch_pr_data(
        parsed["owner"], parsed["repo"], parsed["pr_number"], token, api_base_url
    )

    file_changes = get_pr_file_changes(
        parsed["owner"], parsed["repo"], parsed["pr_number"], token, api_base_url
    )

    # Combine results
    return {
        "pr_url": pr_url,
        "repository": f"{parsed['owner']}/{parsed['repo']}",
        "pr_data": pr_data,
        "file_changes": file_changes,
        "analysis_metadata": {
            "total_files": len(file_changes["changed_files"]),
            "summary": file_changes["summary"],
        },
    }
