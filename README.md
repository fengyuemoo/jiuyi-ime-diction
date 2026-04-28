# jiuyi-ime-diction

久以输入法词库文件仓库，包含所有原始词库文本及打包脚本。

## 词库文件

| 文件 | 语言 | 内容 |
|---|---|---|
| `en_base.txt` | en | 英文基础词库 |
| `en_ext.txt` | en | 英文扩展词库（专有名词、缩写词等） |
| `cn_base_chars_8105.txt` | zh | 中文國标 8105 单字 |
| `cn_base_main.txt` | zh | 中文主干词库 |
| `cn_base_phrases.txt` | zh | 中文常用短语 |
| `cn_en_mixed.txt` | zh | 中英混入词 |
| `cn_ext.txt` | zh | 中文扩展词库 |
| `cn_internet_hot_words.txt` | zh | 互联网热词 |
| `cn_others.txt` | zh | 多音字纠错词条 |
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

## 打包为 dict.db

### 方式一：一键脚本（推荐）

```bash
# 在 Codespaces 或本地终端中执行
chmod +x run_all.sh
./run_all.sh
```

输出文件：`dist/dict.db`

### 方式二：手动调用

```bash
python3 build_dict.py \
  --input en_base.txt en_ext.txt \
  --lang en en \
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

## 词库文件格式说明

脚本自动按列数判断格式：

| 列数 | 分隔符 | 列含义 | 应用文件 |
|---|---|---|---|
| 4 | 空格 | `拼音键序` `数字编码` `候选词` `词频` | `en_*.txt` |
| 3 | 空格 | `拼音串` `汉字/词` `词频` | `cn_*.txt` |
| 2 | tab/空格 | `词` `词频` | 通用 |
| 1 | — | `词` | 纯词列表 |

注：4列英文词库中候选词本身可含空格（如 `Apple Vision Pro`），脚本将自动合并中间列。
