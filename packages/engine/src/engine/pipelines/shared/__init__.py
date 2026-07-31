"""跨 pipeline 组共享的基础设施（browser 生命周期、并发日志、LLM 客户端）。

仅供 engine.pipelines 下各 pipeline 组使用；registry discovery 跳过 .shared. 模块。
"""
