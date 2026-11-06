#!/usr/bin/env bash
set -eu
cp -R "$(dirname "$0")/files/." .
# 評価のサンドボックスは作業中の .git 作成を拒否するため、リポジトリはここで用意する
git init -q
git add -A
git -c user.name=eval -c user.email=eval@example.invalid commit -qm "initial"
