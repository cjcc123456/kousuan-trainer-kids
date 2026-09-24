# -*- coding: utf-8 -*-
"""
口算小达人 —— 小学二年级 100 以内加减法随机出题器

运行方式：
    python 口算小达人.py               正常启动程序
    python 口算小达人.py --selftest    自检（出题引擎1万题校验 + 交互逻辑测试）

规格依据：《制作计划书.md》（规格全部锁定版）
"""

import os
import re
import sys
import random
import time
import tempfile
import tkinter as tk
from tkinter import messagebox

# ---------------------------------------------------------------------------
# 全局常量（设计规范）
# ---------------------------------------------------------------------------
APP_TITLE = "口算小达人"
WINDOW_W, WINDOW_H = 900, 600

# 配色（取自设计草图）
PAGE_BG = "#FFFFFF"
CARD_BG = "#F1EFE8"
WHITE = "#FFFFFF"
BLUE = "#378ADD"
BLUE_LT = "#E6F1FB"
GREEN = "#639922"
GREEN_LT = "#EAF3DE"
ORANGE = "#EF9F27"
ORANGE_LT = "#FAEEDA"
RED = "#A32D2D"
RED_LT = "#FCEBEB"
TITLE_DK = "#26215C"
TEXT_DK = "#444441"
TEXT_MUT = "#888780"
BORDER = "#B4B2A9"
GOLD = "#EF9F27"

FONT = "Microsoft YaHei UI"

MODE_PRACTICE, MODE_TEST, MODE_REVIEW = "practice", "test", "review"
MODE_NAME = {MODE_PRACTICE: "练习模式", MODE_TEST: "测验模式", MODE_REVIEW: "错题重练"}
MODE_COUNT = {MODE_PRACTICE: 20, MODE_TEST: 100}
TEST_TIME_LIMIT = 20 * 60  # 测验模式限时 20 分钟
ONE_DIGIT_RATIO = 0.2      # 两位数±一位数占 20%，其余为两位数±两位数
HISTORY_FILE = "口算小达人-历史成绩.txt"
HISTORY_DISPLAY_MAX = 50   # 软件内最多显示最近 50 次


# ---------------------------------------------------------------------------
# 一、出题引擎
# ---------------------------------------------------------------------------
class Question:
    """一道题：a op b"""

    __slots__ = ("a", "b", "op", "answer", "two_digit", "index_no")

    def __init__(self, a, b, op):
        self.a, self.b, self.op = a, b, op
        self.answer = a + b if op == "+" else a - b
        self.two_digit = b >= 10  # 加数/减数是否为两位数
        self.index_no = 0         # 在本轮中的题号（组卷时赋值）

    @property
    def text(self):
        return "%d %s %d" % (self.a, self.op, self.b)

    def key(self):
        """查重键：加法交换律视为同一题"""
        if self.op == "+":
            x, y = (self.a, self.b) if self.a <= self.b else (self.b, self.a)
            return ("+", x, y)
        return ("-", self.a, self.b)

    def has_carry(self):
        """是否含进位（加法）或退位（减法）"""
        if self.op == "+":
            return (self.a % 10) + (self.b % 10) >= 10
        return (self.a % 10) < (self.b % 10)


def _random_question(two_digit):
    """随机生成一道满足全部数值约束的题"""
    op = "+" if random.random() < 0.5 else "-"
    if two_digit:
        if op == "+":
            a = random.randint(10, 89)          # 保证 100-a >= 11
            b = random.randint(10, 100 - a)     # 和 <= 100
        else:
            a = random.randint(20, 99)
            b = random.randint(10, a)           # 差 >= 0
    else:
        a = random.randint(10, 99)
        if op == "+":
            b = random.randint(1, min(9, 100 - a))   # 和 <= 100
        else:
            b = random.randint(1, 9)                 # a>=10 恒有差>=0
    return Question(a, b, op)


def generate_round(n):
    """
    生成一轮 n 道题：
      - 两位数±一位数 20%，两位数±两位数 80%，顺序打乱
      - 同一轮内不重复（加法交换律视为同一题）
      - 保证既出现进退位题，也出现不进位题
    """
    one_count = int(round(n * ONE_DIGIT_RATIO))
    flags = [True] * (n - one_count) + [False] * one_count

    questions = None
    for _ in range(100):  # 极小概率需要整体重生成
        random.shuffle(flags)
        used, qs, ok = set(), [], True
        for two_digit in flags:
            for _ in range(500):
                q = _random_question(two_digit)
                if q.key() not in used:
                    used.add(q.key())
                    qs.append(q)
                    break
            else:
                ok = False
                break
        if not ok:
            continue
        questions = qs
        carry = sum(1 for q in qs if q.has_carry())
        if 0 < carry < n:      # 进退位混合
            return qs
    return questions if questions else []


# ---------------------------------------------------------------------------
# 二、工具函数
# ---------------------------------------------------------------------------
def fmt_clock(sec):
    """秒 -> mm:ss"""
    sec = max(0, int(sec))
    return "%02d:%02d" % (sec // 60, sec % 60)


def fmt_duration(sec):
    """秒 -> X分Y秒"""
    sec = max(0, int(sec))
    return "%d分%02d秒" % (sec // 60, sec % 60) if sec % 60 < 10 else "%d分%d秒" % (sec // 60, sec % 60)


def compute_stars(acc):
    """星星与正确率挂钩：>=90% 三颗、70-89% 两颗、<70% 一颗"""
    if acc >= 0.9:
        return 3
    if acc >= 0.7:
        return 2
    return 1


def encouragement(acc):
    if acc >= 0.9:
        return "太棒了！五星上将！"
    if acc >= 0.7:
        return "真不错，继续加油！"
    return "别灰心，再来一轮试试！"


def app_dir():
    """程序所在目录（打包后为 exe 同目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """在 Canvas 上画圆角矩形"""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def shade(hex_color, factor=0.9):
    """颜色加深（用于悬停效果）"""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02X%02X%02X" % (int(r * factor), int(g * factor), int(b * factor))


def make_button(parent, title, subtitle, bg, fg, sub_fg, command,
                width, height, title_font=18, sub_font=12, border=None):
    """自绘大按钮（Frame + Label，两行文字），返回 Frame（由调用方 pack）"""
    frame = tk.Frame(parent, bg=bg, width=width, height=height,
                     highlightthickness=(1 if border else 0),
                     highlightbackground=border or bg,
                     highlightcolor=border or bg)
    frame.pack_propagate(False)
    inner = tk.Frame(frame, bg=bg)
    inner.place(relx=0.5, rely=0.5, anchor="center")
    lbl = tk.Label(inner, text=title, bg=bg, fg=fg, font=(FONT, title_font, "bold"))
    lbl.pack()
    widgets = [frame, inner, lbl]
    if subtitle:
        sub = tk.Label(inner, text=subtitle, bg=bg, fg=sub_fg, font=(FONT, sub_font))
        sub.pack(pady=(4, 0))
        widgets.append(sub)

    hover_bg = shade(bg, 0.88)

    def on_enter(_):
        for w in widgets:
            w.config(bg=hover_bg)

    def on_leave(_):
        for w in widgets:
            w.config(bg=bg)

    for w in widgets:
        w.bind("<Button-1>", lambda e, c=command: c() if c else None)
        try:
            w.config(cursor="hand2")
        except tk.TclError:
            pass
        if bg != WHITE:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
    return frame


# ---------------------------------------------------------------------------
# 三、一轮答题的状态
# ---------------------------------------------------------------------------
class RoundState:
    def __init__(self, questions, mode, time_limit=None):
        self.questions = questions
        self.mode = mode
        self.time_limit = time_limit
        self.records = []           # [{"q":Question, "ans":str|None, "status":"right/wrong/skip"}]
        self.index = 0
        self.start_ts = None
        self.elapsed = 0.0
        self.finished = False
        self.locked = False         # 时间到后锁定
        self.timed_out = False


# ---------------------------------------------------------------------------
# 四、主程序
# ---------------------------------------------------------------------------
class App:
    def __init__(self, root, selftest=False):
        self.root = root
        self.selftest = selftest
        self.history_path = self._resolve_history_path()
        self.round = None
        self.result_data = None
        self.screen = "menu"
        self._hint_is_error = False
        self.wrong_rows_count = 0
        self.history_rows_count = 0

        if not selftest:
            root.title(APP_TITLE)
            root.configure(bg=PAGE_BG)
            root.resizable(False, False)
            self._center_window()

        self.container = tk.Frame(root, bg=PAGE_BG)
        self.container.pack(fill="both", expand=True)
        self.screens = {}

        self._build_menu()
        self._build_quiz()
        self._build_result()
        self._build_wrong()
        self._build_history()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        for seq in ("<Return>", "<KP_Enter>"):
            root.bind_all(seq, self._on_enter_key)

        self.show_menu()

    # ---------------- 窗口 ----------------
    def _center_window(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - WINDOW_W) // 2)
        y = max(0, (sh - WINDOW_H) // 2 - 20)
        self.root.geometry("%dx%d+%d+%d" % (WINDOW_W, WINDOW_H, x, y))

    def _show(self, name):
        for s in self.screens.values():
            s.pack_forget()
        self.screens[name].pack(fill="both", expand=True)
        self.screen = name

    def on_close(self):
        """关闭保护：仅答题进行中弹确认"""
        if self.round and not self.round.finished:
            if not messagebox.askyesno(APP_TITLE, "确定退出吗？本轮成绩不会保存"):
                return
        self.root.destroy()

    # ---------------- 主菜单 ----------------
    def _build_menu(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["menu"] = f
        tk.Label(f, text="100 以内加减法", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 34, "bold")).pack(pady=(72, 6))
        tk.Label(f, text="小学二年级口算练习", bg=PAGE_BG, fg=TEXT_MUT,
                 font=(FONT, 14)).pack()

        wrap = tk.Frame(f, bg=PAGE_BG)
        wrap.pack(pady=34)
        make_button(wrap, "练习模式", "20道题 · 不限时间", BLUE, WHITE, BLUE_LT,
                    self.start_practice, 340, 104, 22, 12).pack(pady=9)
        make_button(wrap, "测验模式", "100道题 · 限时20分钟", ORANGE, WHITE, ORANGE_LT,
                    self.start_test, 340, 104, 22, 12).pack(pady=9)
        make_button(wrap, "历史成绩", None, CARD_BG, TEXT_DK, None,
                    self.show_history, 170, 44, 14, 11, border=BORDER).pack(pady=(16, 0))

        tk.Label(f, text="选一个开始吧！", bg=PAGE_BG, fg=TEXT_MUT,
                 font=(FONT, 13)).pack(pady=(16, 0))

    def show_menu(self):
        self.round = None
        self._show("menu")

    # ---------------- 答题界面 ----------------
    def _build_quiz(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["quiz"] = f

        top = tk.Frame(f, bg=PAGE_BG)
        top.pack(fill="x", padx=50, pady=(24, 0))
        self.q_label = tk.Label(top, text="", bg=PAGE_BG, fg=TEXT_DK, font=(FONT, 16, "bold"))
        self.q_label.pack(side="left")

        right = tk.Frame(top, bg=PAGE_BG)
        right.pack(side="right")
        clock = tk.Canvas(right, width=24, height=24, bg=PAGE_BG, highlightthickness=0)
        clock.create_oval(3, 3, 21, 21, outline=TEXT_DK, width=2)
        clock.create_line(12, 12, 12, 7, fill=TEXT_DK, width=2)
        clock.create_line(12, 12, 16, 14, fill=TEXT_DK, width=2)
        clock.pack(side="left", padx=(0, 6))
        self.time_label = tk.Label(right, text="00:00", bg=PAGE_BG, fg=TEXT_DK,
                                   font=(FONT, 16, "bold"))
        self.time_label.pack(side="left")

        self.prog = tk.Canvas(f, width=800, height=12, bg=PAGE_BG, highlightthickness=0)
        self.prog.pack(pady=(14, 0))

        self.card = tk.Frame(f, bg=CARD_BG, width=800, height=212)
        self.card.pack(pady=(20, 0))
        self.card.pack_propagate(False)

        row = tk.Frame(self.card, bg=CARD_BG)
        row.place(relx=0.5, rely=0.5, anchor="center")
        self.eq_label = tk.Label(row, text="", bg=CARD_BG, fg=TITLE_DK,
                                 font=(FONT, 46, "bold"))
        self.eq_label.pack(side="left", padx=(0, 18))
        self.entry = tk.Entry(row, width=4, font=(FONT, 38, "bold"), justify="center",
                              bg=WHITE, fg=TITLE_DK, bd=0, relief="flat",
                              highlightthickness=3, highlightbackground=BLUE,
                              highlightcolor=BLUE, insertbackground=BLUE)
        self.entry.pack(side="left", ipady=4)
        vcmd = (self.root.register(self._validate_answer), "%P")
        self.entry.config(validate="key", validatecommand=vcmd)
        self.entry.bind("<KeyRelease>", self._clear_error)

        self.banner = tk.Label(f, text="时间到！", bg=RED_LT, fg=RED, font=(FONT, 18, "bold"))

        self.hint = tk.Label(f, text="按回车键进入下一题", bg=PAGE_BG, fg=TEXT_MUT,
                             font=(FONT, 13))
        self.hint.pack(pady=(14, 0))

        btns = tk.Frame(f, bg=PAGE_BG)
        btns.pack(pady=(18, 0))
        self.next_btn = make_button(btns, "下一题", None, GREEN, WHITE, None,
                                    self.submit_answer, 220, 62, 19, 11)
        self.next_btn.pack(side="left", padx=(0, 44))
        self.skip_btn = make_button(btns, "跳过", None, WHITE, RED, None,
                                    self.skip_question, 130, 52, 16, 11, border=RED)
        self.skip_btn.pack(side="left")

    def _validate_answer(self, proposed):
        """输入校验：仅 ASCII 数字，最多 3 位"""
        return len(proposed) <= 3 and all(c in "0123456789" for c in proposed)

    def _clear_error(self, event=None):
        if event is not None and getattr(event, "keysym", "") in ("Return", "KP_Enter"):
            return
        if self._hint_is_error:
            self._hint_is_error = False
            self.hint.config(text="按回车键进入下一题", fg=TEXT_MUT)
            self.entry.config(highlightbackground=BLUE, highlightcolor=BLUE)

    def _flash_empty(self):
        """答案为空：输入框变红 + 红字提示，不切题"""
        self._hint_is_error = True
        self.hint.config(text="请先输入答案，或点击【跳过】", fg=RED)
        self.entry.config(highlightbackground=RED, highlightcolor=RED)

    def _update_quiz_top(self):
        rs = self.round
        self.q_label.config(text="第 %d 题 / 共 %d 题" % (rs.index + 1, len(rs.questions)))
        self.prog.delete("all")
        w = 800
        round_rect(self.prog, 0, 2, w, 10, 4, fill=CARD_BG, outline="")
        done = rs.index / float(len(rs.questions))
        if done > 0:
            round_rect(self.prog, 0, 2, max(8, int(w * done)), 10, 4, fill=BLUE, outline="")

    def _show_question(self):
        rs = self.round
        q = rs.questions[rs.index]
        self.eq_label.config(text="%d %s %d =" % (q.a, q.op, q.b))
        self.entry.config(state="normal")
        self.entry.delete(0, "end")
        self._hint_is_error = False
        self.hint.config(text="按回车键进入下一题", fg=TEXT_MUT)
        self.entry.config(highlightbackground=BLUE, highlightcolor=BLUE)
        self._update_quiz_top()
        self.entry.focus_set()

    # ---------------- 一轮的开始/结束 ----------------
    def _begin_round(self, questions, mode, time_limit=None):
        for i, q in enumerate(questions):
            q.index_no = i + 1
        self.round = RoundState(questions, mode, time_limit)
        self._show("quiz")
        self.banner.pack_forget()
        self._show_question()
        self.round.start_ts = time.time()
        self.tick_timer()
        self._tick_gen = getattr(self, "_tick_gen", 0) + 1
        self._schedule_tick()

    def start_practice(self):
        self._begin_round(generate_round(MODE_COUNT[MODE_PRACTICE]), MODE_PRACTICE, None)

    def start_test(self):
        self._begin_round(generate_round(MODE_COUNT[MODE_TEST]), MODE_TEST, TEST_TIME_LIMIT)

    def start_review(self):
        """错题重练：用当前错题本重新组卷（动态错题本）"""
        if not self.result_data or not self.result_data["wrong"]:
            return
        qs = [r["q"] for r in self.result_data["wrong"]]
        random.shuffle(qs)
        self._begin_round(qs, MODE_REVIEW, None)

    def _schedule_tick(self):
        """计时器循环（带轮次守卫，避免重复计时链）"""
        gen = getattr(self, "_tick_gen", 0)

        def run():
            if gen != getattr(self, "_tick_gen", 0):
                return
            if self.screen == "quiz" and self.round and not self.round.finished:
                self.tick_timer()
                self.root.after(200, run)

        self.root.after(200, run)

    def tick_timer(self):
        rs = self.round
        if not rs or rs.finished:
            return
        elapsed = time.time() - (rs.start_ts or time.time())
        if rs.time_limit:
            remain = rs.time_limit - elapsed
            self.time_label.config(text=fmt_clock(remain),
                                   fg=(RED if remain <= 60 else TEXT_DK))
            if remain <= 0:
                self._time_up()
        else:
            self.time_label.config(text=fmt_clock(elapsed), fg=TEXT_DK)

    def _time_up(self):
        rs = self.round
        if not rs or rs.finished or rs.locked:
            return
        rs.locked = True
        rs.timed_out = True
        self._lock_input()
        self.banner.pack(before=self.card, pady=(14, 0))
        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass
        self.root.after(1200, lambda: self.finish_round(timed_out=True))

    def _lock_input(self):
        try:
            self.entry.config(state="disabled", highlightbackground=BORDER,
                              highlightcolor=BORDER)
        except tk.TclError:
            pass

    def submit_answer(self):
        """有答案才切题；空答案被拦截"""
        rs = self.round
        if not rs or rs.finished or rs.locked:
            return
        ans = self.entry.get().strip()
        if ans == "":
            self._flash_empty()
            return
        q = rs.questions[rs.index]
        status = "right" if int(ans) == q.answer else "wrong"
        rs.records.append({"q": q, "ans": ans, "status": status})
        self._advance()

    def skip_question(self):
        rs = self.round
        if not rs or rs.finished or rs.locked:
            return
        q = rs.questions[rs.index]
        rs.records.append({"q": q, "ans": None, "status": "skip"})
        self._advance()

    def _advance(self):
        rs = self.round
        rs.index += 1
        if rs.index >= len(rs.questions):
            self.finish_round()
        else:
            self._show_question()

    def _on_enter_key(self, event=None):
        if self.screen == "quiz" and self.round and not self.round.finished:
            self.submit_answer()

    def finish_round(self, timed_out=False):
        rs = self.round
        if not rs or rs.finished:
            return
        rs.finished = True
        rs.timed_out = rs.timed_out or timed_out

        if rs.timed_out and rs.time_limit:
            rs.elapsed = float(rs.time_limit)
        else:
            rs.elapsed = max(0.0, time.time() - (rs.start_ts or time.time()))

        total = len(rs.questions)
        # 时间到未作答的题：计为未答（等同跳过，计为错误）
        while len(rs.records) < total:
            rs.records.append({"q": rs.questions[len(rs.records)], "ans": None,
                               "status": "skip"})

        right = sum(1 for r in rs.records if r["status"] == "right")
        acc = right / float(total) if total else 0.0
        wrong = [r for r in rs.records if r["status"] != "right"]

        self.result_data = {
            "mode": rs.mode, "right": right, "total": total, "acc": acc,
            "elapsed": rs.elapsed, "timed_out": rs.timed_out,
            "wrong": wrong, "stars": compute_stars(acc),
        }
        if rs.mode in (MODE_PRACTICE, MODE_TEST):
            self.save_history(rs, right, total, acc)
        self._show_result()

    # ---------------- 成绩界面 ----------------
    def _build_result(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["result"] = f
        tk.Label(f, text="做完啦！", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 30, "bold")).pack(pady=(52, 6))
        self.res_stars = tk.Label(f, text="", bg=PAGE_BG, fg=GOLD, font=(FONT, 40))
        self.res_stars.pack()
        self.res_score = tk.Label(f, text="", bg=PAGE_BG, fg=TITLE_DK,
                                  font=(FONT, 44, "bold"))
        self.res_score.pack(pady=(4, 0))
        self.res_right = tk.Label(f, text="", bg=PAGE_BG, fg=GREEN,
                                  font=(FONT, 17, "bold"))
        self.res_right.pack(pady=(6, 0))
        self.res_detail = tk.Label(f, text="", bg=PAGE_BG, fg=TEXT_DK, font=(FONT, 14))
        self.res_detail.pack(pady=(6, 0))
        self.res_note = tk.Label(f, text="", bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 13))
        self.res_note.pack(pady=(4, 0))
        self.res_btns = tk.Frame(f, bg=PAGE_BG)
        self.res_btns.pack(pady=(26, 0))

    def _show_result(self):
        d = self.result_data
        self.res_stars.config(text="★" * d["stars"] + "☆" * (3 - d["stars"]) + "  " + encouragement(d["acc"]))
        self.res_score.config(text="%d / %d" % (d["right"], d["total"]))
        self.res_right.config(text="答对 %d 题" % d["right"])
        self.res_detail.config(text="正确率 %d%%　·　用时 %s"
                                    % (round(d["acc"] * 100), fmt_duration(d["elapsed"])))
        if d["mode"] == MODE_TEST:
            self.res_note.config(text=("时间到，已自动交卷" if d["timed_out"] else "在限定时间内完成"))
        else:
            self.res_note.config(text="")

        for w in self.res_btns.winfo_children():
            w.destroy()

        if d["mode"] == MODE_REVIEW:
            make_button(self.res_btns, "返回错题", None, BLUE, WHITE, None,
                        self.show_wrong_list, 170, 54, 16, 11).pack(side="left", padx=8)
        else:
            make_button(self.res_btns, "再来一轮", None, BLUE, WHITE, None,
                        self.start_practice if d["mode"] == MODE_PRACTICE else self.start_test,
                        170, 54, 16, 11).pack(side="left", padx=8)
        # 全对时也保留入口：进入后显示"全对，没有错题！"的庆祝页
        make_button(self.res_btns, "看看错题", None, ORANGE, WHITE, None,
                    self.show_wrong_list, 170, 54, 16, 11).pack(side="left", padx=8)
        make_button(self.res_btns, "返回菜单", None, WHITE, TEXT_DK, None,
                    self.show_menu, 170, 54, 16, 11, border=BORDER).pack(side="left", padx=8)
        self._show("result")

    # ---------------- 错题回顾 ----------------
    def _build_wrong(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["wrong"] = f
        tk.Label(f, text="看看错题", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 26, "bold")).pack(pady=(26, 2))
        self.wrong_sum = tk.Label(f, text="", bg=PAGE_BG, fg=TEXT_DK, font=(FONT, 14, "bold"))
        self.wrong_sum.pack(pady=(2, 8))

        table = tk.Frame(f, bg=PAGE_BG)
        table.pack(fill="both", expand=True, padx=70)
        self.wrong_canvas = tk.Canvas(table, bg=PAGE_BG, highlightthickness=0)
        sb = tk.Scrollbar(table, orient="vertical", command=self.wrong_canvas.yview)
        self.wrong_inner = tk.Frame(self.wrong_canvas, bg=PAGE_BG)
        self.wrong_window = self.wrong_canvas.create_window((0, 0), window=self.wrong_inner,
                                                           anchor="nw")
        self.wrong_canvas.configure(yscrollcommand=sb.set)
        self.wrong_canvas.pack(side="left", fill="both", expand=True)
        self.wrong_sb = sb
        sb.pack(side="right", fill="y")
        self.wrong_inner.bind("<Configure>",
                              lambda e: self.wrong_canvas.configure(
                                  scrollregion=self.wrong_canvas.bbox("all")))
        self.wrong_canvas.bind("<Configure>",
                               lambda e: self.wrong_canvas.itemconfigure(
                                   self.wrong_window, width=e.width))

        btns = tk.Frame(f, bg=PAGE_BG)
        btns.pack(pady=(10, 20))
        self.wrong_btns = btns

    def show_wrong_list(self):
        for w in self.wrong_inner.winfo_children():
            w.destroy()
        for w in self.wrong_btns.winfo_children():
            w.destroy()

        wrong = self.result_data["wrong"] if self.result_data else []
        n_wrong = sum(1 for r in wrong if r["status"] == "wrong")
        n_skip = sum(1 for r in wrong if r["status"] == "skip")
        self.wrong_rows_count = len(wrong)

        if not wrong:
            self.wrong_sb.pack_forget()          # 无错题时不显示滚动条
            self.wrong_sum.config(text="全对，没有错题！太棒了！")
            tk.Label(self.wrong_inner, text="★★★", bg=PAGE_BG, fg=GOLD,
                     font=(FONT, 44)).pack(pady=(40, 8))
            tk.Label(self.wrong_inner, text="这一轮全部答对，一道错题都没有！",
                     bg=PAGE_BG, fg=GREEN, font=(FONT, 15, "bold")).pack()
        else:
            self.wrong_sb.pack(side="right", fill="y")
            self.wrong_sum.config(text="共 %d 道错题（答错 %d · 跳过 %d）"
                                       % (len(wrong), n_wrong, n_skip))
            head = tk.Frame(self.wrong_inner, bg=CARD_BG)
            head.pack(fill="x", pady=(0, 2))
            self._cell(head, "题目", 0, 360, TEXT_MUT, 12, bold=False, bg=CARD_BG)
            self._cell(head, "你的答案", 1, 150, TEXT_MUT, 12, bold=False, bg=CARD_BG)
            self._cell(head, "正确答案", 2, 150, TEXT_MUT, 12, bold=False, bg=CARD_BG)

            for i, r in enumerate(wrong):
                q = r["q"]
                bg = CARD_BG if i % 2 == 0 else WHITE
                line = tk.Frame(self.wrong_inner, bg=bg)
                line.pack(fill="x", pady=1)
                self._cell(line, "第 %d 题　%d %s %d" % (q.index_no, q.a, q.op, q.b),
                           0, 360, TITLE_DK, 14, bg=bg)
                if r["status"] == "skip":
                    self._cell(line, "跳过", 1, 150, TEXT_MUT, 13, bg=bg)
                else:
                    self._cell(line, "%s" % r["ans"], 1, 150, RED, 14, bold=True, bg=bg)
                self._cell(line, "%d" % q.answer, 2, 150, GREEN, 14, bold=True, bg=bg)

        wheel_targets = [self.wrong_canvas, self.wrong_inner]
        wheel_targets += self.wrong_inner.winfo_children()
        for w in wheel_targets:
            w.bind("<MouseWheel>", self._on_mousewheel_wrong)

        if wrong:
            make_button(self.wrong_btns, "错题重练", None, ORANGE, WHITE, None,
                        self.start_review, 180, 56, 16, 11).pack(side="left", padx=8)
        make_button(self.wrong_btns, "返回", None, WHITE, TEXT_DK, None,
                    self._back_from_wrong, 140, 56, 16, 11, border=BORDER).pack(side="left", padx=8)
        self._show("wrong")

    def _cell(self, parent, text, col, width, fg, size, bold=True, bg=WHITE):
        lbl = tk.Label(parent, text=text, bg=bg, fg=fg,
                       font=(FONT, size, "bold" if bold else "normal"),
                       anchor="w", padx=10, pady=7)
        lbl.grid(row=0, column=col, sticky="w")
        parent.grid_columnconfigure(col, minsize=width)
        lbl.bind("<MouseWheel>", self._on_mousewheel_wrong)
        return lbl

    def _on_mousewheel_wrong(self, event):
        try:
            self.wrong_canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass

    def _back_from_wrong(self):
        self._show_result()

    # ---------------- 历史成绩 ----------------
    def _resolve_history_path(self):
        p = os.path.join(app_dir(), HISTORY_FILE)
        try:
            with open(p, "a", encoding="utf-8"):
                pass
            return p
        except Exception:
            return os.path.join(os.path.expanduser("~"), HISTORY_FILE)

    def save_history(self, rs, right, total, acc):
        """追加保存一次成绩（错题重练不保存）"""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = "%s | %s | 答对 %d/%d | 正确率 %d%% | 用时 %s" % (
            ts, MODE_NAME[rs.mode], right, total, round(acc * 100), fmt_duration(rs.elapsed))
        if rs.timed_out:
            line += " | 时间到"
        try:
            new_file = not os.path.exists(self.history_path)
            with open(self.history_path, "a", encoding="utf-8") as fp:
                if new_file:
                    fp.write("口算小达人 历史成绩记录（每次答题一行）\n")
                    fp.write("时间 | 模式 | 成绩 | 正确率 | 用时\n")
                fp.write(line + "\n")
        except Exception:
            pass  # 写入失败不影响使用

    def read_history(self):
        """读取历史记录，倒序（最新在前）"""
        pat = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (\S+) \| 答对 (\d+)/(\d+) "
                         r"\| 正确率 (\d+)% \| 用时 (.+?)( \| 时间到)?$")
        out = []
        try:
            with open(self.history_path, "r", encoding="utf-8") as fp:
                for line in fp:
                    m = pat.match(line.strip())
                    if m:
                        out.append({
                            "time": m.group(1), "mode": m.group(2),
                            "right": int(m.group(3)), "total": int(m.group(4)),
                            "acc": int(m.group(5)), "dur": m.group(6),
                            "timed_out": bool(m.group(7)),
                        })
        except Exception:
            pass
        out.reverse()
        return out

    def _build_history(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["history"] = f
        tk.Label(f, text="历史成绩", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 26, "bold")).pack(pady=(26, 2))
        self.hist_sum = tk.Label(f, text="", bg=PAGE_BG, fg=TEXT_DK, font=(FONT, 14, "bold"))
        self.hist_sum.pack(pady=(2, 8))

        table = tk.Frame(f, bg=PAGE_BG)
        table.pack(fill="both", expand=True, padx=70)
        self.hist_canvas = tk.Canvas(table, bg=PAGE_BG, highlightthickness=0)
        sb = tk.Scrollbar(table, orient="vertical", command=self.hist_canvas.yview)
        self.hist_inner = tk.Frame(self.hist_canvas, bg=PAGE_BG)
        self.hist_window = self.hist_canvas.create_window((0, 0), window=self.hist_inner,
                                                          anchor="nw")
        self.hist_canvas.configure(yscrollcommand=sb.set)
        self.hist_canvas.pack(side="left", fill="both", expand=True)
        self.hist_sb = sb
        sb.pack(side="right", fill="y")
        self.hist_inner.bind("<Configure>",
                             lambda e: self.hist_canvas.configure(
                                 scrollregion=self.hist_canvas.bbox("all")))
        self.hist_canvas.bind("<Configure>",
                              lambda e: self.hist_canvas.itemconfigure(
                                  self.hist_window, width=e.width))

        tk.Label(f, text="完整记录同时保存在软件旁的 txt 文件里", bg=PAGE_BG,
                 fg=TEXT_MUT, font=(FONT, 12)).pack(pady=(8, 6))
        btns = tk.Frame(f, bg=PAGE_BG)
        btns.pack(pady=(0, 20))
        make_button(btns, "返回菜单", None, WHITE, TEXT_DK, None,
                    self.show_menu, 180, 54, 16, 11, border=BORDER).pack()

    def show_history(self):
        for w in self.hist_inner.winfo_children():
            w.destroy()
        recs = self.read_history()
        self.history_rows_count = min(len(recs), HISTORY_DISPLAY_MAX)
        if recs:
            self.hist_sb.pack(side="right", fill="y")
            avg = round(sum(r["acc"] for r in recs) / float(len(recs)))
            self.hist_sum.config(text="共练习 %d 次 · 平均正确率 %d%%（显示最近 %d 次）"
                                      % (len(recs), avg, self.history_rows_count))
            head = tk.Frame(self.hist_inner, bg=CARD_BG)
            head.pack(fill="x", pady=(0, 2))
            self._cell2(head, "时间", 0, 220, TEXT_MUT, 12, bold=False, bg=CARD_BG)
            self._cell2(head, "模式", 1, 120, TEXT_MUT, 12, bold=False, bg=CARD_BG)
            self._cell2(head, "成绩", 2, 140, TEXT_MUT, 12, bold=False, bg=CARD_BG)
            self._cell2(head, "用时", 3, 160, TEXT_MUT, 12, bold=False, bg=CARD_BG)

            for i, r in enumerate(recs[:HISTORY_DISPLAY_MAX]):
                bg = CARD_BG if i % 2 == 0 else WHITE
                line = tk.Frame(self.hist_inner, bg=bg)
                line.pack(fill="x", pady=1)
                self._cell2(line, r["time"], 0, 220, TEXT_DK, 13, bg=bg)
                self._cell2(line, r["mode"], 1, 120,
                            BLUE if r["mode"] == "练习模式" else ORANGE, 13, bg=bg)
                self._cell2(line, "%d/%d" % (r["right"], r["total"]), 2, 140,
                            GREEN if r["acc"] >= 90 else TEXT_DK, 13, bg=bg)
                dur = r["dur"] + ("（时间到）" if r["timed_out"] else "")
                self._cell2(line, dur, 3, 160, TEXT_DK, 13, bg=bg)
        else:
            self.hist_sb.pack_forget()           # 无记录时不显示滚动条
            self.hist_sum.config(text="还没有记录，快去练习吧！")
            tk.Label(self.hist_inner, text="完成一轮练习或测验后，成绩会出现在这里",
                     bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 14)).pack(pady=40)

        wheel_targets = [self.hist_canvas, self.hist_inner] + self.hist_inner.winfo_children()
        for w in wheel_targets:
            w.bind("<MouseWheel>", self._on_mousewheel_hist)
        self._show("history")

    def _cell2(self, parent, text, col, width, fg, size, bold=True, bg=WHITE):
        lbl = tk.Label(parent, text=text, bg=bg, fg=fg,
                       font=(FONT, size, "bold" if bold else "normal"),
                       anchor="w", padx=10, pady=7)
        lbl.grid(row=0, column=col, sticky="w")
        parent.grid_columnconfigure(col, minsize=width)
        lbl.bind("<MouseWheel>", self._on_mousewheel_hist)
        return lbl

    def _on_mousewheel_hist(self, event):
        try:
            self.hist_canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# 五、自检
# ---------------------------------------------------------------------------
def _validate_round(qs, n):
    """校验一轮题目是否满足全部规格，返回问题列表"""
    errs = []
    if len(qs) != n:
        errs.append("题量 %d != %d" % (len(qs), n))
        return errs
    one = sum(1 for q in qs if not q.two_digit)
    if one != int(round(n * ONE_DIGIT_RATIO)):
        errs.append("两位数±一位数数量 %d != %d" % (one, int(round(n * ONE_DIGIT_RATIO))))
    keys = [q.key() for q in qs]
    if len(set(keys)) != len(keys):
        errs.append("存在重复题目")
    for q in qs:
        if not (10 <= q.a <= 99):
            errs.append("被加/被减数越界: %s" % q.text)
        if q.two_digit:
            if not (10 <= q.b <= 99):
                errs.append("两位数操作数越界: %s" % q.text)
        else:
            if not (1 <= q.b <= 9):
                errs.append("一位数操作数越界: %s" % q.text)
        expect = q.a + q.b if q.op == "+" else q.a - q.b
        if q.answer != expect:
            errs.append("答案错误: %s" % q.text)
        if q.op == "+" and q.answer > 100:
            errs.append("和超过100: %s" % q.text)
        if q.op == "-" and q.answer < 0:
            errs.append("差为负: %s" % q.text)
    carry = sum(1 for q in qs if q.has_carry())
    if carry == 0 or carry == n:
        errs.append("进退位未混合（进位题 %d/%d）" % (carry, n))
    return errs


def run_selftest():
    """自检：出题引擎 1 万题校验 + 交互逻辑测试（结果同时写入报告文件，便于验证打包后的 exe）"""
    report = []

    def out(s):
        report.append(s)
        try:
            if sys.stdout is not None:
                sys.stdout.write(s + "\n")
                sys.stdout.flush()
        except Exception:
            pass

    try:
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    results = []

    def check(name, ok, detail=""):
        results.append((name, ok))
        out("  %s  %s%s" % ("[PASS]" if ok else "[FAIL]", name,
                            ("  -> " + str(detail)) if detail and not ok else ""))

    out("=" * 64)
    out("口算小达人 自检")
    out("=" * 64)

    # ---- 1. 出题引擎 1 万题校验 ----
    out("\n[1] 出题引擎 1 万题校验")
    total, all_errs = 0, []
    for _ in range(50):
        qs = generate_round(100)
        total += len(qs)
        all_errs += _validate_round(qs, 100)
    for _ in range(250):
        qs = generate_round(20)
        total += len(qs)
        all_errs += _validate_round(qs, 20)
    check("生成 %d 题全部满足约束（无重复/范围/进退位混合/配比20:80）" % total,
          not all_errs, all_errs[:5])

    # 加/减近似均衡抽查
    qs = []
    for _ in range(100):
        qs += generate_round(100)
    ratio = sum(1 for q in qs if q.op == "+") / float(len(qs))
    check("加减法比例接近均衡（加法 %.1f%%）" % (ratio * 100), 0.42 <= ratio <= 0.58, ratio)

    # ---- 2. 交互与流程 ----
    out("\n[2] 交互与流程（模拟界面操作）")
    root = tk.Tk()
    root.withdraw()
    app = App(root, selftest=True)
    tmp_hist = os.path.join(tempfile.gettempdir(), "口算小达人-自检历史.txt")
    if os.path.exists(tmp_hist):
        os.remove(tmp_hist)
    app.history_path = tmp_hist

    # 空答案：回车 / 下一题 → 不切题
    app.start_practice()
    i0 = app.round.index
    app.entry.delete(0, "end")
    app._on_enter_key()
    check("空答案按回车 → 不切题且有提示",
          app.round.index == i0 and app._hint_is_error)
    app.submit_answer()
    check("空答案点【下一题】→ 不切题", app.round.index == i0)

    # 跳过 → 切题并记录
    app.skip_question()
    check("空答案点【跳过】→ 切题并记录为 skip",
          app.round.index == i0 + 1 and app.round.records[-1]["status"] == "skip")

    # 有答案 → 切题并记录对错
    q = app.round.questions[app.round.index]
    app.entry.delete(0, "end")
    app.entry.insert(0, str(q.answer))
    app._on_enter_key()
    check("正确作答按回车 → 切题并记录 right",
          app.round.records[-1]["status"] == "right" and app.round.index == i0 + 2)

    q = app.round.questions[app.round.index]
    app.entry.delete(0, "end")
    app.entry.insert(0, str(q.answer + 1))
    app.submit_answer()
    check("错误作答点【下一题】→ 切题并记录 wrong", app.round.records[-1]["status"] == "wrong")

    # 输入过滤
    app.entry.delete(0, "end")
    app.entry.insert(0, "abc")
    ok1 = app.entry.get() == ""
    app.entry.insert(0, "1a2")
    ok2 = app.entry.get() == ""
    app.entry.insert(0, "1234")
    ok3 = app.entry.get() == ""
    app.entry.insert(0, "082")
    ok4 = app.entry.get() == "082" and int(app.entry.get()) == 82
    app.entry.delete(0, "end")
    check("非数字/超长输入被拦截，前导零可正常判定", ok1 and ok2 and ok3 and ok4,
          (ok1, ok2, ok3, ok4))

    # 练习模式答完 20 题 → 出成绩 + 星星
    app.start_practice()
    for _ in range(20):
        q = app.round.questions[app.round.index]
        app.entry.delete(0, "end")
        app.entry.insert(0, str(q.answer))
        app.submit_answer()
    d = app.result_data
    check("练习模式答完 20 题 → 自动出成绩（20/20，三颗星）",
          app.round.finished and d["total"] == 20 and d["right"] == 20 and d["stars"] == 3,
          (d["total"], d["right"], d["stars"]))

    # 历史写入与读取一致
    recs = app.read_history()
    check("成绩自动写入历史文件并可读回一致",
          len(recs) == 1 and recs[0]["total"] == 20 and recs[0]["right"] == 20
          and recs[0]["mode"] == "练习模式", recs)

    # 测验模式：跳过计入错误 + 提前答完
    app.start_test()
    for i in range(100):
        if i % 10 == 0:
            app.skip_question()
        else:
            q = app.round.questions[app.round.index]
            app.entry.delete(0, "end")
            app.entry.insert(0, str(q.answer))
            app.submit_answer()
    d = app.result_data
    check("测验模式提前答完 → 立即出成绩（100题，对90，跳过10计错）",
          app.round.finished and d["total"] == 100 and d["right"] == 90
          and len(d["wrong"]) == 10 and not d["timed_out"],
          (d["total"], d["right"], len(d["wrong"])))

    # 错题列表内容
    app.show_wrong_list()
    check("错题列表行数与错题数一致（10 行）", app.wrong_rows_count == 10,
          app.wrong_rows_count)

    # 错题重练 → 循环至全对；且不计入历史
    before = len(app.read_history())
    app.start_review()
    check("错题重练用当前错题本组卷（10 题）", len(app.round.questions) == 10,
          len(app.round.questions))
    for _ in range(10):
        q = app.round.questions[app.round.index]
        app.entry.delete(0, "end")
        app.entry.insert(0, str(q.answer))
        app.submit_answer()
    d = app.result_data
    after = len(app.read_history())
    check("错题重练全部答对 → 错题本清空且不写入历史",
          d["right"] == 10 and len(d["wrong"]) == 0 and after == before,
          (d["right"], len(d["wrong"]), before, after))

    # 测验倒计时归零 → 锁定并自动交卷
    app.start_test()
    app.round.start_ts = time.time() - (TEST_TIME_LIMIT + 5)
    app.tick_timer()
    locked = app.round.locked and app.round.timed_out
    app.finish_round(timed_out=True)
    d = app.result_data
    check("倒计时归零 → 锁定界面、自动交卷、未答题计错",
          locked and app.round.finished and d["timed_out"] and d["total"] == 100
          and d["right"] == 0 and len(d["wrong"]) == 100,
          (locked, d["right"], len(d["wrong"])))

    # 星星分档
    check("星星分档：100%→3星、80%→2星、50%→1星",
          compute_stars(1.0) == 3 and compute_stars(0.8) == 2 and compute_stars(0.5) == 1)

    # 时间到记录标记
    recs = app.read_history()
    check("时间到成绩在历史中带“时间到”标记",
          any(r.get("timed_out") for r in recs), recs[-1] if recs else None)

    root.destroy()

    passed = sum(1 for _, ok in results if ok)
    out("\n" + "=" * 64)
    out("自检结果：%d / %d 通过" % (passed, len(results)))
    out("=" * 64)

    # 报告写入文件（打包成 exe 后无控制台，可据此查看结果）
    try:
        report_path = os.path.join(tempfile.gettempdir(), "口算小达人-自检报告.txt")
        with open(report_path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(report) + "\n")
    except Exception:
        pass
    return 0 if passed == len(results) else 1


# ---------------------------------------------------------------------------
def main():
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())

    # Windows 高 DPI 感知
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
