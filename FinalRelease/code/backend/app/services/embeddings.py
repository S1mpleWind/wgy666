"""Embedding service with remote + local fallback chain.

Priority:
1. Remote embedding API  (if EMBEDDING_API_KEY is configured)
2. Local sentence-transformers model  (if LOCAL_EMBEDDING_ENABLED=true)
3. Hash-based pseudo-vectors  (deterministic, dev-only, no semantics)

====================================================================
多后端 Embedding 服务（带自动降级）
====================================================================

提供文本向量化能力，按优先级依次尝试三种后端：

  优先级 1 —— 远程 Embedding API：
      当配置了 EMBEDDING_API_KEY 时，调用 OpenAI 兼容的远程 API 获取高质量语义向量。
      适合生产环境，需要网络和 API 额度。

  优先级 2 —— 本地 sentence-transformers 模型：
      当远程 API 不可用或未配置时，自动降级为本地 CPU 推理。
      使用轻量模型（默认 all-MiniLM-L6-v2），约 80MB 内存占用，适合离线开发环境。

  优先级 3 —— 基于哈希的伪向量（兜底方案）：
      当以上两种方式均不可用时，使用 BLAKE2b 哈希 + 归一化生成确定性向量。
      **不具备语义相似度能力**，仅用于开发调试，保证系统不因缺少 embedding 而崩溃。

设计思路：
  - EmbeddingService 对调用方屏蔽后端细节，自动选择最优可用后端。
  - _get_local_service() 使用延迟加载单例模式，模型仅在首次使用时加载，减少内存开销。
  - 降级链保证系统在所有环境中均可运行（生产→离线→开发调试）。
"""

from __future__ import annotations

import hashlib
import logging
import math
import re

from openai import OpenAI, OpenAIError

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Multi-backend embedding with automatic fallback.

    统一的 Embedding 接口，内部自动选择可用的最佳后端。
    """

    _last_backend = "not_used"
    _last_error: str | None = None

    def __init__(self, dimensions: int | None = None) -> None:
        # 向量维度数，默认为配置中指定的值
        self.dimensions = dimensions or settings.embedding_dimensions

    # -- Public API ----------------------------------------------------------

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """将文本列表转换为 embedding 向量列表。

        自动降级路径：
          远程 API → 本地模型 → 哈希模拟向量。

        Args:
            texts: 待向量化的文本列表。

        Returns:
            向量列表，每个向量的维度为 ``self.dimensions``。
            空输入返回空列表。
        """
        if not texts:
            return []

        # 1. 远程 API：优先使用，支持 OpenAl 兼容的 embedding 服务
        if settings.embedding_api_key:
            try:
                vectors = self._remote_embeddings(texts)
                type(self)._last_backend = "remote"
                type(self)._last_error = None
                return vectors
            except (OpenAIError, TypeError, ValueError) as exc:
                type(self)._last_error = str(exc)
                logger.warning("Remote embedding failed; trying fallback: %s", exc)

        # 2. 本地 sentence-transformers 模型：离线/降级方案
        local = _get_local_service()
        if local is not None:
            try:
                vectors = local.embed(texts)
                type(self)._last_backend = "local"
                return vectors
            except Exception as exc:
                type(self)._last_error = str(exc)
                logger.warning("Local embedding failed; using hash fallback: %s", exc)

        # 3. Hash fallback (deterministic, no semantics — dev only)
        type(self)._last_backend = "hash_fallback"
        return [self._hash_embedding(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """便捷方法：将单条查询文本向量化。

        Args:
            text: 查询文本。

        Returns:
            单个 embedding 向量。
        """
        return self.embed_texts([text])[0]

    # -- Backends ------------------------------------------------------------

    def _remote_embeddings(self, texts: list[str]) -> list[list[float]]:
        """调用 OpenAI 兼容的远程 Embedding API。

        使用第三方 API 代理或直接调用 OpenAI embedding 端点；
        对 text-embedding-3 系列模型自动指定 dimensions 参数以节省带宽。

        Args:
            texts: 待向量化的文本列表。

        Returns:
            远程 API 返回的向量列表。

        Raises:
            ValueError: 返回向量数量与输入不匹配。
        """
        client = OpenAI(api_key=settings.embedding_api_key, base_url=settings.embedding_api_base_url)
        vectors: list[list[float]] = []
        batch_size = settings.embedding_batch_size
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            kwargs: dict = {"model": settings.embedding_model, "input": batch}
            if "text-embedding-3" in settings.embedding_model:
                kwargs["dimensions"] = self.dimensions
            response = client.embeddings.create(**kwargs)
            vectors.extend(item.embedding for item in response.data)
        if len(vectors) != len(texts):
            raise ValueError("Embedding response size does not match input size.")
        return vectors

    @classmethod
    def backend_status(cls) -> tuple[str, str | None]:
        return cls._last_backend, cls._last_error

    def _hash_embedding(self, text: str) -> list[float]:
        """基于 BLAKE2b 哈希生成伪向量（确定性、无语义）。

        算法原理：
        1. 将文本拆分为 token（英文单词 / 中文字符 / 路径）。
        2. 对每个 token 计算 BLAKE2b 哈希 → 取 4 字节映射到桶索引。
        3. 用哈希的第 5 字节奇偶性决定该桶上的 ±1 符号。
        4. 所有 token 累加后 L2 归一化。

        注意：
          - 该方法**不具备语义相似度能力**，仅保证相同文本产生相同向量。
          - 适合开发环境中兜底使用，不要让下游业务依赖该向量的检索质量。

        Args:
            text: 输入文本。

        Returns:
            归一化后的 embedding 向量。
        """
        vector = [0.0] * self.dimensions
        # 拆分为 token：英文/数字/路径 + 中文字符
        tokens = re.findall(r"[a-zA-Z0-9_./-]+|[一-鿿]", text.lower())
        for token in tokens or [text[:64]]:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            # 用前 4 字节决定桶索引
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            # 用第 5 字节的奇偶性决定符号方向
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        # L2 归一化，处理零向量边界情况
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [round(value / norm, 8) for value in vector]


# ---------------------------------------------------------------------------
# Lazy local embedding singleton
# 延迟加载的本地 Embedding 单例
# ---------------------------------------------------------------------------

_local_service: object | None = None
_local_failed: bool = False  # 标记本地模型是否已尝试加载且失败


def _get_local_service():
    """Return the cached ``LocalEmbeddingService`` singleton, or ``None``.

    使用延迟加载 + 失败缓存策略：
      - 首次调用时尝试导入并实例化 LocalEmbeddingService。
      - 如果导入失败（如缺少 sentence-transformers），记录失败标记，
        后续调用直接返回 None，避免反复尝试导入。
      - 成功后缓存在全局变量中，复用同一个模型实例。

    返回 None 的条件：
      - 配置中未启用本地 embedding。
      - 之前已加载失败（_local_failed = True）。
    """
    global _local_service, _local_failed

    if not settings.local_embedding_enabled:
        return None
    if _local_failed:
        return None
    if _local_service is not None:
        return _local_service

    try:
        from app.services.local_embedding import LocalEmbeddingService

        # 实例化时会加载 sentence-transformers 模型（约 80MB）
        _local_service = LocalEmbeddingService()
    except ImportError:
        # 导入失败（如缺少依赖库），缓存失败状态，后续不再重试
        _local_failed = True
        return None

    return _local_service
