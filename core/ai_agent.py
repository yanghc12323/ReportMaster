# -*- coding: utf-8 -*-
"""
AI代理模块
定义AI代理的基类和行为
"""

from typing import Dict, Any, Optional
from utils.api_client import APIClient
import logging

logger = logging.getLogger(__name__)


class AIAgent:
    """AI代理基类，代表一个具有特定职能的AI员工"""
    
    def __init__(self, role_name: str, role_config: Dict[str, Any]):
        """
        初始化AI代理
        
        Args:
            role_name: 角色名称
            role_config: 角色配置字典
        """
        self.role_name = role_name
        self.description = role_config.get("description", "")
        self.system_prompt = role_config.get("system_prompt", "")
        
        # 初始化API客户端
        api_config = role_config.get("api_config") or {}
        api_type = api_config.get("api_type", "openai")
        default_base_url = "https://api.openai.com/v1" if api_type.lower() == "openai" else ""
        
        # 验证配置
        if not api_config.get("api_key") or api_config.get("api_key") == "your-api-key-here":
            logger.warning(f"{role_name}: API密钥未配置或使用默认值")
        
        self.client = APIClient(
            api_type=api_type,
            api_key=api_config.get("api_key", ""),
            base_url=api_config.get("base_url", default_base_url),
            model=api_config.get("model", "")
        )
        self.last_meta: Dict[str, Any] = {}
        
        # API调用参数
        self.api_params = role_config.get("api_params") or {}

        # 兼容旧配置：temperature / max_tokens 可能写在 api_config 中
        if "temperature" not in self.api_params and isinstance(api_config.get("temperature"), (int, float)):
            self.api_params["temperature"] = api_config.get("temperature")
        if "max_tokens" not in self.api_params and isinstance(api_config.get("max_tokens"), int):
            self.api_params["max_tokens"] = api_config.get("max_tokens")
        
        logger.info(f"初始化AI代理: {role_name}")
    
    def execute(self, task: str, context: str = "") -> str:
        """
        执行任务
        
        Args:
            task: 任务描述
            context: 上下文信息
            
        Returns:
            执行结果
        """
        logger.info(f"{self.role_name} 开始执行任务")
        
        # 构建完整提示词
        prompt = self._build_prompt(task, context)
        
        # 调用API
        try:
            result = self.client.call(
                prompt=prompt,
                system_prompt=self.system_prompt,
                **self.api_params
            )
            self.last_meta = self.client.get_last_meta()
            logger.info(f"{self.role_name} 任务完成，输出长度: {len(result)}")
            return result
        except Exception as e:
            self.last_meta = self.client.get_last_meta()
            error_msg = f"[错误] {self.role_name}执行失败: {str(e)}"
            logger.error(error_msg)
            return error_msg
    
    def _build_prompt(self, task: str, context: str) -> str:
        """构建提示词"""
        if context:
            return f"上下文信息：\n{context}\n\n任务：\n{task}"
        return task
    
    def __str__(self) -> str:
        return f"AIAgent({self.role_name}): {self.description}"
