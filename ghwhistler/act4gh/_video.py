from _conf import *

def mix_str(a, b):
    return ''.join(c1 + c2 for c1, c2 in zip(a, b))

def confustr(a):
    return ''.join(CONF.confuse[i] for i in a)

#@task
def gen4ghwno(c, ghwno=None, debug=0):
    '''生成底图上的混淆序号
    '''
    if debug:
        ghwno = 42
    else:
        if not ghwno:
            print(f'''USAGE:
        $ inv gen4ghwno \\
            --ghwno= ~要转换的序列号 \\
            --debug=1|0 是否为调试
            ''')
            return None

    _mix = random.randint(1010, 9898)
    str_no = "%04d"%ghwno
    _sequ = confustr(str_no)
    mix_sequ = mix_str(str(_mix), _sequ)
    
    if debug:
        print(f"""...
        _mix:{_mix}
        in
        ghwno:{ghwno} as {str_no}
        => {mix_sequ}
            """)

    return mix_sequ

def txt1n2img(image,font, fsize,txt,color,x,y):
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

    #print(f"txt: {txt}\n\t @({x},{y})")

    # 保存结果
    return image

def put4vstr(img,draw,font,transtep,text,lx=None,ly=None):
    '''ImageDraw模块进行绘制时,坐标系以图像的左上角为原点(0, 0)

    从底部->顶部 无限up...
    '''
    #print(img,draw,idx,text,lx,ly)
    if lx or ly:
        # 上次位置
        #x = lx+42
        y = ly-32
        match (lx%4):
            case 1:
                x = lx
            case 2:
                x = lx-random.randint(1, 2)
            case 3:
                x = lx+random.randint(1, 3)
            case _:
                x = lx-random.randint(1, 4)
        #r = random.randint(1, 42)
        #if r%2 ==0:
        #    #y = ly+random.randint(1, 4)
        #    x = lx+random.randint(1, 4)
        #else:
        #    #y = ly-random.randint(1, 4)
        #    x = lx-random.randint(1, 4)
        #print("x,y",x,y)
    else:
        #print(f'{idx} line init. local')
        # 随机位置出现
        #x = random.sample(range(-142,0),1)[0]
        #print(x)
        x = random.randint(0, img.width)
        #y = random.randint(0, img.height - 42)
        # top->buttom
        #y = random.sample(range(-142,0),1)[0]
        # buttom->top
        y = random.sample(range(img.height-142,img.height),1)[0]

    # 随机生成字体大小
    font_size = random.randint(14, 42)
    #font = ImageFont.truetype(CFG['font2img'], size=font_size)
    # 复制字体对象并修改大小
    font_copy = font.font_variant(size=font_size)
    # 绘制文本
    #draw.text((x, y), text, font=font_copy, fill='white')
    # 给水印添加透明度，因此需要转换图片的格式
    i4rgba=img.convert('RGBA')
    # 创建和原图尺寸一致的水印层, 完全透明
    text_overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
    text_draw = ImageDraw.Draw(text_overlay)
    # 水印层上写入文字
    #transtep = transtep-random.randint(0, 24)
    transtep -= random.randint(0, 24)
    text_draw.text((x, y), text
                , fill=(255, 255, 255, transtep)
                , font=font_copy
                , direction='ttb'
                )
    # 和原图alpha合成
    img = Image.alpha_composite(i4rgba, text_overlay)

    return (img,draw,x, y)

#@task
def evs2v4sequ(c,ghwno=None,ghevents=None,bg4v=CONF.bg4video,debug=0):
    '''将gh事件变成 Matrix 文字流, 并标注片段序列号
    MoviePy 可以直接基于 PIL Image 序列来生成视频,不需要保存每一帧图片
frames = []
for i in range(100):
   frame = generate_frame(i) # 生成每一帧图片
   frames.append(frame)

clip = ImageSequenceClip(frames, fps=25)  
clip.write_videofile('my_video.mp4')
    '''
    is_debug = 'Y' if debug else 'N'
    if debug:
        ghevents = json.load(open(CFG['lastevs'],'r'))
        ghwno = 42
    else:
        if not ghwno:
            print(f"""USAGE:
$ inv evs2v4sequ \\
    --ghevents= 事件字典对象 \\
    --bg4v= 绝对路径指向视频背景图 \\
    --debug=0|1 是否调试状态
            """)
        
    print(f"""evs2v4sequ()
        ghevents: hold {len(ghevents)} events
        bg4v: {bg4v}
        debug: {is_debug}
        Video has been saved to:
            {CONF.fi2v%CONF.v4fps}
        """)
    #print("逐步透明化",CFG['limit'],255)
    #return None
    _anim = []
    for repo in ghevents:
        event = ghevents[repo]
        if 'head' in event['payload']:
            #print(f"\t event head:{event['payload']['head']}")
            _anim.append({'txt':f"{event['payload']['head']}|{event['type']}|{event['id']}|{event['actor']['login']}|{event['actor']['id']}@{event['repo']['name']}:{event['repo']['id']}"})
        else:
            _anim.append({'txt':f"{event['type']}|{event['id']}|{event['actor']['login']}|{event['actor']['id']}@{event['repo']['name']}:{event['repo']['id']}..."})

        #print(f"{_anim[-1]}")
    #return None

    # 准备字体 
    font = ImageFont.truetype(CFG['font2img'], size=12)
    font_sarasa = ImageFont.truetype(CONF.font4sarasa)
    frames = []
    _fn = 0
    #for idx,_ in enumerate(_anim):
    transtep=int(CFG['transtart']/CFG['limit'])
    #for idx in tqdm.trange(CFG['limit']):
    _image = Image.open(bg4v) #CFG['bg4video']
    no4seq = gen4ghwno(c,ghwno=ghwno)
    with tqdm.trange(CFG['limit']) as t:
        for idx in t:
            _transparent = int(255-(transtep*(idx+1)))
            # 进度条提示文字
            t.set_description(f'ts:{_transparent}<-{idx}')
            #print(f"\ttranstep=>{transtep}")
            #img = Image.open(bg4v) #CFG['bg4video']
            ##   直接在图片上绘制文本
            #draw = ImageDraw.Draw(img)
            ## 右下角生成片段序列号
            img = txt1n2img(_image
                            , font_sarasa
                            , 36
                            , no4seq
                            , (255,212,121,142)
                            , CONF.pxw -150
                            , CONF.pxh -150
                            )
            #   直接在图片上绘制文本
            draw = ImageDraw.Draw(img)

            for i in range(idx):
                if 'x' in _anim[i]:
                    img,draw,x,y = put4vstr(img,draw,font
                                    ,_transparent
                                    ,_anim[i]['txt']
                                    , lx= _anim[i]['x']
                                    , ly= _anim[i]['y']
                                    )
                else: # firt draw
                    img,draw,x,y = put4vstr(img,draw,font
                                    ,_transparent
                                    ,_anim[i]['txt']
                                    #, lx= _anim[i]['x']
                                    #, ly= _anim[i]['y']
                                    )
                _anim[i]['x'] = x
                _anim[i]['y'] = y
            #img.save(CFG['f1video'])
            frames.append(img)

            _fn +=1
            #f_exp = CFG['fimg']%(idx+1)
            #f_exp = CFG['fimg']%_fn
            #print("`"*int(_fn/CFG['v4fps']))
    
    #return None
    #print(frames,len(frames))
    
    # 转换每个PIL Image为NumPy数组
    frames_np = [np.array(frame) for frame in frames]
    video_clip = ImageSequenceClip(frames_np, fps=CFG['v4fps'])
    video_clip.write_videofile(CFG['fi2v']%CFG['v4fps'])

    print(f"Video has been saved to {CFG['fi2v']%CFG['v4fps']}")




#@task
def events2v(c,ghevents,bg4v=CFG['bg4video']):
    '''MoviePy 可以直接基于 PIL Image 序列来生成视频,不需要保存每一帧图片
frames = []
for i in range(100):
   frame = generate_frame(i) # 生成每一帧图片
   frames.append(frame)

clip = ImageSequenceClip(frames, fps=25)  
clip.write_videofile('my_video.mp4')
    '''
    print(f"ghevents hold:{len(ghevents)}")
    #print("逐步透明化",CFG['limit'],255)
    #return None
    _anim = []
    for repo in ghevents:
        event = ghevents[repo]
        if 'head' in event['payload']:
            #print(f"\t event head:{event['payload']['head']}")
            _anim.append({'txt':f"{event['id']}|{event['type']}|{event['actor']['id']}|{event['actor']['login']}|{event['repo']['id']}|{event['repo']['name']}|{event['payload']['head']}"})
        else:
            _anim.append({'txt':f"{event['id']}|{event['type']}|{event['actor']['id']}|{event['actor']['login']}|{event['repo']['id']}|{event['repo']['name']}..."})

    # 准备字体 
    font = ImageFont.truetype(CFG['font2img'], size=12)

    frames = []
    _fn = 0
    #for idx,_ in enumerate(_anim):
    transtep=int(CFG['transtart']/CFG['limit'])
    #for idx in tqdm.trange(CFG['limit']):

    with tqdm.trange(CFG['limit']) as t:
        for idx in t:
            _transparent = int(255-(transtep*(idx+1)))
            # 进度条提示文字
            t.set_description(f'ts:{_transparent}<-{idx}')
            #print(f"\ttranstep=>{transtep}")
            img = Image.open(bg4v) #CFG['bg4video']
            #   直接在图片上绘制文本
            draw = ImageDraw.Draw(img)
            for i in range(idx):
                if 'x' in _anim[i]:
                    img,draw,x,y = _draw_line(img,draw,font
                                    ,_transparent
                                    ,_anim[i]['txt']
                                    , lx= _anim[i]['x']
                                    , ly= _anim[i]['y']
                                    )
                else: # firt draw
                    img,draw,x,y = _draw_line(img,draw,font
                                    ,_transparent
                                    ,_anim[i]['txt']
                                    #, lx= _anim[i]['x']
                                    #, ly= _anim[i]['y']
                                    )
                _anim[i]['x'] = x
                _anim[i]['y'] = y
            #img.save(CFG['f1video'])
            frames.append(img)

            _fn +=1
            #f_exp = CFG['fimg']%(idx+1)
            #f_exp = CFG['fimg']%_fn
            #print("`"*int(_fn/CFG['v4fps']))
    
    #return None
    #print(frames,len(frames))
    
    # 转换每个PIL Image为NumPy数组
    frames_np = [np.array(frame) for frame in frames]
    video_clip = ImageSequenceClip(frames_np, fps=CFG['v4fps'])
    video_clip.write_videofile(CFG['fi2v']%CFG['v4fps'])

    print(f"Video has been saved to {CFG['fi2v']%CFG['v4fps']}")


def _draw_line(img,draw,font,transtep,text,lx=None,ly=None):
    '''ImageDraw模块进行绘制时,坐标系以图像的左上角为原点(0, 0)
    从左向右无限流动...

    '''
    #print(img,draw,idx,text,lx,ly)
    if lx or ly:
        #print('base last local line',lx,ly)
        #print("lx,ly",lx,ly)
        # 上次位置
        x = lx+42
        r = random.randint(1, 42)
        if r%2 ==0:
            y = ly+random.randint(1, 4)
        else:
            y = ly-random.randint(1, 4)
        #print("x,y",x,y)
    else:
        #print(f'{idx} line init. local')
        # 随机位置
        x = random.sample(range(-142,0),1)[0]
        #print(x)
        #x = random.randint(1420, img.width)
        y = random.randint(0, img.height - 42)
        #y = random.randint(0, img.height - 42)

    # 随机生成字体大小
    font_size = random.randint(10, 51)
    #font = ImageFont.truetype(CFG['font2img'], size=font_size)
    # 复制字体对象并修改大小
    font_copy = font.font_variant(size=font_size)
    # 绘制文本
    #draw.text((x, y), text, font=font_copy, fill='white')
    # 给水印添加透明度，因此需要转换图片的格式
    i4rgba=img.convert('RGBA')
    # 创建和原图尺寸一致的水印层, 完全透明
    text_overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
    text_draw = ImageDraw.Draw(text_overlay)
    # 水印层上写入文字
    transtep = transtep-random.randint(0, 24)
    text_draw.text((x, y), text
                , fill=(255, 255, 255, transtep)
                , font=font_copy)
    # 和原图alpha合成
    img = Image.alpha_composite(i4rgba, text_overlay)

    return (img,draw,x, y)



#@task
def mergwv4a(c,expv=CFG['v4stream']):
    print(CFG['fi2v']%CFG['v4fps'])
    print(CFG['m1music'])
    #return None
    # 加载视频文件
    video = VideoFileClip(CFG['fi2v']%CFG['v4fps'])

    # 加载背景音乐文件
    background_music = AudioFileClip(CFG['m1music'])

    # 获取视频时长
    video_duration = video.duration

    # 获取音频时长
    music_duration = background_music.duration

    # 如果音频时长不够，循环处理
    if music_duration < video_duration:
        # 计算需要重复音频的次数
        repeat_count = int(video_duration / music_duration)

        # 使用concatenate_audioclips方法将音频重复连接
        repeated_music = concatenate_audioclips([background_music] * repeat_count)
        
        # 截取所需时长的音频
        repeated_music = repeated_music.subclip(0, video_duration)

    # 如果音频过长，截断音频
    if music_duration > video_duration:
        background_music = background_music.subclip(0, video_duration)

    # 将音频与视频合并
    video_with_music = video.set_audio(background_music)

    # 保存合并后的视频
    video_with_music.write_videofile(expv, codec="libx264")

    #print("Video with background music has been generated and saved.")    
    return None
    
