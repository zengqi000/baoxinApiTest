import json
import os


class CacheService:
    def __init__(self, cache_file):
        self.cache_file = cache_file
        self.data = self._load_data()

    def _load_data(self):
        if not os.path.exists(self.cache_file):
            return {"datas": {}, "headers": {}}
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"datas": {}, "headers": {}}

    def _save_data(self):
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_datas(self):
        # 每次从文件实时读取，避免修改 data.json 后需重启服务才能生效
        return self._load_data().get("datas", {})

    def get_headers(self):
        # 每次从文件实时读取，避免修改 data.json 后需重启服务才能生效
        return self._load_data().get("headers", {})

    def set_data(self, key, value, comment=""):
        self.data["datas"][key] = value
        if comment:
            self.data["datas"][f"_{key}_comment"] = comment
        self._save_data()
        print(f"CacheService.set_data: key={key}, value={value}, file={self.cache_file}")
        print(f"当前 datas: {self.data['datas']}")

    def get_data(self, key):
        # 每次从文件实时读取
        return self._load_data()["datas"].get(key)

    def delete_data(self, key):
        if key in self.data["datas"]:
            del self.data["datas"][key]
            comment_key = f"_{key}_comment"
            if comment_key in self.data["datas"]:
                del self.data["datas"][comment_key]
            self._save_data()

    def clear_datas(self):
        self.data["datas"] = {}
        self._save_data()

    def set_header(self, key, value):
        self.data["headers"][key] = value
        self._save_data()

    def get_header(self, key):
        # 每次从文件实时读取
        return self._load_data()["headers"].get(key)

    def update_cache(self, new_datas=None, new_headers=None):
        if new_datas:
            self.data["datas"].update(new_datas)
        if new_headers:
            self.data["headers"].update(new_headers)
        self._save_data()