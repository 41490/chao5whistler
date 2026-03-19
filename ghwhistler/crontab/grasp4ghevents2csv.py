from datetime import datetime
from urllib3.util.retry import Retry
import json

import requests
from requests.adapters import HTTPAdapter


headers= {
    'Authorization': 'token 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',
}

def gen4ts():
    current_time = datetime.now()
    timestamp = current_time.strftime('%y%m%d-%H%M%S-%f')
    #print(timestamp)
    return timestamp


def got4gheve():
    # 设置GitHub事件API的URL，获取最近事件
    events_url = f"https://api.github.com/events?per_page=100"
    #print(events_url)
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

        _ts = gen4ts()
        _exp = f"/opt/logs/ghevents/ghe-{_ts}.json"
        ghevents = {}

        for event in events_data:
            #repo_name = event['repo']['name']
            event_id = event['id']
            # 检查仓库是否已记录，如果没有则添加
            if event_id not in ghevents:
                ghevents[event_id] = event#['repo']

        print(f"got events:{len(ghevents)}, exp.{_exp}" )
        json.dump(ghevents,open(_exp,'w'))
        
        return None
        # 遍历事件数据，加载为事件 dict
        for repo in ghevents:
            event = ghevents[repo]
            if 'head' in event['payload']:
                #print(f"\t event head:{event['payload']['head']}")
                _event = {'txt':f"{event['payload']['head']}|{event['type']}|{event['id']}|{event['actor']['login']}|{event['actor']['id']}@{event['repo']['name']}:{event['repo']['id']}"}
            else:
                _event ={'txt':f"{event['type']}|{event['id']}|{event['actor']['login']}|{event['actor']['id']}@{event['repo']['name']}:{event['repo']['id']}..."}
            print(_event)
        #return None
    else:
        print(f"{_ts} got gh-events FAIL!")

if __name__ == "__main__":
    #print("Hello, World!")
    got4gheve()
    #gen4ts()



