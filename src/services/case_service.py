from ..models.case_model import CaseModel


class CaseService:
    def __init__(self, case_model):
        self.case_model = case_model

    def get_all_cases(self):
        return self.case_model.get_all()

    def get_case_by_id(self, case_id):
        return self.case_model.get_by_id(case_id)

    def get_cases_by_module(self, module_id):
        return self.case_model.get_by_module(module_id)

    def create_case(self, case_data):
        return self.case_model.create(case_data)

    def update_case(self, case_id, case_data):
        return self.case_model.update(case_id, case_data)

    def delete_case(self, case_id):
        self.case_model.delete(case_id)