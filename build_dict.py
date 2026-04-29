#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dict.py — 久以输入法词库构建脚本

将一个或多个词库文本文件打包为自定义二进制格式 dict.bin，供 Android App mmap 使用。

词库文件格式（Tab 分隔三列，UTF-8 无 BOM）：
  中文：  拼音(撇号分隔音节)  汉字/词  词频
  英文：  字母串              词       词频

  中文示例：  ni'hao\t你好\t523901
  英文示例：  hello\thello\t5000000

────────────────────────────────────────────────
dict.bin 二进制格式
────────────────────────────────────────────────
[HEADER  32B]
  magic[8]       = b'JIUYI001'
  version[4]     = 1  (LE uint32)
  entry_count[4] = N  (LE uint32)
  index_offset[8]= 偏移量，指向 INDEX TABLE 起始 (LE uint64)
  reserved[8]    = 0

[STRING POOL  变长]
  每条字符串：2B(LE uint16 长度) + UTF-8 字节
  pool 中存储所有 key(拼音/字母)、word、initials 字符串
  连续排列，offset 从 pool 起始位置算起

[INDEX TABLE  每条 20B，共 N 条，按 key 字符串升序排列]
  key_offset [4B  LE uint32] → string pool 偏移
  word_offset[4B  LE uint32] → string pool 偏移
  ini_offset [4B  LE uint32] → string pool 偏移 (initials)
  freq       [4B  LE int32 ]   ← 有符号，最大 2147483647，超过则截断
  flags      [4B  LE uint32] bit0=lang(0=en,1=zh)

查询方式：
  - 前缀查询：二分定位第一个 key >= prefix 的位置，顺序扫描
  - T9 查询：将输入数字串对应到所有可能字母前缀，多次前缀查询合并
  - initials 查询：直接扫描 ini_offset 字段
────────────────────────────────────────────────

initials 字段：
  中文词存储拼音的首字母序列，供简拼查询。
  "zhong'guo" → "zg"，"ni'hao" → "nh"。
  英文词 initials = ""。

主键设计：(key, word) 复合唯一。
  - 英文词：key = 字母串（小写），word 唯一。
  - 中文词：多音字每个读音独立一条。

用法示例：
  python build_dict.py --input en_base.txt --lang en --output dict.bin
  python build_dict.py --input cn_base.txt en_base.txt --lang zh en --output dict.bin
  python build_dict.py --verify dict.bin
"""

import argparse
import struct
import sys
from pathlib import Path

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


MAGIC          = b'JIUYI001'
FORMAT_VERSION = 1
HEADER_SIZE    = 32
ENTRY_SIZE     = 20   # key_offset(4) + word_offset(4) + ini_offset(4) + freq(4) + flags(4)
MAX_WORD_LEN   = 100
MAX_FREQ       = 2_147_483_647   # int32 最大値，超过则截断


def pinyin_to_initials(pinyin: str) -> str:
    if not pinyin:
        return ''
    syllables = [s.strip() for s in pinyin.split("'") if s.strip()]
    return ''.join(syl[0] for syl in syllables if syl)


def detect_encoding(filepath: str) -> str:
    with open(filepath, 'rb') as f:
        bom = f.read(3)
    if bom[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return 'utf-16'
    if bom[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    return 'utf-8'


def parse_line(line: str, lang: str = 'en'):
    """
    解析一行词库条目，返回 (word, key, freq) 或 None。

    支持格式：
      Tab 三列：  key(拼音/字母)  词  词频
      Tab 两列：  词  词频
      CSV：       词,词频
    """
    line = line.strip().lstrip('\ufeff')
    if not line or line.startswith('#'):
        return None

    if '\t' in line:
        parts = line.split('\t')
        if len(parts) >= 3:
            key  = parts[0].strip()
            word = parts[1].strip()
            try:
                freq = int(parts[2].strip())
            except ValueError:
                freq = 0
        else:
            word = parts[0].strip()
            try:
                freq = int(parts[1].strip())
            except (ValueError, IndexError):
                freq = 0
            key = word.lower() if lang == 'en' else ''
        if not word or len(word) > MAX_WORD_LEN:
            return None
        return (word, key, freq)

    if ',' in line:
        parts = line.split(',', 1)
        word = parts[0].strip()
        try:
            freq = int(float(parts[1].strip()))
        except (ValueError, IndexError):
            freq = 0
        if not word or len(word) > MAX_WORD_LEN:
            return None
        key = word.lower() if lang == 'en' else ''
        return (word, key, freq)

    word = line.strip()
    if not word or len(word) > MAX_WORD_LEN:
        return None
    return (word, word.lower() if lang == 'en' else '', 0)


def load_all_entries(input_files, langs):
    """
    读取所有词库文件，去重后返回排好序的条目列表。
    去重键：(key, word)。相同 key+word 保留词频最大的。
    返回值：[(key, word, initials, freq, lang_flag), ...] 按 key 升序。
    """
    best = {}  # (key, word) -> (freq, lang_flag, initials)

    for filepath, lang in zip(input_files, langs):
        path = Path(filepath)
        if not path.exists():
            print(f"[error] File not found: {filepath}", file=sys.stderr)
            continue

        enc          = detect_encoding(filepath)
        lang_flag    = 1 if lang == 'zh' else 0
        total_lines  = sum(1 for _ in open(filepath, encoding=enc, errors='ignore'))
        print(f"[load ] {path.name} ({total_lines:,} lines, lang={lang})")

        iter_lines = open(filepath, encoding=enc, errors='ignore')
        if HAS_TQDM:
            iter_lines = tqdm(iter_lines, total=total_lines, unit='lines', desc=path.name)

        try:
            for line in iter_lines:
                result = parse_line(line, lang)
                if result is None:
                    continue
                word, key, freq = result
                if not key:
                    continue
                # 截断到 int32 上限
                freq = min(freq, MAX_FREQ)
                initials = pinyin_to_initials(key) if lang == 'zh' else ''
                dk = (key, word)
                if dk not in best or freq > best[dk][0]:
                    best[dk] = (freq, lang_flag, initials)
        finally:
            if hasattr(iter_lines, 'close'):
                iter_lines.close()

    print(f"[load ] 去重后共 {len(best):,} 条")
    entries = sorted(
        ((k[0], k[1], v[2], v[0], v[1]) for k, v in best.items()),
        key=lambda e: e[0]
    )
    return entries


def build_bin(entries, out_path: str):
    """
    将 entries 写入 dict.bin。
    entries: [(key, word, initials, freq, lang_flag), ...] 已按 key 升序。
    freq 字段为 LE int32（有符号），最大 2147483647。
    """
    print(f"[build] 开始打包 {len(entries):,} 条词条...")

    pool      = bytearray()
    str_cache = {}  # str -> offset

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
    for key, word, initials, freq, lang_flag in entries:
        ko = intern(key)
        wo = intern(word)
        io = intern(initials)
        freq = min(max(freq, 0), MAX_FREQ)   # 保险容错：再次截断
        index_rows.append((ko, wo, io, freq, lang_flag))

    pool_offset  = HEADER_SIZE
    index_offset = pool_offset + len(pool)
    entry_count  = len(index_rows)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, 'wb') as f:
        # Header
        f.write(MAGIC)
        f.write(struct.pack('<I', FORMAT_VERSION))
        f.write(struct.pack('<I', entry_count))
        f.write(struct.pack('<Q', index_offset))
        f.write(struct.pack('<Q', 0))  # reserved

        # String pool
        f.write(bytes(pool))

        # Index table
        # 格式： IIIiI = uint32 key_offset, uint32 word_offset, uint32 ini_offset,
        #              int32 freq, uint32 flags
        for ko, wo, io, freq, lang_flag in index_rows:
            f.write(struct.pack('<IIIiI', ko, wo, io, freq, lang_flag))

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"[build] 完成！{entry_count:,} 条 → {out_path} ({size_mb:.1f} MB)")
    if size_mb > 80:
        print("[warn ] 文件超过 80MB，建议检查是否有重复词条。")


def verify_bin(bin_path: str):
    """验证 dict.bin 结构与内容。"""
    path = Path(bin_path)
    if not path.exists():
        print(f"[error] 文件不存在：{bin_path}", file=sys.stderr)
        sys.exit(1)

    data = path.read_bytes()
    size_mb = len(data) / 1024 / 1024
    print(f"[verify] 文件大小：{size_mb:.1f} MB")

    magic = data[:8]
    if magic != MAGIC:
        print(f"[error] magic 不匹配：{magic}")
        sys.exit(1)
    version,      = struct.unpack_from('<I', data, 8)
    entry_count,  = struct.unpack_from('<I', data, 12)
    index_offset, = struct.unpack_from('<Q', data, 16)
    print(f"[verify] version={version}, entry_count={entry_count:,}, index_offset={index_offset}")

    pool_start = HEADER_SIZE

    def read_str(offset: int) -> str:
        length, = struct.unpack_from('<H', data, pool_start + offset)
        return data[pool_start + offset + 2: pool_start + offset + 2 + length].decode('utf-8')

    zh_count = en_count = 0
    for i in range(entry_count):
        base = index_offset + i * ENTRY_SIZE
        flags, = struct.unpack_from('<I', data, base + 16)
        if flags & 1:
            zh_count += 1
        else:
            en_count += 1
    print(f"[verify] zh={zh_count:,}, en={en_count:,}")

    print("[verify] 前5条样本：")
    for i in range(min(5, entry_count)):
        base = index_offset + i * ENTRY_SIZE
        ko, wo, io, freq, flags = struct.unpack_from('<IIIiI', data, base)
        key      = read_str(ko)
        word     = read_str(wo)
        initials = read_str(io)
        lang     = 'zh' if flags & 1 else 'en'
        print(f"         [{i}] key={key} word={word} initials={initials} freq={freq} lang={lang}")

    print("[verify] 检查 index 排序...")
    prev_key = ''
    unsorted = 0
    for i in range(entry_count):
        base = index_offset + i * ENTRY_SIZE
        ko,  = struct.unpack_from('<I', data, base)
        key  = read_str(ko)
        if key < prev_key:
            unsorted += 1
            if unsorted <= 3:
                print(f"  [warn] index[{i}] key={key!r} < prev={prev_key!r}")
        prev_key = key
    if unsorted == 0:
        print("[verify] index 排序正确 ✓")
    else:
        print(f"[verify] 发现 {unsorted} 处乱序！")

    print("[verify] 完成。")


def main():
    parser = argparse.ArgumentParser(description="久以输入法词库构建工具（二进制格式）")
    parser.add_argument('--input',  nargs='+', help='词库输入文件（支持多个）')
    parser.add_argument('--lang',   nargs='+', help='每个文件对应的语言标识（en / zh）')
    parser.add_argument('--output', default='dict.bin', help='输出文件路径（默认 dict.bin）')
    parser.add_argument('--verify', metavar='BIN_PATH', help='验证已构建的 dict.bin')
    args = parser.parse_args()

    if args.verify:
        verify_bin(args.verify)
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    langs = args.lang if args.lang else ['en'] * len(args.input)
    if len(langs) != len(args.input):
        print('[error] --lang 数量必须与 --input 文件数量一致', file=sys.stderr)
        sys.exit(1)

    entries = load_all_entries(args.input, langs)
    build_bin(entries, args.output)


if __name__ == '__main__':
    main()
