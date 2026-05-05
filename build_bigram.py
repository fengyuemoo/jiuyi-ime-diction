#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_bigram.py — 从中文词库生成 bigram.bin

策略：前缀共现统计
  解决“每个 (prev,next) 词对唯一”导致 cnt 永远为 1 的问题。

  对每个倘选 prev 词 P：
    - prev_support(P) = 词库中以 P 开头的多字词数量
      例：「北京」作为前缀出现在：北京大学/北京市/北京人/北京路/北京天安门...
      prev_support(北京) = 这些词条的数量
    - prev_score(P) = min(20, log2(prev_support(P) + 1))

  对每个 (prev, next) 词对：
    - pair_cnt(P, N) = 词库中同时包含 P 和 N 两部分的词条数量
      （即切分局：Prev+Next 直接拼合成词）
    - pair_score(P, N) = min(prev_score, min(20, log2(pair_cnt + 1)))

  过滤条件： pair_cnt >= --min-count（默认 2）
    cnt=2 意味词库里至少两个词条共同包含该对的完整拼接形式
    （比如「北京大学」和「上海大学」都包含「大学」作为 next，但「大学」作为 prev 的尞子很少）

  这样才能输出真正有意义的 bigram：
    「北京 → 大学」只有在词库里同时就包含这个局部形式的词条超过 1 条时才得分。

字数规则：
  - prev 和 next 都可以是 1~4 字的纯中文词
  - 词条总字数 = len(prev) + len(next)，限制在 2~8 字内

输出格式：与 dict.bin 完全相同（JIUYI001 v2）
  key=\"prevWord|nextWord\"  word=nextWord  ini=\"\"  freq=分  flags=0

用法：
  python build_bigram.py --input cn_base.txt --output bigram.bin
  python build_bigram.py --input cn_base.txt --manual bigram_manual.tsv --output bigram.bin

参数：
  --input        cn_base.txt
  --manual       手工 TSV（可选）
  --output       输出路径（默认 bigram.bin）
  --min-count    pair_cnt 最小门槛（默认 2）
  --max-prev     prev 最大字数（默认 4）
  --max-next     next 最大字数（默认 4）
"""

import argparse
import collections
import math
import struct
from pathlib import Path

MAGIC          = b'JIUYI001'
FORMAT_VERSION = 2
HEADER_SIZE    = 32
MAX_FREQ       = 2_147_483_647
_ENTRY_STRUCT  = struct.Struct('<QQQiI')


# ---------------------------------------------------------------------------
# Step 1: 读取词库中所有纯中文词条
# ---------------------------------------------------------------------------

def load_zh_words(filepath: str) -> list[str]:
    """
    返回词库里所有纯中文词的列表（去重）。
    不依赖词频字段。
    """
    enc = 'utf-8'
    try:
        with open(filepath, 'rb') as f:
            if f.read(3) == b'\xef\xbb\xbf':
                enc = 'utf-8-sig'
    except Exception:
        pass

    seen = set()
    result = []
    with open(filepath, encoding=enc, errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            word = parts[1].strip()
            if not word or word in seen:
                continue
            if not all('\u4e00' <= c <= '\u9fff' for c in word):
                continue
            seen.add(word)
            result.append(word)
    print(f'[load ] 共 {len(result):,} 个不重复纯中文词')
    return result


# ---------------------------------------------------------------------------
# Step 2: 统计 prev_support 和 pair_cnt
# ---------------------------------------------------------------------------

def build_stats(
    words: list[str],
    max_prev: int,
    max_next: int,
    min_count: int,
) -> list[tuple[str, str, int]]:
    """
    遍历所有词条，将每个词条拆分为所有局部 (prev, next) 组合并累计。
    对每个词 W：
        for p in 1..min(max_prev, len(W)-1):
            prev = W[:p], next = W[p:p+max_next]
            若 len(next) in 1..max_next： pair_cnt[(prev,next)] += 1
    返回 [(prev, next, score), ...]。
    """
    word_set   = set(words)
    pair_cnt: dict[tuple[str, str], int] = collections.Counter()
    prev_sup:  dict[str, int]             = collections.Counter()

    total = len(words)
    for i, w in enumerate(words):
        if i % 100_000 == 0:
            print(f'  处理词条 {i:,}/{total:,}', end='\r')
        n = len(w)
        for p in range(1, min(max_prev, n - 1) + 1):
            prev = w[:p]
            # 只统计 prev 本身也是词库词的情况（避免拆出单字前缀）
            # 单字 prev 总是允许（单字字在词库里几乎必存）
            if len(prev) > 1 and prev not in word_set:
                continue
            for q in range(1, min(max_next, n - p) + 1):
                nxt = w[p:p + q]
                if nxt not in word_set and len(nxt) > 1:
                    continue
                pair_cnt[(prev, nxt)] += 1
                prev_sup[prev] += 1
    print()
    print(f'[build] 原始 (prev,next) 对 {len(pair_cnt):,} 条')

    result = []
    for (prev, nxt), cnt in pair_cnt.items():
        if cnt < min_count:
            continue
        ps = min(20, max(1, int(math.log2(prev_sup.get(prev, 1) + 1))))
        cs = min(20, max(1, int(math.log2(cnt + 1))))
        score = min(ps, cs)
        result.append((prev, nxt, score))

    result.sort(key=lambda r: (r[0], r[1]))
    print(f'[score] min_count={min_count} 过滤后 {len(result):,} 条')
    return result


# ---------------------------------------------------------------------------
# Step 3: 手工词对表（可选）
# ---------------------------------------------------------------------------

def load_manual(filepath: str) -> list[tuple[str, str, int]]:
    result = []
    enc = 'utf-8'
    try:
        with open(filepath, 'rb') as f:
            if f.read(3) == b'\xef\xbb\xbf':
                enc = 'utf-8-sig'
    except Exception:
        pass
    with open(filepath, encoding=enc, errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            prev  = parts[0].strip()
            nxt   = parts[1].strip()
            score = 10
            if len(parts) >= 3:
                try:
                    score = min(20, max(1, int(parts[2].strip())))
                except ValueError:
                    pass
            if prev and nxt:
                result.append((prev, nxt, score))
    print(f'[manual] 手工词对 {len(result):,} 条')
    return result


def merge(
    auto:   list[tuple[str, str, int]],
    manual: list[tuple[str, str, int]],
) -> list[tuple[str, str, int]]:
    best: dict[tuple[str, str], int] = {}
    for prev, nxt, s in auto:
        best[(prev, nxt)] = max(best.get((prev, nxt), 0), s)
    for prev, nxt, s in manual:
        best[(prev, nxt)] = max(best.get((prev, nxt), 0), s)
    merged = sorted(((p, n, s) for (p, n), s in best.items()),
                    key=lambda r: (r[0], r[1]))
    print(f'[merge] 合并后共 {len(merged):,} 条')
    return merged


# ---------------------------------------------------------------------------
# Step 4: 写入 bigram.bin
# ---------------------------------------------------------------------------

def write_bin(pairs: list[tuple[str, str, int]], out_path: str):
    print(f'[write] 打包 {len(pairs):,} 条 → {out_path}')
    pool:  bytearray      = bytearray()
    cache: dict[str, int] = {}

    def intern(s: str) -> int:
        if s in cache:
            return cache[s]
        off = len(pool)
        b   = s.encode('utf-8')
        pool.extend(struct.pack('<H', len(b)))
        pool.extend(b)
        cache[s] = off
        return off

    rows = []
    for prev, nxt, score in pairs:
        rows.append((intern(f'{prev}|{nxt}'), intern(nxt), intern(''), score, 0))

    index_offset = HEADER_SIZE + len(pool)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('<I', FORMAT_VERSION))
        f.write(struct.pack('<I', len(rows)))
        f.write(struct.pack('<Q', index_offset))
        f.write(struct.pack('<Q', 0))
        f.write(bytes(pool))
        for ko, wo, io, freq, flags in rows:
            f.write(_ENTRY_STRUCT.pack(ko, wo, io, freq, flags))

    size_mb = Path(out_path).stat().st_size / 1024 / 1024
    print(f'[write] 完成！{len(rows):,} 条 → {out_path} ({size_mb:.2f} MB)')


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description='生成 bigram.bin')
    p.add_argument('--input',     required=True)
    p.add_argument('--manual',    default='')
    p.add_argument('--output',    default='bigram.bin')
    p.add_argument('--min-count', type=int, default=2,
                   help='pair 最少被多少个词条包含（默认 2）')
    p.add_argument('--max-prev',  type=int, default=4,
                   help='prev 最大字数（默认 4）')
    p.add_argument('--max-next',  type=int, default=4,
                   help='next 最大字数（默认 4）')
    args = p.parse_args()

    words = load_zh_words(args.input)
    pairs = build_stats(words, args.max_prev, args.max_next, args.min_count)

    if args.manual and Path(args.manual).exists():
        manual = load_manual(args.manual)
        pairs  = merge(pairs, manual)

    write_bin(pairs, args.output)
    print('[done ] bigram.bin 生成完毕，请复制到 jiuyi-ime-android/app/src/main/assets/')


if __name__ == '__main__':
    main()
