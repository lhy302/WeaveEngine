r"""tools/verify_pkg_vs_head.py — 交付包与代码一致性自证（只读）。

用法：
  py -3.13 tools/verify_pkg_vs_head.py <source.zip> <compiled.zip> [--version <ver>] [--json out.json]

判据：
  * source 包：包内 Loom/**.py 与 git show HEAD: 的内容哈希一致（CRLF 归一、排除 player_runtime/）
  * compiled 包：build_info.git_head 必须与 HEAD 的引擎目录等价（HEAD 引擎零 diff 时允许祖先）
  * git_dirty 必须为 false
  * meta（顶层/嵌套）版本一致

2026-11-10 从 C:\loom_build\toolchain_probe 收编进来（审计发现放仓库外换机即失效）。
"""
# -*- coding: utf-8 -*-
"""verify_pkg_vs_head.py — 交付包 vs HEAD 自证（V-03）。

用法:
  py -3.13 verify_pkg_vs_head.py <source.zip> <compiled.zip> [--version 0.1.0.beta6] [--json out.json]

检查:
  A) 源码包: 包内 Loom/*.py 与 git HEAD 同名文件 sha256 逐一对拍（数量/不一致/缺失）
  B) 关键文件: sceneio.py / agent_commands.py / loom_post.py / loom_assets.py 的 sha 前缀
  C) 元数据: 顶层 解释器.json version、build_info(mode/python/nuitka/built_at)、
             嵌套 player_runtime/game_player.dist/解释器.json version 三者一致，且 == --version
  D) 编译包: 无 .py 源码，改为记录 build_info/meta 一致性 + built_at vs HEAD 提交时间（陈旧告警）
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile

def _find_repo():
    for c in (os.environ.get('LOOM_REPO'), os.getcwd(),
              os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        if c and os.path.isdir(os.path.join(c, '.git')):
            return os.path.abspath(c)
    return os.path.abspath(os.getcwd())


REPO = _find_repo()
KEY = ['Loom/sceneio.py', 'Loom/agent_commands.py', 'Loom/loom_post.py',
       'Loom/loom_assets.py']


def sha(b):
    return hashlib.sha256(b).hexdigest()


def norm(b):
    """EOL 归一：仓库 core.autocrlf=true，检出为 CRLF、git blob 为 LF。
    内容一致性按"归一后字节"比较，否则所有 CRLF 文件都会被误判不一致。"""
    return b.replace(b'\r\n', b'\n')


def head_file(path):
    try:
        return subprocess.check_output(['git', '-C', REPO, 'show',
                                        'HEAD:%s' % path], stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None


def _git(args):
    try:
        return subprocess.check_output(
            ['git', '-C', REPO] + args, encoding='utf-8', errors='replace',
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def engine_equivalent(base, head):
    """compiled 包判据（V2-02）：git_head 必须是 HEAD 的祖先，且 HEAD 相对它
    在 Loom/ 零 diff。这样"只改文档/tools"的提交不会误红，引擎改动仍会被抓。"""
    if not base or not head:
        return False, '缺 git_head 或 HEAD'
    if base == head:
        return True, 'equal'
    rc = subprocess.call(['git', '-C', REPO, 'merge-base', '--is-ancestor',
                          base, head], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    if rc != 0:
        return False, 'git_head 不是 HEAD 的祖先'
    diff = _git(['diff', '--name-only', base, head, '--', 'Loom/']) or ''
    files = [x for x in diff.splitlines() if x.strip()]
    if files:
        return False, ('Loom/ 有 %d 处改动: %s'
                       % (len(files), ', '.join(files[:5])))
    return True, '引擎等价（HEAD 仅改非 Loom/ 文件）'


def head_sha():
    try:
        return subprocess.check_output(
            ['git', '-C', REPO, 'rev-parse', 'HEAD'], text=True,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def head_commit_time():
    try:
        out = subprocess.check_output(
            ['git', '-C', REPO, 'log', '-1', '--format=%cd', '--date=format:%Y-%m-%d %H:%M:%S'],
            text=True).strip()
        return out
    except Exception:
        return None


def read_zip_json(zf, name):
    try:
        return json.loads(zf.read(name).decode('utf-8'))
    except Exception:
        return None


def check_source(zip_path, version):
    out = {'zip': os.path.basename(zip_path), 'kind': 'source', 'py_files': 0,
           'mismatch': [], 'missing_in_head': [], 'meta': {}}
    with zipfile.ZipFile(zip_path) as zf:
        # 只比引擎源码；Loom/player_runtime/ 是预置运行为产物（含其自身 .py），
        # 不在源码树里，不能算"与 HEAD 不一致"。
        names = [n for n in zf.namelist()
                 if n.startswith('Loom/') and n.endswith('.py')
                 and not n.startswith('Loom/player_runtime/')]
        out['py_files'] = len(names)
        for n in names:
            hb = head_file(n)
            if hb is None:
                out['missing_in_head'].append(n)
                continue
            if sha(norm(zf.read(n))) != sha(norm(hb)):
                out['mismatch'].append(n)
        out['key'] = {}
        for k in KEY:
            b = zf.read(k) if k in zf.namelist() else None
            hb = head_file(k)
            out['key'][k] = {
                'zip': sha(b)[:12] if b else None,
                'head': sha(hb)[:12] if hb else None,
                'same': bool(b and hb and sha(norm(b)) == sha(norm(hb))),
                'note': 'sha 前缀为 EOL 归一后的内容哈希',
            }
        meta = read_zip_json(zf, 'Loom/解释器.json')
        nested = read_zip_json(zf, 'Loom/player_runtime/game_player.dist/解释器.json')
        out['meta'] = {
            'version': (meta or {}).get('version'),
            'python_version': (meta or {}).get('python_version'),
            'nested_version': (nested or {}).get('version'),
            'same_as_target': (meta or {}).get('version') == version,
            'nested_same': (nested or {}).get('version') == version,
        }
    return out


def check_compiled(zip_path, version):
    out = {'zip': os.path.basename(zip_path), 'kind': 'compiled', 'py_files': 0,
           'note': '编译包不含 .py 源码，改查 meta/build_info/构建时间', 'meta': {}}
    with zipfile.ZipFile(zip_path) as zf:
        meta = read_zip_json(zf, 'Loom/解释器.json')
        nested = read_zip_json(zf, 'Loom/player_runtime/game_player.dist/解释器.json')
        bi = read_zip_json(zf, 'Loom/build_info.json')
        rbi = read_zip_json(zf, 'Loom/player_runtime/game_player.dist/build_info.json')
        out['meta'] = {
            'version': (meta or {}).get('version'),
            'python_version': (meta or {}).get('python_version'),
            'nested_version': (nested or {}).get('version'),
            'same_as_target': (meta or {}).get('version') == version,
            'nested_same': (nested or {}).get('version') == version,
            'editor_build_info': bi,
            'runtime_build_info_mode': (rbi or {}).get('mode'),
            'git_head': (bi or {}).get('git_head'),
            'git_dirty': (bi or {}).get('git_dirty'),
            'smoke_passed_at': (bi or {}).get('smoke_passed_at'),
        }
    return out


def main():
    args = sys.argv[1:]
    version = '0.1.0.beta6'
    if '--version' in args:
        i = args.index('--version')
        version = args[i + 1]
        del args[i:i + 2]
    out_json = None
    if '--json' in args:
        i = args.index('--json')
        out_json = args[i + 1]
        del args[i:i + 2]
    if len(args) < 2:
        print(__doc__)
        return 2
    res = {'head': head_sha(), 'head_commit_time': head_commit_time(),
           'target_version': version,
           'source': check_source(args[0], version),
           'compiled': check_compiled(args[1], version)}
    print('HEAD commit time:', res['head_commit_time'])
    s = res['source']
    print('[source] py 文件 %d，与 HEAD 不一致 %d，HEAD 不存在 %d'
          % (s['py_files'], len(s['mismatch']), len(s['missing_in_head'])))
    for k in KEY:
        v = s['key'][k]
        print('  key %-24s zip=%s head=%s %s'
              % (os.path.basename(k), v['zip'], v['head'],
                 'OK' if v['same'] else 'DIFF'))
    print('[source] meta=%s nested=%s target=%s -> %s'
          % (s['meta'].get('version'), s['meta'].get('nested_version'), version,
             'OK' if s['meta'].get('same_as_target') and s['meta'].get('nested_same')
             else 'BAD'))
    c = res['compiled']
    _head = res['head']
    _cgit = c['meta'].get('git_head')
    print('[compiled] meta=%s nested=%s build_info.mode=%s built_at=%s'
          % (c['meta'].get('version'), c['meta'].get('nested_version'),
             (c['meta'].get('editor_build_info') or {}).get('mode'),
             (c['meta'].get('editor_build_info') or {}).get('built_at')))
    _eq, _why = engine_equivalent(_cgit, _head)
    res['compiled']['engine_equivalent'] = {'ok': _eq, 'why': _why}
    print('[compiled] git_head=%s head=%s dirty=%s -> %s（%s）'
          % ((_cgit or 'None')[:12], (_head or 'None')[:12],
             c['meta'].get('git_dirty'), 'OK' if _eq else 'DIFF', _why))
    print('[compiled] smoke_passed_at=%s built_at=%s'
          % (c['meta'].get('smoke_passed_at'),
             (c['meta'].get('editor_build_info') or {}).get('built_at')))
    if out_json:
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print('json:', out_json)
    _compiled_bad = (not _eq) or (c['meta'].get('git_dirty') is not False)
    bad = (s['mismatch']
           or not (s['meta'].get('same_as_target') and s['meta'].get('nested_same'))
           or _compiled_bad)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
