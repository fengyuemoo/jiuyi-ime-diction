#!/usr/bin/env python3
"""
build_dict.py — 久以输入法词库构建脚本

将一个或多个词库文本文件导入 SQLite 数据库，供 Android App 使用。

词库文件格式（Tab 分隔四列）：
  中文：  拼音  T9编码  汉字/词  词频
  英文：  字母串  T9编码  词  词频

  中文示例：  ni'hao\t6442566\t你好\t523901
  英文示例：  hello\t43556\thello\t5000000

主键设计：(word, pinyin) 复合主键。
  - 英文词：pinyin = ""，每个 word 唯一。
  - 中文词：多音字每个读音独立一行（不合并！）。

initials 列（v5 新增）：
  中文词存储拼音的首字母序列，供简拼查询。
  "zhong'guo" → "zg"，"ni'hao" → "nh"。
  英文词 initials = ""。

用法示例：
  python build_dict.py --input en_base.txt --lang en --output dict.db
  python build_dict.py --input cn_base.txt en_base.txt --lang zh en --output dict.db
  python build_dict.py --verify dict.db

重要：建表 SQL 必须与 Room 生成的 schema 完全一致。
  参考 app/schemas/com.jiuyi.ime.dictionary.DictionaryDatabase/5.json 中的 createSql。
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


def pinyin_to_initials(pinyin: str) -> str:
    """
    从拼音串提取首字母序列。
    "zhong'guo" -> "zg"
    "ni'hao"    -> "nh"
    "zhong"     -> "z"
    """
    if not pinyin:
        return ''
    syllables = [s.strip() for s in pinyin.split("'") if s.strip()]
    return ''.join(syl[0] for syl in syllables if syl)


def detect_encoding(filepath: str) -> str:
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS `words` (
            `word`     TEXT    NOT NULL,
            `freq`     INTEGER NOT NULL,
            `lang`     TEXT    NOT NULL,
            `t9_key`   TEXT    NOT NULL,
            `pinyin`   TEXT    NOT NULL,
            `initials` TEXT    NOT NULL,
            PRIMARY KEY(`word`, `pinyin`)
        )
    """)
    conn.commit()


def build_index(conn: sqlite3.Connection) -> None:
    print("[index] Building indices...")
    conn.execute("CREATE INDEX IF NOT EXISTS `index_words_word`     ON `words`(`word`)")
    conn.execute("CREATE INDEX IF NOT EXISTS `index_words_t9_key`   ON `words`(`t9_key`)")
    conn.execute("CREATE INDEX IF NOT EXISTS `index_words_pinyin`   ON `words`(`pinyin`)")
    conn.execute("CREATE INDEX IF NOT EXISTS `index_words_initials` ON `words`(`initials`)")
    conn.commit()
    print("[index] Done.")


def parse_line(line: str, lang: str = 'en'):
    """
    解析一行词库条目，返回 (word, freq, pinyin) 或 None。

    支持格式（按优先级处理）：
      1. Tab 分隔四列（新统一格式）：
           中文：  拼音  T9  词  词频
           英文：  字母  T9  词  词频
      2. Tab 分隔两列：  词  词频
      3. CSV 格式：         词,词频
    """
    line = line.strip().lstrip('\ufeff')
    if not line or line.startswith('#'):
        return None

    if '\t' in line:
        parts = line.split('\t')
        if len(parts) >= 4:
            # Tab 分隔四列：拼音/字母  T9  词  词频
            pinyin_or_letters = parts[0].strip()
            word = parts[2].strip()
            try:
                freq = int(parts[3].strip())
            except ValueError:
                freq = 0
            # 用 lang 参数判断：zh 存拼音，en 留空（t9_key 直接由 word 计算）
            pinyin = pinyin_or_letters if lang == 'zh' else ''
        else:
            # Tab 分隔两列：词  词频
            word = parts[0].strip()
            try:
                freq = int(parts[1].strip())
            except (ValueError, IndexError):
                freq = 0
            pinyin = ''
        if not word or len(word) > MAX_WORD_LEN:
            return None
        return (word, freq, pinyin)

    if ',' in line:
        parts = line.split(',', 1)
        word = parts[0].strip()
        try:
            freq = int(float(parts[1].strip()))
        except (ValueError, IndexError):
            freq = 0
        if not word or len(word) > MAX_WORD_LEN:
            return None
        return (word, freq, '')

    # 单列
    word = line.strip()
    if not word or len(word) > MAX_WORD_LEN:
        return None
    return (word, 0, '')


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
            "INSERT OR REPLACE INTO `words`"
            "(`word`, `freq`, `lang`, `t9_key`, `pinyin`, `initials`) VALUES(?, ?, ?, ?, ?, ?)",
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
            result = parse_line(line, lang)
            if result is None:
                continue
            word, freq, pinyin = result
            t9       = word_to_t9(word)           if lang == 'en' else ''
            initials = pinyin_to_initials(pinyin) if lang == 'zh' else ''
            batch.append((word, freq, lang, t9, pinyin, initials))
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
        "SELECT word, freq, lang, t9_key, pinyin, initials FROM words ORDER BY freq DESC LIMIT 5"
    ).fetchall()
    print("[verify] top-5 by freq:")
    for row in sample:
        print(f"         {row[0]} (freq={row[1]}, lang={row[2]}, t9={row[3]}, pinyin={row[4]}, initials={row[5]})")
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
        print(f"[info] {empty_pinyin:,} Chinese words have empty pinyin (CJK ext. rare chars — expected)")
    else:
        print("[verify] All Chinese words have pinyin. OK")
    empty_initials = conn.execute(
        "SELECT COUNT(*) FROM words WHERE lang='zh' AND initials=''"
    ).fetchone()[0]
    if empty_initials > 0:
        print(f"[info] {empty_initials:,} Chinese words have empty initials (CJK ext. rare chars — expected)")
    else:
        print("[verify] All Chinese words have initials. OK")
    polyphone_count = conn.execute(
        "SELECT COUNT(*) FROM (SELECT word FROM words WHERE lang='zh' GROUP BY word HAVING COUNT(*)>1)"
    ).fetchone()[0]
    print(f"[verify] Polyphone chars/words : {polyphone_count:,}")
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
