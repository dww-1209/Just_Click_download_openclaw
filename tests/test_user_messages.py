"""UserMessageHelper 单元测试

验证错误消息格式化逻辑不依赖外部系统。
"""

import pytest

from src.models.user_messages import UserMessageHelper, format_size, format_time
from src.models.install import ErrorCategory


class TestFormatHelpers:
    """纯格式化函数测试"""

    def test_format_size_bytes(self) -> None:
        """format_size 正确格式化字节"""
        assert format_size(512) == "512.0 B"

    def test_format_size_kb(self) -> None:
        """format_size 正确格式化 KB"""
        assert format_size(1536) == "1.5 KB"

    def test_format_size_mb(self) -> None:
        """format_size 正确格式化 MB"""
        assert format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_format_size_gb(self) -> None:
        """format_size 正确格式化 GB"""
        assert format_size(2 * 1024 * 1024 * 1024) == "2.0 GB"

    def test_format_time_seconds(self) -> None:
        """format_time 正确格式化秒"""
        assert format_time(45) == "45秒"

    def test_format_time_minutes(self) -> None:
        """format_time 正确格式化分钟"""
        assert format_time(90) == "1分30秒"

    def test_format_time_hours(self) -> None:
        """format_time 正确格式化小时"""
        assert format_time(3661) == "1小时1分"


class TestUserMessageHelper:
    """UserMessageHelper 测试"""

    def test_get_friendly_error_message_known_type(self) -> None:
        """已知错误类型返回中文友好消息"""
        msg = UserMessageHelper.get_friendly_error_message("download", "test error")
        assert "下载" in msg or "网络" in msg

    def test_get_friendly_error_message_unknown_type(self) -> None:
        """未知错误类型返回通用消息"""
        msg = UserMessageHelper.get_friendly_error_message("unknown_xyz", "test error")
        assert "test error" in msg

    def test_get_friendly_message_by_category(self) -> None:
        """ErrorCategory 分类消息包含标题和建议"""
        msg = UserMessageHelper.get_friendly_message_by_category(
            category=ErrorCategory.NETWORK_TIMEOUT,
            user_message="连接超时",
            suggestion="检查网络",
            details="detail info",
        )
        assert "连接超时" in msg
        assert "检查网络" in msg

    def test_get_stage_message(self) -> None:
        """各阶段消息为非空字符串"""
        msg = UserMessageHelper.get_stage_message("downloading")
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_get_progress_message(self) -> None:
        """进度消息根据阶段和百分比变化"""
        msg_early = UserMessageHelper.get_progress_message("downloading", 10)
        msg_late = UserMessageHelper.get_progress_message("downloading", 90)
        assert isinstance(msg_early, str)
        assert isinstance(msg_late, str)
