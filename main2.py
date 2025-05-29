
import click
import requests
import threading
from typing import Any


@click.command()
@click.argument("image")
@click.option("-a", "--architecture", type=str, default='amd64', help='镜像架构 (amd64, arm64, arm/v7)')  # amd64 arm64 arm/v7
@click.option("-p", "--proxies", type=str, default='', help='设置HTTP代理服务器')  # amd64 arm64 arm/v7
@click.pass_context
def main(ctx: click.Context, *args: Any, **kwargs: Any):
    if kwargs['proxies']:
        proxies = {
            'http': kwargs['proxies'],
            'https': kwargs['proxies'],
        }
    else:
        proxies = None
    # 分析镜像信息
    img_name = kwargs['image']
    if ':' in img_name:
        img_name, img_tag = img_name.split(':')
    else:
        img_tag = ''
    img_name = img_name.split('/')
    if len(img_name) > 3:
        raise Exception('错误的镜像名： ' + '/'.join(img_name) + (':' + img_tag if img_tag else ''))
    if len(img_name) == 3:
        image_registry, img_user, img_name = img_name
    elif len(img_name) == 2:
        img_user, img_name = img_name
        image_registry = 'registry-1.docker.io'
    else:
        img_name = img_name[0]
        image_registry = 'registry-1.docker.io'
        img_user = 'library'
    if not img_tag:
        img_tag = 'latest'
    print(image_registry, img_user, img_name, img_tag)




if __name__ == '__main__':
    main()
