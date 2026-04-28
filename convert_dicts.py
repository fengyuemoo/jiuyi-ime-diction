#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jiuyi-ime-diction 词库统一格式转换脚本
目标格式（Tab 分隔四列，UTF-8 无 BOM）：
  中文 / 中英混合：  拼音    T9编码  汉字或词  词频
  英文：             字母    T9编码  词        词频

用法：
  python convert_dicts.py <词库源目录> <输出目录>

依赖：
  pip install pypinyin

输出文件名规则：
  xxx.dict.yaml  →  xxx.txt
  xxx.txt        →  xxx.txt（同名覆盖到输出目录）
"""

import os
import re
import sys

try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    print("请先安装 pypinyin：pip install pypinyin")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
# T9 映射
# ──────────────────────────────────────────────────────────
_T9_TABLE = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz",
    "22233344455566677778889999"
)

def to_t9(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower()).translate(_T9_TABLE)

def pinyin_to_t9(pinyin_str: str) -> str:
    return to_t9(pinyin_str.replace("'", ""))

# ──────────────────────────────────────────────────────────
# pypinyin：汉字 → 拼音（撇号分隔多音节）
# ──────────────────────────────────────────────────────────
def hanzi_to_pinyin(word: str) -> str:
    syllables = lazy_pinyin(word, style=Style.NORMAL, errors="ignore")
    syllables = [s for s in syllables if s]
    if not syllables:
        return ""
    return syllables[0] if len(syllables) == 1 else "'".join(syllables)

# ──────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────
def has_chinese(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", s))

def skip_header(lines):
    """剥除 YAML 头部（--- ... 之间）和 # 注释行"""
    in_yaml = False
    for line in lines:
        s = line.rstrip("\n\r")
        if s.strip() == "---":
            in_yaml = True
            continue
        if in_yaml:
            if s.strip() == "...":
                in_yaml = False
            continue
        if s.lstrip().startswith("#"):
            continue
        yield s

# ──────────────────────────────────────────────────────────
# 解析器
# 统一返回 [(word, col2, freq_or_None), ...]
# col2 含义：中文=拼音, 英文=字母串
# ──────────────────────────────────────────────────────────

def parse_dict_yaml(path: str):
    """
    标准 Rime .dict.yaml 数据行：
      word\tpinyin\tfreq   ← 三列（中文有拼音）
      word\tfreq           ← 两列纯数字（无拼音）
      word\tpinyin         ← 两列字母（无词频）
    """
    results = []
    with open(path, encoding="utf-8") as f:
        for line in skip_header(f):
            if not line.strip():
                continue
            parts = line.split("\t")
            word = parts[0].strip()
            if not word:
                continue

            if len(parts) >= 3:
                second = parts[1].strip()
                third  = parts[2].strip()
                if re.match(r"^[a-zü ]+$", second, re.IGNORECASE):
                    pinyin = second.replace(" ", "'").lower()
                    try:
                        freq = int(third)
                    except ValueError:
                        freq = None
                else:
                    try:
                        freq = int(second)
                    except ValueError:
                        freq = None
                    pinyin = None
                results.append((word, pinyin, freq))

            elif len(parts) == 2:
                second = parts[1].strip()
                if re.match(r"^[a-zü ]+$", second, re.IGNORECASE):
                    results.append((word, second.replace(" ", "'").lower(), None))
                else:
                    try:
                        freq = int(second)
                    except ValueError:
                        freq = None
                    results.append((word, None, freq))
            else:
                results.append((word, None, None))
    return results

def parse_thuocl_txt(path: str):
    """
    cn_thuocl_*.txt / cn_internet_hot_words.txt
    实际格式（空格分隔三列）：
      拼音(撇号分隔音节)  汉字  词频
    例：a'ba'cang'zhu 阿坝藏猪 0
    """
    results = []
    with open(path, encoding="utf-8") as f:
        for line in skip_header(f):
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ")
            if len(parts) >= 3:
                pinyin = parts[0].strip()
                word   = parts[1].strip()
                try:
                    freq = int(parts[2].strip())
                except ValueError:
                    freq = None
                results.append((word, pinyin, freq))
            elif len(parts) == 2:
                pinyin = parts[0].strip()
                word   = parts[1].strip()
                results.append((word, pinyin, None))
    return results

def parse_cn_en_txt(path: str):
    """
    cn_en.txt（Rime tabledb）
    格式：词\t拼音  （无词频，拼音可含空格分隔）
    """
    results = []
    with open(path, encoding="utf-8") as f:
        for line in skip_header(f):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                word   = parts[0].strip()
                pinyin = parts[1].strip()
                results.append((word, pinyin, None))
    return results

def parse_en_space_separated(path: str):
    """
    en_base.txt / en_ext.txt — 空格分隔四列
    格式：字母  T9编码  词  词频
    例：a 2 a 9081174698
        abs 227 ABS 500000
    注意：词本身可能含空格（如 "Ability Power Carry"），
    因此只拆前两列和最后一列，中间全部作为词。
    """
    results = []
    with open(path, encoding="utf-8") as f:
        for line in skip_header(f):
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ")
            if len(parts) >= 4:
                letters = parts[0].strip().lower()
                # parts[1] 是 T9，忽略（重新计算）
                # 最后一列是词频，中间是词（可含空格）
                try:
                    freq = int(parts[-1].strip())
                    word = " ".join(parts[2:-1]).strip()
                except ValueError:
                    freq = None
                    word = " ".join(parts[2:]).strip()
                if word:
                    results.append((word, letters, freq))
            elif len(parts) == 3:
                letters = parts[0].strip().lower()
                word    = parts[1].strip()
                try:
                    freq = int(parts[2].strip())
                except ValueError:
                    freq = None
                results.append((word, letters, freq))
    return results

def parse_en_dict_yaml(path: str):
    """
    en.dict.yaml / en_ext_1.dict.yaml 等英文 Rime 词库
    格式通常：word\tletters\tfreq 或 word\tfreq
    """
    results = []
    with open(path, encoding="utf-8") as f:
        for line in skip_header(f):
            if not line.strip():
                continue
            parts = line.split("\t")
            word = parts[0].strip()
            if not word:
                continue

            if len(parts) >= 3:
                second = parts[1].strip()
                third  = parts[2].strip()
                if re.match(r"^[a-z]+$", second, re.IGNORECASE):
                    letters = second.lower()
                    try:
                        freq = int(third)
                    except ValueError:
                        freq = None
                else:
                    letters = re.sub(r"[^a-z]", "", word.lower())
                    try:
                        freq = int(second)
                    except ValueError:
                        freq = None
                results.append((word, letters, freq))
            elif len(parts) == 2:
                second = parts[1].strip()
                letters = re.sub(r"[^a-z]", "", word.lower())
                try:
                    freq = int(second)
                except ValueError:
                    freq = None
                results.append((word, letters, freq))
            else:
                letters = re.sub(r"[^a-z]", "", word.lower())
                results.append((word, letters, None))
    return results

# ──────────────────────────────────────────────────────────
# 去重
# ──────────────────────────────────────────────────────────
def dedup(entries, key_func):
    """保留每个 key 下词频最大的；相同词频保留第一个出现的。"""
    best_freq  = {}
    best_entry = {}
    for entry in entries:
        k    = key_func(entry)
        freq = entry[2] if entry[2] is not None else 0
        if k not in best_freq or freq > best_freq[k]:
            best_freq[k]  = freq
            best_entry[k] = entry
    return list(best_entry.values())

def dedup_chinese(entries):
    return dedup(entries, lambda e: (e[0], e[1] or ""))

def dedup_english(entries):
    return dedup(entries, lambda e: (e[0], (e[1] or "").lower()))

# ──────────────────────────────────────────────────────────
# 写出
# ──────────────────────────────────────────────────────────
def write_chinese(entries, out_path: str):
    """拼音\tT9\t汉字\t词频"""
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for word, pinyin, freq in entries:
            if not pinyin:
                continue
            t9 = pinyin_to_t9(pinyin)
            f.write(f"{pinyin}\t{t9}\t{word}\t{freq}\n")

def write_english(entries, out_path: str):
    """字母(小写)\tT9\t词\t词频"""
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for word, letters, freq in entries:
            letters_lower = (letters or re.sub(r"[^a-z]", "", word.lower())).lower()
            t9 = to_t9(letters_lower)
            f.write(f"{letters_lower}\t{t9}\t{word}\t{freq}\n")

def write_cn_en(entries, out_path: str):
    """中英混合：含汉字→中文规则，否则→英文规则"""
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for word, col2, freq in entries:
            if has_chinese(word):
                pinyin = col2 or ""
                t9 = pinyin_to_t9(pinyin)
                f.write(f"{pinyin}\t{t9}\t{word}\t{freq}\n")
            else:
                letters = (col2 or re.sub(r"[^a-z0-9]", "", word.lower())).lower()
                t9 = to_t9(letters)
                f.write(f"{letters}\t{t9}\t{word}\t{freq}\n")

# ──────────────────────────────────────────────────────────
# 文件路由
# ──────────────────────────────────────────────────────────

NEED_PYPINYIN = {
    # cn_tencent.dict.yaml 已移除
}

CN_EN_FILES = {
    "cn_en.txt",
}

EN_SPACE_SEPARATED = {
    "en_base.txt",
    "en_ext.txt",
}

EN_DICT_YAML = {
    "en.dict.yaml",
    "en_ext_1.dict.yaml",
}

THUOCL_RE = re.compile(r"^cn_thuocl_.+\.txt$|^cn_internet_hot_words\.txt$")


def process_file(src_path: str, dst_dir: str):
    filename = os.path.basename(src_path)

    if filename.endswith(".dict.yaml"):
        stem = filename[: -len(".dict.yaml")]
    elif filename.endswith(".txt"):
        stem = filename[: -len(".txt")]
    else:
        stem = filename
    out_path = os.path.join(dst_dir, stem + ".txt")

    print(f"  {filename}  →  {stem}.txt", flush=True)

    if filename in CN_EN_FILES:
        raw = parse_cn_en_txt(src_path)
        entries = []
        for w, p, f in raw:
            freq = f if f is not None else 1
            if has_chinese(w):
                p = (p or "").replace(" ", "'") or hanzi_to_pinyin(w)
            else:
                p = (p or re.sub(r"[^a-z0-9]", "", w.lower())).lower()
            entries.append((w, p, freq))
        deduped = dedup_chinese(entries)
        write_cn_en(deduped, out_path)

    elif filename in EN_SPACE_SEPARATED:
        raw = parse_en_space_separated(src_path)
        entries = [(w, l, f if f is not None else 1) for w, l, f in raw]
        deduped = dedup_english(entries)
        write_english(deduped, out_path)

    elif filename in EN_DICT_YAML:
        raw = parse_en_dict_yaml(src_path)
        entries = [(w, l, f if f is not None else 1) for w, l, f in raw]
        deduped = dedup_english(entries)
        write_english(deduped, out_path)

    elif filename in NEED_PYPINYIN:
        raw = parse_dict_yaml(src_path)
        entries = []
        for w, p, f in raw:
            if not p:
                p = hanzi_to_pinyin(w)
            freq = f if f is not None else 1
            entries.append((w, p, freq))
        deduped = dedup_chinese(entries)
        write_chinese(deduped, out_path)

    elif THUOCL_RE.match(filename):
        raw = parse_thuocl_txt(src_path)
        entries = []
        for w, p, f in raw:
            if not p:
                p = hanzi_to_pinyin(w)
            freq = f if f is not None else 1
            entries.append((w, p, freq))
        deduped = dedup_chinese(entries)
        write_chinese(deduped, out_path)

    elif filename.endswith(".dict.yaml"):
        raw = parse_dict_yaml(src_path)
        entries = []
        for w, p, f in raw:
            if not p:
                p = hanzi_to_pinyin(w)
            freq = f if f is not None else 1
            entries.append((w, p, freq))
        deduped = dedup_chinese(entries)
        write_chinese(deduped, out_path)

    else:
        print(f"    ⚠ 未识别格式，跳过。")


# ──────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="久以输入法词库统一格式转换工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 在仓库根目录，转换全部文件到 output/ 目录
  python convert_dicts.py . ./output

输出格式（UTF-8 无 BOM，Tab 分隔四列）：
  中文 / 中英混合：  拼音    T9编码  汉字或词  词频
  英文：             字母    T9编码  词        词频
""",
    )
    ap.add_argument("src_dir", help="词库源目录（仓库根目录）")
    ap.add_argument("dst_dir", help="转换结果输出目录")
    args = ap.parse_args()

    if not os.path.isdir(args.src_dir):
        print(f"错误：源目录不存在：{args.src_dir}")
        sys.exit(1)

    os.makedirs(args.dst_dir, exist_ok=True)

    all_files = sorted(
        f for f in os.listdir(args.src_dir)
        if (f.endswith(".dict.yaml") or f.endswith(".txt"))
        and not f.startswith(".")
        and f != "convert_dicts.py"
    )

    if not all_files:
        print("未找到任何 .dict.yaml 或 .txt 文件。")
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
