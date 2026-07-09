# coding=utf-8
"""
宝信 API 测试管理平台 - Flask 应用
统一入口：Web管理界面 + 测试执行 + 代码生成 + 数据流转(data.json缓存)
项目结构：
  app.py          ← Flask应用入口
  src/
    models/       ← 数据访问层（ORM-like模型）
    services/     ← 业务逻辑层
    routes/       ← 路由层（蓝图）
    utils/        ← 工具函数层
  configs/        ← 配置层（认证、参数、data.json缓存）
  templates/      ← 前端页面（Flask模板）
  static/         ← 静态资源
  data/           ← 平台运行数据（模块、接口、结果JSON）
  reports/        ← 测试报告输出
  logs/           ← 日志文件
"""
import json
import os
import subprocess
import time
import uuid
import csv
import collections
from datetime import datetime
import logging

from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
from src.utils.logging_utils import setup_logger

app = Flask(__name__, static_folder='static', template_folder='templates')

logger = setup_logger('api_test')

_log_buffer = collections.deque(maxlen=500)
_log_listeners = []


class RealtimeLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            _log_buffer.append(msg)
            for q in list(_log_listeners):
                try:
                    q.append(msg)
                except Exception:
                    pass
        except Exception:
            pass


_realtime_handler = RealtimeLogHandler()
_realtime_handler.setLevel(logging.INFO)
_realtime_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
    datefmt='%H:%M:%S'
))
logger.addHandler(_realtime_handler)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, 'data')
MODULES_FILE = os.path.join(DATA_DIR, 'modules.json')
APIS_FILE = os.path.join(DATA_DIR, 'apis.json')
RESULTS_FILE = os.path.join(DATA_DIR, 'test_results.json')
TEST_CASES_FILE = os.path.join(DATA_DIR, 'test_cases.json')
CASE_MODULES_FILE = os.path.join(DATA_DIR, 'case_modules.json')
PROJECT_DATA_FILE = os.path.join(BASE_DIR, 'configs', 'data.json')
CONFIGS_FILE = os.path.join(BASE_DIR, 'configs', 'configs.json')
TEST_REPORTS_FILE = os.path.join(DATA_DIR, 'test_reports.json')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'configs'), exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)


def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_value_by_path(obj, path):
    path = path.strip()
    if path.startswith('res['):
        path = path[4:-1].replace(']["', '.').replace('"]', '').replace('["', '')
    parts = path.replace('[', '.').replace(']', '').split('.')
    current = obj
    for part in parts:
        if part == '':
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx] if idx < len(current) else None
            except ValueError:
                current = None
        else:
            return None
        if current is None:
            return None
    return current


def set_value_by_path(obj, path, value):
    path = path.strip()
    if path.startswith('res['):
        path = path[4:-1].replace(']["', '.').replace('"]', '').replace('["', '')
    parts = path.replace('[', '.').replace(']', '').split('.')
    current = obj
    for i, part in enumerate(parts):
        if part == '':
            continue
        if isinstance(current, dict):
            if i == len(parts) - 1:
                current[part] = value
                return
            if part not in current:
                current[part] = {} if parts[i + 1].isdigit() else {}
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
                if idx >= len(current):
                    current.extend([None] * (idx - len(current) + 1))
                if i == len(parts) - 1:
                    current[idx] = value
                    return
                if current[idx] is None:
                    current[idx] = {}
                current = current[idx]
            except ValueError:
                return
        else:
            return


def generate_test_report(report_id, results):
    report_file = os.path.join(REPORTS_DIR, f'test_report_{report_id}.csv')
    try:
        with open(report_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['接口名称', '接口ID', '状态', '状态码', '错误信息', '执行时间'])
            
            for result in results:
                writer.writerow([
                    result.get('apiName', ''),
                    result.get('apiId', ''),
                    result.get('status', ''),
                    result.get('statusCode', ''),
                    result.get('message', ''),
                    result.get('timestamp', '')
                ])
        
        logger.info(f"测试报告生成成功: {report_file}")
        return report_file
    except Exception as e:
        logger.error(f"测试报告生成失败: {str(e)}")
        return None


def generate_html_report(report_id, results):
    report_file = os.path.join(REPORTS_DIR, f'test_report_{report_id}.html')
    success_count = sum(1 for r in results if r.get('status') == 'success')
    error_count = len(results) - success_count
    pass_rate = round(success_count / len(results) * 100, 2) if results else 0
    
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API测试报告 - {report_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; padding: 20px; }}
        .report {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 24px 32px; }}
        .header h1 {{ font-size: 24px; font-weight: 600; }}
        .header p {{ margin-top: 8px; opacity: 0.9; }}
        .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; padding: 24px 32px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }}
        .stat {{ background: white; padding: 16px; border-radius: 8px; text-align: center; }}
        .stat .label {{ font-size: 12px; color: #64748b; margin-bottom: 4px; }}
        .stat .value {{ font-size: 24px; font-weight: 700; }}
        .stat.success .value {{ color: #22c55e; }}
        .stat.error .value {{ color: #ef4444; }}
        .stat.total .value {{ color: #6366f1; }}
        .stat.rate .value {{ color: #f59e0b; }}
        .chart {{ padding: 24px 32px; }}
        .chart-title {{ font-size: 16px; font-weight: 600; color: #1e293b; margin-bottom: 16px; }}
        .pie-chart {{ width: 200px; height: 200px; border-radius: 50%; background: conic-gradient(#22c55e {pass_rate}%, #ef4444 {pass_rate}%); position: relative; margin: 0 auto; }}
        .pie-center {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; width: 120px; height: 120px; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
        .pie-center .percent {{ font-size: 28px; font-weight: 700; color: #1e293b; }}
        .pie-center .text {{ font-size: 12px; color: #64748b; }}
        .legend {{ display: flex; justify-content: center; gap: 32px; margin-top: 24px; }}
        .legend-item {{ display: flex; align-items: center; gap: 8px; }}
        .legend-color {{ width: 16px; height: 16px; border-radius: 4px; }}
        .legend-color.success {{ background: #22c55e; }}
        .legend-color.error {{ background: #ef4444; }}
        .results {{ padding: 24px 32px; }}
        .results-title {{ font-size: 16px; font-weight: 600; color: #1e293b; margin-bottom: 16px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
        th {{ background: #f8fafc; font-weight: 600; color: #64748b; font-size: 13px; }}
        td {{ font-size: 14px; color: #334155; }}
        .status.success {{ color: #22c55e; font-weight: 500; }}
        .status.error {{ color: #ef4444; font-weight: 500; }}
        .footer {{ padding: 16px 32px; background: #f8fafc; text-align: center; font-size: 12px; color: #94a3b8; }}
    </style>
</head>
<body>
    <div class="report">
        <div class="header">
            <h1>API测试报告</h1>
            <p>报告ID: {report_id} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        <div class="stats">
            <div class="stat total">
                <div class="label">总接口数</div>
                <div class="value">{len(results)}</div>
            </div>
            <div class="stat success">
                <div class="label">成功</div>
                <div class="value">{success_count}</div>
            </div>
            <div class="stat error">
                <div class="label">失败</div>
                <div class="value">{error_count}</div>
            </div>
            <div class="stat rate">
                <div class="label">通过率</div>
                <div class="value">{pass_rate}%</div>
            </div>
        </div>
        <div class="chart">
            <div class="chart-title">执行结果统计</div>
            <div class="pie-chart">
                <div class="pie-center">
                    <div class="percent">{pass_rate}%</div>
                    <div class="text">通过率</div>
                </div>
            </div>
            <div class="legend">
                <div class="legend-item">
                    <div class="legend-color success"></div>
                    <span>成功 ({success_count})</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color error"></div>
                    <span>失败 ({error_count})</span>
                </div>
            </div>
        </div>
        <div class="results">
            <div class="results-title">详细执行结果</div>
            <table>
                <thead>
                    <tr>
                        <th>接口名称</th>
                        <th>接口ID</th>
                        <th>状态</th>
                        <th>状态码</th>
                        <th>错误信息</th>
                        <th>执行时间</th>
                    </tr>
                </thead>
                <tbody>
"""
    
    for result in results:
        status_class = 'success' if result.get('status') == 'success' else 'error'
        status_text = '成功' if result.get('status') == 'success' else '失败'
        html_content += f"""
                    <tr>
                        <td>{result.get('apiName', '')}</td>
                        <td>{result.get('apiId', '')}</td>
                        <td class="status {status_class}">{status_text}</td>
                        <td>{result.get('statusCode', '')}</td>
                        <td>{result.get('message', '')}</td>
                        <td>{result.get('timestamp', '')}</td>
                    </tr>
"""
    
    html_content += """
                </tbody>
            </table>
        </div>
        <div class="footer">
            宝信API测试管理平台 - 自动生成
        </div>
    </div>
</body>
</html>
"""
    
    try:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"HTML测试报告生成成功: {report_file}")
        return report_file
    except Exception as e:
        logger.error(f"HTML测试报告生成失败: {str(e)}")
        return None


from src.models.api_model import ApiModel
from src.models.config_model import ConfigModel
from src.models.module_model import ModuleModel
from src.models.case_model import CaseModel
from src.services.api_service import ApiService
from src.services.config_service import ConfigService
from src.services.module_service import ModuleService
from src.services.cache_service import CacheService
from src.services.test_service import TestService
from src.services.case_service import CaseService

api_model = ApiModel(APIS_FILE)
config_model = ConfigModel(CONFIGS_FILE)
module_model = ModuleModel(MODULES_FILE)
case_model = CaseModel(TEST_CASES_FILE)
cache_service = CacheService(PROJECT_DATA_FILE)

api_service = ApiService(api_model)
config_service = ConfigService(config_model, api_model)
module_service = ModuleService(module_model)
case_service = CaseService(case_model)
test_service = TestService(api_model, config_model, cache_service)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/cases')
def cases():
    return render_template('cases.html')


@app.route('/api/apis/run-module/<module_id>', methods=['POST'])
def run_module_apis(module_id):
    logger.info(f"开始执行模块接口: {module_id}")
    
    config_service.reset_all_referenced()
    cache_service.clear_datas()
    
    apis = api_model.get_all()
    apis = [api for api in apis if api.get("moduleId") == module_id]
    
    results = []
    success_count = 0
    error_count = 0
    
    for api in apis:
        try:
            result = test_service.test_api(api["id"])
            if result["status"] == "success":
                success_count += 1
                logger.info(f"接口执行成功: {api['name']}")
            else:
                error_count += 1
                logger.error(f"接口执行失败: {api['name']} - {result.get('message', '')}")
            
            results.append({
                "apiId": api["id"],
                "apiName": api["name"],
                "status": result["status"],
                "statusCode": result.get("statusCode", 0),
                "message": result.get("message", ""),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        except Exception as e:
            error_count += 1
            logger.error(f"接口执行异常: {api['name']} - {str(e)}")
            results.append({
                "apiId": api["id"],
                "apiName": api["name"],
                "status": "error",
                "statusCode": 0,
                "message": str(e),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    
    config_service.check_config_references()
    
    logger.info(f"模块执行完成: 成功 {success_count} 个, 失败 {error_count} 个")
    
    return jsonify({
        "success": True,
        "results": results,
        "successCount": success_count,
        "errorCount": error_count
    })


@app.route('/api/run-all', methods=['POST'])
def run_all_apis():
    logger.info("开始一键执行所有接口")
    
    config_service.reset_all_referenced()
    cache_service.clear_datas()
    
    apis = api_model.get_all()
    results = []
    success_count = 0
    error_count = 0
    
    for api in apis:
        try:
            result = test_service.test_api(api["id"])
            if result["status"] == "success":
                success_count += 1
                logger.info(f"接口执行成功: {api['name']}")
            else:
                error_count += 1
                logger.error(f"接口执行失败: {api['name']} - {result.get('message', '')}")
            
            results.append({
                "apiId": api["id"],
                "apiName": api["name"],
                "status": result["status"],
                "statusCode": result.get("statusCode", 0),
                "message": result.get("message", ""),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        except Exception as e:
            error_count += 1
            logger.error(f"接口执行异常: {api['name']} - {str(e)}")
            results.append({
                "apiId": api["id"],
                "apiName": api["name"],
                "status": "error",
                "statusCode": 0,
                "message": str(e),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    
    config_service.check_config_references()
    
    report_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    generate_test_report(report_id, results)
    generate_html_report(report_id, results)
    
    reports_data = load_json(TEST_REPORTS_FILE)
    if "reports" not in reports_data:
        reports_data["reports"] = []
    reports_data["reports"].append({
        "id": report_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "success": success_count,
        "error": error_count,
        "status": "completed"
    })
    save_json(TEST_REPORTS_FILE, reports_data)
    
    logger.info(f"一键执行完成: 成功 {success_count} 个, 失败 {error_count} 个")
    
    return jsonify({
        "success": True,
        "results": results,
        "successCount": success_count,
        "errorCount": error_count
    })


@app.route('/api/test/<api_id>', methods=['POST'])
def test_single_api(api_id):
    logger.info(f"开始测试接口: {api_id}")
    result = test_service.test_api(api_id, write_cache=False)
    
    if result["status"] == "success":
        logger.info(f"接口测试成功: {api_id}")
    else:
        logger.error(f"接口测试失败: {api_id} - {result.get('message', '')}")
    
    return jsonify(result)


@app.route('/api/apis/<api_id>/test', methods=['POST'])
def test_api_by_id(api_id):
    data = request.get_json()
    variables = data.get('variables', {}) if data else {}
    pre_api_variables = data.get('preApiVariables', {}) if data else {}
    
    result = test_service.test_api(api_id, variables, write_cache=False, pre_api_variables=pre_api_variables)
    
    if result["status"] == "success":
        logger.info(f"接口测试成功: {api_id}")
    else:
        logger.error(f"接口测试失败: {api_id} - {result.get('message', '')}")
    
    api = api_model.get_by_id(api_id)
    url = api["url"] if api else ""
    if url.startswith('/'):
        url = env_config.get_host() + url
    
    return jsonify({
        "success": True,
        "status": result["status"],
        "statusCode": result.get("statusCode", 0),
        "responseTime": result.get("responseTime", 0),
        "method": api.get("method", "POST") if api else "POST",
        "url": url,
        "requestHeaders": result.get("requestHeaders", {}),
        "requestParams": result.get("requestParams", {}),
        "requestBody": result.get("requestBody", {}),
        "response": result.get("response", {}),
        "message": result.get("message", ""),
        "msg": result.get("message", ""),
        "logs": result.get("logs", []),
        "assertionResults": result.get("assertions", []),
        "allAssertionsPass": all(a.get("passed", True) for a in result.get("assertions", [])),
        "savingLog": result.get("savingLog", []),
        "bindingLog": result.get("bindingLog", []),
        "preApiResult": result.get("preApiResult", None)
    })


@app.route('/api/apis', methods=['GET'])
def get_all_apis():
    module_id = request.args.get('moduleId')
    if module_id:
        apis = api_model.get_by_module(module_id)
    else:
        apis = api_model.get_all()
    
    modules = {m['id']: m['name'] for m in module_model.get_all()}
    for api in apis:
        api['moduleName'] = modules.get(api.get('moduleId'), '')
    
    return jsonify({"success": True, "apis": apis})


@app.route('/api/apis/<api_id>', methods=['GET'])
def get_api(api_id):
    api = api_model.get_by_id(api_id)
    if api:
        modules = {m['id']: m['name'] for m in module_model.get_all()}
        api['moduleName'] = modules.get(api.get('moduleId'), '')
        return jsonify({"success": True, "api": api})
    return jsonify({"success": False, "message": "接口不存在"}), 404


@app.route('/api/apis', methods=['POST'])
def create_api():
    data = request.get_json()
    try:
        api = api_service.create_api(data)
        logger.info(f"创建接口成功: {api['name']}")
        return jsonify({"success": True, "api": api})
    except Exception as e:
        logger.error(f"创建接口失败: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/apis/<api_id>', methods=['PUT'])
def update_api(api_id):
    data = request.get_json()
    api = api_service.update_api(api_id, data)
    if api:
        logger.info(f"更新接口成功: {api['name']}")
        return jsonify({"success": True, "api": api})
    return jsonify({"success": False, "message": "接口不存在"}), 404


@app.route('/api/apis/<api_id>', methods=['DELETE'])
def delete_api(api_id):
    api_model.delete(api_id)
    logger.info(f"删除接口成功: {api_id}")
    return jsonify({"success": True})


@app.route('/api/modules', methods=['GET'])
def get_all_modules():
    modules = module_model.get_all()
    return jsonify({"success": True, "modules": modules})


@app.route('/api/modules', methods=['POST'])
def create_module():
    data = request.get_json()
    module = module_model.create(data)
    logger.info(f"创建模块成功: {module['name']}")
    return jsonify({"success": True, "module": module})


@app.route('/api/modules/<module_id>', methods=['PUT'])
def update_module(module_id):
    data = request.get_json()
    module = module_model.update(module_id, data)
    if module:
        logger.info(f"更新模块成功: {module['name']}")
        return jsonify({"success": True, "module": module})
    return jsonify({"success": False, "message": "模块不存在"}), 404


@app.route('/api/modules/<module_id>', methods=['DELETE'])
def delete_module(module_id):
    module_model.delete(module_id)
    logger.info(f"删除模块成功: {module_id}")
    return jsonify({"success": True})


@app.route('/api/cases', methods=['GET'])
def get_all_cases():
    cases = case_service.get_all_cases()
    return jsonify({"success": True, "cases": cases})


@app.route('/api/cases/<case_id>', methods=['GET'])
def get_case_by_id(case_id):
    case = case_service.get_case_by_id(case_id)
    if case:
        return jsonify({"success": True, "case": case})
    return jsonify({"success": False, "message": "用例不存在"}), 404


@app.route('/api/cases', methods=['POST'])
def create_case():
    data = request.get_json()
    case = case_service.create_case(data)
    logger.info(f"创建用例成功: {case['id']}")
    return jsonify({"success": True, "case": case})


@app.route('/api/cases/<case_id>', methods=['PUT'])
def update_case(case_id):
    data = request.get_json()
    case = case_service.update_case(case_id, data)
    if case:
        logger.info(f"更新用例成功: {case_id}")
        return jsonify({"success": True, "case": case})
    return jsonify({"success": False, "message": "用例不存在"}), 404


@app.route('/api/cases/<case_id>', methods=['DELETE'])
def delete_case(case_id):
    case_service.delete_case(case_id)
    logger.info(f"删除用例成功: {case_id}")
    return jsonify({"success": True})


@app.route('/api/cases/<case_id>/run', methods=['POST'])
def run_case(case_id):
    logger.info(f"开始执行用例: {case_id}")
    
    result = test_service.run_case(case_id, case_model)
    
    if result["success"]:
        logger.info(f"用例执行成功: {case_id}")
    else:
        logger.error(f"用例执行失败: {case_id} - {result.get('message', '')}")
    
    return jsonify(result)


@app.route('/api/cases/<case_id>/run/stream', methods=['POST'])
def run_case_stream(case_id):
    logger.info(f"开始执行用例(流式): {case_id}")
    
    @stream_with_context
    def generate():
        case = case_model.get_by_id(case_id)
        if not case:
            yield f"data: {json.dumps({'type': 'error', 'message': '用例不存在'})}\n\n"
            return
        
        steps = case.get("steps", [])
        total_steps = len(steps)
        
        yield f"data: {json.dumps({'type': 'start', 'totalSteps': total_steps, 'caseName': case.get('name', '')})}\n\n"
        
        temp_vars = {}
        
        case_desc = case.get("description", "")
        if case_desc:
            try:
                desc_vars = json.loads(case_desc)
                if isinstance(desc_vars, dict):
                    configs_data = config_model.get_all()
                    cache_data = {
                        "datas": {**cache_service.get_datas(), **temp_vars},
                        "headers": cache_service.get_headers()
                    }
                    for key, value in desc_vars.items():
                        if isinstance(value, str):
                            value = test_service.resolve_placeholders(value, configs_data, cache_data)
                        temp_vars[key] = value
                    logger.info(f"解析临时变量: {temp_vars}")
            except json.JSONDecodeError:
                pass
        
        for idx, step in enumerate(steps):
            api_id = step.get("apiId")
            api_name = step.get("apiName", "")
            variables = step.get("variables", {})
            assertions = step.get("assertions", [])
            
            yield f"data: {json.dumps({'type': 'step_start', 'step': idx + 1, 'apiName': api_name, 'totalSteps': total_steps})}\n\n"
            
            try:
                result = test_service.test_api(api_id, variables, assertions, write_cache=False, temp_vars=temp_vars)
                
                for log in result.get("savingLog", []):
                    if log.get("value") is not None:
                        temp_vars[log["cacheKey"]] = log["value"]
                
                step_result = {
                    "step": idx + 1,
                    "apiId": api_id,
                    "apiName": api_name,
                    "status": result["status"],
                    "statusCode": result.get("statusCode", 0),
                    "message": result.get("message", ""),
                    "response": result.get("response", {}),
                    "responseTime": result.get("responseTime", 0),
                    "requestUrl": result.get("requestUrl", ""),
                    "requestMethod": result.get("requestMethod", "POST"),
                    "requestParams": result.get("requestParams", {}),
                    "requestBody": result.get("requestBody", {}),
                    "requestHeaders": result.get("requestHeaders", {}),
                    "assertionResults": result.get("assertions", []),
                    "allAssertionsPass": result.get("allAssertionsPass", True),
                    "savingLog": result.get("savingLog", []),
                    "bindingLog": result.get("bindingLog", [])
                }
                
                yield f"data: {json.dumps({'type': 'step_result', 'step': idx + 1, 'result': step_result})}\n\n"
                
            except Exception as e:
                step_result = {
                    "step": idx + 1,
                    "apiId": api_id,
                    "apiName": api_name,
                    "status": "error",
                    "statusCode": 0,
                    "message": str(e),
                    "response": {},
                    "requestUrl": "",
                    "requestMethod": "POST",
                    "requestParams": {},
                    "requestBody": {},
                    "requestHeaders": {},
                    "assertionResults": [],
                    "allAssertionsPass": True
                }
                
                yield f"data: {json.dumps({'type': 'step_result', 'step': idx + 1, 'result': step_result})}\n\n"
        
        yield f"data: {json.dumps({'type': 'end'})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/configs', methods=['GET'])
def get_all_configs():
    configs = config_model.get_all()
    return jsonify({"success": True, "configs": configs})


@app.route('/api/configs', methods=['POST'])
def create_config():
    data = request.get_json()
    config = config_model.create(data)
    logger.info(f"创建配置成功: {config['name']}")
    return jsonify({"success": True, "config": config})


@app.route('/api/configs/<config_id>', methods=['PUT'])
def update_config(config_id):
    data = request.get_json()
    config = config_model.update(config_id, data)
    if config:
        logger.info(f"更新配置成功: {config['name']}")
        return jsonify({"success": True, "config": config})
    return jsonify({"success": False, "message": "配置不存在"}), 404


@app.route('/api/configs/<config_id>', methods=['DELETE'])
def delete_config(config_id):
    config_model.delete(config_id)
    logger.info(f"删除配置成功: {config_id}")
    return jsonify({"success": True})


@app.route('/api/configs/check-references', methods=['POST'])
def check_references():
    config_service.check_config_references()
    return jsonify({"success": True})


@app.route('/api/configs/reset-references', methods=['POST'])
def reset_references():
    config_service.reset_all_referenced()
    return jsonify({"success": True})


@app.route('/api/cache', methods=['GET'])
def get_cache():
    cache_data = {
        "datas": cache_service.get_datas(),
        "headers": cache_service.get_headers()
    }
    return jsonify({"success": True, "data": cache_data})


@app.route('/api/cache', methods=['PUT'])
def update_cache():
    data = request.get_json()
    cache_service.update_cache(data.get("datas"), data.get("headers"))
    logger.info("缓存更新成功")
    return jsonify({"success": True})


@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    cache_service.clear_datas()
    logger.info("缓存清空成功")
    return jsonify({"success": True})


@app.route('/api/data-cache', methods=['GET'])
def get_data_cache():
    cache_data = {
        "datas": cache_service.get_datas(),
        "headers": cache_service.get_headers()
    }
    return jsonify({"success": True, "data": cache_data})


@app.route('/api/data-cache', methods=['PUT'])
def update_data_cache():
    data = request.get_json()
    cache_service.update_cache(data.get("datas"), data.get("headers"))
    logger.info("缓存更新成功")
    return jsonify({"success": True})


@app.route('/api/data-cache/refresh', methods=['POST'])
def refresh_data_cache():
    """强制刷新缓存，重新从文件读取data.json"""
    try:
        # 重新加载缓存数据
        cache_data = {
            "datas": cache_service.get_datas(),
            "headers": cache_service.get_headers()
        }
        logger.info("缓存刷新成功")
        return jsonify({"success": True, "data": cache_data})
    except Exception as e:
        logger.error(f"缓存刷新失败: {e}")
        return jsonify({"success": False, "message": str(e)})


@app.route('/api/data-cache/keys', methods=['GET'])
def get_cache_keys():
    datas = cache_service.get_datas()
    keys = list(datas.keys()) if datas else []
    return jsonify({"success": True, "keys": keys})


@app.route('/api/data-cache/token', methods=['POST', 'PUT'])
def refresh_token():
    try:
        data = request.get_json()
        if data and 'token' in data:
            cache_service.set_header('x-token', data['token'])
            logger.info("Token更新成功")
            cache_data = {
                "datas": cache_service.get_datas(),
                "headers": cache_service.get_headers()
            }
            return jsonify({"success": True, "data": cache_data})
        else:
            import subprocess
            result = subprocess.run(
                ['python3', 'configs/getToken.py'],
                capture_output=True,
                text=True,
                cwd=BASE_DIR
            )
            if result.returncode == 0:
                cache_data = {
                    "datas": cache_service.get_datas(),
                    "headers": cache_service.get_headers()
                }
                logger.info("Token刷新成功")
                return jsonify({"success": True, "data": cache_data})
            else:
                return jsonify({"success": False, "message": result.stderr})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/api/logs/stream', methods=['GET'])
def logs_stream():
    @stream_with_context
    def generate():
        queue = collections.deque()
        _log_listeners.append(queue)
        try:
            for line in _log_buffer:
                yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
            while True:
                if queue:
                    line = queue.popleft()
                    yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
                else:
                    time.sleep(0.3)
                    yield "data: " + json.dumps({"heartbeat": True}) + "\n\n"
        except GeneratorExit:
            pass
        finally:
            if queue in _log_listeners:
                _log_listeners.remove(queue)

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    _log_buffer.clear()
    return jsonify({"success": True})


@app.route('/api/test-reports', methods=['GET'])
def get_test_reports():
    reports = load_json(TEST_REPORTS_FILE)
    return jsonify({"success": True, "reports": reports})


@app.route('/api/test-reports/<report_id>', methods=['DELETE'])
def delete_test_report(report_id):
    reports = load_json(TEST_REPORTS_FILE)
    reports = [r for r in reports if r.get("id") != report_id]
    save_json(TEST_REPORTS_FILE, reports)
    
    csv_file = os.path.join(REPORTS_DIR, f'test_report_{report_id}.csv')
    html_file = os.path.join(REPORTS_DIR, f'test_report_{report_id}.html')
    if os.path.exists(csv_file):
        os.remove(csv_file)
    if os.path.exists(html_file):
        os.remove(html_file)
    
    logger.info(f"删除测试报告成功: {report_id}")
    return jsonify({"success": True})


@app.route('/api/test-reports/<report_id>/download')
def download_test_report(report_id):
    report_file = os.path.join(REPORTS_DIR, f'test_report_{report_id}.csv')
    if os.path.exists(report_file):
        return send_file(report_file, as_attachment=True)
    return jsonify({"success": False, "message": "报告不存在"}), 404


@app.route('/api/test-reports/<report_id>/preview')
def preview_test_report(report_id):
    html_file = os.path.join(REPORTS_DIR, f'test_report_{report_id}.html')
    if os.path.exists(html_file):
        return send_file(html_file)
    return jsonify({"success": False, "message": "报告不存在"}), 404


@app.route('/api/locust/report/<report_name>')
def preview_locust_report(report_name):
    report_file = os.path.join(REPORTS_DIR, report_name)
    if os.path.exists(report_file) and report_file.endswith('.html'):
        return send_file(report_file)
    return jsonify({"success": False, "message": "报告不存在"}), 404


@app.route('/api/test-cases', methods=['GET'])
def get_test_cases():
    cases = load_json(TEST_CASES_FILE)
    return jsonify({"success": True, "cases": cases})


@app.route('/api/test-cases', methods=['POST'])
def create_test_case():
    data = request.get_json()
    cases = load_json(TEST_CASES_FILE)
    case_id = str(uuid.uuid4())[:8]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    case = {
        "id": case_id,
        "name": data.get("name", ""),
        "apiIds": data.get("apiIds", []),
        "createdAt": now,
        "updatedAt": now
    }
    cases.append(case)
    save_json(TEST_CASES_FILE, cases)
    logger.info(f"创建测试用例成功: {case['name']}")
    return jsonify({"success": True, "case": case})


@app.route('/api/test-cases/<case_id>', methods=['PUT'])
def update_test_case(case_id):
    data = request.get_json()
    cases = load_json(TEST_CASES_FILE)
    for i, case in enumerate(cases):
        if case["id"] == case_id:
            cases[i].update(data)
            cases[i]["updatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            save_json(TEST_CASES_FILE, cases)
            logger.info(f"更新测试用例成功: {case['name']}")
            return jsonify({"success": True, "case": cases[i]})
    return jsonify({"success": False, "message": "用例不存在"}), 404


@app.route('/api/test-cases/<case_id>', methods=['DELETE'])
def delete_test_case(case_id):
    cases = load_json(TEST_CASES_FILE)
    cases = [c for c in cases if c.get("id") != case_id]
    save_json(TEST_CASES_FILE, cases)
    logger.info(f"删除测试用例成功: {case_id}")
    return jsonify({"success": True})


@app.route('/api/test-cases/execute/<case_id>', methods=['POST'])
def execute_test_case(case_id):
    cases = load_json(TEST_CASES_FILE)
    case = next((c for c in cases if c.get("id") == case_id), None)
    if not case:
        return jsonify({"success": False, "message": "用例不存在"}), 404
    
    results = []
    success_count = 0
    error_count = 0
    
    for api_id in case.get("apiIds", []):
        result = test_service.test_api(api_id)
        if result["status"] == "success":
            success_count += 1
        else:
            error_count += 1
        results.append({
            "apiId": api_id,
            "status": result["status"],
            "statusCode": result.get("statusCode", 0),
            "message": result.get("message", "")
        })
    
    return jsonify({
        "success": True,
        "results": results,
        "successCount": success_count,
        "errorCount": error_count
    })


@app.route('/api/case-modules', methods=['GET'])
def get_case_modules():
    data = load_json(CASE_MODULES_FILE)
    return jsonify({"success": True, "modules": data.get("modules", [])})


@app.route('/api/case-modules', methods=['POST'])
def create_case_module():
    data = request.get_json()
    modules_data = load_json(CASE_MODULES_FILE)
    modules = modules_data.get("modules", [])
    
    module_id = str(uuid.uuid4())[:8]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    module = {
        "id": module_id,
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "createdAt": now
    }
    
    modules.append(module)
    modules_data["modules"] = modules
    save_json(CASE_MODULES_FILE, modules_data)
    
    logger.info(f"创建用例模块成功: {module_id}")
    return jsonify({"success": True, "module": module})


@app.route('/api/case-modules/<module_id>', methods=['PUT'])
def update_case_module(module_id):
    data = request.get_json()
    modules_data = load_json(CASE_MODULES_FILE)
    modules = modules_data.get("modules", [])
    
    for module in modules:
        if module["id"] == module_id:
            module["name"] = data.get("name", module["name"])
            module["description"] = data.get("description", module["description"])
            break
    else:
        return jsonify({"success": False, "msg": "模块不存在"})
    
    modules_data["modules"] = modules
    save_json(CASE_MODULES_FILE, modules_data)
    
    logger.info(f"更新用例模块成功: {module_id}")
    return jsonify({"success": True, "module": module})


from configs import config as env_config

@app.route('/api/project/envs', methods=['GET'])
def get_envs():
    envs = env_config.ENV_CONFIGS
    current_env = env_config.get_current_env()
    return jsonify({"success": True, "envs": envs, "currentEnv": current_env})


@app.route('/api/project/envs', methods=['POST'])
def update_envs():
    data = request.get_json()
    if "current" in data:
        env_config.switch_env(data["current"])
    if "envs" in data:
        for key, value in data["envs"].items():
            env_config.update_env(key, value)
    return jsonify({"success": True})


@app.route('/api/project/envs/<env_key>', methods=['POST'])
def add_env(env_key):
    data = request.get_json()
    env_config.add_env(env_key, data)
    return jsonify({"success": True})


@app.route('/api/project/envs/<env_key>', methods=['DELETE'])
def delete_env(env_key):
    env_config.delete_env(env_key)
    return jsonify({"success": True})


_locust_process = None
LOCUST_STATS_FILE = os.path.join(DATA_DIR, 'locust_stats.json')

def load_locust_stats():
    if os.path.exists(LOCUST_STATS_FILE):
        try:
            with open(LOCUST_STATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "status": "idle",
        "totalRequests": 0,
        "successRate": "0%",
        "avgResponseTime": 0,
        "maxResponseTime": 0,
        "currentUsers": 0,
        "tps": 0,
        "results": []
    }

def save_locust_stats(stats):
    with open(LOCUST_STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

_locust_test_stats = load_locust_stats()


@app.route('/locust')
def locust_page():
    return render_template('locust.html')


@app.route('/api/locust/start', methods=['POST'])
def start_locust_test():
    global _locust_process, _locust_test_stats
    
    if _locust_process and _locust_process.poll() is None:
        return jsonify({"success": False, "message": "已有测试正在运行"})
    
    data = request.get_json()
    api_ids = data.get('apiIds', [])
    user_count = data.get('userCount', 10)
    spawn_rate = data.get('spawnRate', 2)
    duration = data.get('duration', 60)
    wait_time = data.get('waitTime', 1000)
    
    if not api_ids:
        return jsonify({"success": False, "message": "请选择接口"})
    
    apis = load_json(APIS_FILE)
    # apis.json 结构为 {"apis": [...]}
    api_list = apis.get('apis', []) if isinstance(apis, dict) else apis
    selected_apis = [a for a in api_list if a.get('id') in api_ids]
    
    if not selected_apis:
        return jsonify({"success": False, "message": "未找到选中的接口"})
    
    locust_file = os.path.join(BASE_DIR, 'locustfile.py')
    generate_locust_file(locust_file, selected_apis, wait_time)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    csv_output = os.path.join(REPORTS_DIR, f'locust_results_{timestamp}')
    html_output = os.path.join(REPORTS_DIR, f'locust_report_{timestamp}.html')
    
    _locust_test_stats = {
        "status": "running",
        "totalRequests": 0,
        "successRate": "0%",
        "avgResponseTime": 0,
        "maxResponseTime": 0,
        "currentUsers": 0,
        "tps": 0,
        "results": [],
        "startTime": time.time(),
        "duration": duration,
        "userCount": user_count,
        "spawnRate": spawn_rate,
        "htmlReportPath": html_output
    }
    save_locust_stats(_locust_test_stats)
    
    try:
        import requests
        
        locust_port = 8089
        cmd = [
            'locust', '-f', locust_file,
            '--host', env_config.get_host(),
            '--web-port', str(locust_port),
            '--csv', csv_output,
            '--html', html_output
        ]
        
        _locust_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        logger.info(f"Locust 测试启动: {cmd}")
        
        time.sleep(3)
        
        try:
            # Locust 2.x 的 /swarm 接口只接受 form/query，不接受 JSON body
            # 传递 run_time 参数使 Locust 在指定时长后自动停止测试
            start_data = {
                "user_count": user_count,
                "spawn_rate": spawn_rate,
                "host": env_config.get_host(),
                "run_time": f"{duration}s"
            }
            resp = requests.post(
                f'http://localhost:{locust_port}/swarm',
                data=start_data,
                timeout=5
            )
            if resp.status_code == 200:
                try:
                    resp_json = resp.json()
                except Exception:
                    resp_json = {}
                if resp_json.get('success'):
                    logger.info(f"Locust swarm 启动成功: {resp.text}")
                else:
                    logger.error(f"Locust swarm 启动失败: {resp.text}")
                    _locust_process.terminate()
                    _locust_process.wait()
                    return jsonify({"success": False, "message": f"启动 swarm 失败: {resp.text}"})
            else:
                logger.error(f"Locust swarm 启动失败: {resp.text}")
                _locust_process.terminate()
                _locust_process.wait()
                return jsonify({"success": False, "message": f"启动 swarm 失败: {resp.text}"})
        except Exception as e:
            logger.error(f"连接 Locust 失败: {str(e)}")
            _locust_process.terminate()
            _locust_process.wait()
            return jsonify({"success": False, "message": f"连接 Locust 失败: {str(e)}"})
        
        def monitor_test():
            global _locust_test_stats
            start_time = time.time()
            
            while time.time() - start_time < duration + 30:
                if _locust_process.poll() is not None:
                    exit_code = _locust_process.returncode
                    logger.info(f"Locust 进程已退出, 退出码: {exit_code}")
                    break
                time.sleep(1)
            
            _locust_test_stats = load_locust_stats()
            _locust_test_stats["status"] = "completed"
            _locust_test_stats["results"] = parse_locust_results(selected_apis)
            save_locust_stats(_locust_test_stats)
            
            try:
                requests.post(f'http://localhost:{locust_port}/stop', timeout=5)
                time.sleep(5)
            except:
                pass
            
            if _locust_process.poll() is None:
                try:
                    _locust_process.terminate()
                    _locust_process.wait()
                except:
                    pass
        
        import threading
        threading.Thread(target=monitor_test, daemon=True).start()
        
        return jsonify({"success": True, "message": "测试已启动"})
    
    except Exception as e:
        logger.error(f"启动 Locust 失败: {str(e)}")
        return jsonify({"success": False, "message": f"启动失败: {str(e)}"})


@app.route('/api/locust/stop', methods=['POST'])
def stop_locust_test():
    global _locust_process, _locust_test_stats
    
    final_locust_stats = []
    
    if _locust_process and _locust_process.poll() is None:
        try:
            import requests
            resp = requests.get('http://localhost:8089/stats/requests', timeout=2)
            if resp.status_code == 200:
                final_locust_stats = resp.json().get("stats", [])
                logger.info(f"获取最终统计数据: {len(final_locust_stats)} 条")
        except Exception as e:
            logger.error(f"获取最终统计数据失败: {str(e)}")
        
        try:
            import requests
            requests.post('http://localhost:8089/stop', timeout=2)
            time.sleep(3)
        except Exception as e:
            logger.error(f"优雅停止失败，使用强制终止: {str(e)}")
        
        if _locust_process.poll() is None:
            _locust_process.terminate()
            _locust_process.wait()
        
        logger.info("Locust 测试已停止")
    
    _locust_test_stats = load_locust_stats()
    results = parse_locust_results_from_api(final_locust_stats)
    _locust_test_stats["status"] = "completed"
    _locust_test_stats["results"] = results
    _locust_test_stats["locustStats"] = []
    
    html_report_path = _locust_test_stats.get('htmlReportPath', '')
    if html_report_path and os.path.exists(html_report_path):
        report_file = html_report_path
    else:
        test_config = _locust_test_stats.get('config', {})
        report_file = generate_locust_html_report(results, test_config)
    
    _locust_test_stats["reportFile"] = os.path.basename(report_file)
    
    save_locust_stats(_locust_test_stats)
    return jsonify({"success": True, "reportFile": os.path.basename(report_file)})


# Locust页面中文替换映射表
LOCUST_TRANSLATIONS = {
    'Host': '主机',
    'Status': '状态',
    'Users': '用户数',
    'RPS': '请求/秒',
    'Failures': '失败率',
    'EDIT': '编辑',
    'STOP': '停止',
    'RESET': '重置',
    'STATISTICS': '统计',
    'CHARTS': '图表',
    'FAILURES': '失败',
    'EXCEPTIONS': '异常',
    'CURRENT RATIO': '当前比例',
    'DOWNLOAD DATA': '下载数据',
    'LOGS': '日志',
    'Type': '类型',
    'Name': '名称',
    '# Requests': '请求数',
    '# Fails': '失败数',
    'Median (ms)': '中位数(毫秒)',
    '95%ile (ms)': '95%耗时(毫秒)',
    '99%ile (ms)': '99%耗时(毫秒)',
    'Average (ms)': '平均(毫秒)',
    'Min (ms)': '最小(毫秒)',
    'Max (ms)': '最大(毫秒)',
    'Average size (bytes)': '平均大小(字节)',
    'Current RPS': '当前请求/秒',
    'Current Failures/s': '当前失败/秒',
    'RUNNING': '运行中',
    'Aggregated': '汇总',
    'ABOUT': '关于',
    'Total RPS': '总请求/秒',
    'Total Failures/s': '总失败/秒'
}

def translate_locust_html(html_content):
    """将Locust页面中的英文标签替换为中文"""
    for en, zh in LOCUST_TRANSLATIONS.items():
        html_content = html_content.replace(en, zh)
    return html_content

@app.route('/locust-proxy/<path:path>')
def locust_proxy(path):
    """代理Locust服务的所有请求，并对HTML页面进行中文替换"""
    locust_url = f'http://localhost:8089/{path}'
    try:
        resp = requests.get(locust_url)
        content_type = resp.headers.get('Content-Type', '')
        
        if 'text/html' in content_type:
            # 对HTML页面进行中文替换
            translated = translate_locust_html(resp.text)
            return translated, resp.status_code, dict(resp.headers)
        else:
            # 其他资源直接返回
            return resp.content, resp.status_code, dict(resp.headers)
    except Exception as e:
        logger.error(f'Locust代理请求失败: {e}')
        return '', 503

@app.route('/api/locust/stats', methods=['GET'])
def get_locust_stats():
    global _locust_test_stats, _locust_process
    
    _locust_test_stats = load_locust_stats()
    
    if _locust_test_stats["status"] == "running":
        if _locust_process and _locust_process.poll() is not None:
            _locust_test_stats["status"] = "completed"
            logger.info(f"检测到 Locust 进程已退出，状态更新为 completed")
            save_locust_stats(_locust_test_stats)
            return jsonify({"success": True, "stats": _locust_test_stats})
        
        try:
            import requests
            locust_port = 8089
            
            resp = requests.get(f'http://localhost:{locust_port}/stats/requests', timeout=2)
            if resp.status_code == 200:
                locust_data = resp.json()
                
                _locust_test_stats["status"] = locust_data.get("state", "running")
                if _locust_test_stats["status"] == "stopped":
                    _locust_test_stats["status"] = "completed"
                    logger.info(f"Locust 测试已停止，状态更新为 completed")
                    save_locust_stats(_locust_test_stats)
                
                return jsonify({"success": True, "stats": _locust_test_stats})
        except Exception as e:
            logger.error(f"获取 Locust 状态异常: {str(e)}")
        
        elapsed = time.time() - _locust_test_stats.get("startTime", 0)
        duration = _locust_test_stats.get("duration", 60)
        
        if elapsed >= duration and _locust_test_stats["status"] != "completed":
            _locust_test_stats["status"] = "completed"
            logger.info(f"测试超时，状态更新为 completed")
            save_locust_stats(_locust_test_stats)
    
    return jsonify({"success": True, "stats": _locust_test_stats})


def generate_locust_file(filepath, apis, wait_time_ms):
    wait_time = wait_time_ms / 1000

    # 加载 data.json 中的全局 headers 和 datas，用于合并到请求中并替换变量占位符
    project_data = load_json(PROJECT_DATA_FILE)
    global_headers = project_data.get("headers", {})
    global_datas = project_data.get("datas", {})

    def _resolve_placeholders_in_obj(obj):
        """递归替换对象中的 {{变量}} 占位符，使用 data.json 中的 datas 数据。"""
        if isinstance(obj, str):
            result = obj
            for key, value in global_datas.items():
                placeholder = f"{{{{{key}}}}}"
                if placeholder in result:
                    result = result.replace(placeholder, str(value))
            return result
        elif isinstance(obj, dict):
            return {k: _resolve_placeholders_in_obj(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_resolve_placeholders_in_obj(item) for item in obj]
        else:
            return obj

    def _py_literal(value):
        """把 Python 对象转成 locustfile 可直接 exec 的字面量字符串。

        json.dumps 默认输出 true/false（小写），但 Python 用 True/False。
        这里用 repr 序列化，能正确处理 dict/list/str/int/float/bool/None。
        """
        if isinstance(value, bool):
            return 'True' if value else 'False'
        if value is None:
            return 'None'
        if isinstance(value, (dict, list, tuple)):
            return repr(value)
        return json.dumps(value, ensure_ascii=False)

    code = f'''# coding=utf-8
from locust import HttpUser, task, constant
import json

class ApiUser(HttpUser):
    wait_time = constant({wait_time})

    def on_start(self):
        pass
'''

    for api in apis:
        api_name = api['name'].replace(' ', '_').replace('-', '_')
        method = api['method'].lower()
        url = _py_literal(api['url'])

        merged_headers = {**global_headers, **api.get('headers', {})}
        headers = _py_literal(merged_headers)

        params = _py_literal(api.get('params', {}))

        raw_body = api.get('body', {})
        resolved_body = _resolve_placeholders_in_obj(raw_body)
        body = _py_literal(resolved_body)

        code += f'''
    @task
    def test_{api_name}(self):
        url = {url}
        headers = {headers}
        params = {params}
        # 使用接口名称作为Locust统计显示名称，便于识别
        request_name = {_py_literal(api['name'])}

        try:
            if {json.dumps(method)} == "get":
                self.client.get(url, headers=headers, params=params, name=request_name)
            elif {json.dumps(method)} == "post":
                body = {body}
                self.client.post(url, headers=headers, json=body, name=request_name)
            elif {json.dumps(method)} == "put":
                body = {body}
                self.client.put(url, headers=headers, json=body, name=request_name)
            elif {json.dumps(method)} == "delete":
                self.client.delete(url, headers=headers, params=params, name=request_name)
        except Exception as e:
            pass
'''

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)


def parse_locust_results(apis):
    results = []
    csv_file = os.path.join(REPORTS_DIR, 'locust_results_stats.csv')

    api_list = []
    if apis:
        api_list = apis.get('apis', []) if isinstance(apis, dict) else apis
    else:
        apis_data = load_json(APIS_FILE)
        api_list = apis_data.get('apis', []) if isinstance(apis_data, dict) else apis_data

    if os.path.exists(csv_file):
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('Name') == 'Aggregated':
                        continue
                    try:
                        api_name = row['Name']
                        
                        matched_api = None
                        for api in api_list:
                            api_url = api.get('url', '')
                            if api_url and (api_name == api_url or api_name.endswith(api_url) or api_url in api_name):
                                matched_api = api
                                break
                        
                        if matched_api:
                            api_name = matched_api.get('name', api_name)
                        
                        results.append({
                            'apiName': api_name,
                            'requests': int(row.get('# requests', 0) or 0),
                            'successRate': row.get('Success Rate', '0%'),
                            'avgResponseTime': int(float(row.get('Average Response Time', 0) or 0)),
                            'minResponseTime': int(float(row.get('Min Response Time', 0) or 0)),
                            'maxResponseTime': int(float(row.get('Max Response Time', 0) or 0))
                        })
                    except (ValueError, KeyError):
                        continue
        except Exception as e:
            logger.error(f"解析 Locust 结果失败: {str(e)}")
    
    for api in apis:
        api_name = f'test_{api["name"].replace(" ", "_").replace("-", "_")}'
        exists = any(r['apiName'] == api_name for r in results)
        if not exists:
            results.append({
                'apiName': api['name'],
                'requests': 0,
                'successRate': '0%',
                'avgResponseTime': 0,
                'minResponseTime': 0,
                'maxResponseTime': 0
            })
    
    return results


def parse_locust_results_from_api(locust_stats):
    results = []
    
    apis_data = load_json(APIS_FILE)
    api_list = apis_data.get('apis', []) if isinstance(apis_data, dict) else apis_data
    
    for stat in locust_stats:
        stat_name = stat.get('name', '')
        if stat_name == 'Aggregated':
            continue
        
        matched_api = None
        for api in api_list:
            api_url = api.get('url', '')
            if api_url and (stat_name == api_url or stat_name.endswith(api_url) or api_url in stat_name):
                matched_api = api
                break
        
        api_name = matched_api.get('name', stat_name) if matched_api else stat_name
        
        num_requests = stat.get('num_requests', 0)
        num_failures = stat.get('num_failures', 0)
        success_rate = f"{int((num_requests - num_failures) / num_requests * 100)}%" if num_requests > 0 else "0%"
        
        p95_key = 'response_time_percentile_0.95'
        p95_alt_key = 'response_time_percentile_95'
        p95 = stat[p95_key] if p95_key in stat else (stat[p95_alt_key] if p95_alt_key in stat else 0)
        
        p99_key = 'response_time_percentile_0.99'
        p99_alt_key = 'response_time_percentile_99'
        p99 = stat[p99_key] if p99_key in stat else (stat[p99_alt_key] if p99_alt_key in stat else 0)
        
        results.append({
            'apiName': api_name,
            'requests': num_requests,
            'failures': num_failures,
            'successRate': success_rate,
            'medianResponseTime': int(stat.get('median_response_time', 0)),
            'p95ResponseTime': int(p95),
            'p99ResponseTime': int(p99),
            'avgResponseTime': int(stat.get('avg_response_time', 0)),
            'minResponseTime': int(stat.get('min_response_time', 0)),
            'maxResponseTime': int(stat.get('max_response_time', 0)),
            'tps': stat.get('current_rps', 0)
        })
    
    return results


def generate_locust_html_report(results, test_config):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(REPORTS_DIR, f'locust_report_{timestamp}.html')
    
    total_requests = sum(r['requests'] for r in results)
    total_failures = sum(r['failures'] for r in results)
    success_count = sum(1 for r in results if r['failures'] == 0)
    avg_tps = sum(r['tps'] for r in results) / len(results) if results else 0
    avg_response = sum(r['avgResponseTime'] for r in results) / len(results) if results else 0
    max_response = max(r['maxResponseTime'] for r in results) if results else 0
    
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>性能测试报告 - {timestamp}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; padding: 20px; }}
        .report {{ max-width: 1400px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #10b981, #059669); color: white; padding: 24px 32px; }}
        .header h1 {{ font-size: 24px; font-weight: 600; }}
        .header p {{ margin-top: 8px; opacity: 0.9; }}
        .config {{ padding: 16px 32px; background: #f0fdf4; border-bottom: 1px solid #dcfce7; font-size: 14px; color: #065f46; }}
        .config span {{ margin-right: 24px; }}
        .stats {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 16px; padding: 24px 32px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }}
        .stat {{ background: white; padding: 16px; border-radius: 8px; text-align: center; }}
        .stat .label {{ font-size: 12px; color: #64748b; margin-bottom: 4px; }}
        .stat .value {{ font-size: 24px; font-weight: 700; }}
        .stat.success .value {{ color: #22c55e; }}
        .stat.error .value {{ color: #ef4444; }}
        .stat.total .value {{ color: #6366f1; }}
        .stat.tps .value {{ color: #f59e0b; }}
        .stat.time .value {{ color: #3b82f6; }}
        .chart {{ padding: 24px 32px; }}
        .chart-title {{ font-size: 16px; font-weight: 600; color: #1e293b; margin-bottom: 16px; }}
        .pie-chart {{ width: 200px; height: 200px; border-radius: 50%; background: conic-gradient(#22c55e {100 - (total_failures/total_requests*100 if total_requests>0 else 0)}%, #ef4444 {total_failures/total_requests*100 if total_requests>0 else 0}%); position: relative; margin: 0 auto; }}
        .pie-center {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; width: 120px; height: 120px; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
        .pie-center .percent {{ font-size: 28px; font-weight: 700; color: #1e293b; }}
        .pie-center .text {{ font-size: 12px; color: #64748b; }}
        .legend {{ display: flex; justify-content: center; gap: 32px; margin-top: 24px; }}
        .legend-item {{ display: flex; align-items: center; gap: 8px; }}
        .legend-color {{ width: 16px; height: 16px; border-radius: 4px; }}
        .legend-color.success {{ background: #22c55e; }}
        .legend-color.error {{ background: #ef4444; }}
        .results {{ padding: 24px 32px; }}
        .results-title {{ font-size: 16px; font-weight: 600; color: #1e293b; margin-bottom: 16px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
        th {{ background: #f8fafc; font-weight: 600; color: #64748b; font-size: 13px; }}
        td {{ font-size: 14px; color: #334155; }}
        .failures {{ color: #ef4444; font-weight: 500; }}
        .success {{ color: #22c55e; font-weight: 500; }}
        .footer {{ padding: 16px 32px; background: #f8fafc; text-align: center; font-size: 12px; color: #94a3b8; }}
        .summary-row {{ background: #f8fafc; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="report">
        <div class="header">
            <h1>性能测试报告</h1>
            <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        <div class="config">
            <span><strong>并发用户数:</strong> {test_config.get('users', '-')}</span>
            <span><strong>每秒新增用户:</strong> {test_config.get('spawnRate', '-')}</span>
            <span><strong>测试时长:</strong> {test_config.get('duration', '-')}秒</span>
            <span><strong>请求间隔:</strong> {test_config.get('requestInterval', '-')}毫秒</span>
        </div>
        <div class="stats">
            <div class="stat total">
                <div class="label">总请求数</div>
                <div class="value">{total_requests}</div>
            </div>
            <div class="stat error">
                <div class="label">失败数</div>
                <div class="value">{total_failures}</div>
            </div>
            <div class="stat success">
                <div class="label">成功率</div>
                <div class="value">{100 - round(total_failures/total_requests*100, 2) if total_requests>0 else 100}%</div>
            </div>
            <div class="stat tps">
                <div class="label">平均TPS</div>
                <div class="value">{round(avg_tps, 2)}</div>
            </div>
            <div class="stat time">
                <div class="label">平均响应(ms)</div>
                <div class="value">{round(avg_response)}</div>
            </div>
            <div class="stat time">
                <div class="label">最大响应(ms)</div>
                <div class="value">{max_response}</div>
            </div>
        </div>
        <div class="results">
            <div class="results-title">接口性能统计</div>
            <table>
                <thead>
                    <tr>
                        <th>接口名称</th>
                        <th>请求数</th>
                        <th>失败数</th>
                        <th>成功率</th>
                        <th>中位数(ms)</th>
                        <th>95%(ms)</th>
                        <th>99%(ms)</th>
                        <th>平均(ms)</th>
                        <th>最小(ms)</th>
                        <th>最大(ms)</th>
                        <th>TPS</th>
                    </tr>
                </thead>
                <tbody>
"""

    for result in results:
        failures_class = 'failures' if result['failures'] > 0 else 'success'
        html_content += f"""
                    <tr>
                        <td><strong>{result['apiName']}</strong></td>
                        <td>{result['requests']}</td>
                        <td class="{failures_class}">{result['failures']}</td>
                        <td>{result['successRate']}</td>
                        <td>{result['medianResponseTime']}</td>
                        <td>{result['p95ResponseTime']}</td>
                        <td>{result['p99ResponseTime']}</td>
                        <td>{result['avgResponseTime']}</td>
                        <td>{result['minResponseTime']}</td>
                        <td>{result['maxResponseTime']}</td>
                        <td>{round(result['tps'], 2)}</td>
                    </tr>
"""

    html_content += f"""
                    <tr class="summary-row">
                        <td>汇总</td>
                        <td>{total_requests}</td>
                        <td class="{('failures' if total_failures > 0 else 'success')}">{total_failures}</td>
                        <td>{100 - round(total_failures/total_requests*100, 2) if total_requests>0 else 100}%</td>
                        <td>-</td>
                        <td>-</td>
                        <td>-</td>
                        <td>{round(avg_response)}</td>
                        <td>-</td>
                        <td>{max_response}</td>
                        <td>{round(avg_tps, 2)}</td>
                    </tr>
                </tbody>
            </table>
        </div>
        <div class="footer">
            宝信API测试管理平台 - 性能测试报告
        </div>
    </div>
</body>
</html>
"""
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return report_file


if __name__ == '__main__':
    logger.info("宝信API测试管理平台启动")
    # 关闭 reloader，避免生成 locustfile.py 触发 Flask 主进程重启导致子进程孤儿化
    app.run(debug=True, host='0.0.0.0', port=8889, use_reloader=False)