# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""git 履歴からホットスポットと同時変更ペア（変更結合）を集計する。

使い方（SKILL_DIR はこのスキルのディレクトリ）:
    uv run "$SKILL_DIR/scripts/change_coupling.py" [--repo PATH] [--since DATE] [--until DATE]
        [--path PREFIX ...] [--max-files N] [--min-pair-count N]
        [--top N] [--warn-below N] [--partner PATH ...] [--format text|json]

挙動:
- マージコミットは常に除外する。ファイル変更のない空コミットは commits_empty に数え、
  commits_seen には含めない。
- 1 コミットで --max-files を超えるファイルを変えたコミット（一括整形、
  一括リネーム、依存更新など）は除外する。判定は --path での絞り込み前の全ファイル数で行う。
- リネームは古いコミットから順に追跡し、旧パスの履歴を新パスへ付け替える。
  集計はファイルの最終的なパス（削除済みなら最後のパス）で行う。
  削除後に同じパスで作り直したファイルは、内部では別のファイルとして追跡するが、
  最終パスが同じになるため集計では合算される。
- --path を指定すると、最終的なパスがその条件に一致するファイルだけを集計する。
  先頭の ./ と / は除去する。末尾が / なら接頭辞一致、そうでなければ
  「完全一致 または <PATH>/ の接頭辞」。
- --partner を指定すると、そのファイル（最終的なパスで完全一致）を変えたコミットの中で、
  ほかのどのファイルが一緒に変わったかを、回数と割合（同時変更回数 ÷ 指定ファイルの変更回数）で出す。
  --since / --until / --max-files で残ったコミットだけを数え、相手は --path に一致するものだけを出す
  （指定ファイル自身は --path に関係なく数える）。--min-pair-count は使わない。
  指定ファイルの変更回数が --warn-below 未満なら警告を出す。text 出力ではホットスポットと
  同時変更ペアを省略する（json には両方が入る）。
- GIT_DIR などの環境変数と、利用者の git 設定（ページャ、外部 diff など）の影響を受けない。
- bare リポジトリも対象にできる。
- 終了コード: 0 = 成功、2 = 入力や環境のエラー。

既知の制約:
- 履歴を 1 本の列（コミット日時ではなく git log --reverse の順）として処理するため、
  並行ブランチの片方でリネームし、もう片方で旧パスを変更していた場合、
  旧パス側の変更は付け替えられず、旧パスの行として別に残る。
- --since で期間を絞ると、期間より前のリネームは追跡できない。
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field

COMMIT_MARK = "\x01"
GIT_TIMEOUT_SEC = 300
MAX_FILES_RANGE = (2, 500)
BULK_WARN_RATIO = 0.2
RENAME_LIMIT = 100000

GIT_CONFIG = [
    "-c", "core.quotepath=off",
    "-c", "core.fsmonitor=false",
    "-c", "diff.relative=false",
    "-c", "diff.renames=true",
    "-c", f"diff.renameLimit={RENAME_LIMIT}",
    "-c", "log.showSignature=false",
]

# 呼び出し元（git フックなど）から引き継ぐと --repo 以外のリポジトリを読んでしまう変数
GIT_ENV_TO_DROP = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES",
)


class CouplingError(Exception):
    """利用者に見せるためのエラー。"""


def display(name: str) -> str:
    """内部表現（surrogateescape）を表示用の文字列にする。UTF-8 でないバイトは \\xNN になる。"""
    return name.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


@dataclass
class Result:
    repo: str
    filters: dict
    bare: bool = False
    commits_seen: int = 0
    commits_empty: int = 0
    commits_analyzed: int = 0
    commits_skipped_bulk: int = 0
    renames_followed: int = 0
    hotspots: list = field(default_factory=list)
    pairs: list = field(default_factory=list)
    partners: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "bare": self.bare,
            "filters": self.filters,
            "commits_seen": self.commits_seen,
            "commits_empty": self.commits_empty,
            "commits_analyzed": self.commits_analyzed,
            "commits_skipped_bulk": self.commits_skipped_bulk,
            "renames_followed": self.renames_followed,
            "hotspots": self.hotspots,
            "pairs": self.pairs,
            "partners": self.partners,
            "warnings": self.warnings,
        }


@dataclass
class GitOutput:
    returncode: int
    stdout: str  # surrogateescape で復号（ファイル名を失わない）
    stderr: str  # 表示用に復号


def git_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_TO_DROP}
    env["GIT_PAGER"] = "cat"
    env["LC_ALL"] = "C"  # git のメッセージを英語に固定して警告を判定できるようにする
    env["LANGUAGE"] = "C"
    return env


def run_git(repo: str, args: list[str]) -> GitOutput:
    cmd = ["git", "--no-pager", *GIT_CONFIG, "-C", repo, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, env=git_env(), timeout=GIT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        raise CouplingError(
            f"git が {GIT_TIMEOUT_SEC} 秒以内に終わらなかった。--since や --path で範囲を狭めること。"
        ) from None
    except OSError as e:
        raise CouplingError(f"git を起動できない: {e}") from None
    return GitOutput(
        returncode=proc.returncode,
        stdout=proc.stdout.decode("utf-8", "surrogateescape"),
        stderr=proc.stderr.decode("utf-8", "backslashreplace"),
    )


def check_repo(repo: str) -> tuple[str, bool]:
    if shutil.which("git") is None:
        raise CouplingError("git コマンドが見つからない。git をインストールして PATH に通すこと。")
    proc = run_git(repo, ["rev-parse", "--is-bare-repository"])
    if proc.returncode != 0:
        raise CouplingError(
            f"git リポジトリではない、またはアクセスできない: {repo}\n"
            f"git の出力: {proc.stderr.strip()}"
        )
    bare = proc.stdout.strip() == "true"
    loc = run_git(repo, ["rev-parse", "--absolute-git-dir" if bare else "--show-toplevel"])
    if loc.returncode != 0:
        raise CouplingError(f"リポジトリの場所を特定できない: {repo}\n git の出力: {loc.stderr.strip()}")
    top = loc.stdout.rstrip("\n")
    head = run_git(repo, ["rev-parse", "--verify", "--quiet", "HEAD"])
    if head.returncode != 0:
        raise CouplingError(f"コミット履歴が空: {display(top)}（最初のコミット後に再実行すること）")
    return top, bare


def parse_log(raw: str) -> list[list[tuple[str, ...]]]:
    """`git log -z --name-status --format=%x01%H` の出力を、古い順のコミット列に変換する。

    各コミットは変更の列。変更は ("R", old, new) / ("C", old, new) / (status, path)。
    ファイル名は NUL 区切りで受け取り、空白や記号を削らない。
    """
    commits: list[list[tuple[str, ...]]] = []
    tokens = raw.split("\0")
    i = 0
    current: list[tuple[str, ...]] | None = None
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if tok.startswith(COMMIT_MARK):
            current = []
            commits.append(current)
            continue
        # 状態トークン（A, M, D, T, R100, C075 など）。ヘッダ直後の改行だけを取り除く。
        status = tok.lstrip("\n")
        if not status or current is None:
            continue
        kind = status[0]
        if kind in ("R", "C"):
            if i + 1 >= len(tokens):
                break
            old, new = tokens[i], tokens[i + 1]
            i += 2
            current.append((kind, old, new))
        else:
            if i >= len(tokens):
                break
            current.append((kind, tokens[i]))
            i += 1
    return commits


def read_commits(
    repo: str, since: str | None, until: str | None
) -> tuple[list[list[tuple[str, ...]]], str]:
    args = [
        "log", "--no-merges", "--reverse", "--name-status", "-M", "-z",
        "--no-show-signature", "--no-ext-diff", "--no-textconv", "--no-color",
        f"--format={COMMIT_MARK}%H",
    ]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    proc = run_git(repo, args)
    if proc.returncode != 0:
        raise CouplingError(f"git log に失敗した: {proc.stderr.strip()}")
    return parse_log(proc.stdout), proc.stderr


def normalize_prefix(p: str) -> str:
    while True:
        if p.startswith("./"):
            p = p[2:]
        elif p.startswith("/"):
            p = p[1:]
        else:
            break
    return "" if p in ("", ".") else p


def matches(path: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return True
    for p in prefixes:
        if p == "":
            return True
        if p.endswith("/"):
            if path.startswith(p):
                return True
        elif path == p or path.startswith(p + "/"):
            return True
    return False


def validate(max_files: int, min_pair_count: int, top: int, warn_below: int) -> None:
    lo, hi = MAX_FILES_RANGE
    if not lo <= max_files <= hi:
        raise CouplingError(f"--max-files は {lo}〜{hi} の範囲で指定すること（指定値: {max_files}）。")
    if min_pair_count < 1:
        raise CouplingError(f"--min-pair-count は 1 以上で指定すること（指定値: {min_pair_count}）。")
    for name, value in (("--top", top), ("--warn-below", warn_below)):
        if value < 0:
            raise CouplingError(f"{name} は 0 以上で指定すること（指定値: {value}）。")


def analyze(
    repo: str = ".",
    since: str | None = None,
    until: str | None = None,
    prefixes: list[str] | None = None,
    max_files: int = 30,
    min_pair_count: int = 2,
    top: int = 20,
    warn_below: int = 30,
    partners: list[str] | None = None,
) -> Result:
    validate(max_files, min_pair_count, top, warn_below)
    prefixes = [normalize_prefix(p) for p in (prefixes or [])]
    partners = list(dict.fromkeys(normalize_prefix(p) for p in (partners or [])))
    if "" in partners:
        raise CouplingError("--partner にはファイルのパス（リポジトリルート相対）を指定すること。")
    top_dir, bare = check_repo(repo)
    result = Result(
        repo=display(top_dir),
        bare=bare,
        filters={
            "since": since,
            "until": until,
            "path_prefixes": [display(p) for p in prefixes],
            "max_files": max_files,
            "min_pair_count": min_pair_count,
            "top": top,
            "warn_below": warn_below,
            "partners": [display(p) for p in partners],
            "bulk_warn_ratio": BULK_WARN_RATIO,
        },
    )

    # ファイルの同一性を ID で追跡する。リネームでは ID を引き継ぎ、名前だけ更新する。
    path_to_id: dict[str, int] = {}
    id_name: dict[int, str] = {}
    next_id = itertools.count()

    def ident(path: str) -> int:
        if path not in path_to_id:
            fid = next(next_id)
            path_to_id[path] = fid
            id_name[fid] = path
        return path_to_id[path]

    commits, log_stderr = read_commits(repo, since, until)
    kept_commits: list[set[int]] = []
    for changes in commits:
        if not changes:
            result.commits_empty += 1
            continue
        result.commits_seen += 1
        ids: set[int] = set()
        for change in changes:
            kind = change[0]
            if kind == "R":
                old, new = change[1], change[2]
                fid = path_to_id.pop(old, None)
                if fid is None:  # 旧パスの履歴が範囲外（--since など）
                    fid = ident(new)
                else:
                    path_to_id[new] = fid
                    id_name[fid] = new
                    result.renames_followed += 1
                ids.add(fid)
            elif kind == "C":
                ids.add(ident(change[2]))
            elif kind == "D":
                ids.add(ident(change[1]))
                # 以後に同じパスで作られたファイルは新しい ID で追跡する。
                # 集計は最終パスで行うので、最終パスが同じなら合算される。
                path_to_id.pop(change[1], None)
            else:
                ids.add(ident(change[1]))
        if len(ids) > max_files:
            result.commits_skipped_bulk += 1
            continue
        kept_commits.append(ids)

    file_counts: Counter = Counter()
    pair_counts: Counter = Counter()
    for ids in kept_commits:
        names = sorted({id_name[f] for f in ids if matches(id_name[f], prefixes)})
        if not names:
            continue
        result.commits_analyzed += 1
        file_counts.update(names)
        pair_counts.update(itertools.combinations(names, 2))

    ranked_files = sorted(file_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    result.hotspots = [{"path": display(p), "commits": n} for p, n in ranked_files[: top or None]]

    pairs = []
    for (a, b), together in pair_counts.items():
        if together < min_pair_count:
            continue
        pairs.append(
            {
                "a": a,
                "b": b,
                "together": together,
                "a_commits": file_counts[a],
                "b_commits": file_counts[b],
                "b_given_a": round(together / file_counts[a], 3),
                "a_given_b": round(together / file_counts[b], 3),
            }
        )
    pairs.sort(key=lambda p: (-p["together"], -max(p["b_given_a"], p["a_given_b"]), p["a"], p["b"]))
    for p in pairs:
        p["a"], p["b"] = display(p["a"]), display(p["b"])
    result.pairs = pairs[: top or None]

    for partner in partners:
        own = 0
        companions: Counter = Counter()
        for ids in kept_commits:
            names = {id_name[f] for f in ids}
            if partner not in names:
                continue
            own += 1
            companions.update(n for n in names if n != partner and matches(n, prefixes))
        ranked = sorted(companions.items(), key=lambda kv: (-kv[1], kv[0]))
        result.partners.append(
            {
                "path": display(partner),
                "commits": own,
                "companions": [
                    {"path": display(n), "together": c, "ratio": round(c / own, 3)}
                    for n, c in ranked[: top or None]
                ],
            }
        )
        if own == 0:
            result.warnings.append(
                f"--partner {display(partner)} を変えたコミットがない。"
                "最終的なパス（リポジトリルート相対、リネーム後の名前）と期間を見直すこと。"
            )
        elif own < warn_below:
            result.warnings.append(
                f"--partner {display(partner)} の変更コミットが {own} 件しかない（目安 {warn_below} 件以上）。"
                "割合は偶然に左右されやすいので、傾向の参考程度に扱うこと。"
            )

    if "rename detection was skipped" in log_stderr or "too many files" in log_stderr:
        detail = " ".join(line.strip() for line in log_stderr.splitlines() if "rename" in line)
        result.warnings.append(
            f"git がリネーム検出の一部を省略した（{detail}）。リネーム前後の履歴が別の行に分かれている可能性がある。"
        )
    if result.commits_seen == 0:
        result.warnings.append("指定した期間にファイルを変更したコミットがない。--since / --until を見直すこと。")
    elif result.commits_analyzed == 0:
        result.warnings.append("条件に合うコミットがない。--path（リポジトリルートからの相対パス）を見直すこと。")
    if 0 < result.commits_analyzed < warn_below:
        result.warnings.append(
            f"分析対象コミットが {result.commits_analyzed} 件しかない（目安 {warn_below} 件以上）。"
            "割合は偶然に左右されやすいので、傾向の参考程度に扱うこと。"
        )
    if result.commits_seen and result.commits_skipped_bulk / result.commits_seen > BULK_WARN_RATIO:
        scope = "（--path での絞り込み前の全コミットに対する件数）" if prefixes else ""
        result.warnings.append(
            f"全コミット {result.commits_seen} 件中 {result.commits_skipped_bulk} 件を一括変更として除外した"
            f"（{BULK_WARN_RATIO:.0%} 超）{scope}。--max-files が小さすぎないか確認すること。"
        )
    return result


def render_text(result: Result) -> str:
    out = []
    f = result.filters
    out.append(f"repo: {result.repo}" + (" (bare)" if result.bare else ""))
    out.append(
        "filters: since={} until={} path={} max_files={} min_pair_count={} warn_below={}".format(
            f["since"] or "-", f["until"] or "-", ",".join(f["path_prefixes"]) or "-",
            f["max_files"], f["min_pair_count"], f["warn_below"],
        )
    )
    out.append(
        f"commits: seen={result.commits_seen} empty={result.commits_empty} "
        f"analyzed={result.commits_analyzed} skipped_bulk={result.commits_skipped_bulk} "
        f"renames_followed={result.renames_followed} (merges excluded)"
    )
    for w in result.warnings:
        out.append(f"WARNING: {w}")
    if result.partners:
        for p in result.partners:
            out.append("")
            out.append(f"## partner: {p['path']} (変更 {p['commits']} 回)")
            out.append("  together   ratio  path")
            if not p["companions"]:
                out.append("  (なし)")
            for c in p["companions"]:
                out.append(f"  {c['together']:>8}  {c['ratio']:>6.0%}  {c['path']}")
        return "\n".join(out)
    out.append("")
    out.append("## hotspots (変更回数)")
    if not result.hotspots:
        out.append("  (なし)")
    for h in result.hotspots:
        out.append(f"  {h['commits']:>5}  {h['path']}")
    out.append("")
    out.append("## co-change pairs (同時変更)")
    out.append("  together  P(b|a)  P(a|b)  a  <->  b")
    if not result.pairs:
        out.append("  (なし)")
    for p in result.pairs:
        out.append(
            f"  {p['together']:>8}  {p['b_given_a']:>6.0%}  {p['a_given_b']:>6.0%}  {p['a']}  <->  {p['b']}"
        )
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="git 履歴からホットスポットと同時変更ペアを集計する")
    ap.add_argument("--repo", default=".", help="対象リポジトリ（既定: カレントディレクトリ。bare も可）")
    ap.add_argument("--since", help="git log --since に渡す値（例: 2025-01-01, '6 months ago'）")
    ap.add_argument("--until", help="git log --until に渡す値")
    ap.add_argument("--path", action="append", default=[], dest="prefixes",
                    help="集計するパス（リポジトリルート相対、複数指定可、先頭の ./ と / は除去）。"
                         "末尾 / は接頭辞一致、それ以外は完全一致または <PATH>/ 配下")
    ap.add_argument("--max-files", type=int, default=30,
                    help="これを超えるファイル数を変えたコミットを一括変更として除外（2〜500、既定: 30）")
    ap.add_argument("--min-pair-count", type=int, default=2,
                    help="ペアとして出す最小同時変更回数（1 以上、既定: 2）")
    ap.add_argument("--top", type=int, default=20, help="各一覧の最大件数。0 で無制限（既定: 20）")
    ap.add_argument("--warn-below", type=int, default=30,
                    help="分析コミット数がこれ未満なら警告（0 以上、既定: 30）")
    ap.add_argument("--partner", action="append", default=[], dest="partners",
                    help="このファイル（最終的なパス、複数指定可）と一緒に変わったファイルを、"
                         "回数と割合（同時変更回数 ÷ このファイルの変更回数）で出す")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = analyze(
            repo=args.repo, since=args.since, until=args.until, prefixes=args.prefixes,
            max_files=args.max_files, min_pair_count=args.min_pair_count,
            top=args.top, warn_below=args.warn_below, partners=args.partners,
        )
    except CouplingError as e:
        msg = display(str(e))
        if args.format == "json":
            print(json.dumps({"error": msg}, ensure_ascii=False))
        print(f"error: {msg}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
