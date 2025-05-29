
import click
import requests
from typing import Any


@click.command()
@click.argument("image")
@click.option("-a", "--architecture", type=str, default='amd64', help='镜像架构 (amd64, arm64, arm/v7)')  # amd64 arm64 arm/v7
@click.option("-p", "--proxy", type=str, default='', help='设置HTTP代理服务器')  # amd64 arm64 arm/v7
@click.pass_context
def main(ctx: click.Context, *args: Any, **kwargs: Any):
    print('')


if __name__ == '__main__':
    main()
