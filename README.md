# preparatory-refactoring

振る舞い変更（機能追加・不具合修正）の前後に、振る舞いを変えない小さな構造改善を「入れるか / いつ / どこに / どこまで」判断して、計画・実行・レビューする Agent Skill です。依存関係と git 履歴（変更頻度、同時変更）から構造と結合を実測します。

[skills](https://github.com/vercel-labs/skills) CLI の形式（`skills/<name>/SKILL.md`）に従っています。

## インストール

Node.js 22.20 以降が必要です。

```bash
# 現在のプロジェクトに入れる（対象のエージェントを対話で選ぶ）
npx skills add 53able/preparatory-refactoring

# Claude Code 向けに、全プロジェクトで使えるように入れる
npx skills add 53able/preparatory-refactoring -g -a claude-code

# 入れずに中身を確認する
npx skills add 53able/preparatory-refactoring --list
```

更新は `npx skills update preparatory-refactoring`、削除は `npx skills remove preparatory-refactoring` です。

同梱スクリプトは [uv](https://docs.astral.sh/uv/) で実行します（`uv run scripts/change_coupling.py ...`）。git 履歴の集計を使うため、対象リポジトリに git が必要です。

<details>
<summary>CLI を使わずに入れる場合</summary>

```bash
git clone https://github.com/53able/preparatory-refactoring.git
cp -R preparatory-refactoring/skills/preparatory-refactoring ~/.claude/skills/
```

</details>

## 使い方

エージェントに次のように依頼すると使われます。

- 「X を追加したいが、先に整理すべきか判断して計画を書いて」
- 「必要ならリファクタしてから実装して」
- 「この PR は refactor と feature が混ざっているので分け方を提案して」
- 「技術的負債をどこから返すべきか」

## 構成

```
skills/preparatory-refactoring/
├── SKILL.md                     手順と出力テンプレート
├── references/                  判断基準、手法、レビュー手順
├── scripts/change_coupling.py   変更頻度と同時変更の集計
├── scripts/test_change_coupling.py
└── evals/                       動作確認用の評価ケース
```

テスト:

```bash
cd skills/preparatory-refactoring/scripts && uv run python -m unittest test_change_coupling
```

## ライセンス

[MIT](LICENSE)
