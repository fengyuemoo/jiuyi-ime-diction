#!/usr/bin/env python3
"""
build_dict.py — 久以输入法词库构建脚本

将一个或多个词库文本文件导入 SQLite 数据库，供 Android App 使用。

支持的输入格式（自动按列数判断）：
  4列（空格分隔）: <拼音键序> <数字编码> <候选词> <词频>   ← 英文词库
  3列（空格分隔）: <拼音串>   <汉字/词>  <词频>           ← 中文词库（pinyin 列存入 DB）
  2列（tab/空格）: <词>        <词频>                     ← 通用简易格式
  1列            : <词>                                  ← 纴词列表，词频默认 0
  CSV            : <词>,<词频>

用法示例：
  python build_dict.py --input en_ext.txt --lang en --output dict.db
  python build_dict.py --input en_ext.txt cn_base.txt --lang en zh --output dict.db
  python build_dict.py --verify dict.db

重要：建表 SQL 必须与 Room 生成的 schema 完全一致。
  参考 app/schemas/com.jiuyi.ime.dictionary.DictionaryDatabase/3.json 中的 createSql。
  不得加 DEFAULT 値，word 列必须有 NOT NULL。
"""

import argparse
import sqlite3
import sys
from pathlib import Path

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


BATCH_SIZE   = 50_000
MAX_WORD_LEN = 100

# T9 键位映射表
T9_MAP = {
    'a': '2', 'b': '2', 'c': '2',
    'd': '3', 'e': '3', 'f': '3',
    'g': '4', 'h': '4', 'i': '4',
    'j': '5', 'k': '5', 'l': '5',
    'm': '6', 'n': '6', 'o': '6',
    'p': '7', 'q': '7', 'r': '7', 's': '7',
    't': '8', 'u': '8', 'v': '8',
    'w': '9', 'x': '9', 'y': '9', 'z': '9',
}


def word_to_t9(word: str) -> str:
    """'hello' -> '43556'，非字母字符保留原字符。"""
    return ''.join(T9_MAP.get(ch, ch) for ch in word.lower())


def detect_encoding(filepath: str) -> str:
    """
    检测文件编码。只看 BOM，不依赖外部库。
    - UTF-16 LE BOM (FF FE) → 'utf-16'
    - UTF-16 BE BOM (FE FF) → 'utf-16'
    - UTF-8 BOM (EF BB BF)  → 'utf-8-sig'
    - 其他            → 'utf-8'
    """
    with open(filepath, 'rb') as f:
        bom = f.read(4)
    if bom[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return 'utf-16'
    if bom[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    return 'utf-8'


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    # 建表 SQL 必须与 Room schema v3 的 createSql 字段完全一致：
    #   - word 必须 NOT NULL
    #   - freq / lang / t9_key / pinyin 不得有 DEFAULT 子句
    #   - PRIMARY KEY 写在列尾，不单独建 PRIMARY KEY 语句
    conn.execute("""
        CREATE TABLE IF NOT EXISTS `words` (
            `word`   TEXT    NOT NULL,
            `freq`   INTEGER NOT NULL,
            `lang`   TEXT    NOT NULL,
            `t9_key` TEXT    NOT NULL,
            `pinyin` TEXT    NOT NULL,
            PRIMARY KEY(`word`)
        )
    """)
    conn.commit()


def build_index(conn: sqlite3.Connection) -> None:
    print("[index] Building indices...")
    conn.execute("CREATE INDEX IF NOT EXISTS `index_words_word`   ON `words`(`word`)")
    conn.execute("CREATE INDEX IF NOT EXISTS `index_words_t9_key` ON `words`(`t9_key`)")
    conn.execute("CREATE INDEX IF NOT EXISTS `index_words_pinyin` ON `words`(`pinyin`)")
    conn.commit()
    print("[index] Done.")


def parse_line(line: str):
    """
    返回 (word, freq, pinyin) 元组，或 None。
    - 3列中文词库：pinyin = parts[0]（如 "zhong'guo"）
    - 其他格式：pinyin = ''
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
        return (word, freq, '')

    if '\t' in line:
        parts = line.split('\t', 1)
        word = parts[0].strip()
        try:
            freq = int(float(parts[1].strip()))
        except (ValueError, IndexError):
            freq = 0
        if not word or len(word) > MAX_WORD_LEN:
            return None
        return (word, freq, '')

    parts = [p for p in line.split(' ') if p]
    n = len(parts)

    if n >= 4:
        # 英文词库 4列：拼音键序 数字编码 候选词 词频
        try:
            freq = int(parts[-1])
        except ValueError:
            freq = 0
        word = ' '.join(parts[2:-1])
        pinyin = ''
    elif n == 3:
        # 中文词库 3列：拼音串 汉字/词 词频  ← 保存 pinyin
        pinyin = parts[0]
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
        pinyin = ''
    else:
        word = parts[0]
        freq = 0
        pinyin = ''

    if not word or len(word) > MAX_WORD_LEN:
        return None
    return (word, freq, pinyin)


def count_lines(filepath: str) -> int:
    enc = detect_encoding(filepath)
    count = 0
    with open(filepath, 'r', encoding=enc, errors='ignore') as f:
        for _ in f:
            count += 1
    return count


def import_file(conn: sqlite3.Connection, filepath: str, lang: str) -> int:
    path = Path(filepath)
    if not path.exists():
        print(f"[error] File not found: {filepath}", file=sys.stderr)
        return 0

    enc = detect_encoding(filepath)
    total_lines = count_lines(filepath)
    print(f"[import] {path.name} ({total_lines:,} lines, lang={lang}, enc={enc})")

    batch   = []
    success = 0

    def flush():
        nonlocal success
        conn.executemany(
            "INSERT OR REPLACE INTO `words`(`word`, `freq`, `lang`, `t9_key`, `pinyin`) VALUES(?, ?, ?, ?, ?)",
            batch
        )
        conn.commit()
        success += len(batch)
        batch.clear()

    iter_lines = open(filepath, 'r', encoding=enc, errors='ignore')
    if HAS_TQDM:
        iter_lines = tqdm(iter_lines, total=total_lines, unit='lines', desc=path.name)

    try:
        for line in iter_lines:
            result = parse_line(line)
            if result is None:
                continue
            word, freq, pinyin = result
            t9 = word_to_t9(word) if lang == 'en' else ''
            batch.append((word, freq, lang, t9, pinyin))
            if len(batch) >= BATCH_SIZE:
                flush()
    finally:
        if hasattr(iter_lines, 'close'):
            iter_lines.close()

    if batch:
        flush()

    print(f"[import] {path.name}: {success:,} rows inserted/updated.")
    return success


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
        "SELECT word, freq, lang, t9_key, pinyin FROM words ORDER BY freq DESC LIMIT 5"
    ).fetchall()
    print("[verify] top-5 by freq:")
    for row in sample:
        print(f"         {row[0]} (freq={row[1]}, lang={row[2]}, t9={row[3]}, pinyin={row[4]})")
    empty_t9 = conn.execute(
        "SELECT COUNT(*) FROM words WHERE lang='en' AND t9_key=''"
    ).fetchone()[0]
    if empty_t9 > 0:
        print(f"[warn] {empty_t9:,} English words have empty t9_key!")
    else:
        print("[verify] All English words have t9_key. OK")
    empty_pinyin = conn.execute(
        "SELECT COUNT(*) FROM words WHERE lang='zh' AND pinyin=''"
    ).fetchone()[0]
    if empty_pinyin > 0:
        print(f"[warn] {empty_pinyin:,} Chinese words have empty pinyin!")
    else:
        print("[verify] All Chinese words have pinyin. OK")
    conn.close()


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
