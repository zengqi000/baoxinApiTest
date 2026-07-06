import json
import os
from abc import ABC, abstractmethod


class BaseModel(ABC):
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = self._load_data()

    def _load_data(self):
        if not os.path.exists(self.file_path):
            return self._get_default_data()
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return self._get_default_data()

    def _save_data(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    @abstractmethod
    def _get_default_data(self):
        pass

    @abstractmethod
    def get_all(self):
        pass

    @abstractmethod
    def get_by_id(self, item_id):
        pass

    @abstractmethod
    def create(self, item_data):
        pass

    @abstractmethod
    def update(self, item_id, item_data):
        pass

    @abstractmethod
    def delete(self, item_id):
        pass