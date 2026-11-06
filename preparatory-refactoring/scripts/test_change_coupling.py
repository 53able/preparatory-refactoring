# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""change_coupling.py の自己テスト。

使い方:
    uv run scripts/test_change_coupling.py

一時ディレクトリに git リポジトリを作り、既知の履歴に対する集計結果を検証する。
一時ディレクトリは終了時に削除される。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "change_coupling.py"


def git_env(home: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.path.join(home, "gitconfig"),
            "HOME": home,
            "GIT_AUTHOR_NAME": "tester",
            "GIT_AUTHOR_EMAIL": "tester@example.invalid",
            "GIT_COMMITTER_NAME": "tester",
            "GIT_COMMITTER_EMAIL": "tester@example.invalid",
        }
    )
    return env


class Repo:
    def __init__(self, root: Path, home: str):
        self.root = root
        self.env = git_env(home)
        self.clock = 0

    def git(self, *args: str, date: str | None = None) -> str:
        env = dict(self.env)
        if date:
            env["GIT_AUTHOR_DATE"] = date
            env["GIT_COMMITTER_DATE"] = date
        proc = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=self.root, env=env, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout.strip()

    def commit(self, files: list[str], date: str | None = None) -> None:
        self.clock += 1
        for name in files:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"change {self.clock}\n")
        self.git("add", "--", *files)
        if date is None:
            date = f"2024-03-{self.clock:02d}T12:00:00+00:00"
        self.git("commit", "-q", "-m", f"c{self.clock}", date=date)

    def commit_staged(self, *extra: str) -> None:
        self.clock += 1
        date = f"2024-03-{self.clock:02d}T12:00:00+00:00"
        self.git("commit", "-q", *extra, "-m", f"c{self.clock}", date=date)

    def write_big(self, name: str, seed: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{seed} line {i}\n" for i in range(40)), encoding="utf-8")

    def rename(self, old: str, new: str) -> None:
        """git mv + 1 行追記（類似度が高いのでリネームとして検出される）。"""
        self.git("mv", old, new)
        with (self.root / new).open("a", encoding="utf-8") as fh:
            fh.write("renamed\n")
        self.git("add", "--", new)
        self.commit_staged()


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8",
    )


def make_base_dirs(prefix: str):
    tmp = tempfile.TemporaryDirectory(prefix=prefix)
    base = Path(tmp.name)
    home = base / "home"
    home.mkdir()
    (home / "gitconfig").write_text("", encoding="utf-8")
    return tmp, base, str(home)


class ChangeCouplingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="change-coupling-test-")
        base = Path(cls._tmp.name)
        home = base / "home"
        home.mkdir()
        (home / "gitconfig").write_text("", encoding="utf-8")
        cls.home = str(home)
        root = base / "repo"
        root.mkdir()
        repo = Repo(root, cls.home)
        repo.git("init", "-q")
        repo.commit(["old.txt"], date="2020-01-01T12:00:00+00:00")
        for _ in range(3):
            repo.commit(["a.py", "b.py"])
        repo.commit(["a.py"])
        repo.commit(["c.py"])
        # 一括変更: 6 ファイル（--max-files 5 で除外される想定）
        repo.commit(["a.py", "b.py", "c.py", "x1.py", "x2.py", "x3.py"])
        main_branch = repo.git("rev-parse", "--abbrev-ref", "HEAD")
        repo.git("checkout", "-q", "-b", "feature")
        repo.commit(["d.py"])
        repo.git("checkout", "-q", main_branch)
        repo.commit(["e.py"])
        repo.git("merge", "-q", "--no-ff", "-m", "merge feature", "feature",
                 date="2024-03-20T12:00:00+00:00")
        repo.commit(["a.py", "sub/f.py"])
        cls.root = str(root)

        empty = base / "empty"
        empty.mkdir()
        Repo(empty, cls.home).git("init", "-q")
        cls.empty = str(empty)
        notrepo = base / "notrepo"
        notrepo.mkdir()
        cls.notrepo = str(notrepo)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def json_run(self, *args: str) -> dict:
        proc = run_script("--repo", self.root, "--format", "json", "--max-files", "5", *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_counts_and_bulk_and_merge_exclusion(self):
        data = self.json_run()
        # 非マージ 10 件 = old, ab x3, a, c, bulk, d, e, a+f
        self.assertEqual(data["commits_seen"], 10)
        self.assertEqual(data["commits_skipped_bulk"], 1)
        self.assertEqual(data["commits_analyzed"], 9)
        hot = {h["path"]: h["commits"] for h in data["hotspots"]}
        self.assertEqual(hot["a.py"], 5)
        self.assertEqual(hot["b.py"], 3)
        self.assertNotIn("x1.py", hot)
        self.assertIn("d.py", hot)  # マージで取り込まれた側のコミットは数える
        self.assertEqual(data["hotspots"][0]["path"], "a.py")

    def test_pairs_and_conditional_ratios(self):
        data = self.json_run()
        self.assertEqual(len(data["pairs"]), 1)  # a+f は 1 回なので min_pair_count=2 で落ちる
        p = data["pairs"][0]
        self.assertEqual((p["a"], p["b"], p["together"]), ("a.py", "b.py", 3))
        self.assertAlmostEqual(p["b_given_a"], 0.6)
        self.assertAlmostEqual(p["a_given_b"], 1.0)
        data1 = self.json_run("--min-pair-count", "1")
        names = {(q["a"], q["b"]) for q in data1["pairs"]}
        self.assertIn(("a.py", "sub/f.py"), names)

    def test_bulk_threshold_can_be_raised(self):
        proc = run_script("--repo", self.root, "--format", "json", "--max-files", "10")
        data = json.loads(proc.stdout)
        self.assertEqual(data["commits_skipped_bulk"], 0)
        hot = {h["path"]: h["commits"] for h in data["hotspots"]}
        self.assertEqual(hot["a.py"], 6)

    def test_since_filter(self):
        data = self.json_run("--since", "2021-01-01")
        paths = {h["path"] for h in data["hotspots"]}
        self.assertNotIn("old.txt", paths)
        self.assertEqual(data["commits_seen"], 9)

    def test_path_prefix(self):
        data = self.json_run("--path", "sub/")
        self.assertEqual([h["path"] for h in data["hotspots"]], ["sub/f.py"])
        self.assertEqual(data["commits_analyzed"], 1)
        self.assertEqual(data["pairs"], [])

    def test_low_commit_warning(self):
        data = self.json_run()
        self.assertTrue(any("9 件" in w for w in data["warnings"]), data["warnings"])
        data = self.json_run("--warn-below", "5")
        self.assertFalse(any("しかない" in w for w in data["warnings"]))

    def test_no_match_warning(self):
        data = self.json_run("--path", "nope/")
        self.assertEqual(data["commits_analyzed"], 0)
        self.assertTrue(any("--path" in w for w in data["warnings"]))

    def test_text_output(self):
        proc = run_script("--repo", self.root, "--max-files", "5")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("## hotspots", proc.stdout)
        self.assertIn("a.py  <->  b.py", proc.stdout)
        self.assertIn("WARNING:", proc.stdout)

    def partner_of(self, data: dict, path: str) -> dict:
        found = [p for p in data["partners"] if p["path"] == path]
        self.assertEqual(len(found), 1, data["partners"])
        return found[0]

    def test_partner_counts_and_ratio(self):
        # a.py を変えた非一括コミット: ab x3, a, a+f = 5 件
        data = self.json_run("--partner", "a.py")
        p = self.partner_of(data, "a.py")
        self.assertEqual(p["commits"], 5)
        comp = {c["path"]: (c["together"], c["ratio"]) for c in p["companions"]}
        self.assertEqual(comp, {"b.py": (3, 0.6), "sub/f.py": (1, 0.2)})
        self.assertEqual(p["companions"][0]["path"], "b.py")
        self.assertEqual(data["filters"]["partners"], ["a.py"])
        self.assertIn("hotspots", data)

    def test_partner_multiple_and_dot_slash(self):
        data = self.json_run("--partner", "./b.py", "--partner", "sub/f.py")
        b = self.partner_of(data, "b.py")
        self.assertEqual(b["commits"], 3)
        self.assertEqual([(c["path"], c["together"], c["ratio"]) for c in b["companions"]],
                         [("a.py", 3, 1.0)])
        f = self.partner_of(data, "sub/f.py")
        self.assertEqual([(c["path"], c["ratio"]) for c in f["companions"]], [("a.py", 1.0)])

    def test_partner_respects_max_files(self):
        data = self.json_run("--partner", "a.py")
        comp = {c["path"] for c in self.partner_of(data, "a.py")["companions"]}
        self.assertNotIn("x1.py", comp)
        proc = run_script("--repo", self.root, "--format", "json", "--max-files", "10",
                          "--partner", "a.py")
        p = self.partner_of(json.loads(proc.stdout), "a.py")
        self.assertEqual(p["commits"], 6)
        comp = {c["path"]: (c["together"], c["ratio"]) for c in p["companions"]}
        self.assertEqual(comp["b.py"], (4, 0.667))
        self.assertEqual(comp["x1.py"], (1, 0.167))

    def test_partner_path_since_and_top(self):
        data = self.json_run("--partner", "a.py", "--path", "sub/")
        comp = [c["path"] for c in self.partner_of(data, "a.py")["companions"]]
        self.assertEqual(comp, ["sub/f.py"])
        data = self.json_run("--partner", "a.py", "--since", "2024-03-05")
        p = self.partner_of(data, "a.py")
        self.assertEqual(p["commits"], 2)  # a 単独 と a+f
        data = self.json_run("--partner", "a.py", "--top", "1")
        self.assertEqual(len(self.partner_of(data, "a.py")["companions"]), 1)

    def test_partner_warn_below(self):
        data = self.json_run("--partner", "a.py", "--warn-below", "10")
        self.assertTrue(any("--partner a.py" in w and "5 件" in w for w in data["warnings"]),
                        data["warnings"])
        data = self.json_run("--partner", "a.py", "--warn-below", "5")
        self.assertFalse(any("--partner" in w for w in data["warnings"]))

    def test_partner_absent_from_history(self):
        data = self.json_run("--partner", "nope.py")
        p = self.partner_of(data, "nope.py")
        self.assertEqual((p["commits"], p["companions"]), (0, []))
        self.assertTrue(any("nope.py" in w and "コミットがない" in w for w in data["warnings"]))
        # ディレクトリ名は完全一致しないので見つからない扱い
        data = self.json_run("--partner", "sub")
        self.assertEqual(self.partner_of(data, "sub")["commits"], 0)

    def test_partner_empty_value_is_error(self):
        proc = run_script("--repo", self.root, "--partner", "./")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--partner", proc.stderr)

    def test_partner_text_output(self):
        proc = run_script("--repo", self.root, "--max-files", "5", "--partner", "a.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("## partner: a.py (変更 5 回)", proc.stdout)
        self.assertRegex(proc.stdout, r"\n\s+3\s+60%\s+b\.py\n")
        self.assertNotIn("## hotspots", proc.stdout)

    def test_not_a_repo(self):
        proc = run_script("--repo", self.notrepo)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("git リポジトリではない", proc.stderr)
        proc = run_script("--repo", self.notrepo, "--format", "json")
        self.assertIn("error", json.loads(proc.stdout))

    def test_empty_history(self):
        proc = run_script("--repo", self.empty)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("コミット履歴が空", proc.stderr)

    def test_git_missing(self):
        env = dict(os.environ, PATH="")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", self.root],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("git コマンドが見つからない", proc.stderr)


ODD_NAMES = ["src/日本語 ファイル.py", 'src/q"uote.py', "src/ lead.py", "src/tab\there.py"]
BULK_EXTRA = [f"bulk/f{i}.py" for i in range(5)]


class EdgeCaseTest(unittest.TestCase):
    """ファイル名、リネーム、--path の境界、--max-files との組み合わせ、値の検証。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp, base, home = make_base_dirs("change-coupling-edge-")
        cls.home = home
        root = base / "repo"
        root.mkdir()
        repo = Repo(root, home)
        repo.git("init", "-q")
        # 1-2: 特殊なファイル名を含む同時変更 x2
        repo.commit(["src/main.py", *ODD_NAMES])
        repo.commit(["src/main.py", *ODD_NAMES])
        # 3: 接頭辞境界の確認用（src2/ は src に一致してはいけない）
        repo.commit(["src/main.py", "src2/other.py"])
        # 4-5: リネーム前の履歴
        old = root / "lib" / "old_name.py"
        old.parent.mkdir(parents=True)
        old.write_text("".join(f"line {i}\n" for i in range(40)), encoding="utf-8")
        repo.commit(["lib/old_name.py"])
        repo.commit(["lib/old_name.py"])
        # 6: git mv + 小さな修正（リネームとして検出される）
        repo.git("mv", "lib/old_name.py", "lib/new_name.py")
        repo.commit(["lib/new_name.py"])
        # 7: リネーム後
        repo.commit(["lib/new_name.py"])
        # 8-9: 一括変更（6 ファイル）x2。--max-files 5 で除外される
        repo.commit(["src/main.py", *BULK_EXTRA])
        repo.commit(["src/main.py", *BULK_EXTRA])
        cls.root = str(root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def json_run(self, *args: str) -> dict:
        proc = run_script("--repo", self.root, "--format", "json", *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_odd_file_names_are_exact(self):
        data = self.json_run("--max-files", "10", "--path", "src/")
        hot = {h["path"]: h["commits"] for h in data["hotspots"]}
        for name in ODD_NAMES:
            self.assertEqual(hot.get(name), 2, (name, hot))
        pair_names = {(p["a"], p["b"]) for p in data["pairs"]}
        self.assertIn(tuple(sorted(["src/main.py", "src/日本語 ファイル.py"])), pair_names)

    def test_odd_file_names_text_output(self):
        proc = run_script("--repo", self.root, "--path", "src/")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("src/日本語 ファイル.py", proc.stdout)
        self.assertIn('src/q"uote.py', proc.stdout)

    def test_rename_is_followed(self):
        data = self.json_run("--path", "lib/")
        hot = {h["path"]: h["commits"] for h in data["hotspots"]}
        self.assertEqual(hot, {"lib/new_name.py": 4})
        self.assertGreaterEqual(data["renames_followed"], 1)

    def test_path_boundary(self):
        data = self.json_run("--path", "src", "--max-files", "10")
        paths = {h["path"] for h in data["hotspots"]}
        self.assertIn("src/main.py", paths)
        self.assertNotIn("src2/other.py", paths)
        data = self.json_run("--path", "src2")
        self.assertEqual([h["path"] for h in data["hotspots"]], ["src2/other.py"])
        data = self.json_run("--path", "src2/other.py")
        self.assertEqual([h["path"] for h in data["hotspots"]], ["src2/other.py"])

    def test_path_dot_slash_is_stripped(self):
        a = self.json_run("--path", "./src/", "--max-files", "10")
        b = self.json_run("--path", "src/", "--max-files", "10")
        self.assertEqual(a["hotspots"], b["hotspots"])
        self.assertEqual(a["filters"]["path_prefixes"], ["src/"])
        c = self.json_run("--path", "/src/", "--max-files", "10")
        self.assertEqual(c["hotspots"], b["hotspots"])

    def test_bare_repository(self):
        bare = Path(self._tmp.name) / "bare.git"
        subprocess.run(["git", "clone", "-q", "--bare", self.root, str(bare)],
                       check=True, capture_output=True, env=git_env(self.home))
        a = self.json_run("--max-files", "10")
        proc = run_script("--repo", str(bare), "--format", "json", "--max-files", "10")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        b = json.loads(proc.stdout)
        self.assertTrue(b["bare"])
        self.assertEqual(a["hotspots"], b["hotspots"])

    def test_ignores_inherited_git_env(self):
        # フック内から呼ばれた状況の再現: GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE が別リポジトリを指す
        other = Path(self._tmp.name) / "other"
        other.mkdir(exist_ok=True)
        orepo = Repo(other, self.home)
        orepo.git("init", "-q")
        orepo.commit(["only_in_other.py"])
        env = dict(os.environ, GIT_DIR=str(other / ".git"), GIT_WORK_TREE=str(other),
                   GIT_INDEX_FILE=str(other / ".git" / "index"),
                   GIT_CEILING_DIRECTORIES=str(Path(self._tmp.name)))
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", self.root, "--format", "json", "--max-files", "10"],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        paths = {h["path"] for h in data["hotspots"]}
        self.assertNotIn("only_in_other.py", paths)
        self.assertIn("src/main.py", paths)
        self.assertEqual(os.path.realpath(data["repo"]), os.path.realpath(self.root))

    def test_path_with_max_files(self):
        data = self.json_run("--path", "src", "--max-files", "5")
        hot = {h["path"]: h["commits"] for h in data["hotspots"]}
        self.assertEqual(hot["src/main.py"], 3)  # 一括変更 2 件は絞り込み前の件数で除外
        self.assertEqual(data["commits_skipped_bulk"], 2)
        self.assertEqual(data["commits_analyzed"], 3)
        self.assertTrue(any("全コミット 9 件中 2 件" in w and "--path" in w for w in data["warnings"]),
                        data["warnings"])
        data = self.json_run("--path", "src", "--max-files", "10")
        hot = {h["path"]: h["commits"] for h in data["hotspots"]}
        self.assertEqual(hot["src/main.py"], 5)

    def test_filters_include_thresholds(self):
        data = self.json_run("--warn-below", "7")
        self.assertEqual(data["filters"]["warn_below"], 7)
        self.assertIn("bulk_warn_ratio", data["filters"])

    def test_value_validation(self):
        cases = [
            ("--max-files", "1"), ("--max-files", "501"),
            ("--top", "-1"), ("--min-pair-count", "0"), ("--min-pair-count", "-1"),
        ]
        for opt, val in cases:
            with self.subTest(opt=opt, val=val):
                proc = run_script("--repo", self.root, opt, val)
                self.assertEqual(proc.returncode, 2, proc.stdout)
                self.assertIn(opt, proc.stderr)
                proc = run_script("--repo", self.root, "--format", "json", opt, val)
                self.assertEqual(proc.returncode, 2)
                self.assertIn("error", json.loads(proc.stdout))
        for opt, val in [("--max-files", "2"), ("--max-files", "500"), ("--top", "0"),
                         ("--min-pair-count", "1")]:
            with self.subTest(opt=opt, val=val):
                self.assertEqual(run_script("--repo", self.root, opt, val).returncode, 0)


class HistoryTest(unittest.TestCase):
    """リネーム連鎖、旧パスの作り直し、削除、空コミット、--since との組み合わせ。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp, base, home = make_base_dirs("change-coupling-history-")
        root = base / "repo"
        root.mkdir()
        r = Repo(root, home)
        r.git("init", "-q")
        r.write_big("a.txt", "alpha")
        r.commit(["a.txt"])            # c1  2024-03-01
        r.commit(["a.txt"])            # c2
        r.rename("a.txt", "b.txt")     # c3
        r.commit(["b.txt"])            # c4  2024-03-04
        r.rename("b.txt", "c.txt")     # c5
        r.commit(["c.txt"])            # c6
        r.write_big("x.txt", "xray")
        r.commit(["x.txt"])            # c7
        r.rename("x.txt", "y.txt")     # c8
        r.write_big("x.txt", "brand-new-unrelated-content")
        r.commit(["x.txt"])            # c9  旧パスに別ファイルを作り直す
        r.commit(["z.txt"])            # c10
        r.git("rm", "-q", "z.txt")
        r.commit_staged()              # c11 削除
        r.commit_staged("--allow-empty")  # c12 空コミット
        cls.root = str(root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def json_run(self, *args: str) -> dict:
        proc = run_script("--repo", self.root, "--format", "json", "--top", "0", *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_rename_chain_and_recreate_and_delete(self):
        data = self.json_run()
        hot = {h["path"]: h["commits"] for h in data["hotspots"]}
        self.assertEqual(hot, {"c.txt": 6, "y.txt": 2, "x.txt": 1, "z.txt": 2})
        self.assertEqual(data["renames_followed"], 3)

    def test_empty_commit_is_separate(self):
        data = self.json_run()
        self.assertEqual(data["commits_empty"], 1)
        self.assertEqual(data["commits_seen"], 11)
        self.assertEqual(data["commits_analyzed"], 11)

    def test_since_with_rename(self):
        data = self.json_run("--since", "2024-03-04T00:00:00+00:00")
        hot = {h["path"]: h["commits"] for h in data["hotspots"]}
        # c4 以降: b.txt(c4) は c5 で c.txt に付け替えられる。a→b のリネームは範囲外
        self.assertEqual(hot["c.txt"], 3)
        self.assertNotIn("b.txt", hot)
        self.assertNotIn("a.txt", hot)
        self.assertEqual(data["renames_followed"], 2)


class NonUtf8NameTest(unittest.TestCase):
    """UTF-8 でない別々のファイル名が 1 つにまとまらないこと。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp, base, home = make_base_dirs("change-coupling-bytes-")
        root = base / "repo"
        root.mkdir()
        r = Repo(root, home)
        r.git("init", "-q")
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=b"x\n", cwd=root,
                              env=r.env, capture_output=True, check=True).stdout.decode().strip()
        for n in range(2):
            for raw in (b"bin/\xff.txt", b"bin/\xfe.txt"):
                content = subprocess.run(["git", "hash-object", "-w", "--stdin"],
                                         input=f"v{n}\n".encode(), cwd=root, env=r.env,
                                         capture_output=True, check=True).stdout.decode().strip()
                subprocess.run([b"git", b"update-index", b"--add", b"--cacheinfo",
                                b"100644," + (content or blob).encode() + b"," + raw],
                               cwd=root, env=r.env, capture_output=True, check=True)
            r.commit_staged()
        cls.root = str(root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_distinct_names(self):
        proc = run_script("--repo", self.root, "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        hot = {h["path"]: h["commits"] for h in data["hotspots"]}
        self.assertEqual(hot, {"bin/\\xfe.txt": 2, "bin/\\xff.txt": 2})
        proc = run_script("--repo", self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("bin/\\xff.txt", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
