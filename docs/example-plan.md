# 計画モードの出力例: billing/ に通貨 JPY を追加する

preparatory-refactoring スキルを計画モードで実行したときの出力例。「計画」見出しから下が、スキルが返す計画本体。

- 入力（`evals/invoice-currency-plan/prompt.md` より）: 「billing/ リポジトリ（git 履歴あり）に通貨 JPY を追加する予定。コードがごちゃっとしてて、どこから手をつければいいか分からない。先に整理したほうがいいのか、するならどこをどこまでやるべきか、計画を出して。まだコードは変更しないで。計画は plan.md に書いて。」
- 対象: `skills/preparatory-refactoring/evals/invoice-currency-plan/billing.bundle` を clone した作業コピー。fixture のコードは変更していない。
- 実行したコマンド: 事実確認表の `rg` / `ls` / `git show`、`uv run "$SKILL_DIR/scripts/change_coupling.py" --repo . --top 15`（`--path billing/` 付きも実行）、同スクリプトの `--partner billing/invoice.py`・`billing/money.py`・`report/monthly.py`（各 `--top 10`）。
- 注意: fixture の履歴は 7 コミットしかなく、スクリプトは毎回「分析対象コミットが 7 件しかない（目安 30 件以上）」と警告した。計画中の履歴の割合は方向の参考に留めている。

---

# 計画

## 結論
構造改善あり。前に 1 件（fmt の入れ子を平らにする）、直後に 1 件（total の丸め分岐を表にする）。どちらも小さく、JPY 追加の前提となる特性テストを先に置く。
なし判定: D1 非発火、D2 非発火、D3 非発火
## 対象の変更
通貨 "JPY" の請求について、API スキーマと月次集計が受け付け、`total` が円未満を丸め、`fmt` が円の表記で出力するようにする。
## 構造メモ
### 事実確認表
| # | 主張 | 種別 | 確認したもの（検索コマンドまたは file:line） | 結果 | 判定 |
|---|---|---|---|---|---|
| 1 | JPY はまだどこにも無い | 否定 | `rg -n 'JPY\|"JPY"\|yen\|¥'` | 0 件 | 確認済 |
| 2 | 通貨ごとの分岐・列挙は 4 ファイルにある | 存在 | `rg -n '"USD"\|"EUR"'` | 6 行: billing/invoice.py:11,13 / billing/money.py:2,5 / report/monthly.py:6 / api/schema.py:1 | 確認済 |
| 3 | 請求書の経路は render → total → fmt | 経路 | billing/invoice.py:1,3-15,17-18、billing/money.py:1-7 | 小計（invoice.py:5-6）→ 国別税（7-10）→ 通貨別丸め（11-14）→ fmt で通貨別書式（money.py:2-7） | 確認済 |
| 4 | リポジトリ内の呼び出し元 | 否定 | `rg -n 'fmt\(\|total\(\|render\(\|monthly\(\|INVOICE_SCHEMA'` | total・fmt は invoice.py:18 のみ。render・monthly・INVOICE_SCHEMA は定義行のみ | 確認済（リポジトリ内のみ。外部の呼び出し元は未確認） |
| 5 | 未対応通貨は monthly と INVOICE_SCHEMA で拒否される | 肯定 | report/monthly.py:6-7、api/schema.py:1 | 検査の記述はあるが、呼び出し元がリポジトリ内に無い（#4） | 未確認 |
| 6 | 丸め桁と書式桁が別々の場所にある | 経路 | `rg -n 'round\('` と money.py:3,6 | round は invoice.py:12,14（どちらも 2 桁）。書式の桁は money.py:3,6 の `".2f"` | 確認済 |
| 7 | US の `t * 1.0` は戻り値の型に効く | 経路 | billing/invoice.py:9-10 | 整数の小計を float に変える。消すと戻り値の型が変わる | 確認済 |
| 8 | fmt は USD・EUR 以外で `str(amount)` を返す | 経路 | billing/money.py:2-7 | EUR の分岐は else の中に入れ子。未登録通貨は 7 行目へ落ちる | 確認済 |
| 9 | テストが無い | 否定 | `rg --files -g '*test*'` | 0 件 | 確認済 |
| 10 | lint / 型検査の設定が無い | 否定 | `ls -a pyproject.toml setup.cfg .pylintrc tox.ini .flake8 ruff.toml mypy.ini` | すべて No such file | 確認済 |
| 11 | 通貨関連 4 ファイルが履歴上も一緒に変わる | 履歴 | `change_coupling.py --repo . --top 15` | hotspot: invoice.py 5、money.py 5、schema.py 3、monthly.py 3。ペア: invoice↔money 5 回 100%/100%、schema↔monthly 3 回 100%/100%、schema↔invoice 2 回 67%/40%。警告: 7 件 | 確認済（警告あり） |
| 12 | invoice.py の履歴上の相手に schema.py と monthly.py が入る | 履歴 | `change_coupling.py --repo . --partner billing/invoice.py --top 10` | money.py 5（100%）、schema.py 2（40%）、monthly.py 2（40%）、README.md 1（20%）。変更 5 回で警告 | 確認済（履歴不足 5 回） |
| 13 | money.py の相手も同じ | 履歴 | `change_coupling.py --repo . --partner billing/money.py --top 10` | invoice.py 5（100%）、schema.py 2（40%）、monthly.py 2（40%）、README.md 1（20%） | 確認済（履歴不足 5 回） |
| 14 | monthly.py は schema.py と常に一緒に変わる | 履歴 | `change_coupling.py --repo . --partner report/monthly.py --top 10` | schema.py 3（100%）、invoice.py 2（67%）、money.py 2（67%） | 確認済（履歴不足 3 回） |
| 15 | 前回の通貨追加（GBP）は 4 ファイルに及んだ | 履歴 | `git log --oneline --stat` | 897786d「add GBP (reverted later)」が schema.py・invoice.py・money.py・monthly.py を変更 | 確認済 |
| 16 | 履歴の差分そのものはコメント行のみ | 履歴 | `git show 897786d 45aeffa e082586 5026238 \| grep '^[+-][^+-]'` | `# gbp`、`# tweak 1`、`# t1` などの追加だけ | 確認済 |

### 経路表（肯定の主張ごとに必須）
| # | 検査箇所 file:line | 呼び出し元 file:line（すべて列挙） | その呼び出しで対象項目が渡されているか |
|---|---|---|---|
| 5 | report/monthly.py:6、api/schema.py:1 | リポジトリ内に無い（#4）。外部の入口は未確認 | 未確認 |

### 着地点表
| ファイル | 経路上の位置 | 出所 | 変更する / 変更不要 | 理由（事実 #n） |
|---|---|---|---|---|
| api/schema.py | 入口（通貨の enum） | 両方 | 変更する | enum に JPY を足す（#2、#12） |
| billing/invoice.py | 計算（total） | 両方 | 変更する | 通貨別丸めに JPY を足す（#3、#6） |
| billing/money.py | 出力（fmt） | 両方 | 変更する | JPY の書式を足す（#3、#8、#13） |
| report/monthly.py | 出力（月次集計） | 両方 | 変更する | 許容通貨に JPY を足す（#2、#12、#14） |
| README.md | 経路外 | 履歴 | 変更不要 | 相手としての割合 20%・1 回で基準未満（#12） |

### D 判定の入力
| 判定・計算 / 関数 | 呼び出し元・類似箇所（rg と件数、file:line） | 既存の式の書き換え / 追加のみ | 引数の数 |
|---|---|---|---|
| total の通貨別丸め | 呼び出し元 1（invoice.py:18、#4）。類似 2（invoice.py:12,14、#6） | 追加のみ（JPY の分岐を足す） | total 3 → 3 |
| fmt の通貨別書式 | 呼び出し元 1（invoice.py:18、#4） | 追加のみ（JPY の分岐を足す） | fmt 2 → 2 |
| monthly の許容通貨判定 | 判定式は monthly.py:6 の 1 か所。schema.py:1 は enum のデータ（#2） | 追加のみ（列挙項目を足す） | monthly 1 → 1 |

- lint / 型検査: 設定ファイルなし（#10）。pylint `max-args` の既定値 5 に対して最大 3
- 触る要素: api/schema.py の `INVOICE_SCHEMA`、billing/invoice.py の `total`、billing/money.py の `fmt`、report/monthly.py の `monthly`（#2、#3）
- 閉じていない粒度: パッケージ — 通貨の一覧と通貨ごとの規則が billing/・api/・report/ の 3 パッケージに分かれている（#2）
- 依存（静的 / 暗黙）: 静的: invoice.py → money.py（import と呼び出し、invoice.py:1,18）。暗黙: schema.py と monthly.py は import 関係が無いのに同じ許容通貨の一覧を持つ（重複した業務ルール、#2、#14）。暗黙: invoice.py の丸め桁と money.py の書式桁は同じ「通貨の小数桁」の意味を別々に持つ（値の意味、#6）
- 結合と波及: 「通貨を追加する」変更で 4 ファイルが同時に変わる（一対多、#2、#15）。「通貨の小数桁を変える」変更で invoice.py と money.py が同時に変わる（#6、#11）。「許容通貨を変える」変更で schema.py と monthly.py が同時に変わる（#14）
- 履歴: 7 コミット中、invoice↔money 5 回、schema↔monthly 3 回の同時変更（#11）。`--partner` で schema.py・monthly.py を着地点に加えた（#12、#13、#14、いずれも履歴不足）。差分はコメント行のみ（#16）。警告あり、割合は方向の参考
## 診断
| 原因 | 根拠（事実 #n、履歴の数値） |
|---|---|
| 変更箇所が散在 | 通貨の追加で 4 ファイルを直す（#2）。前回の GBP も 4 ファイル（#15）。invoice↔money 5 回、schema↔monthly 3 回（#11） |
| 理解しにくい | fmt の EUR 分岐が else の中に入れ子で、未登録通貨がどこへ落ちるか読み取りにくい（#8） |
| ノイズ | 各ファイル末尾の `# tweak 1` などのコメント（#16）。目的の変更には効かない |

## タイミング判断
| 改善候補 | 判断 | 理由 |
|---|---|---|
| fmt の入れ子を平らにする（M4） | 前 | JPY の分岐を足す場所そのもの。数分で終わり、未登録通貨の落ち先が明示される（#8） |
| total の丸め分岐を「通貨 → 桁」の表にする（M14） | 直後 | JPY 追加で触る箇所。次の通貨追加（GBP は過去に試みあり、#15）が表への 1 行で済む。前にやっても JPY の手間は 2 行 → 1 行で差が小さい |
| 許容通貨の一覧を schema.py と monthly.py で共有する（M14 / M12） | 後回し | 今は import 関係の無いパッケージ間に新しい依存を作る（#2）。JPY では各 1 項目の追加で足り、履歴の根拠は警告付き（#11） |
| US の `t * 1.0` を消す | しない | 戻り値を int から float に変えている（#7）。消すのは振る舞い変更 |
| 末尾コメント（`# tweak 1` など）を消す（M20） | 後回し | JPY の変更のどこも楽にならない（#16） |

## 計画（順序つき）
1. [テスト] 特性テストを追加する: `total` を USD・EUR・未登録通貨 × US・DE で、`fmt` を USD・EUR・未登録通貨で、`monthly` を USD・EUR と未登録通貨（ValueError）で、現在の戻り値と型のまま記録する（#9 よりテストが無いため）
2. [構造] M4 早期脱出で入れ子を平らにする: billing/money.py の `fmt`
   - 楽になる部分: JPY の分岐を足す場所が「else の中の 2 段目」から「同じ深さの if の並び」になり、追加が 1 か所で迷わず書ける
   - 変わりうる振る舞い: `fmt` の未登録通貨（USD・EUR 以外）で `str(amount)` を返す経路（money.py:7）。呼び出し元は invoice.py:18 の 1 か所、例外を投げる経路は無い
   - 固定する方法: 手順 1 の `fmt` の特性テスト（未登録通貨のケースを含む）が変更前後で同じ結果になる
3. [振る舞い] JPY を追加する: schema.py の enum、monthly.py:6 の許容通貨、invoice.py の丸め分岐、money.py の書式分岐に JPY を足し、JPY のテストを足す
4. [構造] M14 散在する分岐を 1 か所に集める: billing/invoice.py の `total` の丸め分岐（USD・EUR・JPY）を「通貨 → 桁」の表にする
   - 楽になる部分: 次の通貨追加で丸めの変更が「if 分岐 2 行」から「表への 1 行」になる
   - 変わりうる振る舞い: 表に無い通貨で、今は丸めずに返す（invoice.py:11-14 のどれにも当たらない）。表の参照で KeyError にしないこと。丸めは国別税の後という順序
   - 固定する方法: 手順 1 の `total` の特性テスト（未登録通貨を含む）と手順 3 の JPY テストが変更前後で同じ結果になる
- 振る舞い変更のコミット分割: `test:` 特性テスト → `refactor:` fmt を平らに → `feat:` JPY 追加（4 ファイルとテスト）→ `refactor:` 丸めの表
- 時間の上限: 「前に行う」構造改善は合計 1 時間程度（M4 は 1 関数で、上限内の見込み）
- PR の分け方: PR1 = 特性テスト + fmt の整理（説明: JPY の書式は 1 か所の追加で済む）/ PR2 = JPY 追加 / PR3 = 丸めの表（説明: 次の通貨の丸めは表への 1 行）
- 停止条件: `fmt` が 1 段の if の並びになり、JPY 追加が 4 ファイルそれぞれ 1 か所の追加で書ける状態になったら前の構造改善をやめる
## 範囲外の別計画
- 通貨ごとの規則（記号、位置、小数桁、許容可否）を 1 つの通貨定義に集め、api/・report/ からも参照する。段階: 定義を billing/ に追加 → monthly.py を参照に切り替え → schema.py を切り替え。各段階を別 PR にし、元の一覧に戻せば戻る
## 後回しリスト
- api/schema.py:1 と report/monthly.py:6 の許容通貨の重複 — 共有すると新しいパッケージ間依存ができる — M14 / M12
- invoice.py の丸め桁と money.py の書式桁の重複（#6） — 手順 4 の表ができてから判断する — M14
- 各ファイル末尾のコメント — JPY に効かない — M20
## リスク
- `render`・`monthly`・`INVOICE_SCHEMA` の外部の呼び出し元は未確認（#4、#5）。monthly が実際に通貨検査の役を果たしているかは不明
- JPY の仕様が未確定: 表示形式（`¥1,234` か `1234 円` か）、丸め方（Python の `round` は偶数丸め。既存の 2 桁丸めも同じ）、戻り値を int にするか float にするか（`round(t, 0)` は float、US の `* 1.0` で小計も float になる、#7）
- テストが無い（#9）。手順 1 の特性テストが固定の唯一の手段
- 履歴は 7 コミットで警告付き、差分はコメント行のみ（#11、#16）。同時変更の回数は根拠の一部に留めた

---

## この例の読みどころ

- D1〜D3: 「結論」の `なし判定:` 行と「D 判定の入力」表。3 つとも非発火なので、前・直後の構造改善は D ではなく診断（散在・理解しにくい）から来ている。
- 事実確認表: 本文の主張はすべて「#n」で表の行を指す。#5 は検査の記述はあるが呼び出し元を確認できず「未確認」で、経路表にもそう書いている。
- 履歴: #11〜#14 が `change_coupling.py` の実測値。`--partner` の結果で schema.py・monthly.py を着地点表に加えている（出所「両方」）。
- [構造] の 3 欄: 計画の手順 2 と 4。「変わりうる振る舞い」は呼び出し元の数と例外経路の有無まで書いている。
- 振る舞い変更の線引き: `t * 1.0` の削除は int → float の型の変化があるので「しない」に分類している（#7）。
