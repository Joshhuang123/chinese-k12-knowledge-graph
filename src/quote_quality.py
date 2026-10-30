#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""教材原话的质量判据 —— 共用。

为什么要有这个：
  教材原话是从教材 PDF 的**文本层**抽出来的句子，OCR 会把句子**截断**：
    「成水华，一部分湖水变臭，鱼是难以」          ← 后面还有半句
    「人们利用苔藓植物的这个特点，把它当做监测空气」  ← 后面还有半句
    「使用刻度尺测量长度78910」                  ← 数字被读成了乱码
  学习页把它当「**教材原话**」原样展示，学生看到的就是半句话。

  项目在别处早就有同样的判断：
  · 讲解稿协议（docs/lesson-script-protocol.md）：「残骸就别引用 … 都没有就不写
    quote 这个字段（**页面会少一块，比引用错话好**）」
  · 学习卡（src/build_learn_cards.py）：教材原文段落「汉字密度 ≥35%」，
    不合格的直接丢掉
  学习页以前**没有这道门** —— 于是它成了整条链上唯一会把残骸端给学生的地方。

判据（都是**硬信号**，不是猜测）：
  ① 长度 8–70 字 —— 短的像目录条目，长的像整页复制 / 段落粘连
     （人教引文来自 PDF 文本层，5,530 条里 5,427 条本来就 ≤60 字，
       这个上限对它零成本；沪教引文来自 tesseract，超过 60 字的
       基本上是「几个段落被粘连在一起」的长句）
  ② **必须以句末标点收尾**（。．！？ 或收尾括号/引号）——
     截断的句子收不了尾，这是最有效的一条
  ③ 不能以标点/数字/题号开头（"(2)制作临时装片…" / "、的…"）
  ④ 结尾不能带省略号（说明后面还有）
  ⑤ 汉字密度 ≥ 50%（"使用刻度尺测量长度78910" 这类混着乱码数字的挡掉）
  ⑥ 不含私用区字符（U+E000–U+F8FF，OCR 残骸的常见产物）
  ⑦ 不含「汉字 + 单个大写字母」（"昌Ra" 这种把汉字读坏了的）
  ⑧ 不能是图注（"图4-53 神经系统的组成和功能"）
"""
import re

# 句末标点：句号/问号/叹号/点，或收尾的括号引号
_TAIL_OK = re.compile(r'[。．\.！!？?）)」”"]$')
# 题号开头："(2)制作…" / "3. 某某…"
_NUM_HEAD = re.compile(r'^[（(]?\d+[）).、]')
# 不能开头的标点（上一句的尾巴接过来了）
_BAD_HEAD = set('）)】],.，。、：:；;\"“\'‘’')
# 汉字 + 单个大写字母（OCR 把汉字读坏）
_CJK_UPPER = re.compile(r'[一-鿿][A-Z]')
# 图注
_FIGCAP = re.compile(r'^图\s*\d')
# 私用区
_PUA = re.compile(r'[\ue000-\uf8ff]')


def cjk_ratio(t):
    t = (t or '').strip()
    if not t:
        return 0.0
    return sum(1 for c in t if '一' <= c <= '鿿') / len(t)


def quote_ok(t, min_len=8, max_len=70, min_cjk=0.5):
    """教材原话能不能端给学生看。"""
    t = (t or '').strip()
    if not t:
        return False, '空'
    if len(t) < min_len:
        return False, f'太短（{len(t)} 字）'
    if len(t) > max_len:
        return False, f'太长（{len(t)} 字）'
    if not _TAIL_OK.search(t):
        return False, '句子被截断（收不了尾）'
    if _NUM_HEAD.match(t):
        return False, '题号开头'
    if t[0] in _BAD_HEAD:
        return False, '标点开头（上一句的尾巴）'
    if '…' in t[-3:]:
        return False, '结尾有省略号'
    if cjk_ratio(t) < min_cjk:
        return False, f'汉字密度低（{cjk_ratio(t):.0%}）'
    if _PUA.search(t):
        return False, '含私用区字符（OCR 残骸）'
    if _CJK_UPPER.search(t):
        return False, '汉字里夹着大写字母（OCR 残骸）'
    if _FIGCAP.match(t):
        return False, '是图注不是正文'
    return True, ''


def filter_quotes(reads, **kw):
    """筛掉不合格的原话，返回 (留下的, 被剔掉的[(原文, 原因)])。"""
    keep, dropped = [], []
    for r in reads or []:
        ok, why = quote_ok(r.get('t') or '', **kw)
        if ok:
            keep.append(r)
        else:
            dropped.append((r.get('t') or '', why))
    return keep, dropped


if __name__ == '__main__':
    import sys
    for t in sys.argv[1:]:
        print(quote_ok(t), '|', t[:50])
