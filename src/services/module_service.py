from ..models.module_model import ModuleModel


class ModuleService:
    def __init__(self, module_model):
        self.module_model = module_model

    def get_all_modules(self):
        return self.module_model.get_all()

    def get_module_by_id(self, module_id):
        return self.module_model.get_by_id(module_id)

    def get_module_by_name(self, name):
        return self.module_model.get_by_name(name)

    def create_module(self, module_data):
        return self.module_model.create(module_data)

    def update_module(self, module_id, module_data):
        return self.module_model.update(module_id, module_data)

    def delete_module(self, module_id):
        self.module_model.delete(module_id)