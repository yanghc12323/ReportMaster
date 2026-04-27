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
from threading import Event
from werkzeug.utils import secure_filename
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
workflow_cancel_event = None


@app.route('/')
def index():
    """主页"""
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({"status": "ok", "version": "0.7"})


def _extract_text_from_pdf(file_path: Path) -> str:
    """从 PDF 提取文本（优先使用 pypdf，缺失时返回说明）。"""
    try:
        from pypdf import PdfReader
    except Exception:
        return "[提示] 当前环境未安装 pypdf，无法解析 PDF 正文。"

    reader = PdfReader(str(file_path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"\n[PDF 第{index}页]\n{text}")
    return "\n".join(pages).strip()


def _extract_text_from_docx(file_path: Path) -> str:
    """从 DOCX 提取文本（依赖 python-docx）。"""
    try:
        from docx import Document
    except Exception:
        return "[提示] 当前环境未安装 python-docx，无法解析 Word 正文。"

    doc = Document(str(file_path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return "\n".join(paragraphs).strip()


def _extract_text_from_word(file_path: Path, ext: str) -> str:
    """Word 解析入口：docx 可解析，doc 给出兼容提示。"""
    if ext == '.docx':
        return _extract_text_from_docx(file_path)

    # .doc 旧格式通常需额外依赖（如 antiword/textract），此处先保底接入语料流程
    return "[提示] 已接收 .doc 文件，但当前环境未启用旧版 Word(.doc) 正文解析。建议另存为 .docx 以获得完整文本提取。"


def _extract_text_from_image(file_path: Path) -> str:
    """从 PNG 识别文本（优先 OCR，缺失依赖时给出说明）。"""
    try:
        from PIL import Image
        import pytesseract
    except Exception:
        return "[提示] 当前环境未安装 OCR 依赖（Pillow/pytesseract），仅接收图片文件名作为语料线索。"

    image = Image.open(str(file_path))
    text = pytesseract.image_to_string(image, lang='chi_sim+eng')
    return (text or "").strip()


@app.route('/api/corpus/upload', methods=['POST'])
def upload_corpus():
    """上传语料文件（支持 pdf/doc/docx/png），提取文本后返回给前端。"""
    if 'files' not in request.files:
        return jsonify({"success": False, "error": "未接收到文件"}), 400

    files = request.files.getlist('files')
    if not files:
        return jsonify({"success": False, "error": "文件列表为空"}), 400

    allowed = {'.pdf', '.doc', '.docx', '.png'}
    upload_dir = Path("backend/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)

    snippets = []
    accepted_files = []

    for file in files:
        raw_name = file.filename or ''
        safe_name = secure_filename(raw_name)
        if not safe_name:
            continue

        ext = Path(safe_name).suffix.lower()
        if ext not in allowed:
            continue

        target_path = upload_dir / safe_name
        file.save(target_path)

        try:
            if ext == '.pdf':
                extracted = _extract_text_from_pdf(target_path)
            elif ext in {'.doc', '.docx'}:
                extracted = _extract_text_from_word(target_path, ext)
            else:
                extracted = _extract_text_from_image(target_path)
        except Exception as exc:
            extracted = f"[解析失败] {safe_name}: {str(exc)}"

        snippets.append(f"\n===== 文件：{raw_name} =====\n{extracted or '[空内容]'}")
        accepted_files.append(raw_name)

    if not accepted_files:
        return jsonify({"success": False, "error": "未上传有效文件（仅支持 pdf/doc/docx/png）"}), 400

    merged = "\n".join(snippets).strip()
    return jsonify({
        "success": True,
        "files": accepted_files,
        "corpus_text": merged,
        "corpus_chars": len(merged)
    })


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
    corpus_text = data.get('corpus_text', '')
    
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
    global role_manager, workflow_engine, workflow_cancel_event
    workflow_cancel_event = Event()
    role_manager = RoleManager(str(temp_config_path))
    workflow_engine = WorkflowEngineV2(role_manager, socketio, workflow_cancel_event)
    
    # 在后台线程中执行工作流
    socketio.start_background_task(
        target=workflow_engine.execute_collaborative_workflow,
        topic=topic,
        mode=mode,
        corpus_text=corpus_text
    )
    
    return jsonify({"success": True, "message": "工作流已启动"})


@app.route('/api/stop_workflow', methods=['POST'])
def stop_workflow():
    """中止当前工作流任务。"""
    global workflow_engine
    if not workflow_engine:
        return jsonify({"success": False, "error": "当前没有正在运行的任务"}), 400

    workflow_engine.request_stop()
    return jsonify({"success": True, "message": "已发送中止信号"})


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
