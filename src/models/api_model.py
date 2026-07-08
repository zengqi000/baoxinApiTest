import uuid
from datetime import datetime
from .base import BaseModel


class ApiModel(BaseModel):
    def _get_default_data(self):
        return {"apis": []}

    def get_all(self):
        apis = self.data.get("apis", [])
        return sorted(apis, key=lambda a: a.get("createdAt", ""), reverse=True)

    def get_by_id(self, api_id):
        apis = self.data.get("apis", [])
        return next((a for a in apis if a.get("id") == api_id), None)

    def get_by_module(self, module_id):
        apis = self.data.get("apis", [])
        filtered = [a for a in apis if a.get("moduleId") == module_id]
        return sorted(filtered, key=lambda a: a.get("createdAt", ""), reverse=True)

    def create(self, api_data):
        api_id = str(uuid.uuid4())[:8]
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        api = {
            "id": api_id,
            "name": api_data.get("name", ""),
            "funcName": api_data.get("funcName", ""),
            "url": api_data.get("url", ""),
            "method": api_data.get("method", "POST"),
            "moduleId": api_data.get("moduleId", ""),
            "moduleName": api_data.get("moduleName", ""),
            "preApiId": api_data.get("preApiId", ""),
            "preApiVariables": api_data.get("preApiVariables", {}),
            "headers": api_data.get("headers", {}),
            "params": api_data.get("params", {}),
            "body": api_data.get("body", {}),
            "responseMapping": api_data.get("responseMapping", []),
            "paramBinding": api_data.get("paramBinding", []),
            "assertions": api_data.get("assertions", []),
            "script": api_data.get("script", ""),
            "variables": api_data.get("variables", ""),
            "createdAt": now,
            "updatedAt": now
        }
        self.data["apis"].append(api)
        self._save_data()
        return api

    def update(self, api_id, api_data):
        apis = self.data["apis"]
        for i, api in enumerate(apis):
            if api["id"] == api_id:
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                apis[i].update(api_data)
                apis[i]["updatedAt"] = now
                self._save_data()
                return apis[i]
        return None

    def delete(self, api_id):
        apis = self.data["apis"]
        self.data["apis"] = [a for a in apis if a.get("id") != api_id]
        self._save_data()

    def get_func_names(self):
        return [a.get("funcName", "") for a in self.get_all()]

    def check_func_name_unique(self, func_name, exclude_id=None):
        func_names = self.get_func_names()
        if exclude_id:
            api = self.get_by_id(exclude_id)
            if api and api.get("funcName") == func_name:
                return True
        return func_name not in func_names