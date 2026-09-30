# -*- coding: utf-8 -*-
"""study 里接的自有工具集合。

每个模块封装一个业务能力，供 agent 与课件复用：

- :mod:`tools.wenshu_tool` —— hgt-2 问数（scope → 平台配置 → cbb），
  见第 3 章 `chapters/03-custom-tool.md`。
"""
from .wenshu_tool import SCOPE_TO_SCENE, WenshuQueryTool

__all__ = ["WenshuQueryTool", "SCOPE_TO_SCENE"]
