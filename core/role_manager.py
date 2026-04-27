"""
角色管理器模块
负责加载和管理所有AI角色
"""

import json
from typing import Dict, List
from pathlib import Path
from core.ai_agent import AIAgent


class RoleManager:
    """角色管理器，负责管理所有AI代理"""
    
    def __init__(self, config_path: str = "config/roles.json"):
        """
        初始化角色管理器
        
        Args:
            config_path: 角色配置文件路径
        """
        self.config_path = config_path
        self.agents: Dict[str, AIAgent] = {}
        self._load_roles()
    
    def _load_roles(self):
        """从配置文件加载角色"""
        config_file = Path(self.config_path)
        
        if not config_file.exists():
            print(f"警告: 配置文件 {self.config_path} 不存在，使用空配置")
            return
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                roles_config = json.load(f)
            
            for role_name, role_config in roles_config.items():
                self.agents[role_name] = AIAgent(role_name, role_config)
            
            print(f"成功加载 {len(self.agents)} 个角色")
        except Exception as e:
            print(f"加载角色配置失败: {str(e)}")
    
    def get_agent(self, role_name: str) -> AIAgent:
        """
        获取指定角色的代理
        
        Args:
            role_name: 角色名称
            
        Returns:
            AI代理实例
        """
        if role_name not in self.agents:
            raise ValueError(f"角色 '{role_name}' 不存在")
        return self.agents[role_name]
    
    def list_roles(self) -> List[str]:
        """列出所有可用角色"""
        return list(self.agents.keys())
    
    def add_role(self, role_name: str, role_config: Dict):
        """
        动态添加角色
        
        Args:
            role_name: 角色名称
            role_config: 角色配置
        """
        self.agents[role_name] = AIAgent(role_name, role_config)
    
    def remove_role(self, role_name: str):
        """删除角色"""
        if role_name in self.agents:
            del self.agents[role_name]
