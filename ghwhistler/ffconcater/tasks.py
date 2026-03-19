__project__ = 'ghwhistler/ffconcater'
__version__ = 'v.231112.1642'
__author__ = 'Zoom.Quiet'
__license__ = 'MIT@2023-11'

import os
from pprint import pprint as pp
from collections import namedtuple
import time
#import json
#import random
#import datetime
from invoke import task
#from fabric.api import env, lcd, local, task
#import tqdm
from natsort import natsorted
import tailhead

SROOT = os.path.dirname(os.path.abspath(__file__))
print("SROOT",SROOT)
PROOT = os.path.abspath(os.path.join(SROOT, os.pardir))
print("PROOT",PROOT)

CFG = {
    "title": "@ChaosDAMA 大媽的多重宇宙",
    "sub_title": "color base:🎦 %s",
    # vlogging
    "path4v": "/opt/vlog/ghwhistler",
    #"tpl2vf": "%d.mp4",
    "p2f4v": "/opt/code/ghwhistler/log/f4v",
    "tpl4fcs": "fcs_bg_%s_bgau.mp4",
    "p2ffconcat": "/opt/vlog/p2ffconcat.txt",
    "tpl4ffc": "tpl_ffconcat.txt",
    "rtmplog":"/opt/vlog/rtmp4ffmpeg.log",

}
# 定义一个namedtuple，将CFG字典转化为具有字段名的元组子类
Config = namedtuple('Config', CFG.keys())
# 将CFG字典转化为Config命名元组
CONF = Config(**CFG)
## 现在你可以通过点号来访问CFG字典中的键值对
#print(CONF.title)
#print(CONF.tpl2vf)


@task
def ver(c):
    '''echo crt. verions
    '''
    print('''{}
<:watch /opt/vlog, update ffconcat
    make FFmpeg RMTP full-day-streamming:>
    ~> version   {} <~
    ~> powded by {} <~
    '''.format(__project__
               ,__version__
               ,__author__
               ))

#   support stuff func.
def cd(c, path2, echo=True):
    os.chdir(path2)
    if echo:
        print('\n\t crt. PATH ===')
        c.run('pwd')
        c.run('echo \n')


@task
def genffc(c,vp=CONF.path4v,sp=None,ep=None,debug=1):
    '''gen. FFmpeg need ffconcat.txt
    '''
    if debug:
        max = 10
        is_debug = 'Y' if debug else 'N'
        print(f'''debug: { is_debug}
    sp:\t{sp}
    ep:\t{ep}
    
    path4v:\t{CONF.path4v}
    
    p2f4v:\t{CONF.p2f4v}
    tpl4fcs:\t{CONF.tpl4fcs}
    
    p2ffconcat:\t{CONF.p2ffconcat}
        ''')
    else:
        #if (not sp) or (not ep):
        print(f'''USAGE:
    $ inv genffc 
    --vp=path/2/视频目录
    --sp= (0为第一个)~从哪个视频开始
    --ep= (0为所有)~最大包含视频数量
    --debug= 是否为调试状态
        ''')
        #    return None
        
    # 获取拟定目录下的视频文件
    #video_files = [f for f in os.listdir(CONF.path4v) if f.endswith(('.mp4', '.avi'))]
    video_files = [f for f in os.listdir(vp) if f.endswith(('.mp4', '.avi'))]
    sorted_vfiles = natsorted(video_files)
    #print(f"""sorted_vfiles: {len(sorted_vfiles)}
    #{sorted_vfiles[:10]}""")
    _flist = []
    #for i in sorted_vfiles[:60]:
    #sp, ep = int(sp), int(ep)
    match (sp, ep):
        case (None, None):
            _grasp = sorted_vfiles
        case (_, None):
            _grasp = sorted_vfiles[int(sp):]
        case (None, _):
            _grasp = sorted_vfiles[:int(ep)]
        case (_, _):
            _grasp = sorted_vfiles[int(sp):int(ep)]

    for idx,i in enumerate(_grasp):
        #print(f"file {CFG['path4v']}/{i}")
        _vno = (idx%6)+1
        #_flist.append(f"file {CONF.p2f4v}/{CONF.tpl4fcs%_vno}")
        #print(f"_vno:{_vno}->{CONF.tpl4fcs}")
        #print(f"{CONF.tpl4fcs%_vno}")
        #_flist.append(f"file {CONF.path4v}/{i}")
        _flist.append(f"file {vp}/{i}")
        
    _ffc_tpl = open(CONF.tpl4ffc,'r').read()
    #print(_ffc_tpl.format("\n".join(_flist)))
    
    with open(CONF.p2ffconcat,'w') as file:
        file.write(_ffc_tpl.format("\n".join(_flist)))

    print(f"""exp. ffconcat -> {CONF.p2ffconcat}
    index {len(_flist)} video files;
        """)
    return None





@task
def chk4play(c,debug=1):
    '''base $ ffmpeg ... 2>path/2/rtmp4ffmpeg.log terminal check now play
    
    '''
    #logfile = tailhead.tail(open(CONF.rtmplog))
    logfile = open(CONF.rtmplog,"r")
    loglines = follow(logfile)
    # iterate over the generator
    pattern = '/opt/vlog/ghwhistler/'

    for line in loglines:
        print(line)
        if pattern in line:
            print("Found match:", line)



def follow(thefile):
    '''generator function that yields new lines in a file
    '''
    # seek the end of the file
    thefile.seek(0, os.SEEK_END)
    
    # start infinite loop
    while True:
        # read last line of file
        line = thefile.readline()
        # sleep if file hasn't been updated
        if not line:
            time.sleep(1)
            continue

        yield line

if __name__ == '__main__':
    pass


