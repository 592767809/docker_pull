
import os
import json
import gzip
import click
import queue
import shutil
import tarfile
import requests
import threading
from typing import Any
from urllib import parse
from loguru import logger
from Crypto.Hash import SHA256


@click.command()
@click.argument("image")
@click.option("-a", "--architecture", type=str, default='amd64', help='镜像架构 (amd64, arm64, arm/v7)')  # amd64 arm64 arm/v7
@click.option("-p", "--proxies", type=str, default='', help='设置HTTP代理服务器')
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
    platform = kwargs['architecture']
    img_name = kwargs['image']
    raw_name = img_name
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
    logger.info('镜像架构：' + platform)
    logger.info('镜像来源：' + image_registry)
    logger.info('镜像用户：' + img_user)
    logger.info('镜像名称：' + img_name)
    logger.info('镜像标签：' + img_tag)
    temp_dir = os.path.join(os.getcwd(), '_'.join([platform, image_registry, img_user, img_name, img_tag, 'tar']))
    out_name = '_'.join([platform, image_registry, img_user, img_name, img_tag]) + '.tar'
    out_path = os.path.join(os.getcwd(), out_name)
    logger.info('本地镜像缓存路径：' + temp_dir)
    logger.info('本地镜像输出路径：' + out_path)
    if os.path.exists(out_path):
        logger.info('镜像已存在')
        return
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    # 判断是否需要token
    image_registry = 'https://' + image_registry
    headers = {
        'Accept': ','.join([
            'application/vnd.oci.image.manifest.v1+json',
            'application/vnd.docker.distribution.manifest.v2+json',
            'application/vnd.docker.distribution.manifest.list.v2+json',
            'application/vnd.oci.image.index.v1+json',
            'application/vnd.docker.distribution.manifest.v1+prettyjws',
            'application/json'
        ])
    }
    response = requests.get(image_registry + '/v2/', proxies=proxies)
    if response.status_code != 200:
        url = response.headers['www-authenticate'].split('"')[1]
        service = response.headers['www-authenticate'].split('"')[3]
        data = {
            'scope': f'repository:{img_user}/{img_name}:pull',
            'service': service
        }
        response = requests.get(url + '?' + parse.urlencode(data), proxies=proxies).json()
        headers['Authorization'] = 'Bearer ' + response['token']
    response = requests.head(f'{image_registry}/v2/{img_user}/{img_name}/manifests/{img_tag}', headers=headers, proxies=proxies)
    logger.info('获取镜像的digest：' + response.headers['docker-content-digest'])
    response = requests.get(f'{image_registry}/v2/{img_user}/{img_name}/manifests/{response.headers['docker-content-digest']}', headers=headers, proxies=proxies).json()
    logger.info('根据镜像的digest获取不同架构的信息')
    if response['mediaType'] == 'application/vnd.oci.image.index.v1+json':
        try:
            digest = filter(lambda n: n['platform']['architecture'] == platform, response['manifests']).__next__()['digest']
        except:
            logger.info('仅允许选择以下架构')
            logger.info(', '.join(set([each['platform']['architecture'] for each in response['manifests'] if each['platform']['architecture'] != 'unknown'])))
            return
        logger.info('选择对应架构的digest')
        logger.info(digest)
        manifest_v1 = requests.get(f'{image_registry}/v2/{img_user}/{img_name}/manifests/{digest}', headers=headers, proxies=proxies).json()
        logger.info('获取镜像清单列表')
        logger.info(manifest_v1["config"]["digest"])
        config = requests.get(f'{image_registry}/v2/{img_user}/{img_name}/blobs/{manifest_v1["config"]["digest"]}', headers=headers, proxies=proxies).json()
        logger.info('获取镜像元数据')
        with open(os.path.join(temp_dir, manifest_v1["config"]["digest"][7:] + '.json'), 'w', encoding='utf-8') as f:
            f.write(json.dumps(config, separators=(',', ':')))
        # 创建manifest.json框架
        manifest = [{
            'Config': manifest_v1["config"]["digest"][7:] + '.json',
            'RepoTags': [raw_name],
            'Layers': []
        }]
        # 开始下载每一个layer
        logger.info(f'总共需要下载 {len(manifest_v1["layers"])} 个layer')
        work_queue = queue.Queue(maxsize=0)
        thread_list = []
        for layer in manifest_v1["layers"]:
            work_queue.put(layer)

        for t in range(8):
            thread = threading.Thread(target=down_layer, args=(work_queue, temp_dir, image_registry, img_user, img_name, headers, proxies))
            thread.start()
            thread_list.append(thread)

        for thread in thread_list:
            thread.join()

        parent_id = ''
        for layer in manifest_v1["layers"]:
            layer_id = SHA256.new(f'{parent_id}\n{layer["digest"]}\n'.encode()).hexdigest()
            layer_path = os.path.join(temp_dir, layer_id)
            if not os.path.exists(layer_path):
                os.makedirs(layer_path)
            os.rename(os.path.join(temp_dir, layer["digest"][7:] + '.tar'), os.path.join(layer_path, 'layer.tar'))
            with open(os.path.join(layer_path, 'VERSION'), 'wb') as f:
                f.write('1.0'.encode())
            layer_json = {
                'id': layer_id,
                'parent': parent_id,
                'created': '1970-01-01T00:00:00Z',
                'container_config': {
                    'Hostname': '',
                    'Domainname': '',
                    'User': '',
                    'AttachStdin': False,
                    'AttachStdout': False,
                    'AttachStderr': False,
                    'Tty': False,
                    'OpenStdin': False,
                    'StdinOnce': False,
                    'Env': None,
                    'Cmd': None,
                    'Image': '',
                    'Volumes': None,
                    'WorkingDir': '',
                    'Entrypoint': None,
                    'OnBuild': None,
                    'Labels': None
                },
                'os': config['os']
            }
            if not parent_id:
                del layer_json['parent']
            with open(os.path.join(layer_path, 'json'), 'wb') as f:
                f.write(json.dumps(layer_json, ensure_ascii=False, separators=(',', ':')).encode())
            manifest[0]['Layers'].append(layer_id + '/layer.tar')
            parent_id = layer_id

        with open(os.path.join(temp_dir, 'manifest.json'), 'wb') as f:
            f.write(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')).encode())
        with open(os.path.join(temp_dir, 'repositories'), 'wb') as f:
            f.write(json.dumps({
                img_name: {
                    img_tag: parent_id
                }
            }, ensure_ascii=False, separators=(',', ':')).encode())
    elif response['mediaType'] == 'application/vnd.docker.distribution.manifest.v2+json':
        logger.info('暂不支持这个镜像下载')
        return
    else:
        logger.info('未知的结构：' + response['mediaType'])
        return

    # 最后打包tar
    with tarfile.open(out_path, "w") as f:
        f.add(temp_dir, arcname=os.path.sep)
    shutil.rmtree(temp_dir)
    logger.info('下载完成 ' + temp_dir)


def down_layer(work_queue, out_dir, image_registry, img_user, img_name, headers, proxies):
    while True:
        if work_queue.empty():
            break
        else:
            layer = work_queue.get()
            layer_path = os.path.join(out_dir, layer["digest"][7:] + '.tar')
            layer_gz_path = os.path.join(out_dir, layer["digest"][7:] + '.tar.gz')
            if os.path.exists(layer_path):
                if os.path.exists(layer_gz_path):
                    os.remove(layer_gz_path)
                continue
            while True:
                try:  # TODO 断点续传
                    response = requests.get(f'{image_registry}/v2/{img_user}/{img_name}/blobs/{layer["digest"]}', headers=headers, proxies=proxies, stream=True)
                    file_size = int(response.headers['Content-Length'])
                    with open(layer_gz_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=1024 * 1024 * 5):
                            if not chunk:
                                break
                            f.write(chunk)
                    if os.path.getsize(layer_gz_path) == file_size:
                        with open(layer_path, 'wb') as fou, open(layer_gz_path, 'rb') as fin:
                            fou.write(gzip.decompress(fin.read()))
                        logger.info('下载完成： ' + layer["digest"])
                        os.remove(layer_gz_path)
                        break
                    else:
                        os.remove(layer_gz_path)
                except:
                    logger.info('链接失败，尝试重试： ' + layer["digest"])


if __name__ == '__main__':
    main()
