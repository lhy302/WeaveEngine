# -*- coding: utf-8 -*-
import sys
try:
    import glfw
    ver = glfw.get_version_string()
    print("glfw version:", ver)
    print("has preedit cb:", hasattr(glfw, 'set_preedit_callback'))
    print("has char cb:", hasattr(glfw, 'set_char_callback'))
except Exception as e:
    print("glfw import failed:", repr(e))
try:
    import rendercanvas
    print("rendercanvas:", getattr(rendercanvas, '__version__', '?'))
    import rendercanvas.glfw as rcg
    print("rendercanvas.glfw ok")
except Exception as e:
    print("rendercanvas failed:", repr(e))
