#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_bigram.py — 从中文词库生成 bigram.bin

策略：拆解多字词条推断搜配强度
  cn_base.txt 中的多字词（N ≥ 2）就是隐含的 bigram 证据。
  例如：
    ni'hao      你好       → 不拆（单个音节词的组合就是 bigram）
    bei'jing    北京       → 「北 → 京」（单字级）
    zhong'guo   中国       → 「中 → 国」
    bei'jing'da'xue 北京大学 → 「北京 → 大学」（双字词级）
    zhong'hua'ren'min 中华人民 → 「中华 → 人民」

  拆分规则：
    - 2音节词： prev = 第1字， next = 第2字（单字级）
    - 3音节词： prev = 第1字1字， next = 后2字； prev = 前2字， next = 第3字1字
    - 4音节词： prev = 前2字， next = 后2字（双字词级）
    - 5+音节词： prev = 前 N//2 字， next = 后 N//2 字
    每条词对的得分 = min(20, log2(词条在词库中出现次数 + 1))
    出现次数 = 该模式对应的所有词条的词条间索引和（以 idx 累加）

  词库词频字段不使用（它们在 cn_base.txt 中无法信赖）。
  只用词条的「存在」和「在词库中的排序位置（越靠前 = 词条越少见 = 越高级）。

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
  # 然后将 bigram.bin 复制到 jiuyi-ime-android/app/src/main/assets/

参数：
  --input   输入词库文件（cn_base.txt 格式）
  --manual  可选：手工词对文件（TSV：prev_word TAB next_word TAB score）
  --output  输出文件路径（默认 bigram.bin）
  --min-word-len  参与拆分的最小词条字数（默认 2）
  --max-word-len  参与拆分的最大词条字数（默认 8）
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
# Step 1: 读取词库，返回所有符合词长的词条列表
# ---------------------------------------------------------------------------

def load_entries(filepath: str, min_len: int, max_len: int) -> list[tuple[str, str]]:
    """
    返回 [(pinyin, word), ...]，只保留字数在 [min_len, max_len] 之间的纯中文词条。
    不加载词频字段。
    """
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
    """
    将一条词条拆分为 (prev_word, next_word) 列表。
    以音节分界为领，用汉字数对齐切分点。
    """
    syllables = [s for s in pinyin.split("'") if s.strip()]
    n = len(word)
    ns = len(syllables)
    # 音节数和字数不匹配时回退
    if ns != n:
        return []

    pairs = []
    if n == 2:
        # 单字级
        pairs.append((word[0], word[1]))
    elif n == 3:
        # 前1 → 后2，前2 → 后1
        pairs.append((word[0], word[1:]))
        pairs.append((word[:2], word[2]))
    elif n == 4:
        # 双字词级
        pairs.append((word[:2], word[2:]))
    else:
        # 5+ 字：前华 N//2 字
        half = n // 2
        pairs.append((word[:half], word[half:]))

    return pairs


def build_pairs(entries: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """
    遍历所有词条，累加每个 (prev, next) 对的出现次数。
    出现次数 = 该对对应的所有词条的词条序号和（用序号而非词频）。
    """
    count: dict[tuple[str, str], int] = {}
    for idx, (pinyin, word) in enumerate(entries):
        for prev, nxt in split_to_pairs(pinyin, word):
            key = (prev, nxt)
            count[key] = count.get(key, 0) + 1
    print(f'[build] 拆分得到原始词对 {len(count):,} 条')
    return count


def score_pairs(count: dict[tuple[str, str], int], min_score: int = 1) \
        -> list[tuple[str, str, int]]:
    """
    将出现次数映射为先验分 1~20，过滤掉低于 min_score 的。
    返回 [(prev, next, score), ...] 按 (prev, next) 升序。
    """
    result = []
    for (prev, nxt), cnt in count.items():
        s = min(20, max(0, int(math.log2(cnt + 1))))
        if s >= min_score:
            result.append((prev, nxt, s))
    result.sort(key=lambda r: (r[0], r[1]))
    print(f'[score] 过滤后有效词对 {len(result):,} 条')
    return result


# ---------------------------------------------------------------------------
# Step 3: 加入手工词对表（可选）
# ---------------------------------------------------------------------------

def load_manual(filepath: str) -> list[tuple[str, str, int]]:
    """
    读取手工 TSV 文件： prev_word TAB next_word TAB score
    返回 [(prev, next, score), ...]
    """
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
    """
    将自动对和手工对合并，手工对取更大分。
    """
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

    pool: bytearray      = bytearray()
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
        key = f'{prev}|{nxt}'
        rows.append((_ENTRY_STRUCT, intern(key), intern(nxt), intern(''), score, 0))

    index_offset = HEADER_SIZE + len(pool)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('<I', FORMAT_VERSION))
        f.write(struct.pack('<I', len(rows)))
        f.write(struct.pack('<Q', index_offset))
        f.write(struct.pack('<Q', 0))
        f.write(bytes(pool))
        for _, ko, wo, io, freq, flags in rows:
            f.write(_ENTRY_STRUCT.pack(ko, wo, io, freq, flags))

    size_mb = Path(out_path).stat().st_size / 1024 / 1024
    print(f'[write] 完成！{len(rows):,} 条 → {out_path} ({size_mb:.2f} MB)')


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description='生成 bigram.bin（久以输入法 bigram 先验词库）')
    p.add_argument('--input',        required=True, help='输入词库（cn_base.txt）')
    p.add_argument('--manual',       default='',    help='手工词对 TSV（可选）')
    p.add_argument('--output',       default='bigram.bin')
    p.add_argument('--min-word-len', type=int, default=2,  help='参与拆分的最小字数（默认 2）')
    p.add_argument('--max-word-len', type=int, default=8,  help='参与拆分的最大字数（默认 8）')
    args = p.parse_args()

    entries = load_entries(args.input, args.min_word_len, args.max_word_len)
    count   = build_pairs(entries)
    pairs   = score_pairs(count)

    if args.manual and Path(args.manual).exists():
        manual = load_manual(args.manual)
        pairs  = merge(pairs, manual)

    write_bin(pairs, args.output)
    print('[done ] bigram.bin 生成完毕，请复制到 jiuyi-ime-android/app/src/main/assets/')


if __name__ == '__main__':
    main()
