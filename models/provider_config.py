"""AI Provider 配置数据模型 - 按供应商 + Key 类型组织"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ModelInfo:
    """模型信息"""
    id: str           # 模型 ID，如 "kimi-k2.5"
    name: str         # 显示名称
    ref: str          # 完整 model ref，如 "moonshot/kimi-k2.5"
    reasoning: bool = False


@dataclass
class KeyTypeInfo:
    """同一个供应商下的不同 API Key 类型"""
    key: str                  # 内部标识，如 "standard"
    label: str                # 显示标签，如 "标准 API"
    env_var: str              # 环境变量名
    fallback_env_var: Optional[str] = None
    base_url: Optional[str] = None      # 特殊 baseUrl（可选，大多数不需要）
    auth_choice: Optional[str] = None   # onboard auth choice
    model_prefix: str = ""      # model ref 前缀提示
    models: List[ModelInfo] = field(default_factory=list)


@dataclass
class VendorInfo:
    """供应商信息"""
    id: str                   # 内部标识
    name: str                 # 显示名称
    icon: str = ""
    key_types: List[KeyTypeInfo] = field(default_factory=list)


# ============================================================
# 供应商配置（来自 openclaw-cn 源码）
# ============================================================

VENDOR_REGISTRY: List[VendorInfo] = [
    VendorInfo(
        id="kimi",
        name="Kimi (Moonshot)",
        key_types=[
            KeyTypeInfo(
                key="standard",
                label="标准 API Key",
                env_var="MOONSHOT_API_KEY",
                base_url="https://api.moonshot.cn/v1",
                auth_choice="moonshot-api-key-cn",
                model_prefix="moonshot/",
                models=[
                    ModelInfo("kimi-k2.6", "Kimi K2.6", "moonshot/kimi-k2.6"),
                    ModelInfo("kimi-k2.5", "Kimi K2.5", "moonshot/kimi-k2.5"),
                    ModelInfo("kimi-k2-thinking", "Kimi K2 Thinking", "moonshot/kimi-k2-thinking", reasoning=True),
                    ModelInfo("kimi-k2-turbo", "Kimi K2 Turbo", "moonshot/kimi-k2-turbo"),
                    ModelInfo("kimi-k2-thinking-turbo", "Kimi K2 Thinking Turbo", "moonshot/kimi-k2-thinking-turbo", reasoning=True),
                ],
            ),
            KeyTypeInfo(
                key="coding",
                label="Kimi Coding API Key",
                env_var="KIMI_API_KEY",
                fallback_env_var="KIMICODE_API_KEY",
                base_url="https://api.kimi.com/coding/",
                auth_choice="kimi-code-api-key",
                model_prefix="",
                models=[
                    ModelInfo("kimi-for-coding", "Kimi for Coding", "kimi-for-coding"),
                ],
            ),
        ],
    ),
    VendorInfo(
        id="deepseek",
        name="DeepSeek",
        key_types=[
            KeyTypeInfo(
                key="standard",
                label="API Key",
                env_var="DEEPSEEK_API_KEY",
                base_url="https://api.deepseek.com",
                auth_choice="deepseek-api-key",
                model_prefix="deepseek/",
                models=[
                    ModelInfo("deepseek-v4-pro", "DeepSeek V4 Pro", "deepseek/deepseek-v4-pro"),
                    ModelInfo("deepseek-v4-flash", "DeepSeek V4 Flash", "deepseek/deepseek-v4-flash"),
                ],
            ),
        ],
    ),
    VendorInfo(
        id="minimax",
        name="MiniMax",
        key_types=[
            KeyTypeInfo(
                key="standard",
                label="API Key",
                env_var="MINIMAX_API_KEY",
                base_url="https://api.minimaxi.com/anthropic",
                auth_choice="minimax-api-key-cn",
                model_prefix="minimax/",
                models=[
                    ModelInfo("MiniMax-M2.1", "MiniMax M2.1", "minimax/MiniMax-M2.1"),
                    ModelInfo("MiniMax-M2.1-lightning", "MiniMax M2.1 Lightning", "minimax/MiniMax-M2.1-lightning"),
                    ModelInfo("MiniMax-VL-01", "MiniMax VL 01", "minimax/MiniMax-VL-01"),
                    ModelInfo("MiniMax-M2.5", "MiniMax M2.5", "minimax/MiniMax-M2.5", reasoning=True),
                    ModelInfo("MiniMax-M2.5-Lightning", "MiniMax M2.5 Lightning", "minimax/MiniMax-M2.5-Lightning", reasoning=True),
                ],
            ),
        ],
    ),
    VendorInfo(
        id="volcengine",
        name="Volcano Engine (豆包)",
        key_types=[
            KeyTypeInfo(
                key="standard",
                label="标准 API Key (按量付费)",
                env_var="VOLCANO_ENGINE_API_KEY",
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                auth_choice="volcengine-api-key-cn",
                model_prefix="volcengine/",
                models=[
                    ModelInfo("doubao-seed-1-8-251228", "Doubao Seed 1.8", "volcengine/doubao-seed-1-8-251228"),
                    ModelInfo("doubao-seed-code-preview-251028", "Doubao Seed Code Preview", "volcengine/doubao-seed-code-preview-251028"),
                    ModelInfo("deepseek-v3-2-251201", "DeepSeek V3.2", "volcengine/deepseek-v3-2-251201"),
                    ModelInfo("glm-4-7-251222", "GLM 4.7", "volcengine/glm-4-7-251222"),
                    ModelInfo("kimi-k2-5-260127", "Kimi K2.5", "volcengine/kimi-k2-5-260127"),
                ],
            ),
            KeyTypeInfo(
                key="coding",
                label="Coding Plan API Key (订阅)",
                env_var="VOLCANO_ENGINE_API_KEY",
                base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
                model_prefix="volcengine-plan/",
                models=[
                    ModelInfo("ark-code-latest", "Ark Coding Plan", "volcengine-plan/ark-code-latest"),
                    ModelInfo("doubao-seed-code", "Doubao Seed Code", "volcengine-plan/doubao-seed-code"),
                    ModelInfo("doubao-seed-code-preview-251028", "Doubao Seed Code Preview", "volcengine-plan/doubao-seed-code-preview-251028"),
                    ModelInfo("glm-4.7", "GLM 4.7 Coding", "volcengine-plan/glm-4.7"),
                    ModelInfo("kimi-k2-thinking", "Kimi K2 Thinking", "volcengine-plan/kimi-k2-thinking"),
                    ModelInfo("kimi-k2.5", "Kimi K2.5 Coding", "volcengine-plan/kimi-k2.5"),
                ],
            ),
        ],
    ),
    VendorInfo(
        id="openrouter",
        name="OpenRouter",
        key_types=[
            KeyTypeInfo(
                key="standard",
                label="API Key",
                env_var="OPENROUTER_API_KEY",
                base_url="https://openrouter.ai/api/v1",
                auth_choice="openrouter-api-key",
                model_prefix="openrouter/",
                models=[],  # OpenRouter 模型太多且不固定，不提供硬编码列表
            ),
        ],
    ),
    VendorInfo(
        id="zai",
        name="Z.AI (智谱 GLM)",
        key_types=[
            KeyTypeInfo(
                key="standard",
                label="通用 API Key",
                env_var="ZAI_API_KEY",
                fallback_env_var="Z_AI_API_KEY",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                auth_choice="zai-api-key-cn",
                model_prefix="zai/",
                models=[
                    ModelInfo("glm-4.5", "GLM 4.5", "zai/glm-4.5"),
                    ModelInfo("glm-4.5-air", "GLM 4.5 Air", "zai/glm-4.5-air"),
                    ModelInfo("glm-4.5-flash", "GLM 4.5 Flash", "zai/glm-4.5-flash"),
                    ModelInfo("glm-4.5v", "GLM 4.5V", "zai/glm-4.5v"),
                    ModelInfo("glm-4.6", "GLM 4.6", "zai/glm-4.6"),
                    ModelInfo("glm-4.6v", "GLM 4.6V", "zai/glm-4.6v"),
                    ModelInfo("glm-4.7", "GLM 4.7", "zai/glm-4.7", reasoning=True),
                    ModelInfo("glm-4.7-flash", "GLM 4.7 Flash", "zai/glm-4.7-flash", reasoning=True),
                    ModelInfo("glm-4.7-flashx", "GLM 4.7 FlashX", "zai/glm-4.7-flashx", reasoning=True),
                    ModelInfo("glm-5", "GLM-5", "zai/glm-5", reasoning=True),
                ],
            ),
            KeyTypeInfo(
                key="coding",
                label="Coding Plan API Key",
                env_var="ZAI_API_KEY",
                fallback_env_var="Z_AI_API_KEY",
                base_url="https://open.bigmodel.cn/api/coding/paas/v4",
                auth_choice="zai-coding-api-key-cn",
                model_prefix="zai/",
                models=[
                    ModelInfo("glm-4.5", "GLM 4.5", "zai/glm-4.5"),
                    ModelInfo("glm-4.5-air", "GLM 4.5 Air", "zai/glm-4.5-air"),
                    ModelInfo("glm-4.5-flash", "GLM 4.5 Flash", "zai/glm-4.5-flash"),
                    ModelInfo("glm-4.5v", "GLM 4.5V", "zai/glm-4.5v"),
                    ModelInfo("glm-4.6", "GLM 4.6", "zai/glm-4.6"),
                    ModelInfo("glm-4.6v", "GLM 4.6V", "zai/glm-4.6v"),
                    ModelInfo("glm-4.7", "GLM 4.7", "zai/glm-4.7", reasoning=True),
                    ModelInfo("glm-4.7-flash", "GLM 4.7 Flash", "zai/glm-4.7-flash", reasoning=True),
                    ModelInfo("glm-4.7-flashx", "GLM 4.7 FlashX", "zai/glm-4.7-flashx", reasoning=True),
                    ModelInfo("glm-5", "GLM-5", "zai/glm-5", reasoning=True),
                ],
            ),
        ],
    ),
    VendorInfo(
        id="xiaomi",
        name="Xiaomi (MiMo)",
        key_types=[
            KeyTypeInfo(
                key="standard",
                label="API Key",
                env_var="XIAOMI_API_KEY",
                base_url="https://api.xiaomimimo.com/anthropic",
                auth_choice="xiaomi-api-key",
                model_prefix="xiaomi/",
                models=[
                    ModelInfo("mimo-v2-flash", "MiMo V2 Flash", "xiaomi/mimo-v2-flash"),
                ],
            ),
        ],
    ),
    VendorInfo(
        id="aliyun",
        name="阿里云百炼",
        key_types=[
            KeyTypeInfo(
                key="standard",
                label="DashScope API Key (按量付费)",
                env_var="DASHSCOPE_API_KEY",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model_prefix="dashscope/",
                models=[
                    ModelInfo("qwen-coder-plus", "Qwen Coder Plus", "dashscope/qwen-coder-plus"),
                    ModelInfo("qwen-coder-plus-latest", "Qwen Coder Plus (Latest)", "dashscope/qwen-coder-plus-latest"),
                    ModelInfo("qwen-max", "Qwen Max", "dashscope/qwen-max"),
                    ModelInfo("qwen-max-latest", "Qwen Max (Latest)", "dashscope/qwen-max-latest"),
                    ModelInfo("qwen-plus", "Qwen Plus", "dashscope/qwen-plus"),
                    ModelInfo("qwen-plus-latest", "Qwen Plus (Latest)", "dashscope/qwen-plus-latest"),
                    ModelInfo("qwen-turbo", "Qwen Turbo", "dashscope/qwen-turbo"),
                    ModelInfo("qwen-turbo-latest", "Qwen Turbo (Latest)", "dashscope/qwen-turbo-latest"),
                ],
            ),
            KeyTypeInfo(
                key="coding",
                label="Coding Plan API Key (订阅)",
                env_var="DASHSCOPE_CODING_API_KEY",
                base_url="https://coding.dashscope.aliyuncs.com/v1",
                model_prefix="aliyun-coding/",
                models=[
                    ModelInfo("qwen3.5-plus", "Qwen 3.5 Plus", "aliyun-coding/qwen3.5-plus"),
                    ModelInfo("qwen3-max", "Qwen 3 Max", "aliyun-coding/qwen3-max"),
                    ModelInfo("qwen3-coder-next", "Qwen 3 Coder Next", "aliyun-coding/qwen3-coder-next"),
                    ModelInfo("qwen3-coder-plus", "Qwen 3 Coder Plus", "aliyun-coding/qwen3-coder-plus"),
                    ModelInfo("minimax-m2.5", "MiniMax M2.5", "aliyun-coding/minimax-m2.5"),
                    ModelInfo("glm-5", "GLM-5", "aliyun-coding/glm-5"),
                    ModelInfo("kimi-k2.5", "Kimi K2.5", "aliyun-coding/kimi-k2.5"),
                    ModelInfo("glm-4.7", "GLM-4.7", "aliyun-coding/glm-4.7"),
                ],
            ),
        ],
    ),

]


def get_vendor_by_id(vendor_id: str) -> Optional[VendorInfo]:
    for v in VENDOR_REGISTRY:
        if v.id == vendor_id:
            return v
    return None


def get_key_type(vendor_id: str, key_type_key: str) -> Optional[KeyTypeInfo]:
    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        return None
    for kt in vendor.key_types:
        if kt.key == key_type_key:
            return kt
    return None
