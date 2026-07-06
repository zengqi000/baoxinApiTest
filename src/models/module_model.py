import uuid
from datetime import datetime
from .base import BaseModel


class ModuleModel(BaseModel):
    def _get_default_data(self):
        return {"modules": []}

    def get_all(self):
        return self.data.get("modules", [])

    def get_by_id(self, module_id):
        modules = self.get_all()
        return next((m for m in modules if m.get("id") == module_id), None)

    def get_by_name(self, name):
        modules = self.get_all()
        return next((m for m in modules if m.get("name") == name), None)

    def create(self, module_data):
        module_id = str(uuid.uuid4())[:8]
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        module = {
            "id": module_id,
            "name": module_data.get("name", ""),
            "description": module_data.get("description", ""),
            "createdAt": now,
            "updatedAt": now
        }
        self.data["modules"].append(module)
        self._save_data()
        return module

    def update(self, module_id, module_data):
        modules = self.data["modules"]
        for i, module in enumerate(modules):
            if module["id"] == module_id:
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                modules[i].update(module_data)
                modules[i]["updatedAt"] = now
                self._save_data()
                return modules[i]
        return None

    def delete(self, module_id):
        modules = self.data["modules"]
        self.data["modules"] = [m for m in modules if m.get("id") != module_id]
        self._save_data()