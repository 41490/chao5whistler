__project__ = 'ghwhistler/movcolor'
__version__ = 'v.231107.1942'
__author__ = 'Zoom.Quiet'
__license__ = 'MIT@2023-11'

import os
from pprint import pprint as pp
#import time
#import json
import random
import datetime
from collections import namedtuple

from invoke import task
#from fabric.api import env, lcd, local, task
import tqdm

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import moviepy.editor as mpe
#from moviepy.editor import ImageSequenceClip
#from moviepy.editor import VideoClip
#from moviepy.editor import VideoFileClip, AudioFileClip
#from moviepy.editor import concatenate_audioclips
import imageio

SROOT = os.path.dirname(os.path.abspath(__file__))
print("SROOT",SROOT)
PROOT = os.path.abspath(os.path.join(SROOT, os.pardir))
print("PROOT",PROOT)

CFG = {
    "drops": 100,    #60 180,#240,
    "fps4vi" : 25,
    "pxw" : 1920,
    "pxh" : 1080,
    "font2img" : "/opt/font/sarasa-mono-sc-semibold.ttf",
    #"font2img" : "/opt/font/CascadiaMono.ttf",
    "font4self" : "/opt/font/XiQuexiaoqingsong-regular.otf",
    
    "title": "@ChaosDAMA | 大媽的多重宇宙",
    "sub_title": "color from: %s",
    # 保存生成的电影色彩频谱图片的文件路径
    "exp2img" : "../log/color_spectrogram.png",
    "txt2img" : "../log/color_spectrogram_txt.png",
    # 生成频谱底图的生成动画
    "mfc2bg" : "../log/mfc2bg.png",
    "mfc2vi" : "../log/mfc2bg_anime.mp4",
    "au2mov" : "../log/mfc2bg_anime_bgau.mp4",
    "au4mfc" : "../_assets/audio/_fcs_bg.MP3",
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
    }
}
# 定义一个namedtuple，将CFG字典转化为具有字段名的元组子类
Config = namedtuple('Config', CFG.keys())
# 将CFG字典转化为Config命名元组
CONF = Config(**CFG)

@task
def ver(c):
    '''echo crt. verions
    '''
    print('''{}
<:grasp frame from Movie gen. 
    frame-color-spectra as ghwhistler backgrand img.:>
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


def _txt1n2img(image,font, fsize,txt,color,x,y):
    '''inject text into img. for mark witch movie ..etc.
    - image   Image 对象
    - font    字体对象
    - fsize   文本尺寸
    - txt     具体文字
    - x,y     注入位置
    在fill颜色值的格式中,除了RGB三原色,最后一位表示透明度,范围0-255,0为完全透明。
    '''
    #print("font",font)
    #return None
    # 复制字体对象并修改大小
    font = font.font_variant(size=fsize)
    # 调整字体大小
    #font.size = fsize

    # 给水印添加透明度，因此需要转换图片的格式
    i4rgba=image.convert('RGBA')
    # 创建和原图尺寸一致的水印层, 完全透明
    text_overlay = Image.new('RGBA', image.size, (255, 255, 255, 0))
    text_draw = ImageDraw.Draw(text_overlay)
    # 水印层上写入文字
    #   绘制外层白色描边
    text_draw.text((x+2, y+2), txt, fill=(242,242,242,142), font=font) 
    # 绘制内层颜色文字
    #text_draw.text((x, y), txt, fill=color, font=font, direction='ttb')
    text_draw.text((x, y), txt, fill=color, font=font)
    # 和原图alpha合成
    image = Image.alpha_composite(i4rgba, text_overlay)

    # 绘制外层白色描边
    #draw.text((x+4, y+4), txt, fill=(242,242,242,0), font=font) 
    # 绘制内层颜色文字
    #draw.text((x, y), txt, fill=color, font=font)

    print(f"txt: {txt}\n\t @({x},{y})")

    # 保存结果
    return image


#@task
def txt2img(c, aimp=None,subt=None, debug=0):
    '''inject text into img. for mark witch movie ..etc.
    @ChaosDAMA🙈♥️🙉💀🙊🤖
    🎦Scavengers.Reign.S01E01.1080p.WEB.h264.mkv
    
    '''
    # 打开图片 
    image = Image.open(CFG['exp2img']) # 统一临时文件
    if debug:
        aimp = CONF.mfc2bg  #CFG['txt2img']
        subt = "Scavengers.Reign.S01E0"

    if not subt:
        print('''USAGE:
    $ inv txt2img --debug=1
    or
    $ inv txt2img \
        --aimp= 绝对路径指向要输出的最终图片
        --subt= 要注入在左下角的影片信息文本
        ''')
        return None

    # 准备字体 
    print(CFG['font2img'])
    font_sarasa = ImageFont.truetype(CFG['font2img'])
    image = _txt1n2img(image
                     , font_sarasa
                     , 64
                     , CFG['title']
                     , (0,142,81,200)
                     , 42
                     , 42
                     
                     )
    image = _txt1n2img(image
                     , font_sarasa
                     , 42
                     , CFG['sub_title']%subt
                     , (42,42,42,142)
                     , 42
                     , CFG['pxh']-142
                     )
    ## 右下角生成片段序列号
    #image = _txt1n2img(image
    #                 , font_sarasa
    #                 , 32
    #                 , _gen4ghwno(c,debug=1)
    #                 , (142,142,142,142)
    #                 , CONF.pxw -150
    #                 , CONF.pxh -50
    #                 )

    font_XQeasy = ImageFont.truetype(CFG['font4self'])
    image = _txt1n2img(image
                     , font_XQeasy
                     , 142
                     , "代码回哨"
                     , (242,242,242,142)
                     , CFG['pxw']/2-242
                     , CFG['pxh']/2-142
                     )

    # 保存结果
    #image.save(CFG['txt2img'])
    image.save(aimp)
    print(f"exp.=>{aimp}")
    return None


#@task
def txt4hbg(c, aimp=None,subt=None, debug=1):
    '''inject text into horizontal bg_img. to mark movie ..etc.
    '''
    if debug:
        aimp = CFG['txt2img']
        subt = "Scavengers.Reign.S01E0"

    # 打开图片 
    image = Image.open(aimp) # 直接写回底图
    if not subt:
        print('''USAGE:
    $ inv txt4hbg 
    or
    $ inv txt4hbg \
        --aimp= 绝对路径指向要输出的最终图片
        --subt= 要注入在左下角的影片信息文本
        --ghwno= 要注入在左下角的 ghw 片段序号
        --debug=0
        ''')
        return None

    print(f"txt4hbg(): {subt}->\n\t{aimp}")
    # 准备字体 
    print(CFG['font2img'])
    font_sarasa = ImageFont.truetype(CFG['font2img'])
    image = _txt1n2img(image
                     , font_sarasa
                     , 64
                     , CFG['title']
                     , (0,142,81,200)
                     , 42
                     , 42
                     
                     )
    image = _txt1n2img(image
                     , font_sarasa
                     , 42
                     , CFG['sub_title']%subt
                     , (42,42,42,142)
                     , 42
                     , CFG['pxh']-142
                     )
    ## 右下角生成片段序列号
    #image = _txt1n2img(image
    #                 , font_sarasa
    #                 , 32
    #                 , _gen4ghwno(c,debug=1)
    #                 , (142,142,142,142)
    #                 , CONF.pxw -150
    #                 , CONF.pxh -50
    #                 )

    font_XQeasy = ImageFont.truetype(CFG['font4self'])
    image = _txt1n2img(image
                     , font_XQeasy
                     , 142
                     , "GitHub"
                     , (242,242,242,142)
                     , CFG['pxw']/2-202
                     , CFG['pxh']/2-142
                     )
    image = _txt1n2img(image
                     , font_XQeasy
                     , 142
                     , "whistler"
                     , (242,242,242,142)
                     , CFG['pxw']/2-242
                     , CFG['pxh']/2-42
                     )

    # 保存结果
    #image.save(CFG['txt2img'])
    image.save(aimp)
    print(f"exp.=>{aimp}")
    return None

#@task
def gen2fcs(c, mov=None, aimp=None, subt=None, debug=1):
    '''auto grasp frames from Movie ge. framw-color-spectra img.
    - mov 绝对路径指向的电影文件
    - aimp 绝对路径指向输出的图片
    - subt 对应图片上注入的影片文字
    - debug 是否为调试, 如果是调试, 使用内置参数    

    USAGE:
    inv gen2fcs --mov="/opt/vlog/2023_ScavengersReign/Scavengers.Reign.S01E01.1080p.WEB.h264.mkv" --aimp="../log/f4v/fcs_bg_1.png" --subt="Scavengers.Reign.S01E01" --debug=0
    '''
    _drops = CFG['drops'] 
    # 保存生成的电影色彩频谱图片的文件路径, 中间文件,注入文字后,要另外指向
    output_image_path = CFG['exp2img']#"../log/color_spectrogram.png"

    if debug:
        # 视频文件路径
        video_path = "/opt/vlog/2023_ScavengersReign/Scavengers.Reign.S01E01.1080p.WEB.h264.mkv"

    else:
        if not mov:
            print('''USAGE:
    --mov= 绝对路径指向的电影文件
    --aimp= 绝对路径指向输出的图片
    --subt= 对应图片上注入的影片文字
    --debug= 是否为调试, 如果是调试, 使用内置参数
                  ''')
        else:
            video_path = mov

    # 保存生成的电影色彩频谱图片的文件路径
    output_image_path = CFG['exp2img']#"../log/color_spectrogram.png"

    # 打开视频文件
    cap = cv2.VideoCapture(video_path)
    # count the number of frames
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    # 获取视频帧率
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    # calculate dusration of the video
    seconds = int(frames / fps)
    video_time = str(datetime.timedelta(seconds=seconds))
    # 获取视频宽度和高度
    width = int(cap.get(3))
    height = int(cap.get(4))
    # 计算每一片的平均时长
    avg_duration = int(seconds / (_drops+4))

    print(f'''mov::{video_path}
    frames: {frames}
    fps:    {fps}
    seconds:{seconds} -> {video_time}
    -> avg_duration:{avg_duration}

    width:  {width}
    height: {height}
          ''')

    # 创建空白图片
    img = Image.new('RGB', (CFG['pxw'], CFG['pxh']))
    # 计算每张色条的宽度
    bar_width = CFG['pxw'] // _drops 
    # 初始化画笔
    draw = ImageDraw.Draw(img)
    # 计算每帧的间隔（帧数）
    frame_interval = avg_duration*fps
    #for i in range(_drops):
    #for i in tqdm.trange(_drops):
    with tqdm.trange(_drops) as t:
        for i in t:
            frame_no =  i * frame_interval
            # 读取指定帧
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            ret, frame = cap.read() 
            if not ret:
                break
            # 从当前帧计算主颜色
            bgr_mean = np.mean(frame, axis=(0, 1))
            dominant_color = tuple(bgr_mean.astype(int))
            #print(f"i:{i}->color:{dominant_color}")
            # 进度条提示文字
            t.set_description(f'RGB: {dominant_color}')
            # 计算色条左上角坐标
            x = i * bar_width
            y = 0
            # 绘制色条
            draw.rectangle(
                (x, y, x + bar_width - 1, CFG['pxh'])
                , fill=dominant_color
                ) 

    # 保存图片
    img.save(output_image_path)
    
    txt2img(c, aimp,subt)
    return None

#horizontal
@task
def mfc2hv(c
        , mov=None
        , subt=None
        , aimp=CFG['mfc2bg']
        , aimv=CFG['mfc2vi']
        , au2v=CFG['au2mov']
        , fps4vi=CFG['fps4vi']
        , debug=1):
    '''将影片帧主色提取为一个横向帧色频谱图
    
    过程变成一个定长动画过门,以便直播时使用
    - 背影从全白->全黑
    - 每帧一个帧主色条安装到位
    - 180条, 36fps ~> 5s 视频

inv mfc2hv --mov="/opt/vlog/2023_ScavengersReign/Scavengers.Reign.S01E01.1080p.WEB.h264.mkv" --subt="Scavengers.Reign.S01E01" --aimp="../log/f4v/fcs_bg_1.png" --aimv="../log/f4v/fcs_bg_1.mp4" --au2v="../log/f4v/fcs_bg_1_bgau.mp4"  --debug=0
    '''
    print(f'''
    aimp:{aimp}
    aimv:{aimv}
    au2v:{au2v}
    fps4vi:{fps4vi}
    au4mfc:{CFG['au4mfc']}
    _drops: {CFG['drops']}
    ''')
    #return None
    _drops = CFG['drops'] 
    # 保存生成的电影色彩频谱图片的文件路径, 中间文件,注入文字后,要另外指向
    output_image_path = aimp

    if debug:
        #video_path = "/opt/vlog/2021冥想指南HeadspaceGuide-to-Meditation/Headspace.Guide.to.Meditation.S01E07.How.to.Deal.with.Anger.1080p.mp4"
        #subt = "2021.Headspace Guide to Meditation S01E07"
        #video_path = "/opt/vlog/2021SuperCub/[11][720P][更多高清资源→公众号@电影解忧酱].mp4"
        #subt = "2021.Super Cub E11"
        mov = "/opt/vlog/2018YuruCamp/yc△S1E03.mp4"
        subt = "2018.Yuru Camp△S1E03"
    else:
        if not mov:
            print('''USAGE:
    $ inv fcolor2v \
    --mov=      \ 绝对路径指向要分析的电影文件
    --subt=     \ 对应图片上注入的影片文字
    --aimp=     \ 绝对路径指向输出的图片
    --aimv=     \ 绝对路径指向输出的影片
    --au2v=     \ 绝对路径指向最终影片->追加背景音乐
    --fps4vi=   \ 目标影片的 fps
    --debug=    是否为调试, 如果是调试, 使用内置参数
                  ''')
    video_path = mov

    # 打开视频文件
    cap = cv2.VideoCapture(video_path)
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    fps4cap = int(cap.get(cv2.CAP_PROP_FPS))
    # calculate dusration of the video
    seconds = int(frames / fps4cap)
    video_time = str(datetime.timedelta(seconds=seconds))
    # 获取视频宽度和高度
    width = int(cap.get(3))
    height = int(cap.get(4))
    # 计算每一抽帧间平均时长
    avg_duration = int(seconds / (_drops+4))

    print(f'''mov::{video_path}
    frames: {frames}
    fps:    {fps4cap}
    seconds:{seconds} -> {video_time}
    -> avg_duration:{avg_duration}

    width:  {width}
    height: {height}
          ''')

    # 创建空白图片 # RGB颜色值，这里为白色
    img = Image.new('RGB', (CFG['pxw'], CFG['pxh']),(255, 255, 255))
    # 计算帧底色变化步长
    step4rgb = 255 // _drops
    #gb1st = (255-step4rgb*_drops)
    crt_gb = 255
    # 计算每张色条的宽度
    #bar_width = CFG['pxw'] // _drops
    # 计算每张色条的高度
    bar_high = CFG['pxh'] // _drops

    # 初始化画笔
    draw = ImageDraw.Draw(img)
    # 计算每帧的间隔（帧数）
    frame_interval = avg_duration*fps4cap
    frames = []
    with tqdm.trange(_drops) as t:
        for i in t:
            # 读取指定帧
            frame_no =  i * frame_interval
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            ret, frame = cap.read() 
            if not ret:
                break
            # 从当前帧计算主颜色
            bgr_mean = np.mean(frame, axis=(0, 1))
            dominant_color = tuple(bgr_mean.astype(int))
            # 进度条提示文字
            #t.set_description(f'RGB: {dominant_color}')
            # 计算色条左上角坐标
            #x = i * bar_width
            #y = 0
            x = 0
            y = i * bar_high
            draw.rectangle(
                (x, y
                 , CONF.pxw , y + bar_high - 1)#左上,右下角两点
                , fill=dominant_color
                )
            # 剩余补渐黑, 目标矩形的, (左上,右下) 两坐标点
            crt_gb -= step4rgb
            _h4tail = CONF.pxh - (i+1)* bar_high
            draw.rectangle(
                   ( x , y+ bar_high,
                    CONF.pxw , CONF.pxh
                   )
                   , fill=(crt_gb,crt_gb,crt_gb)
                   )
            # 进度条提示文字
            #t.set_description(f'({x},0):{x + bar_width}|{_w4tail}')
            #t.set_description(f'({x},0):{dominant_color}/{crt_gb}')
            t.set_description(f'(0,{y}):{CONF.pxw}/{_h4tail}')
            #img = _put1column(img,draw,x,y,bar_width,dominant_color)
            # 频谱生成过程动画
            #temp_img = img.copy()
            frames.append(img.copy())
            #print()
            #t.set_description(f'frames: {len(frames)}')

    # 保存图片
    img.save(output_image_path)
    print(f"output_image_path:{output_image_path}")
    # 追加文字...
    txt4hbg(c, aimp,subt,debug=0)
    return None

    # 转换每个PIL Image为NumPy数组
    frames_np = [np.array(frame) for frame in frames]
    # moviepy error always : TypeError: must be real number, not NoneType
    #   [write_videofile error · Issue #1625 · Zulko/moviepy](https://github.com/keikoro)
    video_clip = mpe.ImageSequenceClip(frames_np, fps=CFG['fps4vi'])
    video_clip.write_videofile(aimv, fps=CFG['fps4vi'])
    # 追加背景音效
    au2bg4v(c,srmv=aimv,aimv=au2v,debug=0)
    return None


# horizontal
@task
def img4mfc(
    c,
    mov=None,
    subt=None,
    aimp=CFG["mfc2bg"],
    debug=1,
):
    """将影片帧主色提取为一个横向帧色频谱图

    inv img4mfc --mov="/opt/vlog/2023_ScavengersReign/Scavengers.Reign.S01E01.1080p.WEB.h264.mkv" --subt="Scavengers.Reign.S01E01" --aimp="../log/f4v/fcs_bg_1.png" --debug=0
    """
    print(
        f"""
    aimp:{aimp}
    """
    )
    # return None
    _drops = CFG["drops"]
    # 保存生成的电影色彩频谱图片的文件路径, 中间文件,注入文字后,要另外指向
    output_image_path = aimp

    if debug:
        mov = "/opt/vlog/2019S1FAMankind/4AM-S01E01.mp4"
        subt = "2019/For All Mankind/S1E01"
    else:
        if not mov:
            print(
                """USAGE:
    $ inv fcolor2v \
    --mov=      \ 绝对路径指向要分析的电影文件
    --subt=     \ 对应图片上注入的影片文字
    --aimp=     \ 绝对路径指向输出的图片
    --debug=    是否为调试, 如果是调试, 使用内置参数
                """)
    video_path = mov

    # 打开视频文件
    cap = cv2.VideoCapture(video_path)
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    fps4cap = int(cap.get(cv2.CAP_PROP_FPS))
    # calculate dusration of the video
    seconds = int(frames / fps4cap)
    video_time = str(datetime.timedelta(seconds=seconds))
    # 获取视频宽度和高度
    width = int(cap.get(3))
    height = int(cap.get(4))
    # 计算每一抽帧间平均时长
    avg_duration = int(seconds / (_drops + 4))

    print(
        f"""mov::{video_path}
    frames: {frames}
    fps:    {fps4cap}
    seconds:{seconds} -> {video_time}
    -> avg_duration:{avg_duration}

    width:  {width}
    height: {height}
        """)

    # 创建空白图片 # RGB颜色值，这里为白色
    img = Image.new("RGB", (CFG["pxw"], CFG["pxh"]), (255, 255, 255))
    # 计算帧底色变化步长
    step4rgb = 255 // _drops
    # gb1st = (255-step4rgb*_drops)
    crt_gb = 255
    # 计算每张色条的宽度
    # bar_width = CFG['pxw'] // _drops
    # 计算每张色条的高度
    bar_high = CFG["pxh"] // _drops

    # 初始化画笔
    draw = ImageDraw.Draw(img)
    # 计算每帧的间隔（帧数）
    frame_interval = avg_duration * fps4cap
    frames = []
    with tqdm.trange(_drops) as t:
        for i in t:
            # 读取指定帧
            frame_no = i * frame_interval
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            ret, frame = cap.read()
            if not ret:
                break
            # 从当前帧计算主颜色
            bgr_mean = np.mean(frame, axis=(0, 1))
            dominant_color = tuple(bgr_mean.astype(int))
            # 进度条提示文字
            # t.set_description(f'RGB: {dominant_color}')
            # 计算色条左上角坐标
            # x = i * bar_width
            # y = 0
            x = 0
            y = i * bar_high
            draw.rectangle(
                (x, y, CONF.pxw, y + bar_high - 1), fill=dominant_color  # 左上,右下角两点
            )
            # 剩余补渐黑, 目标矩形的, (左上,右下) 两坐标点
            crt_gb -= step4rgb
            _h4tail = CONF.pxh - (i + 1) * bar_high
            draw.rectangle(
                (x, y + bar_high, CONF.pxw, CONF.pxh), fill=(crt_gb, crt_gb, crt_gb)
            )
            # 进度条提示文字
            # t.set_description(f'({x},0):{x + bar_width}|{_w4tail}')
            # t.set_description(f'({x},0):{dominant_color}/{crt_gb}')
            t.set_description(f"(0,{y}):{CONF.pxw}/{_h4tail}")
            # img = _put1column(img,draw,x,y,bar_width,dominant_color)
            # 频谱生成过程动画
            # temp_img = img.copy()
            #frames.append(img.copy())
            # print()
            # t.set_description(f'frames: {len(frames)}')

    # 保存图片
    img.save(output_image_path)
    print(f"output_image_path:{output_image_path}")
    # 追加文字...
    txt4hbg(c, aimp, subt, debug=0)
    return None


#vertical
#@task
def fcolor2v(c
        , mov=None
        , subt=None
        , aimp=CFG['mfc2bg']
        , aimv=CFG['mfc2vi']
        , au2v=CFG['au2mov']
        , fps4vi=CFG['fps4vi']
        , debug=1):
    '''将影片帧主色提取过程变成一个定长动画过门,以便直播时使用
    - 背影从全白->全黑
    - 每帧一个帧主色条安装到位
    - 180条, 36fps ~> 5s 视频

inv fcolor2v --mov="/opt/vlog/2023_ScavengersReign/Scavengers.Reign.S01E01.1080p.WEB.h264.mkv" --subt="Scavengers.Reign.S01E01" --aimp="../log/f4v/fcs_bg_1.png" --aimv="../log/f4v/fcs_bg_1.mp4" --au2v="../log/f4v/fcs_bg_1_bgau.mp4"  --debug=0

    '''
    print(f'''
    aimp:{aimp}
    aimv:{aimv}
    au2v:{au2v}
    fps4vi:{fps4vi}
    au4mfc:{CFG['au4mfc']}
    _drops: {CFG['drops']}
    ''')
    #return None
    _drops = CFG['drops'] 
    # 保存生成的电影色彩频谱图片的文件路径, 中间文件,注入文字后,要另外指向
    output_image_path = aimp

    if debug:
        #video_path = "/opt/vlog/2021冥想指南HeadspaceGuide-to-Meditation/Headspace.Guide.to.Meditation.S01E07.How.to.Deal.with.Anger.1080p.mp4"
        #subt = "2021.Headspace Guide to Meditation S01E07"
        #video_path = "/opt/vlog/2021SuperCub/[11][720P][更多高清资源→公众号@电影解忧酱].mp4"
        #subt = "2021.Super Cub E11"
        mov = "/opt/vlog/2018YuruCamp/yc△S1E03.mp4"
        subt = "2018.Yuru Camp△S1E03"
    else:
        if not mov:
            print('''USAGE:
    $ inv fcolor2v \
    --mov=      \ 绝对路径指向要分析的电影文件
    --subt=     \ 对应图片上注入的影片文字
    --aimp=     \ 绝对路径指向输出的图片
    --aimv=     \ 绝对路径指向输出的影片
    --au2v=     \ 绝对路径指向最终影片->追加背景音乐
    --fps4vi=   \ 目标影片的 fps
    --debug=    是否为调试, 如果是调试, 使用内置参数
                  ''')
        else:
            video_path = mov

    # 打开视频文件
    cap = cv2.VideoCapture(video_path)
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    fps4cap = int(cap.get(cv2.CAP_PROP_FPS))
    # calculate dusration of the video
    seconds = int(frames / fps4cap)
    video_time = str(datetime.timedelta(seconds=seconds))
    # 获取视频宽度和高度
    width = int(cap.get(3))
    height = int(cap.get(4))
    # 计算每一抽帧间平均时长
    avg_duration = int(seconds / (_drops+4))

    print(f'''mov::{video_path}
    frames: {frames}
    fps:    {fps4cap}
    seconds:{seconds} -> {video_time}
    -> avg_duration:{avg_duration}

    width:  {width}
    height: {height}
          ''')

    # 创建空白图片 # RGB颜色值，这里为白色
    img = Image.new('RGB', (CFG['pxw'], CFG['pxh']),(255, 255, 255))
    # 计算每张色条的宽度
    bar_width = CFG['pxw'] // _drops 
    # 计算帧底色变化步长
    step4rgb = 255 // _drops
    #gb1st = (255-step4rgb*_drops)
    crt_gb = 255
    # 初始化画笔
    draw = ImageDraw.Draw(img)
    # 计算每帧的间隔（帧数）
    frame_interval = avg_duration*fps4cap
    frames = []
    with tqdm.trange(_drops) as t:
        for i in t:
            # 读取指定帧
            frame_no =  i * frame_interval
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            ret, frame = cap.read() 
            if not ret:
                break
            # 从当前帧计算主颜色
            bgr_mean = np.mean(frame, axis=(0, 1))
            dominant_color = tuple(bgr_mean.astype(int))
            # 进度条提示文字
            #t.set_description(f'RGB: {dominant_color}')
            # 计算色条左上角坐标
            x = i * bar_width
            y = 0
            draw.rectangle(
                (x, y
                 , x + bar_width - 1, CFG['pxh'])#左上,右下角两点
                , fill=dominant_color
                )
            # 剩余补渐黑
            crt_gb -= step4rgb
            _w4tail = CFG['pxw']- (i+1)* bar_width
            draw.rectangle(
                   ( x + bar_width, y
                       , CFG['pxw'] , CFG['pxh']
                   )
                   , fill=(crt_gb,crt_gb,crt_gb)
                   )
            # 进度条提示文字
            t.set_description(f'({x},0):{x + bar_width}|{_w4tail}')
            #t.set_description(f'({x},0):{dominant_color}/{crt_gb}')
            #img = _put1column(img,draw,x,y,bar_width,dominant_color)
            # 频谱生成过程动画
            #temp_img = img.copy()
            frames.append(img.copy())
            #print()
            #t.set_description(f'frames: {len(frames)}')

    # 保存图片
    img.save(output_image_path)
    print(f"output_image_path:{output_image_path}")
    # 追加文字...
    txt2bg(c, aimp,subt,debug=0)
    #return None

    # 转换每个PIL Image为NumPy数组
    frames_np = [np.array(frame) for frame in frames]
    # moviepy error always : TypeError: must be real number, not NoneType
    #   [write_videofile error · Issue #1625 · Zulko/moviepy](https://github.com/keikoro)
    video_clip = mpe.ImageSequenceClip(frames_np, fps=CFG['fps4vi'])
    video_clip.write_videofile(aimv, fps=CFG['fps4vi'])


    # 追加背景音效
    au2bg4v(c,srmv=aimv,aimv=au2v,debug=0)
    return None

    # 将图片数组转换为图像列表
    img4imageio = [imageio.core.util.Array(frame) for frame in frames_np]
    # 写入视频文件
    imageio.mimwrite(aimv, img4imageio, format='mp4', fps=CFG['fps4vi'])
    print(f"Video has been saved to {aimv}")
    # base OpenCV2 gen. .mp4...
    #cv2exp2v(frames_np,aimv,CFG['fps4vi'])
    #return None
    #video_clip = mpe.ImageSequenceClip(frames_np, fps=CFG['fps4vi'])
    #video_clip.write_videofile(aimv)

#@task
def au2bg4v(c,srmv=None,aimv=None,mp3=CFG['au4mfc'],debug=1):
    '''append bg-music for mfc-anime
    '''
    if debug:
        srmv = "../log/mfc2bg_anime.mp4"
        aimv = "../log/mfc2bg_anime_bgau.mp4"
    else:
        if not srmv:
            print('''USAGE:
        $ inv au2bg4v \
            --srmv= 绝对路径指向 源视频
            --aimv= 绝对路径指向 目标视频
            --mp3= 绝对路径指向 背景音乐
            --debug=1|0 是否在调试
            ''')
    print(f"aimv:{aimv}")
    print(f"mp3:{mp3}")
    #return None
    # 加载视频文件
    video = mpe.VideoFileClip(srmv)
    # 加载背景音乐文件
    background_music = mpe.AudioFileClip(mp3)

    # 获取视频时长
    video_duration = video.duration
    # 获取音频时长
    music_duration = background_music.duration
    print(f'''
    video_duration:{video_duration}
    music_duration:{music_duration}
    ''')
    # 如果音频时长不够，循环处理
    if music_duration < video_duration:
        # 计算需要重复音频的次数
        repeat_count = int(video_duration / music_duration)
        # 使用concatenate_audioclips方法将音频重复连接
        repeated_music = mpe.concatenate_audioclips([background_music] * repeat_count)
        # 截取所需时长的音频
        repeated_music = repeated_music.subclip(0, video_duration)

    # 如果音频过长，截断音频
    if music_duration > video_duration:
        background_music = background_music.subclip(0, video_duration)

    print(f'''FIXED:
    music_duration:{music_duration}
    ''')
    # 将音频与视频合并
    video_with_music = video.set_audio(background_music)

    # 保存合并后的视频
    video_with_music.write_videofile(aimv, codec="libx264")

    print("Video with background music has been generated and saved.")
    return None

def cv2exp2v(frames_np,aimv,fps):
    '''base cv2 gen. mp4
    # 确认每个元素的类型和属性
    for frame in frames_np:
        if not isinstance(frame, np.ndarray):
            raise TypeError("Frames must be NumPy arrays")
        if frame.ndim != 3:
            raise ValueError("Frames must be 3-dimensional (height x width x channels)")
        height, width, channels = frame.shape
        print(height, width)
        if channels != 3:
            raise ValueError("Frames must have 3 channels (RGB)")

    '''
    # 定义视频输出参数
    output_file = aimv
    fps = fps  # 帧率
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # 编码器

    # 获取第一张图片的尺寸
    height, width, _ = frames_np[0].shape

    # 创建视频写入器
    video_writer = cv2.VideoWriter(output_file, fourcc, fps, (width, height))

    # 逐帧写入图片数据
    with tqdm.trange(len(frames_np)) as t:
        for i in t:
            # 进度条提示文字
            t.set_description(f'f:{i}/{len(frames_np)}')
            #for frame in frames_np:
            video_writer.write(frames_np[i])

    print(f"exp. as:{output_file}")
    # 释放资源
    video_writer.release()
    return None


def mix_str(a, b):
    return ''.join(c1 + c2 for c1, c2 in zip(a, b))

def confustr(a):
    return ''.join(CONF.confuse[i] for i in a)

#@task
def _gen4ghwno(c, ghwno=None, debug=0):
    '''生成底图上的混淆序号
    '''
    if debug:
        ghwno = 42
    else:
        if not ghwno:
            print(f'''USAGE:
        $ inv _gen4ghwno \\
            --ghwno= ~要转换的序列号 \\
            --debug=1|0 是否为调试
            ''')
            return None

    _mix = random.randint(1010, 9898)
    str_no = "%04d"%ghwno
    _sequ = confustr(str_no)
    mix_sequ = mix_str(str(_mix), _sequ)
    

    print(f"""...
    _mix:{_mix}
    in
    ghwno:{ghwno} as {str_no}
    => {mix_sequ}
        """)

    return mix_sequ




#@task
def txt2bg(c, aimp=None,subt=None, debug=1):
    '''inject text into img. for mark witch movie ..etc.
    '''
    if debug:
        aimp = CFG['txt2img']
        subt = "Scavengers.Reign.S01E0"

    # 打开图片 
    image = Image.open(aimp) # 直接写回底图
    if not subt:
        print('''USAGE:
    $ inv txt2bg 
    or
    $ inv txt2bg \
        --aimp= 绝对路径指向要输出的最终图片
        --subt= 要注入在左下角的影片信息文本
        --debug=0
        ''')
        return None

    # 准备字体 
    print(CFG['font2img'])
    font_sarasa = ImageFont.truetype(CFG['font2img'])
    image = _txt1n2img(image
                     , font_sarasa
                     , 64
                     , CFG['title']
                     , (0,142,0,200)
                     , 50
                     , 50
                     )
    image = _txt1n2img(image
                     , font_sarasa
                     , 42
                     , CFG['sub_title']%subt
                     , (42,42,42,142)
                     , 150
                     , CFG['pxh']-100
                     )
    font_XQeasy = ImageFont.truetype(CFG['font4self'])
    image = _txt1n2img(image
                     , font_XQeasy
                     , 142
                     , "代码回哨"
                     , (242,242,242,142)
                     , CFG['pxw']/2-242
                     , CFG['pxh']/2-142
                     )

    # 保存结果
    #image.save(CFG['txt2img'])
    image.save(aimp)
    print(f"exp.=>{aimp}")
    return None
