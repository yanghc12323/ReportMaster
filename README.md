# Report Master v0.6

面向中国大学生的多 AI 协作报告/论文写作工具。

> 核心思路：把不同 AI 当成不同岗位的“员工”（结构规划者、调研者、主笔人、编辑、审稿人），通过固定协作链路和审稿闭环，提升生成效率与可控性。

---

## ✨ v0.6 核心能力

### 1) 五角色协作 + 审稿闭环（直到接收）

```text
结构规划者 → 调研者 → 主笔人 → 编辑 → 审稿人
      ↑                                   ↓
      └────────── 大修回路（重做主链）───────┘
                          小修回路（编辑修订后再次送审）
```

- 审稿结论标准化为：`大修 / 小修 / 接收`
- 若审稿输出“拒稿/不接收”，系统自动按**大修**处理，保证流程不中断
- v0.6 所有模式均采用**无限迭代，直到审稿接收**

### 2) 输出可靠性增强（防截断/防上下文溢出）

- 对超长任务与上下文自动“中段压缩”并推送风险提示
- 检测到模型 `finish_reason` 为长度截断时，自动续写一次并拼接
- 前端实时展示 `output_warning`（风险信息 + 建议 + 元数据）

### 3) Word 风格实时稿件面板

- 实时接收 `manuscript_update` 阶段稿（初稿/编辑稿/小修稿/终稿）
- 可在前端直接编辑并“保存到当前稿件”
- 支持基础格式操作（字体、字号、加粗、列表、对齐）

### 4) 导出能力完善

- TXT 导出
- DOC 导出（HTML 包装）
- PDF 导出（html2pdf）

---

## 🏗️ 项目结构

```text
report master/
├── backend/
│   ├── __init__.py
│   └── app.py               # Flask + Socket.IO 服务
├── core/
│   ├── __init__.py
│   ├── ai_agent.py          # AI 角色代理
│   ├── role_manager.py      # 角色配置加载与管理
│   └── workflow.py          # 协作引擎（v0.6）
├── frontend/
│   ├── index.html           # 页面结构
│   ├── styles.css           # 样式
│   └── app.js               # 前端逻辑
├── config/
│   ├── roles.example.json   # 示例配置
│   └── roles.json           # 本地配置模板
├── utils/
│   ├── __init__.py
│   └── api_client.py        # 多模型 API 适配
├── requirements.txt
├── start.bat
└── TESTING.md
```

---

## 🚀 快速开始

### 1) 环境要求

- Python 3.8+
- 可访问的模型 API（OpenAI 兼容 / Claude / 自定义）

### 2) 安装依赖

```bash
pip install -r requirements.txt
```

### 3) 启动应用

Windows（推荐）：

```bash
start.bat
```

通用方式：

```bash
python backend/app.py
```

打开：`http://localhost:5000`

---

## ⚙️ 使用流程

1. 进入「配置管理」，为 5 个角色填写 API 信息与 Prompt
2. 回到「工作流」，输入主题并选择模式
3. 点击「开始生成」，观察角色状态与实时协作消息
4. 在 Word 页面查看/编辑阶段稿并保存到当前稿件
5. 完成后导出 TXT / DOC / PDF

---

## 📡 后端接口

- `GET /api/health`：健康检查（当前版本 `0.6`）
- `GET /api/roles`：读取角色信息
- `POST /api/roles`：保存角色配置
- `POST /api/start_workflow`：启动协作工作流
- `GET /api/workflow/history`：获取内存中的工作流历史

WebSocket 关键事件：

- `workflow_start`
- `iteration_start`
- `step_start` / `step_complete`
- `ai_message`
- `role_status`
- `manuscript_update`
- `output_warning`
- `workflow_complete` / `workflow_error`

---

## 🔐 安全说明（v0 原型）

- 配置与历史默认存储在浏览器 `localStorage`
- 当前更偏本地原型验证，不建议直接公网暴露
- 生产化建议补充：用户鉴权、服务端密钥托管、限流审计、持久化存储
