# AI信息雷达 · 任务清单

> 当前详细路线图以 [docs/development-plan.md](docs/development-plan.md) 为准。下面的“已完成”主要保留历史记录，不代表当前架构仍使用当时的旧流程。

## 当前唯一下一任务

- [ ] 补齐 GitHub、Product Hunt、Qwen、DeepSeek 的可靠 `published_at`，确保抓到的高价值信息可以在不破坏日期隔离的前提下进入最终日报。

## 当前后续顺序

1. 发布时间完整性和最终日报覆盖。
2. GitHub、Reddit、Product Hunt 信源稳定性。
3. 统一 1～5 星评价标准。
4. AI 成本、耗时和质量记录。
5. 开源与可复现发布准备。

## 已完成

- [x] 项目骨架与种子日报（2026-08-05）
- [x] Flask 应用：新闻门户首页 + 日报详情页
- [x] 日报生成脚本（抓取素材 + 调用路由器 + 降级策略）
- [x] 项目文档（README/rules/changelog）
- [x] 浏览器验证首页与详情页渲染效果
- [x] start.bat 双击启动脚本（纯ASCII+CRLF，编码安全）
- [x] 生成 2026-08-06 日报
- [x] Windows 计划任务：每天 08:33 自动生成日报
- [x] 学习建议板块添加可点击学习链接
- [x] 日报新增AI智能体推荐模块
- [x] **实时信息采集模块**：`src/collector.py` + `src/sources/` 包，9信源并发采集→过滤→分类→评分
- [x] **已读/未读追踪**：`data/read_status.json` 持久化 + 首页未读/已读分区 + 阅读自动标记
- [x] **自动补录缺失日报**：启动时后台线程扫描缺失日期，自动采集+AI生成补齐
- [x] **生成 2026-08-08 ~ 2026-08-10 日报**：补齐8月8日-10日共3期日报
- [x] **手机版 Android APK**：WebView 壳应用 + 手工构建工具链，成品 `android/dist/ai-radar.apk`
  - [x] 下载构建工具链（build-tools 34 + android.jar + Microsoft JDK 17）
  - [x] 编写应用源码（MainActivity 地址输入 + ReaderActivity WebView 阅读页）
  - [x] 雷达风格启动图标（PIL 生成各密度）
  - [x] 编译 → dex → 对齐 → 签名 打包流程（build.bat 一键）
  - [x] Windows 防火墙放行 8899 + 局域网连通测试
- [x] **手机版离线改造（v1.7）**：WebView 壳 → 离线优先 App
  - [x] `bundle_reports.py`：日报预渲染打包进 APK assets（自包含 HTML + 索引）
  - [x] 原生日报列表（未读红点/A级徽章/统计）+ 本地已读存储
  - [x] 离线阅读器 + 上一篇/下一篇导航 + 外链跳浏览器
  - [x] 后台同步 API（`/api/reports` + `/api/read`）+ 已读双向合并
  - [x] 重新打包验证（assets 进包、签名正常）→ 发送到手机

## 早期备选需求（需按新路线图重新排序）

- [ ] 首页"实时快讯"模块（实时采集数据的可视化展示）
- [ ] 日报搜索与关键词筛选
- [ ] 按板块（模型/工具/机会）分类浏览
- [ ] RSS 输出，方便订阅
- [ ] 自动生成后通知（如写入提示或弹窗）
- [ ] 中文信源接入（机器之心、量子位、36Kr AI频道）
- [ ] WebSocket 实时推送（采集到A级事件后浏览器弹通知）
