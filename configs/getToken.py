# coding=utf-8
"""
宝信项目 - 认证与数据缓存管理
提供登录获取token、JSON数据读写、缓存数据获取等功能
"""
import requests, json
import configs.config as config

host = config.host
evn = config.evn


def jsonData(key, value):
    """读写缓存数据到 data.json 文件
    key: 数据键名
    value: 数据值（传入则写入，不传则仅读取该key的值）
    """
    file_path = config.path + '/configs/data.json'
    try:
        # 读取JSON文件
        with open(file_path, 'r', encoding='utf-8') as json_file:
            data = json.load(json_file)
            # 修改数据
            data[key] = value
            # 将修改后的数据写回文件
        with open(file_path, 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)
    except FileNotFoundError:
        print(f"文件 {file_path} 不存在。")
    except json.JSONDecodeError:
        print(f"文件 {file_path} 不是有效的JSON格式。")
    except Exception as e:
        print(f"发生错误: {e}")


def getToken():
    """宝信系统登录，获取Bearer token
    根据实际项目的认证接口和参数修改
    返回: 包含Authorization的headers字典
    """
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
    }
    # TODO: 根据实际项目修改登录接口地址和认证参数
    data = {
        'grant_type': 'password',
        'username': '&ADMIN&testuser@baoxin.com',
        'password': 'Test123456'
    }
    url = host + "/api/baoxin-auth-center/oauth/token"
    res = requests.post(url, data=data).json()
    headers['Authorization'] = 'Bearer ' + res["data"]['access_token']
    jsonData("getToken", headers)
    return headers


def getData():
    """读取 data.json 中所有缓存数据"""
    file_path = config.path + '/configs/data.json'
    with open(file_path, 'r', encoding='utf-8') as json_file:
        data = json.load(json_file)
    return data


def setData(key, value):
    """设置单个缓存数据到 data.json（简洁版，用于代码生成的响应保存）
    key: 缓存键名
    value: 缓存值
    """
    jsonData(key, value)
    return value
