# -*- coding: utf-8 -*-
import sys, os
# 探针在 LoomHub/tests/_tmp/，向上 3 级到 LoomHub/
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.abspath(os.path.join(THIS_DIR, '..', '..'))
sys.path.insert(0, HUB)
print('HUB =', HUB)
ok = []
fail = []
for m in ['LoomHubGUI', 'hub_controller', 'hub_config', 'hub_commands',
          'hub_install', 'hub_console', 'hub_view_tk']:
    try:
        __import__(m)
        ok.append(m)
    except Exception as e:
        fail.append((m, repr(e)))
print('OK:', ok)
print('FAIL:', fail)
