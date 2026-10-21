"""P01-02 配置的离线测试；只在临时目录保存虚构密钥。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import traceback
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from yanagent.config import AppConfig, ConfigStore, MASKED_SECRET
from yanagent.config.settings import DEFAULT_CONFIG_PATH
from yanagent.errors import ConfigurationError


class ConfigTests(unittest.TestCase):
    """验证读取优先级、持久化边界、字段约束和失败时保留原文件。"""

    def setUp(self) -> None:
        """为每个用例分配隔离目录，避免接触真实配置和系统环境密钥。"""
        directory = tempfile.TemporaryDirectory(
            prefix=".yan-config-test-", dir=Path(__file__).resolve().parents[1],
        )
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config.json"
        self.store = ConfigStore(self.path, environ={})

    def write_fixture(self, data: dict) -> None:
        """写入受控文件内容，供读取与更新行为测试使用。"""
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_missing_file_returns_defaults_without_creating_file(self) -> None:
        """首次读取没有副作用，默认配置允许启动但尚不可调用模型。"""
        config = self.store.load()
        self.assertEqual(config, AppConfig())
        self.assertFalse(self.path.exists())
        with self.assertRaises(ConfigurationError) as caught:
            config.require_model_ready()
        self.assertEqual(caught.exception.field, "api_base")

    def test_example_config_is_valid(self) -> None:
        """仓库示例能直接读取，且不包含演示密钥或已配置模型的假象。"""
        sample = Path(__file__).resolve().parents[1] / "config.example.json"
        self.assertEqual(ConfigStore(sample, environ={}).load(), AppConfig())

    def test_nonempty_environment_overrides_file_and_defaults(self) -> None:
        """环境覆盖每个受支持字段，读取不会将环境值写入文件。"""
        self.write_fixture({"model": "file-model", "api_key": "file-secret", "port": 9800})
        original = self.path.read_bytes()
        config = ConfigStore(self.path, environ={
            "YAN_MODEL_PROVIDER": "openai-compatible", "YAN_MODEL": "env-model",
            "YAN_API_BASE": "http://localhost:1234/v1", "YAN_API_KEY": "env-secret",
            "YAN_REQUEST_TIMEOUT": "12.5", "YAN_WEB_HOST": "localhost",
            "YAN_WEB_PORT": "9901", "YAN_PERMISSION_MODE": "deny",
        }).load()
        self.assertEqual(config.model, "env-model")
        self.assertEqual(config.api_key, "env-secret")
        self.assertEqual(config.api_base, "http://localhost:1234/v1")
        self.assertEqual((config.port, config.host, config.request_timeout), (9901, "localhost", 12.5))
        self.assertEqual(config.permission_mode, "deny")
        config.require_model_ready()
        self.assertEqual(self.path.read_bytes(), original)

    def test_blank_environment_keeps_file_but_whitespace_is_invalid(self) -> None:
        """空环境占位不清除密钥，非空白要求失败时不静默回退。"""
        self.write_fixture({"api_key": "file-secret", "request_timeout": 20})
        config = ConfigStore(self.path, environ={"YAN_API_KEY": "", "YAN_REQUEST_TIMEOUT": ""}).load()
        self.assertEqual((config.api_key, config.request_timeout), ("file-secret", 20))
        with self.assertRaises(ConfigurationError):
            ConfigStore(self.path, environ={"YAN_API_KEY": " "}).load()

    def test_foreign_environment_is_not_imported(self) -> None:
        """CowAgent 和通用变量不污染 YanAgent 的独立模型配置。"""
        config = ConfigStore(self.path, environ={
            "COW_DATA_DIR": "unused", "COW_WEB_PORT": "9001", "MODEL": "foreign",
            "OPENAI_API_KEY": "foreign-secret", "API_KEY": "another-secret",
        }).load()
        self.assertEqual(config, AppConfig())

    def test_environment_is_captured_per_store_instance(self) -> None:
        """运行期环境变化不偷偷更改已有实例，重建实例才读取新环境。"""
        with patch.dict(os.environ, {"YAN_MODEL": "old"}, clear=True):
            store = ConfigStore(self.path)
            os.environ["YAN_MODEL"] = "new"
            self.assertEqual(store.load().model, "old")
            self.assertEqual(ConfigStore(self.path).load().model, "new")

    def test_config_path_priority(self) -> None:
        """显式路径优先，其次专属环境路径，默认位置不依赖工作目录。"""
        other = self.path.parent / "other.json"
        env = {"YAN_CONFIG_PATH": str(other)}
        self.assertEqual(ConfigStore(self.path, environ=env).path, self.path.resolve())
        self.assertEqual(ConfigStore(environ=env).path, other.resolve())
        self.assertEqual(ConfigStore(environ={}).path, DEFAULT_CONFIG_PATH)

    def test_utf8_bom_and_chinese_model_round_trip(self) -> None:
        """Windows 带 BOM 文件可读，中文模型标识保存后保持不变。"""
        self.path.write_text('{"model": "中文模型"}', encoding="utf-8-sig")
        self.assertEqual(self.store.load().model, "中文模型")
        self.store.save({"request_timeout": 8})
        self.assertEqual(self.store.load().model, "中文模型")
        self.assertIn("中文模型", self.path.read_text(encoding="utf-8"))

    def test_patch_preserves_key_and_never_persists_environment(self) -> None:
        """保存局部设置保留文件密钥，临时环境密钥和模型只影响生效值。"""
        self.write_fixture({"api_key": "file-secret", "model": "file-model"})
        store = ConfigStore(self.path, environ={"YAN_API_KEY": "env-secret", "YAN_MODEL": "env-model"})
        effective = store.save({"request_timeout": 25})
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((saved["api_key"], saved["model"]), ("file-secret", "file-model"))
        self.assertEqual((effective.api_key, effective.model), ("env-secret", "env-model"))
        self.assertEqual(self.store.load().request_timeout, 25)
        self.assertNotIn("env-secret", self.path.read_text(encoding="utf-8"))

    def test_key_can_be_replaced_or_explicitly_cleared(self) -> None:
        """省略密钥保留原值，明确提交新值替换，空字符串清除。"""
        self.store.save({"api_key": "old"})
        self.store.save({"api_key": "new"})
        self.assertEqual(self.store.load().api_key, "new")
        self.store.save({"api_key": ""})
        self.assertEqual(self.store.load().to_dict()["api_key"], "")

    def test_masked_display_cannot_overwrite_secret(self) -> None:
        """误将展示字典用于保存时拒绝占位符，原密钥不丢失。"""
        config = self.store.save({"api_key": "file-secret"})
        with self.assertRaises(ConfigurationError) as caught:
            self.store.save(config.to_dict())
        self.assertEqual(caught.exception.reason, "masked_key")
        self.assertEqual(self.store.load().api_key, "file-secret")

    def test_malformed_files_are_rejected_and_preserved(self) -> None:
        """损坏、重复字段、未知字段和非标准 JSON 均报错且不自动重建。"""
        for raw in ('{', '[]', 'null', '{"model":"a","model":"b"}',
                    '{"request_timeout": NaN}', '{"request_timeout": Infinity}',
                    '{"api-key":"hidden"}', '{"port":"9876"}', '{"model":null}'):
            with self.subTest(raw=raw):
                self.path.write_text(raw, encoding="utf-8")
                with self.assertRaises(ConfigurationError):
                    self.store.load()
                with self.assertRaises(ConfigurationError):
                    self.store.save({"model": "new"})
                self.assertEqual(self.path.read_text(encoding="utf-8"), raw)

    def test_invalid_utf8_and_unreadable_file_are_safe_errors(self) -> None:
        """编码损坏和操作系统错误分类明确，异常栈不回显底层敏感路径。"""
        self.path.write_bytes(b"\xff")
        with self.assertRaises(ConfigurationError) as caught:
            self.store.load()
        self.assertEqual(caught.exception.reason, "invalid_json")
        with patch.object(Path, "read_text", side_effect=PermissionError("secret-in-path")):
            try:
                self.store.load()
            except ConfigurationError as error:
                self.assertEqual(error.reason, "read_failed")
                self.assertNotIn("secret-in-path", traceback.format_exc())
            else:
                self.fail("读取失败必须返回统一错误")

    def test_invalid_fields_are_rejected(self) -> None:
        """数字拒绝 bool、非有限值和越界；文本及枚举不接受隐式转换。"""
        cases = {
            "port": [True, 0, 65536, 1.5, "9876"],
            "request_timeout": [True, 0, -1, 3601, float("nan"), float("inf"), "60"],
            "model_provider": ["TODO", "claude", "", None],
            "permission_mode": ["unknown", True],
            "host": ["", " ", "host/name", "host\nname"],
            "model": [False, None, " model", "a\nb", "\ud800"],
            "api_key": [None, 123, "***", "abc\r\ndef"],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=repr(value)):
                    with self.assertRaises(ConfigurationError) as caught:
                        AppConfig(**{field: value})
                    self.assertEqual(caught.exception.field, field)

    def test_api_base_validation(self) -> None:
        """允许本地模型地址，拒绝坏端口、URL 凭据及查询串密钥。"""
        for value in ("https://example.com/v1", "http://127.0.0.1:8000/v1", "http://[::1]:1234/v1"):
            self.assertEqual(AppConfig(api_base=value).api_base, value)
        for value in ("example.com", "ftp://example.com", "https://", "https://[bad",
                      "https://host:abc", "https://host:0", "https://host:65536",
                      "https://user:secret@host", "https://host?key=secret", "https://host#secret",
                      "https://ho st", "https://host\\path"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                AppConfig(api_base=value)

    def test_invalid_environment_does_not_fall_back_or_write(self) -> None:
        """错误环境覆盖明确失败，保存过程中发现错误也不提交文件更新。"""
        self.write_fixture({"model": "old"})
        original = self.path.read_bytes()
        for env in ({"YAN_WEB_PORT": "abc"}, {"YAN_REQUEST_TIMEOUT": "nan"},
                    {"YAN_REQUEST_TIMEOUT": "0"}, {"YAN_MODEL_PROVIDER": "other"}):
            store = ConfigStore(self.path, environ=env)
            with self.assertRaises(ConfigurationError):
                store.load()
            with self.assertRaises(ConfigurationError):
                store.save({"model": "new"})
            self.assertEqual(self.path.read_bytes(), original)

    def test_bad_file_cannot_be_hidden_by_environment(self) -> None:
        """各层单独合法后才合并，环境值不能掩盖文件中的非法字段。"""
        self.write_fixture({"port": "bad"})
        with self.assertRaises(ConfigurationError):
            ConfigStore(self.path, environ={"YAN_WEB_PORT": "9876"}).load()

    def test_invalid_patch_is_all_or_nothing(self) -> None:
        """局部更新中任意字段失败都不修改旧文件。"""
        self.store.save({"model": "old"})
        original = self.path.read_bytes()
        for updates in ({"model": "new", "request_timeout": -1}, {"typo": 1}, []):
            with self.assertRaises(ConfigurationError):
                self.store.save(updates)
            self.assertEqual(self.path.read_bytes(), original)

    def test_failed_fsync_or_replace_preserves_old_file_and_cleans_temp(self) -> None:
        """模拟落盘和替换失败，原文件完整保留，同目录无多余临时文件。"""
        self.store.save({"api_key": "file-secret", "model": "old"})
        original = self.path.read_bytes()
        for operation in ("fsync", "replace"):
            with patch(f"yanagent.config.settings.os.{operation}", side_effect=OSError("hidden-secret")):
                try:
                    self.store.save({"model": "new"})
                except ConfigurationError as error:
                    self.assertEqual(error.reason, "write_failed")
                    self.assertNotIn("hidden-secret", traceback.format_exc())
                else:
                    self.fail("模拟保存失败应返回错误")
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_missing_directory_does_not_create_partial_file(self) -> None:
        """不存在的目标目录产生可识别错误，不声称保存成功。"""
        target = self.path.parent / "missing" / "config.json"
        with self.assertRaises(ConfigurationError) as caught:
            ConfigStore(target, environ={}).save({"model": "demo"})
        self.assertEqual(caught.exception.reason, "write_failed")
        self.assertFalse(target.exists())

    def test_secret_redaction_in_display_and_logs(self) -> None:
        """展示字典、对象打印和正常日志均不显示任何长度的非空密钥。"""
        for secret in ("x", "short", "long-test-secret-123456"):
            config = AppConfig(api_key=secret)
            self.assertEqual(config.to_dict()["api_key"], MASKED_SECRET)
            self.assertNotIn("api_key=", repr(config))
            with self.assertLogs("yanagent.config.test", level="INFO") as captured:
                logging.getLogger("yanagent.config.test").info("%s %s", config, config.to_dict())
            if len(secret) > 1:
                self.assertNotIn(secret, "\n".join(captured.output))
            self.assertEqual(config.api_key, secret)

    def test_readiness_and_immutable_snapshot(self) -> None:
        """完整配置才允许进入模型层；快照和展示副本不会互相修改。"""
        config = AppConfig(api_base="https://example.com/v1", model="demo")
        with self.assertRaises(ConfigurationError) as caught:
            config.require_model_ready()
        self.assertEqual(caught.exception.reason, "missing_key")
        with self.assertRaises(FrozenInstanceError):
            config.model = "changed"
        display = config.to_dict()
        display["model"] = "changed"
        self.assertEqual(config.model, "demo")


if __name__ == "__main__":
    unittest.main()
