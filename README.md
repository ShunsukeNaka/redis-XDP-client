# redis-xdp-client

標準ライブラリだけで書いた Redis クライアントです(外部ライブラリ不要、Python 3.8 以上)。

## セットアップ

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

`venv` が作れない場合は、Debian/Ubuntu なら `sudo apt install python3-venv` を実行してください。

## 使い方

```bash
source .venv/bin/activate

redis-xdp-client -H 10.0.0.2                          # 対話モード
redis-xdp-client -H 10.0.0.2 SET foo bar              # 1 コマンドだけ実行
redis-xdp-client -H 10.0.0.2 --hexdump GET foo        # 送受信したバイト列を表示
redis-xdp-client -H 10.0.0.2 --bench 100000 GET foo   # 遅延を計測
redis-xdp-client -H 10.0.0.2 --bench 100000 -P 32 GET foo  # パイプライン 32 段で計測
```
