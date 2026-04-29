#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jiuyi-ime-diction 跨文件全局去重脚本

策略：
  - 以「拼音/字母 + 词」为唯一键，全局只保留词频最高的那一条
  - 词频相同时，按文件优先级顺序保留排名靠前文件的条目
  - 去重后按原来源文件分别写出，文件结构不变

词库格式（Tab 分隔三列）：
  拼音/字母    词    词频

用法：
  python dedup_output.py <output目录>

示例：
  python dedup_output.py ./output
"""

import os
import sys
from collections import defaultdict

# ──────────────────────────────────────────────────────────
# 文件分组及优先级（数字越小优先级越高，词频相同时以此决胜）
# ──────────────────────────────────────────────────────────

CN_FILES_PRIORITY = [
    "cn_base.txt",
    "cn_ext.txt",
    "cn_internet_hot_words.txt",
    "cn_8105.txt",
    "cn_41448.txt",
    "cn_others.txt",
    "cn_thuocl_it.txt",
    "cn_thuocl_place.txt",
    "cn_thuocl_medical.txt",
    "cn_thuocl_animal.txt",
    "cn_thuocl_law.txt",
    "cn_thuocl_history.txt",
    "cn_thuocl_poem.txt",
    "cn_thuocl_food.txt",
    "cn_thuocl_idiom.txt",
    "cn_thuocl_finance.txt",
    "cn_thuocl_car.txt",
    "cn_en.txt",
]

EN_FILES_PRIORITY = [
    "en_base.txt",
    "en.txt",
    "en_ext.txt",
    "en_ext_1.txt",
]


def dedup_files(src_dir: str, dst_dir: str, file_list: list):
    """
    读取 file_list 中所有文件，全局去重后写回 dst_dir。
    词库格式：Tab 分隔三列  拼音/字母  词  词频
    去重键：第1列（拼音/字母） + 第2列（词）
    保留策略：词频最高者优先；词频相同时，file_list 中靠前的文件优先。
    """
    best = {}

    for priority, fname in enumerate(file_list):
        src_path = os.path.join(src_dir, fname)
        if not os.path.exists(src_path):
            print(f"  ⚠ 跳过（不存在）: {fname}")
            continue

        with open(src_path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                key = (parts[0], parts[1])   # (拼音/字母, 词)
                try:
                    freq = int(parts[2])
                except ValueError:
                    freq = 0

                if key not in best:
                    best[key] = (freq, priority, fname, line)
                else:
                    cur_freq, cur_pri, _, _ = best[key]
                    if freq > cur_freq or (freq == cur_freq and priority < cur_pri):
                        best[key] = (freq, priority, fname, line)

    result = defaultdict(list)
    for freq, priority, fname, line in best.values():
        result[fname].append(line)

    os.makedirs(dst_dir, exist_ok=True)
    stats = []
    for fname in file_list:
        src_path = os.path.join(src_dir, fname)
        dst_path = os.path.join(dst_dir, fname)
        if not os.path.exists(src_path):
            continue

        lines = sorted(result.get(fname, []), key=lambda l: l.split("\t")[0])
        with open(dst_path, "w", encoding="utf-8", newline="\n") as f:
            for line in lines:
                f.write(line + "\n")

        orig_count = sum(1 for _ in open(src_path, encoding="utf-8"))
        new_count  = len(lines)
        removed    = orig_count - new_count
        stats.append((fname, orig_count, new_count, removed))
        print(f"  {fname}: {orig_count} → {new_count}  (移除 {removed} 条重复)")

    return stats


def main():
    if len(sys.argv) < 2:
        print("用法: python dedup_output.py <output目录>")
        print("示例: python dedup_output.py ./output")
        sys.exit(1)

    output_dir = sys.argv[1]
    if not os.path.isdir(output_dir):
        print(f"错误：目录不存在：{output_dir}")
        sys.exit(1)

    print(f"\n{'='*50}")
    print("中文词库全局去重")
    print('='*50)
    cn_stats = dedup_files(output_dir, output_dir, CN_FILES_PRIORITY)

    print(f"\n{'='*50}")
    print("英文词库全局去重")
    print('='*50)
    en_stats = dedup_files(output_dir, output_dir, EN_FILES_PRIORITY)

    total_removed = sum(s[3] for s in cn_stats + en_stats)
    print(f"\n✅ 全部完成，共移除重复条目：{total_removed} 条")


if __name__ == "__main__":
    main()
