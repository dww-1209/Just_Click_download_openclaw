"""ShellRunner 纯逻辑单元测试

验证 ShellResult 数据对象的方法不依赖外部系统。
"""

import pytest

from src.adapters.run_shell import ShellResult


class TestShellResult:
    """ShellResult 数据对象测试"""

    def test_success_when_returncode_zero(self) -> None:
        """returncode=0 且未超时、未找不到进程时 success=True"""
        result = ShellResult(command="echo hello", returncode=0)
        assert result.success is True

    def test_success_when_returncode_nonzero(self) -> None:
        """returncode != 0 时 success=False"""
        result = ShellResult(command="false", returncode=1)
        assert result.success is False

    def test_success_when_timed_out(self) -> None:
        """超时时 success=False"""
        result = ShellResult(command="sleep 10", returncode=0, timed_out=True)
        assert result.success is False

    def test_success_when_process_not_found(self) -> None:
        """进程未找到时 success=False"""
        result = ShellResult(
            command="nonexistent_cmd", returncode=0, process_not_found=True
        )
        assert result.success is False

    def test_combined_output_empty(self) -> None:
        """stdout 和 stderr 均为空时 combined_output 为空字符串"""
        result = ShellResult(command="echo hello")
        assert result.combined_output == ""

    def test_combined_output_stdout_only(self) -> None:
        """仅有 stdout 时 combined_output 等于 stdout"""
        result = ShellResult(command="echo hello", returncode=0, stdout="hello")
        assert result.combined_output == "hello"

    def test_combined_output_both(self) -> None:
        """stdout 和 stderr 均存在时 combined_output 合并两者"""
        result = ShellResult(
            command="echo hello", returncode=0, stdout="hello", stderr="warning"
        )
        assert "hello" in result.combined_output
        assert "warning" in result.combined_output

    def test_default_values(self) -> None:
        """ShellResult 默认值正确"""
        result = ShellResult(command="test")
        assert result.returncode == -1
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.elapsed_seconds == 0.0
        assert result.timed_out is False
        assert result.process_not_found is False
        assert result.permission_denied is False
        assert result.error_detail is None
