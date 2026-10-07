# 開発環境

## 前提

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/)
- Ollamaモデル `qwen3.5:latest`

## セットアップ

```sh
uv sync
ollama pull qwen3.5:latest
cp .env.example .env
```

`.env`の既定値はOllamaを同じPCで動かす設定です。別のホストを使う場合は`OLLAMA_API_BASE`を変更してください。`.env`はGit管理対象外です。

ADKはLiteLLM経由でOllamaに接続します。モデル名には`ollama_chat/`を付け、Ollamaの接続先には`OLLAMA_API_BASE`を使います。ツール呼び出しを使うモデルでは、Ollamaモデルに`tools` capabilityがあることも確認してください。

## 接続確認

Ollamaを起動した状態で次を実行します。

```sh
uv run python scripts/check_ollama.py
```

成功するとモデルからの短い応答が表示されます。接続に失敗した場合は、Ollamaが稼働していること、`OLLAMA_API_BASE`が正しいこと、`ollama list`に`qwen3.5:latest`があることを確認してください。モデルがなければ`ollama pull qwen3.5:latest`で取得できます。

## 依存関係

`google-adk[a2a,extensions]`を利用します。依存バージョンは`uv.lock`に固定し、環境構築時は`uv sync`を使ってください。
