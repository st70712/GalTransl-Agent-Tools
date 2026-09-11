---
name: start-translator
description: 要跑翻譯但本機 Sakura 模型伺服器沒起來（translate.py 回報 /health 失敗）時，啟動並確認 llama-server。
---

# /start-translator

## 觸發
`tools/translate.py` 印出「llama-server 未啟動」、`curl http://127.0.0.1:8080/health` 失敗，或使用者說模型關掉了。

## 輸入
- 無；預設值在 `config.yaml`（`llama_server_bin`、`model_gguf`、`endpoint`、`llama_ctx`、`llama_np`、`llama_gpu`）。

## 步驟
```bash
bash tools/llama_server.sh status                  # pid / health / 模型名
bash tools/llama_server.sh start                   # nohup 背景啟動 + 等 health ok；已在跑則只印 status
bash tools/llama_server.sh start --gpu 3 --ctx 32768 --np 16   # 指定卡；預設 auto 挑用量最低的卡
bash tools/llama_server.sh wait --timeout 300
bash tools/llama_server.sh stop                    # 用 pid 檔停；備援掃 /proc，絕不 pkill -f
```
1. `start` 是同步的（含等待），可以直接前景跑；模型載入約 1–2 分鐘。
2. 失敗看 `logs/llama-server.log`；常見：GPU 被別人的 vLLM 占滿（換 `--gpu`）、port 被占（換 `--port` 並在 translate.py 用 `-e`）。
3. 模型：`Sakura-GalTransl-14B-v3.8.gguf`，OpenAI 相容 API `http://127.0.0.1:8080/v1`，模型型別 `galtransl-v3`。

## 輸出
- `/health` 回 ok、`/v1/models` 列出模型；translate.py 可連。

## 停下來問使用者
- 所有 GPU 都被占用、或需要停掉別人的行程時——不要自己殺。
