# -*- coding: utf-8 -*-
"""
Report Master Backend - Flask应用主入口
提供RESTful API接口和静态文件服务
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import json
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))

from core.role_manager import RoleManager
from core.workflow import WorkflowEngineV2

# 设置静态文件目录
app = Flask(__name__, 
            static_folder='../frontend',
            static_url_path='')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# 全局变量
role_manager = None
workflow_engine = None


@app.route('/')
def index():
    """主页"""
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({"status": "ok", "version": "0.6"})


@app.route('/api/roles', methods=['GET'])
def get_roles():
    """获取所有角色配置"""
    global role_manager
    if not role_manager:
        role_manager = RoleManager("config/roles.json")
    
    roles = []
    for role_name in role_manager.list_roles():
        agent = role_manager.get_agent(role_name)
        roles.append({
            "name": role_name,
            "description": agent.description
        })
    
    return jsonify({"roles": roles})


@app.route('/api/roles', methods=['POST'])
def save_roles():
    """保存角色配置"""
    data = request.json
    config_path = Path("config/roles.json")
    
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # 重新加载角色
    global role_manager
    role_manager = RoleManager("config/roles.json")
    
    return jsonify({"success": True, "message": "配置已保存"})


@app.route('/api/start_workflow', methods=['POST'])
def start_workflow():
    """启动工作流（接收前端配置）"""
    data = request.json
    topic = data.get('topic', '')
    mode = data.get('mode', 'standard')
    config = data.get('config', {})
    
    if not topic:
        return jsonify({"success": False, "error": "主题不能为空"}), 400
    
    if not config:
        return jsonify({"success": False, "error": "配置不能为空"}), 400
    
    # 使用前端传递的配置创建临时配置文件
    temp_config_path = Path("config/temp_roles.json")
    temp_config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    # 使用临时配置初始化角色管理器
    global role_manager, workflow_engine
    role_manager = RoleManager(str(temp_config_path))
    workflow_engine = WorkflowEngineV2(role_manager, socketio)
    
    # 在后台线程中执行工作流
    socketio.start_background_task(
        target=workflow_engine.execute_collaborative_workflow,
        topic=topic,
        mode=mode
    )
    
    return jsonify({"success": True, "message": "工作流已启动"})


@app.route('/api/workflow/history', methods=['GET'])
def get_workflow_history():
    """获取工作流历史"""
    global workflow_engine
    if not workflow_engine:
        return jsonify({"history": []})
    
    return jsonify({"history": workflow_engine.get_history()})


@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    print('客户端已连接')
    emit('connected', {'message': '已连接到服务器'})


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    print('客户端已断开')


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
