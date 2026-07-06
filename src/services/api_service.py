import json
import re
from datetime import datetime
from ..models.api_model import ApiModel


class ApiService:
    def __init__(self, api_model):
        self.api_model = api_model

    def to_python_func(self, name):
        verb_mapping = {
            "新增": "add", "添加": "add", "创建": "create",
            "删除": "delete", "移除": "remove",
            "修改": "update", "编辑": "edit", "更新": "update",
            "查询": "query", "获取": "get", "列表": "list", "搜索": "search",
            "登录": "login", "登出": "logout", "认证": "auth",
            "保存": "save", "提交": "submit", "审核": "audit",
            "确认": "confirm", "取消": "cancel", "关闭": "close",
            "开启": "open", "启动": "start", "停止": "stop",
            "上传": "upload", "下载": "download", "导入": "import",
            "导出": "export", "同步": "sync", "刷新": "refresh"
        }
        noun_mapping = {
            "合同": "Contract", "订单": "Order", "提单": "Bill",
            "报价": "Quote", "询价": "Inquiry", "采购": "Purchase",
            "销售": "Sales", "库存": "Inventory", "仓库": "Warehouse",
            "客户": "Customer", "供应商": "Supplier", "用户": "User",
            "权限": "Permission", "角色": "Role", "部门": "Dept",
            "组织": "Org", "员工": "Staff", "业务": "Business",
            "产品": "Product", "商品": "Goods", "服务": "Service",
            "配置": "Config", "参数": "Param", "设置": "Setting",
            "数据": "Data", "信息": "Info", "详情": "Detail",
            "列表": "List", "查询": "Query", "统计": "Stats",
            "平台": "Platform", "系统": "System", "接口": "Api",
            "项目": "Project", "任务": "Task", "工单": "WorkOrder",
            "审批": "Approval", "流程": "Process", "日志": "Log",
            "记录": "Record", "历史": "History", "版本": "Version",
            "分类": "Class", "类型": "Type", "状态": "Status",
            "编码": "Code", "名称": "Name", "标识": "Id",
            "金额": "Amount", "数量": "Quantity", "价格": "Price",
            "日期": "Date", "时间": "Time", "期限": "Period",
            "协议": "Agreement", "条款": "Clause", "备注": "Remark",
            "附件": "Attachment", "文件": "File", "图片": "Image",
            "标签": "Tag", "标记": "Mark", "分组": "Group",
            "区域": "Area", "地址": "Address", "位置": "Location",
            "联系人": "Contact", "电话": "Phone", "邮箱": "Email",
            "账号": "Account", "密码": "Password", "验证码": "Captcha",
            "Token": "Token", "票据": "Receipt", "发票": "Invoice",
            "结算": "Settlement", "支付": "Payment", "收款": "Receipt",
            "退款": "Refund", "转账": "Transfer", "对账": "Reconciliation",
            "通知": "Notification", "消息": "Message", "提醒": "Reminder",
            "告警": "Alarm", "预警": "Warning", "错误": "Error",
            "异常": "Exception", "故障": "Fault", "修复": "Fix"
        }

        verb = "get"
        noun = ""
        
        for v, target in verb_mapping.items():
            if v in name:
                verb = target
                break
        
        for n, target in noun_mapping.items():
            if n in name:
                noun += target
        
        if not noun:
            cleaned = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', name)
            if len(cleaned) > 0:
                noun = ''.join(chr(ord(c) + 65248) if 'a' <= c <= 'z' or 'A' <= c <= 'Z' else c for c in cleaned[:6])
        
        func_name = f"{verb}{noun}"
        return func_name

    def generate_unique_func_name(self, name, exclude_id=None):
        base_name = self.to_python_func(name)
        if not base_name:
            base_name = "api"
        
        if self.api_model.check_func_name_unique(base_name, exclude_id):
            return base_name
        
        counter = 2
        while True:
            new_name = f"{base_name}{counter}"
            if self.api_model.check_func_name_unique(new_name, exclude_id):
                return new_name
            counter += 1

    def create_api(self, api_data):
        if not api_data.get("funcName") or api_data["funcName"].strip() == "":
            api_data["funcName"] = self.generate_unique_func_name(api_data.get("name", ""))
        return self.api_model.create(api_data)

    def update_api(self, api_id, api_data):
        if "funcName" not in api_data or api_data.get("funcName") == "":
            api = self.api_model.get_by_id(api_id)
            if api and api.get("name"):
                api_data["funcName"] = self.generate_unique_func_name(api["name"], api_id)
        return self.api_model.update(api_id, api_data)

    def get_all_apis(self):
        return self.api_model.get_all()

    def get_api_by_id(self, api_id):
        return self.api_model.get_by_id(api_id)

    def get_apis_by_module(self, module_id):
        return self.api_model.get_by_module(module_id)

    def delete_api(self, api_id):
        self.api_model.delete(api_id)