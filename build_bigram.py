#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_bigram.py — 从中文词库生成 bigram.bin

原理：
  从 cn_base.txt（拼音\t词\t词频 格式）读取所有中文词及词频。
  用词频模拟共现：对词频最高的 TOP_N 个词，枚举所有有意义的「词对」，
  共现分 = min(20, log2(min(freq_prev, freq_next) / FREQ_SCALE + 1))

  这不是真正的语料 bigram 统计，但对于输入法而言效果相当于：
  - 两个词都高频 → 它们搭配出现概率也高 → 先验分高
  - 冷门词无论与谁搭配 → 先验分低

  配合 BigramStore 动态学习，用户的真实习惯会在几次选词后覆盖先验。

输出格式：与 dict.bin 完全相同（JIUYI001 v2）
  key  = "prevWord|nextWord"（UTF-8）
  word = nextWord
  ini  = ""（bigram 不需要 initials）
  freq = 先验分 0~20（int32）
  flags= 0

用法：
  cd jiuyi-ime-diction/
  python build_bigram.py --input cn_base.txt --output bigram.bin
  # 然后将 bigram.bin 复制到 jiuyi-ime-android/app/src/main/assets/

参数：
  --input   输入词库文件（cn_base.txt 格式）
  --output  输出文件路径（默认 bigram.bin）
  --top     取词频最高的 TOP 词作为 prev/next 候选（默认 3000）
  --scale   共现分计算的频次基准 FREQ_SCALE（默认 1000）
"""

import argparse
import math
import struct
import sys
from pathlib import Path

MAGIC          = b'JIUYI001'
FORMAT_VERSION = 2
HEADER_SIZE    = 32
ENTRY_SIZE     = 32
MAX_FREQ       = 2_147_483_647

_ENTRY_STRUCT = struct.Struct('<QQQiI')


def load_zh_words(filepath: str, top_n: int) -> list[tuple[str, int]]:
    """读取 cn_base.txt，返回按词频降序的 (word, freq) 列表，取前 top_n 条。"""
    words = {}
    enc = 'utf-8'
    try:
        with open(filepath, 'rb') as f:
            bom = f.read(3)
        if bom[:3] == b'\xef\xbb\xbf':
            enc = 'utf-8-sig'
    except Exception:
        pass

    with open(filepath, encoding=enc, errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            word = parts[1].strip()
            try:
                freq = int(parts[2].strip())
            except ValueError:
                continue
            if not word:
                continue
            # 只保留纯中文词（过滤英文、数字、标点）
            if not all('\u4e00' <= c <= '\u9fff' for c in word):
                continue
            if word in words:
                words[word] = max(words[word], freq)
            else:
                words[word] = freq

    sorted_words = sorted(words.items(), key=lambda x: x[1], reverse=True)
    result = sorted_words[:top_n]
    print(f"[load ] 共 {len(words):,} 个中文词，取前 {len(result):,} 个构建 bigram")
    return result


def compute_score(freq_prev: int, freq_next: int, scale: int) -> int:
    """对数归一化先验分，映射到 0~20。"""
    co_occur = min(freq_prev, freq_next)
    score = math.log2(co_occur / scale + 1)
    return min(20, max(0, int(score)))


def build_bigram_entries(
    words: list[tuple[str, int]],
    scale: int,
    min_score: int = 1
) -> list[tuple[str, str, str, int, int]]:
    """
    枚举所有 (prev, next) 词对，过滤掉得分为 0 的。
    返回 [(key, word, initials, freq, flags), ...] 按 key 升序。
    """
    print(f"[build] 枚举词对（{len(words):,} × {len(words):,} = {len(words)**2:,} 对）...")
    entries = {}
    total = len(words)
    for i, (prev, fp) in enumerate(words):
        if i % 500 == 0:
            print(f"  {i}/{total}", end='\r')
        for next_word, fn in words:
            if prev == next_word:
                continue
            score = compute_score(fp, fn, scale)
            if score < min_score:
                continue
            key = f"{prev}|{next_word}"
            if key not in entries or score > entries[key]:
                entries[key] = score

    print(f"\n[build] 有效词对 {len(entries):,} 条")
    result = sorted(
        ((k, k.split('|', 1)[1], '', v, 0) for k, v in entries.items()),
        key=lambda e: e[0]
    )
    return result


def write_bin(entries: list, out_path: str):
    """写入 bigram.bin，格式与 dict.bin 完全相同。"""
    print(f"[write] 打包 {len(entries):,} 条词对 → {out_path}")

    pool      = bytearray()
    str_cache = {}

    def intern(s: str) -> int:
        if s in str_cache:
            return str_cache[s]
        offset = len(pool)
        encoded = s.encode('utf-8')
        pool.extend(struct.pack('<H', len(encoded)))
        pool.extend(encoded)
        str_cache[s] = offset
        return offset

    index_rows = []
    for key, word, ini, freq, flags in entries:
        ko = intern(key)
        wo = intern(word)
        io = intern(ini)
        freq = min(max(freq, 0), MAX_FREQ)
        index_rows.append((ko, wo, io, freq, flags))

    pool_size    = len(pool)
    index_offset = HEADER_SIZE + pool_size
    entry_count  = len(index_rows)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('<I', FORMAT_VERSION))
        f.write(struct.pack('<I', entry_count))
        f.write(struct.pack('<Q', index_offset))
        f.write(struct.pack('<Q', 0))  # reserved
        f.write(bytes(pool))
        for row in index_rows:
            f.write(_ENTRY_STRUCT.pack(*row))

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"[write] 完成！{entry_count:,} 条 → {out_path} ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="生成 bigram.bin（久以输入法 bigram 先验词库）")
    parser.add_argument('--input',  required=True, help='输入词库文件（cn_base.txt）')
    parser.add_argument('--output', default='bigram.bin', help='输出路径（默认 bigram.bin）')
    parser.add_argument('--top',    type=int, default=3000, help='取词频最高的 TOP 词（默认 3000）')
    parser.add_argument('--scale',  type=int, default=1000, help='共现分频次基准（默认 1000）')
    args = parser.parse_args()

    words   = load_zh_words(args.input, args.top)
    entries = build_bigram_entries(words, args.scale)
    write_bin(entries, args.output)
    print("[done ] bigram.bin 生成完毕，请复制到 jiuyi-ime-android/app/src/main/assets/")


if __name__ == '__main__':
    main()
