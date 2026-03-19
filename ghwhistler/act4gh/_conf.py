
#import functools
import os
#from pathlib import Path
from pprint import pprint as pp
from collections import namedtuple

import time
import json
import random
import math

from invoke import task
#from fabric.api import env, lcd, local, task
from urllib3.util.retry import Retry
import requests
from requests.adapters import HTTPAdapter

import tqdm
from natsort import natsorted
import numpy as np
from PIL import Image, ImageDraw, ImageFont

#   video effect abt.
#import imageio
from moviepy.editor import ImageSequenceClip
#from moviepy.editor import VideoClip
from moviepy.editor import VideoFileClip, AudioFileClip
from moviepy.editor import concatenate_audioclips

#   audio effect abt.
#import pydub
from pydub import AudioSegment
import librosa
from scipy.signal import convolve

SROOT = os.path.dirname(os.path.abspath(__file__))
#print("SROOT",SROOT)
PROOT = os.path.abspath(os.path.join(SROOT, os.pardir))
print(f"SROOT:{SROOT}\nPROOT:{PROOT}\n")

    # 使用个人访问令牌进行身份验证
headers= {
    'Authorization': 'token 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',
}

CFG = {
    "perp": 100,    # gh-evnevt API 单页要求
    
    "evmax": 181, # for got: 59s au.
    "limit": 118, # for got: 59s video
    "v4fps": 2,
    "retry": 10,

    "transtart": 220, #透明开始配值

    "bgv_w" : 1920,
    "bgv_h" : 1080,
    "pxw" : 1920,
    "pxh" : 1080,

    #   crontab 任务相关约定
    "gen1ghw": "/opt/logs/gen1ghw.json",# 任务进展暂存
    "gen2path": "/opt/vlog/ghw2",       # 视频输出目录
    "gen4json": "/opt/logs/ghevents",   # 数据来源目录

    #   最终 FFmpeg 推流的批量视频目录
    "exp4vlog" : "/opt/vlog/ghwhistler/%s.mp4",
    "exp2vlog" : "/opt/vlog/ghw2/%s.mp4",

    "font2img" : "/opt/font/1942.ttf",
    "font4sarasa" : "/opt/font/sarasa-mono-sc-semibold.ttf",

    "bg4video" : "../log/mfc2bg.png",
    "mov2bgs" : [
        "../log/f4v/fcs_bg_1.png",
        "../log/f4v/fcs_bg_2.png",
        "../log/f4v/fcs_bg_3.png",
        "../log/f4v/fcs_bg_4.png",
        "../log/f4v/fcs_bg_5.png",
        "../log/f4v/fcs_bg_6.png",
        ],
    "bgs4mov" : [
        "../log/ghw3/bg4allmankind-01.png",
        "../log/ghw3/bg4allmankind-02.png",
        "../log/ghw3/bg4allmankind-03.png",
        "../log/ghw3/bg4allmankind-04.png",
        "../log/ghw3/bg4allmankind-05.png",
        "../log/ghw3/bg4allmankind-06.png",
        "../log/ghw3/bg4allmankind-07.png",
        "../log/ghw3/bg4allmankind-08.png",
        "../log/ghw3/bg4allmankind-09.png",
        "../log/ghw3/bg4allmankind-10.png",
        ],
    "fimg" : "../log/f4v/%s.png",

    "f1video" : "../log/dbg1f.png",
    "fi2v" : "../log/dbg%sfps.mp4",
    "v4stream" : "../log/dbg_v4stream.mp4",
    "m1audio" : "../log/dbg1m.MP3",

    "au4overly" : "../log/au4overly.MP3",
    "au4append" : "../log/au4append.MP3",
    "m1music" : "../log/dbg2m1music.MP3",

    # 前次成功 event 数据集
    "lastevs" : "../log/lastevents.json",
    
    #"asset2a" : "../_assets/audio",
    "ghw2au" : "../_assets/ghw3",
    "music4bg" : "_BackGround.MP3",
    "event2audio" : {
        #   一个或多个提交被推送到仓库分支或标记
        "PushEvent":"PushEvent.MP3",
        #   当有人标星仓库时
        "WatchEvent":"WatchEvent.MP3",

        #   Git 分支或标签已创建
        "CreateEvent":"CreateEvent.MP3",
        #   Git 分支或标签已删除
        "DeleteEvent":"DeleteEvent.MP3",

        # 知识相关
        #   创建或更新 wiki 页面
        "GollumEvent":"GollumEvent.MP3",
        #   与议题相关的活动
        "IssuesEvent":"IssuesEvent.MP3",
        "IssueCommentEvent":"IssueCommentEvent.MP3",

        #   提交评论已创建
        "CommitCommentEvent":"CommitCommentEvent.MP3",
        #   与仓库协作者相关的活动
        "MemberEvent":"MemberEvent.MP3",

        #   用户复刻仓库
        "ForkEvent":"ForkEvent.MP3",

        #   与拉取请求相关的活动。
        "PullRequestEvent":"PullRequestEvent.MP3",
        #   与拉取请求审查相关的活动。
        "PullRequestReviewEvent":"PullRequestReviewEvent.MP3",
        #   与拉取请求统一差异中的拉取请求审查评论相关的活动
        "PullRequestReviewCommentEvent":"PullRequestReviewCommentEvent.MP3",
        #   与拉取请求的批注线程相关的活动标记为已解决或未解决
        "PullRequestReviewThreadEvent":"PullRequestReviewThreadEvent.MP3",

        #少见重大行为
        #   当私有仓库公开时。 毫无疑问：最好的 GitHub 事件,此事件返回一个空 payload 对象
        "PublicEvent":"PublicEvent.MP3",
        #   与发行版相关的活动
        "ReleaseEvent":"ReleaseEvent.MP3",
        #   与赞助列表相关的活动
        "SponsorshipEvent":"SponsorshipEvent.MP3",
    },
    "mp3preload": {},
    "confuse":{
        "0":"O",
        "1":"I",
        "2":"r",
        "3":"E",
        "4":"A",
        "5":"S",
        "6":"b",
        "7":"L",
        "8":"B",
        "9":"P",
    },
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
