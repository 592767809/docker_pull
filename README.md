# docker_pull
免安装docker下载镜像

# 依赖
python环境，然后安装三方库
pip install -r requirements.txt

# 使用方法

## 直接使用
    python main.py mysql
    python main.py mysql:8.0.0
    python main.py linuxserver/transmission

## 增加代理
    python main.py mysql -p http://127.0.0.1:7890

## 指定镜像架构
    python main.py mysql -a amd64
