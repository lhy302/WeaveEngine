# -*- coding: utf-8 -*-
"""hub_install_ui.py — LoomHub 安装/卸载对话框（2026-10-19）

三个自定义对话框（都是 Toplevel，异步非阻塞）：
  show_zip_preview(parent, controller, zip_path, on_success):
      zip 元数据预览 + 可选安装位置 + 确认安装

  show_github_install(parent, controller, on_success):
      GitHub 引擎版本列表 + 下载进度 + 自动进入安装

  show_remove_interp(parent, interp):
      移除三选一：「仅从列表移除」/「彻底删除」/「取消」

设计原则：
  - 所有对话框非阻塞（Toplevel + grab_set），返回后主窗口继续运行
  - 下载走后台线程，进度用 parent.after 调度回主线程（tkinter 线程安全）
  - 失败/取消明确反馈，不静默
"""
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import hub_github as gh
import hub_install as inst


# ============================================================
# zip 预览 + 安装
# ============================================================

def show_zip_preview(parent, controller, zip_path, on_success=None):
    """zip 元数据预览对话框. 成功安装后调用 on_success(installed_dir) 并返回."""
    try:
        size_mb = os.path.getsize(zip_path) / (1024.0 * 1024.0)
    except OSError:
        messagebox.showerror('安装 .zip', '无法读取文件: %s' % zip_path)
        return
    # 读元数据
    preview = controller.preview_zip(zip_path)
    if not preview.get('ok'):
        messagebox.showerror('安装 .zip', preview.get('error', '无法解析 zip'))
        return
    info = preview['info']
    version = (info.get('version') or '').strip()

    dlg = tk.Toplevel(parent)
    dlg.title('安装 Loom 解释器')
    dlg.geometry('560x360')
    dlg.transient(parent)
    dlg.grab_set()

    # 头部
    head = tk.Frame(dlg, bg='#f0f4fa')
    head.pack(fill='x')
    tk.Label(head, text='准备安装 Loom 引擎', font=('Microsoft YaHei UI', 12, 'bold'),
             bg='#f0f4fa', padx=12, pady=10).pack(anchor='w')

    # 信息区
    body = tk.Frame(dlg, padx=20, pady=10)
    body.pack(fill='both', expand=True)
    rows = [
        ('版本号', version or '(未读)'),
        ('名称', info.get('name', '?')),
        ('类型', info.get('kind', '?')),
        ('Python 版本', info.get('python_version', '?')),
        ('压缩包大小', '%.2f MB' % size_mb),
        ('说明', (info.get('description') or '(无)')[:120]),
    ]
    for i, (k, v) in enumerate(rows):
        tk.Label(body, text=k + ':', anchor='w', fg='#666').grid(
            row=i, column=0, sticky='w', pady=3)
        tk.Label(body, text=v, anchor='w', wraplength=380, justify='left').grid(
            row=i, column=1, sticky='w', padx=(8, 0), pady=3)

    # 安装位置（可改）
    loc_row = tk.Frame(body)
    loc_row.grid(row=len(rows), column=0, columnspan=2, sticky='ew', pady=(15, 0))
    tk.Label(loc_row, text='安装到:', fg='#666').pack(side='left')
    loc_var = tk.StringVar(value=controller.install_root)
    loc_entry = tk.Entry(loc_row, textvariable=loc_var)
    loc_entry.pack(side='left', fill='x', expand=True, padx=6)

    def _browse():
        import filedialog
        d = filedialog.choose_directory('选择安装位置', initial_dir=loc_var.get())
        if d:
            loc_var.set(d)
    tk.Button(loc_row, text='浏览...', command=_browse).pack(side='left')

    tk.Label(body, text='提示: 已存在同版本会覆盖安装目录。',
             fg='#999', font=('Microsoft YaHei UI', 8)).grid(
        row=len(rows) + 1, column=0, columnspan=2, sticky='w', pady=(6, 0))

    # 底部按钮
    btns = tk.Frame(dlg, pady=10)
    btns.pack(fill='x')
    result = {'ok': False}

    def _do_install():
        target_root = loc_var.get().strip()
        if not target_root:
            messagebox.showerror('安装', '安装位置不能为空', parent=dlg)
            return
        # 检查权限（尝试创建目录）
        try:
            os.makedirs(target_root, exist_ok=True)
        except OSError as e:
            messagebox.showerror('安装', '无法创建安装目录:\n%s\n%r' % (target_root, e),
                                 parent=dlg)
            return
        dlg.config(cursor='watch')
        dlg.update()
        # 同步安装（zip 解压很快，通常 < 3 秒，不阻塞体验）
        r = controller.do_install_zip(version=version, zip_path=zip_path,
                                       target_root=target_root)
        dlg.config(cursor='')
        if r.get('ok'):
            result['ok'] = True
            dlg.destroy()
            if on_success is not None:
                on_success(r.get('installed_dir', target_root))
        else:
            messagebox.showerror('安装失败', r.get('message', '未知错误'), parent=dlg)

    tk.Button(btns, text='取消', command=dlg.destroy, width=12).pack(
        side='right', padx=(6, 20))
    tk.Button(btns, text='安装', command=_do_install, width=12,
              bg='#5a8ede', fg='white', relief='raised').pack(
        side='right')
    # 居中
    dlg.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    w, h = dlg.winfo_width(), dlg.winfo_height()
    dlg.geometry('+%d+%d' % (px + (pw - w) // 2, py + (ph - h) // 2))





# ============================================================
# GitHub 在线安装
# ============================================================

def show_github_install(parent, controller, on_success=None):
    """GitHub 引擎版本列表 + 下载进度 + 自动进入安装（非阻塞 Toplevel）."""
    dlg = tk.Toplevel(parent)
    dlg.title('从 GitHub 安装 Loom 引擎')
    dlg.geometry('700x480')
    dlg.transient(parent)
    dlg.grab_set()

    # 顶部：状态 + 刷新 + Token 设置
    head = tk.Frame(dlg, bg='#f0f4fa')
    head.pack(fill='x')
    status_var = tk.StringVar(value='正在拉取版本列表...')
    tk.Label(head, textvariable=status_var, anchor='w',
             bg='#f0f4fa', padx=12, pady=8).pack(side='left', fill='x', expand=True)

    def _open_token_dialog():
        _show_token_dialog(dlg, controller, on_reload=_reload)
    tk.Button(head, text='Token 设置', command=_open_token_dialog).pack(
        side='right', padx=(0, 4), pady=4)
    tk.Button(head, text='刷新', command=lambda: _reload()).pack(
        side='right', padx=(0, 4), pady=4)

    # 版本列表（Treeview）
    list_frame = tk.Frame(dlg, padx=10, pady=6)
    list_frame.pack(fill='both', expand=True)
    cols = ('version', 'date', 'size')
    tv = ttk.Treeview(list_frame, columns=cols, show='headings', height=12)
    tv.heading('version', text='版本')
    tv.heading('date', text='发布日期')
    tv.heading('size', text='大小 (MB)')
    tv.column('version', width=200, anchor='w')
    tv.column('date', width=180, anchor='w')
    tv.column('size', width=100, anchor='e')
    sb = ttk.Scrollbar(list_frame, orient='vertical', command=tv.yview)
    tv.config(yscrollcommand=sb.set)
    tv.pack(side='left', fill='both', expand=True)
    sb.pack(side='right', fill='y')

    # 下载进度区（默认隐藏）
    prog_frame = tk.Frame(dlg, padx=10, pady=6)
    prog_frame.pack(fill='x')
    prog_var = tk.DoubleVar(value=0.0)
    prog_bar = ttk.Progressbar(prog_frame, variable=prog_var, maximum=100.0)
    prog_bar.pack(fill='x', pady=(0, 4))
    prog_label_var = tk.StringVar(value='')
    tk.Label(prog_frame, textvariable=prog_label_var, anchor='w', fg='#666').pack(fill='x')

    # 底部按钮
    btns = tk.Frame(dlg, pady=8)
    btns.pack(fill='x')
    install_btn = tk.Button(btns, text='下载并安装', width=14,
                            bg='#5a8ede', fg='white', relief='raised')
    install_btn.pack(side='right', padx=(6, 20))
    cancel_btn = tk.Button(btns, text='取消', width=10, command=dlg.destroy)
    cancel_btn.pack(side='right')

    # 状态：当前候选列表 / 当前下载
    state = {
        'releases': [],
        'by_iid': {},
        'cancel': None,
        'downloading': False,
        'downloaded_zip': None,
    }

    def _reload():
        if state['downloading']:
            messagebox.showwarning('正在下载', '请等待当前下载完成或取消后再刷新', parent=dlg)
            return
        status_var.set('正在拉取版本列表...')
        tv.delete(*tv.get_children())
        state['releases'] = []
        state['by_iid'] = {}

        def _worker():
            token = gh.load_token() or None
            result = gh.list_engine_releases(token=token, max_count=50)
            dlg.after(0, lambda: _on_loaded(result))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_loaded(result):
        if not result.get('ok'):
            err = result.get('error', '未知错误')
            rl = result.get('rate_limit', {})
            tail = ' (剩余 %s/%s)' % (rl.get('remaining', '?'), rl.get('limit', '?'))
            status_var.set('拉取失败: ' + err + tail)
            return
        releases = result.get('releases', [])
        state['releases'] = releases
        tv.delete(*tv.get_children())
        state['by_iid'] = {}
        for r in releases:
            iid = tv.insert('', 'end', values=(
                r['version'],
                (r.get('published_at') or '')[:10],
                '%.1f' % r.get('size_mb', 0),
            ))
            state['by_iid'][iid] = r
        rl = result.get('rate_limit', {})
        if releases:
            status_var.set('共 %d 个版本 (API 剩余 %s/%s)，选中后点「下载并安装」'
                           % (len(releases), rl.get('remaining', '?'),
                              rl.get('limit', '?')))
        else:
            status_var.set('仓库中没有 engine-v* 前缀的 release '
                           '(API 剩余 %s/%s)' % (rl.get('remaining', '?'),
                                                rl.get('limit', '?')))
        # 默认选中第一个
        if releases:
            first_iid = list(state['by_iid'].keys())[0]
            tv.selection_set(first_iid)

    def _do_install():
        if state['downloading']:
            return
        sel = tv.selection()
        if not sel:
            messagebox.showwarning('选择版本', '请先在列表中选择一个版本', parent=dlg)
            return
        rel = state['by_iid'].get(sel[0])
        if not rel:
            return
        url = rel.get('download_url')
        if not url:
            messagebox.showerror('下载', '该版本没有可下载的 zip', parent=dlg)
            return
        # 下载到临时目录
        import tempfile
        tmpdir = os.path.join(tempfile.gettempdir(), 'LoomHub_download')
        os.makedirs(tmpdir, exist_ok=True)
        dest = os.path.join(tmpdir, rel.get('asset_name') or ('Loom-%s.zip' % rel['version']))
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        cancel = gh.CancelToken()
        state['cancel'] = cancel
        state['downloading'] = True
        install_btn.config(state='disabled')
        cancel_btn.config(text='取消下载')
        prog_var.set(0.0)
        prog_label_var.set('正在下载 %s...' % rel['version'])

        def _progress(downloaded, total, speed):
            # 主线程调度
            def _upd():
                if total > 0:
                    prog_var.set(downloaded * 100.0 / total)
                    remain = (total - downloaded) / speed if speed > 0 else 0
                    prog_label_var.set('%.1f/%.1f MB  %.1f MB/s  剩余 %.0f 秒'
                                       % (downloaded / 1048576.0,
                                          total / 1048576.0,
                                          speed / 1048576.0,
                                          remain))
                else:
                    prog_label_var.set('%.1f MB  %.1f MB/s'
                                       % (downloaded / 1048576.0, speed / 1048576.0))
            try:
                dlg.after(0, _upd)
            except Exception:
                pass

        def _worker():
            try:
                ok = gh.download_asset(url, dest, progress_cb=_progress,
                                       cancel_token=cancel)
                dlg.after(0, lambda: _on_downloaded(ok, dest, rel))
            except Exception as e:
                dlg.after(0, lambda: _on_download_error(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_downloaded(ok, dest, rel):
        state['downloading'] = False
        install_btn.config(state='normal')
        cancel_btn.config(text='取消')
        if not ok:
            prog_label_var.set('已取消下载')
            return
        state['downloaded_zip'] = dest
        prog_var.set(100.0)
        prog_label_var.set('下载完成，进入安装确认...')
        # 关掉当前 GitHub 对话框，打开 zip 预览对话框
        dlg.destroy()

        def _on_install_done(installed_dir):
            if on_success is not None:
                on_success(installed_dir)
        show_zip_preview(parent, controller, dest, on_success=_on_install_done)

    def _on_download_error(e):
        state['downloading'] = False
        install_btn.config(state='normal')
        cancel_btn.config(text='取消')
        prog_label_var.set('下载失败')
        messagebox.showerror('下载失败', repr(e), parent=dlg)

    def _on_cancel():
        if state['downloading'] and state['cancel'] is not None:
            state['cancel'].cancel()
        else:
            dlg.destroy()

    install_btn.config(command=_do_install)
    cancel_btn.config(command=_on_cancel)
    dlg.protocol('WM_DELETE_WINDOW', _on_cancel)

    # 居中
    dlg.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    w, h = dlg.winfo_width(), dlg.winfo_height()
    dlg.geometry('+%d+%d' % (px + (pw - w) // 2, py + (ph - h) // 2))

    # 自动加载
    _reload()





# ============================================================
# Token 设置对话框
# ============================================================

def _show_token_dialog(parent, controller, on_reload=None):
    """GitHub Token 设置（可选，提升速率限制 60 -> 5000 次/小时）."""
    dlg = tk.Toplevel(parent)
    dlg.title('GitHub Token 设置（可选）')
    dlg.geometry('560x320')
    dlg.transient(parent)
    dlg.grab_set()

    body = tk.Frame(dlg, padx=20, pady=14)
    body.pack(fill='both', expand=True)
    tk.Label(body, text='GitHub Personal Access Token',
             font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w')
    tk.Label(body, text='留空 = 匿名访问（60 次/小时，够用）\n'
                        '填入 Token = 5000 次/小时（频繁刷新时推荐）',
             fg='#666', justify='left').pack(anchor='w', pady=(4, 10))

    # 当前 Token（可一键从 git credential manager 读）
    cur = gh.load_token()
    tk.Label(body, text='Token:', anchor='w').pack(anchor='w')
    token_var = tk.StringVar(value=cur)
    ent = tk.Entry(body, textvariable=token_var, show='*')
    ent.pack(fill='x', pady=(2, 6))

    show_var = tk.BooleanVar(value=False)
    def _toggle_show():
        ent.config(show='' if show_var.get() else '*')
    tk.Checkbutton(body, text='显示明文', variable=show_var,
                   command=_toggle_show).pack(anchor='w')

    auto_var = tk.StringVar(value='')
    def _from_git():
        t = gh.get_token_from_git()
        if t:
            token_var.set(t)
            auto_var.set('已从 git credential manager 读取（未保存，需点"保存"）')
        else:
            auto_var.set('git credential manager 中没有 GitHub 凭据')
    tk.Button(body, text='从 git 凭据读取', command=_from_git).pack(
        anchor='w', pady=(6, 0))
    tk.Label(body, textvariable=auto_var, fg='#090',
             font=('Microsoft YaHei UI', 8)).pack(anchor='w')

    # 底部
    btns = tk.Frame(dlg, pady=10)
    btns.pack(fill='x')

    def _save():
        gh.save_token(token_var.get())
        dlg.destroy()
        if on_reload is not None:
            on_reload()

    def _clear():
        token_var.set('')

    tk.Button(btns, text='取消', command=dlg.destroy, width=10).pack(
        side='right', padx=(6, 20))
    tk.Button(btns, text='保存', command=_save, width=10,
              bg='#5a8ede', fg='white', relief='raised').pack(side='right')
    tk.Button(btns, text='清空', command=_clear, width=8).pack(side='right', padx=6)

    dlg.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    w, h = dlg.winfo_width(), dlg.winfo_height()
    dlg.geometry('+%d+%d' % (px + (pw - w) // 2, py + (ph - h) // 2))


# ============================================================
# 移除三选一
# ============================================================

def show_remove_interp(parent, controller, interp, on_success=None):
    """移除解释器三选一对话框.

    [仅从列表移除]  保留磁盘文件
    [彻底删除]     物理删除安装目录（二次确认）
    [取消]        不动
    """
    if not interp:
        messagebox.showinfo('移除', '请先在列表中选择一个解释器', parent=parent)
        return
    ver = interp.get('version', '?')
    dirp = interp.get('dir', '')

    dlg = tk.Toplevel(parent)
    dlg.title('移除解释器')
    dlg.geometry('560x260')
    dlg.transient(parent)
    dlg.grab_set()

    head = tk.Frame(dlg, bg='#fff6e0')
    head.pack(fill='x')
    tk.Label(head, text='移除 Loom 解释器  %s' % ver,
             font=('Microsoft YaHei UI', 12, 'bold'),
             bg='#fff6e0', padx=12, pady=10).pack(anchor='w')

    body = tk.Frame(dlg, padx=20, pady=12)
    body.pack(fill='both', expand=True)
    tk.Label(body, text='安装目录:', fg='#666').pack(anchor='w')
    tk.Label(body, text=dirp or '(未知)', anchor='w', wraplength=500,
             justify='left', fg='#333').pack(anchor='w', pady=(0, 12))
    tk.Label(body, text='请选择移除方式：',
             font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w')

    def _remove_only():
        controller.remove_interpreter(interp, delete_files=False)
        dlg.destroy()
        if on_success is not None:
            on_success()

    def _remove_and_delete():
        # 二次确认
        ok = messagebox.askyesno(
            '彻底删除',
            '确定要永久删除以下目录吗？此操作不可撤销！\n\n%s' % (dirp or '(未知)'),
            parent=dlg, icon='warning', default='no')
        if not ok:
            return
        r = controller.remove_interpreter(interp, delete_files=True)
        if not r.get('ok'):
            messagebox.showerror('删除失败', r.get('message', '未知错误'), parent=dlg)
            return
        dlg.destroy()
        if on_success is not None:
            on_success()

    # 三个选项按钮
    row = tk.Frame(body)
    row.pack(fill='x', pady=(10, 0))
    tk.Button(row, text='仅从列表移除\n（保留磁盘文件）', width=22, height=3,
              command=_remove_only, bg='#e8f0fb').pack(side='left', padx=4)
    tk.Button(row, text='彻底删除\n（磁盘文件也删掉）', width=22, height=3,
              command=_remove_and_delete, bg='#fbe8e8').pack(side='left', padx=4)

    btns = tk.Frame(dlg, pady=8)
    btns.pack(fill='x')
    tk.Button(btns, text='取消', command=dlg.destroy, width=10).pack(side='right', padx=20)

    dlg.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    w, h = dlg.winfo_width(), dlg.winfo_height()
    dlg.geometry('+%d+%d' % (px + (pw - w) // 2, py + (ph - h) // 2))
