# coding=utf-8
"""
宝信项目 - 全局配置文件
支持多环境切换（测试/预发布/开发），环境配置持久化到 data/env_config.json
"""
import json, os

# ========== 项目目录 ==========
path = "/Users/cengqi/Desktop/study/baoxinApiTest"

# 环境配置文件路径
ENV_CONFIG_FILE = os.path.join(path, 'data', 'env_config.json')

# 默认环境配置
DEFAULT_ENV_CONFIGS = {
    "test": {
        "name": "测试环境",
        "host": "http://test-baoxin.example.com",
        "desc": "测试环境 - 用于日常测试"
    },
    "pre": {
        "name": "预发布环境",
        "host": "http://pre-baoxin.example.com",
        "desc": "预发布环境 - 用于上线前验证"
    },
    "dev": {
        "name": "开发环境",
        "host": "http://dev-baoxin.example.com",
        "desc": "开发环境 - 用于开发联调"
    }
}


def _load_env_config():
    """从 JSON 文件加载环境配置，不存在则使用默认配置并创建文件"""
    if os.path.exists(ENV_CONFIG_FILE):
        try:
            with open(ENV_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "envs" in data and "current" in data:
                    return data["envs"], data["current"]
        except (json.JSONDecodeError, IOError):
            pass

    # 首次使用：创建默认配置文件
    data = {"current": "test", "envs": DEFAULT_ENV_CONFIGS}
    _save_env_config(data["envs"], data["current"])
    return data["envs"], data["current"]


def _save_env_config(envs, current):
    """保存环境配置到 JSON 文件"""
    os.makedirs(os.path.dirname(ENV_CONFIG_FILE), exist_ok=True)
    with open(ENV_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump({"current": current, "envs": envs}, f, ensure_ascii=False, indent=2)


# 加载环境配置
ENV_CONFIGS, current_env = _load_env_config()


def get_current_env():
    return current_env


def get_host():
    return ENV_CONFIGS[current_env]["host"]


def get_env_name():
    return ENV_CONFIGS[current_env]["name"]


def get_env_desc():
    return ENV_CONFIGS[current_env]["desc"]


def switch_env(env_key):
    """切换当前环境，并持久化到文件"""
    global current_env
    if env_key in ENV_CONFIGS:
        current_env = env_key
        _save_env_config(ENV_CONFIGS, current_env)
        return True
    return False


def add_env(env_key, config):
    """新增环境，并持久化到文件"""
    ENV_CONFIGS[env_key] = config
    _save_env_config(ENV_CONFIGS, current_env)
    return True


def update_env(env_key, config):
    """更新环境配置，并持久化到文件"""
    if env_key in ENV_CONFIGS:
        ENV_CONFIGS[env_key].update(config)
        _save_env_config(ENV_CONFIGS, current_env)
        return True
    return False


def delete_env(env_key):
    """删除环境，并持久化到文件"""
    global current_env
    if env_key in ENV_CONFIGS:
        del ENV_CONFIGS[env_key]
        # 如果删除的是当前环境，切回第一个可用环境
        if current_env == env_key and ENV_CONFIGS:
            current_env = list(ENV_CONFIGS.keys())[0]
        _save_env_config(ENV_CONFIGS, current_env)
        return True
    return False


host = get_host()
evn = get_current_env()


# ========== 业务基础数据 ==========
# 签约平台/企业主体名称
orgName = "宝信集团股份有限公司"

# 部组名称
buzuName = "宝信-业务一部"

# 供应商名称
gysName = "供应商A有限公司"

# 客户名称
khName = "客户B有限公司"

# 业务员名称
ywName = "测试员"

# OA账号
oaName = "testuser"

# 拟定审核人
ndName = "测试员"

# 品名列表
brandName = ["品名1", "品名2"]

# ========== 业务字典配置 ==========
# 业务类型
ywlxName = "业务类型A"

# 业务形式
ywxsName = "自营"

# 签约标记
qybjName = "合同签约"

# 合同签约文件
htqyName = "全部主要责任风险"

# 合同类型
htlxName = "内贸"

# 采购合同类型
cghtlxName = "内贸采购"

# 交货方式
jhName = "过户"

# 购销类型
gxlxName = "统购分销"

# 运输方式
ysfsName = "公路运输"

# ========== 字典类型映射 ==========
# 新增合同时下拉框取id，根据实际项目的字典类型编码修改
basicType = {
    "购销类型": "BX_PURCHASE_SALE_TYPE",
    "溢短控制类型": "BX_GAP_TYPE",
    "产品组": "BX_PRODUCT_GROUP",
    "业务分类": "BX_BUSINESS_TYPE",
    "业务形式": "BX_BUSINESS_FORM",
    "签约标记": "BX_SIGN_LABEL",
    "合同签约文件": "BX_SIGN_FILE",
    "提货方式": "BX_DELIVERY_TYPE",
    "盈利模式": "BX_PROFIT_MODEL",
    "合同类型": "BX_CONTRACT_TYPE",
    "结算方式": "BX_SETTLEMENT",
    "对账类别": "BX_CHECK_AMOUNT_TYPE",
    "应收标志": "BX_RECEIVE_MARK",
    "定价方式": "BX_PRICING_TYPE",
    "套保类型": "BX_HEDGE_TYPE",
    "质保金账期类型": "BX_QUALITY_MONEY_PAYMENT_TYPE",
    "赊销天数单位": "BX_CREDIT_SELL_DAY_UNIT",
    "付款条款": "1",
    "自营模式": "BX_PROPRIETARY_MODEL",
    "发票类型": "INVOICES_TYPE",
    "发票-付款条件": "INVOICE_CHECK",
    "定价周期": "BX_PRICING_PERIOD"
}
