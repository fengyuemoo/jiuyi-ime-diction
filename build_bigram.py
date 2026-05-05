#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_bigram.py — 从中文词库生成 bigram.bin

策略：拆解多字词条推断搜配强度
  cn_base.txt 中的多字词（N ≥ 2）就是隐含的 bigram 证据。
  一个 (prev, next) 词对在词库中被多个不同词条共享，说明这个搜配在语言中封化得越稳固。
  例如：
    bei'jing    北京  → 「北 → 京」
    bei'jing'da'xue 北京大学 → 「北京 → 大学」
    zhong'hua'ren'min 中华人民 → 「中华 → 人民」

  得分公式：score = min(20, log2(cnt + 1))
  cnt = 该词对被多少个不同词条包含

  阶梯参考：
    cnt ≥ 1  → score 1（仅一个词包含，证据极弱）
    cnt ≥ 3  → score 2
    cnt ≥ 7  → score 3  ← 默认门槛（--min-count 7）
    cnt ≥ 15 → score 4
    cnt ≥ 31 → score 5

输出格式：与 dict.bin 完全相同（JIUYI001 v2）
  key   = "prevWord|nextWord"
  word  = nextWord
  ini   = ""
  freq  = 先验分 1~20（int32）
  flags = 0

用法：
  cd jiuyi-ime-diction/
  python build_bigram.py --input cn_base.txt --output bigram.bin
  # 可选加入手工词对表
  python build_bigram.py --input cn_base.txt --manual bigram_manual.tsv --output bigram.bin

参数：
  --input        输入词库文件（cn_base.txt 格式）
  --manual       可选：手工词对文件（TSV：prev TAB next TAB score）
  --output       输出文件路径（默认 bigram.bin）
  --min-count    词对最少需被多少个词条包含，低于此就过滤（默认 7）
  --min-word-len 参与拆分的最小词条字数（默认 2）
  --max-word-len 参与拆分的最大词条字数（默认 8）
"""

import argparse
import math
import struct
from pathlib import Path

MAGIC          = b'JIUYI001'
FORMAT_VERSION = 2
HEADER_SIZE    = 32
MAX_FREQ       = 2_147_483_647
_ENTRY_STRUCT  = struct.Struct('<QQQiI')


# ---------------------------------------------------------------------------
# Step 1: 读取词库
# ---------------------------------------------------------------------------

def load_entries(filepath: str, min_len: int, max_len: int) -> list[tuple[str, str]]:
    enc = 'utf-8'
    try:
        with open(filepath, 'rb') as f:
            if f.read(3) == b'\xef\xbb\xbf':
                enc = 'utf-8-sig'
    except Exception:
        pass
    result = []
    with open(filepath, encoding=enc, errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            pinyin = parts[0].strip()
            word   = parts[1].strip()
            if not word or not pinyin:
                continue
            if not all('\u4e00' <= c <= '\u9fff' for c in word):
                continue
            n = len(word)
            if n < min_len or n > max_len:
                continue
            result.append((pinyin, word))
    print(f'[load ] {len(result):,} 条符合条件的词条（{min_len}–{max_len}字）')
    return result


# ---------------------------------------------------------------------------
# Step 2: 拆解词条成 bigram 对
# ---------------------------------------------------------------------------

def split_to_pairs(pinyin: str, word: str) -> list[tuple[str, str]]:
    syllables = [s for s in pinyin.split("'") if s.strip()]
    n  = len(word)
    ns = len(syllables)
    if ns != n:
        return []
    if n == 2:
        return [(word[0], word[1])]
    elif n == 3:
        return [(word[0], word[1:]), (word[:2], word[2])]
    elif n == 4:
        return [(word[:2], word[2:])]
    else:
        half = n // 2
        return [(word[:half], word[half:])]


def build_pairs(entries: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    count: dict[tuple[str, str], int] = {}
    for pinyin, word in entries:
        for prev, nxt in split_to_pairs(pinyin, word):
            k = (prev, nxt)
            count[k] = count.get(k, 0) + 1
    print(f'[build] 拆分得到原始词对 {len(count):,} 条')
    return count


def score_pairs(count: dict[tuple[str, str], int], min_count: int) \
        -> list[tuple[str, str, int]]:
    """
    过滤掉 cnt < min_count 的词对，剩下的映射为分 1~20。
    min_count=7 对应 score≥3，即至少 7 个不同词条包含此搜配。
    """
    result = []
    for (prev, nxt), cnt in count.items():
        if cnt < min_count:
            continue
        s = min(20, max(1, int(math.log2(cnt + 1))))
        result.append((prev, nxt, s))
    result.sort(key=lambda r: (r[0], r[1]))
    print(f'[score] min_count={min_count} 过滤后有效词对 {len(result):,} 条')
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
            prev = parts[0].strip()
            nxt  = parts[1].strip()
            try:
                score = min(20, max(1, int(parts[2].strip()))) if len(parts) >= 3 else 10
            except ValueError:
                score = 10
            if prev and nxt:
                result.append((prev, nxt, score))
    print(f'[manual] 手工词对 {len(result):,} 条')
    return result


def merge(auto: list[tuple[str, str, int]],
          manual: list[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
    best: dict[tuple[str, str], int] = {}
    for prev, nxt, s in auto:
        best[(prev, nxt)] = max(best.get((prev, nxt), 0), s)
    for prev, nxt, s in manual:
        best[(prev, nxt)] = max(best.get((prev, nxt), 0), s)
    merged = sorted(((p, n, s) for (p, n), s in best.items()), key=lambda r: (r[0], r[1]))
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
    p = argparse.ArgumentParser(description='生成 bigram.bin（久以输入法 bigram 先验词库）')
    p.add_argument('--input',        required=True)
    p.add_argument('--manual',       default='')
    p.add_argument('--output',       default='bigram.bin')
    p.add_argument('--min-count',    type=int, default=7,
                   help='词对最少被多少个词条包含（默认 7，对应 score≥3）')
    p.add_argument('--min-word-len', type=int, default=2)
    p.add_argument('--max-word-len', type=int, default=8)
    args = p.parse_args()

    entries = load_entries(args.input, args.min_word_len, args.max_word_len)
    count   = build_pairs(entries)
    pairs   = score_pairs(count, args.min_count)

    if args.manual and Path(args.manual).exists():
        manual = load_manual(args.manual)
        pairs  = merge(pairs, manual)

    write_bin(pairs, args.output)
    print('[done ] bigram.bin 生成完毕，请复制到 jiuyi-ime-android/app/src/main/assets/')


if __name__ == '__main__':
    main()
