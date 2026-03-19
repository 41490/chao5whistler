
#import functools
import os
#from pathlib import Path
from pprint import pprint as pp
from collections import namedtuple

#import time
import json
#import random
#import math

from invoke import task

from natsort import natsorted


SROOT = os.path.dirname(os.path.abspath(__file__))
#print("SROOT",SROOT)
PROOT = os.path.abspath(os.path.join(SROOT, os.pardir))
print(f"SROOT:{SROOT}\nPROOT:{PROOT}\n")

CFG = {
    #   crontab 任务相关约定
    "gen1ghw": "/opt/logs/gen1ghw.json",# 任务进展暂存
    "gen4json": "/opt/logs/ghevents",   # 数据来源目录

}

# 定义一个namedtuple，将CFG字典转化为具有字段名的元组子类
Config = namedtuple('Config', CFG.keys())
# 将CFG字典转化为Config命名元组
CONF = Config(**CFG)



#   support stuff func.
def cd(c, path2, echo=True):
    os.chdir(path2)
    if echo:
        print('\n\t crt. PATH ===')
        c.run('pwd')
        c.run('echo \n')
