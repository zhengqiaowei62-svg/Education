"""综合对比实验脚本。

包含5组实验：
1. RAG 分块策略对比
2. 检索模式对比（BM25 vs 语义 vs 混合）
3. 知识图谱对齐 - 相似度阈值对比
4. Hash Embedding vs BGE Embedding 质量对比
5. Map-Reduce 并行加速比
"""
import sys
import os
import time
import math
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.rag_pipeline import (
    chunk_text, _hash_embedding, _cosine, _get_st_model, _encode,
    build_index, retrieve, EMBED_DIM
)
from backend.core.parser import parse
from backend.storage import state
from backend.utils.llm import text_similarity, tokens

# 测试文档路径
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_NEURO = os.path.join(TESTS_DIR, "sample_neuro.md")
SAMPLE_PHYSIO = os.path.join(TESTS_DIR, "sample_physio.md")


# ============================================================
# 实验1：RAG 分块策略对比
# ============================================================
def experiment_chunking():
    """实验1: 不同 chunk_size 和 overlap 参数对检索质量的影响"""
    with open(SAMPLE_NEURO, "r", encoding="utf-8") as f:
        text_neuro = f.read()
    with open(SAMPLE_PHYSIO, "r", encoding="utf-8") as f:
        text_physio = f.read()

    combined_text = text_neuro + "\n" + text_physio

    configs = [
        (400, 60), (600, 100), (800, 150), (1000, 200)
    ]

    results = []
    for size, overlap in configs:
        chunks = chunk_text(combined_text, size=size, overlap=overlap)
        num_chunks = len(chunks)
        avg_len = sum(len(c) for c in chunks) / num_chunks if num_chunks else 0
        total_chunk_chars = sum(len(c) for c in chunks)
        coverage = total_chunk_chars / len(combined_text) if combined_text else 0

        # 计算 chunk 间信息重叠率（相邻 chunk 的共同字符比例）
        overlap_ratios = []
        for i in range(len(chunks) - 1):
            c1 = chunks[i]
            c2 = chunks[i + 1]
            # 计算尾部与头部的重叠
            max_overlap_len = min(len(c1), len(c2), overlap)
            tail = c1[-max_overlap_len:]
            head = c2[:max_overlap_len]
            # 找最长公共子串（简化：直接检查尾部在头部出现的比例）
            common = 0
            for j in range(max_overlap_len, 0, -1):
                if c2.startswith(c1[-j:]):
                    common = j
                    break
            overlap_ratios.append(common / max_overlap_len if max_overlap_len else 0)

        avg_overlap_ratio = sum(overlap_ratios) / len(overlap_ratios) if overlap_ratios else 0

        # 对固定 query 的 Top-5 命中分布（用 hash embedding 模拟）
        query = "静息电位的形成机制"
        q_vec = _hash_embedding(query)
        chunk_scores = []
        for c in chunks:
            c_vec = _hash_embedding(c)
            score = _cosine(q_vec, c_vec)
            chunk_scores.append(score)
        chunk_scores_sorted = sorted(chunk_scores, reverse=True)
        top5_scores = chunk_scores_sorted[:5]

        results.append({
            "chunk_size": size,
            "overlap": overlap,
            "num_chunks": num_chunks,
            "avg_chunk_len": round(avg_len, 1),
            "total_chars": len(combined_text),
            "coverage_ratio": round(coverage, 3),
            "avg_overlap_ratio": round(avg_overlap_ratio, 3),
            "top5_avg_score": round(sum(top5_scores) / len(top5_scores), 4) if top5_scores else 0,
        })

    return results


# ============================================================
# 实验2：检索模式对比（BM25 vs 语义 vs 混合）
# ============================================================
def experiment_retrieval_modes():
    """实验2: 检索模式对比"""
    # 解析样本教材并加载到 state
    with open(SAMPLE_NEURO, "rb") as f:
        data_neuro = f.read()
    tb1 = parse(data_neuro, "md", "neuro.md", "book_exp_neuro")
    state.TEXTBOOKS["book_exp_neuro"] = tb1

    with open(SAMPLE_PHYSIO, "rb") as f:
        data_physio = f.read()
    tb2 = parse(data_physio, "md", "physio.md", "book_exp_physio")
    state.TEXTBOOKS["book_exp_physio"] = tb2

    # 构建索引
    n_books, n_chunks = build_index(["book_exp_neuro", "book_exp_physio"])
    print(f"  [索引构建] 教材: {n_books}, chunks: {n_chunks}")

    # 测试 query
    queries = [
        "什么是静息电位？",
        "突触传递的过程是怎样的？",
        "动作电位的产生机制",
        "神经递质有哪些类型？",
        "细胞膜的通透性",
    ]

    modes = ["term", "semantic", "hybrid"]
    results = []

    for mode in modes:
        mode_scores = []
        mode_times = []
        hit_counts = []
        for q in queries:
            start = time.time()
            hits = retrieve(q, top_k=5, search_mode=mode)
            elapsed = time.time() - start
            scores = [h.get("relevance_score", 0) for h in hits] if hits else []
            mode_scores.append(scores)
            mode_times.append(elapsed)
            hit_counts.append(len(hits))

        avg_time = sum(mode_times) / len(mode_times) * 1000
        avg_top1 = sum(s[0] for s in mode_scores if s) / len(queries)
        avg_top5 = sum(
            sum(s[:5]) / max(len(s[:5]), 1) for s in mode_scores
        ) / len(queries)
        avg_hits = sum(hit_counts) / len(hit_counts)

        results.append({
            "mode": mode,
            "avg_time_ms": round(avg_time, 2),
            "avg_top1_score": round(avg_top1, 4),
            "avg_top5_score": round(avg_top5, 4),
            "avg_hits": round(avg_hits, 1),
        })

    return results


# ============================================================
# 实验3：知识图谱对齐 - 相似度阈值对比
# ============================================================
def experiment_alignment_threshold():
    """实验3: 对齐阈值对比（Jaccard 文本相似度）"""
    # 构造测试数据：(节点A名称, 节点B名称, 真实标签: merge/keep)
    test_pairs = [
        ("静息膜电位", "静息电位", "merge"),
        ("动作电位", "action potential", "merge"),
        ("突触传递", "突触信号传导", "merge"),
        ("抗原", "免疫原", "keep"),
        ("细胞膜", "质膜", "merge"),
        ("钠离子通道", "Na+通道", "merge"),
        ("有丝分裂", "减数分裂", "keep"),
        ("兴奋性突触后电位", "EPSP", "merge"),
        ("细胞凋亡", "程序性死亡", "merge"),
        ("抗体", "免疫球蛋白", "merge"),
        ("白细胞", "红细胞", "keep"),
        ("基因表达", "蛋白质合成", "keep"),
        ("突触前膜", "突触后膜", "keep"),
        ("肌动蛋白", "肌球蛋白", "keep"),
        ("葡萄糖", "糖原", "keep"),
    ]

    thresholds = [0.4, 0.5, 0.55, 0.6, 0.7, 0.8]

    # 计算所有对的相似度
    similarities = []
    for name_a, name_b, label in test_pairs:
        sim = text_similarity(name_a, name_b)
        similarities.append((name_a, name_b, label, sim))

    # 打印相似度详情
    print("\n  [相似度详情]")
    for name_a, name_b, label, sim in similarities:
        print(f"    {name_a} <-> {name_b}: sim={sim:.4f} (label={label})")

    results = []
    for threshold in thresholds:
        tp = fp = fn = tn = 0
        for name_a, name_b, label, sim in similarities:
            predicted = "merge" if sim >= threshold else "keep"
            if label == "merge" and predicted == "merge":
                tp += 1
            elif label == "keep" and predicted == "merge":
                fp += 1
            elif label == "merge" and predicted == "keep":
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        results.append({
            "threshold": threshold,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        })

    return results


# ============================================================
# 实验4：Hash Embedding vs BGE Embedding 质量对比
# ============================================================
def experiment_embedding_quality():
    """实验4: 向量质量对比（区分度测试）"""
    def cosine_sim(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na and nb else 0

    # 测试对：(query, 相关文本, 无关文本)
    test_cases = [
        ("静息电位的定义",
         "静息电位是指细胞在未受刺激时膜内外的电位差，通常为-70mV左右",
         "蛋白质是由氨基酸通过肽键连接而成的大分子化合物"),
        ("突触传递过程",
         "突触传递是指神经冲动通过突触从一个神经元传到另一个神经元的过程",
         "光合作用是绿色植物利用光能将二氧化碳和水合成有机物的过程"),
        ("免疫应答机制",
         "免疫应答是机体免疫系统对抗原刺激产生的一系列免疫学反应",
         "牛顿第二定律表明力等于质量乘以加速度"),
        ("动作电位产生",
         "动作电位是细胞受到阈刺激后膜电位发生的快速极性倒转过程",
         "DNA双螺旋结构由沃森和克里克在1953年提出"),
        ("钠钾泵的功能",
         "钠钾泵以3Na+:2K+比例进行主动转运维持离子浓度梯度",
         "地球绕太阳公转的周期约为365.25天"),
    ]

    # Hash embedding 对比
    hash_results = []
    for query, relevant, irrelevant in test_cases:
        q_vec = _hash_embedding(query)
        r_vec = _hash_embedding(relevant)
        i_vec = _hash_embedding(irrelevant)
        rel_score = cosine_sim(q_vec, r_vec)
        irr_score = cosine_sim(q_vec, i_vec)
        hash_results.append({
            "query": query,
            "relevant_sim": round(rel_score, 4),
            "irrelevant_sim": round(irr_score, 4),
            "discrimination": round(rel_score - irr_score, 4),
        })

    # 尝试 BGE embedding
    bge_results = []
    bge_available = False
    try:
        model = _get_st_model()
        if model:
            bge_available = True
            for query, relevant, irrelevant in test_cases:
                q_vec = _encode([query])
                r_vec = _encode([relevant])
                i_vec = _encode([irrelevant])
                if q_vec is not None and r_vec is not None and i_vec is not None:
                    rel_score = cosine_sim(q_vec[0].tolist(), r_vec[0].tolist())
                    irr_score = cosine_sim(q_vec[0].tolist(), i_vec[0].tolist())
                    bge_results.append({
                        "query": query,
                        "relevant_sim": round(rel_score, 4),
                        "irrelevant_sim": round(irr_score, 4),
                        "discrimination": round(rel_score - irr_score, 4),
                    })
    except Exception as e:
        print(f"  [BGE模型未加载] {e}")

    return {"hash": hash_results, "bge": bge_results, "bge_available": bge_available}


# ============================================================
# 实验5：Map-Reduce 并行加速比
# ============================================================
def experiment_parallelism():
    """实验5: 并行加速比（模拟 LLM 调用延迟）"""
    # 模拟 LLM 调用（不同章节的处理时间不同）
    def simulate_chapter_extraction(chapter_idx):
        # 模拟不同章节处理时间（1.5-2.5秒）
        delay = 1.5 + (chapter_idx % 3) * 0.5
        time.sleep(delay)
        return f"chapter_{chapter_idx}_result"

    num_chapters = 8
    worker_configs = [1, 2, 4, 8]
    results = []

    for workers in worker_configs:
        start = time.time()
        if workers == 1:
            # 串行
            for i in range(num_chapters):
                simulate_chapter_extraction(i)
        else:
            # 并行
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(simulate_chapter_extraction, i)
                           for i in range(num_chapters)]
                for f in as_completed(futures):
                    f.result()
        elapsed = time.time() - start

        results.append({
            "workers": workers,
            "total_time_s": round(elapsed, 2),
            "speedup": 1.0,  # 后续修正
            "num_chapters": num_chapters,
        })

    # 计算加速比
    baseline = results[0]["total_time_s"]
    for r in results:
        r["speedup"] = round(baseline / r["total_time_s"], 2)
        r["efficiency"] = round(r["speedup"] / r["workers"] * 100, 1)

    return results


# ============================================================
# 结果格式化输出
# ============================================================
def print_table(title, headers, rows, col_widths=None):
    """打印格式化表格"""
    if not col_widths:
        col_widths = []
        for i, h in enumerate(headers):
            max_w = len(str(h))
            for row in rows:
                max_w = max(max_w, len(str(row[i])))
            col_widths.append(max_w + 2)

    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

    # header
    header_line = "|".join(str(h).center(col_widths[i]) for i, h in enumerate(headers))
    print(f"| {header_line} |")
    sep_line = "+".join("-" * col_widths[i] for i in range(len(headers)))
    print(f"+-{sep_line}-+")

    # rows
    for row in rows:
        row_line = "|".join(str(row[i]).center(col_widths[i]) for i in range(len(headers)))
        print(f"| {row_line} |")

    print()


def format_experiment1(results):
    """格式化实验1结果"""
    headers = ["chunk_size", "overlap", "num_chunks", "avg_len", "coverage", "overlap_ratio", "top5_score"]
    rows = []
    for r in results:
        rows.append([
            r["chunk_size"], r["overlap"], r["num_chunks"],
            r["avg_chunk_len"], r["coverage_ratio"],
            r["avg_overlap_ratio"], r["top5_avg_score"],
        ])
    print_table("实验1: RAG 分块策略对比", headers, rows)


def format_experiment2(results):
    """格式化实验2结果"""
    headers = ["mode", "avg_time(ms)", "top1_score", "top5_score", "avg_hits"]
    rows = []
    for r in results:
        rows.append([
            r["mode"], r["avg_time_ms"], r["avg_top1_score"],
            r["avg_top5_score"], r["avg_hits"],
        ])
    print_table("实验2: 检索模式对比 (BM25 vs Semantic vs Hybrid)", headers, rows)


def format_experiment3(results):
    """格式化实验3结果"""
    headers = ["threshold", "precision", "recall", "F1", "TP", "FP", "FN", "TN"]
    rows = []
    for r in results:
        rows.append([
            r["threshold"], r["precision"], r["recall"], r["f1"],
            r["tp"], r["fp"], r["fn"], r["tn"],
        ])
    print_table("实验3: 知识图谱对齐阈值对比 (Jaccard相似度)", headers, rows)


def format_experiment4(results):
    """格式化实验4结果"""
    print(f"\n{'='*70}")
    print(f"  实验4: Hash Embedding vs BGE Embedding 质量对比")
    print(f"{'='*70}")

    # Hash embedding
    print("\n  [Hash Embedding 结果]")
    headers = ["query", "相关相似度", "无关相似度", "区分度"]
    rows = []
    for r in results["hash"]:
        rows.append([r["query"], r["relevant_sim"], r["irrelevant_sim"], r["discrimination"]])
    print_table("Hash Embedding", headers, rows)

    avg_disc_hash = sum(r["discrimination"] for r in results["hash"]) / len(results["hash"]) if results["hash"] else 0
    print(f"  Hash Embedding 平均区分度: {avg_disc_hash:.4f}")

    # BGE embedding
    if results["bge"]:
        print("\n  [BGE Embedding 结果]")
        rows = []
        for r in results["bge"]:
            rows.append([r["query"], r["relevant_sim"], r["irrelevant_sim"], r["discrimination"]])
        print_table("BGE Embedding", headers, rows)
        avg_disc_bge = sum(r["discrimination"] for r in results["bge"]) / len(results["bge"])
        print(f"  BGE Embedding 平均区分度: {avg_disc_bge:.4f}")
        print(f"  BGE vs Hash 区分度提升: {(avg_disc_bge - avg_disc_hash) / max(abs(avg_disc_hash), 0.0001) * 100:.1f}%")
    else:
        print("\n  [BGE Embedding] 未加载（sentence-transformers 不可用），仅展示 Hash 结果")


def format_experiment5(results):
    """格式化实验5结果"""
    headers = ["workers", "total_time(s)", "speedup", "efficiency(%)"]
    rows = []
    for r in results:
        rows.append([r["workers"], r["total_time_s"], r["speedup"], r["efficiency"]])
    print_table("实验5: Map-Reduce 并行加速比 (8章节模拟)", headers, rows)


# ============================================================
# 主入口
# ============================================================
def main():
    print("=" * 70)
    print("  教育知识图谱系统 - 综合对比实验")
    print(f"  运行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    all_results = {}

    # --- 实验1 ---
    print("\n>>> 实验1: RAG 分块策略对比...")
    t0 = time.time()
    res1 = experiment_chunking()
    print(f"    完成 ({time.time()-t0:.2f}s)")
    format_experiment1(res1)
    all_results["experiment_1_chunking"] = res1

    # --- 实验2 ---
    print("\n>>> 实验2: 检索模式对比...")
    t0 = time.time()
    res2 = experiment_retrieval_modes()
    print(f"    完成 ({time.time()-t0:.2f}s)")
    format_experiment2(res2)
    all_results["experiment_2_retrieval"] = res2

    # --- 实验3 ---
    print("\n>>> 实验3: 知识图谱对齐阈值对比...")
    t0 = time.time()
    res3 = experiment_alignment_threshold()
    print(f"    完成 ({time.time()-t0:.2f}s)")
    format_experiment3(res3)
    all_results["experiment_3_alignment"] = res3

    # --- 实验4 ---
    print("\n>>> 实验4: Embedding 质量对比...")
    t0 = time.time()
    res4 = experiment_embedding_quality()
    print(f"    完成 ({time.time()-t0:.2f}s)")
    format_experiment4(res4)
    all_results["experiment_4_embedding"] = res4

    # --- 实验5 ---
    print("\n>>> 实验5: 并行加速比...")
    print("    (模拟8章节LLM调用，请等待约16秒...)")
    t0 = time.time()
    res5 = experiment_parallelism()
    print(f"    完成 ({time.time()-t0:.2f}s)")
    format_experiment5(res5)
    all_results["experiment_5_parallelism"] = res5

    # --- 汇总 ---
    print("\n" + "=" * 70)
    print("  实验完成汇总")
    print("=" * 70)
    print(f"  实验1 - 分块策略: {len(res1)} 组配置对比")
    print(f"  实验2 - 检索模式: {len(res2)} 种模式对比")
    print(f"  实验3 - 对齐阈值: {len(res3)} 个阈值对比")
    print(f"  实验4 - Embedding: Hash {'+ BGE' if res4.get('bge') else '(BGE不可用)'}")
    print(f"  实验5 - 并行加速: {len(res5)} 种 worker 配置")
    print("=" * 70)

    # 输出 JSON 数据（便于后续引用）
    print("\n\n--- JSON 数据 ---")
    print(json.dumps(all_results, ensure_ascii=False, indent=2))

    return all_results


if __name__ == "__main__":
    main()
