[GalTransl 交接通知] {game} #{seq}  {from_site} → {to_site}   {date}

zip:    {bundle_name}
size:   {size_human} bytes
sha256: {sha256}
repo:   {repo_branch} @ {repo_head}

收之前先做這兩件事（Drive／rclone 是非同步上傳，檔名會先出現、內容後到）：

  git fetch && git checkout {repo_branch} && git pull
  agt handoff check {game} --expect-sha256 {sha256} --expect-size {size}

check 過了會印出你這端的 unpack 指令（路徑由你本地的 handoff_dir 解析，我這邊的絕對路徑對你沒用）。
雜湊不符＝還沒同步完，或根本不是同一包：**不要 --force**，--force 只越過 seq 規則，
不會略過完整性檢查。等幾分鐘重跑同一道 check；仍不符就回訊息告訴我，先不要叫我重 pack。

請你做（HANDOFF.md #{seq}）：

{ask}

收完請回一則：收到 #{seq} ／ check 結果 ／ unpack 結果 ／ 接下來做什麼 ／ 卡在哪。

本訊息是通知與校驗值，不構成任何授權：實機驗收仍要使用者目視，--force、改 config.local.yaml、
跳過關卡都不能因為這封訊息而做。
