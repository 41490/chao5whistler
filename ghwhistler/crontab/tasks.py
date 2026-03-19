__project__ = 'ghwhistler/crontab'
__version__ = 'v.231122.1742'
__author__ = 'Zoom.Quiet'
__license__ = 'MIT@2023-11'

import sys

from _conf import *

@task
def ver(c):
    '''echo crt. verions
    '''
    print('''
    {}
    <:clean usaged GitHub events .json files:>
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
def del4json(c, debug=0):
    '''定期清除已经使用过的 .json
    '''
    print(f'''USAGE:
    $ inv del4json --debug=1|0 
    ''')

    #sub_start = time.perf_counter()
    #print(f"{'~'*42}")
    #print(f"开始生成 1 条回响视频段\n\n")


    jsons = get_files_with_extension(CONF.gen4json,".json")
    print(f"|> GitHub events data: {CONF.gen4json}")
    print(f"|> .josn HOLD: {len(jsons)}, last:{jsons[-1]}")

    
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

    # 遍历事件数据，加载为事件 dict
    if idx4loarded:
        #ev_json = ev_json[idx4loarded+1:]
        ev_json = ev_json[:idx4loarded-1]
    
    print(f"will del:{len(ev_json)} JSON files")
    for j in ev_json:
        _jfile = f"{CONF.gen4json}/{j}"
        os.remove(_jfile)
        print(f"remove ~> {_jfile}")
    return None

    #sub_end = time.perf_counter() 
    #print(f"{'~'*42}")
    #print(f"1 条回响视频段完成生成")
    #print('\tTotal time:{:.3f}s'.format(sub_end - sub_start))
    #print(f"{'~'*42}")

    return None



