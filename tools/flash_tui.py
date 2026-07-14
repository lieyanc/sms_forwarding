#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SMS Forwarder 烧录 TUI(Linux)。

快捷查看串口设备列表,选中后一键构建/烧录/查看日志;
构建烧录动作复用 tools/idf.sh,产物在 build/idf,与 CI 一致。

用法:
    tools/flash_tui.py          # 打开交互界面
    tools/flash_tui.py --list   # 仅打印串口设备列表后退出

按键:
    ↑/↓ 或 j/k   选择串口        r   刷新设备列表
    Enter 或 f   烧录            g   烧录并打开日志
    m            串口日志        b   仅构建
    q / Esc      退出
"""

import curses
import glob
import locale
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDF_SH = os.path.join(REPO_ROOT, "tools", "idf.sh")

# 常见 USB 串口芯片厂商,仅用于列表展示提示
VENDOR_HINTS = {
    "303a": "Espressif 原生 USB/JTAG",
    "1a86": "CH34x 转串口",
    "10c4": "CP210x 转串口",
    "0403": "FTDI 转串口",
}


def read_sys(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def usb_info(dev):
    """从 sysfs 取 USB 描述(product / vid:pid),取不到返回空串。"""
    base = os.path.basename(dev)
    node = os.path.realpath(os.path.join("/sys/class/tty", base, "device"))
    # ttyACM 的 device 指向接口目录,ttyUSB 中间还隔一层 usb-serial 端口目录;
    # 向上最多找 4 层,遇到含 idVendor 的目录即为 USB 设备节点。
    for _ in range(4):
        if os.path.exists(os.path.join(node, "idVendor")):
            vid = read_sys(os.path.join(node, "idVendor"))
            pid = read_sys(os.path.join(node, "idProduct"))
            product = read_sys(os.path.join(node, "product"))
            hint = VENDOR_HINTS.get(vid, "")
            label = " / ".join(p for p in (product, hint) if p) or "USB 串口"
            return f"{label} [{vid}:{pid}]"
        node = os.path.dirname(node)
    return ""


def scan_ports():
    ports = []
    for dev in sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*")):
        ports.append({
            "dev": dev,
            "info": usb_info(dev),
            "ok": os.access(dev, os.R_OK | os.W_OK),
        })
    return ports


def print_list():
    ports = scan_ports()
    if not ports:
        print("未检测到串口设备(/dev/ttyACM*、/dev/ttyUSB*)")
        return 1
    for p in ports:
        flag = "可用" if p["ok"] else "无权限(需加入 dialout 组)"
        print(f"{p['dev']:<16} {p['info']:<44} {flag}")
    return 0


def run_idf(stdscr, args, pause=True):
    """临时退出 curses 执行 idf.sh 子命令,结束后恢复界面,返回退出码。"""
    curses.def_prog_mode()
    curses.endwin()
    cmd = ["bash", IDF_SH] + args
    print("\n$ " + " ".join(cmd) + "\n", flush=True)
    try:
        rc = subprocess.call(cmd)
    except KeyboardInterrupt:
        rc = 130
    if pause and rc != 0:
        try:
            input(f"\n[退出码 {rc}] 按回车返回菜单…")
        except (EOFError, KeyboardInterrupt):
            pass
    stdscr.refresh()  # 恢复 curses 屏幕
    return rc


class Colors:
    header = ok = err = warn = 0


def init_colors():
    c = Colors()
    if not curses.has_colors():
        return c
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    c.header = curses.color_pair(1)
    c.ok = curses.color_pair(2)
    c.err = curses.color_pair(3)
    c.warn = curses.color_pair(4)
    return c


def draw(stdscr, colors, ports, sel, msg, msg_attr):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    def put(y, x, text, attr=0, until=None):
        limit = (w if until is None else until) - x - 1
        if 0 <= y < h and limit > 0:
            try:
                stdscr.addnstr(y, x, text, limit, attr)
            except curses.error:
                pass  # 终端过小时忽略越界绘制

    put(0, 0, "SMS Forwarder 烧录工具(ESP32-C3)", curses.A_BOLD | colors.header)
    put(1, 0, f"项目:{REPO_ROOT}")

    put(3, 0, "串口设备(↑↓ 选择,r 刷新):", curses.A_BOLD)
    if not ports:
        put(4, 2, "未检测到 /dev/ttyACM*、/dev/ttyUSB* 设备,插入开发板后按 r 刷新", colors.warn)
    for i, p in enumerate(ports):
        perm = "可用" if p["ok"] else "无权限"
        perm_attr = colors.ok if p["ok"] else colors.err
        line_attr = curses.A_REVERSE if i == sel else 0
        prefix = "> " if i == sel else "  "
        # 信息行在权限标签前截断,避免重叠
        put(4 + i, 2, f"{prefix}{p['dev']:<16} {p['info']}", line_attr, until=w - 10)
        put(4 + i, max(2, w - 8), perm, perm_attr)

    base = 5 + max(1, len(ports))
    put(base, 0, "操作:", curses.A_BOLD)
    put(base + 1, 2, "Enter/f 烧录    g 烧录并打开日志    m 串口日志(Ctrl+] 退出)")
    put(base + 2, 2, "b 仅构建        r 刷新设备列表      q 退出")

    if ports and not ports[sel]["ok"]:
        put(base + 4, 0, "提示:当前串口无权限,先执行 sudo usermod -aG dialout $USER 并注销重登",
            colors.warn)
    if msg:
        put(h - 2, 0, msg, msg_attr)
    stdscr.refresh()


def main(stdscr):
    curses.curs_set(0)
    colors = init_colors()
    ports = scan_ports()
    sel = 0
    msg, msg_attr = "", 0

    while True:
        sel = max(0, min(sel, len(ports) - 1))
        draw(stdscr, colors, ports, sel, msg, msg_attr)
        ch = stdscr.getch()

        if ch in (ord("q"), 27):
            break
        elif ch in (curses.KEY_UP, ord("k")):
            sel -= 1
        elif ch in (curses.KEY_DOWN, ord("j")):
            sel += 1
        elif ch == ord("r"):
            ports = scan_ports()
            msg, msg_attr = f"已刷新,共 {len(ports)} 个设备", 0
        elif ch == curses.KEY_RESIZE:
            pass
        elif ch == ord("b"):
            rc = run_idf(stdscr, ["build"])
            ok = rc == 0
            msg = "构建完成" if ok else f"构建失败(退出码 {rc})"
            msg_attr = colors.ok if ok else colors.err
        elif ch in (curses.KEY_ENTER, 10, 13, ord("f"), ord("g"), ord("m")):
            if not ports:
                msg, msg_attr = "没有可用串口设备,插入后按 r 刷新", colors.warn
                continue
            dev = ports[sel]["dev"]
            action = {ord("g"): "flash-monitor", ord("m"): "monitor"}.get(ch, "flash")
            rc = run_idf(stdscr, [action, "-p", dev])
            ok = rc == 0
            names = {"flash": "烧录", "flash-monitor": "烧录+日志", "monitor": "日志"}
            msg = f"{names[action]}完成({dev})" if ok else f"{names[action]}失败(退出码 {rc})"
            msg_attr = colors.ok if ok else colors.err
            # 烧录复位后设备可能重新枚举,动作结束后刷新列表
            ports = scan_ports()


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__.strip())
        sys.exit(0)
    if "--list" in sys.argv or "-l" in sys.argv:
        sys.exit(print_list())
    if not os.path.exists(IDF_SH):
        print(f"找不到 {IDF_SH},请在仓库内运行。", file=sys.stderr)
        sys.exit(1)
    locale.setlocale(locale.LC_ALL, "")  # 保证中文/宽字符正确渲染
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
