"""Local embedding service using sentence-transformers.

Provides a lightweight alternative to remote embedding APIs when no
embedding-capable cloud model is available.  Uses a CPU-friendly
model by default.

====================================================================
基于 sentence-transformers 的本地 Embedding 服务
====================================================================

在无法使用远程 Embedding API 时提供轻量级的本地替代方案。

关键设计：
  1. 延迟加载：模型（约 80MB）在首次调用 embed() 时加载，避免启动时长时间等待。
  2. 内存缓存：加载后缓存在内存中，后续调用复用同一个模型实例。
  3. 默认模型：all-MiniLM-L6-v2（384 维），在 CPU 上快速推理，适合开发环境。
  4. 维度适配：模型输出维度与期望维度不一致时，自动 pad/truncate。

使用方式：
    svc = LocalEmbeddingService()
    vectors = svc.embed(["def foo(): pass", "def bar(): pass"])
    # → list[list[float]]，每个向量的维度 = settings.embedding_dimensions

Python 依赖：
  pip install sentence-transformers
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    import numpy as np


class LocalEmbeddingService:
    """Sentence-transformers based embedding with lazy model loading.

    The model is loaded once and cached in-process.  Memory footprint is
    roughly 100-500 MB depending on the chosen model.

    延迟加载 + 内存缓存的本地向量化服务。

    Usage::

        svc = LocalEmbeddingService()
        vectors = svc.embed(["def foo(): pass", "def bar(): pass"])
        # → list[list[float]] each of length *settings.embedding_dimensions*
    """

    # 默认轻量模型（~80MB，384 维输出），CPU 推理速度快，检索质量可接受。
    # 可选替代："all-MiniLM-L6-v2"（80MB / 384 维）或
    #           "intfloat/multilingual-e5-small"（多语言支持）。
    _DEFAULT_MODEL: str = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str | None = None) -> None:
        """初始化本地 Embedding 服务。

        Args:
            model_name: 可选的 sentence-transformers 模型名。
                        默认使用配置中的 LOCAL_EMBEDDING_MODEL，
                        如果未配置则回退到 _DEFAULT_MODEL。
        """
        self._model_name: str = model_name or settings.local_embedding_model or self._DEFAULT_MODEL
        self._expected_dims: int = settings.embedding_dimensions
        self._model: object | None = None  # 模型实例，延迟加载

    # -- Public API ----------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return normalised embedding vectors for *texts*.

        核心方法：将文本列表向量化，返回归一化的 embedding 向量。

        处理流程：
          1. 检查文本列表是否为空。
          2. 获取模型实例（首次调用触发加载）。
          3. 调用模型 encode()，启用 normalize_embeddings=True（输出已归一化）。
          4. 如果模型输出维度与期望维度不同 → 调用 _resize() 适配。

        Args:
            texts: 待向量化的文本列表。

        Returns:
            归一化后的向量列表（每个向量维度 = settings.embedding_dimensions）。
        """
        if not texts:
            return []
        model = self._get_model()
        # 调用 sentence-transformers 的 encode 方法
        # normalize_embeddings=True → 输出向量已 L2 归一化
        embeddings: np.ndarray = model.encode(  # type: ignore[union-attr]
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        # 模型输出维度可能不等于配置期望的维度 → resize
        if embeddings.shape[1] != self._expected_dims:
            embeddings = self._resize(embeddings, self._expected_dims)
        return [row.tolist() for row in embeddings]

    def embed_query(self, text: str) -> list[float]:
        """便捷方法：将单条查询文本向量化。

        Args:
            text: 查询文本。

        Returns:
            单个 embedding 向量。
        """
        return self.embed([text])[0]

    # -- Internal ------------------------------------------------------------

    def _get_model(self):
        """延迟加载 sentence-transformers 模型实例。

        首次调用时加载模型（耗资源），后续复用缓存。
        """
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            # 加载模型（会自动下载到 ~/.cache/sentence-transformers/）
            self._model = SentenceTransformer(self._model_name)
        return self._model

    @staticmethod
    def _resize(vectors: "np.ndarray", target_dim: int) -> "np.ndarray":
        """Pad with zeros or truncate to *target_dim*.

        适配模型输出维度与期望维度：

          - 输出 < 期望 → 尾部补零。
          - 输出 > 期望 → 截断尾部维度。
          - 输出 == 期望 → 不处理。

        之所以兼容不同维度，是因为不同 sentence-transformers 模型
        的输出维度不同（384 / 768 / 1024 等），而配置中期望的维度
        应与选择的模型匹配。resize 仅在配置不一致时作为容错手段。

        Args:
            vectors:    形状为 (n, current_dim) 的 numpy 数组。
            target_dim: 期望的目标维度。

        Returns:
            形状为 (n, target_dim) 的 numpy 数组。
        """
        import numpy as np

        current_dim = vectors.shape[1]
        if current_dim == target_dim:
            return vectors
        if current_dim < target_dim:
            # 补零：创建全零矩阵 → 将原始向量拷贝到前 current_dim 列
            padded = np.zeros((vectors.shape[0], target_dim), dtype=vectors.dtype)
            padded[:, :current_dim] = vectors
            return padded
        # 截断：只保留前 target_dim 列
        return vectors[:, :target_dim]


# ---------------------------------------------------------------------------
# Module-level factory — used by EmbeddingService to decide whether to
# fall back or use a local model.
# 模块级工厂函数，供 EmbeddingService 判断是否使用本地模型。
# ---------------------------------------------------------------------------

_local_instance: LocalEmbeddingService | None = None


def get_local_embedding_service() -> LocalEmbeddingService | None:
    """Return a cached ``LocalEmbeddingService``, or ``None`` if unavailable.

    返回缓存的 LocalEmbeddingService 单例。

    返回 None 的条件：
      - settings.local_embedding_enabled 为 False（配置禁用）。
      - 导入 sentence_transformers 失败（依赖未安装）。

    Returns:
        LocalEmbeddingService 实例或 None。
    """
    global _local_instance
    if not settings.local_embedding_enabled:
        return None
    if _local_instance is None:
        try:
            _local_instance = LocalEmbeddingService()
        except ImportError:
            # sentence-transformers 未安装
            return None
    return _local_instance
