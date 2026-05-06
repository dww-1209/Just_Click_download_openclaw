"""OpenClaw Installer 测试包

职责：存放各层级的单元测试，验证接口契约、数据模型和纯逻辑函数。

设计原则：
- 不涉及真实 subprocess、文件系统或网络 IO 的测试。
- 对 IO 依赖使用 mock/接口替换。
"""
