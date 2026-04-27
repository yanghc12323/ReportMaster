# -*- coding: utf-8 -*-
"""
API客户端模块
负责与各种AI服务API进行通信
"""

import requests
import json
from typing import Dict, Any, Optional
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class APIClient:
    """通用API客户端，支持多种AI服务"""
    
    def __init__(self, api_type: str, api_key: str, base_url: str, model: str = ""):
        """
        初始化API客户端
        
        Args:
            api_type: API类型（openai, claude, custom等）
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称
        """
        self.api_type = api_type.lower()
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.last_meta: Dict[str, Any] = {}
        
        logger.info(f"初始化API客户端: type={api_type}, base_url={base_url}, model={model}")

    def get_last_meta(self) -> Dict[str, Any]:
        """获取最近一次调用的元信息。"""
        return dict(self.last_meta)
    
    def call(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        """
        调用AI API
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            **kwargs: 其他参数（temperature, max_tokens等）
            
        Returns:
            AI响应文本
        """
        logger.info(f"调用API: type={self.api_type}, prompt_length={len(prompt)}")
        self.last_meta = {}
        
        try:
            if self.api_type == "openai":
                return self._call_openai(prompt, system_prompt, **kwargs)
            elif self.api_type == "claude":
                return self._call_claude(prompt, system_prompt, **kwargs)
            else:
                return self._call_custom(prompt, system_prompt, **kwargs)
        except Exception as e:
            logger.error(f"API调用失败: {str(e)}", exc_info=True)
            raise
    
    def _call_openai(self, prompt: str, system_prompt: str, **kwargs) -> str:
        """调用OpenAI兼容API（包括DeepSeek等）"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2000)
        }
        
        url = f"{self.base_url}/chat/completions"
        logger.info(f"请求URL: {url}")
        logger.info(f"请求数据: model={self.model}, messages_count={len(messages)}, temperature={data['temperature']}")
        
        result = {}
        try:
            response = requests.post(
                url,
                headers=headers,
                json=data,
                timeout=120  # 增加超时时间到120秒
            )
            
            logger.info(f"响应状态码: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"API错误响应: {response.text}")
                response.raise_for_status()
            
            result = response.json()
            choices = result.get("choices") or []
            if not choices:
                raise Exception(f"API响应缺少 choices 字段: {result}")

            choice = choices[0] or {}
            message = choice.get("message") or {}
            content = message.get("content", "")

            if isinstance(content, list):
                # 兼容部分多模态返回结构
                content = "".join(
                    (block.get("text", "") if isinstance(block, dict) else str(block))
                    for block in content
                )

            finish_reason = choice.get("finish_reason")
            usage = result.get("usage") or {}
            self.last_meta = {
                "provider": "openai",
                "finish_reason": finish_reason,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "truncated": finish_reason == "length"
            }

            logger.info(f"API调用成功，响应长度: {len(content)}")
            
            return content
            
        except requests.exceptions.Timeout:
            logger.error("API请求超时")
            raise Exception("API请求超时，请检查网络连接或稍后重试")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"API连接失败: {str(e)}")
            raise Exception(f"无法连接到API服务器，请检查base_url配置和网络连接: {str(e)}")
        except KeyError as e:
            logger.error(f"API响应格式错误: {e}, 响应内容: {result}")
            raise Exception(f"API响应格式不正确: {str(e)}")
        except Exception as e:
            logger.error(f"未知错误: {str(e)}")
            raise
    
    def _call_claude(self, prompt: str, system_prompt: str, **kwargs) -> str:
        """调用Claude API"""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_tokens", 2000)
        }
        
        if system_prompt:
            data["system"] = system_prompt
        
        url = f"{self.base_url}/messages"
        logger.info(f"请求Claude API: {url}")
        
        result = {}
        try:
            response = requests.post(
                url,
                headers=headers,
                json=data,
                timeout=120
            )
            
            logger.info(f"响应状态码: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"API错误响应: {response.text}")
                response.raise_for_status()
            
            result = response.json()
            content_blocks = result.get("content") or []
            if not content_blocks:
                raise Exception(f"Claude响应缺少 content 字段: {result}")

            first_block = content_blocks[0] or {}
            content = first_block.get("text", "")

            stop_reason = result.get("stop_reason")
            usage = result.get("usage") or {}
            self.last_meta = {
                "provider": "claude",
                "finish_reason": stop_reason,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "truncated": stop_reason in ("max_tokens", "model_context_window_exceeded")
            }

            logger.info(f"Claude API调用成功，响应长度: {len(content)}")
            
            return content
            
        except Exception as e:
            logger.error(f"Claude API调用失败: {str(e)}")
            raise
    
    def _call_custom(self, prompt: str, system_prompt: str, **kwargs) -> str:
        """调用自定义API（需要用户自行适配）"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            **kwargs
        }
        
        logger.info(f"请求自定义API: {self.base_url}")
        
        result = {}
        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=data,
                timeout=120
            )
            
            logger.info(f"响应状态码: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"API错误响应: {response.text}")
                response.raise_for_status()
            
            result = response.json()
            content = result.get("response", "") or result.get("content", "")

            self.last_meta = {
                "provider": "custom",
                "finish_reason": result.get("finish_reason"),
                "truncated": bool(result.get("truncated", False))
            }

            logger.info(f"自定义API调用成功，响应长度: {len(content)}")
            
            return content
            
        except Exception as e:
            logger.error(f"自定义API调用失败: {str(e)}")
            raise
