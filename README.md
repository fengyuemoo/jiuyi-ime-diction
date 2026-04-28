# jiuyi-ime-diction

久以输入法词库文件仓库，包含所有转换后的统一格式词库文本及打包脚本。

## 词库文件格式

所有词库文件均为 **UTF-8 无 BOM、Tab 分隔四列**：

| 列 | 中文 / 中英混合 | 英文 |
|---|---|---|
| 第1列 | 拼音（音节间用 `'` 分隔） | 小写字母串 |
| 第2列 | T9 编码 | T9 编码 |
| 第3列 | 汉字或词 | 词（可含空格） |
| 第4列 | 词频 | 词频 |

示例：
```
ni'hao	6442566	你好	523901
zhong'guo	946464486	中国	998000
hello	43556	hello	5000000
```

## 词库文件列表

| 文件 | 语言 | 内容 |
|---|---|---|
| `en_base.txt` | en | 英文基础词库 |
| `en_ext.txt` | en | 英文扩展词库（专有名词、缩写词等） |
| `en_ext_1.txt` | en | 英文补充扩展词库 |
| `en.txt` | en | 英文通用词库 |
| `cn_8105.txt` | zh | 中文国标 8105 单字 |
| `cn_base.txt` | zh | 中文主干词库 |
| `cn_ext.txt` | zh | 中文扩展词库 |
| `cn_en.txt` | zh | 中英混合词库 |
| `cn_internet_hot_words.txt` | zh | 互联网热词 |
| `cn_others.txt` | zh | 多音字纠错词条 |
| `cn_41448.txt` | zh | 中文 41448 字词库 |
| `cn_thuocl_animal.txt` | zh | THUOCL 动物词库 |
| `cn_thuocl_car.txt` | zh | THUOCL 车辆词库 |
| `cn_thuocl_finance.txt` | zh | THUOCL 金融词库 |
| `cn_thuocl_food.txt` | zh | THUOCL 食物词库 |
| `cn_thuocl_history.txt` | zh | THUOCL 历史词库 |
| `cn_thuocl_idiom.txt` | zh | THUOCL 成语词库 |
| `cn_thuocl_it.txt` | zh | THUOCL IT 词库 |
| `cn_thuocl_law.txt` | zh | THUOCL 法律词库 |
| `cn_thuocl_medical.txt` | zh | THUOCL 医学词库 |
| `cn_thuocl_place.txt` | zh | THUOCL 地名词库 |
| `cn_thuocl_poem.txt` | zh | THUOCL 诗词词库 |

## 词库转换与去重（从原始源文件重新生成时使用）

若需要从原始 `.dict.yaml` / 原始 `.txt` 源文件重新生成统一格式词库，按以下顺序执行：

### 第一步：转换格式

```bash
# 安装依赖
pip install pypinyin

# 将源目录（.）下所有词库转换，输出到 ./output
python convert_dicts.py . ./output
```

### 第二步：跨文件全局去重

```bash
# 对 output 目录中所有文件做全局去重，直接覆盖写回
python dedup_output.py ./output
```

去重策略：以「拼音 + 词」为唯一键，全局只保留词频最高的条目；词频相同时按文件优先级决定归属，文件结构不变。

### 第三步：将去重后文件移至根目录

```bash
mv output/*.txt .
rmdir output
```

### 验证去重结果

```bash
cd <词库根目录>
# 中文跨文件重复检查（结果应为 0）
cat cn_8105.txt cn_41448.txt cn_base.txt cn_ext.txt \
    cn_internet_hot_words.txt cn_others.txt \
    cn_thuocl_animal.txt cn_thuocl_car.txt cn_thuocl_finance.txt \
    cn_thuocl_food.txt cn_thuocl_history.txt cn_thuocl_idiom.txt \
    cn_thuocl_it.txt cn_thuocl_law.txt cn_thuocl_medical.txt \
    cn_thuocl_place.txt cn_thuocl_poem.txt cn_en.txt \
    | awk -F'\t' '{print $1"\t"$3}' | sort | uniq -d | wc -l

# 英文跨文件重复检查（结果应为 0）
cat en.txt en_base.txt en_ext.txt en_ext_1.txt \
    | awk -F'\t' '{print $1"\t"$3}' | sort | uniq -d | wc -l
```

## 打包为 dict.db

### 方式一：一键脚本（推荐）

```bash
chmod +x run_all.sh
./run_all.sh
```

输出文件：`dist/dict.db`

### 方式二：手动调用

```bash
python3 build_dict.py \
  --input cn_base.txt en_base.txt \
  --lang zh en \
  --output dist/dict.db
```

### 验证结果

```bash
python3 build_dict.py --verify dist/dict.db
```

## 将 dict.db 转移到输入法仓库

```bash
cp dist/dict.db …/jiuyi-ime-android/app/src/main/assets/dict.db
```
