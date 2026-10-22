# 每日 03:30（Asia/Shanghai）

这些文件只是模板，不要在本仓库的安装步骤里加载它们。

交易日按 Asia/Shanghai 计算，与机器时区无关。launchd 的 `StartCalendarInterval` 用的是 Mac 的系统时区，所以 Mac 应设为上海时间，03:30 才会落在上海凌晨。如果机器保持 UTC，把 Hour 改成 19、Minute 改成 30，对应的是前一日 19:30 UTC，也就是上海时间 03:30。

把 `__REPO__` 换成仓库绝对路径，把 `__UV__` 换成 `uv` 的绝对路径。日志目录需要事先存在。

```bash
mkdir -p __REPO__/logs
cp deploy/com.tradeguard.daily.plist ~/Library/LaunchAgents/
# 编辑路径后再：
launchctl load ~/Library/LaunchAgents/com.tradeguard.daily.plist
```

cron 示例（在上海时区的机器上，或支持 `CRON_TZ` 的 cron）：

```cron
CRON_TZ=Asia/Shanghai
30 3 * * * cd __REPO__ && __UV__ run tradeguard pipeline daily --market CN >> __REPO__/logs/tradeguard-daily.log 2>&1
```

同一命令可以重复执行：已补齐的标的不会再次下载，已有成功摘要的交易日不会重复扫描，除非用 `--date` 或 `--from/--to` 指定重扫。
