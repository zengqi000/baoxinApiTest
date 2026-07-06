import re
import json
from ..models.config_model import ConfigModel
from ..models.api_model import ApiModel


class ConfigService:
    def __init__(self, config_model, api_model):
        self.config_model = config_model
        self.api_model = api_model

    def get_all_configs(self):
        return self.config_model.get_all()

    def get_config_by_id(self, config_id):
        return self.config_model.get_by_id(config_id)

    def get_config_by_name(self, name):
        return self.config_model.get_by_name(name)

    def create_config(self, config_data):
        return self.config_model.create(config_data)

    def update_config(self, config_id, config_data):
        return self.config_model.update(config_id, config_data)

    def delete_config(self, config_id):
        self.config_model.delete(config_id)

    def reset_all_referenced(self):
        self.config_model.reset_all_referenced()

    def check_config_references(self):
        apis = self.api_model.get_all()
        configs = self.config_model.get_all()

        for config in configs:
            config["referenced"] = False

        for api in apis:
            content = json.dumps(api, ensure_ascii=False)
            
            for config in configs:
                placeholder = f"{{{{{config['name']}}}}}"
                if placeholder in content:
                    config["referenced"] = True

        self.config_model._save_data()

    def get_config_value(self, name):
        config = self.config_model.get_by_name(name)
        return config.get("value", "") if config else ""