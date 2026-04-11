#!/usr/bin/env python3
"""
build_dict.py — 久以输入法词库构建脚本

将一个或多个词库文本文件导入 SQLite 数据库，供 Android App 使用。

支持的输入格式（自动按列数判断）：
  4列（空格分隔）: <拼音键序> <数字编码> <候选词> <词频>   ← 英文词库
  3列（空格分隔）: <拼音串>   <汉字/词>  <词频>           ← 中文词库
  2列（tab/空格）: <词>        <词频>                     ← 通用简易格式
  1列            : <词>                                  ← 纯词列表，词频默认 0
  CSV            : <词>,<词频>

用法示例：
  python build_dict.py --input en_ext.txt --lang en --output dict.db
  python build_dict.py --input en_ext.txt cn_base.txt --lang en zh --output dict.db
  python build_dict.py --verify dict.db

注意：
  本脚本不写入 room_master_table / identity_hash。
  identity_hash 由 App 在首次启动时自动注入（见 DictionaryDatabase.kt）。
  因此本脚本可以在任意时间、任意环境独立运行，无需依赖 Android 编译产物。
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


# ── 常量 ────────────────────────────────────────────────────────────────
BATCH_SIZE   = 50_000
MAX_WORD_LEN = 100


# ── 数据库初始化 ─────────────────────────────────────────────────────────────
def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS words (
            word TEXT PRIMARY KEY,
            freq INTEGER NOT NULL DEFAULT 0,
            lang TEXT NOT NULL DEFAULT 'en'
        )
    """)
    # room_master_table 由 App 运行时写入，此处不创建
    conn.commit()


def build_index(conn: sqlite3.Connection) -> None:
    print("[index] Building index on 'word'...")
    # 索引名必须与 WordEntry.kt @Index 生成的名称一致：index_words_word
    conn.execute("CREATE INDEX IF NOT EXISTS index_words_word ON words(word)")
    conn.commit()
    print("[index] Done.")


# ── 词库文件解析 ─────────────────────────────────────────────────────────────
def parse_line(line: str):
    """
    解析单行，返回 (word, freq) 或 None（跳过）。
    """
    line = line.strip().lstrip('\ufeff')
    if not line or line.startswith('#'):
        return None

    if ',' in line and '\t' not in line:
        parts = line.split(',', 1)
        word = parts[0].strip()
        try:
            freq = int(float(parts[1].strip()))
        except (ValueError, IndexError):
            freq = 0
        if not word or len(word) > MAX_WORD_LEN:
            return None
        return (word, freq)

    if '\t' in line:
        parts = line.split('\t', 1)
        word = parts[0].strip()
        try:
            freq = int(float(parts[1].strip()))
        except (ValueError, IndexError):
            freq = 0
        if not word or len(word) > MAX_WORD_LEN:
            return None
        return (word, freq)

    parts = [p for p in line.split(' ') if p]
    n = len(parts)

    if n >= 4:
        try:
            freq = int(parts[-1])
        except ValueError:
            freq = 0
        word = ' '.join(parts[2:-1])
    elif n == 3:
        word = parts[1]
        try:
            freq = int(parts[2])
        except ValueError:
            freq = 0
    elif n == 2:
        word = parts[0]
        try:
            freq = int(parts[1])
        except ValueError:
            freq = 0
    else:
        word = parts[0]
        freq = 0

    if not word or len(word) > MAX_WORD_LEN:
        return None
    return (word, freq)


def count_lines(filepath: str) -> int:
    count = 0
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for _ in f:
            count += 1
    return count


def import_file(conn: sqlite3.Connection, filepath: str, lang: str) -> int:
    path = Path(filepath)
    if not path.exists():
        print(f"[error] File not found: {filepath}", file=sys.stderr)
        return 0

    total_lines = count_lines(filepath)
    print(f"[import] {path.name} ({total_lines:,} lines, lang={lang})")

    batch   = []
    success = 0

    def flush():
        nonlocal success
        conn.executemany(
            "INSERT OR REPLACE INTO words(word, freq, lang) VALUES(?, ?, ?)",
            batch
        )
        conn.commit()
        success += len(batch)
        batch.clear()

    iter_lines = open(filepath, 'r', encoding='utf-8', errors='ignore')
    if HAS_TQDM:
        iter_lines = tqdm(iter_lines, total=total_lines, unit='lines', desc=path.name)

    try:
        for line in iter_lines:
            result = parse_line(line)
            if result is None:
                continue
            word, freq = result
            batch.append((word, freq, lang))
            if len(batch) >= BATCH_SIZE:
                flush()
    finally:
        if hasattr(iter_lines, 'close'):
            iter_lines.close()

    if batch:
        flush()

    print(f"[import] {path.name}: {success:,} rows inserted/updated.")
    return success


# ── 验证模式 ────────────────────────────────────────────────────────────────
def verify_db(db_path: str) -> None:
    if not Path(db_path).exists():
        print(f"[error] File not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    print(f"[verify] total rows : {total:,}")
    for lang_row in conn.execute("SELECT lang, COUNT(*) FROM words GROUP BY lang"):
        print(f"[verify] {lang_row[0]:10s}  : {lang_row[1]:,}")
    sample = conn.execute(
        "SELECT word, freq, lang FROM words ORDER BY freq DESC LIMIT 5"
    ).fetchall()
    print("[verify] top-5 by freq:")
    for row in sample:
        print(f"         {row[0]} (freq={row[1]}, lang={row[2]})")
    # identity_hash 由 App 运行时写入，此处不验证
    conn.close()


# ── 主程序 ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="久以输入法词库构建工具")
    parser.add_argument('--input',  nargs='+', help='词库输入文件（支持多个）')
    parser.add_argument('--lang',   nargs='+', help='每个文件对应的语言标识（en / zh 等）')
    parser.add_argument('--output', default='dict.db', help='输出 .db 文件路径（默认 dict.db）')
    parser.add_argument('--verify', metavar='DB_PATH', help='验证已构建的 .db 文件')
    args = parser.parse_args()

    if args.verify:
        verify_db(args.verify)
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    langs = args.lang if args.lang else ['en'] * len(args.input)
    if len(langs) != len(args.input):
        print('[error] --lang 数量必须与 --input 文件数量一致', file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(out_path))
    init_db(conn)

    total_rows = 0
    for filepath, lang in zip(args.input, langs):
        total_rows += import_file(conn, filepath, lang)

    build_index(conn)
    conn.close()

    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\n[done] {total_rows:,} rows → {out_path} ({size_mb:.1f} MB)")
    if size_mb > 100:
        print("[warn] .db 超过 100MB，建议使用 Play Asset Delivery 分发。")


if __name__ == '__main__':
    main()
