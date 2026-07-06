import uuid
from datetime import datetime
from .base import BaseModel


class ConfigModel(BaseModel):
    def _get_default_data(self):
        return {"configs": []}

    def get_all(self):
        return self.data.get("configs", [])

    def get_by_id(self, config_id):
        configs = self.get_all()
        return next((c for c in configs if c.get("id") == config_id), None)

    def get_by_name(self, name):
        configs = self.get_all()
        return next((c for c in configs if c.get("name") == name), None)

    def create(self, config_data):
        config_id = str(uuid.uuid4())[:8]
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        config = {
            "id": config_id,
            "name": config_data.get("name", ""),
            "value": config_data.get("value", ""),
            "referenced": config_data.get("referenced", False),
            "createdAt": now,
            "updatedAt": now
        }
        self.data["configs"].append(config)
        self._save_data()
        return config

    def update(self, config_id, config_data):
        configs = self.data["configs"]
        for i, config in enumerate(configs):
            if config["id"] == config_id:
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                configs[i].update(config_data)
                configs[i]["updatedAt"] = now
                self._save_data()
                return configs[i]
        return None

    def delete(self, config_id):
        configs = self.data["configs"]
        self.data["configs"] = [c for c in configs if c.get("id") != config_id]
        self._save_data()

    def reset_all_referenced(self):
        configs = self.data["configs"]
        for config in configs:
            config["referenced"] = False
        self._save_data()

    def set_referenced(self, name, value):
        configs = self.data["configs"]
        for config in configs:
            if config["name"] == name:
                config["referenced"] = value
                self._save_data()
                return True
        return False