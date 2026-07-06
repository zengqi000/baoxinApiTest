import uuid
from datetime import datetime
from .base import BaseModel


class CaseModel(BaseModel):
    def _get_default_data(self):
        return {"cases": []}

    def get_all(self):
        return self.data.get("cases", [])

    def get_by_id(self, case_id):
        cases = self.get_all()
        return next((c for c in cases if c.get("id") == case_id), None)

    def get_by_module(self, module_id):
        cases = self.get_all()
        return [c for c in cases if c.get("moduleId") == module_id]

    def create(self, case_data):
        case_id = str(uuid.uuid4())[:8]
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        case = {
            "id": case_id,
            "name": case_data.get("name", ""),
            "description": case_data.get("description", ""),
            "moduleId": case_data.get("moduleId", ""),
            "moduleName": case_data.get("moduleName", ""),
            "steps": case_data.get("steps", []),
            "createdAt": now,
            "updatedAt": now
        }
        self.data["cases"].append(case)
        self._save_data()
        return case

    def update(self, case_id, case_data):
        cases = self.data["cases"]
        for i, case in enumerate(cases):
            if case["id"] == case_id:
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                cases[i].update(case_data)
                cases[i]["updatedAt"] = now
                self._save_data()
                return cases[i]
        return None

    def delete(self, case_id):
        cases = self.data["cases"]
        self.data["cases"] = [c for c in cases if c.get("id") != case_id]
        self._save_data()