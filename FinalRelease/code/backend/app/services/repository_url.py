"""GitHub repository URL parser.

Supports HTTPS URLs, git@ SSH URLs, and bare ``owner/name`` strings.

====================================================================
GitHub 仓库 URL 解析器
====================================================================

负责从各种格式的 GitHub 仓库标识符中提取 owner 和 name。

支持的输入格式：
  - HTTPS URL:  ``https://github.com/owner/name``
  - SSH URL:    ``git@github.com:owner/name.git``
  - 裸格式:     ``owner/name``（直接使用，不走 URL 解析）

输出：
  - RepositoryRef(owner, name) —— 不可变的 owner/name 数据对象。

使用方式：
    ref = parse_github_repository_url("https://github.com/fastapi/fastapi")
    print(ref.owner)  # "fastapi"
    print(ref.name)   # "fastapi"
"""

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class RepositoryRef:
    """Parsed repository reference with owner and name components.

    不可变（frozen=True）数据类，用于在服务间传递仓库的 owner/name 标识。

    Attributes:
        owner: 仓库所有者（GitHub 用户名或组织名）。
        name:  仓库名称（不含 .git 后缀）。
    """

    owner: str
    name: str


def parse_github_repository_url(value: str) -> RepositoryRef:
    """Parse a GitHub repository URL or identifier into ``RepositoryRef``.

    Accepts:
    - ``https://github.com/owner/name``
    - ``git@github.com:owner/name.git``
    - ``owner/name`` (bare format)

    解析逻辑：
      1. SSH 格式（git@github.com:...） → 去掉前缀和后缀 .git。
      2. 裸格式（owner/name，不含 ://）→ 直接分割。
      3. HTTPS 格式 → urlparse 解析 → 验证域名为 github.com → 提取路径。
      4. 校验：路径至少包含 2 段（owner + name），且两者非空。

    Args:
        value: GitHub 仓库 URL 或裸标识符。

    Returns:
        RepositoryRef(owner, name)。

    Raises:
        ValueError: 不是 GitHub URL 或格式不正确。
    """
    candidate = value.strip()

    # 分支 1: SSH 格式 (git@github.com:owner/repo.git)
    if candidate.startswith("git@github.com:"):
        path = candidate.removeprefix("git@github.com:")

    # 分支 2: 裸标识符格式 (owner/name)，不含 :// 视为裸格式
    elif "://" not in candidate and candidate.count("/") >= 1:
        path = candidate

    # 分支 3: HTTPS URL (https://github.com/owner/repo)
    else:
        parsed = urlparse(candidate)
        # 仅支持 github.com（未来可扩展为其他 Git 托管平台）
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ValueError("Only GitHub repository links are supported.")
        path = parsed.path

    # 提取路径段并过滤空值
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("Expected a GitHub repository URL like https://github.com/owner/repo.")

    owner = parts[0]
    # 去除可能的 .git 后缀
    name = parts[1].removesuffix(".git")

    if not owner or not name:
        raise ValueError("Repository owner and name are required.")
    return RepositoryRef(owner=owner, name=name)
