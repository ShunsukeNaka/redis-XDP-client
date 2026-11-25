# redis-cli の基本的な使い方

Redis に付いてくる公式 CLI のまとめです(redis-cli 8.0.2 の `--help` で確認)。
ホスト名は README に合わせて `10.0.0.2` を例にしています。

## 接続

```bash
redis-cli                          # 127.0.0.1:6379 に接続
redis-cli -h 10.0.0.2 -p 6379      # ホストとポートを指定
redis-cli -h 10.0.0.2 -n 1         # DB 番号 1 を使う
redis-cli -s /run/redis/redis.sock # UNIX ソケットで接続
redis-cli -u redis://user:pass@10.0.0.2:6379/0   # URI でまとめて指定
```

| オプション | 意味 |
| --- | --- |
| `-h <host>` / `-p <port>` | 接続先(既定 `127.0.0.1:6379`) |
| `-n <db>` | DB 番号 |
| `-a <password>` | パスワード。`--user <name>` と組み合わせると ACL ユーザで認証 |
| `-t <sec>` | 接続タイムアウト(既定は無制限) |
| `-2` / `-3` | RESP2 / RESP3 で話す |
| `--tls` | TLS で接続(`--cacert` `--cert` `--key` などと併用) |

パスワードは `-a` だとシェル履歴に残るので、環境変数 `REDISCLI_AUTH` か `--askpass` を使う方が安全です。

## 対話モード

引数なしで起動すると対話モードになります。

```text
$ redis-cli -h 10.0.0.2
10.0.0.2:6379> SET foo bar
OK
10.0.0.2:6379> GET foo
"bar"
10.0.0.2:6379> HELP GET        # コマンドのヘルプ
10.0.0.2:6379> SELECT 1        # DB 切り替え
10.0.0.2:6379[1]> quit
```

- Tab でコマンド名を補完、↑↓ で履歴(`~/.rediscli_history` に保存)
- 先頭に回数を付けると繰り返し実行: `5 INCR counter`
- `CONNECT <host> <port>` で接続先を切り替え

## 1 コマンドだけ実行

```bash
redis-cli -h 10.0.0.2 SET foo bar
redis-cli -h 10.0.0.2 GET foo
redis-cli -h 10.0.0.2 -e GET foo     # エラー応答なら終了コード 1 にする
```

`-e` を付けないと、サーバがエラーを返しても終了コードは 0 です。スクリプトで使うときは `-e` を付けます。

## 出力形式

| オプション | 出力 |
| --- | --- |
| (なし、端末に出す場合) | `"bar"`、`(integer) 1` のような整形表示 |
| `--raw` | 値だけ(パイプやリダイレクト時はこちらが既定) |
| `--no-raw` | パイプ先でも整形表示 |
| `--csv` | CSV |
| `--json` | JSON(既定で RESP3 を使う。RESP2 で使うなら `-2`) |

```bash
redis-cli -h 10.0.0.2 --raw GET foo > value.txt
redis-cli -h 10.0.0.2 --json HGETALL user:1
```

## 標準入力から値を渡す

```bash
redis-cli -h 10.0.0.2 -x SET blob < file.bin   # 最後の引数を stdin から読む
cat commands.txt | redis-cli -h 10.0.0.2       # 1 行 1 コマンドで流し込む
```

大量のデータを流すときは、RESP をそのまま送る `--pipe` の方が速いです。

```bash
cat data.resp | redis-cli -h 10.0.0.2 --pipe
```

## 繰り返し実行

```bash
redis-cli -h 10.0.0.2 -r 100 INCR counter           # 100 回実行
redis-cli -h 10.0.0.2 -r -1 -i 1 INFO memory        # 1 秒おきに無限に実行
```

`-r` は回数(`-1` で無限)、`-i` は間隔(秒。`0.1` のような小数も可)。

## 遅延の計測

```bash
redis-cli -h 10.0.0.2 --latency               # PING の往復時間を計り続ける(min/max/avg)
redis-cli -h 10.0.0.2 --latency-history       # 15 秒ごとに区切って表示(-i で変更)
redis-cli -h 10.0.0.2 --latency-dist          # 分布を色付きで表示
redis-cli --intrinsic-latency 10              # 手元のマシン自体の遅延を 10 秒計測
```

`--latency` は PING で計るため、GET/SET など特定のコマンドの遅延を見たいときは
このリポジトリの `redis-xdp-client --bench` か `redis-benchmark` を使います。
出力をパイプに流す(または `--raw` / `--csv` を付ける)と、1 秒だけ計測して 1 行出して終わります。

## サーバの様子を見る

```bash
redis-cli -h 10.0.0.2 --stat                  # メモリ・クライアント数・要求数などを 1 秒ごとに表示
redis-cli -h 10.0.0.2 INFO                    # サーバ情報(INFO stats, INFO memory のように絞れる)
redis-cli -h 10.0.0.2 MONITOR                 # サーバが受けたコマンドをすべて表示(負荷が高いので注意)
redis-cli -h 10.0.0.2 SLOWLOG GET 10          # 遅かったコマンド
redis-cli -h 10.0.0.2 CLIENT LIST             # 接続中のクライアント
```

## キーを調べる

```bash
redis-cli -h 10.0.0.2 --scan --pattern 'user:*'   # SCAN でキー一覧(KEYS と違いサーバを止めない)
redis-cli -h 10.0.0.2 --bigkeys                   # 要素数の多いキーを探す
redis-cli -h 10.0.0.2 --memkeys                   # メモリを多く使うキーを探す
redis-cli -h 10.0.0.2 TYPE foo
redis-cli -h 10.0.0.2 TTL foo
```

本番に近い環境では `KEYS *` ではなく `--scan` を使います。

## よく使うコマンド

| 種類 | コマンド例 |
| --- | --- |
| 文字列 | `SET k v` / `GET k` / `SET k v EX 60`(60 秒で消える) / `INCR k` / `MGET k1 k2` |
| キー操作 | `DEL k` / `EXISTS k` / `EXPIRE k 60` / `TTL k` / `RENAME k k2` |
| ハッシュ | `HSET h f v` / `HGET h f` / `HGETALL h` |
| リスト | `LPUSH l a` / `RPUSH l b` / `LRANGE l 0 -1` / `LPOP l` |
| セット | `SADD s a` / `SMEMBERS s` / `SISMEMBER s a` |
| ソート済みセット | `ZADD z 1 a` / `ZRANGE z 0 -1 WITHSCORES` |
| サーバ | `PING` / `DBSIZE` / `FLUSHDB`(今の DB を全消去) / `CONFIG GET maxmemory` |

## このリポジトリのクライアントとの違い

| やりたいこと | redis-cli | redis-xdp-client |
| --- | --- | --- |
| 対話・1 コマンド実行 | できる | できる |
| 送受信したバイト列を見る | できない | `--hexdump` |
| 任意コマンドの遅延分布(p99 など) | できない(`--latency` は PING のみ) | `--bench N [-P DEPTH]` |
| TLS・認証・クラスタ | できる | できない |
