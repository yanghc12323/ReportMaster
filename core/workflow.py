# -*- coding: utf-8 -*-
"""
工作流引擎V2

v0.6 更新重点：
1. 所有模式均采用“直到审稿人接收”为止的无限迭代
2. 修复小修后直接终止问题：编辑小修后必须再次交给审稿人
3. 保留完整消息与稿件阶段推送，支持前端 Word 页面实时预览
"""

from typing import Dict, Any, List, Tuple
import time
import logging
from threading import Event

from core.role_manager import RoleManager

logger = logging.getLogger(__name__)


class WorkflowCancelled(Exception):
    """工作流被用户中止时抛出的异常。"""


class WorkflowEngineV2:
    """支持多角色协作、审稿决策和多轮迭代的工作流引擎。"""

    # 上下文安全阈值（按字符近似控制，避免请求超大导致模型截断或报错）
    MAX_TASK_CHARS = 10000
    MAX_CONTEXT_CHARS = 30000

    def __init__(self, role_manager: RoleManager, socketio=None, cancel_event: Event = None):
        """
        初始化工作流引擎。

        Args:
            role_manager: 角色管理器
            socketio: SocketIO实例，用于向前端实时推送事件
        """
        self.role_manager = role_manager
        self.socketio = socketio
        self.conversation_history: List[Dict[str, Any]] = []
        self.iteration_count = 0
        self.last_output = ""
        self.cancel_event = cancel_event

    def request_stop(self):
        """请求中止当前任务。"""
        if self.cancel_event:
            self.cancel_event.set()

    def _check_cancelled(self):
        """在关键节点检查是否收到中止信号。"""
        if self.cancel_event and self.cancel_event.is_set():
            raise WorkflowCancelled("任务已被用户中止")

    # ----------------------------
    # 事件推送与基础能力
    # ----------------------------
    def _emit_message(self, event: str, data: Dict[str, Any]):
        """发送 WebSocket 消息。"""
        if self.socketio:
            self.socketio.emit(event, data)
            logger.info("发送消息: event=%s", event)
        else:
            logger.warning("SocketIO 未初始化，事件未发送: %s", event)

    def _emit_role_status(self, role: str, status: str, message: str = ""):
        """统一推送角色状态变更。"""
        payload = {"role": role, "status": status}
        if message:
            payload["message"] = message
        self._emit_message("role_status", payload)

    def _emit_manuscript_update(self, stage: str, role: str, content: str):
        """推送阶段性稿件内容（用于前端实时编辑器预览）。"""
        self._emit_message("manuscript_update", {
            "stage": stage,
            "role": role,
            "content": content,
            "iteration": self.iteration_count,
            "timestamp": time.time()
        })

    def _emit_output_warning(self, role: str, message: str, suggestion: str = "", meta: Dict[str, Any] = None):
        """推送输出风险提示（如 token 截断、上下文压缩等）。"""
        payload = {
            "role": role,
            "message": message,
            "suggestion": suggestion,
            "iteration": self.iteration_count,
            "timestamp": time.time()
        }
        if meta:
            payload["meta"] = meta
        self._emit_message("output_warning", payload)

    def _clip_text(self, role: str, field_name: str, text: str, max_chars: int) -> str:
        """对超长文本做中段压缩，降低上下文溢出概率。"""
        normalized = text if isinstance(text, str) else str(text)
        if len(normalized) <= max_chars:
            return normalized

        keep_head = max_chars // 2
        keep_tail = max_chars - keep_head
        omitted = len(normalized) - max_chars

        clipped = (
            f"{normalized[:keep_head]}\n\n"
            f"[...为避免模型上下文溢出，已省略中间约 {omitted} 字符...]\n\n"
            f"{normalized[-keep_tail:]}"
        )

        self._emit_output_warning(
            role=role,
            message=f"{field_name}过长，系统已自动压缩中间内容以提高稳定性。",
            suggestion="如需更完整上下文，可在配置页降低各角色 max_tokens 或缩小主题范围。",
            meta={"field": field_name, "original_chars": len(normalized), "clipped_chars": len(clipped)}
        )
        return clipped

    def _prepare_prompt_inputs(self, role: str, task: str, context: str = "") -> Tuple[str, str]:
        """在调用模型前做任务与上下文安全处理。"""
        safe_task = self._clip_text(role, "任务描述", task, self.MAX_TASK_CHARS)
        safe_context = self._clip_text(role, "上下文", context, self.MAX_CONTEXT_CHARS) if context else ""
        return safe_task, safe_context

    @staticmethod
    def _get_generation_meta(agent) -> Dict[str, Any]:
        """读取本次模型调用元信息，并标准化截断标记。"""
        raw_meta = getattr(agent, "last_meta", {}) or {}
        meta = dict(raw_meta)
        finish_reason = str(meta.get("finish_reason", "")).lower()
        meta["truncated"] = bool(meta.get("truncated")) or finish_reason in {
            "length",
            "max_tokens",
            "model_context_window_exceeded"
        }
        return meta

    def _execute_with_reliability(self, role: str, agent, task: str, context: str = "") -> str:
        """
        统一执行代理调用，并处理截断兜底逻辑。

        规则：
        1) 先做 task/context 长度保护
        2) 若检测到输出被截断，自动续写一次并拼接
        """
        self._check_cancelled()
        safe_task, safe_context = self._prepare_prompt_inputs(role, task, context)

        output = agent.execute(safe_task, safe_context)
        self._check_cancelled()
        self._validate_output(role, output)

        meta = self._get_generation_meta(agent)
        if not meta.get("truncated"):
            return output

        finish_reason = meta.get("finish_reason") or "unknown"
        self._emit_output_warning(
            role=role,
            message=f"检测到 {role} 输出可能因长度限制被截断（finish_reason={finish_reason}），系统将自动续写一次。",
            suggestion="建议适当提高该角色 max_tokens，或拆分任务减少单次输出压力。",
            meta=meta
        )

        continue_task = "你上一条输出可能因长度限制被截断。请在不重复已有内容的前提下继续补全剩余部分。"
        continue_context = f"原任务：\n{safe_task}\n\n已有内容（可能被截断）：\n{output}"
        safe_continue_task, safe_continue_context = self._prepare_prompt_inputs(role, continue_task, continue_context)

        continuation = agent.execute(safe_continue_task, safe_continue_context)
        self._check_cancelled()
        self._validate_output(role, continuation)
        merged_output = f"{output.rstrip()}\n\n{continuation.lstrip()}"

        second_meta = self._get_generation_meta(agent)
        if second_meta.get("truncated"):
            self._emit_output_warning(
                role=role,
                message=f"{role} 续写后仍可能未完整输出，请关注最终结果完整性。",
                suggestion="可继续提高 max_tokens，或在 Prompt 中要求分段输出。",
                meta=second_meta
            )
        else:
            self._emit_output_warning(
                role=role,
                message=f"{role} 已完成自动续写，输出完整性已提升。",
                suggestion="如质量仍不足，可在配置页细化该角色的 system prompt。",
                meta=second_meta
            )

        return merged_output

    def _send_message(self, from_role: str, to_role: str, message_type: str, content: str):
        """
        AI 角色之间发送消息并推送给前端。

        注意：v0.6 中仅对“模型入参上下文”做安全压缩；消息展示仍保留完整输出。
        """
        normalized_content = content if isinstance(content, str) else str(content)

        message = {
            "from": from_role,
            "to": to_role,
            "type": message_type,
            "content": normalized_content,
            "timestamp": time.time()
        }
        self.conversation_history.append(message)

        self._emit_message("ai_message", {
            "from": from_role,
            "to": to_role,
            "type": message_type,
            "content": normalized_content,
            "timestamp": message["timestamp"]
        })

        return message

    @staticmethod
    def _validate_output(role_name: str, content: str):
        """校验角色输出，避免空输出或错误字符串继续传递。"""
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"{role_name} 输出为空，请检查 API 配置或提示词")
        if content.strip().startswith("[错误]"):
            raise RuntimeError(content.strip())

    @staticmethod
    def _parse_review_decision(review: str) -> str:
        """
        将审稿意见映射为标准决策。

        返回值：major_revision / minor_revision / accept
        """
        normalized = review.replace(" ", "").replace("\n", "")

        if "拒稿" in normalized or "不接收" in normalized or "不接受" in normalized:
            # v0.6 仍要求流程可迭代推进，拒稿语义按大修兜底
            return "major_revision"
        if "大修" in normalized or "重大修改" in normalized:
            return "major_revision"
        if "小修" in normalized or "轻微修改" in normalized:
            return "minor_revision"
        if "接收" in normalized or "接受" in normalized or "录用" in normalized:
            return "accept"

        # 容错：若模型未严格按格式返回，默认小修（比直接接收更稳妥）
        return "minor_revision"

    @staticmethod
    def _decision_label(decision: str) -> str:
        """将标准决策转为中文标签。"""
        return {
            "major_revision": "大修",
            "minor_revision": "小修",
            "accept": "接收"
        }.get(decision, "未知")

    # ----------------------------
    # 主流程
    # ----------------------------
    def execute_collaborative_workflow(self, topic: str, mode: str = "standard", corpus_text: str = ""):
        """执行协作式工作流（v0.6：无限迭代直到审稿接收）。"""
        self.iteration_count = 1
        reviewer_feedback = ""
        final_content = ""
        current_manuscript = ""
        last_decision = ""
        review_result: Dict[str, Any] = {"decision": "minor_revision", "feedback": ""}

        self._emit_message("workflow_start", {
            "topic": topic,
            "mode": mode,
            "corpus_chars": len(corpus_text or ""),
            "max_iterations": "unlimited",
            "loop_strategy": "until_accept"
        })

        try:
            while True:
                self._check_cancelled()
                iteration_payload = {"iteration": self.iteration_count}
                if reviewer_feedback:
                    iteration_payload["reason"] = reviewer_feedback
                self._emit_message("iteration_start", iteration_payload)

                # 首轮 / 大修：走完整五角色链路
                if last_decision in ("", "major_revision"):
                    # 1) 结构规划者
                    outline = self._step_outline(topic, reviewer_feedback, corpus_text)

                    # 2) 调研者
                    research = self._step_research(outline)

                    # 3) 主笔人
                    draft = self._step_draft(outline, research)
                    self._emit_manuscript_update("初稿", "主笔人", draft)

                    # 4) 编辑
                    current_manuscript = self._step_edit(draft)
                    self._emit_manuscript_update("编辑稿", "编辑", current_manuscript)

                # 小修：编辑按审稿意见修订后，必须再次送审
                elif last_decision == "minor_revision":
                    current_manuscript = self._step_final_edit(current_manuscript, reviewer_feedback)
                    self._emit_manuscript_update("小修稿", "编辑", current_manuscript)

                # 5) 审稿人评审
                review_result = self._step_review(current_manuscript)
                last_decision = review_result.get("decision", "minor_revision")
                reviewer_feedback = review_result.get("feedback", "")

                if last_decision == "accept":
                    final_content = current_manuscript
                    self._emit_manuscript_update("终稿（审稿接收）", "编辑", final_content)
                    break

                # v0.6: 不设上限，继续迭代直到接收
                self.iteration_count += 1

            self.last_output = final_content

            # 兼容前端：同时返回 result 与 final_content
            self._emit_message("workflow_complete", {
                "result": final_content,
                "final_content": final_content,
                "iterations": self.iteration_count,
                "decision": review_result.get("decision", "minor_revision"),
                "decision_label": self._decision_label(review_result.get("decision", "minor_revision")),
                "review_feedback": review_result.get("feedback", "")
            })

        except WorkflowCancelled as exc:
            logger.info("工作流已中止: %s", exc)
            self._emit_message("workflow_cancelled", {
                "message": str(exc),
                "iterations": self.iteration_count
            })
        except Exception as exc:
            logger.exception("工作流执行失败")
            self._emit_message("workflow_error", {"error": str(exc)})

    # ----------------------------
    # 各步骤实现
    # ----------------------------
    def _step_outline(self, topic: str, feedback: str = "", corpus_text: str = "") -> str:
        """步骤1：结构规划。"""
        role_name = "结构规划者"
        self._emit_message("step_start", {"step": "outline", "role": role_name})
        self._emit_role_status(role_name, "working", "规划中")

        planner = self.role_manager.get_agent(role_name)
        task = f"请为以下主题设计详细、可落地的文章大纲：\n{topic}"
        if corpus_text.strip():
            task += f"\n\n以下是用户提供的语料，请优先吸收其中信息并在大纲中体现：\n{corpus_text}"
        if feedback:
            task += f"\n\n审稿人反馈如下，请据此重构大纲：\n{feedback}"

        try:
            outline = self._execute_with_reliability(role_name, planner, task)
            self._validate_output(role_name, outline)
            self._send_message(role_name, "调研者", "outline", outline)
            self._emit_message("step_complete", {"step": "outline"})
            self._emit_role_status(role_name, "completed", "已完成")
            return outline
        except Exception as exc:
            self._emit_role_status(role_name, "error", str(exc))
            raise

    def _step_research(self, outline: str) -> str:
        """步骤2：调研。"""
        role_name = "调研者"
        self._emit_message("step_start", {"step": "research", "role": role_name})
        self._emit_role_status(role_name, "working", "调研中")

        researcher = self.role_manager.get_agent(role_name)
        task = "请根据以下大纲进行调研，补充关键论据、案例、数据与参考资料建议。"

        try:
            research = self._execute_with_reliability(role_name, researcher, task, outline)
            self._validate_output(role_name, research)
            self._send_message(role_name, "主笔人", "research", research)
            self._emit_message("step_complete", {"step": "research"})
            self._emit_role_status(role_name, "completed", "已完成")
            return research
        except Exception as exc:
            self._emit_role_status(role_name, "error", str(exc))
            raise

    def _step_draft(self, outline: str, research: str) -> str:
        """步骤3：主笔人撰写初稿。"""
        role_name = "主笔人"
        self._emit_message("step_start", {"step": "draft", "role": role_name})
        self._emit_role_status(role_name, "working", "写作中")

        writer = self.role_manager.get_agent(role_name)
        context = f"大纲：\n{outline}\n\n调研资料：\n{research}"
        task = "请根据大纲和调研资料，输出结构完整、论证清晰的报告初稿。"

        try:
            draft = self._execute_with_reliability(role_name, writer, task, context)
            self._validate_output(role_name, draft)
            self._send_message(role_name, "编辑", "draft", draft)
            self._emit_message("step_complete", {"step": "draft"})
            self._emit_role_status(role_name, "completed", "已完成")
            return draft
        except Exception as exc:
            self._emit_role_status(role_name, "error", str(exc))
            raise

    def _step_edit(self, draft: str) -> str:
        """步骤4：编辑润色。"""
        role_name = "编辑"
        self._emit_message("step_start", {"step": "edit", "role": role_name})
        self._emit_role_status(role_name, "working", "润色中")

        editor = self.role_manager.get_agent(role_name)
        task = "请对以下文章进行润色与结构优化，提升可读性和学术表达规范性。"

        try:
            edited = self._execute_with_reliability(role_name, editor, task, draft)
            self._validate_output(role_name, edited)
            self._send_message(role_name, "审稿人", "edited", edited)
            self._emit_message("step_complete", {"step": "edit"})
            self._emit_role_status(role_name, "completed", "已完成")
            return edited
        except Exception as exc:
            self._emit_role_status(role_name, "error", str(exc))
            raise

    def _step_review(self, content: str) -> Dict[str, Any]:
        """步骤5：审稿人评审并给出大修/小修/接收。"""
        role_name = "审稿人"
        self._emit_message("step_start", {"step": "review", "role": role_name})
        self._emit_role_status(role_name, "working", "评审中")

        reviewer = self.role_manager.get_agent(role_name)
        task = """
请审查以下文章，并严格按以下格式输出：

【评审决定】：大修 / 小修 / 接收（只能三选一）
【具体反馈】：请给出可执行的修改建议。

注意：不要输出“拒稿”，必须在“大修 / 小修 / 接收”中选择。
""".strip()

        try:
            review = self._execute_with_reliability(role_name, reviewer, task, content)
            self._validate_output(role_name, review)

            normalized_review = review.replace(" ", "").replace("\n", "")
            explicit_markers = ("大修", "重大修改", "小修", "轻微修改", "接收", "接受", "录用", "拒稿", "不接收", "不接受")
            if not any(marker in normalized_review for marker in explicit_markers):
                self._emit_output_warning(
                    role=role_name,
                    message="审稿输出未明确包含“大修/小修/接收”，系统已按“小修”兜底以继续迭代。",
                    suggestion="建议强化审稿人 prompt 的格式约束，确保输出固定决策字段。"
                )
            elif any(marker in normalized_review for marker in ("拒稿", "不接收", "不接受")):
                self._emit_output_warning(
                    role=role_name,
                    message="检测到“拒稿/不接收”语义，系统已按“大修”处理并继续迭代。",
                    suggestion="如需严格避免此类词汇，可在审稿人 prompt 中进一步限制表达。"
                )

            decision = self._parse_review_decision(review)
            decision_label = self._decision_label(decision)

            result = {
                "decision": decision,
                "feedback": review
            }

            if decision == "major_revision":
                self._send_message(role_name, "结构规划者", "review_feedback", review)
            elif decision == "minor_revision":
                self._send_message(role_name, "编辑", "review_feedback", review)
            else:
                self._send_message(role_name, "系统", "review_feedback", review)

            self._emit_message("step_complete", {
                "step": "review",
                "decision": decision,
                "decision_label": decision_label
            })
            self._emit_role_status(role_name, "completed", f"评审：{decision_label}")
            return result

        except Exception as exc:
            self._emit_role_status(role_name, "error", str(exc))
            raise

    def _step_final_edit(self, content: str, feedback: str) -> str:
        """步骤6：小修场景下按审稿意见修订。"""
        role_name = "编辑"
        self._emit_message("step_start", {"step": "final_edit", "role": role_name})
        self._emit_role_status(role_name, "working", "按审稿意见修订")

        editor = self.role_manager.get_agent(role_name)
        context = f"审稿人反馈：\n{feedback}\n\n文章内容：\n{content}"
        task = "请根据审稿意见完成小修，保持核心结构不变并输出修订稿。"

        try:
            final = self._execute_with_reliability(role_name, editor, task, context)
            self._validate_output(role_name, final)
            self._send_message(role_name, "审稿人", "minor_revised", final)
            self._emit_message("step_complete", {"step": "final_edit"})
            self._emit_role_status(role_name, "completed", "小修稿已完成")
            return final
        except Exception as exc:
            self._emit_role_status(role_name, "error", str(exc))
            raise

    def get_history(self) -> List[Dict[str, Any]]:
        """获取对话历史。"""
        return self.conversation_history
