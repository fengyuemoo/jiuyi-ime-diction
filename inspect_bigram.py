#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_bigram.py — 直接解析 bigram.bin 并导出 CSV

用法：
  python inspect_bigram.py --input bigram.bin --output bigram_preview.csv
  python inspect_bigram.py --input bigram.bin --output bigram_preview.csv --min-score 3
"""
import argparse
import csv
import struct
from pathlib import Path

MAGIC          = b'JIUYI001'
FORMAT_VERSION = 2
HEADER_SIZE    = 32
_ENTRY_STRUCT  = struct.Struct('<QQQiI')


def read_str(data: bytes, offset: int) -> str:
    length = struct.unpack_from('<H', data, offset)[0]
    return data[offset + 2: offset + 2 + length].decode('utf-8', errors='replace')


def load_bigram(path: str):
    raw = Path(path).read_bytes()

    magic = raw[:8]
    if magic != MAGIC:
        raise ValueError(f'魔数不匹配: {magic!r}')

    version      = struct.unpack_from('<I', raw, 8)[0]
    entry_count  = struct.unpack_from('<I', raw, 12)[0]
    index_offset = struct.unpack_from('<Q', raw, 16)[0]

    pool = raw[HEADER_SIZE: index_offset]
    index_data = raw[index_offset:]

    entry_size = _ENTRY_STRUCT.size
    rows = []
    for i in range(entry_count):
        off = i * entry_size
        key_off, word_off, ini_off, freq, flags = _ENTRY_STRUCT.unpack_from(index_data, off)
        key_str = read_str(pool, key_off)
        score   = freq
        if '|' in key_str:
            prev, nxt = key_str.split('|', 1)
        else:
            prev, nxt = key_str, ''
        rows.append((prev, nxt, score))

    return rows


def main():
    p = argparse.ArgumentParser(description='解析 bigram.bin 并导出 CSV')
    p.add_argument('--input',     required=True,              help='bigram.bin 路径')
    p.add_argument('--output',    default='bigram_preview.csv', help='输出 CSV（默认 bigram_preview.csv）')
    p.add_argument('--min-score', type=int, default=0,        help='最小 score 过滤')
    args = p.parse_args()

    rows = load_bigram(args.input)
    print(f'[load] 共 {len(rows):,} 条词对')

    if args.min_score > 0:
        rows = [r for r in rows if r[2] >= args.min_score]
        print(f'[filter] min_score={args.min_score} 后 {len(rows):,} 条')

    rows.sort(key=lambda r: (-r[2], r[0], r[1]))

    with open(args.output, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['prev', 'next', 'score'])
        for prev, nxt, score in rows:
            writer.writerow([prev, nxt, score])

    print(f'[done] 已写出 {args.output}（{len(rows):,} 条）')


if __name__ == '__main__':
    main()
