# preparatory-refactoring

振る舞い変更（機能追加・不具合修正）の前後に、振る舞いを変えない小さな構造改善を「入れるか / いつ / どこに / どこまで」判断して、計画・実行・レビューする Agent Skill です。依存関係と git 履歴（変更頻度、同時変更）から構造と結合を実測します。

## 使い方

```bash
cp -R preparatory-refactoring ~/.claude/skills/
```

Claude Code で「X を追加したいが先に整理すべきか」「refactor と feature が混ざった PR を分けたい」などと依頼すると使われます。

## 構成

- `preparatory-refactoring/SKILL.md` — 手順と出力テンプレート
- `preparatory-refactoring/references/` — 判断基準、手法、レビュー手順
- `preparatory-refactoring/scripts/change_coupling.py` — 変更頻度と同時変更の集計（`uv run` で実行）
- `preparatory-refactoring/evals/` — 動作確認用の評価ケース

テスト:

```bash
cd preparatory-refactoring/scripts && uv run python -m unittest test_change_coupling
```

## ライセンス

MIT
