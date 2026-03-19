from _conf import *

def mp3preload(c):
    #mp3preload = {}
    for eau in CFG['event2audio']:
        #print(eau)
        _mp3 = f"{CONF.ghw2au}/{CFG['event2audio'][eau]}"
        print(eau,_mp3)
        CONF.mp3preload[eau] = AudioSegment.from_mp3(_mp3)

def prel4effects(c):
    #mp3preload = {}
    for eau in CFG['event2audio']:
        #print(eau)
        _mp3 = f"{CONF.ghw2au}/{CFG['event2audio'][eau]}"
        print(f"|> {eau} <~ {_mp3}")
        CONF.mp3preload[eau] = []
        CONF.mp3preload[eau].append(AudioSegment.from_mp3(_mp3))
        for i in range(2, 8, 2):
            _room_size = i/10.0
            ex4effect = f"{CONF.ghw2au}/{eau}-ef{_room_size}.mp3"
            CONF.mp3preload[eau].append(AudioSegment.from_mp3(ex4effect))
    return CONF.mp3preload


@task
def pre2gen4effcau(c):
    '''预生成批量效果追加音频
    '''
    for eau in CFG['event2audio']:
        #print(eau)
        _mp3 = f"{CONF.ghw2au}/{CFG['event2audio'][eau]}"
        print(eau,_mp3)
        for i in range(2, 8, 2):
            _room_size = i/10.0
            ex4effect = f"{CONF.ghw2au}/{eau}-ef{_room_size}.mp3"
            effec2au(c,
                     sau=_mp3,
                     exau=ex4effect,
                     rosize=_room_size,
                     )
            print(f"gen. {ex4effect}")
    return None

from pedalboard.io import AudioFile
from pedalboard import (Pedalboard,
                    Chorus,
                    Reverb,
                    )

#@task
def effec2au(c, sau=None, exau=None,rosize=.1, debug=0):
    '''对 au 追加效果器
    '''
    if debug:
        sau = f"{CONF.ghw2au}/{CONF.event2audio['PushEvent']}"
        exau = "../log/effec2au.mp3"
        print(f'''
        sau:{sau}
        exau:{exau}
            ''')
    # Make a Pedalboard object, containing multiple audio plugins:
    #board = Pedalboard([Chorus(), Reverb(room_size=0.42)])
    board = Pedalboard([
                Chorus(), 
                Reverb(
                    room_size=rosize,
                    ),
            ])
    
    # Open an audio file for reading, just like a regular file:
    with AudioFile(sau) as f:
        # Open an audio file to write to:
        with AudioFile(exau, 'w', f.samplerate, f.num_channels) as o:
            # Read one second of audio at a time, until the file is empty:
            while f.tell() < f.frames:
                chunk = f.read(f.samplerate)
                
                # Run the audio through our pedalboard:
                effected = board(chunk, f.samplerate, reset=False)
                
                # Write the output to our output file:
                o.write(effected)

    return None



#@task
def ev2au4effects(c,ghevents=None,debug=0):
    '''write evnets write into audoio with pre-effect
    '''
    if debug:
        ghevents = json.load(open(CONF.lastevs,'r'))

    #print(f"ghevents got:{len(ghevents)}")
    if not debug:
        mp3preload = CONF.mp3preload
    else:
        mp3preload = prel4effects(c)

    _acts = [ghevents[repo]['type'] for repo in ghevents]
    #_acts = ["IssueCommentEvent","PushEvent","PushEvent","GollumEvent","PushEvent","GollumEvent","PushEvent","GollumEvent"]
    #print(f"{len(_acts)}:\n{_acts[:5]}...")
    #print(f"mp3preload['ReleaseEvent']:{len(mp3preload['ReleaseEvent'])}")
    #return None
    snippets = []
    for e in _acts:
        #snippets.append(mp3preload[e])
        # 加载多个效果器变化后的随机片段之一
        _ri = random.randint(0,len(mp3preload[e])-1)
        #print(f"randint:{_ri}")
        snippets.append(mp3preload[e][_ri])
    #return None
    #print(_acts[:4])
    #_head = ""
    # 创建一个空的音频段，作为最终音频
    appended = AudioSegment.silent(duration=0)
    #crossfaded = AudioSegment.silent(duration=0)
    
    #for idx,snip in enumerate(snippets):
    with tqdm.trange(len(snippets)) as t:
        for idx in t:
            snip = snippets[idx]
            #print(idx,len(snip))
            # 进度条提示文字
            t.set_description(f'{idx}:{len(snip)}')
            if 0 == idx: # 第一个片段
                #_head = snip
                appended = snip
                #mixed = snip
            else:
                # 随机选择叠音时长
                _min = min(len(appended),len(snip))
                mix_dur = random.randint(int(_min*.01),int(_min*.08))
                #dur4snip = len(snip)
                #dur2min4overlay = int(dur4snip*0.10) #最短叠音为后片总长 10%
                #dur2max4overlay = int(dur4snip*0.30)#最长叠音为后片总长 40%
                #dur4overlay = random.randint(dur2min4overlay, dur2max4overlay)
                dur4overlay = mix_dur
                #print(f"    dur4overlay:{dur4overlay}")
                pre_head = appended[:len(appended)-dur4overlay]
                pre_tail = appended[len(appended)-dur4overlay:]
                #print(f"    pre_head:{len(pre_head)}+pre_tail:{len(pre_tail)}")
                head_next = snip[:dur4overlay]

                #mixed = AudioSegment.silent(duration=0)
                mix = pre_tail.overlay(head_next, position=0)
                #print(f"tail_pre:{len(pre_tail)}:overlay:head_next:{len(head_next)}->mix:{len(mix)}")
                appended = pre_head + mix + snip[dur4overlay:]
                #appended = mixed
                #print("after appended",len(appended))
                continue
                if debug:
                    print(f'''
                    mixed:{len(appended)}
                    = pre-hold: {len(pre_head)}
                    + mix:{len(mix)}
                    + cuted sinp:{len(snip[dur4overlay:])}
                        ''')
                #print("after appended",len(appended))

    #print("after mixed",len(mixed))
    #mixed.export(CFG['au4overly'], format="mp3")
    appended.export(CFG['au4overly'], format="mp3")
    print(f"""exp mixed as:{CFG['au4overly']}
        events dur.:{len(appended)}
        """)
    return None



#@task
def mix2au(c,pau=None, tau=None, exau=None,debug=0):
    '''合理 mix 前后两个音效
    '''
    is_debug = 'Y' if debug else 'N'
    if debug:
        pau = f"{CONF.ghw2au}/{CONF.event2audio['PushEvent']}"
        tau = f"{CONF.ghw2au}/{CONF.event2audio['GollumEvent']}"
        exau = "../log/mix2au.mp3"
        exhead = "../log/mix2au0head.mp3"
        exmix = "../log/mix2au1mix.mp3"
        exnext = "../log/mix2au2next.mp3"
        print(f'''
        pau:{pau}
        +
        tau:{tau}
        => exau:{exau}

        debug:{is_debug}
            ''')
    else:
        if not pau:
            print(f'''USAGE:
    $ inv mix2au
        --pau= /path/2/前音频.mp3
        --tau= /path/2/后接.mp3
        --debug=0|1 是否在调试
            ''')

    # 创建一个空的音频段，作为最终音频
    snip0 = AudioSegment.from_mp3(pau)
    snip1 = AudioSegment.from_mp3(tau)

    _min = min(len(snip0),len(snip1))
    mix_dur = random.randint(int(_min*.1),int(_min*.4))
    print(f'''
    snip0:      {len(snip0)}
    snip1:      {len(snip1)}
    dur.min:    {min(len(snip0),len(snip1))}
    mix dur.:   {int(_min*.2)}..{int(_min*.6)}
    random mix: {mix_dur}
    will got:   {len(snip0)+len(snip1)-mix_dur}
        ''')

    mixed = AudioSegment.silent(duration=0)

    pre_head = snip0[:len(snip0)-mix_dur]
    pre_tail = snip0[len(snip0)-mix_dur:]
    head_next = snip1[:mix_dur]
    tail_next=snip1[mix_dur:]
    mix = pre_tail.overlay(head_next, position=0)
    #print(f"tail_pre:{len(pre_tail)}:overlay:head_next:{len(head_next)}->mix:{len(mix)}")
    mixed = pre_head + mix + tail_next

    mixed.export(exau, format="mp3")
    pre_head.export(exhead, format="mp3")
    mix.export(exmix, format="mp3")
    tail_next.export(exnext, format="mp3")

    print(f'''\
    pre_head:   {len(pre_head)}
    +
    pre_tail:   {len(pre_tail)}
    overlay::
        mix:    {len(mix)}
    + 
    tail_next:  {len(tail_next)}
    => mixed:   {len(mixed)}

    exp.:{exau}

    be check:
    pre_head->  {exhead}
    mix->       {exmix}
    tail_next-> {exnext}
    ''')
    return None



#@task
def events2au(c,ghevents):
    '''write lasted evnets random write into audoio.
    '''
    print(f"ghevents got:{len(ghevents)}")
    mp3preload = CONF.mp3preload

    _acts = [ghevents[repo]['type'] for repo in ghevents]
    #_acts = ["IssueCommentEvent","PushEvent","PushEvent","GollumEvent","PushEvent","GollumEvent","PushEvent","GollumEvent"]
    #pp(_acts)
    #return None
    snippets = []
    for e in _acts:
        #_mp3 = f"{CONF.ghw2au}/{CFG['event2audio'][e]}"
        #print(e,_mp3)
        #_audio = AudioSegment.from_mp3(_mp3)
        #snippets.append(_audio)
        snippets.append(mp3preload[e])

    #print(_acts[:4])
    #_head = ""
    # 创建一个空的音频段，作为最终音频
    appended = AudioSegment.silent(duration=0)
    #crossfaded = AudioSegment.silent(duration=0)
    mixed = AudioSegment.silent(duration=0)
    for idx,snip in enumerate(snippets):
        #print(idx,len(snip))
        if 0 == idx: # 第一个片段
            #_head = snip
            appended = snip
            mixed = snip
        else:
            # 随机选择叠音时长
            #print("before mix:appended",len(appended))
            dur4snip = len(snip)
            #print(" mix with:snip",len(snip))
            dur2min4overlay = int(dur4snip*0.10) #最短叠音为后片总长 10%
            dur2max4overlay = int(dur4snip*0.30)#最长叠音为后片总长 40%
            dur4overlay = random.randint(dur2min4overlay, dur2max4overlay)
            #print(f"    dur4overlay:{dur4overlay}")
            pre_head = mixed[:len(appended)-dur4overlay]
            pre_tail = mixed[len(appended)-dur4overlay:]
            #print(f"    pre_head:{len(pre_head)}+pre_tail:{len(pre_tail)}")
            head_next = snip[:dur4overlay]
            mix = pre_tail.overlay(head_next, position=0)
            #print(f"tail_pre:{len(pre_tail)}:overlay:head_next:{len(head_next)}->mix:{len(mix)}")
            mixed = pre_head + mix + snip[dur4overlay:]
            appended +=snip
            #print("after appended",len(appended))
            continue
            print(f'''
            mixed:{len(mixed)}
            = pre-hold: {len(pre_head)}
            + mix:{len(mix)}
            + cuted sinp:{len(snip[dur4overlay:])}
                  ''')
            #print("after appended",len(appended))

    print("after mixed",len(mixed))
    mixed.export(CFG['au4overly'], format="mp3")
    print(f"exp mixed as:{CFG['au4overly']}")
    return None
    appended.export(CFG['au4append'], format="mp3")
    print(f"exp appended as:{CFG['au4append']}")
    return None




#@task
def au4bgmusic(c):
    '''mege event audio with bg ground music
    这里的关键步骤是:
    1. 使用 AudioSegment.from_mp3() 载入音频文件
    2. 使用 - 操作符调节背景音量,数字表示 dB
    3. 使用 overlay() 方法叠加背景音乐和事件音频
    4. 使用 export() 将叠加后的音频导出为文件
    overlay() 会将两段音频混合在一起,事件音量不变,背景音量减弱。
    这样我们就可以实现背景音乐和事件音频的叠加效果。pydub 提供了丰富的音频处理接口,可以方便实现各种音频编辑功能。
    '''

    # 载入音频文件
    _mp3bg = f"{CONF.ghw2au}/{CFG['music4bg']}"
    _mp3ev = CFG['au4overly']
    #print(f'merge {_mp3ev} under {_mp3bg}')
    bg = AudioSegment.from_mp3(_mp3bg)
    eve = AudioSegment.from_mp3(_mp3ev)

    # 调节背景音量到原来的一半
    bg = bg + 0
    #bg = bg -6
    #eve = eve - 10
    eve = eve + 3

    # 叠加音频 
    combined = bg.overlay(eve)

    # 导出音频  
    combined.export(CFG['m1music'], format="mp3")
    print(f"gen.::{CFG['m1music']}")


