__project__ = 'ghwhistler/act4gh'
__version__ = 'v.231115.1142'
__author__ = 'Zoom.Quiet'
__license__ = 'MIT@2023-11'

import sys

from _conf import *
from _events import *
from _audio import *
from _video import *

@task
def ver(c):
    '''echo crt. verions
    '''
    print('''
    {}
    <:grasp GitHub top repo. real actions:>
    ~> version   {} <~
    ~> powded by {} <~
    '''.format(__project__
               ,__version__
               ,__author__
               ))
    #print(dir(_mp3preload))
    # 使用 sys.modules 获取当前加载的所有模块对象
    loaded_modules = list(sys.modules.keys())
    # 打印所有加载的模块对象
    print(f'''
    loaded_modules: {len(loaded_modules)}
    is mp3preload: {'mp3preload' in loaded_modules}
          ''')

def get_files_with_extension(directory, extension):
    file_list = []
    for file in os.listdir(directory):
        if file.endswith(extension):
            file_list.append(file)
    
    #file_list.sort()  # 按文件名字母顺序排序
    mp4sort = natsorted(file_list)
    return mp4sort


@task
def gen1cron(c, vp=CONF.gen2path,sp=1,debug=1):
    '''定期生成一则视频, 并记录使用的数据
    '''
    print(f'''USAGE:
    $ inv gen1cron --debug=1|0 
        --vp=path/2/视频入口目录
        --sp= ~ 视频序号开始数字, 默许为1
    ''')

    sub_start = time.perf_counter()
    print(f"{'~'*42}")
    print(f"开始生成 1 条回响视频段\n\n")

    
    print(f"|> log:{CONF.gen1ghw}\n json<-{CONF.gen4json}\n mp4->{vp}")
    
    if os.path.exists(CONF.gen1ghw):
        #print("文件存在")
        cfg4cron = json.loads(open(CONF.gen1ghw,'r').read())
    else:
        print(f"|> 文件不存在:{CONF.gen1ghw}")
        cfg4cron = {'use6j':None,
                    }

    if debug:
        cfg4cron['use6j'] = "ghe-231116-033600-921769.json"

    ev_json = get_files_with_extension(CONF.gen4json,".json")
    print(f"|> ev_json:\n\t {len(ev_json)}")
    print(f"|> cfg4cron['use6j']:{cfg4cron['use6j']}")
    #for i in ev_json[:10]: print(i)
    
    idx4loarded = None
    if cfg4cron['use6j']:
        for idx,item in enumerate(ev_json):
            # 标记用过的 json, 以此为标记, 抛弃之前的
            if item == cfg4cron['use6j']:
                print(f"|> \t {idx}?{cfg4cron['use6j']}")
                idx4loarded = idx
                break
    #print(f"usaded idx:\n\t {idx4loarded} \n{'-'*42}")
    #for i in ev_json[:10]: print(i)
    #print(f"\n{'-'*42}")
    #print(f"{ev_json[idx4loarded]}")
    #print(f"{ev_json[idx4loarded+1]}")
    
    #return None
    # 遍历事件数据，加载为事件 dict
    if idx4loarded:
        ev_json = ev_json[idx4loarded+1:]

    print(f"|> jumped ev_json:\n\t {len(ev_json)}")
    dict4events = {}
    is_enough = 0
    for evej in ev_json:
        #repo_name = event['repo']['name']
        f_json = f"{CONF.gen4json}/{evej}"
        events4json = json.loads(open(f_json,'r').read())
        print(f"|> loaded:{f_json}")
        #pp(event)
        #break
        #print(event.keys())
        for event_id in events4json:
            # 检查仓库是否已记录，如果没有则添加
            if event_id not in dict4events:
                dict4events[event_id] = events4json[event_id]#['repo']

            if len(dict4events) >= CONF.evmax:#CONF.limit:
                print(f"|> GOT ENOUGH events:{len(dict4events)}...")
                # 最终写回日志
                cfg4cron['use6j'] = evej
                # 记录回日志文件
                open(CONF.gen1ghw,'w').write(json.dumps(cfg4cron))
                is_enough = 1
                break
        if is_enough:
            break

    
    prel4effects(c)

    mp4ev = get_files_with_extension(vp,".mp4")
    print(f"|> mp4ev: {len(mp4ev)}")
    if 0==len(mp4ev):
        mp4will=sp
    else:
        print(f"|> mp4ev: {len(mp4ev)}, last:{mp4ev[-1]}")
        mp4will = int(mp4ev[-1].split('.')[0])+1
    print(f"|> next mp4: {mp4will}")
    #return None

    # 加载当前事件
    ghe = dict4events#crt42event(c) # 默认 debug=0
    # 连接匹配事件音效
    ev2au4effects(c,
                ghevents=ghe
                )# 默认 debug=0
    # 追加背景音乐到事件音效
    au4bgmusic(c)
    #return None

    #   要追加不同的序列号在对应背景图片上...形成视频
    evs2v4sequ(c
                , ghwno=mp4will
                , ghevents=ghe
                , bg4v=CONF.bgs4mov[mp4will%len(CONF.bgs4mov)]
                )

    #_expv = f"{CONF.gen2path}/{mp4will}.mp4"
    _expv = f"{vp}/{mp4will}.mp4"
    #   事件动画注入对应事件音效
    mergwv4a(c,expv=_expv)

    sub_end = time.perf_counter() 
    print(f"{'~'*42}")
    print(f"1 条回响视频段完成生成")
    print('\tTotal time:{:.3f}s'.format(sub_end - sub_start))
    print(f"{'~'*42}")

    return None


#@task
def ghw(c, test=0, debug=1):
    '''test ghWhistler main work flow 1time
    '''
    _start = time.perf_counter()
    print(f"{'*'*42}")
    print(f"开始生成 1 段回响视频段")
    print(f"{'*'*42}")
    ghe = crt42event(c,debug=debug)
    if len(ghe) < CFG['limit']:
        print("ALERT!\n\tgot events:{len(ghe)}\n\tNOT ENOUGH...")
        return None

    prel4effects(c)

    if test:
        #return None
        #events2v(c,ghe,CFG['mov2bgs'][4])
        ev2au4effects(c,
                  ghevents=ghe,
                  debug=debug)
        au4bgmusic(c)
        return None

    ev2au4effects(c,
                  ghevents=ghe,
                  debug=debug)
    au4bgmusic(c)
    #events2v(c,ghe,CFG['mov2bgs'][4])
    evs2v4sequ(c,
               #ghwno=None,
               #ghevents=None,
               #bg4v=CONF.bg4video,
               debug=debug)
    mergwv4a(c)
        
    _end = time.perf_counter() 
    print(f"{'*'*42}")
    print(f"完成生成 1 段回响视频段")
    print('\tTotal time:{:.3f}'.format(_end - _start))
    print(f"{'*'*42}")
    return None
    #return None
    #events2img(c,ghe)

@task
def c2gen(c, sno=1,want=10):
    '''--sno=起始序号 --want=需要数量 ~ 批量输出ghW视频
    '''
    #return None
    _start = time.perf_counter()
    print(f"{'*'*42}")
    print(f"开始批量生成 {want} 段回响视频段")
    print(f"{'*'*42}")

    print(f'''
    sno: {sno}
    need:{want} 
    max: {sno+want}
    exp. -> {CONF.exp2vlog}
        ''')
    #return None
    prel4effects(c)

    for i in range(int(sno),int(sno+want)):
        sub_start = time.perf_counter()
        print(f"{'~'*42}")
        print(f"开始生成 No.{i} 回响视频段\n\n")

        ghe = crt42event(c) # 默认 debug=0

        _retry = CONF.retry
        # 随机睡眠200~800毫秒
        if len(ghe) >= CONF.evmax:#CONF.limit:
            print(f"GOT ENOUGH events:{len(ghe)}...")
            #continue
        else:
            pause_time = random.uniform(0.42, 1.42)
            time.sleep(pause_time)
            print(f"\t睡 {int(pause_time*1000)}ms=> RETry")
            ghe = crt42event(c) # 默认 debug=0
            _retry -=1
            if 0>_retry:
                print(f"ALERT!\n\t retry {CONF.retry} times!\n\t events:{len(ghe)}\n\t NOT ENOUGH...")
                continue
                
        #if len(ghe) < CFG['limit']:
        #    print("ALERT!\n\tgot events:{len(ghe)}\n\tNOT ENOUGH...")
        #    continue
        #events2au(c,ghe)
        ev2au4effects(c,
                  ghevents=ghe
                  )# 默认 debug=0
        au4bgmusic(c)
        #events2v(c,ghe,CFG['mov2bgs'][i%len(CFG['mov2bgs'])])
        #   要追加不同的序列号在对应背景图片上...
        evs2v4sequ(c
                   , ghwno=i
                   , ghevents=ghe
                   , bg4v=CONF.bgs4mov[i%len(CONF.bgs4mov)]
                   )
        mergwv4a(c,expv=CONF.exp2vlog%i)

        sub_end = time.perf_counter() 
        print(f"{'~'*42}")
        print(f"No.{i} 回响视频段完成生成")
        print('\tTotal time:{:.3f}'.format(sub_end - sub_start))
        print(f"{'~'*42}")

    _end = time.perf_counter() 
    print(f"{'*'*42}")
    print(f"完成批量生成{want}段回响视频段")
    print('\tTotal time:{:.3f}'.format(_end - _start))
    print(f"{'*'*42}")
    #print('\n\tTotal time:{:.3f}'.format(_end - _start))




'''
curl -H "Authorization: token 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" https://api.github.com/events?per_page=60

'''
