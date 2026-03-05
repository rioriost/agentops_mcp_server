# Draft for 0.3.1: Refactor main.py continued

## Background
0.3.0でmain.pyを部分的にクラスに分割したが、main.pyはまだ大きい。

## Goal
- main.py全体にクラスを導入して、クラスごとにファイルを分割する。

## Acceptance criteria
- バージョン0.2.3と外面的な動作が変わらないこと＝tool呼び出しと結果は同じ
- カバレッジ90%以上
