#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_bigram.py — 从 cn_base.txt 直接列出 bigram 词对，无需读 bigram.bin。

用法：
  python inspect_bigram.py --input cn_base.txt --top 200 --scale 100000 --out bigram_preview.csv
"""
import argparse
import math
import csv

def load_zh_words(filepath, top_n):
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
            if not all('\u4e00' <= c <= '\u9fff' for c in word):
                continue
            if word in words:
                words[word] = max(words[word], freq)
            else:
                words[word] = freq
    sorted_words = sorted(words.items(), key=lambda x: x[1], reverse=True)
    return sorted_words[:top_n]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  required=True)
    parser.add_argument('--top',    type=int, default=200)
    parser.add_argument('--scale',  type=int, default=100000)
    parser.add_argument('--out',    default='bigram_preview.csv')
    args = parser.parse_args()

    words = load_zh_words(args.input, args.top)
    print(f"取前 {len(words)} 个词：{ [w for w,_ in words[:20]] } ...")

    rows = []
    for i, (prev, fp) in enumerate(words):
        for j, (nxt, fn) in enumerate(words):
            if prev == nxt:
                continue
            co = min(fp, fn)
            score = int(math.log2(co / args.scale + 1))
            score = min(20, max(0, score))
            if score >= 1:
                rows.append((score, prev, fp, nxt, fn))

    # 按分降序、prev词频降序排列
    rows.sort(key=lambda r: (-r[0], -r[2], -r[4]))

    with open(args.out, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['score', 'prev_word', 'prev_freq', 'next_word', 'next_freq'])
        for r in rows:
            writer.writerow(r)

    print(f"共 {len(rows):,} 条，已写出 {args.out}")

if __name__ == '__main__':
    main()
