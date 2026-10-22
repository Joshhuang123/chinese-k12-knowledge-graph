#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 LaTeX 公式转成**人看得懂的纯文本**。

为什么要转
----------
视觉层从教材扫描页里抽出的是 LaTeX：
    y = \\frac{1}{2}(x - 6)^2 + 3
这一串直接显示在页面上，老师和家长读不懂——
「\\frac{1}{2}」不是人话。而页面**不允许加载外部资源**
（Katex 带着字体文件几百 KB，还要引外链），所以不能引渲染库。

办法是在**构建期**转一次，转成人眼能扫的形态：
    y = ½(x - 6)² + 3

设计原则：**宁可保守，不要转错。**
转不了的（比如不认识的命令）就原样留着 —— 一个没转的 `\\alpha`
比一个转错的 `a` 好。

实现：**带组的扫描器**，不是正则。
正则 `\\\\frac\\{([^{}]*)\\}\\{([^{}]*)\\}` 匹配不了嵌套花括号：
    \\frac{-1 \\pm \\sqrt{5}}{2}      ← 分子里还有一层 {5}
第一版就栽在这上面，输出了 `frac-1 ± √(5)2` —— 「frac」裸奔出来了。

命令表是**照着真实数据配齐的**：
`data/concept-vision.jsonl` 里一共出现 62 种命令，逐个配过，
不是「碰到一个补一个」。
"""
from __future__ import annotations

import re

# ── 符号表：命令 → 符号 ────────────────────────────────────────────────
SINGLE = {
    # 希腊字母
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "theta": "θ", "lambda": "λ", "mu": "μ", "pi": "π", "rho": "ρ",
    "sigma": "σ", "tau": "τ", "phi": "φ", "omega": "ω",
    "Delta": "Δ", "Omega": "Ω", "Sigma": "Σ", "Phi": "Φ", "Theta": "Θ",
    # 运算符
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "ne": "≠", "neq": "≠", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥",
    "leqslant": "≤", "geqslant": "≥", "leqslant": "≤", "geqslant": "≥",
    "approx": "≈", "equiv": "≡", "propto": "∝", "sim": "∼", "simeq": "≃",
    "cong": "≅", "backsim": "∽", "odot": "⊙", "circ": "°", "degree": "°",
    "bigcirc": "⊙", "prime": "′", "dprime": "″", "backprime": "‵",
    # ── 沪教版实测补的一批 ──
    "in": "∈", "notin": "∉", "ni": "∋",
    "overrightarrow": "→", "overleftarrow": "←", "Longleftrightarrow": "⟺",
    "iff": "⟺", "implies": "⟹", "impliedby": "⟸",
    "langle": "⟨", "rangle": "⟩", "lvert": "|", "rvert": "|", "lVert": "‖",
    "rVert": "‖", "overgroup": "⟮", "overbracket": "⟦",
    "lg": "lg", "varnothing": "∅", "infty": "∞", "dotsm": "⋯",
    "ll": "≪", "gg": "≫", "preceq": "⪯", "succeq": "⪰",
    "vdash": "⊢", "dashv": "⊣", "models": "⊨", "therefore": "∴",
    "cup": "∪", "cap": "∩", "complement": "∁", "setminus": "∖",
    # ── 全库扫描补的一批 ──
    # 箭头
    "xrightarrow": "→", "xrightarrow": "→", "longrightarrow": "→",
    "Longrightarrow": "⇒", "Longleftarrow": "⇐", "longleftarrow": "←",
    "longleftrightarrow": "↔", "Uparrow": "⇑", "Downarrow": "⇓",
    "nRightarrow": "↛", "nLeftarrow": "⇍", "twoheadrightarrow": "↠",
    "hookrightarrow": "↪", "twoheadleftarrow": "⇜", "nearrow": "↗",
    "searrow": "↘", "swarrow": "↙", "nwarrow": "↖",
    # 逻辑 / 集合
    "forall": "∀", "exists": "∃", "nexists": "∄", "neg": "¬",
    "subset": "⊂", "supset": "⊃", "subseteq": "⊆", "supseteq": "⊇",
    "nsubseteq": "⊄", "propto2": "∝", "models2": "⊨",
    # 几何
    "Box": "□", "checkmark": "✓", "bot": "⊥", "top": "⊤",
    "bigstar": "★", "blacktriangle": "▲", "blacktriangledown": "▼",
    "blacklozenge": "◆", "lozenge": "◊", "bigcirc2": "⊙",
    "wideparen": "⌢", "frown": "⌢", "flat": "―",
    # 希腊字母
    "varphi": "φ", "chi": "χ", "eta": "η", "nu": "ν", "mu2": "μ",
    "varPhi": "Φ", "varOmega": "Ω", "varSigma": "Σ", "varepsilon": "ε",
    "vartheta": "ϑ", "varsigma": "ς", "varpi": "ϖ", "digamma": "ϝ",
    "textasciicircum": "^", "textquotesingle": "'", "textasciitilde": "~",
    "textbackslash": "\\", "textunderscore": "_", "textbar": "|",
    "because": "∵", "square": "□", "bullet": "•", "blacksquare": "■",
    "vartriangle": "△", "triangle": "△", "perp": "⊥", "parallel": "∥",
    "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮", "partial": "∂",
    "nabla": "∇", "pm": "±", "mp": "∓", "cdot": "·", "times": "×", "div": "÷",
    "therefore": "∴", "because": "∵", "square": "□", "star": "⋆",
    # 关系
    "rightarrow": "→", "to": "→", "leftarrow": "←", "Rightarrow": "⇒",
    "Leftarrow": "⇐", "leftrightarrow": "↔", "Leftrightarrow": "⇔",
    "longleftrightarrow": "⟺", "xrightleftharpoons": "⇄", "rightharpoonup": "⇀",
    "perp": "⊥", "parallel": "∥", "mid": "∣", "doteq": "≐",
    # 几何
    "angle": "∠", "triangle": "△", "squarecap": "⊓", "wedge": "∧", "vee": "∨",
    # 函数名：去掉反斜杠就是它自己
    "sin": "sin", "cos": "cos", "tan": "tan", "cot": "cot", "sec": "sec",
    "csc": "csc", "log": "log", "ln": "ln", "exp": "exp", "lim": "lim",
    "max": "max", "min": "min", "arcsin": "arcsin", "arccos": "arccos",
    "arctan": "arctan",
    # 省略号
    "cdots": "⋯", "ldots": "…", "dots": "…",
    "vdots": "⋮", "ddots": "⋱", "dotsb": "⋯",
}

# ── 重音表：命令 → 组合符号（加在被修饰的字符后面）────────────────────
ACCENT = {
    "overline": "\u0304",   # 组合抑扬符（x̄）
    "bar": "\u0304",
    "underline": "\u0332",  # 组合下划线（x̲）
    "widehat": "\u0302",    # 组合扬抑符（x̂）
    "hat": "\u0302",
    "widetilde": "\u0303",  # 组合波浪号（x̃）
    "tilde": "\u0303",
    "vec": "\u20d7",        # 组合箭头（x⃗）
    "dot": "\u0307",        # 组合点（ẋ）
    "ddot": "\u0308",       # 组合分音符（ẍ）
    "check": "\u030c",      # 组合勾（x̌）
    "breve": "\u0306",      # 组合 breve（x̆）
}

# ── 丢弃表：纯排版命令，连内容一起丢 ─────────────────────────────────
DROP_CMD = {"left", "right", "quad", "qquad", "hspace", "phantom",
            "mathrel", "displaystyle", "limits", "!", ",", ";", ":", " ",
            "hline",           # hline 是表格横线，纯排版（实测 16 次）
            "smash", "mkern", "mspace", "nobreak", "allowbreak",
            "nonumber", "notag", "phantom2",
            "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl",
            "Bigr", "pr", "pmod", "tfrac2",
            # ── 全库扫描补的一批：纯排版，丢掉 ──
            "Large", "large", "huge", "Huge", "Huge", "tiny",
            "scriptsize", "footnotesize", "small", "normalsize",
            "mskip", "kern", "middle", "arg", "colon", "textasciicircum",
            "textquoteright", "textquotesingle", "textasciitilde",
            "textbackslash", "textunderscore", "textbar", "textless",
            "textgreater", "textbraceleft", "textbraceright",
            "not", "cancel", "phantom3", "mathchoice", "linebreak"}

# ── 保留表：命令丢掉，组里的内容留着 ─────────────────────────────────
# **分两种**：文字类原样留（转了没意义），数学类要递归转。
RAW_CONTENT = {"text", "mathrm", "mathbf", "mathit", "operatorname", "textbf",
               "mathcal", "mathsf", "rm", "textnormal", "textit",
               "boxed"}         # boxed 是给公式加框，内容要留（实测 12 次）
CONVERT_CONTENT = {"overbrace", "underbrace", "overarc", "overparen",
                   # ── 沪教版实测补的排版类命令：丢掉命令，内容留下 ──
                   "boldsymbol", "mathnormal", "mathrel", "mathopen",
                   "mathclose", "mathpunct", "mathbin", "mathrm2"}
KEEP_CONTENT = RAW_CONTENT | CONVERT_CONTENT

# 环境名，成对丢弃
ENV_CMD = {"begin", "end"}

# 这些命令取**第二个**参数显示：\overset{上}{下} 显示的是「下」
SECOND_GROUP = {"overset", "stackrel", "underset", "enclose"}

SUP = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
       "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
       "n": "ⁿ", "i": "ⁱ", "a": "ᵃ", "b": "ᵇ", "c": "ᶜ",
       "x": "ˣ", "y": "ʸ", "z": "ᶻ", "+": "⁺", "-": "⁻",
       "(": "⁽", ")": "⁾"}
SUB = {"0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
       "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
       "n": "ₙ", "i": "ᵢ", "a": "ₐ", "e": "ₑ", "o": "ₒ",
       "x": "ₓ", "y": "ᵧ", "k": "ₖ", "+": "₊", "-": "₋",
       "(": "₍", ")": "₎"}

VULGAR = {("1", "2"): "½", ("1", "3"): "⅓", ("2", "3"): "⅔",
          ("1", "4"): "¼", ("3", "4"): "¾", ("1", "5"): "⅕",
          ("1", "6"): "⅙", ("1", "8"): "⅛", ("1", "10"): "⅒"}


def _read_group(s: str, i: int):
    """从 s[i] 读一个 {...} 组。返回 (内容, 下一个下标)。支持嵌套。"""
    if i >= len(s) or s[i] != "{":
        return None, i
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    return None, i


def _sup_sub(body: str, table: dict) -> str:
    return "".join(table.get(ch, ch) for ch in body)


def _read_script_arg(s: str, i: int):
    """读上下标的参数。**不只认花括号组**。

    `x_1` / `x^{10}` / `x_\\text{甲}` / `x_\\alpha` 四种形状都得认。
    只认 `{}` 的话，`x_\\text{甲}` 会把反斜杠当成下标字符，
    整段 `\\text{甲}` 就漏到页面上了。
    """
    if i >= len(s):
        return None, i
    if s[i] == "{":
        g, j = _read_group(s, i)
        return (g, j) if g is not None else (None, i)
    if s[i] == "\\":
        m = re.match(r"\\([A-Za-z]+)", s[i:])
        if m:
            name = m.group(1)
            j = i + m.end()
            if name in RAW_CONTENT:
                g, j2 = _read_group(s, j)
                if g is not None:
                    return g, j2
            if name in SINGLE:
                return SINGLE[name], j
            return "\\" + name, j
    return s[i], i + 1


def _frac_str(a: str, b: str) -> str:
    """分子/分母 → 分数写法。**只给复杂的那一边加括号**。"""
    v = VULGAR.get((a, b))
    if v:
        return v

    def simple(x):
        return len(x) <= 4 and " " not in x and not any(op in x for op in "+-")

    if simple(b):
        return (a if simple(a) else f"({a})") + "/" + b
    return f"({a})/({b})"


def _convert(s: str, depth: int = 0) -> str:
    """带组解析的 LaTeX → 纯文本。"""
    if not s or depth > 12:
        return s
    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\":
            # 命令。**不吞掉后面的空格** —— LaTeX 里空格是命令的终止符，
            # 吞掉它会让「a \ne 0」变成「a ≠0」，读起来黏在一起。
            m = re.match(r"\\([A-Za-z]+)", s[i:])
            if m:
                name = m.group(1)
                j = i + m.end()
                if name == "frac" or name == "dfrac" or name == "tfrac":
                    a, j2 = _read_group(s, j)
                    b, j3 = _read_group(s, j2 if a is not None else j)
                    if a is not None and b is not None:
                        out.append(_frac_str(_convert(a, depth + 1), _convert(b, depth + 1)))
                        i = j3
                        continue
                    out.append("\\frac")
                    i = j
                    continue
                if name == "sqrt":
                    j2 = j
                    root = ""
                    if j2 < n and s[j2] == "[":
                        k = s.find("]", j2)
                        if k != -1:
                            root = _sup_sub(s[j2 + 1:k], SUP)
                            j2 = k + 1
                    g, j3 = _read_group(s, j2)
                    if g is not None:
                        out.append(root + "√(" + _convert(g, depth + 1) + ")")
                        i = j3
                        continue
                    out.append("√")
                    i = j
                    continue
                if name in ACCENT:
                    # 加横线/上标的字符：\overline{x} → x̄
                    g, j2 = _read_group(s, j)
                    if g is not None:
                        body = _convert(g, depth + 1)
                        if body.strip():
                            out.append(body + ACCENT[name])
                        i = j2
                        continue
                    if j < n:
                        out.append(s[j] + ACCENT[name])
                        i = j + 1
                        continue
                if name in ENV_CMD:
                    # \begin{aligned} ... \end{aligned}：整个环境丢掉
                    g, j2 = _read_group(s, j)
                    if g is not None:
                        i = j2
                        continue
                if name in SECOND_GROUP:
                    g1, j2 = _read_group(s, j)
                    g2, j3 = _read_group(s, j2 if g1 is not None else j)
                    if g2 is not None:
                        out.append(_convert(g2, depth + 1))
                        i = j3
                        continue
                if name in RAW_CONTENT:
                    # 文字：原样留。转了没意义，还可能把中文搞坏
                    g, j2 = _read_group(s, j)
                    if g is not None:
                        out.append(g)
                        i = j2
                        continue
                    out.append(" ")
                    i = j
                    continue
                if name in CONVERT_CONTENT:
                    # 数学：递归转。\overbrace{a^m \cdot a^m} 里的
                    # \cdot 必须转掉，不然原样漏到页面上
                    g, j2 = _read_group(s, j)
                    if g is not None:
                        out.append(_convert(g, depth + 1))
                        i = j2
                        continue
                    out.append(" ")
                    i = j
                    continue
                if name in DROP_CMD:
                    i = j
                    continue
                if name in SINGLE:
                    out.append(SINGLE[name])
                    i = j
                    continue
                # 不认识的命令：**原样留着**（宁可没转，不要转错）
                out.append("\\" + name)
                if j < n and s[j] not in " \t":
                    out.append(" ")     # 留个空格，免得跟后面的字黏住
                i = j
                continue
            # 转义符号 \{ \} \\ \% \$ \& \_ \# \,
            m2 = re.match(r"\\([\\{}$%&_#, ;:!])", s[i:])
            if m2:
                c = m2.group(1)
                out.append({"\\": " ", "{": "{", "}": "}", "$": "", "%": "%",
                            "&": "＆", "_": "_", "#": "#", ",": " ",
                            " ": " ", ";": " ", ":": " ", "!": ""}.get(c, c))
                i += m2.end()
                continue
            out.append("\\")
            i += 1
            continue
        if ch == "{":
            g, j = _read_group(s, i)
            if g is not None:
                out.append(_convert(g, depth + 1))
                i = j
                continue
        if ch in "^_":
            arg, j2 = _read_script_arg(s, i + 1)
            if arg is not None:
                # **组里的内容要先递归转一遍**。
                # `a^{n\text{个}}` 这种形状，组里混着命令；
                # 不转的话 `\text` 的 t/e/x/t 会被当成上标字符，
                # 页面���就漏出 `\teˣt个` 这种东西。
                out.append(_sup_sub(_convert(arg, depth + 1), SUP if ch == "^" else SUB))
                i = j2
                continue
        if ch == "&":
            out.append("，")
            i += 1
            continue
        if ch == "$":
            # **裸的 `$` 是数学定界符**，丢掉。
            # 之前只处理了 `\$`（反斜杠转义），裸的走默认分支被原样抄下来，
            # 页面上就出现「$t/时$」这种半吊子 LaTeX。
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def to_plain(s: str) -> str:
    """LaTeX → 可读纯文本。转不了的部分原样留着。"""
    if not s:
        return s
    t = _convert(s)
    t = t.replace("{", "").replace("}", "")
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    t = re.sub(r"，\s*", "，", t)
    return t


# ── 自检 ──────────────────────────────────────────────────────────────
CASES = [
    ("y = \\frac{1}{2}x^2 - 6x + 21", "y = ½x² - 6x + 21"),
    ("y = \\frac{1}{2}(x - 6)^2 + 3", "y = ½(x - 6)² + 3"),
    ("y = a(x - h)^2 + k", "y = a(x - h)² + k"),
    ("x = -\\frac{b}{2a}", "x = -b/2a"),
    ("x = \\frac{-1 \\pm \\sqrt{5}}{2}", "x = (-1 ± √(5))/2"),
    ("\\frac{1}{2} + \\frac{1}{3}", "½ + ⅓"),
    ("\\sqrt{3}", "√(3)"),
    ("\\triangle ABC", "△ ABC"),
    ("a \\ne 0", "a ≠ 0"),
    ("\\text{时间} = \\frac{\\text{路程}}{\\text{速度}}", "时间 = 路程/速度"),
    ("2x + 3y \\le 8", "2x + 3y ≤ 8"),
    ("\\left( x + 1 \\right)^2", "( x + 1 )²"),
    ("\\begin{aligned} OA=OC \\\\ \\angle A=\\angle C \\end{aligned}",
     "OA=OC ∠ A=∠ C"),
    # 嵌套花括号 —— 第一版正则栽在这
    ("\\frac{\\sqrt{2}}{2}", "√(2)/2"),
    ("\\frac{1}{\\frac{1}{2}}", "1/½"),
    # 不认识的命令要**原样留着**，不能瞎转
    ("\\foo{x}", "\\foo x"),
    # 换行符
    ("a + b \\\\ c + d", "a + b c + d"),
    # 加横线的 x（平均数）
    ("\\overline{x} = \\frac{x_1 f_1 + \\cdots + x_k f_k}{n}",
     "x̄ = (x₁ f₁ + ⋯ + xₖ fₖ)/n"),
    ("\\overline{x}_\\text{甲} = 165", "x̄甲 = 165"),
    # 上下标后面跟的是**命令**而不是花括号组
    ("s_\\text{甲}^2 = 1.5", "s甲² = 1.5"),
    ("x_1", "x₁"),
    ("x^{10}", "x¹⁰"),
    ("x_\\alpha", "xα"),
    # 数据里真实出现过的形状
    ("\\underline{\\quad}", ""),
    ("a \\leqslant b", "a ≤ b"),
    ("a \\geqslant b", "a ≥ b"),
    ("\\because a=b", "∵ a=b"),
    ("\\therefore x=1", "∴ x=1"),
    ("\\pi r^2", "π r²"),
    ("\\sin A = \\frac{a}{2R}", "sin A = a/2R"),
    ("AB \\perp CD", "AB ⊥ CD"),
    ("\\overline{AB} = \\underline{CD}", "AB̄ = CD̲"),
    ("\\overset{a}{b}", "b"),
    ("\\overbrace{a+b}^{n}", "a+bⁿ"),
    ("x \\cdot y \\div z", "x · y ÷ z"),
    ("\\square ABCD", "□ ABCD"),
    ("\\therefore \\because", "∴ ∵"),
    ("1\\ 200", "1 200"),
    # overbrace 里的内容是数学，要转；\text{个} 里的中文要原样留
    ("\\overbrace{a^m \\cdot a^m}^{n\\text{个}a^m}",
     "am · amⁿ个ᵃm"),
    ("\\parallel", "∥"),
    # 裸 $ 是数学定界符，要丢掉
    ("横轴为时间 $t/时$，纵轴为气温 $T/°C$", "横轴为时间 t/时，纵轴为气温 T/°C"),
]


def main() -> int:
    bad = 0
    for src, want in CASES:
        got = to_plain(src)
        okk = got == want
        if not okk:
            bad += 1
        print(("  ✓ " if okk else "  ✗ ") + f"{src!r}\n      → {got!r}"
              + ("" if okk else f"   （想要 {want!r}）"))
    print(f"\n{'全部通过' if not bad else str(bad) + ' 条不对'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
