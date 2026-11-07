
import sys, os
sys.path.insert(0, r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom")
os.chdir(r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom")
os.environ['LOOM_NO_PARALLEL']='1'; os.environ['LOOM_NO_SAVE_MIGRATE']='1'
import vk_player
fps = vk_player.run_vk(os.path.join(r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom","tests","_tmp","ab_ui_scene.json"),
                       frames_n=25, width=480, height=320, title="UI smoke")
print("VK+UI 冒烟结束 FPS:", fps)
