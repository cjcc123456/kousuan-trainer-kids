# -*- coding: utf-8 -*-
"""
口算小达人 v1.1 —— 小学二年级 100 以内加减法随机出题器（家庭多用户版）

运行方式：
    python 口算小达人.py               正常启动程序
    python 口算小达人.py --selftest    自检（出题引擎1万题校验 + 交互逻辑 + 用户体系测试）

规格依据：《制作计划书.md》（v1.0 规格 + 第九章 v1.1 用户与权限升级，均已锁定）

数据文件（均位于程序同目录，txt 记事本可直接查看）：
    口算小达人-用户.json            用户列表、角色、密码哈希、当前用户
    口算小达人-历史成绩-<姓名>.txt   每位用户一份历史记录
"""

import hashlib
import json
import os
import random
import re
import sys
import tempfile
import time
import tkinter as tk
from tkinter import messagebox

# ---------------------------------------------------------------------------
# 全局常量（设计规范）
# ---------------------------------------------------------------------------
APP_TITLE = "口算小达人"
WINDOW_W, WINDOW_H = 900, 600

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
TEST_TIME_LIMIT = 20 * 60
ONE_DIGIT_RATIO = 0.2
HISTORY_DISPLAY_MAX = 50

ROLE_PARENT, ROLE_CHILD = "parent", "child"
ROLE_NAME = {ROLE_PARENT: "家长", ROLE_CHILD: "学生"}
ROLE_COLOR = {ROLE_PARENT: "#854F0B", ROLE_CHILD: "#185FA5"}

USER_FILE = "口算小达人-用户.json"
LEGACY_HISTORY = "口算小达人-历史成绩.txt"
HISTORY_PREFIX = "口算小达人-历史成绩-"
HISTORY_DETAIL_PREFIX = "口算小达人-历史明细-"
DATA_VERSION = 2
HISTORY_HEADER = ("口算小达人 历史成绩记录（每次答题一行）\n"
                  "时间 | 模式 | 得分 | 答对 | 作答 | 跳过 | 未答 | 总题 | 正确率 | 用时\n")

# 得分配色：>=90 绿、70-89 深黄、<70 红
SCORE_GREEN, SCORE_AMBER, SCORE_RED = "#3B6D11", "#854F0B", "#A32D2D"


# ---------------------------------------------------------------------------
# 一、出题引擎
# ---------------------------------------------------------------------------
class Question:
    """一道题：a op b"""

    __slots__ = ("a", "b", "op", "answer", "two_digit", "index_no")

    def __init__(self, a, b, op):
        self.a, self.b, self.op = a, b, op
        self.answer = a + b if op == "+" else a - b
        self.two_digit = b >= 10
        self.index_no = 0

    @property
    def text(self):
        return "%d %s %d" % (self.a, self.op, self.b)

    def key(self):
        if self.op == "+":
            x, y = (self.a, self.b) if self.a <= self.b else (self.b, self.a)
            return ("+", x, y)
        return ("-", self.a, self.b)

    def has_carry(self):
        if self.op == "+":
            return (self.a % 10) + (self.b % 10) >= 10
        return (self.a % 10) < (self.b % 10)


def _random_question(two_digit):
    op = "+" if random.random() < 0.5 else "-"
    if two_digit:
        if op == "+":
            a = random.randint(10, 89)
            b = random.randint(10, 100 - a)
        else:
            a = random.randint(20, 99)
            b = random.randint(10, a)
    else:
        a = random.randint(10, 99)
        if op == "+":
            b = random.randint(1, min(9, 100 - a))
        else:
            b = random.randint(1, 9)
    return Question(a, b, op)


def generate_round(n):
    """生成一轮 n 道题：配比 20:80、去重（加法交换同题）、保证进退位混合"""
    one_count = int(round(n * ONE_DIGIT_RATIO))
    flags = [True] * (n - one_count) + [False] * one_count

    questions = None
    for _ in range(100):
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
        if 0 < carry < n:
            return qs
    return questions if questions else []


# ---------------------------------------------------------------------------
# 二、工具函数
# ---------------------------------------------------------------------------
def fmt_clock(sec):
    sec = max(0, int(sec))
    return "%02d:%02d" % (sec // 60, sec % 60)


def fmt_duration(sec):
    sec = max(0, int(sec))
    if sec % 60 < 10:
        return "%d分%02d秒" % (sec // 60, sec % 60)
    return "%d分%d秒" % (sec // 60, sec % 60)


def score_of(right, total):
    """得分 = 答对 ÷ 总题数 × 100（满分 100）"""
    return int(round(right / float(total) * 100)) if total else 0


def acc_of(right, answered):
    """正确率 = 答对 ÷ 已作答题数（不含跳过、不含未答）"""
    return right / float(answered) if answered else 0.0


def stars_of_score(score):
    """星星按得分：>=90 三颗、70-89 两颗、<70 一颗"""
    if score >= 90:
        return 3
    if score >= 70:
        return 2
    return 1


def score_color(score):
    if score >= 90:
        return SCORE_GREEN
    if score >= 70:
        return SCORE_AMBER
    return SCORE_RED


def compute_stats(records, total):
    """从答题记录统计：答对/作答/跳过/未答/得分/正确率"""
    right = sum(1 for r in records if r["status"] == "right")
    wrong = sum(1 for r in records if r["status"] == "wrong")
    skipped = sum(1 for r in records if r["status"] == "skip")
    unanswered = sum(1 for r in records if r["status"] == "unanswered")
    answered = right + wrong
    return {
        "right": right, "wrong": wrong, "answered": answered,
        "skipped": skipped, "unanswered": unanswered, "total": total,
        "score": score_of(right, total), "acc": acc_of(right, answered),
    }


def encouragement(score):
    if score >= 90:
        return "太棒了！五星上将！"
    if score >= 70:
        return "真不错，继续加油！"
    return "别灰心，再来一轮试试！"


def question_from_text(text):
    """把 "47 + 35" / "62-28" 还原为 Question 对象（历史错题重练用）"""
    m = re.match(r"^(\d+)\s*([+\-])\s*(\d+)$", (text or "").strip())
    if not m:
        return None
    q = Question(int(m.group(1)), int(m.group(3)), m.group(2))
    return q


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resolve_base_dir():
    """数据文件目录：优先程序同目录，不可写则退到用户主目录"""
    for d in (app_dir(), os.path.expanduser("~")):
        try:
            probe = os.path.join(d, ".口算小达人-写入测试")
            with open(probe, "w", encoding="utf-8"):
                pass
            os.remove(probe)
            return d
        except Exception:
            continue
    return os.path.expanduser("~")


def safe_filename(name):
    """用户名转安全文件名"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "用户"


def make_pin_hash(pin, salt=None):
    salt = salt or os.urandom(8).hex()
    return salt, hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def shade(hex_color, factor=0.9):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02X%02X%02X" % (int(r * factor), int(g * factor), int(b * factor))


def person_icon(parent, x, y, r, color, bg):
    """小人图标（头 + 肩），返回 Canvas"""
    cv = tk.Canvas(parent, width=r * 4, height=r * 4, bg=bg, highlightthickness=0)
    cx, cy = r * 2, r * 1.5
    cv.create_oval(cx - r * 0.72, cy - r * 1.5, cx + r * 0.72, cy - r * 0.06,
                   fill=color, outline="")
    cv.create_arc(cx - r * 1.7, cy + r * 0.1, cx + r * 1.7, cy + r * 3.5,
                  start=0, extent=180, fill=color, outline="", style="chord")
    return cv


def make_button(parent, title, subtitle, bg, fg, sub_fg, command,
                width, height, title_font=18, sub_font=12, border=None,
                enabled=True):
    """自绘按钮（Frame + Label），返回 Frame（由调用方 pack）"""
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
        if enabled:
            w.bind("<Button-1>", lambda e, c=command: c() if c else None)
            try:
                w.config(cursor="hand2")
            except tk.TclError:
                pass
            if bg != WHITE:
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
    return frame


def widget_texts(widget, out=None):
    """收集控件树里的全部文字（自检用）"""
    out = [] if out is None else out
    try:
        t = widget.cget("text")
        if t:
            out.append(str(t))
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        widget_texts(child, out)
    return out


# ---------------------------------------------------------------------------
# 三、用户数据（家长 / 孩子）
# ---------------------------------------------------------------------------
class UserStore:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.path = os.path.join(base_dir, USER_FILE)
        self.users = []
        self.current = None
        self.load()

    # ---- 读写 ----
    def load(self):
        self.data_version = DATA_VERSION
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                self.users = [u for u in data.get("users", []) if u.get("name")]
                self.current = data.get("current")
                self.data_version = int(data.get("data_version", 1))
            except Exception:
                self.users, self.current = [], None
        else:
            # v1.1 首次使用：按约定清空 v1.0 的旧历史记录
            legacy = os.path.join(self.base_dir, LEGACY_HISTORY)
            if os.path.exists(legacy):
                try:
                    os.remove(legacy)
                except Exception:
                    pass
        names = [u["name"] for u in self.users]
        if self.current not in names:
            self.current = names[0] if names else None

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fp:
                json.dump({"users": self.users, "current": self.current,
                           "data_version": getattr(self, "data_version", DATA_VERSION)},
                          fp, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def set_data_version(self, version):
        self.data_version = version
        self.save()

    # ---- 查询 ----
    def has_users(self):
        return bool(self.users)

    def names(self):
        return [u["name"] for u in self.users]

    def children(self):
        return [u["name"] for u in self.users if u["role"] == ROLE_CHILD]

    def parents(self):
        return [u["name"] for u in self.users if u["role"] == ROLE_PARENT]

    def find(self, name):
        for u in self.users:
            if u["name"] == name:
                return u
        return None

    def role_of(self, name):
        u = self.find(name)
        return u["role"] if u else None

    def is_parent(self, name=None):
        return self.role_of(name or self.current) == ROLE_PARENT

    def requires_pin(self, name):
        return self.role_of(name) == ROLE_PARENT

    def verify(self, name, pin):
        u = self.find(name)
        if not u or u["role"] != ROLE_PARENT:
            return False
        salt, expected = u.get("salt"), u.get("pw")
        if not salt or not expected:
            return False
        _, got = make_pin_hash(pin, salt)
        return got == expected

    # ---- 增删改 ----
    def validate_name(self, name, exclude_self=False):
        name = (name or "").strip()
        if not name:
            return "请输入姓名"
        if len(name) > 10:
            return "姓名最多 10 个字"
        if name in self.names() and not exclude_self:
            return "这个姓名已经用过了"
        return None

    def validate_pin(self, pin):
        if not re.fullmatch(r"\d{4,6}", pin or ""):
            return "密码需为 4-6 位数字"
        return None

    def add_user(self, name, role, pin=None):
        name = (name or "").strip()
        err = self.validate_name(name)
        if err:
            return False, err
        if role == ROLE_PARENT:
            err = self.validate_pin(pin)
            if err:
                return False, err
        user = {"name": name, "role": role, "salt": None, "pw": None}
        if role == ROLE_PARENT:
            user["salt"], user["pw"] = make_pin_hash(pin)
        self.users.append(user)
        if not self.current:
            self.current = name
        self.save()
        return True, "已创建用户「%s」" % name

    def can_remove(self, name):
        u = self.find(name)
        if not u:
            return False, "用户不存在"
        if name == self.current:
            return False, "不能删除当前登录的用户"
        if len(self.users) <= 1:
            return False, "至少要保留一个用户"
        if u["role"] == ROLE_PARENT and len(self.parents()) <= 1:
            return False, "至少要保留一名家长"
        return True, ""

    def remove_user(self, name):
        ok, msg = self.can_remove(name)
        if not ok:
            return False, msg
        self.users = [u for u in self.users if u["name"] != name]
        self.save()
        return True, "已删除用户「%s」" % name

    def set_pin(self, name, pin):
        u = self.find(name)
        if not u:
            return False, "用户不存在"
        err = self.validate_pin(pin)
        if err:
            return False, err
        u["salt"], u["pw"] = make_pin_hash(pin)
        self.save()
        return True, "密码已修改"

    def set_current(self, name):
        if self.find(name):
            self.current = name
            self.save()
            return True
        return False


# ---------------------------------------------------------------------------
# 四、一轮答题的状态
# ---------------------------------------------------------------------------
class RoundState:
    def __init__(self, questions, mode, time_limit=None):
        self.questions = questions
        self.mode = mode
        self.time_limit = time_limit
        self.records = []
        self.index = 0
        self.start_ts = None
        self.elapsed = 0.0
        self.finished = False
        self.locked = False
        self.timed_out = False


# ---------------------------------------------------------------------------
# 五、模态对话框
# ---------------------------------------------------------------------------
class Modal(tk.Toplevel):
    def __init__(self, parent, title, w, h):
        super().__init__(parent, bg=PAGE_BG)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        try:
            parent.update_idletasks()
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 3)
            self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except tk.TclError:
            self.geometry("%dx%d" % (w, h))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.body = tk.Frame(self, bg=PAGE_BG)
        self.body.pack(fill="both", expand=True, padx=20, pady=16)

    def close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def show(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window()
        return self.result


def _pin_entry(parent, width=10):
    return tk.Entry(parent, show="●", justify="center", font=(FONT, 18), width=width,
                    bd=0, relief="flat", highlightthickness=2,
                    highlightbackground=BORDER, highlightcolor=BLUE,
                    insertbackground=BLUE)


class PinDialog(Modal):
    """家长密码验证"""

    def __init__(self, parent, store, user):
        super().__init__(parent, "家长验证", 380, 260)
        self.store, self.user = store, user
        tk.Label(self.body, text="请输入家长「%s」的密码" % user, bg=PAGE_BG,
                 fg=TEXT_DK, font=(FONT, 14)).pack(pady=(4, 12))
        self.pin = _pin_entry(self.body)
        self.pin.pack(ipady=4)
        self.pin.focus_set()
        self.err = tk.Label(self.body, text="", bg=PAGE_BG, fg=RED, font=(FONT, 11))
        self.err.pack(pady=(8, 0))
        btns = tk.Frame(self.body, bg=PAGE_BG)
        btns.pack(pady=(12, 0))
        make_button(btns, "确认", None, BLUE, WHITE, None, self.ok, 110, 40, 14, 11).pack(side="left", padx=6)
        make_button(btns, "取消", None, WHITE, TEXT_DK, None, self.close, 110, 40, 14, 11,
                    border=BORDER).pack(side="left", padx=6)
        tk.Label(self.body, text="忘记密码？删除软件旁的用户配置文件即可重置",
                 bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 11), wraplength=320).pack(pady=(14, 0))
        self.pin.bind("<Return>", lambda e: self.ok())

    def ok(self):
        if self.store.verify(self.user, self.pin.get().strip()):
            self.result = True
            self.close()
        else:
            self.err.config(text="密码错误，请重试")
            self.pin.delete(0, "end")
            self.pin.focus_set()


class PickUserDialog(Modal):
    """选择用户（切换用户 / 选择查看对象）"""

    def __init__(self, parent, store, title="切换用户", current=None):
        users = store.users
        h = 140 + 52 * max(1, len(users))
        super().__init__(parent, title, 380, min(h, 520))
        self.store, self.current = store, current
        tk.Label(self.body, text=title, bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 16, "bold")).pack(pady=(0, 10))
        for u in users:
            is_parent = u["role"] == ROLE_PARENT
            bg = CARD_BG if is_parent else WHITE
            row = tk.Frame(self.body, bg=bg, height=44,
                           highlightthickness=1, highlightbackground=BORDER)
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)
            icon = person_icon(row, 0, 0, 6, ORANGE if is_parent else BLUE, bg)
            icon.pack(side="left", padx=(12, 8))
            name = tk.Label(row, text=u["name"], bg=bg, fg=TITLE_DK,
                            font=(FONT, 14, "bold"))
            name.pack(side="left")
            tip = "家长 · 需密码" if is_parent else "学生 · 一键切换"
            t = tk.Label(row, text=tip, bg=bg, fg=ROLE_COLOR[u["role"]], font=(FONT, 11))
            t.pack(side="right", padx=12)
            if u["name"] == current:
                tk.Label(row, text="当前", bg=bg, fg=TEXT_MUT,
                         font=(FONT, 11)).pack(side="right", padx=6)
            for w in (row, name, t, icon):
                w.bind("<Button-1>", lambda e, n=u["name"]: self.choose(n))
                try:
                    w.config(cursor="hand2")
                except tk.TclError:
                    pass
        make_button(self.body, "取消", None, CARD_BG, TEXT_DK, None, self.close,
                    110, 36, 13, 11, border=BORDER).pack(pady=(12, 0))

    def choose(self, name):
        self.result = name
        self.close()


class AddUserDialog(Modal):
    """添加用户"""

    def __init__(self, parent, store):
        super().__init__(parent, "添加用户", 420, 400)
        self.store = store
        tk.Label(self.body, text="添加用户", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 16, "bold")).pack(pady=(0, 10))

        self.role = tk.StringVar(value=ROLE_CHILD)
        row = tk.Frame(self.body, bg=PAGE_BG)
        row.pack(pady=(0, 10))
        for val, txt in ((ROLE_CHILD, "孩子（免密码）"), (ROLE_PARENT, "家长（需密码）")):
            tk.Radiobutton(row, text=txt, value=val, variable=self.role,
                           bg=PAGE_BG, fg=TEXT_DK, font=(FONT, 12),
                           activebackground=PAGE_BG, selectcolor=WHITE,
                           command=self._sync_state).pack(side="left", padx=8)

        tk.Label(self.body, text="姓名", bg=PAGE_BG, fg=TEXT_MUT,
                 font=(FONT, 11)).pack(anchor="w")
        self.name = tk.Entry(self.body, font=(FONT, 14), bd=0, relief="flat",
                             highlightthickness=2, highlightbackground=BORDER,
                             highlightcolor=BLUE, insertbackground=BLUE)
        self.name.pack(fill="x", ipady=4, pady=(2, 10))

        self.pin_label = tk.Label(self.body, text="密码（4-6 位数字）", bg=PAGE_BG,
                                  fg=TEXT_MUT, font=(FONT, 11))
        self.pin_label.pack(anchor="w")
        self.pin = _pin_entry(self.body, width=12)
        self.pin.pack(anchor="w", ipady=3, pady=(2, 10))

        self.err = tk.Label(self.body, text="", bg=PAGE_BG, fg=RED, font=(FONT, 11))
        self.err.pack()
        btns = tk.Frame(self.body, bg=PAGE_BG)
        btns.pack(pady=(10, 0))
        make_button(btns, "确定", None, BLUE, WHITE, None, self.ok, 110, 40, 14, 11).pack(side="left", padx=6)
        make_button(btns, "取消", None, WHITE, TEXT_DK, None, self.close, 110, 40, 14, 11,
                    border=BORDER).pack(side="left", padx=6)
        self._sync_state()
        self.name.focus_set()

    def _sync_state(self):
        if self.role.get() == ROLE_PARENT:
            self.pin.config(state="normal", highlightbackground=BORDER)
        else:
            self.pin.delete(0, "end")
            self.pin.config(state="disabled", highlightbackground=CARD_BG)

    def ok(self):
        name = self.name.get().strip()
        role = self.role.get()
        pin = self.pin.get().strip() if role == ROLE_PARENT else None
        ok, msg = self.store.add_user(name, role, pin)
        if ok:
            self.result = name
            self.close()
        else:
            self.err.config(text=msg)


class ChangePinDialog(Modal):
    """修改家长密码"""

    def __init__(self, parent, store, user):
        super().__init__(parent, "修改密码", 400, 360)
        self.store, self.user = store, user
        tk.Label(self.body, text="修改「%s」的密码" % user, bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 16, "bold")).pack(pady=(0, 10))
        for label, attr in (("原密码", "old"), ("新密码（4-6 位数字）", "new"),
                            ("再输一遍新密码", "new2")):
            tk.Label(self.body, text=label, bg=PAGE_BG, fg=TEXT_MUT,
                     font=(FONT, 11)).pack(anchor="w")
            e = _pin_entry(self.body, width=12)
            e.pack(anchor="w", ipady=3, pady=(2, 8))
            setattr(self, attr, e)
        self.err = tk.Label(self.body, text="", bg=PAGE_BG, fg=RED, font=(FONT, 11))
        self.err.pack()
        btns = tk.Frame(self.body, bg=PAGE_BG)
        btns.pack(pady=(10, 0))
        make_button(btns, "确定", None, BLUE, WHITE, None, self.ok, 110, 40, 14, 11).pack(side="left", padx=6)
        make_button(btns, "取消", None, WHITE, TEXT_DK, None, self.close, 110, 40, 14, 11,
                    border=BORDER).pack(side="left", padx=6)
        self.old.focus_set()

    def ok(self):
        if not self.store.verify(self.user, self.old.get().strip()):
            self.err.config(text="原密码不正确")
            return
        new, new2 = self.new.get().strip(), self.new2.get().strip()
        if new != new2:
            self.err.config(text="两次输入的新密码不一致")
            return
        ok, msg = self.store.set_pin(self.user, new)
        if ok:
            self.result = True
            self.close()
        else:
            self.err.config(text=msg)


class QuitDialog(Modal):
    """答题中途关闭：两种退出都会记录成绩"""

    def __init__(self, parent, answered, right, can_save):
        super().__init__(parent, "提示", 420, 380)
        tk.Label(self.body, text="本次答题还没结束", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 15, "bold")).pack(pady=(4, 8))
        if can_save:
            tk.Label(self.body, text="已答 %d 题（对 %d 题）" % (answered, right),
                     bg=PAGE_BG, fg=TEXT_DK, font=(FONT, 13)).pack()
            tk.Label(self.body, text="两种退出都会记入历史，要看看成绩吗？", bg=PAGE_BG,
                     fg=TEXT_DK, font=(FONT, 13)).pack(pady=(4, 12))
            make_button(self.body, "记录并看成绩", None, GREEN, WHITE, None,
                        lambda: self.choose("save"), 250, 40, 14, 11).pack(pady=4)
            make_button(self.body, "记录后直接退出", None, WHITE, TEXT_DK, None,
                        lambda: self.choose("discard"), 250, 40, 14, 11,
                        border=BORDER).pack(pady=4)
        else:
            tk.Label(self.body, text="还没有作答，本次不会记录成绩", bg=PAGE_BG,
                     fg=TEXT_MUT, font=(FONT, 13)).pack(pady=(4, 12))
            make_button(self.body, "退出", None, WHITE, TEXT_DK, None,
                        lambda: self.choose("discard"), 250, 40, 14, 11,
                        border=BORDER).pack(pady=4)
        make_button(self.body, "继续答题", None, BLUE, WHITE, None,
                    lambda: self.choose("cancel"), 250, 40, 14, 11).pack(pady=4)
        if can_save:
            tk.Label(self.body, text="中途退出：得分按总题数计算，正确率按已作答计算，"
                                     "历史中标记「中途退出」",
                     bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 11),
                     wraplength=360).pack(pady=(10, 0))

    def choose(self, value):
        self.result = value
        self.close()


class RecordDetailDialog(Modal):
    """历史成绩详情：汇总统计 + 错题明细 + 重练本次错题"""

    def __init__(self, parent, rec, detail):
        super().__init__(parent, "成绩详情", 700, 580)
        items = (detail or {}).get("items", [])
        wrong_items = [it for it in items
                       if it.get("s") in ("wrong", "skip", "unanswered")]

        tk.Label(self.body, text="成绩详情", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 17, "bold")).pack(pady=(0, 6))
        tk.Label(self.body, text="%s　·　%s" % (rec["time"], rec["mode"]),
                 bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 11)).pack()
        tk.Label(self.body, text="得分 %d 分　·　答对 %d / 总题 %d　·　正确率 %d%%（作答 %d）"
                 % (rec["score"], rec["right"], rec["total"], rec["acc"], rec["answered"]),
                 bg=PAGE_BG, fg=score_color(rec["score"]),
                 font=(FONT, 14, "bold")).pack(pady=(8, 2))
        line2 = "跳过 %d · 未答 %d · 用时 %s" % (rec["skipped"], rec["unanswered"], rec["dur"])
        if rec["flag"]:
            line2 += " · " + rec["flag"]
        tk.Label(self.body, text=line2, bg=PAGE_BG, fg=TEXT_DK,
                 font=(FONT, 11)).pack(pady=(0, 8))

        if wrong_items:
            tk.Label(self.body, text="本次错题与跳过（共 %d 道）" % len(wrong_items),
                     bg=PAGE_BG, fg=TEXT_DK, font=(FONT, 12, "bold")).pack(anchor="w",
                                                                          padx=10, pady=(2, 4))
            wrap = tk.Frame(self.body, bg=PAGE_BG)
            wrap.pack(fill="both", expand=True, padx=10)
            canvas = tk.Canvas(wrap, bg=PAGE_BG, highlightthickness=0, height=250)
            sb = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
            inner = tk.Frame(canvas, bg=PAGE_BG)
            win = canvas.create_window((0, 0), window=inner, anchor="nw")
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            inner.bind("<Configure>",
                       lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>",
                        lambda e: canvas.itemconfigure(win, width=e.width))

            head = tk.Frame(inner, bg=CARD_BG)
            head.pack(fill="x", pady=(0, 2))
            for label, col, w in (("题目", 0, 240), ("你的答案", 1, 140), ("正确答案", 2, 140)):
                lbl = tk.Label(head, text=label, bg=CARD_BG, fg=TEXT_MUT, font=(FONT, 12),
                               anchor="w", padx=8, pady=6)
                lbl.grid(row=0, column=col, sticky="w")
                head.grid_columnconfigure(col, minsize=w)
                lbl.bind("<MouseWheel>", lambda e, c=canvas: c.yview_scroll(
                    int(-e.delta / 120), "units"))

            labels = {"right": "答对", "wrong": "答错", "skip": "跳过", "unanswered": "未答"}
            for i, it in enumerate(wrong_items):
                bg = CARD_BG if i % 2 == 0 else WHITE
                row = tk.Frame(inner, bg=bg)
                row.pack(fill="x", pady=1)
                cells = [
                    (it.get("q", ""), 0, 240, TITLE_DK, 14, True),
                    (("跳过" if it.get("s") == "skip" else
                      ("未答" if it.get("s") == "unanswered" else str(it.get("a", "")))),
                     1, 140, RED if it.get("s") == "wrong" else TEXT_MUT, 14,
                     it.get("s") == "wrong"),
                    (str(it.get("c", "")), 2, 140, SCORE_GREEN, 14, True),
                ]
                for text, col, w, fg, size, bold in cells:
                    lbl = tk.Label(row, text=text, bg=bg, fg=fg,
                                   font=(FONT, size, "bold" if bold else "normal"),
                                   anchor="w", padx=8, pady=6)
                    lbl.grid(row=0, column=col, sticky="w")
                    row.grid_columnconfigure(col, minsize=w)
                    lbl.bind("<MouseWheel>", lambda e, c=canvas: c.yview_scroll(
                        int(-e.delta / 120), "units"))
        else:
            tk.Label(self.body, text="本次全部答对，没有错题！", bg=PAGE_BG, fg=SCORE_GREEN,
                     font=(FONT, 14, "bold")).pack(pady=30)

        btns = tk.Frame(self.body, bg=PAGE_BG)
        btns.pack(pady=(10, 0))
        if wrong_items:
            make_button(btns, "重练本次错题", None, ORANGE, WHITE, None,
                        lambda: self.choose(("review", wrong_items)),
                        170, 44, 14, 11).pack(side="left", padx=8)
        make_button(btns, "关闭", None, CARD_BG, TEXT_DK, None,
                    lambda: self.choose(("close", None)), 120, 44, 14, 11,
                    border=BORDER).pack(side="left", padx=8)
        if wrong_items:
            tk.Label(self.body, text="重练成绩不计入历史", bg=PAGE_BG, fg=TEXT_MUT,
                     font=(FONT, 11)).pack(pady=(8, 0))

    def choose(self, value):
        self.result = value
        self.close()


# ---------------------------------------------------------------------------
# 六、主程序
# ---------------------------------------------------------------------------
class App:
    def __init__(self, root, selftest=False, base_dir=None):
        self.root = root
        self.selftest = selftest
        self.base_dir = base_dir or resolve_base_dir()
        self.store = UserStore(self.base_dir)
        self.round = None
        self.result_data = None
        self.screen = "menu"
        self._hint_is_error = False
        self.wrong_rows_count = 0
        self.history_rows_count = 0
        self.hist_view_user = None
        self.wizard_parent = None

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
        self._build_users()
        self._build_wizard()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        for seq in ("<Return>", "<KP_Enter>"):
            root.bind_all(seq, self._on_enter_key)

        self._migrate_data_if_needed()

        if self.store.has_users():
            self.show_menu()
        else:
            self.show_wizard()

    def _migrate_data_if_needed(self):
        """v1.1 → v1.2：历史格式升级，按用户确认清空旧记录"""
        if getattr(self.store, "data_version", DATA_VERSION) >= DATA_VERSION:
            return
        self.wipe_all_history()
        self.store.set_data_version(DATA_VERSION)

    def wipe_all_history(self):
        """清空所有用户的历史记录与明细"""
        for name in self.store.names():          # 注意：这里是用户名，不是用户字典
            try:
                with open(self.history_path(name), "w", encoding="utf-8") as fp:
                    fp.write(HISTORY_HEADER)
            except Exception:
                pass
            try:
                os.remove(self.detail_path(name))
            except Exception:
                pass

    # ---------------- 通用 ----------------
    def _center_window(self):
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = max(0, (sw - WINDOW_W) // 2)
        y = max(0, (sh - WINDOW_H) // 2 - 20)
        self.root.geometry("%dx%d+%d+%d" % (WINDOW_W, WINDOW_H, x, y))

    def _show(self, name):
        for s in self.screens.values():
            s.pack_forget()
        self.screens[name].pack(fill="both", expand=True)
        self.screen = name

    def current_user(self):
        return self.store.current

    def is_parent(self):
        return self.store.is_parent()

    def can_delete_records(self):
        """删改历史记录的权限：仅家长"""
        return self.is_parent()

    def on_close(self):
        if self.round and not self.round.finished and self.screen == "quiz":
            self._ask_quit_round()
            return
        self.root.destroy()

    # ---------------- 主菜单 ----------------
    def _build_menu(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["menu"] = f

        bar_wrap = tk.Frame(f, bg=PAGE_BG)
        bar_wrap.pack(fill="x", padx=40, pady=(16, 0))
        self.user_bar = tk.Frame(bar_wrap, bg=BLUE_LT, height=46)
        self.user_bar.pack(fill="x")
        self.user_bar.pack_propagate(False)
        self.user_icon_holder = tk.Frame(self.user_bar, bg=BLUE_LT)
        self.user_icon_holder.pack(side="left", padx=(14, 4))
        self.user_label = tk.Label(self.user_bar, text="", bg=BLUE_LT, fg=TEXT_DK,
                                   font=(FONT, 13, "bold"))
        self.user_label.pack(side="left")
        make_button(self.user_bar, "切换", None, WHITE, TEXT_DK, None,
                    self.open_switch_dialog, 66, 30, 12, 11,
                    border=BORDER).pack(side="right", padx=10)

        tk.Label(f, text="100 以内加减法", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 32, "bold")).pack(pady=(26, 4))
        tk.Label(f, text="小学二年级口算练习", bg=PAGE_BG, fg=TEXT_MUT,
                 font=(FONT, 13)).pack()

        wrap = tk.Frame(f, bg=PAGE_BG)
        wrap.pack(pady=24)
        make_button(wrap, "练习模式", "20道题 · 不限时间", BLUE, WHITE, BLUE_LT,
                    self.start_practice, 340, 96, 21, 12).pack(pady=8)
        make_button(wrap, "测验模式", "100道题 · 限时20分钟", ORANGE, WHITE, ORANGE_LT,
                    self.start_test, 340, 96, 21, 12).pack(pady=8)

        small = tk.Frame(f, bg=PAGE_BG)
        small.pack(pady=(6, 0))
        make_button(small, "历史成绩", None, CARD_BG, TEXT_DK, None,
                    self.show_history, 150, 40, 13, 11, border=BORDER).pack(side="left", padx=6)
        self.manage_btn = make_button(small, "用户管理", None, CARD_BG, TEXT_DK, None,
                                      self.show_users, 150, 40, 13, 11, border=BORDER)

        tk.Label(f, text="选一个开始吧！", bg=PAGE_BG, fg=TEXT_MUT,
                 font=(FONT, 12)).pack(pady=(14, 0))

    def refresh_user_bar(self):
        for w in self.user_icon_holder.winfo_children():
            w.destroy()
        name = self.current_user()
        if not name:
            return
        role = self.store.role_of(name)
        color = ORANGE if role == ROLE_PARENT else BLUE
        person_icon(self.user_icon_holder, 0, 0, 7, color, BLUE_LT).pack()
        self.user_label.config(text="当前：%s（%s）" % (name, ROLE_NAME[role]))
        if role == ROLE_PARENT:
            if not self.manage_btn.winfo_ismapped():
                self.manage_btn.pack(side="left", padx=6)
        else:
            self.manage_btn.pack_forget()

    def show_menu(self):
        self.round = None
        self.result_data = None
        self.hist_view_user = self.current_user()
        self.refresh_user_bar()
        self._show("menu")

    def open_switch_dialog(self):
        name = PickUserDialog(self.root, self.store, "切换用户",
                              current=self.current_user()).show()
        if not name or name == self.current_user():
            return
        if self.store.requires_pin(name) and not PinDialog(self.root, self.store, name).show():
            return
        self.switch_user(name)

    def switch_user(self, name):
        self.store.set_current(name)
        self.result_data = None
        self.hist_view_user = name
        self.show_menu()

    # ---------------- 首次运行向导 ----------------
    def _build_wizard(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["wizard"] = f
        tk.Label(f, text="欢迎使用口算小达人", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 26, "bold")).pack(pady=(44, 6))
        tk.Label(f, text="先创建家庭成员，之后可以随时在主界面切换",
                 bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 13)).pack()
        self.wiz_step_label = tk.Label(f, text="", bg=PAGE_BG, fg=TEXT_DK,
                                       font=(FONT, 15, "bold"))
        self.wiz_step_label.pack(pady=(22, 12))

        self.wiz_body = tk.Frame(f, bg=CARD_BG, width=520, height=340)
        self.wiz_body.pack()
        self.wiz_body.pack_propagate(False)
        self.wiz_step1 = tk.Frame(self.wiz_body, bg=CARD_BG)
        self.wiz_step2 = tk.Frame(self.wiz_body, bg=CARD_BG)
        self._build_wizard_step1()
        self._build_wizard_step2()

    def _wiz_field(self, parent, label):
        tk.Label(parent, text=label, bg=CARD_BG, fg=TEXT_MUT,
                 font=(FONT, 11)).pack(anchor="w")
        e = tk.Entry(parent, font=(FONT, 14), width=24, bd=0, relief="flat",
                     highlightthickness=2, highlightbackground=BORDER,
                     highlightcolor=BLUE, insertbackground=BLUE)
        e.pack(ipady=4, pady=(2, 8))
        return e

    def _build_wizard_step1(self):
        p = self.wiz_step1
        self.wp_name = self._wiz_field(p, "家长姓名")
        tk.Label(p, text="设置密码（4-6 位数字）", bg=CARD_BG, fg=TEXT_MUT,
                 font=(FONT, 11)).pack(anchor="w")
        self.wp_pin = _pin_entry(p, width=12)
        self.wp_pin.pack(anchor="w", ipady=3, pady=(2, 8))
        tk.Label(p, text="再输一遍密码", bg=CARD_BG, fg=TEXT_MUT,
                 font=(FONT, 11)).pack(anchor="w")
        self.wp_pin2 = _pin_entry(p, width=12)
        self.wp_pin2.pack(anchor="w", ipady=3, pady=(2, 6))
        self.wiz_err = tk.Label(p, text="", bg=CARD_BG, fg=RED, font=(FONT, 11))
        self.wiz_err.pack()
        make_button(p, "下一步", None, BLUE, WHITE, None, self.wizard_next,
                    150, 40, 14, 11).pack(pady=(8, 0))

    def _build_wizard_step2(self):
        p = self.wiz_step2
        self.wc_name = self._wiz_field(p, "孩子姓名")
        self.wiz_err2 = tk.Label(p, text="", bg=CARD_BG, fg=RED, font=(FONT, 11))
        self.wiz_err2.pack(pady=(6, 0))
        make_button(p, "完成，开始使用", None, GREEN, WHITE, None, self.wizard_finish,
                    220, 44, 14, 11).pack(pady=(16, 0))
        tk.Label(p, text="之后可以在「用户管理」里添加更多孩子或家长",
                 bg=CARD_BG, fg=TEXT_MUT, font=(FONT, 11)).pack(pady=(12, 0))

    def show_wizard(self):
        self.wiz_step1.pack(fill="both", expand=True, padx=40, pady=20)
        self.wiz_step2.pack_forget()
        self.wiz_step_label.config(text="第 1 步 / 共 2 步：创建家长")
        self.wiz_err.config(text="")
        self.wp_name.delete(0, "end")
        self.wp_pin.delete(0, "end")
        self.wp_pin2.delete(0, "end")
        self._show("wizard")
        self.wp_name.focus_set()

    def wizard_next(self):
        name = self.wp_name.get().strip()
        pin, pin2 = self.wp_pin.get().strip(), self.wp_pin2.get().strip()
        err = self.store.validate_name(name)
        if not err:
            err = self.store.validate_pin(pin)
        if not err and pin != pin2:
            err = "两次输入的密码不一致"
        if err:
            self.wiz_err.config(text=err)
            return
        self.store.add_user(name, ROLE_PARENT, pin)
        self.wizard_parent = name
        self.wiz_step1.pack_forget()
        self.wiz_step2.pack(fill="both", expand=True, padx=40, pady=20)
        self.wiz_step_label.config(text="第 2 步 / 共 2 步：创建孩子")
        self.wc_name.delete(0, "end")
        self.wiz_err2.config(text="")
        self.wc_name.focus_set()

    def wizard_finish(self):
        name = self.wc_name.get().strip()
        err = self.store.validate_name(name)
        if err:
            self.wiz_err2.config(text=err)
            return
        self.store.add_user(name, ROLE_CHILD)
        self.store.set_current(name)
        self.show_menu()

    # ---------------- 答题界面 ----------------
    def _build_quiz(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["quiz"] = f

        top = tk.Frame(f, bg=PAGE_BG)
        top.pack(fill="x", padx=50, pady=(24, 0))
        self.q_label = tk.Label(top, text="", bg=PAGE_BG, fg=TEXT_DK, font=(FONT, 16, "bold"))
        self.q_label.pack(side="left")
        self.quiz_user_label = tk.Label(top, text="", bg=PAGE_BG, fg=TEXT_MUT,
                                        font=(FONT, 11))
        self.quiz_user_label.pack(side="left", padx=12)

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
        return len(proposed) <= 3 and all(c in "0123456789" for c in proposed)

    def _clear_error(self, event=None):
        if event is not None and getattr(event, "keysym", "") in ("Return", "KP_Enter"):
            return
        if self._hint_is_error:
            self._hint_is_error = False
            self.hint.config(text="按回车键进入下一题", fg=TEXT_MUT)
            self.entry.config(highlightbackground=BLUE, highlightcolor=BLUE)

    def _flash_empty(self):
        self._hint_is_error = True
        self.hint.config(text="请先输入答案，或点击【跳过】", fg=RED)
        self.entry.config(highlightbackground=RED, highlightcolor=RED)

    def _update_quiz_top(self):
        rs = self.round
        self.q_label.config(text="第 %d 题 / 共 %d 题" % (rs.index + 1, len(rs.questions)))
        self.quiz_user_label.config(text="答题人：%s" % self.current_user())
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
        if not self.result_data or not self.result_data["wrong"]:
            return
        qs = [r["q"] for r in self.result_data["wrong"]]
        random.shuffle(qs)
        self._begin_round(qs, MODE_REVIEW, None)

    def _schedule_tick(self):
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

    def _build_result_data(self, rs, partial=False):
        """汇总本轮结果：得分/正确率口径见 compute_stats"""
        st = compute_stats(rs.records, len(rs.questions))
        st.update({
            "mode": rs.mode, "elapsed": rs.elapsed, "timed_out": rs.timed_out,
            "partial": partial, "stars": stars_of_score(st["score"]),
            "records": list(rs.records),
            "wrong": [r for r in rs.records
                      if r["status"] in ("wrong", "skip", "unanswered")],
        })
        return st

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
        # 时间到未作答的题：记为「未答」（不计入正确率分母）
        while len(rs.records) < total:
            rs.records.append({"q": rs.questions[len(rs.records)], "ans": None,
                               "status": "unanswered"})
        self.result_data = self._build_result_data(rs)
        if rs.mode in (MODE_PRACTICE, MODE_TEST):
            self.save_history(self.current_user(), self.result_data)
        self._show_result()

    def _ask_quit_round(self):
        """答题中途关闭：两种退出都会记录成绩（已答 0 题除外）"""
        rs = self.round
        answered = sum(1 for r in rs.records if r["status"] in ("right", "wrong"))
        right = sum(1 for r in rs.records if r["status"] == "right")
        choice = QuitDialog(self.root, answered, right, answered >= 1).show()
        if choice == "save":
            self.save_partial_and_exit(show_result=True)
        elif choice == "discard":
            self.save_partial_and_exit(show_result=False)

    def save_partial_and_exit(self, show_result=True):
        """中断退出：记录已答部分（得分按总题数、正确率按已作答），标记「中途退出」"""
        rs = self.round
        if not rs or not rs.records:
            self.round = None
            self.show_menu()
            return
        rs.finished = True
        rs.elapsed = max(0.0, time.time() - (rs.start_ts or time.time()))
        self.result_data = self._build_result_data(rs, partial=True)
        if rs.mode in (MODE_PRACTICE, MODE_TEST):
            self.save_history(self.current_user(), self.result_data)
        if show_result:
            self._show_result()
        else:
            self.round = None
            self.show_menu()

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
        self.res_stars.config(text="★" * d["stars"] + "☆" * (3 - d["stars"]) +
                                   "  " + encouragement(d["score"]))
        self.res_score.config(text="得分 %d 分" % d["score"],
                              fg=score_color(d["score"]))
        self.res_right.config(text="答对 %d 题 / 共 %d 题" % (d["right"], d["total"]))
        extra = "作答 %d · 跳过 %d" % (d["answered"], d["skipped"])
        if d["unanswered"]:
            extra += " · 未答 %d" % d["unanswered"]
        self.res_detail.config(text="正确率 %d%%（%s）　·　用时 %s"
                                    % (round(d["acc"] * 100), extra,
                                       fmt_duration(d["elapsed"])))
        if d.get("partial"):
            self.res_note.config(text="中途退出：得分按总题数 %d 计算" % d["total"])
        elif d["mode"] == MODE_TEST:
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
            self.wrong_sb.pack_forget()
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
                elif r["status"] == "unanswered":
                    self._cell(line, "未答", 1, 150, TEXT_MUT, 13, bg=bg)
                else:
                    self._cell(line, "%s" % r["ans"], 1, 150, RED, 14, bold=True, bg=bg)
                self._cell(line, "%d" % q.answer, 2, 150, GREEN, 14, bold=True, bg=bg)

        targets = [self.wrong_canvas, self.wrong_inner] + self.wrong_inner.winfo_children()
        for w in targets:
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

    # ---------------- 历史成绩（按用户隔离） ----------------
    def history_path(self, user):
        return os.path.join(self.base_dir, HISTORY_PREFIX + safe_filename(user) + ".txt")

    def detail_path(self, user):
        return os.path.join(self.base_dir, HISTORY_DETAIL_PREFIX + safe_filename(user) + ".jsonl")

    def save_history(self, user, data):
        """追加一条成绩到 txt，同时写一条明细到 jsonl（供历史详情与重练）"""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        flag = ""
        if data.get("partial"):
            flag = "中途退出"
        elif data.get("timed_out"):
            flag = "时间到"
        line = ("%s | %s | 得分 %d | 答对 %d | 作答 %d | 跳过 %d | 未答 %d | 总题 %d "
                "| 正确率 %d%% | 用时 %s" % (
                    ts, MODE_NAME[data["mode"]], data["score"], data["right"],
                    data["answered"], data["skipped"], data["unanswered"],
                    data["total"], round(data["acc"] * 100),
                    fmt_duration(data["elapsed"])))
        if flag:
            line += " | " + flag
        try:
            path = self.history_path(user)
            new_file = (not os.path.exists(path)) or os.path.getsize(path) == 0
            with open(path, "a", encoding="utf-8") as fp:
                if new_file:
                    fp.write(HISTORY_HEADER)
                fp.write(line + "\n")
            detail = {
                "time": ts, "mode": data["mode"], "total": data["total"],
                "right": data["right"], "answered": data["answered"],
                "skipped": data["skipped"], "unanswered": data["unanswered"],
                "score": data["score"], "acc": round(data["acc"] * 100),
                "elapsed": int(data["elapsed"]), "flag": flag,
                "items": [{"q": r["q"].text, "a": r["ans"], "c": r["q"].answer,
                           "s": r["status"]} for r in data.get("records", [])],
            }
            with open(self.detail_path(user), "a", encoding="utf-8") as fp:
                fp.write(json.dumps(detail, ensure_ascii=False) + "\n")
            return True
        except Exception:
            return False

    def read_history(self, user):
        """读取某用户历史（最新在前）；带物理行号 line_no 与明细序号 data_idx"""
        pat = re.compile(
            r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (\S+) \| 得分 (\d+) \| 答对 (\d+) "
            r"\| 作答 (\d+) \| 跳过 (\d+) \| 未答 (\d+) \| 总题 (\d+) \| 正确率 (\d+)% "
            r"\| 用时 (.+?)( \| (时间到|中途退出))?$")
        out = []
        data_idx = 0
        try:
            with open(self.history_path(user), "r", encoding="utf-8") as fp:
                for idx, raw in enumerate(fp):
                    m = pat.match(raw.strip())
                    if m:
                        out.append({
                            "line_no": idx, "data_idx": data_idx,
                            "time": m.group(1), "mode": m.group(2),
                            "score": int(m.group(3)), "right": int(m.group(4)),
                            "answered": int(m.group(5)), "skipped": int(m.group(6)),
                            "unanswered": int(m.group(7)), "total": int(m.group(8)),
                            "acc": int(m.group(9)), "dur": m.group(10),
                            "flag": m.group(12) or "",
                        })
                        data_idx += 1
        except Exception:
            pass
        out.reverse()
        return out

    def read_detail(self, user, data_idx):
        """读取某条历史记录对应的明细（错题列表等）"""
        if data_idx is None:
            return None
        try:
            with open(self.detail_path(user), "r", encoding="utf-8") as fp:
                lines = fp.readlines()
            if 0 <= data_idx < len(lines):
                return json.loads(lines[data_idx])
        except Exception:
            pass
        return None

    def delete_history_record(self, user, rec):
        """删除一条记录（仅家长）；同时删除对应明细"""
        if not self.can_delete_records():
            return False
        try:
            line_no = rec["line_no"] if isinstance(rec, dict) else int(rec)
            path = self.history_path(user)
            with open(path, "r", encoding="utf-8") as fp:
                lines = fp.readlines()
            if not (0 <= line_no < len(lines)):
                return False
            del lines[line_no]
            with open(path, "w", encoding="utf-8") as fp:
                fp.writelines(lines)
            if isinstance(rec, dict):
                self._delete_detail_line(user, rec.get("data_idx"))
            return True
        except Exception:
            return False

    def _delete_detail_line(self, user, data_idx):
        if data_idx is None:
            return
        try:
            path = self.detail_path(user)
            with open(path, "r", encoding="utf-8") as fp:
                lines = fp.readlines()
            if 0 <= data_idx < len(lines):
                del lines[data_idx]
                with open(path, "w", encoding="utf-8") as fp:
                    fp.writelines(lines)
        except Exception:
            pass

    def clear_history(self, user):
        """清空某用户历史与明细（仅家长）"""
        if not self.can_delete_records():
            return False
        try:
            with open(self.history_path(user), "w", encoding="utf-8") as fp:
                fp.write(HISTORY_HEADER)
            try:
                os.remove(self.detail_path(user))
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _build_history(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["history"] = f
        tk.Label(f, text="历史成绩", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 26, "bold")).pack(pady=(24, 2))
        self.hist_sum = tk.Label(f, text="", bg=PAGE_BG, fg=TEXT_DK, font=(FONT, 14, "bold"))
        self.hist_sum.pack(pady=(2, 6))
        self.hist_view_btn_holder = tk.Frame(f, bg=PAGE_BG)
        self.hist_view_btn_holder.pack()

        table = tk.Frame(f, bg=PAGE_BG)
        table.pack(fill="both", expand=True, padx=36, pady=(8, 0))
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

        self.hist_footer = tk.Label(f, text="", bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 11))
        self.hist_footer.pack(pady=(6, 4))
        self.hist_btns = tk.Frame(f, bg=PAGE_BG)
        self.hist_btns.pack(pady=(0, 18))

    def show_history(self, view_user=None):
        user = view_user or self.hist_view_user or self.current_user()
        if not user:
            self.show_menu()
            return
        self.hist_view_user = user
        parent = self.can_delete_records()

        for holder in (self.hist_inner, self.hist_btns, self.hist_view_btn_holder):
            for w in holder.winfo_children():
                w.destroy()

        recs = self.read_history(user)
        self.history_rows_count = min(len(recs), HISTORY_DISPLAY_MAX)

        if parent and len(self.store.users) > 1:
            make_button(self.hist_view_btn_holder,
                        "查看：%s（%s）▾" % (user, ROLE_NAME[self.store.role_of(user)]),
                        None, CARD_BG, TEXT_DK, None, self._pick_view_user,
                        220, 34, 12, 11, border=BORDER).pack()

        if recs:
            self.hist_sb.pack(side="right", fill="y")
            avg = round(sum(r["score"] for r in recs) / float(len(recs)))
            self.hist_sum.config(text="共练习 %d 次 · 平均得分 %d 分（显示最近 %d 次）"
                                      % (len(recs), avg, self.history_rows_count))
            head = tk.Frame(self.hist_inner, bg=CARD_BG)
            head.pack(fill="x", pady=(0, 2))
            cols = [("时间", 0, 190), ("模式", 1, 90), ("得分", 2, 80),
                    ("正确率", 3, 90), ("用时", 4, 130), ("标记", 5, 100)]
            if parent:
                cols.append(("操作", 6, 70))
            for label, col, w in cols:
                self._cell3(head, label, col, w, TEXT_MUT, 12, bold=False, bg=CARD_BG)

            for i, r in enumerate(recs[:HISTORY_DISPLAY_MAX]):
                bg = CARD_BG if i % 2 == 0 else WHITE
                line = tk.Frame(self.hist_inner, bg=bg)
                line.pack(fill="x", pady=1)
                self._cell3(line, r["time"], 0, 190, TEXT_DK, 13, bg=bg)
                self._cell3(line, r["mode"], 1, 90,
                            BLUE if r["mode"] == "练习模式" else ORANGE, 13, bg=bg)
                self._cell3(line, "%d分" % r["score"], 2, 80,
                            score_color(r["score"]), 13, bg=bg)
                self._cell3(line, "%d%%" % r["acc"], 3, 90, TEXT_DK, 13, bg=bg)
                self._cell3(line, r["dur"], 4, 130, TEXT_DK, 13, bg=bg)
                self._cell3(line, r["flag"], 5, 100,
                            RED if r["flag"] else TEXT_MUT, 12, bg=bg)
                holder = tk.Frame(line, bg=bg, width=70, height=30)
                holder.grid(row=0, column=6, sticky="w")
                holder.grid_propagate(False)
                make_button(holder, "详", None, WHITE, "#185FA5", None,
                            lambda u=user, rr=r: self.show_record_detail(u, rr),
                            30, 24, 11, 11, border=BLUE).pack(side="left", padx=(0, 2))
                if parent:
                    make_button(holder, "删", None, WHITE, RED, None,
                                lambda u=user, rr=r: self._delete_record(u, rr),
                                30, 24, 11, 11, border=RED).pack(side="left")
            self.hist_footer.config(text="共 %d 条记录 · 点击【详】查看当次答题详情" % len(recs))
        else:
            self.hist_sb.pack_forget()
            self.hist_sum.config(text="还没有记录，快去练习吧！")
            tk.Label(self.hist_inner, text="完成一轮练习或测验后，成绩会出现在这里",
                     bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 14)).pack(pady=30)
            self.hist_footer.config(text="")

        if parent:
            make_button(self.hist_btns, "清空记录", None, WHITE, RED, None,
                        lambda: self._clear_records(user), 150, 46, 14, 11,
                        border=RED).pack(side="left", padx=8)
        make_button(self.hist_btns, "返回菜单", None, CARD_BG, TEXT_DK, None,
                    self.show_menu, 150, 46, 14, 11, border=BORDER).pack(side="left", padx=8)

        targets = [self.hist_canvas, self.hist_inner] + self.hist_inner.winfo_children()
        for w in targets:
            w.bind("<MouseWheel>", self._on_mousewheel_hist)
        self._show("history")

    def show_record_detail(self, user, rec):
        """历史记录详情（孩子也可查看自己的记录）"""
        detail = self.read_detail(user, rec.get("data_idx"))
        res = RecordDetailDialog(self.root, rec, detail).show()
        if res and res[0] == "review":
            self.start_review_items(res[1])

    def start_review_items(self, items):
        """用某次记录的错题重新组卷（不计入历史）"""
        qs = []
        for it in items:
            q = question_from_text(it.get("q", ""))
            if q:
                qs.append(q)
        if not qs:
            messagebox.showinfo(APP_TITLE, "这次没有可重练的题目")
            return
        random.shuffle(qs)
        self._begin_round(qs, MODE_REVIEW, None)

    def _pick_view_user(self):
        name = PickUserDialog(self.root, self.store, "选择查看对象",
                              current=self.hist_view_user).show()
        if name:
            self.show_history(name)

    def _delete_record(self, user, rec):
        if not self.can_delete_records():
            messagebox.showinfo(APP_TITLE, "只有家长可以删除历史记录")
            return
        if messagebox.askyesno(APP_TITLE, "确定删除这条成绩记录吗？"):
            if self.delete_history_record(user, rec):
                self.show_history(user)

    def _clear_records(self, user):
        if not self.can_delete_records():
            messagebox.showinfo(APP_TITLE, "只有家长可以清空历史记录")
            return
        if messagebox.askyesno(APP_TITLE,
                               "确定清空「%s」的全部成绩记录吗？\n此操作不可撤销。" % user):
            if self.clear_history(user):
                self.show_history(user)

    def _cell3(self, parent, text, col, width, fg, size, bold=True, bg=WHITE):
        lbl = tk.Label(parent, text=text, bg=bg, fg=fg,
                       font=(FONT, size, "bold" if bold else "normal"),
                       anchor="w", padx=8, pady=6)
        lbl.grid(row=0, column=col, sticky="w")
        parent.grid_columnconfigure(col, minsize=width)
        lbl.bind("<MouseWheel>", self._on_mousewheel_hist)
        return lbl

    def _on_mousewheel_hist(self, event):
        try:
            self.hist_canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass

    # ---------------- 用户管理（仅家长） ----------------
    def _build_users(self):
        f = tk.Frame(self.container, bg=PAGE_BG)
        self.screens["users"] = f
        tk.Label(f, text="用户管理", bg=PAGE_BG, fg=TITLE_DK,
                 font=(FONT, 26, "bold")).pack(pady=(40, 4))
        self.users_hint = tk.Label(f, text="", bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 12))
        self.users_hint.pack(pady=(0, 14))
        self.users_list = tk.Frame(f, bg=PAGE_BG, width=560, height=200)
        self.users_list.pack()
        self.users_list.pack_propagate(False)
        btns = tk.Frame(f, bg=PAGE_BG)
        btns.pack(pady=(20, 0))
        make_button(btns, "添加用户", None, BLUE, WHITE, None, self.add_user_dialog,
                    160, 46, 14, 11).pack(side="left", padx=8)
        make_button(btns, "修改密码", None, WHITE, TEXT_DK, None, self.change_pin_dialog,
                    160, 46, 14, 11, border=BORDER).pack(side="left", padx=8)
        make_button(btns, "返回菜单", None, CARD_BG, TEXT_DK, None, self.show_menu,
                    160, 46, 14, 11, border=BORDER).pack(side="left", padx=8)
        tk.Label(f, text="规则：不能删除当前登录用户；至少保留一名家长；"
                         "删除用户会同时删除其历史记录",
                 bg=PAGE_BG, fg=TEXT_MUT, font=(FONT, 11)).pack(pady=(16, 0))

    def show_users(self):
        if not self.is_parent():
            messagebox.showinfo(APP_TITLE, "只有家长可以管理用户")
            self.show_menu()
            return
        for w in self.users_list.winfo_children():
            w.destroy()
        self.users_hint.config(text="当前登录：%s（%s）" % (
            self.current_user(), ROLE_NAME[self.store.role_of(self.current_user())]))
        for u in self.store.users:
            role = u["role"]
            bg = CARD_BG if role == ROLE_PARENT else WHITE
            row = tk.Frame(self.users_list, bg=bg, height=52,
                           highlightthickness=1, highlightbackground=BORDER)
            row.pack(fill="x", pady=4)
            row.pack_propagate(False)
            person_icon(row, 0, 0, 8, ORANGE if role == ROLE_PARENT else BLUE,
                        bg).pack(side="left", padx=(14, 10))
            tk.Label(row, text=u["name"], bg=bg, fg=TITLE_DK,
                     font=(FONT, 15, "bold")).pack(side="left")
            tk.Label(row, text=ROLE_NAME[role], bg=bg, fg=ROLE_COLOR[role],
                     font=(FONT, 12)).pack(side="left", padx=12)
            if u["name"] == self.current_user():
                tk.Label(row, text="当前登录", bg=bg, fg=TEXT_MUT,
                         font=(FONT, 11)).pack(side="right", padx=(0, 12))
            can, _msg = self.store.can_remove(u["name"])
            if can:
                make_button(row, "删除", None, WHITE, RED, None,
                            lambda n=u["name"]: self.remove_user_dialog(n),
                            66, 30, 12, 11, border=RED).pack(side="right", padx=10)
            else:
                tk.Label(row, text="不可删除", bg=bg, fg=TEXT_MUT,
                         font=(FONT, 11)).pack(side="right", padx=(0, 12))
        self._show("users")

    def add_user_dialog(self):
        if not self.is_parent():
            return
        name = AddUserDialog(self.root, self.store).show()
        if name:
            self.show_users()

    def remove_user_dialog(self, name):
        if not self.is_parent():
            return
        can, msg = self.store.can_remove(name)
        if not can:
            messagebox.showinfo(APP_TITLE, msg)
            return
        if not messagebox.askyesno(APP_TITLE,
                                   "确定删除用户「%s」吗？\n其历史成绩也会一起删除。" % name):
            return
        ok, msg = self.store.remove_user(name)
        if ok:
            try:
                os.remove(self.history_path(name))
            except Exception:
                pass
        else:
            messagebox.showinfo(APP_TITLE, msg)
        self.show_users()

    def change_pin_dialog(self):
        if not self.is_parent():
            return
        if ChangePinDialog(self.root, self.store, self.current_user()).show():
            messagebox.showinfo(APP_TITLE, "密码已修改")


# ---------------------------------------------------------------------------
# 七、自检
# ---------------------------------------------------------------------------
def _validate_round(qs, n):
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

    out("=" * 66)
    out("口算小达人 v1.2 自检")
    out("=" * 66)

    # ---- 1. 出题引擎 ----
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
    qs = []
    for _ in range(100):
        qs += generate_round(100)
    ratio = sum(1 for q in qs if q.op == "+") / float(len(qs))
    check("加减法比例接近均衡（加法 %.1f%%）" % (ratio * 100), 0.42 <= ratio <= 0.58, ratio)

    # ---- 2. 交互与流程 ----
    out("\n[2] 交互与流程（模拟界面操作）")
    root = tk.Tk()
    root.withdraw()
    tmp_dir = tempfile.mkdtemp(prefix="ksx_test_")
    app = App(root, selftest=True, base_dir=tmp_dir)
    check("无用户时自动进入首次运行向导", app.screen == "wizard", app.screen)

    app.wp_name.insert(0, "王一")
    app.wp_pin.insert(0, "1234")
    app.wp_pin2.insert(0, "1234")
    app.wizard_next()
    app.wc_name.insert(0, "王二")
    app.wizard_finish()
    st = app.store
    check("向导创建家长与孩子并切换到孩子",
          st.names() == ["王一", "王二"] and st.role_of("王一") == ROLE_PARENT
          and st.role_of("王二") == ROLE_CHILD and st.current == "王二",
          (st.names(), st.current))
    check("用户数据已落盘 users.json", os.path.exists(os.path.join(tmp_dir, USER_FILE)))
    check("密码加盐哈希存储（非明文）",
          st.find("王一")["pw"] not in ("1234", None)
          and st.verify("王一", "1234") and not st.verify("王一", "9999"))
    check("孩子切换免密码、家长需密码",
          (not st.requires_pin("王二")) and st.requires_pin("王一"))

    check("孩子登录时无删改权限", app.can_delete_records() is False)
    app.switch_user("王一")
    check("家长登录后有删改权限", app.can_delete_records() is True)
    app.switch_user("王二")

    # 练习一轮（王二）
    app.start_practice()
    for _ in range(20):
        q = app.round.questions[app.round.index]
        app.entry.delete(0, "end")
        app.entry.insert(0, str(q.answer))
        app.submit_answer()
    check("练习成绩记入当前用户（王二 1 条 / 王一 0 条）",
          len(app.read_history("王二")) == 1 and len(app.read_history("王一")) == 0)

    # 含跳过与错题的完整轮次：对 15、错 3、跳 2
    app.start_practice()
    for i in range(20):
        if i < 2:
            app.skip_question()
            continue
        q = app.round.questions[app.round.index]
        app.entry.delete(0, "end")
        app.entry.insert(0, str(q.answer if i < 17 else q.answer + 1))
        app.submit_answer()
    d = app.result_data
    check("含跳过：得分=答对/总题（15/20→75分）、正确率=答对/作答（15/18→83%）",
          d["right"] == 15 and d["answered"] == 18 and d["skipped"] == 2
          and d["score"] == 75 and round(d["acc"] * 100) == 83,
          (d["right"], d["answered"], d["skipped"], d["score"], round(d["acc"] * 100)))
    check("星星按得分评定（75 分→2 颗星）", d["stars"] == 2, d["stars"])

    # 历史明细与"重练本次错题"
    rec0 = app.read_history("王二")[0]
    detail0 = app.read_detail("王二", rec0["data_idx"])
    check("历史明细与记录一致（得分/逐题明细/跳过数）",
          detail0 and detail0["score"] == 75 and len(detail0["items"]) == 20
          and sum(1 for it in detail0["items"] if it["s"] == "skip") == 2,
          detail0 and (detail0.get("score"), len(detail0.get("items", []))))
    wrong_items = [it for it in detail0["items"] if it["s"] in ("wrong", "skip")]
    app.start_review_items(wrong_items)
    check("详情→重练本次错题：错题+跳过共 5 道组卷",
          len(app.round.questions) == 5, len(app.round.questions))
    before_cnt = len(app.read_history("王二"))
    for _ in range(5):
        q = app.round.questions[app.round.index]
        app.entry.delete(0, "end")
        app.entry.insert(0, str(q.answer))
        app.submit_answer()
    check("历史错题重练不计入历史", len(app.read_history("王二")) == before_cnt)

    app.switch_user("王一")
    app.start_practice()
    for _ in range(20):
        q = app.round.questions[app.round.index]
        app.entry.delete(0, "end")
        app.entry.insert(0, str(q.answer))
        app.submit_answer()
    check("不同用户历史互相隔离",
          len(app.read_history("王一")) == 1 and len(app.read_history("王二")) == 2)

    # 权限界面差异
    app.switch_user("王二")
    app.show_history()
    child_texts = widget_texts(app.screens["history"])
    check("孩子历史页不含删除/清空按钮",
          not any(("清空记录" in t) or (t == "删") for t in child_texts),
          [t for t in child_texts if "删" in t or "清空" in t])
    app.switch_user("王一")
    app.show_history("王二")
    parent_texts = widget_texts(app.screens["history"])
    check("家长历史页含删除与清空按钮",
          any(t == "删" for t in parent_texts) and any(t == "清空记录" for t in parent_texts))

    # 删除单条 / 清空（记录由孩子产生，再切到家长删除）
    app.switch_user("王二")
    for _ in range(2):
        app.start_practice()
        for _ in range(20):
            q = app.round.questions[app.round.index]
            app.entry.delete(0, "end")
            app.entry.insert(0, str(q.answer))
            app.submit_answer()
    recs = app.read_history("王二")
    check("王二累计 4 条记录", len(recs) == 4, len(recs))
    app.switch_user("王一")
    app.delete_history_record("王二", recs[0])
    check("家长删除单条后 txt 与明细同步减少",
          len(app.read_history("王二")) == 3
          and len(open(app.detail_path("王二"), encoding="utf-8").readlines()) == 3)
    check("家长清空记录后仅剩表头", app.clear_history("王二")
          and len(app.read_history("王二")) == 0
          and not os.path.exists(app.detail_path("王二")))

    # 中断退出（两种退出都记录）
    app.switch_user("王二")
    app.start_practice()
    for i in range(3):
        q = app.round.questions[app.round.index]
        app.entry.delete(0, "end")
        app.entry.insert(0, str(q.answer if i < 2 else q.answer + 1))
        app.submit_answer()
    app.save_partial_and_exit(show_result=True)
    d = app.result_data
    check("中途退出：得分按总题数（2/20→10分）、正确率按已作答（2/3→67%）",
          d["partial"] and d["total"] == 20 and d["right"] == 2 and d["answered"] == 3
          and d["score"] == 10 and round(d["acc"] * 100) == 67,
          (d["total"], d["right"], d["answered"], d["score"], round(d["acc"] * 100)))
    last = open(app.history_path("王二"), encoding="utf-8").read().strip().split("\n")[-1]
    check("历史记录带「中途退出」标记且含得分/作答字段",
          "中途退出" in last and "得分 10" in last and "作答 3" in last, last)
    check("成绩页显示中途退出说明",
          "中途退出" in app.res_note.cget("text"), app.res_note.cget("text"))

    cnt = len(app.read_history("王二"))
    app.start_practice()
    for _ in range(2):
        q = app.round.questions[app.round.index]
        app.entry.delete(0, "end")
        app.entry.insert(0, str(q.answer))
        app.submit_answer()
    app.save_partial_and_exit(show_result=False)
    check("另一种退出方式（不看成绩）同样记入历史",
          len(app.read_history("王二")) == cnt + 1 and app.screen == "menu",
          (len(app.read_history("王二")), app.screen))

    # 时间到：跳过与未答分开统计
    app.start_test()
    for i in range(11):
        if i == 10:
            app.skip_question()
            continue
        q = app.round.questions[app.round.index]
        app.entry.delete(0, "end")
        app.entry.insert(0, str(q.answer if i < 8 else q.answer + 1))
        app.submit_answer()
    app.round.start_ts = time.time() - (TEST_TIME_LIMIT + 5)
    app.tick_timer()
    app.finish_round(timed_out=True)
    d = app.result_data
    check("时间到：未答计入「未答」且不进入正确率分母（对8/作答10→80%，得分8分）",
          d["unanswered"] == 89 and d["skipped"] == 1 and d["answered"] == 10
          and d["right"] == 8 and d["score"] == 8 and round(d["acc"] * 100) == 80,
          (d["right"], d["answered"], d["skipped"], d["unanswered"], d["score"]))
    check("星星与得分配档：90分→3星、75分→2星、50分→1星",
          stars_of_score(90) == 3 and stars_of_score(75) == 2 and stars_of_score(50) == 1)
    check("得分配色分档（≥90绿 / 70-89黄 / <70红）",
          score_color(95) == SCORE_GREEN and score_color(75) == SCORE_AMBER
          and score_color(40) == SCORE_RED)
    check("时间到记录在历史中带「时间到」标记",
          any(r["flag"] == "时间到" for r in app.read_history("王二")))

    # 用户管理
    ok, msg = st.add_user("王三", ROLE_CHILD)
    check("添加孩子用户成功", ok and "王三" in st.names(), msg)
    check("重名被拒绝", not st.add_user("王三", ROLE_CHILD)[0])
    check("家长密码格式校验（4-6 位数字）",
          not st.add_user("王四", ROLE_PARENT, "12")[0]
          and not st.add_user("王四", ROLE_PARENT, "abcd")[0])
    check("不能删除当前登录用户", not st.can_remove(st.current)[0], st.current)
    st.set_current("王一")
    check("不能删除最后一名家长", not st.can_remove("王一")[0])
    check("可以删除其他用户", st.can_remove("王三")[0])
    ok, msg = st.remove_user("王三")
    check("删除用户成功", ok and "王三" not in st.names(), msg)
    check("修改密码后旧密码失效、新密码生效",
          st.set_pin("王一", "5678")[0] and not st.verify("王一", "1234")
          and st.verify("王一", "5678"))

    # 旧数据迁移：v1.0 单文件历史 / v1.1 旧格式历史
    tmp2 = tempfile.mkdtemp(prefix="ksx_legacy_")
    legacy = os.path.join(tmp2, LEGACY_HISTORY)
    with open(legacy, "w", encoding="utf-8") as fp:
        fp.write("旧记录\n")
    app2 = App(root, selftest=True, base_dir=tmp2)
    check("v1.1 首次启动清空 v1.0 旧历史文件并进入向导",
          (not os.path.exists(legacy)) and app2.screen == "wizard")

    tmp3 = tempfile.mkdtemp(prefix="ksx_v11_")
    with open(os.path.join(tmp3, USER_FILE), "w", encoding="utf-8") as fp:
        json.dump({"users": [{"name": "王一", "role": "parent", "salt": "s", "pw": "p"},
                             {"name": "王二", "role": "child", "salt": None, "pw": None}],
                   "current": "王二"}, fp, ensure_ascii=False)
    old_hist = os.path.join(tmp3, HISTORY_PREFIX + "王二.txt")
    with open(old_hist, "w", encoding="utf-8") as fp:
        fp.write("口算小达人 历史成绩记录（每次答题一行）\n"
                 "时间 | 模式 | 成绩 | 正确率 | 用时\n"
                 "2026-09-24 20:00:00 | 练习模式 | 答对 18/20 | 正确率 90% | 用时 6分23秒\n")
    app3 = App(root, selftest=True, base_dir=tmp3)
    content = open(old_hist, encoding="utf-8").read()
    check("v1.2 首次启动清空 v1.1 旧格式历史并记录数据版本",
          ("18/20" not in content) and ("得分" in content)
          and app3.store.data_version == DATA_VERSION
          and len(app3.read_history("王二")) == 0)

    root.destroy()

    passed = sum(1 for _, ok in results if ok)
    out("\n" + "=" * 66)
    out("自检结果：%d / %d 通过" % (passed, len(results)))
    out("=" * 66)
    try:
        rp = os.path.join(tempfile.gettempdir(), "口算小达人-自检报告.txt")
        with open(rp, "w", encoding="utf-8") as fp:
            fp.write("\n".join(report) + "\n")
    except Exception:
        pass
    return 0 if passed == len(results) else 1


# ---------------------------------------------------------------------------
def main():
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())

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
