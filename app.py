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


@app.route('/code')
def code():
    return render_template('code.html')


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
    
    result = test_service.test_api(api_id, variables, write_cache=False)
    
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
        "bindingLog": result.get("bindingLog", [])
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


@app.route('/api/code/generate', methods=['POST'])
def generate_code():
    data = request.get_json()
    api_ids = data.get("apiIds", [])
    
    code_lines = [
        "# coding=utf-8",
        "\"\"\"",
        "宝信 API 测试代码 - 自动生成",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "\"\"\"",
        "",
        "import unittest",
        "import sys",
        "sys.path.insert(0, '..')",
        "",
        "from utilss import *",
        "",
        "",
        "class TestAPIs(unittest.TestCase):",
        "    \"\"\"API测试用例\"\"\"",
        "",
        "    def setUp(self):",
        "        \"\"\"测试前准备\"\"\"",
        "        pass",
        "",
        "    def tearDown(self):",
        "        \"\"\"测试后清理\"\"\"",
        "        pass",
        ""
    ]
    
    apis = api_model.get_all()
    for api_id in api_ids:
        api = api_model.get_by_id(api_id)
        if api:
            func_name = api.get("funcName", f"test_{api['id']}")
            code_lines.append(f"    def {func_name}(self):")
            code_lines.append(f"        \"\"\"{api.get('name', '')}\"\"\"")
            code_lines.append(f"        result = {func_name}()")
            code_lines.append("        self.assertEqual(result['status'], 'success')")
            code_lines.append("")
    
    code_lines.append("")
    code_lines.append("if __name__ == '__main__':")
    code_lines.append("    unittest.main()")
    
    code = "\n".join(code_lines)
    return jsonify({"success": True, "code": code})


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


if __name__ == '__main__':
    logger.info("宝信API测试管理平台启动")
    app.run(debug=True, host='0.0.0.0', port=5555)