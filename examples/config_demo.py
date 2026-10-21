"""离线演示文件保存、环境覆盖、密钥脱敏和错误分类；不请求真实模型。"""

import json
import tempfile
from pathlib import Path

from yanagent.config import ConfigStore
from yanagent.errors import ConfigurationError, map_http_error


def main() -> None:
    """在自动清理的临时目录演示配置，所有密钥均为无效测试字符串。"""
    with tempfile.TemporaryDirectory(
        prefix=".yan-config-demo-", dir=Path(__file__).resolve().parents[1],
    ) as directory:
        path = Path(directory) / "config.json"
        file_store = ConfigStore(path, environ={})
        file_store.save({
            "api_base": "https://example.com/v1", "model": "file-demo-model",
            "api_key": "demo-file-key-not-real", "request_timeout": 30,
        })
        store = ConfigStore(path, environ={
            "YAN_MODEL": "env-demo-model", "YAN_API_KEY": "demo-env-key-not-real",
        })
        config = store.load()
        config.require_model_ready()
        print("环境覆盖后的配置（密钥已脱敏）：")
        print(json.dumps(config.to_dict(), ensure_ascii=False, indent=2))
        store.save({"request_timeout": 15})
        saved = file_store.load()
        assert saved.model == "file-demo-model"
        assert saved.api_key == "demo-file-key-not-real"
        assert saved.request_timeout == 15
        print("保存超时设置后，文件仍保留原模型和文件密钥，环境密钥未落盘。")
        try:
            store.save({"request_timeout": -1})
        except ConfigurationError as error:
            print("非法超时被拒绝：", json.dumps(error.to_dict(), ensure_ascii=False))
        assert file_store.load().request_timeout == 15
        print("模拟 HTTP 429：", json.dumps(map_http_error(429).to_dict(), ensure_ascii=False))
        print("验收通过：配置可保存还原，覆盖优先级正确，失败保留原值，展示隐藏密钥。")
        print("本示例未调用真实模型；临时配置会自动删除。")


if __name__ == "__main__":
    main()
