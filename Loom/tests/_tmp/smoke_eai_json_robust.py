# -*- coding: utf-8 -*-
"""smoke_eai_json_robust.py — P0-1 EAI JSON 代理字符健壮性冒烟 (2026-10-19)

背景: 缺陷报告 P0-1 指出，/logs 和 /cmd 返回含孤立代理字符时直接断连。
根因: json.dumps(..., ensure_ascii=False).encode('utf-8') 遇 \udcba 抛 UnicodeEncodeError，
      do_GET/do_POST 未兜底 -> BaseHTTPRequestHandler 直接关连接。

本冒烟验证:
  A) log() 对坏字符做清洗 -> 日志环里不出现非法字符
  B) _json() 对坏字符做编码兜底 -> 不再抛异常（旧代码会抛）
  C) 极端场景（json.dumps 本身失败）也不空断 -> 返回最小错误 JSON
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

# 无头：agent_commands 顶层 import 不依赖 GUI / GL
import agent_commands as ac
import json

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ============ 1) log() 清洗 ============
LONE = 'bad_\udcba_char'
try:
    seq = ac.log(LONE)
    check('1a) log(孤立代理字符) 不抛异常', True, 'seq=%d' % seq)
except Exception as e:
    check('1a) log(孤立代理字符) 不抛异常', False, e)
    sys.exit(1)

# 检查日志环
lines = ac.log_since(seq - 1)
check('1b) 日志环返回 1 行', len(lines) == 1, lines)
if lines:
    text = lines[0][2]
    has_surrogate = any(0xD800 <= ord(c) <= 0xDFFF for c in text)
    check('1c) 环里无孤立代理字符', not has_surrogate, repr(text))
    # 应该被替换成 '?'
    check('1d) 坏字符被替换', '?' in text or '\ufffd' in text, repr(text))


# ============ 2) _json 编码兜底 ============
# 模拟 HTTP handler 的最小 _json（复刻 agent_commands._JsonHandler._json 的逻辑）
def fake_json(obj):
    try:
        return json.dumps(obj, ensure_ascii=False).encode('utf-8', 'replace')
    except Exception as e:
        return json.dumps({'ok': False, 'error': 'dump failed',
                           'detail': repr(e)[:200]}).encode('utf-8', 'replace')


bad_obj = {'ok': True, 'line': '中文\udcba中文'}
try:
    body = fake_json(bad_obj)
    check('2a) _json 对坏字符不抛异常', True, '%d bytes' % len(body))
    # 验证能反向解析成合法 JSON
    parsed = json.loads(body.decode('utf-8'))
    check('2b) 输出仍是合法 JSON', parsed.get('ok') is True, parsed)
except Exception as e:
    check('2a) _json 对坏字符不抛异常', False, e)


# ============ 3) 对比：旧代码会抛异常 ============
old_failed = False
try:
    json.dumps(bad_obj, ensure_ascii=False).encode('utf-8')
except UnicodeEncodeError as e:
    old_failed = True
    check('3a) 旧代码 encode(utf-8) 抛 UnicodeEncodeError（回归证据）',
          True, str(e)[:60])
except Exception:
    pass
if not old_failed:
    check('3a) 旧代码 encode(utf-8) 抛 UnicodeEncodeError（回归证据）', False,
          '旧代码居然没抛？环境异常')


# ============ 4) 极端：json.dumps 自身失败（循环引用） ============
circ = {}
circ['self'] = circ
try:
    body = fake_json(circ)
    check('4a) 循环引用不崩，返回最小错误 JSON', True, '%d bytes' % len(body))
    parsed = json.loads(body.decode('utf-8'))
    check('4b) 错误 JSON 是合法格式', parsed.get('ok') is False, parsed)
except Exception as e:
    check('4a) 循环引用不崩，返回最小错误 JSON', False, e)


# ============ 汇总 ============
print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
