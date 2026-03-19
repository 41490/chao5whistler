from _conf import *

#@task
def crt42event(c,debug=0):
    '''got lasted event from all repo.
    + 如果这次没有拿到gh 数据, 返回 lastevents.json 上次的数据
    + 输出 ../log/lastevents.json
    '''
    if debug:
        print(f"loaded historic evnets:{CFG['lastevs']}")
        active_repositories = json.load(open(CFG['lastevs'],'r'))
        return active_repositories
    
    print(f"API,limit/perp={CFG['limit']/CFG['perp']}")
    #   每次获得的数据并不一定都是 per_pages 要求的
    pages = math.ceil(CFG['limit']/CFG['perp'])+5
    print(f"API,pages={pages}")
    #return None
        

    dict4events = {}
    for i in range(pages):
        #print(f"i for pages:{i+1}")
        # 设置GitHub事件API的URL，获取最近事件
        events_url = f"https://api.github.com/events?per_page={CFG['perp']}&page={i+1}"
        print(events_url)
        # 发送GET请求 
        response = requests.get(events_url, headers=headers)

        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            #method_whitelist=["HEAD", "GET", "OPTIONS"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        http = requests.Session()
        http.mount("https://", adapter)
        #http.mount("http://", adapter)

        try:
            response = http.get(events_url)
        except Exception as e:
            print(f"请求失败,重试了{retry_strategy.total}次")

        # 解析响应数据 
        if response.status_code == 200:
            events_data = response.json()

            print("got events:", len(events_data))
            # 遍历事件数据，加载为事件 dict
            for event in events_data:
                #repo_name = event['repo']['name']
                event_id = event['id']
                # 检查仓库是否已记录，如果没有则添加
                if event_id not in dict4events:
                    dict4events[event_id] = event#['repo']

            #return None

        else:
            print(f"Failed to retrieve events. Status code: {response.status_code}")
        # 随机睡眠200~800毫秒
        pause_time = random.uniform(0.12, 0.64)
        time.sleep(pause_time)
        print(f"\t睡 {int(pause_time*1000)}ms 结束")
        if len(dict4events) >= CONF.evmax:#CONF.limit:
            print(f"GOT ENOUGH events:{len(dict4events)}...")
            break

    if dict4events:
        # 非空
        json.dump(dict4events,open(CFG['lastevs'],'w'))
    else:
        # 加载老的
        #dict4events = json.load(open(CFG['lastevs'],'r'))
        # 等待随机时间再尝试
        pass

    print(f"got gh-events:{len(dict4events)}")
    return dict4events

