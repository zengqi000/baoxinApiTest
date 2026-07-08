import requests
import json
import re
import ast
import logging
from datetime import datetime
from ..services.cache_service import CacheService
from configs import config

logger = logging.getLogger('api_test')


class TestService:
    def __init__(self, api_model, config_model, cache_service):
        self.api_model = api_model
        self.config_model = config_model
        self.cache_service = cache_service

    def _resolve_placeholder_value(self, value, configs_data, cache_data):
        if isinstance(value, str):
            return self._resolve_string_placeholders(value, configs_data, cache_data)
        elif isinstance(value, dict):
            return {k: self._resolve_placeholder_value(v, configs_data, cache_data) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._resolve_placeholder_value(item, configs_data, cache_data) for item in value]
        else:
            return value

    def _resolve_string_placeholders(self, content, configs_data, cache_data):
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        
        resolved = set()
        all_datas = {**{c['name']: c.get('value', '') for c in configs_data}, **cache_data.get("datas", {})}
        
        pattern = r'\{\{([^}]+)\}\}'
        matches = re.findall(pattern, content)
        
        if '{{random}}' in content:
            content = content.replace('{{random}}', str(int(datetime.now().timestamp() * 1000)))
        
        for placeholder_content in matches:
            placeholder = f"{{{{{placeholder_content}}}}}"
            if placeholder not in content:
                continue
            
            sub_path = placeholder_content.replace('[', '.').replace(']', '')
            parts = sub_path.split('.')
            base_key = parts[0]
            
            if base_key not in all_datas:
                continue
            
            value = all_datas[base_key]
            
            if len(parts) > 1 and isinstance(value, (dict, list)):
                sub_path_for_extract = '.'.join(parts[1:])
                extracted = self.extract_value(value, sub_path_for_extract)
                if extracted is not None:
                    content = content.replace(placeholder, str(extracted))
                    resolved.add(base_key)
            elif base_key not in resolved:
                if isinstance(value, (dict, list)):
                    content = content.replace(placeholder, json.dumps(value, ensure_ascii=False))
                else:
                    content = content.replace(placeholder, str(value))
                resolved.add(base_key)
        
        if content.strip() in all_datas and content.strip() not in resolved:
            content = str(all_datas.get(content.strip(), ''))
        
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content

    def resolve_placeholders(self, content, configs_data, cache_data):
        if isinstance(content, dict):
            return self._resolve_placeholder_value(content, configs_data, cache_data)
        elif isinstance(content, list):
            return self._resolve_placeholder_value(content, configs_data, cache_data)
        else:
            return self._resolve_string_placeholders(content, configs_data, cache_data)

    def extract_value(self, data, path):
        if not path or not data:
            return None
        
        path = path.strip()
        
        if path.startswith('res['):
            path = path[4:-1].replace(']["', '.').replace('"]', '').replace('["', '')
        
        path = path.replace('[', '.').replace(']', '')
        
        parts = path.split('.')
        result = data
        
        for part in parts:
            if part == '':
                continue
            if isinstance(result, dict):
                result = result.get(part)
            elif isinstance(result, list):
                try:
                    idx = int(part)
                    result = result[idx] if 0 <= idx < len(result) else None
                except ValueError:
                    result = None
            else:
                result = None
            if result is None:
                break
        return result

    def execute_python_script(self, script, response_data, cache_data):
        if not script or script.strip() == "":
            return {}, {}
        
        exec_locals = {}
        saved_data = {}
        
        def save(key, value=None, comment=""):
            if value is None:
                exec_locals[key] = None
                return
            exec_locals[key] = value
            saved_data[key] = value
            if comment:
                saved_data[f"_{key}_comment"] = comment
        
        cache = cache_data.get("datas", {})
        
        try:
            exec(script, {"response": response_data, "save": save, "cache": cache}, exec_locals)
        except Exception as e:
            pass
        
        return exec_locals, saved_data

    def test_api(self, api_id, variables=None, step_assertions=None, write_cache=True, temp_vars=None):
        api = self.api_model.get_by_id(api_id)
        if not api:
            return {"status": "error", "message": "接口不存在"}
        
        if variables is None:
            variables = {}
        if step_assertions is None:
            step_assertions = []
        
        configs_data = self.config_model.get_all()
        temp_vars = temp_vars or {}
        cache_data = {
            "datas": {**self.cache_service.get_datas(), **temp_vars},
            "headers": self.cache_service.get_headers()
        }
        
        resolved_variables = {}
        for k, v in variables.items():
            if isinstance(v, str):
                if k in cache_data["datas"] and v.strip() == '{{' + k + '}}':
                    resolved_variables[k] = cache_data["datas"][k]
                else:
                    resolved_variables[k] = self.resolve_placeholders(v, configs_data, cache_data)
            else:
                resolved_variables[k] = v
        
        cache_data["datas"].update(resolved_variables)
        for k, v in resolved_variables.items():
            if isinstance(v, (str, int, float, bool)) and v is not None:
                if isinstance(v, str) and v.startswith('{{') and v.endswith('}}'):
                    continue
                temp_vars[k] = v
        logger.info(f"test_api - api_id={api_id}, temp_vars={temp_vars}, variables={variables}, resolved_variables={resolved_variables}")
        logger.info(f"test_api - cache_data[datas] keys={list(cache_data['datas'].keys())}")
        
        pre_api_result = None
        pre_api_id = api.get("preApiId", "")
        pre_api_variables = api.get("preApiVariables", {})
        
        if pre_api_id:
            logger.info(f"执行前置接口: {pre_api_id}")
            pre_api_result = self.test_api(pre_api_id, pre_api_variables, [], write_cache, temp_vars)
            
            http_success = 200 <= pre_api_result.get("statusCode", 0) < 400
            if http_success:
                for log in pre_api_result.get("savingLog", []):
                    if log.get("value") is not None:
                        temp_vars[log["cacheKey"]] = log["value"]
                        cache_data["datas"][log["cacheKey"]] = log["value"]
                logger.info(f"前置接口执行成功，更新temp_vars: {list(temp_vars.keys())}")
            else:
                logger.info(f"前置接口执行失败: {pre_api_result.get('message', '')}")
        
        configs_data = self.config_model.get_all()
        
        url = api["url"]
        if url.startswith('/'):
            url = config.get_host() + url
        
        cache_headers = self.cache_service.get_headers()
        api_headers = api.get("headers", {})
        
        headers = {**cache_headers}
        if isinstance(api_headers, dict):
            headers.update(api_headers)
        
        headers = self.resolve_placeholders(headers, configs_data, cache_data)
        
        params = {}
        if api.get("params"):
            params = self.resolve_placeholders(api["params"], configs_data, cache_data)
        
        body = {}
        if api.get("body"):
            body = self.resolve_placeholders(api["body"], configs_data, cache_data)
        
        method = api.get("method", "POST").upper()
        
        try:
            
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method == "POST":
                response = requests.post(url, headers=headers, params=params, json=body, timeout=30)
            elif method == "PUT":
                response = requests.put(url, headers=headers, params=params, json=body, timeout=30)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, params=params, json=body, timeout=30)
            else:
                return {"status": "error", "message": f"不支持的HTTP方法: {method}"}
            
            response_data = response.json()
            logger.info(f"接口 {api['name']} 响应状态码: {response.status_code}")
            logger.info(f"接口 {api['name']} 响应数据: {json.dumps(response_data, ensure_ascii=False)[:500]}")
            
            script = api.get("script", "")
            script = self.resolve_placeholders(script, configs_data, cache_data)
            exec_locals, saved_data = self.execute_python_script(script, response_data, cache_data)
            
            if saved_data and write_cache:
                for key, value in saved_data.items():
                    if not key.startswith("_"):
                        comment_key = f"_{key}_comment"
                        comment = saved_data.get(comment_key, "")
                        self.cache_service.set_data(key, value, comment)
            
            logs = []
            saving_log = []
            binding_log = []
            
            if script:
                logs.append(f"Python脚本 → {'已保存' if saved_data else '无数据'}")
            
            mapping_success = False
            response_mapping = api.get("responseMapping", [])
            if response_mapping:
                for mapping in response_mapping:
                    response_path = mapping.get("responsePath", "")
                    cache_key = mapping.get("cacheKey", "")
                    comment = mapping.get("comment", "")
                    
                    response_path = self.resolve_placeholders(response_path, configs_data, cache_data)
                    
                    value = None
                    if response_path in exec_locals:
                        value = exec_locals[response_path]
                        logger.info(f"从脚本获取值: {response_path} = {value}")
                    elif response_path in cache_data["datas"]:
                        value = cache_data["datas"][response_path]
                        logger.info(f"从缓存获取值: {response_path} = {value}")
                    else:
                        value = self.extract_value(response_data, response_path)
                        logger.info(f"从响应提取值: {response_path} = {value}")
                    
                    if value is not None:
                        if write_cache:
                            self.cache_service.set_data(cache_key, value, comment)
                            logger.info(f"保存到缓存: {cache_key} = {value}")
                        logs.append(f"{response_path} → {cache_key}")
                        saving_log.append({
                            "responsePath": response_path,
                            "cacheKey": cache_key,
                            "status": "已保存" if write_cache else "跳过",
                            "value": value
                        })
                        mapping_success = True
                    else:
                        logs.append(f"{response_path} → {cache_key} (响应中未找到此路径)")
                        saving_log.append({
                            "responsePath": response_path,
                            "cacheKey": cache_key,
                            "status": "失败",
                            "value": None
                        })
            
            assertions = step_assertions if step_assertions else api.get("assertions", [])
            assertion_results = []
            
            assertion_results.append({
                "field": "",
                "responsePath": "",
                "operator": "status_code",
                "expected": "200-399",
                "expectedValue": "200-399",
                "actual": response.status_code,
                "actualValue": response.status_code,
                "passed": 200 <= response.status_code < 400,
                "result": 200 <= response.status_code < 400
            })
            
            if assertions:
                for assertion in assertions:
                    field = assertion.get("field", assertion.get("responsePath", ""))
                    operator = assertion.get("comparator", assertion.get("operator", "eq"))
                    expected = assertion.get("expected", assertion.get("expectedValue", ""))
                    
                    expected = self.resolve_placeholders(expected, configs_data, cache_data)
                    
                    passed = False
                    if operator == "eq":
                        actual = self.extract_value(response_data, field)
                        passed = str(actual) == str(expected)
                    elif operator == "ne":
                        actual = self.extract_value(response_data, field)
                        passed = str(actual) != str(expected)
                    elif operator == "in" or operator == "contains":
                        if not field or field.strip() == "":
                            def has_key(obj, key):
                                if isinstance(obj, dict):
                                    if key in obj:
                                        return True
                                    for v in obj.values():
                                        if has_key(v, key):
                                            return True
                                elif isinstance(obj, list):
                                    for item in obj:
                                        if has_key(item, key):
                                            return True
                                return False
                            passed = has_key(response_data, expected)
                            actual = f"字段'{expected}'存在" if passed else f"字段'{expected}'不存在"
                        else:
                            actual = self.extract_value(response_data, field)
                            passed = str(expected) in str(actual)
                    elif operator == "greater_than":
                        actual = self.extract_value(response_data, field)
                        try:
                            passed = float(actual) > float(expected)
                        except ValueError:
                            passed = False
                    elif operator == "less_than":
                        actual = self.extract_value(response_data, field)
                        try:
                            passed = float(actual) < float(expected)
                        except ValueError:
                            passed = False
                    
                    assertion_results.append({
                        "field": field,
                        "responsePath": field,
                        "operator": operator,
                        "expected": expected,
                        "expectedValue": expected,
                        "actual": actual,
                        "actualValue": actual,
                        "passed": passed,
                        "result": passed
                    })
            
            all_assertions_pass = all(a["passed"] for a in assertion_results) if assertion_results else True
            
            return {
                "status": "success" if all_assertions_pass else "error",
                "statusCode": response.status_code,
                "response": response_data,
                "logs": logs,
                "assertions": assertion_results,
                "allAssertionsPass": all_assertions_pass,
                "savingLog": saving_log,
                "bindingLog": binding_log,
                "requestHeaders": headers,
                "requestParams": params,
                "requestBody": body,
                "requestUrl": url,
                "requestMethod": method,
                "responseTime": response.elapsed.total_seconds() * 1000,
                "preApiResult": pre_api_result
            }
        
        except requests.exceptions.RequestException as e:
            response_data = {}
            status_code = 0
            response_time = 0
            if hasattr(e, 'response') and e.response:
                try:
                    response_data = e.response.json()
                except:
                    response_data = e.response.text
                status_code = e.response.status_code
                response_time = e.response.elapsed.total_seconds() * 1000
            
            return {
                "status": "error",
                "message": str(e),
                "statusCode": status_code,
                "response": response_data,
                "responseTime": response_time,
                "requestHeaders": headers,
                "requestParams": params,
                "requestBody": body,
                "requestUrl": url,
                "requestMethod": method,
                "logs": [],
                "assertions": [],
                "allAssertionsPass": True,
                "savingLog": [],
                "bindingLog": [],
                "preApiResult": pre_api_result
            }

    def run_module_apis(self, module_id=None):
        results = []
        success_count = 0
        error_count = 0
        
        if module_id:
            apis = self.api_model.get_by_module(module_id)
        else:
            apis = self.api_model.get_all()
        
        self.cache_service.clear_datas()
        
        for api in apis:
            try:
                result = self.test_api(api["id"])
                if result["status"] == "success":
                    success_count += 1
                else:
                    error_count += 1
                results.append({
                    "apiId": api["id"],
                    "apiName": api["name"],
                    "status": result["status"],
                    "statusCode": result.get("statusCode", 0),
                    "message": result.get("message", "")
                })
            except Exception as e:
                error_count += 1
                results.append({
                    "apiId": api["id"],
                    "apiName": api["name"],
                    "status": "error",
                    "statusCode": 0,
                    "message": str(e)
                })
        
        return {
            "success": True,
            "results": results,
            "successCount": success_count,
            "errorCount": error_count
        }
    
    def run_case(self, case_id, case_model):
        case = case_model.get_by_id(case_id)
        if not case:
            return {"success": False, "message": "用例不存在"}
        
        results = []
        success_count = 0
        error_count = 0
        temp_vars = {}
        
        case_desc = case.get("description", "")
        logger.info(f"run_case - case_desc: {case_desc}")
        if case_desc:
            try:
                desc_vars = json.loads(case_desc)
                logger.info(f"run_case - desc_vars: {desc_vars}")
                if isinstance(desc_vars, dict):
                    configs_data = self.config_model.get_all()
                    cache_data = {
                        "datas": {**self.cache_service.get_datas(), **temp_vars},
                        "headers": self.cache_service.get_headers()
                    }
                    for key, value in desc_vars.items():
                        if isinstance(value, str):
                            value = self.resolve_placeholders(value, configs_data, cache_data)
                        temp_vars[key] = value
                    logger.info(f"解析临时变量后: {temp_vars}")
                    logger.info(f"临时变量 name 的值: {temp_vars.get('name', '未设置')}")
            except json.JSONDecodeError as e:
                logger.error(f"解析临时变量失败: {e}")
                pass
        
        steps = case.get("steps", [])
        for step in steps:
            api_id = step.get("apiId")
            api_name = step.get("apiName", "")
            variables = step.get("variables", {})
            assertions = step.get("assertions", [])
            
            for key, value in list(variables.items()):
                if isinstance(value, str) and value.startswith('{{') and value.endswith('}}'):
                    placeholder_key = value[2:-2].strip()
                    if placeholder_key in temp_vars:
                        variables[key] = temp_vars[placeholder_key]
                        logger.info(f"将临时变量 {placeholder_key} 的值 '{temp_vars[placeholder_key]}' 赋值给 {key}")
            
            try:
                result = self.test_api(api_id, variables, assertions, write_cache=False, temp_vars=temp_vars)
                if result["status"] == "success":
                    success_count += 1
                else:
                    error_count += 1
                
                api = self.api_model.get_by_id(api_id)
                url = api["url"] if api else ""
                if url.startswith('/'):
                    url = config.get_host() + url
                method = api.get("method", "POST").upper() if api else "POST"
                
                for log in result.get("savingLog", []):
                    if log.get("value") is not None:
                        temp_vars[log["cacheKey"]] = log["value"]
                
                results.append({
                    "step": step.get("step", 0),
                    "apiId": api_id,
                    "apiName": api_name,
                    "status": result["status"],
                    "statusCode": result.get("statusCode", 0),
                    "message": result.get("message", ""),
                    "response": result.get("response", {}),
                    "responseTime": result.get("responseTime", 0),
                    "requestUrl": url,
                    "requestMethod": method,
                    "requestParams": result.get("requestParams", {}),
                    "requestBody": result.get("requestBody", {}),
                    "requestHeaders": result.get("requestHeaders", {}),
                    "assertionResults": result.get("assertions", []),
                    "allAssertionsPass": result.get("allAssertionsPass", True),
                    "savingLog": result.get("savingLog", []),
                    "bindingLog": result.get("bindingLog", [])
                })
            except Exception as e:
                error_count += 1
                results.append({
                    "step": step.get("step", 0),
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
                })
        
        return {
            "success": True,
            "caseName": case.get("name", ""),
            "results": results,
            "successCount": success_count,
            "errorCount": error_count
        }