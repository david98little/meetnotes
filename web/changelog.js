/* MeetNotes 更新日志 — 新条目加在数组最前面 */
const CHANGELOG = [
  {
    version: "v0.7",
    date: "2026-09-30",
    items: [
      { type: "feat", text: "项目关键词支持映射格式（张老师→张鸿韦），转写错词强制改写为正确写法" },
      { type: "feat", text: "会议统计看板：年/月/周/日维度，六卡片 + 趋势图 + 项目分布 + 日历热力图，图表可点击查看对应会议" },
      { type: "feat", text: "摘要阶段 AI 自动归纳会议名称（≤20 字），手动命名的会议不被覆盖" },
      { type: "feat", text: "项目级关键词：分组头 🔑 编辑，与全局热词叠加注入整理/摘要，提升专名准确性" },
      { type: "fix", text: "重跑语音转写报“找不到分片文件”——重试链补上预处理步骤" },
    ],
  },
  {
    version: "v0.6",
    date: "2026-09-17",
    items: [
      { type: "feat", text: "会议项目分组：归组 / 筛选 / 重命名 / 解散，分组可折叠，会议行可拖拽移动分组" },
      { type: "feat", text: "设置改为全局弹窗（Esc / 点遮罩关闭）" },
      { type: "ui", text: "顶部精简为图标按钮，项目分组头悬浮操作" },
    ],
  },
  {
    version: "v0.5",
    date: "2026-09-16",
    items: [
      { type: "feat", text: "ASR 与文本模型双通道独立配置，支持跨厂商混搭（方舟 ASR + DeepSeek 官方文本引擎）" },
      { type: "feat", text: "macOS / Linux 支持：start.sh 一键启动 + mn 命令注册模板" },
      { type: "feat", text: "mn CLI 全量子命令 --json 化，Agent 可稳定解析" },
    ],
  },
  {
    version: "v0.4",
    date: "2026-09-16",
    items: [
      { type: "feat", text: "mn CLI 首发与 Agent 接入：transcribe / list / show / search / todo / export / rename / remove" },
      { type: "feat", text: "内置 meetnotes Skill（~/.agents/skills），codex / pi / claude 零配置调用" },
      { type: "feat", text: "会议标题行内编辑（✏️），列表即时同步" },
      { type: "ui", text: "音频回放条移至页面底部横跨全宽" },
    ],
  },
  {
    version: "v0.3",
    date: "2026-08-28",
    items: [
      { type: "feat", text: "首次开源发布：转录 → 整理 → 摘要 → 待办全流水线" },
      { type: "feat", text: "Web UI：上传/页面录音、文稿回放联动、行内编辑、导出 Markdown" },
      { type: "feat", text: "双转录引擎：火山方舟（云）/ 本地 faster-whisper（离线）" },
      { type: "feat", text: "静音感知切片并行转写、热词修正、失败步骤单独重跑" },
    ],
  },
];

const TYPE_META = {
  feat: ["✨ 新功能", "#059669", "#ecfdf5"],
  fix: ["🛠 修复", "#b45309", "#fef3c7"],
  ui: ["🎨 界面", "#4338ca", "#e0e7ff"],
};
