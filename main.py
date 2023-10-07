
import os
import ssl
import sys
import json
import gzip
import socket
import shutil
import tarfile
import hashlib
import threading
import traceback
from urllib import parse, request


def get_data(url, headers, send_type):
    url_parse = parse.urlparse(url)
    socket.setdefaulttimeout(10)
    i = 0
    while True:
        try:
            if url_parse.scheme == 'https':
                sock = ssl.wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
                sock.connect((url_parse.hostname, 443))
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((url_parse.hostname, 80))
            break
        except:
            i += 1
            print('链接失败，尝试重试： ' + url)
            if i == 10:
                raise Exception('')
    send_data = send_type + ' ' + url + ' HTTP/1.1\r\n'
    send_data += 'Host: ' + str(url_parse.hostname) + '\r\n'
    send_data += 'User-Agent: docker/20.10.23 go/go1.18.10 git-commit/6051f14 kernel/5.10.16.3-microsoft-standard-WSL2 os/linux arch/amd64 UpstreamClient(Docker-Client/20.10.23 \(windows\))' + '\r\n'
    for key in headers:
        if type(headers[key]) == list:
            for each in headers[key]:
                send_data += key + ':' + each + '\r\n'
        else:
            send_data += key + ': ' + headers[key] + '\r\n'
    send_data += '\r\n'
    sock.send(send_data.encode())
    buffer = b''
    while True:
        try:
            temp = sock.recv(1024)
            if temp:
                buffer += temp
            else:
                break
        except:
            if buffer:
                break
    temp = buffer[:buffer.find(b'\n')].strip(b'\r')
    status_code = int(temp.split(b' ')[1].decode())
    buffer = buffer[buffer.find(b'\n') + 1:]
    headers = dict()
    while buffer[buffer.find(b'\n') + 1] != 13 and buffer[buffer.find(b'\n') + 2] != 10:
        key, value = buffer[:buffer.find(b'\n')].strip(b'\r').split(b': ')
        headers[key.decode().lower()] = value.decode()
        buffer = buffer[buffer.find(b'\n') + 1:]
    key, value = buffer[:buffer.find(b'\n')].strip(b'\r').split(b': ')
    headers[key.decode().lower()] = value.decode()
    content = buffer[buffer.find(b'\n') + 3:]
    return {
        'status_code': status_code,
        'headers': headers,
        'content': content
    }


def get_response(url):
    i = 0
    while True:
        try:
            response = request.urlopen(url).read()
            return response
        except:
            i += 1
            print('链接失败，尝试重试： ' + url)
            if i == 10:
                raise Exception('')


def down_layer(layer, layer_path, base_url, image_library, tar_name, headers):
    while not os.path.exists(layer_path):
        try:
            layer_url = get_data(f'{base_url}/v2/{image_library}/{tar_name}/blobs/{layer["digest"]}', headers, 'GET')['headers']['location']
            layer_gzip = get_response(layer_url)
            with open(layer_path, 'wb') as f:
                f.write(gzip.decompress(layer_gzip))
            print('下载完成： ' + os.path.abspath(layer_path))
            break
        except:
            print('链接失败，尝试重试： ' + layer["digest"])


def main():
    try:
        image_name = sys.argv[1]
        try:
            base_url = sys.argv[2]
        except:
            base_url = 'https://registry-1.docker.io'
        try:
            image_library, tar_name = image_name.split('/')
        except:
            image_library = 'library'
            tar_name = image_name
        try:
            tar_name, image_tag = tar_name.split(':')
        except:
            image_tag = 'latest'
        if os.path.exists(os.path.join(os.getcwd(), tar_name + '.tar')):
            print('镜像已存在')
            return
        file_path = os.path.join(os.getcwd(), tar_name)
        if not os.path.exists(file_path):
            os.makedirs(file_path)
        platform = 'amd64'
        token = ''
        if base_url == 'https://registry-1.docker.io':
            data = {
                'scope': f'repository:{image_library}/{tar_name}:pull',
                'service': 'registry.docker.io'
            }
            # 获取请求所需的token
            response = get_response('https://auth.docker.io/token?' + parse.urlencode(data))
            try:
                token = json.loads(response)['token']
                print('获取token: ' + token)
            except:
                print(response)
                return
        headers = {
            'Accept': [
                'application/vnd.oci.image.manifest.v1+json',
                'application/vnd.docker.distribution.manifest.v2+json',
                'application/vnd.docker.distribution.manifest.list.v2+json',
                'application/vnd.oci.image.index.v1+json',
                'application/vnd.docker.distribution.manifest.v1+prettyjws',
                'application/json'
            ]
        }
        if token:
            headers['Authorization'] = 'Bearer ' + token

        # 获取镜像的digest
        response = get_data(f'{base_url}/v2/{image_library}/{tar_name}/manifests/{image_tag}', headers, 'HEAD')['headers']
        print(response)
        # 根据镜像的digest获取不同架构的信息
        response = json.loads(get_data(f'{base_url}/v2/{image_library}/{tar_name}/manifests/{response["docker-content-digest"]}', headers, 'GET')['content'].decode())
        print(response)
        # 选择对应架构的digest
        digest = filter(lambda n: n['platform']['architecture'] == platform, response['manifests']).__next__()['digest']
        print(digest)
        # 获取镜像清单列表
        manifest_v1 = json.loads(get_data(f'{base_url}/v2/{image_library}/{tar_name}/manifests/{digest}', headers, 'GET')['content'].decode())
        print(manifest_v1)
        # 获取镜像元数据
        config_url = get_data(f'{base_url}/v2/{image_library}/{tar_name}/blobs/{manifest_v1["config"]["digest"]}', headers, 'GET')['headers']['location']
        config = get_response(config_url)
        with open(os.path.join(file_path, manifest_v1["config"]["digest"][7:] + '.json'), 'wb') as f:
            f.write(config)
        config = json.loads(config.decode())
        # 创建manifest.json框架
        manifest = [{
            'Config': manifest_v1["config"]["digest"][7:] + '.json',
            'RepoTags': [f'{image_name}:{image_tag}'],
            'Layers': []
        }]
        print(manifest)
        # 开始下载每一个layer
        print(f'总共需要下载 {len(manifest_v1["layers"])} 个layer')
        thread_list = []
        for layer in manifest_v1["layers"]:
            layer_path = os.path.join(file_path, layer["digest"][7:] + '.tar')
            thread = threading.Thread(target=down_layer, args=(layer, layer_path, base_url, image_library, tar_name, headers))
            thread.start()
            thread_list.append(thread)

        for thread in thread_list:
            thread.join()

        parent_id = ''
        for layer in manifest_v1["layers"]:
            layer_id = hashlib.sha256(f'{parent_id}{layer["digest"]}'.encode()).hexdigest()
            layer_path = os.path.join(file_path, layer_id)
            if not os.path.exists(layer_path):
                os.makedirs(layer_path)
            os.rename(os.path.join(file_path, layer["digest"][7:] + '.tar'), os.path.join(layer_path, 'layer.tar'))
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
            print('下载完成： ' + parent_id)
        with open(os.path.join(file_path, 'manifest.json'), 'wb') as f:
            f.write(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')).encode())
        with open(os.path.join(file_path, 'repositories'), 'wb') as f:
            f.write(json.dumps({
                image_name: {
                    image_tag: parent_id
                }
            }, ensure_ascii=False, separators=(',', ':')).encode())

        # 最后打包tar
        with tarfile.open(os.path.join(os.getcwd(), tar_name + '.tar'), "w") as f:
            f.add(file_path, arcname=os.path.sep)
        shutil.rmtree(file_path)
        print('下载完成 ' + os.path.abspath(os.path.join(os.getcwd(), tar_name + '.tar')))
    except:
        print(traceback.format_exc())


if __name__ == '__main__':
    main()
