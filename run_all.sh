#!/usr/bin/env bash
# run_all.sh — 一键将所有词库文件打包成 dict.db
#
# 用法：
#   chmod +x run_all.sh
#   ./run_all.sh
#
# 输出： dist/dict.db
# 运行完成后把 dist/dict.db 拷贝到：
#   jiuyi-ime-android/app/src/main/assets/dict.db

set -euo pipefail

OUTPUT="dist/dict.db"
mkdir -p dist

# 如果没有 tqdm 就安装（可选）
pip install tqdm -q 2>/dev/null || true

python3 build_dict.py \
  --input \
    en_base.txt \
    en_ext.txt \
    cn_base_chars_8105.txt \
    cn_base_main.txt \
    cn_base_phrases.txt \
    cn_en_mixed.txt \
    cn_ext.txt \
    cn_internet_hot_words.txt \
    cn_others.txt \
    cn_thuocl_animal.txt \
    cn_thuocl_car.txt \
    cn_thuocl_finance.txt \
    cn_thuocl_food.txt \
    cn_thuocl_history.txt \
    cn_thuocl_idiom.txt \
    cn_thuocl_it.txt \
    cn_thuocl_law.txt \
    cn_thuocl_medical.txt \
    cn_thuocl_place.txt \
    cn_thuocl_poem.txt \
  --lang \
    en \
    en \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
    zh \
  --output "$OUTPUT"

echo ""
echo "===== 验证 ====="
python3 build_dict.py --verify "$OUTPUT"

echo ""
echo "✓ 完成！输出文件：$OUTPUT"
echo "接下来把它拷贝到久以输入法仓库："
echo "  app/src/main/assets/dict.db"
