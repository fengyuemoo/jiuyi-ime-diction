#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jiuyi-ime-diction 词库统一格式转换脚本

所有词库文件原始格式均为 Tab 分隔四列：
  中文 / 中英混合：  拼音(音节用'分隔)  T9编码  汉字或词  词频
  英文：             字母串(小写)       T9编码  词        词频

目标格式（Tab 分隔三列，UTF-8 无 BOM）：
  中文 / 中英混合：  拼音    词    词频
  英文：             字母串  词    词频

T9 列直接丢弃，由 build_dict.py 打包时实时计算。

用法：
  python convert_dicts.py <源目录> <输出目录>

示例：
  python convert_dicts.py . ./output
"""

import os
import re
import sys

try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    print("请先安装 pypinyin：pip install pypinyin")
    sys.exit(1)


# ── 工具函数 ──────────────────────────────────────────────────

def hanzi_to_pinyin(word: str) -> str:
    """汉字 → 拼音（音节间用 ' 分隔）"""
    syllables = lazy_pinyin(word, style=Style.NORMAL, errors="ignore")
    syllables = [s for s in syllables if s]
    if not syllables:
        return ""
    return syllables[0] if len(syllables) == 1 else "'".join(syllables)


def has_chinese(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", s))


# ── 通用解析器 ────────────────────────────────────────────────
#
# 所有文件格式统一为 Tab 分隔四列：
#   col0: 拼音 / 字母串
#   col1: T9 编码（丢弃）
#   col2: 词
#   col3: 词频
#
# 同时兼容三列（无 T9 列）和两列旧格式。

def parse_tab4(path: str):
    """
    解析 Tab 分隔四列文件，返回 [(key, word, freq), ...]。
    兼容三列和两列。col1（T9）直接丢弃。
    """
    results = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n\r").lstrip("\ufeff")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 4:
                key  = parts[0].strip()
                # parts[1] = T9，丢弃
                word = parts[2].strip()
                try:
                    freq = int(parts[3].strip())
                except ValueError:
                    freq = 1
            elif len(parts) == 3:
                key  = parts[0].strip()
                word = parts[1].strip()
                try:
                    freq = int(parts[2].strip())
                except ValueError:
                    freq = 1
            elif len(parts) == 2:
                key  = parts[0].strip()
                word = parts[1].strip()
                freq = 1
            else:
                continue
            if key and word:
                results.append((key, word, freq))
    return results


# ── 去重 ──────────────────────────────────────────────────────

def dedup(entries):
    """(key, word) 为唯一键，保留词频最大的。"""
    best_freq  = {}
    best_entry = {}
    for key, word, freq in entries:
        k = (key, word)
        if k not in best_freq or freq > best_freq[k]:
            best_freq[k]  = freq
            best_entry[k] = (key, word, freq)
    return list(best_entry.values())


# ── 写出 ──────────────────────────────────────────────────────

def write_entries(entries, out_path: str):
    """统一写出三列：key\tword\tfreq"""
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for key, word, freq in entries:
            f.write(f"{key}\t{word}\t{freq}\n")


# ── 文件路由 ──────────────────────────────────────────────────

def process_file(src_path: str, dst_dir: str):
    filename = os.path.basename(src_path)
    stem = filename[:-len(".txt")] if filename.endswith(".txt") else filename
    out_path = os.path.join(dst_dir, stem + ".txt")

    print(f"  {filename}  →  {stem}.txt", flush=True)

    raw = parse_tab4(src_path)
    if not raw:
        print(f"    ⚠ 无有效行，跳过。")
        return

    entries = []
    for key, word, freq in raw:
        # 中文词：key 是拼音（含 ' 分隔），若缺失则用 pypinyin 补全
        if has_chinese(word):
            if not key or re.search(r"[^\x00-\x7f']", key):
                # key 含非 ASCII 说明不是拼音，重新生成
                key = hanzi_to_pinyin(word)
            key = key.lower()
        else:
            # 英文词：key 取纯字母小写
            key = re.sub(r"[^a-z0-9]", "", key.lower()) or re.sub(r"[^a-z0-9]", "", word.lower())
        if key:
            entries.append((key, word, freq))

    deduped = dedup(entries)
    # 按 key 升序排列，方便 build_dict.py 二分查找
    deduped.sort(key=lambda e: e[0])
    write_entries(deduped, out_path)
    print(f"    → {len(deduped)} 条", flush=True)


# ── 主入口 ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="久以输入法词库统一格式转换工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 在仓库根目录，转换全部文件到 output/ 目录
  python convert_dicts.py . ./output

输出格式（UTF-8 无 BOM，Tab 分隔三列）：
  中文 / 中英混合：  拼音    词    词频
  英文：             字母串  词    词频

T9 编码列已删除，由 build_dict.py 打包时实时计算。
""",
    )
    ap.add_argument("src_dir", help="词库源目录（仓库根目录）")
    ap.add_argument("dst_dir", help="转换结果输出目录")
    args = ap.parse_args()

    if not os.path.isdir(args.src_dir):
        print(f"错误：源目录不存在：{args.src_dir}")
        sys.exit(1)

    os.makedirs(args.dst_dir, exist_ok=True)

    # 只处理词库 .txt 文件，排除脚本自身和 output 子目录的文件
    SKIP = {"convert_dicts.py", "dedup_output.py", "build_dict.py", "run_all.sh"}
    all_files = sorted(
        f for f in os.listdir(args.src_dir)
        if f.endswith(".txt")
        and not f.startswith(".")
        and f not in SKIP
    )

    if not all_files:
        print("未找到任何 .txt 文件。")
        sys.exit(0)

    print(f"共 {len(all_files)} 个文件，开始转换...\n")
    ok = fail = 0

    for fname in all_files:
        src = os.path.join(args.src_dir, fname)
        try:
            process_file(src, args.dst_dir)
            ok += 1
        except Exception as e:
            import traceback
            print(f"  ❌ {fname} 出错：{e}")
            traceback.print_exc()
            fail += 1

    print(f"\n✅ 完成。成功 {ok} 个，失败 {fail} 个。")
    print(f"输出目录：{os.path.abspath(args.dst_dir)}")
