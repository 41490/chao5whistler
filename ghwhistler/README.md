# ghwhistler
> github 回哨


## background

Youtube 需要无限自动直播节目


## goal

- 以 github 真实仓库行动, 为触发
- 生成无限白噪音
- 配套静态/无限循环 gif 图片, 变成无限视频流
- 通过 ffmpeg 变成直播流...


# tracing

- 231124 ghw3 音乐重构 cosmos v1
    + 迁移仓库到 git.code.tencent.com/IAS41490/ghwhistler
    + 选择 音频集
    + 上传剧集...本地无法进行
- 231122 深化持续直播支持
    + 定期删除生成过的事件数据
    + 增补定期视频生成行为, 指定输出目录, 指定起始序号...
    + 检验无限嵌套播放列表:
        + 手工构建两个嵌套播放列表
        + 小号直播观查
        + ffmpeg -re -f concat -i "list1.txt" -f flv "rtmp://xxx"
        + ffmpeg -re -f concat -safe 0 -i "/opt/vlog/ffconcat0li.txt" -f flv "rtmp://a.rtmp.youtube.com/live2/amj3-qauw-v6p3-uvfp-3gd8"
        + 失败:
```
Impossible to open '/opt/vlog/ffconcat1li.txt'
/opt/vlog/ffconcat0li.txt: Operation not permitted
/opt/vlog/ffconcat0li.txt: Input/output error
```
- 231116 crontab 自动永久摄取 gh-events
    + crontab 中调用 conda 环境?
    + crontab->log-> /opt/logs/dama1m_crontab.log
    + crontab-> csv -> /opt/logs/ghevents/yymmdd-hhmmss.csv
- 231113 mix au by FFmpeg:
    + ffmpeg -i 1.mp3 -i 2.mp3 -filter_complex "[0:a]adelay=400|400[del];[1:a][del]amix" -map 0:a -map 1:a -c:a libmp3lame -y mix.mp3
    + 继续升级:
        + Matrix 化:
            + 频谱横向, 随机等待
                + 
            + 文字流竖向
                + $ sudo aptitude -y install libraqm-dev
    + 为了观察播放进展, 嵌入序号:
        + 随机数字间隔字母替代的真正数字
            + 0 : O
            + 1 : I
            + 2 : r
            + 3 : E
            + 4 : A
            + 5 : S
            + 6 : b
            + 7 : T
            + 8 : B
            + 9 : P
            + ... 4O4O5O6I -> 0001
- 231112 测试直播
    + [python - I have a ffmpeg command to concatenate 300+ videos of different formats. What is the proper syntax for the concat complex filter? - Stack Overflow](https://stackoverflow.com/questions/71992615/i-have-a-ffmpeg-command-to-concatenate-300-videos-of-different-formats-what-is)
    + 
- 231111  moviepy error always : TypeError: must be real number, not NoneType
    + [write_videofile error · Issue #1625 · Zulko/moviepy](https://github.com/keikoro)
    [write_videofile error · Issue #1625 · Zulko/moviepy](https://github.com/keikoro)
    + $ pip uninstall moviepy decorator
    + $ pip install moviepy
    + can fixed it...
- 231110 重装
    + $ conda remove -n py311 --all
    + $ conda create --name py310 python=3.10
    + $ conda install Pillow,opencv
    + $ pip install -r requirements.txt
    + moviepy 重新可用...
- 231108 核算所有时间:
    + 单次生成 59s 视频
    + 用时: Total time:268.602
    + ~= 5倍时间
    + 全天1440分钟
    + 至少要提前准备 1500份 视频
    + ~= 450000秒,7500分钟,125小时,5.2天
    + 25Mb 每个,36.6Gb
    + 日志化收集
        + $ inv ghw > ../log/ghw.log 2>&1
    + 并发生产:
        + $ inv cgen --sno=33 --want=721 > ../log/gen4day1.log 2>&1
        + $ inv cgen --sno=721 --want=721 > ../log/cgen4day1.log 2>&1

- 231107 cv2 -> 电影 framw-color-spectra img.
    + conda install opencv
    + 要求 py3.12 以下
    +  python3 -c "import cv2; print(cv2.__version__)"
> 4.6.0     
    + poetry 管理依赖包:
        + conda install poetry
        + poetry add requests

- ...
- 231102 Claude 进行思路组织
    + miniConda 安装
        + wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
        + chmod +x Miniconda3-latest-Linux-x86_64.sh
        + ./Miniconda3-latest-Linux-x86_64.sh
        + conda search python
        + conda create --name py312 python=3.12
    + gh Developer Settings: token
        + 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
    + code-server install
        + Install Code-Server for VS code on Ubuntu 22.04 or 20.04 LTS
https://linux.how2shout.com/install-code-server-for-vs-code-on-ubuntu-22-04-or-20-04-lts/
        + wget https://github.com/coder/code-server/releases/download/v4.18.0/code-server_4.18.0_amd64.deb
        + sudo apt install ./code-server_*_amd64.deb
        + sudo systemctl enable --now code-server@$USER
        + sudo systemctl start code-server@$USER
        + Nginx Proxy on Ubuntu 22.04 | 20.04
            + sudo apt install nginx -y
            + sudo systemctl start nginx
            + sudo systemctl enable nginx
            + sudo systemctl status nginx
            + 配置: /etc/nginx/sites-available/code-server
            + sudo systemctl restart nginx
            + sudo systemctl restart code-server@$USER
            + sudo ufw allow 80
            + sudo ufw allow 443

```
server {
listen 80;
listen [::]:80;
server_name code.swn.101.so;
location / {
    proxy_pass http://localhost:8080/;
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection upgrade;
    proxy_set_header Accept-Encoding gzip;
    }
}

```

ssh -N -L 18080:127.0.0.1:8080 ubuntu@40.233.83.61


## bottom
bottom - crates.io: Rust Package Registry
https://crates.io/crates/bottom


### x86-64
curl -LO https://github.com/ClementTsang/bottom/releases/download/0.9.6/bottom_0.9.6_amd64.deb
sudo dpkg -i bottom_0.9.6_amd64.deb

### ARM64
curl -LO https://github.com/ClementTsang/bottom/releases/download/0.9.6/bottom_0.9.6_arm64.deb
sudo dpkg -i bottom_0.9.6_arm64.deb

### ARM
curl -LO https://github.com/ClementTsang/bottom/releases/download/0.9.6/bottom_0.9.6_armhf.deb
sudo dpkg -i bottom_0.9.6_armhf.deb

## HTTPS

sudo apt install certbot python3-certbot-nginx -y

sudo certbot --nginx -d code.swn.101.so


