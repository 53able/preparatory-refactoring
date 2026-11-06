# CONTRIBUTING

`skills/preparatory-refactoring/`（Agent Skill 本体）を変更する人向けの手順です。利用方法は [README.md](README.md) を参照してください。

## 開発環境

- [uv](https://docs.astral.sh/uv/): 同梱スクリプトの実行とテストに使う。
- Node.js 22.20 以降: README のインストール手順（`npx skills`）の要件。
- git: `change_coupling.py` は git 履歴を集計する。

スクリプトの自己テスト:

```bash
cd skills/preparatory-refactoring/scripts && uv run python -m unittest test_change_coupling
```

## 評価ケース（evals）

`skills/preparatory-refactoring/evals/<case>/` が 1 ケース。構成:

| ファイル | 内容 |
|---|---|
| `case.yaml` | `schema_version: "1.1"`（引用符つき）、`name`（フォルダ名と同じ）、`expected_outcome`、`context.scaffold_script` |
| `prompt.md` | 先頭に設定ブロック（`tags` / `max_turns` / `timeout_seconds` / `allowed_tools`）、続けて利用者の依頼文。末尾に `Input files: ...` |
| `graders/NN-assertion.md` | 1 ファイル 1 アサーション。先頭に `type: llm` / `focus: trace` / `weight: 1`、本文に検証する文 |
| `place-files.sh` | 作業ディレクトリへ入力ファイルを配置する（`files/` をコピー。`invoice-currency-plan` は加えて `billing.bundle` を clone） |
| `files/` または `*.bundle` | 入力ファイル。git 履歴が必要なケースは bundle |

既存ケース:

- `discount-rule-change`: `pricing.js` に tier 4 の 20% 引きを追加させ、構造変更と振る舞い変更のコミット分離を見る（実行モード）。
- `invoice-currency-plan`: JPY 追加に向けた整理の計画を `plan.md` に書かせ、コードは変更させない（計画モード）。
- `mixed-pr-review`: refactor と称する `pr.diff` から紛れた振る舞い変更を指摘させ、分割案を `review.md` に書かせる（レビューモード）。

実行（skill ディレクトリから。Claude Code v2.1.269 以降が必要）:

```bash
cd skills/preparatory-refactoring
claude plugin eval . --allow-tools Write,Edit,Bash --scaffold
```

各ケースを skill あり / なしで実行し、レポートを `evals/results/` に書く。実際のモデル実行で課金される。`evals/results/` はコミットしない（リポジトリに `.gitignore` は無いので、手で除外すること）。

新しいケースを足すとき:

- フォルダ名は小文字・数字・ハイフンで、英字で始める。`results` / `mocks` / `node_modules` / `files` / `true` / `false` / `null` は使えない。
- `prompt.md` の設定ブロックに未知のキーを書くとケースの読み込みに失敗する。設定ブロックは最初の `---` で終わるため、説明文は `case.yaml` に書く。
- grader が 1 つも無いケースは読み込みに失敗する。検証する文は 1 ファイル 1 件にし、番号で順序を保つ。

## SKILL.md / references を編集するときの約束

- `SKILL.md` の「モードと読む範囲」表が、モードごとに読む参照ファイルと節の正本。`references/*.md` の冒頭は、`structure-and-diagnosis.md` を除く 4 ファイルがこの表を指す（`structure-and-diagnosis.md` は「SKILL.md の手順 2〜3 で読む」と書く）。
- `structure-and-diagnosis.md` の冒頭は「0. 事実確認」「4. 原因の分類」を、`timing-and-discipline.md` の冒頭は「3 節（実行の規律）」「4 節（停止条件）」を名指ししている。
- 節の見出しを改名・番号変更するときは、次を同時に直す。
  - `SKILL.md` の表と手順中の「」引用（「事実確認」「原因の分類」「実行の規律」「絡まったときの立て直し」「見落としやすい振る舞い変更」「変更履歴で結合を実測する」「0. 事実確認」「4. 原因の分類」）。
  - 各 `references/*.md` 冒頭の節名・節番号。`review-mode.md` と `timing-and-discipline.md` にも「見落としやすい振る舞い変更」への参照がある。
- `SKILL.md` 手順番号（「手順 2a」「手順 4」「手順 5」）と D1〜D3 は `references/structure-and-diagnosis.md`、`references/timing-and-discipline.md`、`references/techniques.md` から参照されている。`techniques.md` 冒頭付近は D1〜D3 と手法 M3 / M5 / M11 / M13 の対応を書いている。
- 手法番号 M1〜M22 は `techniques.md` の見出しが定義で、`SKILL.md` は「M1〜M22」の範囲を書いている。手法を増減したらこの範囲も直す。
- `SKILL.md` の計画テンプレートの固定文言（「該当なし（構造改善なし）」「なし判定:」）は `timing-and-discipline.md` にも書かれている。片方だけ変えない。
- evals の grader は、テンプレートの表名と固定文言を参照していない（`graders/` を grep して確認）。例外として `invoice-currency-plan/graders/07-assertion.md` はテンプレートの項目名「停止条件」を使う。依存先は次の 2 つ。
  - prompt が指定する成果物名（`plan.md` / `summary.md` / `review.md`）と、各ケースの入力ファイルの内容（tier の金額、郵便番号 `97`、`FREESHIP` など）。
  - `invoice-currency-plan` の grader 01 は「先に/後で/後日/やらない」、SKILL.md は「前/直後/後回し/しない」と書いており、語は一致していない。
- `SKILL.md` の自己テスト記載（`uv run "$SKILL_DIR/scripts/test_change_coupling.py"`）と README の記載（`python -m unittest`）は書式が異なる。どちらを残すかは未確認。

## 変更後の確認手順

1. 上記の自己テストを実行し、全件が通ることを確認する。
2. `SKILL.md` / `references/` / `evals/` を変えた場合は、`claude plugin eval` を実行して `evals/results/` のレポートで skill ありの結果を確認する（課金される）。
3. 節名・手順番号を変えた場合は、「」引用と `手順 n` を grep して参照切れが無いことを確認する。

## コミット

- skill 自身は、コミットメッセージに `refactor:` / `feat:` / `fix:` / `test:` を付け、構造変更と振る舞い変更を別コミットにすることを定めている（`SKILL.md` 手順 6）。
- このリポジトリの現状の履歴（`git log --oneline`）は 2 件で、どちらもこの接頭辞を使っていない（"Add preparatory-refactoring agent skill"、"Adopt skills CLI layout and document installation"）。履歴からは規約を読み取れない。
- skill 自身の規則に合わせることを推奨する。接頭辞を必須にするかは未決定。
