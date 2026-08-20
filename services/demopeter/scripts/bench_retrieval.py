#!/usr/bin/env python3
"""
szpeter2026 — RAG 检索质量评估脚本
======================================

评估向量检索的真实质量，而非仅验证链路连通性。

功能:
  1. 合成标注数据集 — 生成含已知 ground-truth 的测试文档
  2. 多指标评测 — MRR / NDCG@K / Recall@K / Precision@K
  3. 配置对比 — 不同 chunk_size / overlap 组合横向对比
  4. 结果报告 — 终端彩色输出 + JSON + CSV

用法:
    # 快速评测（默认配置）
    python scripts/bench_retrieval.py

    # 对比多种分块配置
    python scripts/bench_retrieval.py --compare

    # 使用外部标注数据集
    python scripts/bench_retrieval.py --dataset ./data/qrels.json

    # 指定 top_k 和输出路径
    python scripts/bench_retrieval.py --top-k 5 --output ./reports/bench.json
"""

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from statistics import mean, stdev
from typing import Any

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import config
from src.vector_store import VectorStore
from src.doc_processor import DocumentProcessor
from src.db_manager import DBManager


# ============================================================
# 数据结构
# ============================================================

@dataclass
class QueryLabel:
    """单条查询的标注信息"""
    query: str
    relevant_doc_titles: list[str]   # 应该被检索到的文档标题列表
    difficulty: str = "medium"       # easy / medium / hard


@dataclass
class HitResult:
    """单次检索命中的结果"""
    rank: int
    doc_id: str
    content: str = ""
    similarity: float = 0.0


@dataclass
class QueryResult:
    """单条查询的完整结果"""
    query: str
    hits: list[HitResult] = field(default_factory=list)
    relevant_titles: list[str] = field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def hit_doc_ids(self) -> list[str]:
        return [h.doc_id for h in self.hits]


@dataclass
class MetricsReport:
    """单次评测的指标汇总"""
    mrr: float = 0.0
    ndcg_at_k: dict[int, float] = field(default_factory=dict)
    recall_at_k: dict[int, float] = field(default_factory=dict)
    precision_at_k: dict[int, float] = field(default_factory=dict)
    avg_latency_ms: float = 0.0
    total_queries: int = 0
    detail: list[dict] = field(default_factory=list)


@dataclass
class ConfigVariant:
    """分块配置变体"""
    label: str
    chunk_size: int
    chunk_overlap: int


@dataclass
class ComparisonReport:
    """多配置对比结果"""
    variants: list[ConfigVariant] = field(default_factory=list)
    results: dict[str, MetricsReport] = field(default_factory=dict)
    best_mrr: str = ""
    best_recall_5: str = ""


# ============================================================
# 合成数据集生成器
# ============================================================

SYNTHETIC_DOCS: list[dict[str, Any]] = [
    {
        "title": "向量数据库原理",
        "content": """# 向量数据库原理

## 什么是向量数据库
向量数据库是一种专门用于存储和检索高维向量的数据库系统。
它将文本、图像等非结构化数据通过 Embedding 模型转换为高维向量，
然后通过向量相似度计算实现语义检索。

## 核心概念
### 向量嵌入 (Embedding)
Embedding 是将文本映射到高维空间中的向量表示。
例如，句子 "我爱编程" 可能被映射为一个 384 维的浮点数数组。
语义相近的文本在向量空间中距离更近。

### 余弦相似度
余弦相似度是衡量两个向量方向相似程度的指标，取值范围 [-1, 1]。
两个完全相同方向的向量，余弦相似度为 1。
对于文本向量，通常只取正值，范围在 [0, 1] 之间。

余弦相似度公式：
cos(θ) = (A · B) / (||A|| × ||B||)

### 近似最近邻搜索 (ANN)
当向量数量达到百万级别时，精确的最近邻搜索（遍历所有向量）不可行。
ANN 算法如 HNSW、IVF 通过牺牲少量精度换取巨大速度提升。

## 常见向量数据库
- **Chroma**: 轻量级，适合中小规模项目和快速原型
- **Pinecone**: 托管服务，零运维
- **Weaviate**: 开源，支持混合搜索
- **Milvus**: 高性能，适合大规模生产环境
- **Qdrant**: Rust 编写，性能优秀
""",
    },
    {
        "title": "RAG系统架构设计",
        "content": """# RAG 系统架构设计

## RAG 概述
RAG (Retrieval-Augmented Generation) 是一种结合检索和生成的 AI 架构。
它先从一个知识库中检索相关文档片段，然后将这些片段作为上下文注入 LLM，
从而产生更准确、更可信的回答。

## RAG 的核心组件
1. **文档处理器**: 导入、解析、清洗文档
2. **分块器 (Chunker)**: 将文档切分为适当大小的片段
3. **Embedding 模型**: 将文本片段转换为向量
4. **向量数据库**: 存储和检索向量
5. **检索器 (Retriever)**: 根据查询检索最相关的片段
6. **生成器 (Generator)**: 基于检索到的上下文生成回答

## RAG 的优势
- 减少幻觉：LLM 基于真实文档回答
- 知识更新：无需重新训练模型，只需更新知识库
- 可追溯：每个回答都可以追溯到来源文档
- 领域适配：可以注入特定领域的知识

## 常见 RAG 模式
### Naive RAG
简单的"检索→拼接→生成"流程，适用于原型验证。

### Advanced RAG
引入查询重写、重排序、混合检索等优化手段。

### Agentic RAG
将 RAG 作为工具嵌入 AI Agent，支持多步推理和工具调用。
""",
    },
    {
        "title": "Python数据分析入门",
        "content": """# Python 数据分析入门

## NumPy 基础
NumPy 是 Python 科学计算的基础库，提供了多维数组对象和丰富的数学函数。

```python
import numpy as np
arr = np.array([1, 2, 3, 4, 5])
print(arr.mean())  # 3.0
```

## Pandas 数据处理
Pandas 提供了 DataFrame 和 Series 两种核心数据结构。

```python
import pandas as pd
df = pd.read_csv('data.csv')
print(df.describe())
```

### 数据清洗
- 处理缺失值: `df.dropna()` 或 `df.fillna(0)`
- 去重: `df.drop_duplicates()`
- 类型转换: `df.astype()`

## 数据可视化
Matplotlib 和 Seaborn 是 Python 最常用的可视化库。

```python
import matplotlib.pyplot as plt
import seaborn as sns
sns.heatmap(df.corr())
plt.show()
```

## 统计分析
- 描述性统计: mean, median, std, quantile
- 相关性分析: Pearson, Spearman
- 假设检验: t-test, chi-square
""",
    },
    {
        "title": "深度学习优化器比较",
        "content": """# 深度学习优化器比较

## SGD (随机梯度下降)
最基本的优化算法。每次使用一个或一小批样本计算梯度并更新参数。

优点：简单、可解释
缺点：收敛慢、容易陷入局部最优

## Adam
结合了 Momentum 和 RMSProp 的优点，是目前最流行的优化器。

Adam 的更新公式涉及一阶矩估计 (m) 和二阶矩估计 (v)：
- m_t = β₁ * m_{t-1} + (1-β₁) * g_t
- v_t = β₂ * v_{t-1} + (1-β₂) * g_t²

默认超参数: lr=0.001, β₁=0.9, β₂=0.999, ε=1e-8

## AdamW
Adam 的改进版本，将权重衰减与自适应学习率解耦。
在 Transformer 训练中表现优于 Adam。

## 其他优化器
- **RMSProp**: 自适应学习率，适合非平稳目标
- **Adagrad**: 适合稀疏特征
- **LAMB**: 大 batch 训练优化器

## 选择建议
- NLP/Transformer: AdamW
- CNN 图像分类: SGD + Momentum 或 Adam
- GAN: Adam
- 强化学习: RMSProp
""",
    },
    {
        "title": "Docker容器化部署指南",
        "content": """# Docker 容器化部署指南

## Docker 基础概念
Docker 是一个开源的应用容器引擎，让开发者可以打包应用及其依赖
到一个可移植的容器中。

### 镜像 (Image)
镜像是一个只读模板，包含运行应用所需的一切。

### 容器 (Container)
容器是镜像的运行实例，可以启动、停止、删除。

### Dockerfile
Dockerfile 是构建镜像的脚本：

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

## Docker Compose
用于定义和运行多容器应用：

```yaml
version: '3.8'
services:
  web:
    build: .
    ports:
      - "5220:5220"
    volumes:
      - ./db:/app/db
  chroma:
    image: chromadb/chroma
    ports:
      - "8001:8000"
```

## 数据持久化
- **Volumes**: Docker 管理的持久化存储
- **Bind Mounts**: 挂载宿主机目录
- **tmpfs**: 临时文件系统，存储在内存中

## 最佳实践
1. 使用多阶段构建减小镜像体积
2. 不要以 root 用户运行容器
3. 一个容器一个职责
4. 使用 .dockerignore 排除不需要的文件
""",
    },
]


def build_synthetic_labels() -> list[QueryLabel]:
    """基于合成文档构建标注查询对

    标注策略：每条查询对应 1-2 个准确知道答案在哪的文档。
    """
    return [
        # === 向量数据库主题 ===
        QueryLabel(
            query="余弦相似度是如何计算的",
            relevant_doc_titles=["向量数据库原理"],
            difficulty="easy",
        ),
        QueryLabel(
            query="Chroma 和 Milvus 有什么区别",
            relevant_doc_titles=["向量数据库原理"],
            difficulty="medium",
        ),
        QueryLabel(
            query="什么是 ANN 近似搜索",
            relevant_doc_titles=["向量数据库原理"],
            difficulty="medium",
        ),

        # === RAG 主题 ===
        QueryLabel(
            query="RAG 系统由哪些核心组件组成",
            relevant_doc_titles=["RAG系统架构设计"],
            difficulty="easy",
        ),
        QueryLabel(
            query="Agentic RAG 和 Naive RAG 有什么不同",
            relevant_doc_titles=["RAG系统架构设计"],
            difficulty="medium",
        ),
        QueryLabel(
            query="如何减少 LLM 的幻觉问题",
            relevant_doc_titles=["RAG系统架构设计"],
            difficulty="medium",
        ),

        # === Python 数据分析主题 ===
        QueryLabel(
            query="Pandas 怎么处理缺失值",
            relevant_doc_titles=["Python数据分析入门"],
            difficulty="easy",
        ),
        QueryLabel(
            query="如何用 Python 做数据可视化",
            relevant_doc_titles=["Python数据分析入门"],
            difficulty="medium",
        ),

        # === 深度学习主题 ===
        QueryLabel(
            query="Adam 优化器的默认超参数是什么",
            relevant_doc_titles=["深度学习优化器比较"],
            difficulty="easy",
        ),
        QueryLabel(
            query="Adam 和 AdamW 有什么区别",
            relevant_doc_titles=["深度学习优化器比较"],
            difficulty="medium",
        ),
        QueryLabel(
            query="Transformer 训练推荐用什么优化器",
            relevant_doc_titles=["深度学习优化器比较"],
            difficulty="medium",
        ),

        # === Docker 主题 ===
        QueryLabel(
            query="Docker 镜像和容器有什么区别",
            relevant_doc_titles=["Docker容器化部署指南"],
            difficulty="easy",
        ),
        QueryLabel(
            query="Docker Compose 怎么配置多容器应用",
            relevant_doc_titles=["Docker容器化部署指南"],
            difficulty="medium",
        ),
        QueryLabel(
            query="Docker 数据持久化有哪几种方式",
            relevant_doc_titles=["Docker容器化部署指南"],
            difficulty="easy",
        ),

        # === 跨主题（hard） ===
        QueryLabel(
            query="向量数据库在 RAG 系统中扮演什么角色",
            relevant_doc_titles=["向量数据库原理", "RAG系统架构设计"],
            difficulty="hard",
        ),
        QueryLabel(
            query="如何用 Docker 部署一个基于 Chroma 的 RAG 应用",
            relevant_doc_titles=["Docker容器化部署指南", "向量数据库原理", "RAG系统架构设计"],
            difficulty="hard",
        ),
    ]


# ============================================================
# 评测指标计算
# ============================================================

def compute_dcg(relevances: list[float], k: int | None = None) -> float:
    """计算 DCG (Discounted Cumulative Gain)

    DCG@k = Σ_{i=1}^{k} (2^rel_i - 1) / log2(i + 1)
    """
    if k is not None:
        relevances = relevances[:k]
    if not relevances:
        return 0.0
    dcg = relevances[0]  # rel_1 (no discount for position 1)
    for i in range(1, len(relevances)):
        dcg += relevances[i] / math.log2(i + 2)  # i+2 because 1-indexed
    return dcg


def compute_ndcg(
    hit_doc_ids: list[str],
    relevant_doc_ids: set[str],
    k: int,
) -> float:
    """计算 NDCG@k (Normalized DCG)"""
    # 构建 relevance 列表（binary: 1 if relevant, 0 otherwise）
    relevances = [1.0 if doc_id in relevant_doc_ids else 0.0 for doc_id in hit_doc_ids[:k]]
    dcg = compute_dcg(relevances)

    # Ideal DCG: 所有相关文档排在最前面
    num_relevant = min(len(relevant_doc_ids), k)
    ideal_relevances = [1.0] * num_relevant + [0.0] * (k - num_relevant)
    idcg = compute_dcg(ideal_relevances[:k])

    return dcg / idcg if idcg > 0 else 0.0


def compute_mrr(
    all_results: list[QueryResult],
    title_to_ids: dict[str, set[str]],
) -> float:
    """计算 MRR (Mean Reciprocal Rank)

    MRR = (1/N) * Σ 1/rank_of_first_relevant
    """
    reciprocal_ranks = []
    for result in all_results:
        relevant_ids: set[str] = set()
        for title in result.relevant_titles:
            relevant_ids.update(title_to_ids.get(title, set()))

        first_rank = None
        for hit in result.hits:
            if hit.doc_id in relevant_ids:
                first_rank = hit.rank
                break

        if first_rank is not None:
            reciprocal_ranks.append(1.0 / first_rank)
        else:
            reciprocal_ranks.append(0.0)

    return mean(reciprocal_ranks) if reciprocal_ranks else 0.0


def compute_recall_at_k(
    hit_doc_ids: list[str],
    relevant_doc_ids: set[str],
    k: int,
) -> float:
    """Recall@K = |relevant ∩ top-k| / |relevant|"""
    if not relevant_doc_ids:
        return 0.0
    top_k = set(hit_doc_ids[:k])
    return len(top_k & relevant_doc_ids) / len(relevant_doc_ids)


def compute_precision_at_k(
    hit_doc_ids: list[str],
    relevant_doc_ids: set[str],
    k: int,
) -> float:
    """Precision@K = |relevant ∩ top-k| / k"""
    if k == 0:
        return 0.0
    top_k = set(hit_doc_ids[:k])
    return len(top_k & relevant_doc_ids) / k


# ============================================================
# 评测引擎
# ============================================================

class RetrievalEvaluator:
    """检索质量评测器"""

    def __init__(self, store: VectorStore, title_to_ids: dict[str, set[str]]):
        self.store = store
        self.title_to_ids = title_to_ids

    def evaluate(
        self,
        queries: list[QueryLabel],
        top_k: int = 5,
    ) -> MetricsReport:
        """运行完整评测"""
        results: list[QueryResult] = []
        latencies: list[float] = []

        for ql in queries:
            # 检索
            t0 = time.perf_counter()
            raw_hits = self.store.search(ql.query, top_k=top_k, threshold=0.0)
            latency = (time.perf_counter() - t0) * 1000

            relevant_ids: set[str] = set()
            for title in ql.relevant_doc_titles:
                relevant_ids.update(self.title_to_ids.get(title, set()))

            hits = []
            for rank, h in enumerate(raw_hits, 1):
                hits.append(HitResult(
                    rank=rank,
                    doc_id=h["id"],
                    content=h.get("content", "")[:200],
                    similarity=h.get("similarity", 0.0),
                ))

            results.append(QueryResult(
                query=ql.query,
                hits=hits,
                relevant_titles=ql.relevant_doc_titles,
                latency_ms=latency,
            ))
            latencies.append(latency)

        # 计算指标
        report = MetricsReport(total_queries=len(queries))
        report.mrr = compute_mrr(results, self.title_to_ids)

        ks = [1, 3, 5, 10]
        for k in ks:
            if k > top_k:
                break
            ndcgs = []
            recalls = []
            precisions = []
            for r in results:
                relevant_ids: set[str] = set()
                for title in r.relevant_titles:
                    relevant_ids.update(self.title_to_ids.get(title, set()))
                ndcgs.append(compute_ndcg(r.hit_doc_ids, relevant_ids, k))
                recalls.append(compute_recall_at_k(r.hit_doc_ids, relevant_ids, k))
                precisions.append(compute_precision_at_k(r.hit_doc_ids, relevant_ids, k))

            report.ndcg_at_k[k] = round(mean(ndcgs), 4) if ndcgs else 0.0
            report.recall_at_k[k] = round(mean(recalls), 4) if recalls else 0.0
            report.precision_at_k[k] = round(mean(precisions), 4) if precisions else 0.0

        report.avg_latency_ms = round(mean(latencies), 2) if latencies else 0.0

        # 逐条详情
        for r in results:
            relevant_ids: set[str] = set()
            for title in r.relevant_titles:
                relevant_ids.update(self.title_to_ids.get(title, set()))

            found = sum(1 for h in r.hits if h.doc_id in relevant_ids)
            first_rank = next(
                (h.rank for h in r.hits if h.doc_id in relevant_ids), None
            )
            report.detail.append({
                "query": r.query,
                "expected_titles": r.relevant_titles,
                "found_relevant": found,
                "first_relevant_rank": first_rank,
                "total_hits": len(r.hits),
                "latency_ms": round(r.latency_ms, 2),
                "hits": [
                    {"rank": h.rank, "doc_id": h.doc_id, "similarity": h.similarity}
                    for h in r.hits
                ],
            })

        return report


# ============================================================
# 数据集导入
# ============================================================

def import_synthetic_docs(
    store: VectorStore,
    db: DBManager,
    processor: DocumentProcessor,
    tmp_dir: Path,
) -> tuple[dict[str, set[str]], list[int]]:
    """导入合成测试文档

    返回:
        title_to_ids: {title: {doc_id_chunk_N, ...}}
        doc_ids: [int, ...]  用于后续清理
    """
    title_to_ids: dict[str, set[str]] = defaultdict(set)
    doc_ids: list[int] = []

    for doc_def in SYNTHETIC_DOCS:
        title = doc_def["title"]
        content = doc_def["content"]

        # 写临时文件
        doc_path = tmp_dir / f"{title}.md"
        doc_path.write_text(content, encoding="utf-8")

        # 注册到 SQLite
        doc_id = db.register_document(
            title=title,
            file_path=str(doc_path),
            doc_type="md",
            file_size=doc_path.stat().st_size,
        )
        doc_ids.append(doc_id)

        # 提取文本 + 分块
        _, chunks = processor.process_file(str(doc_path))

        # 保存分块到 SQLite
        db.save_chunks(doc_id, chunks)

        # 写入向量库
        if store.is_available:
            added = store.add_documents(str(doc_id), chunks)
            for i in range(added):
                title_to_ids[title].add(f"{doc_id}_chunk_{i}")

    return dict(title_to_ids), doc_ids


def cleanup_test_data(store: VectorStore, db: DBManager, doc_ids: list[int], tmp_dir: Path):
    """清理测试数据"""
    # 从向量库删除（用数字 doc_id）
    for did in doc_ids:
        try:
            store.delete_document(str(did))
        except Exception:
            pass

    # 从 SQLite 删除
    import sqlite3
    conn = sqlite3.connect(config.METADATA_DB)
    placeholders = ",".join("?" * len(doc_ids))
    conn.execute(f"DELETE FROM chunks WHERE document_id IN ({placeholders})", doc_ids)
    conn.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", doc_ids)
    conn.commit()
    conn.close()

    # 清理临时文件
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass


# ============================================================
# 报告输出
# ============================================================

def print_report(report: MetricsReport, label: str = ""):
    """打印美观的终端报告"""
    name = f" [{label}]" if label else ""
    print(f"\n{'='*60}")
    print(f"  检索质量评测报告{name}")
    print(f"{'='*60}")

    # 汇总指标
    print(f"\n  📊 汇总指标 (共 {report.total_queries} 条查询)")
    print(f"  {'─'*50}")
    print(f"  MRR (Mean Reciprocal Rank):    {report.mrr:.4f}")
    print(f"  平均延迟:                       {report.avg_latency_ms:.2f} ms")

    ks = sorted(report.ndcg_at_k.keys())
    if ks:
        print(f"\n  {'K':<6} {'NDCG':<10} {'Recall':<10} {'Precision':<10}")
        print(f"  {'─'*36}")
        for k in ks:
            ndcg = report.ndcg_at_k.get(k, 0)
            recall = report.recall_at_k.get(k, 0)
            prec = report.precision_at_k.get(k, 0)
            print(f"  @{k:<5} {ndcg:<10.4f} {recall:<10.4f} {prec:<10.4f}")

    # 逐条详情
    print(f"\n  📋 逐条查询详情")
    print(f"  {'─'*50}")
    for i, d in enumerate(report.detail, 1):
        status = "✅" if d["found_relevant"] > 0 else "❌"
        rank_str = f"首位@{d['first_relevant_rank']}" if d["first_relevant_rank"] else "未命中"
        print(f"  {status} Q{i}: {d['query'][:45]}")
        print(f"      期待文档: {d['expected_titles']}")
        print(f"      结果: {d['found_relevant']}/{len(d['expected_titles'])} 命中, {rank_str}")

    # 评分
    print(f"\n  🏆 综合评分")
    print(f"  {'─'*50}")
    score = _calculate_score(report)
    grade = _score_to_grade(score)
    print(f"  总分: {score:.1f}/100  等级: {grade}")


def _calculate_score(report: MetricsReport) -> float:
    """基于关键指标计算综合分数 (0-100)"""
    score = 0.0

    # MRR 权重 40%
    score += min(report.mrr / 0.8, 1.0) * 40

    # NDCG@5 权重 30%
    ndcg5 = report.ndcg_at_k.get(5, 0)
    score += min(ndcg5 / 0.9, 1.0) * 30

    # Recall@5 权重 20%
    recall5 = report.recall_at_k.get(5, 0)
    score += min(recall5 / 0.9, 1.0) * 20

    # 命中率（至少找到1个相关文档的查询比例）权重 10%
    hit_rate = sum(1 for d in report.detail if d["found_relevant"] > 0) / max(report.total_queries, 1)
    score += hit_rate * 10

    return round(score, 1)


def _score_to_grade(score: float) -> str:
    if score >= 85:
        return "A — 检索质量优秀"
    elif score >= 70:
        return "B — 检索质量良好"
    elif score >= 55:
        return "C — 检索质量一般，建议优化"
    elif score >= 40:
        return "D — 检索质量较差，需要调整"
    else:
        return "F — 检索质量很差，请检查配置"


def print_comparison(comp: ComparisonReport):
    """打印多配置对比表格"""
    print(f"\n{'='*60}")
    print(f"  多配置对比报告")
    print(f"{'='*60}")

    print(f"\n  {'配置':<25} {'MRR':<10} {'NDCG@5':<10} {'Recall@5':<10} {'Prec@5':<10} {'延迟':<10}")
    print(f"  {'─'*75}")

    for var in comp.variants:
        r = comp.results.get(var.label)
        if r is None:
            continue
        ndcg5 = r.ndcg_at_k.get(5, 0)
        recall5 = r.recall_at_k.get(5, 0)
        prec5 = r.precision_at_k.get(5, 0)
        marker = ""
        if var.label == comp.best_mrr:
            marker = " ★ MRR"
        elif var.label == comp.best_recall_5:
            marker = " ★ Recall"
        print(f"  {var.label:<25} {r.mrr:<10.4f} {ndcg5:<10.4f} {recall5:<10.4f} {prec5:<10.4f} {r.avg_latency_ms:<7.1f}ms{marker}")

    print(f"\n  🏆 最佳 MRR: {comp.best_mrr}")
    print(f"  🏆 最佳 Recall@5: {comp.best_recall_5}")


# ============================================================
# 主流程
# ============================================================

def run_single_benchmark(
    queries: list[QueryLabel],
    store: VectorStore,
    title_to_ids: dict[str, set[str]],
    top_k: int = 5,
    label: str = "",
) -> MetricsReport:
    """运行单次评测"""
    evaluator = RetrievalEvaluator(store, title_to_ids)
    report = evaluator.evaluate(queries, top_k=top_k)
    print_report(report, label)
    return report


def run_comparison(
    queries: list[QueryLabel],
    top_k: int = 5,
    skip_cleanup: bool = False,
) -> ComparisonReport:
    """对比多种分块配置"""
    variants = [
        ConfigVariant("chunk_500_o50", 500, 50),
        ConfigVariant("chunk_500_o100", 500, 100),
        ConfigVariant("chunk_1000_o200", 1000, 200),   # 默认
        ConfigVariant("chunk_1500_o300", 1500, 300),
        ConfigVariant("chunk_2000_o400", 2000, 400),
    ]

    comp = ComparisonReport(variants=variants)
    best_mrr_score = -1
    best_recall5_score = -1

    for var in variants:
        print(f"\n{'▶'*30} 测试配置: {var.label} {'◀'*30}")

        # 创建独立的 store（不同 collection）避免冲突
        tmp_dir = Path(tempfile.mkdtemp(prefix="bench_"))
        try:
            # 使用自定义 chunk 配置的 processor
            processor = DocumentProcessor()
            processor.chunk_size = var.chunk_size
            processor.chunk_overlap = var.chunk_overlap

            # 独立的 Chroma collection
            collection_name = f"bench_{var.label}"
            store = _create_isolated_store(collection_name)

            if not store.is_available:
                print(f"  ⚠️ 无法创建 {var.label} 的向量库，跳过")
                continue

            db = DBManager()

            # 导入数据
            title_to_ids, doc_ids = import_synthetic_docs(store, db, processor, tmp_dir)

            # 评测
            report = run_single_benchmark(queries, store, title_to_ids, top_k, var.label)
            comp.results[var.label] = report

            if report.mrr > best_mrr_score:
                best_mrr_score = report.mrr
                comp.best_mrr = var.label

            recall5 = report.recall_at_k.get(5, 0)
            if recall5 > best_recall5_score:
                best_recall5_score = recall5
                comp.best_recall_5 = var.label

            # 清理
            if not skip_cleanup:
                cleanup_test_data(store, db, doc_ids, tmp_dir)
                store.delete_collection()

        finally:
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass

    return comp


def _create_isolated_store(collection_name: str) -> VectorStore:
    """创建一个独立的 VectorStore，使用独立的 collection"""
    import chromadb
    from chromadb.utils import embedding_functions

    import os as _os
    _os.makedirs(str(config.DB_DIR / "chroma_data"), exist_ok=True)

    store = VectorStore.__new__(VectorStore)
    store.collection_name = collection_name
    store._mode = "persistent"

    try:
        embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        store._client = chromadb.PersistentClient(
            path=str(config.DB_DIR / "chroma_data")
        )
        store._collection = store._client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
            metadata={"description": f"benchmark: {collection_name}"},
        )
    except Exception as e:
        print(f"  [bench] 创建独立 store 失败: {e}")
        store._client = None
        store._collection = None
        store._mode = "unavailable"

    return store


def main():
    parser = argparse.ArgumentParser(
        description="szpeter2026 — RAG 检索质量评估",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/bench_retrieval.py                    # 快速评测
  python scripts/bench_retrieval.py --compare          # 对比多种分块配置
  python scripts/bench_retrieval.py --output report.json  # 保存报告
        """,
    )
    parser.add_argument("--dataset", type=str, help="外部标注数据集 JSON 路径")
    parser.add_argument("--top-k", type=int, default=5, help="检索 top-k (默认 5)")
    parser.add_argument("--compare", action="store_true", help="对比多种分块配置")
    parser.add_argument("--output", type=str, help="JSON 报告输出路径")
    parser.add_argument("--skip-cleanup", action="store_true", help="保留测试数据")
    args = parser.parse_args()

    print("=" * 60)
    print("  szpeter2026 — RAG 检索质量评估")
    print(f"  Chroma 模式: {config.CHROMA_MODE}")
    print(f"  默认 chunk_size: {config.CHUNK_SIZE}, overlap: {config.CHUNK_OVERLAP}")
    print("=" * 60)

    # 加载查询集
    if args.dataset:
        with open(args.dataset, encoding="utf-8") as f:
            raw = json.load(f)
        queries = [QueryLabel(**q) for q in raw["queries"]]
        print(f"\n  从 {args.dataset} 加载了 {len(queries)} 条标注查询")
    else:
        queries = build_synthetic_labels()
        print(f"\n  使用内置合成数据集: {len(queries)} 条查询, {len(SYNTHETIC_DOCS)} 篇文档")

    if args.compare:
        # === 多配置对比模式 ===
        comp = run_comparison(queries, top_k=args.top_k, skip_cleanup=args.skip_cleanup)
        print_comparison(comp)

        if args.output:
            output = {
                "variants": [asdict(v) for v in comp.variants],
                "results": {k: asdict(v) for k, v in comp.results.items()},
                "best_mrr": comp.best_mrr,
                "best_recall_5": comp.best_recall_5,
            }
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n  📄 报告已保存: {args.output}")

    else:
        # === 单次评测模式 ===
        tmp_dir = Path(tempfile.mkdtemp(prefix="bench_"))
        try:
            store = VectorStore()
            db = DBManager()
            processor = DocumentProcessor()

            if not store.is_available:
                print("\n  ❌ VectorStore 不可用，无法评测")
                return 1

            # 导入数据
            title_to_ids, doc_ids = import_synthetic_docs(store, db, processor, tmp_dir)

            # 评测
            report = run_single_benchmark(queries, store, title_to_ids, args.top_k)

            # 清理
            if not args.skip_cleanup:
                cleanup_test_data(store, db, doc_ids, tmp_dir)

            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(
                    json.dumps(asdict(report), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"\n  📄 报告已保存: {args.output}")

        finally:
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
