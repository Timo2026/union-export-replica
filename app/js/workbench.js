/* Union Export Agent Workbench · 融合版 Mock（不接真 API）
   来源：C′ 工程壳 + workbench-v4-web 交互；已修 draft 发送 / 随机门禁 / 链名 */
(function () {
  "use strict";

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  var CHAIN = ["INTAKE", "RFQ", "DFM", "VERIFY", "QUOTE", "REPLY", "CRM"];

  var MAILS = [
    {
      id: "M-2201", from: "采购 · 徐工集团 · Mr. Wang",
      subject: "RFQ #A11 — DIN 2527 盲板法兰 1200 件 · 交期 26-10-15",
      st: "NEW", badges: ["🔒锁价路径"], time: "09:42",
      body: "Dear Supplier,\n\n徐工集团采购部，随附图纸 DIN2527-2023 盲板法兰：\n\n1. 材质：S355JR\n2. 尺寸：DN100 PN16，OD 172 × t 18\n3. 数量：1200 pcs，年框架\n4. 表面：发黑\n5. 交期：2026-10-15（FOB 上海）\n\n请 24h 内回复最优价与 DFM 意见。",
      ctx: "徐工集团 · 工程机械主机厂 · 年采购额 ¥4.2M",
      scenario: "quote_path",
      stage: "RFQ",
      customer: { name: "徐工集团", country: "CN", note: "年框架 · 复购高" },
      history: [
        { t: "09-16", e: "PO 确认", d: "订单 P88-99 提前付款", tone: "ok" },
        { t: "09-12", e: "二次询价", d: "#A07 法兰 300 件", tone: "ok" },
        { t: "09-02", e: "质量事件", d: "发黑花斑 · postmortem 已入库", tone: "warn" }
      ],
      geometry: { file: "DIN2527-2023_A11.step", vol: "1.24e-4 m³", mass: "0.97 kg", util: "78%" },
      evidence: {
        rag: "待查询", step: "待锁定", pm: "1 条"
      }
    },
    {
      id: "M-2202", from: "甲方转包 · 三一重工",
      subject: "量产 M37 — 阀块超声清洗后表面白斑 · 需 HITL",
      st: "HITL", badges: ["🛡HITL", "💬3"], time: "昨天 16:20",
      body: "白斑问题第三次复现。客户索赔窗口今天 18:00 关闭，需决策：\nA) 返工喷砂（+3 天 · +¥0.4/pc）\nB) 折价接收（-2.5%）\n附件：金相图 + 显微照片。",
      ctx: "三一重工 · 甲方转包 · 返工历史 2 批",
      scenario: "hitl_fixed",
      stage: "VERIFY",
      customer: { name: "三一重工", country: "CN", note: "转包 · 质量敏感" },
      history: [
        { t: "09-15", e: "质量复现", d: "白斑第 3 批", tone: "warn" },
        { t: "09-08", e: "FAI", d: "M37 第二批 12/12 PASS", tone: "ok" },
        { t: "09-02", e: "返工", d: "喷砂返工 2 批", tone: "warn" }
      ],
      geometry: { file: "M37-valve.step", vol: "2.10e-4 m³", mass: "1.62 kg", util: "71%" },
      evidence: { rag: "3 案例", step: "已锁定 (LOCKED)", pm: "返工史" }
    },
    {
      id: "M-2203", from: "新询盘 · 中联重科",
      subject: "RFQ #B04 — 泵车支腿销轴 840 件 · 45# 调质",
      st: "NEW", badges: ["🔒"], time: "昨天 11:05",
      body: "外径 85 h7，长 480，调质 HRC24-28，发黑。报价越快越好。",
      ctx: "中联重科 · 新客户 · 无历史",
      scenario: "quote_path",
      stage: "RFQ",
      customer: { name: "中联重科", country: "CN", note: "新客户" },
      history: [{ t: "09-14", e: "新询盘", d: "销轴 840 件", tone: "ok" }],
      geometry: { file: "ZL-B04-shaft.step", vol: "8.02e-4 m³", mass: "6.30 kg", util: "82%" },
      evidence: { rag: "待查询", step: "待上传", pm: "无" }
    },
    {
      id: "M-2204", from: "老客户 · 卡特彼勒（中国）",
      subject: "PO 跟进 #P88 — 上批 45# 轴套提前付款",
      st: "PASS", badges: ["✅PASS"], time: "09-16",
      body: "订单 P88-99 已确认，财务通知本周五提前付款。",
      ctx: "卡特彼勒 · 年采购额 ¥8.1M · 准时率 100%",
      scenario: "pass_only",
      stage: "CRM",
      customer: { name: "卡特彼勒", country: "CN", note: "准时率 100%" },
      history: [{ t: "09-16", e: "付款确认", d: "P88-99", tone: "ok" }],
      geometry: { file: "P88-sleeve.step", vol: "3.10e-4 m³", mass: "2.40 kg", util: "90%" },
      evidence: { rag: "2 案例", step: "已锁定 (LOCKED)", pm: "无异常" }
    },
    {
      id: "M-2205", from: "外协 · 华中精工",
      subject: "后处理异常 — 阳极氧化色差 ΔE=3.8 · BLOCKED",
      st: "BLOCKED", badges: ["🚫BLOCKED"], time: "09-15",
      body: "内六角块 600pcs 氧化色差超标。换膜系还是分色出货？",
      ctx: "华中精工 · 外协 · 质量事件 1",
      scenario: "blocked_fixed",
      stage: "DFM",
      customer: { name: "华中精工", country: "CN", note: "外协" },
      history: [{ t: "09-15", e: "色差超标", d: "ΔE=3.8", tone: "warn" }],
      geometry: { file: "hex-block.step", vol: "5.02e-5 m³", mass: "0.14 kg", util: "64%" },
      evidence: { rag: "工艺 FAQ", step: "已解析", pm: "质量 1" }
    },
    {
      id: "M-2206", from: "新客户 · 特变电工",
      subject: "RFQ #C12 — 变压器散热器安装板 4 尺寸组",
      st: "NEW", badges: ["🔒"], time: "09-12",
      body: "4 组尺寸共 2400 件，6061-T6 阳极氧化银白。返修率要求 < 0.5%。",
      ctx: "特变电工 · 新客户 · 铜价联动",
      scenario: "quote_path",
      stage: "INTAKE",
      customer: { name: "特变电工", country: "CN", note: "铜价联动条款" },
      history: [{ t: "09-12", e: "新询盘", d: "散热器安装板", tone: "ok" }],
      geometry: { file: "TB-C12-plate.step", vol: "4.20e-4 m³", mass: "1.13 kg", util: "76%" },
      evidence: { rag: "待查询", step: "待上传", pm: "无" }
    },
    {
      id: "M-2207", from: "供应商 · 广东远航 CNC",
      subject: "产能确认 — #A11 法兰 1200 件可承接",
      st: "NEW", badges: ["🏭供应商"], time: "09-14",
      body: "三轴 + 四轴卧加均可，打样周期 3 天，量产 15 天。价格按框架协议浮动 5%。",
      ctx: "广东远航 · 框架供应商 · 产能 15d",
      scenario: "pass_only",
      stage: "CRM",
      customer: { name: "广东远航 CNC", country: "CN", note: "框架供应商" },
      history: [{ t: "09-14", e: "产能确认", d: "1200 pcs / 15d", tone: "ok" }],
      geometry: { file: "supplier-A11.step", vol: "1.24e-4 m³", mass: "0.97 kg", util: "78%" },
      evidence: { rag: "框架协议", step: "已锁定 (LOCKED)", pm: "无" }
    },
    {
      id: "M-2208", from: "QA · 内部检验",
      subject: "FAI 报告 — M37 阀块第二批 12/12 PASS",
      st: "PASS", badges: ["✅PASS", "📎"], time: "09-13",
      body: "GD&T 全项合格，粗糙度 Ra0.8 达标。报告已存 VDC。",
      ctx: "内部检验 · FAI 12/12",
      scenario: "pass_only",
      stage: "CRM",
      customer: { name: "内部 QA", country: "CN", note: "FAI 报告" },
      history: [{ t: "09-13", e: "FAI PASS", d: "12/12 项", tone: "ok" }],
      geometry: { file: "M37-valve.step", vol: "2.10e-4 m³", mass: "1.62 kg", util: "71%" },
      evidence: { rag: "QA 记录", step: "已上传 VDC", pm: "无异常" }
    },
    {
      id: "M-2209", from: "风控 · 合规通知",
      subject: "Sanction 名单命中 — 无雷同，继续",
      st: "PASS", badges: ["✅PASS"], time: "09-10",
      body: "全量比对完成，本轮无禁运地区。",
      ctx: "风控 · sanction 全量比对",
      scenario: "pass_only",
      stage: "CRM",
      customer: { name: "合规组", country: "CN", note: "Sanction 比对" },
      history: [{ t: "09-10", e: "合规通过", d: "无雷同", tone: "ok" }],
      geometry: { file: "compliance-batch.csv", vol: "—", mass: "—", util: "—" },
      evidence: { rag: "sanction_index", step: "—", pm: "无" }
    },
    {
      id: "M-2210", from: "老客户 · 徐工",
      subject: "复购 — #A07 法兰 300 件（去年同期同款）",
      st: "PASS", badges: ["✅PASS", "💬1"], time: "09-11",
      body: "按 2025 年合同价 + 铜价联动重报，客户历史 30 天内有 2 次复购。",
      ctx: "徐工集团 · 30 天复购 2 次",
      scenario: "pass_only",
      stage: "CRM",
      customer: { name: "徐工集团", country: "CN", note: "复购老客户" },
      history: [
        { t: "09-11", e: "复购询价", d: "#A07 法兰 300 件", tone: "ok" },
        { t: "08-15", e: "去年成交", d: "同款 ¥105.6/pc", tone: "ok" }
      ],
      geometry: { file: "XG-A07-flange.step", vol: "9.80e-5 m³", mass: "0.77 kg", util: "80%" },
      evidence: { rag: "3 案例", step: "已锁定 (LOCKED)", pm: "无" }
    }
  ];

  var SKILLS = [
    { id: "chat_understand", name: "意图理解", ico: "💬", iron: "llm_proposal", g: "对话编排", desc: "自然语言 → intent + slots" },
    { id: "rag_recall", name: "RAG 召回", ico: "🔍", iron: "none", g: "对话编排", desc: "crm + rag + postmortem" },
    { id: "context_lookup", name: "上下文聚合", ico: "🗂", iron: "none", g: "对话编排", desc: "1 次拉 8 区" },
    { id: "skill_dispatch", name: "编排调度", ico: "🎯", iron: "none", g: "对话编排", desc: "dispatcher · bound_context" },
    { id: "cite_evidence", name: "引用证据", ico: "🔗", iron: "none", g: "对话编排", desc: "双轨引用，不改写数字" },
    { id: "suggest_reply", name: "草稿建议", ico: "📝", iron: "draft_only", g: "对话编排", desc: "信封 subject/body/locked" },
    { id: "parse_rfq", name: "解析 RFQ", ico: "📧", iron: "deterministic", g: "业务管道", desc: "邮件 → 需求槽位" },
    { id: "extract_specs", name: "提取规格", ico: "📐", iron: "llm_proposal", g: "业务管道", desc: "图纸参数结构化" },
    { id: "check_dfm", name: "DFM 检查", ico: "🔍", iron: "deterministic", g: "业务管道", desc: "薄壁 / 深孔 / 共面度" },
    { id: "calc_quote", name: "算报价", ico: "💰", iron: "deterministic 🔒", g: "业务管道", desc: "引擎裁决 + sha16 锁" },
    { id: "verify_gate", name: "跑门禁", ico: "🛡", iron: "deterministic", g: "业务管道", desc: "辟牟援推止 · 场景固定" },
    { id: "write_reply", name: "起草回复", ico: "✍️", iron: "draft_only", g: "业务管道", desc: "无 send · 仅采纳/丢弃" },
    { id: "render_thumbnail", name: "STEP 预览", ico: "🧊", iron: "deterministic", g: "业务管道", desc: "几何缩略示意" },
    { id: "supplier_match", name: "供应商匹配", ico: "🏭", iron: "none", g: "业务管道", desc: "7 维 TopN（演示）" },
    { id: "approve_gate", name: "批准门禁", ico: "✅", iron: "hitl_required", g: "批准", desc: "双确认 + sha16" },
    { id: "hitl_explain", name: "HITL 解释", ico: "📖", iron: "none", g: "批准", desc: "reasons / risk 中文" },
    { id: "golden_chain", name: "黄金链", ico: "🔗", iron: "deterministic", g: "端到端", desc: "INTAKE→CRM 业务七步" },
    { id: "audit_tail", name: "审计尾巴", ico: "📜", iron: "none", g: "质量", desc: "skill_audit 最近 N 条" }
  ];

  var PALETTE = [
    { l: "🛡 跑门禁 verify_gate", k: "V", act: function () { runVerify(); } },
    { l: "💰 算报价 calc_quote", k: "Q", act: function () { runQuote(); } },
    { l: "✅ 批准（双确认）approve_gate", k: "A", act: function () { requestApprove(); } },
    { l: "🔍 查 DFM", k: "D", act: function () { runDfm(); } },
    { l: "📚 查历史 RAG", k: "R", act: function () { runRag(); } },
    { l: "📝 起草回复 draft_only", k: "W", act: function () { runDraft(); } },
    { l: "🔗 跑黄金链", k: "C", act: function () { runGolden(); } },
    { l: "📜 看最近审计", k: "L", act: function () { runAudit(); } },
    { l: "打开 Skill Console", k: "S", act: function () { setChatMode("console"); } },
    { l: "切到审批页签", k: "4", act: function () { switchInspectTab("approval"); } }
  ];

  var state = {
    mails: MAILS.slice(),
    curId: null,
    filter: "ALL",
    search: "",
    chatMode: "chat",
    messages: [],
    audit: 0,
    quote: null,
    gate: null,
    draft: null,
    approved: false,
    pendingApprove: false,
    chain: CHAIN.map(function (k) { return { k: k, done: false, active: false, flag: false, sha: null }; })
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m];
    });
  }
  function sha(s) {
    var h = 0, i;
    for (i = 0; i < String(s).length; i++) h = (h * 31 + String(s).charCodeAt(i)) >>> 0;
    return ("0000000" + h.toString(16)).slice(-8);
  }
  function nowT() {
    var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
    return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }
  function cur() {
    var id = state.curId;
    return state.mails.filter(function (m) { return m.id === id; })[0] || null;
  }
  function toast(t, kind) {
    var host = $("#toastHost");
    var el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = "· " + t;
    host.appendChild(el);
    setTimeout(function () { el.remove(); }, 2800);
  }
  function bumpAudit(tag) {
    state.audit += 1;
    $("#auditCount").textContent = "skill_audit: " + state.audit + (tag ? " · " + tag : "");
  }

  /* ── chain ── */
  function setChainFromStage(stage, opts) {
    opts = opts || {};
    var idx = CHAIN.indexOf(stage);
    if (idx < 0) idx = 0;
    state.chain.forEach(function (s, i) {
      s.done = i < idx || !!opts.allDone;
      s.active = i === idx && !opts.allDone;
      s.flag = !!opts.flagAt && opts.flagAt === i;
      if (s.flag) { s.done = false; s.active = false; }
      if (opts.shaAt === i && opts.sha) s.sha = opts.sha;
      if (i !== opts.shaAt) s.sha = s.done && s.sha ? s.sha : null;
    });
    if (opts.allDone) {
      state.chain.forEach(function (s) { s.done = true; s.active = false; s.flag = false; });
    }
  }
  function renderChain() {
    var box = $("#goldenChain");
    var active = state.chain.filter(function (s) { return s.active; })[0];
    var flag = state.chain.filter(function (s) { return s.flag; })[0];
    var phase = flag ? flag.k : (active ? active.k : (state.approved ? "CRM" : "—"));
    var html = "";
    state.chain.forEach(function (s, i) {
      var cls = "gc-step" + (s.done ? " done" : "") + (s.active ? " active" : "") + (s.flag ? " flag" : "");
      var dot = s.done ? "✓" : s.flag ? "!" : s.active ? "●" : String(i + 1);
      html += '<div class="' + cls + '"><span class="dot">' + dot + "</span><span>" + s.k + "</span>";
      if (s.sha) html += '<span style="color:var(--acc)">' + s.sha + "</span>";
      html += "</div>";
      if (i < state.chain.length - 1) html += '<span class="gc-arrow">→</span>';
    });
    html += '<span class="gc-phase">阶段 ' + phase + "</span>";
    box.innerHTML = html;
  }

  /* ── inbox ── */
  function renderInbox() {
    var box = $("#mailList");
    var kw = state.search.toLowerCase();
    var list = state.mails.filter(function (m) {
      if (state.filter !== "ALL" && m.st !== state.filter) return false;
      if (kw && (m.subject + m.from + m.id).toLowerCase().indexOf(kw) < 0) return false;
      return true;
    });
    $("#inboxCount").textContent = list.length + " / " + state.mails.length;
    if (!list.length) {
      box.innerHTML = '<div class="empty">无匹配线索。清除筛选或更换关键词。</div>';
      return;
    }
    box.innerHTML = list.map(function (m) {
      var badges = m.badges.map(function (b) {
        var c = b.indexOf("BLOCK") >= 0 || b.indexOf("🚫") >= 0 ? "err"
          : b.indexOf("HITL") >= 0 || b.indexOf("🛡") >= 0 ? "warn"
          : b.indexOf("PASS") >= 0 || b.indexOf("✅") >= 0 ? "ok" : "acc";
        return '<span class="tag ' + c + '">' + esc(b) + "</span>";
      }).join("");
      return '<button type="button" class="mail' + (m.id === state.curId ? " active" : "") + '" data-id="' + m.id + '" role="option" aria-selected="' + (m.id === state.curId) + '">' +
        '<div class="mrow"><span class="msub">' + esc(m.subject) + '</span><span class="mtime">' + esc(m.time) + "</span></div>" +
        '<div class="mfrom">' + esc(m.from) + " · " + esc(m.st) + "</div>" +
        '<div class="mbadges">' + badges + "</div></button>";
    }).join("");
  }

  /* ── panes ── */
  function renderMailPane(m) {
    var p = $("#pane-mail");
    if (!m) { p.innerHTML = '<div class="empty">← 从左侧选择一封邮件</div>'; return; }
    p.innerHTML =
      '<div class="doc-head"><h3>' + esc(m.subject) + "</h3></div>" +
      '<div class="kvrow"><span class="k">编号</span><span class="mono">' + esc(m.id) + "</span></div>" +
      '<div class="kvrow"><span class="k">发件人</span><span>' + esc(m.from) + "</span></div>" +
      '<div class="kvrow"><span class="k">时间</span><span class="mono">' + esc(m.time) + "</span></div>" +
      '<div class="kvrow"><span class="k">客户</span><span>' + esc(m.customer.name) + " · " + esc(m.customer.note) + "</span></div>" +
      '<div class="kvrow"><span class="k">图纸</span><span><span class="tag acc mono">' + esc(m.geometry.file) + "</span></span></div>" +
      '<div class="mail-body">' + esc(m.body) + "</div>";
  }

  function renderDraftPane() {
    var p = $("#pane-draft");
    var m = cur();
    var q = state.quote;
    var g = state.gate;
    var locked = !!(q && g && !g.fail && state.draft);
    var body = state.draft ||
      "Subject: RE: " + (m ? m.subject : "(未绑定)") + "\n\nDear Sir,\n\n随附报价与 DFM 意见（draft_only，系统不会自动发送）。\n如确认请回 PO。\n\nBest regards,\nUnion Export Agent";
    p.innerHTML =
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">' +
      '<span class="col-title">草稿 · suggest_reply / write_reply</span>' +
      (locked ? '<span class="tag acc">🔒 sha16 已锁 · 人工外发</span>' : '<span class="tag warn">未锁定 · 需先报价+门禁</span>') +
      '<span class="tag mut" style="margin-left:auto">draft_only · 无 send 按钮</span></div>' +
      (q ? '<div class="lock-line">🔒 LOCK sha:' + q.sha + " · 价格字段冻结 · iron-rule-1</div>" : "") +
      '<div class="mail-body">' + esc(body) + "</div>" +
      '<div class="actionbar">' +
      '<button type="button" class="btn primary" id="btnDraftAdopt" ' + (locked ? "" : "disabled") + ">采纳草稿</button>" +
      '<button type="button" class="btn" id="btnDraftRegen">重新起草</button>' +
      '<button type="button" class="btn danger" id="btnDraftDrop">丢弃</button>' +
      '<span class="tag mut" style="margin-left:auto">can_send: ' + (locked ? "true（人工）" : "false") + "</span></div>";
  }

  function renderHistPane(m) {
    var p = $("#pane-hist");
    if (!m) { p.innerHTML = '<div class="empty">← 绑定邮件后展示客户历史</div>'; return; }
    var rows = m.history.map(function (h) {
      var time = typeof h.t === "string" ? h.t : String(h.t);
      return '<div class="tl-item ' + (h.tone || "") + '"><div class="t1"><span class="mono" style="color:var(--acc)">' +
        esc(time) + "</span><b>" + esc(h.e) + '</b></div><div class="t2">' + esc(h.d) + "</div></div>";
    }).join("");
    p.innerHTML =
      '<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">' +
      '<span class="col-title">30 天客户历史 · ' + esc(m.customer.name) + "</span>" +
      '<span class="tag mut" style="margin-left:auto">RAG · postmortem</span></div>' +
      '<div class="tl">' + rows + "</div>";
  }

  function renderApprovalPane() {
    var p = $("#pane-approval");
    var m = cur();
    var q = state.quote, g = state.gate;
    if (!m) { p.innerHTML = '<div class="empty">← 绑定邮件后生成证据链</div>'; return; }

    var gateHtml, gateTag;
    if (!g) { gateHtml = "未运行 · 请先「跑门禁」"; gateTag = '<span class="tag mut">…</span>'; }
    else if (g.fail) { gateHtml = '<b style="color:var(--err)">' + esc(g.fail) + "</b> → 需 HITL"; gateTag = '<span class="tag err">FAIL</span>'; }
    else { gateHtml = g.passText || "校验通过 → 可批准"; gateTag = '<span class="tag ok">PASS</span>'; }

    var quoteHtml = q
      ? "总额 <b style=\"color:var(--acc)\">" + esc(q.total) + "</b> · " + esc(q.unit) + " · 锁 " + esc(q.sha)
      : "未运行 · 请先「算报价」";
    var quoteTag = q ? '<span class="tag acc">deterministic 🔒</span>' : '<span class="tag mut">…</span>';

    var canApprove = !!(q && g && !g.fail && !state.approved);

    var hitlBanner = "";
    if (state.approved) {
      hitlBanner = '<div class="banner ok"><div class="ico">✅</div><div><div class="t">已批准 · dispatch_id ' +
        sha("ap-" + m.id + "-done") + '</div><div class="d">audit jsonl +1 · draft_only 仍待人工外发</div></div></div>';
    } else if (g && g.fail) {
      hitlBanner = '<div class="banner err"><div class="ico">🛡</div><div><div class="t">门禁 FAIL · 禁止批准</div><div class="d">' +
        esc(g.fail) + " · 请切到 HITL 页签做业务裁决</div></div></div>";
    }

    p.innerHTML =
      '<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">' +
      '<span class="col-title">决策面 · 证据链 · 中栏唯一审批权威</span>' +
      '<span class="tag mut" style="margin-left:auto">batch ' + sha(m.id) + "</span></div>" +
      hitlBanner +
      (g && g.fail ? "" :
        g && !g.fail && m.scenario === "hitl_fixed" ? "" :
        g && !g.fail ? "" : "") +
      (m.scenario === "hitl_fixed" && (!g || g.fail) ?
        '<div class="banner"><div class="ico">⚠</div><div><div class="t">HITL 场景 · 固定演示</div><div class="d">risk_score 0.72 · 共面度超差 / 索赔窗口 · 不随机</div></div></div>' : "") +
      '<div class="evchain">' +
      '<div class="evrow"><span class="evk">① 候选解析</span><span class="evv">' + esc(m.customer.name) + " · " + esc(m.geometry.file) + "</span>" + '<span class="tag ok">parse_rfq</span></div>' +
      '<div class="evrow"><span class="evk">② RAG 搜索</span><span class="evv">' + esc(m.evidence.rag) + '</span><span class="tag blue">rag_recall</span></div>' +
      '<div class="evrow"><span class="evk">③ STEP 锁定</span><span class="evv mono">' + esc(m.geometry.file) + " · " + esc(m.evidence.step) + '</span><span class="tag acc">sha 🔒</span></div>' +
      '<div class="evrow"><span class="evk">④ 报价引擎</span><span class="evv">' + quoteHtml + "</span>" + quoteTag + "</div>" +
      '<div class="evrow"><span class="evk">⑤ 门禁</span><span class="evv">' + gateHtml + "</span>" + gateTag + "</div>" +
      '<div class="evrow"><span class="evk">⑥ 事后分析</span><span class="evv">' + esc(m.evidence.pm) + '</span><span class="tag mut">postmortem</span></div>' +
      "</div>" +
      '<div class="metrics">' +
      '<div class="metric"><div class="k">风险评分</div><div class="v' + (g && g.fail ? " risk" : "") + '">' +
      esc(g && g.risk != null ? g.risk : m.scenario === "hitl_fixed" ? "0.72" : "0.18") + "</div></div>" +
      '<div class="metric"><div class="k">门禁结果</div><div class="v' + (g && g.fail ? " risk" : "") + '" style="font-size:14px">' +
      (!g ? "未跑" : g.fail ? "FAIL / HITL" : "PASS") + "</div></div>" +
      '<div class="metric"><div class="k">报价锁</div><div class="v rule">' + (q ? q.sha : "—") + "</div></div></div>" +
      '<div class="card"><h4>审批决策 <span class="hint">右栏快捷与此同源 · 仍以本页为准</span></h4>' +
      '<label class="check"><input type="checkbox" id="chkConfirm" ' + (canApprove || (state.pendingApprove && canApprove) ? (state.pendingApprove || state.confirmedApprove ? "checked" : "") : "") +
      (canApprove ? "" : " disabled") + ' /><span>我已确认风险、报价锁与门禁结果，提交审批决策</span></label>' +
      '<div class="actionbar">' +
      '<button type="button" class="btn primary" id="btnApprove" ' + (canApprove ? "" : "disabled") + ">✓ 批准 (Approve)</button>" +
      '<button type="button" class="btn danger" id="btnReject" ' + (q && g && !state.approved ? "" : "disabled") + ">✕ 拒绝 (Reject)</button>" +
      "</div>" +
      (state.approved ? '<p style="margin-top:8px;font-size:12px;color:var(--acc)">已批准 · audit +1 · iron-rule-1 仍锁定</p>' : "") +
      "</div>" +
      '<div class="card"><h4>几何预览 <span class="hint">' + esc(m.geometry.file) + " · render_thumbnail</span></h4>" +
      '<div class="geo3d" id="geo3d" role="img" aria-label="' + esc(m.geometry.file) + ' 几何预览"><div class="geo-title">🧊 ' + esc(m.geometry.file) + "</div>" +
      '<svg viewBox="0 0 320 200"><g class="geo-g">' +
      '<ellipse cx="160" cy="108" rx="110" ry="58" fill="#2a3b50" stroke="#4e7a0b" stroke-width="1.2"/>' +
      '<ellipse cx="160" cy="92" rx="64" ry="32" fill="none" stroke="#76b900" opacity=".8"/>' +
      '<circle cx="160" cy="104" r="12" fill="none" stroke="#76b900" stroke-dasharray="3 3"/>' +
      '<circle cx="160" cy="108" r="2" fill="#76b900"/>' +
      '</g></svg>' +
      '<span class="geo-label geo-label-od">OD φ172</span>' +
      '<span class="geo-label geo-label-t">t 18</span>' +
      '<span class="geo-label geo-label-hole">8×φ13</span>' +
      '<div class="geo-meta"><span>体积 <b class="mono" style="color:var(--acc)">' + esc(m.geometry.vol) + "</b></span>" +
      "<span>质量 <b class=\"mono\" style=\"color:var(--acc)\">" + esc(m.geometry.mass) + "</b></span>" +
      "<span>利用率 <b class=\"mono\" style=\"color:var(--acc)\">" + esc(m.geometry.util) + "</b></span></div></div></div>" +
      '<div class="card"><h4>客户上下文</h4><div class="kvrow"><span class="k">名称</span><span>' + esc(m.customer.name) + "</span></div>" +
      '<div class="kvrow"><span class="k">国家</span><span>' + esc(m.customer.country) + "</span></div>" +
      '<div class="kvrow"><span class="k">备注</span><span>' + esc(m.customer.note) + "</span></div>" +
      '<div class="kvrow"><span class="k">ctx</span><span>' + esc(m.ctx) + "</span></div></div>";

    bindApproval();
  }

  function renderHitlPane() {
    var p = $("#pane-hitl");
    var m = cur();
    var g = state.gate;
    if (!m) { p.innerHTML = '<div class="empty">← 绑定邮件查看 HITL 上下文</div>'; return; }
    var isHitl = m.scenario === "hitl_fixed" || (g && g.fail) || m.st === "HITL";
    if (!isHitl) {
      p.innerHTML =
        '<div class="banner ok"><div class="ico">✓</div><div><div class="t">当前无强制 HITL</div>' +
        '<div class="d">场景 ' + esc(m.scenario) + " · 若门禁 FAIL 会升级到本页。</div></div></div>" +
        '<div class="kvrow"><span class="k">客户</span><span>' + esc(m.customer.name) + "</span></div>" +
        '<div class="kvrow"><span class="k">说明</span><span>' + esc(m.ctx) + "</span></div>";
      return;
    }
    var fail = g && g.fail ? g.fail : "共面度 0.06 超差 (ISO 1101) · 索赔窗口 18:00";
    p.innerHTML =
      '<div class="banner"><div class="ico">🛡</div><div><div class="t">HITL 待处理 · 风险评分 ' +
      (g && g.risk != null ? g.risk : "0.72") + '</div><div class="d">' + esc(fail) +
      "</div><div class=\"d\">触发: hitl-required.yaml · 责任: 业务员署名 · 固定场景可复现</div></div></div>" +
      '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">' +
      '<span class="tag warn">reasons: 1</span><span class="tag warn">conflicts: 1</span>' +
      '<span class="tag mut">risk: 0.72</span>' +
      '<button type="button" class="tag acc" id="btnHitlExplain" style="cursor:pointer">🤔 为什么需要 HITL</button></div>' +
      '<div class="card"><h4>业务裁决选项（非报价改写）</h4>' +
      '<div class="kvrow"><span class="k">决策 A</span><span>返工喷砂（+3 天 · +¥0.4/pc）</span></div>' +
      '<div class="kvrow"><span class="k">决策 B</span><span>折价接收（-2.5%）· 窗口 18:00</span></div>' +
      '<div class="actionbar">' +
      '<button type="button" class="btn primary" id="btnHitlA">执行 A · 返工</button>' +
      '<button type="button" class="btn" id="btnHitlB">执行 B · 折价</button>' +
      '<button type="button" class="btn" id="btnHitlHuman">转人工工单</button></div>' +
      '<p style="margin-top:8px;font-size:11px;color:var(--ink3)">批准报价仍须在「审批」页签完成双确认；此处仅记录 HITL 业务决策。</p></div>';
  }

  function renderEvidence() {
    var m = cur();
    var e = m ? m.evidence : null;
    var q = state.quote, g = state.gate;
    var rag = e ? e.rag : "—";
    var step = e ? e.step : "—";
    var pm = e ? e.pm : "—";
    if (q) step = "已锁定 (LOCKED)";
    $("#evGrid").innerHTML =
      '<div class="ev-card"><div class="t">RAG 搜索</div><div class="s" style="color:var(--chat)">' + esc(rag) + "</div></div>" +
      '<div class="ev-card"><div class="t">STEP 文件</div><div class="s lock">' + esc(step) + "</div></div>" +
      '<div class="ev-card"><div class="t">门禁 / 复盘</div><div class="s" style="font-size:12px;color:var(--ink)">' +
      esc(!g ? pm : g.fail ? "HITL · " + pm : "PASS · " + pm) + "</div></div>";
  }

  function renderPanes() {
    var m = cur();
    renderMailPane(m);
    renderDraftPane();
    renderHistPane(m);
    renderApprovalPane();
    renderHitlPane();
    renderEvidence();
    renderChain();
  }

  /* ── chat ── */
  function writeSys(t) {
    state.messages.push({ role: "sys", text: t });
    renderChat();
  }
  function msgUser(t) {
    state.messages.push({ role: "user", text: t, time: nowT() });
    renderChat();
  }
  function msgAgent(html, skills, cites, trace) {
    state.messages.push({
      role: "agent", html: html, skills: skills || [], cites: cites || [],
      trace: trace || null, dispatch: sha("d-" + Date.now()), time: nowT()
    });
    renderChat();
    bumpAudit((skills && skills[0]) || "agent");
  }
  function renderChat() {
    var thread = $("#chatThread");
    thread.innerHTML = state.messages.map(function (mm) {
      if (mm.role === "sys") {
        return '<div class="msg sys"><span class="tag mut">' + esc(mm.text) + "</span></div>";
      }
      if (mm.role === "user") {
        return '<div class="msg user"><div class="who">你 · ' + esc(mm.time) + '</div><div class="bubble">' + esc(mm.text) + "</div></div>";
      }
      var h = '<div class="msg agent"><div class="who"><span class="tag blue">Agent</span><span class="mono" style="color:var(--ink3)">' +
        esc(mm.time) + '</span></div><div class="bubble">' + mm.html;
      if (mm.skills && mm.skills.length) {
        h += '<div class="skill-strip">' + mm.skills.map(function (s) {
          return '<span class="skill-chip">🔧 ' + esc(s) + " ✓</span>";
        }).join("") + "</div>";
      }
      if (mm.cites && mm.cites.length) {
        h += '<div class="cite-wrap">' + mm.cites.map(function (c) {
          return '<button type="button" class="cite-chip" data-cite-k="' + esc(c.k) + '" data-cite-key="' + esc(c.key) + '">📎 ' + esc(c.key) + "</button>";
        }).join("") + "</div>";
      }
      if (mm.trace) {
        h += '<details class="trace-det"><summary>🔬 trace · ' + esc(mm.dispatch) + "</summary><pre>" +
          esc(JSON.stringify(mm.trace, null, 2)) + "</pre></details>";
      }
      h += "</div></div>";
      return h;
    }).join("");
    thread.scrollTop = thread.scrollHeight;
  }

  function setChatMode(md) {
    state.chatMode = md;
    $$(".st-seg button").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-mode") === md);
    });
    $("#chatThread").classList.toggle("hidden", md !== "chat");
    $("#chatInput").classList.toggle("hidden", md !== "chat");
    $("#evidenceBox").classList.toggle("hidden", md !== "chat");
    $(".quick-actions").classList.toggle("hidden", md !== "chat");
    $("#skillConsole").classList.toggle("hidden", md !== "console");
    if (md === "console") renderConsole();
  }

  function renderConsole() {
    var box = $("#skillConsole");
    var groups = [];
    SKILLS.forEach(function (s) { if (groups.indexOf(s.g) < 0) groups.push(s.g); });
    var html = "";
    groups.forEach(function (g) {
      html += '<div class="sk-group">' + esc(g) + "</div>";
      SKILLS.filter(function (s) { return s.g === g; }).forEach(function (s) {
        var ironCls = (s.iron.indexOf("🔒") >= 0 || s.iron.indexOf("hitl") >= 0) ? "warn" : "mut";
        html += '<div class="sk-item" data-skill="' + esc(s.id) + '" role="button" tabindex="0">' +
          '<span class="sk-ico">' + s.ico + "</span>" +
          '<div class="sk-body"><div class="sk-name">' + esc(s.name) + '<span class="sk-id">' + esc(s.id) + "</span></div>" +
          '<div class="sk-desc">' + esc(s.desc) + "</div></div>" +
          '<div class="sk-meta"><span class="tag ' + ironCls + '">' + esc(s.iron) + '</span><span style="color:var(--ink3)">▶</span></div></div>';
      });
    });
    box.innerHTML = html;
  }

  /* ── scenarios ── */
  function bindMail(id) {
    state.curId = id;
    var m = cur();
    state.quote = null; state.gate = null; state.draft = null;
    state.approved = false; state.pendingApprove = false; state.confirmedApprove = false;
    setChainFromStage(m ? m.stage : "INTAKE");
    $("#boundTag").textContent = "bound " + id;
    renderInbox();
    renderPanes();
    switchInspectTab("mail");
    writeSys("session 绑定 " + id + " · bound_context_id · 8 区聚合（演示）");
    if (m) {
      msgAgent(
        "已接收 <b>" + esc(m.subject) + "</b>。<br>建议：<b>算报价</b> → <b>跑门禁</b> → <b>起草回复</b>；HITL 单请到审批/HITL 页签。",
        ["parse_rfq", "extract_specs", "context_lookup"],
        [{ k: "geometry", key: m.geometry.file }, { k: "rag", key: m.evidence.rag }],
        { intent: "inbox_open", mail: id, scenario: m.scenario }
      );
    }
  }

  function runQuote() {
    var m = cur();
    if (!m) { writeSys("先绑定一封邮件再算报价"); return; }
    if (m.scenario === "pass_only") {
      msgAgent("该线索为已成交 PO 跟进，无需重新报价。", ["calc_quote"], [], { skip: "already_quoted" });
      return;
    }
    var totals = {
      "M-2201": { total: "¥ 128,640.00", unit: "¥ 107.20 / pc · 1200 pcs · 毛利 31.4%" },
      "M-2203": { total: "¥ 86,520.00", unit: "¥ 103.00 / pc · 840 pcs" },
      "M-2205": { total: "¥ 12,480.00", unit: "¥ 20.80 / pc · 600 pcs" },
      "M-2206": { total: "¥ 64,800.00", unit: "¥ 27.00 / pc · 2400 pcs" },
      "M-2202": { total: "¥ 48,200.00", unit: "返工批次重算 · 锁定历史价" },
      "M-2207": { total: "¥ 121,440.00", unit: "¥ 101.20 / pc · 1200 pcs · 框架价 -5%" },
      "M-2210": { total: "¥ 31,680.00", unit: "¥ 105.60 / pc · 300 pcs · 复购同价" }
    };
    var t = totals[m.id] || { total: "¥ 25,600.00", unit: "演示价" };
    var s = sha("quote-" + m.id);
    state.quote = { total: t.total, unit: t.unit, sha: s };
    var qi = CHAIN.indexOf("QUOTE");
    setChainFromStage("QUOTE", { shaAt: qi, sha: s.slice(0, 8) });
    renderPanes();
    msgAgent(
      "💰 报价 <b style=\"color:var(--acc)\">" + esc(t.total) + "</b>（" + esc(t.unit) + "）<br>" +
      "确定性引擎 LOCK <span class=\"mono\" style=\"color:var(--acc)\">" + s + "</span> · LLM 无权改写（iron-rule-1）。",
      ["parse_rfq", "extract_specs", "calc_quote"],
      [{ k: "geometry", key: m.geometry.file }],
      { total: t.total, sha: s, engine: "deterministic", llm_authority: false }
    );
    switchInspectTab("approval");
  }

  function runVerify() {
    var m = cur();
    if (!m) { writeSys("先绑定邮件再跑门禁"); return; }
    var fail, risk, passText;
    if (m.scenario === "hitl_fixed") {
      fail = "共面度 0.06 超差 (ISO 1101) · 索赔窗口 18:00"; risk = "0.72";
      writeSys("HITL 场景 · 建议同时查 RAG 历史 + 客户记忆 辅助决策");
    } else if (m.scenario === "blocked_fixed") {
      fail = "阳极氧化色差 ΔE=3.8 超标 · 工艺硬冲突"; risk = "0.81";
      writeSys("BLOCKED 场景 · 工艺硬冲突 → DFM 拒绝 · 禁止批准（draft_only 仍生效）");
    } else if (!state.quote && m.scenario === "quote_path") {
      writeSys("建议先「算报价」再跑门禁（也可直接跑，将提示缺锁）");
      fail = null; passText = "无报价锁上下文 · 结构校验通过（演示建议先报价）"; risk = "0.22";
    } else {
      fail = null; passText = "5/5 通过 · 报价锁与工艺约束 OK"; risk = "0.15";
    }
    state.gate = { fail: fail, risk: risk, passText: passText };
    if (fail) {
      setChainFromStage("VERIFY", { flagAt: CHAIN.indexOf("VERIFY") });
      msgAgent(
        "🛡 门禁 <b style=\"color:var(--err)\">FAIL</b> — " + esc(fail) + "<br>转 HITL 人工裁决；禁止自动批准。",
        ["verify_gate", "hitl_explain"],
        [{ k: "geometry", key: m.geometry.file }],
        { hitl_required: true, risk: risk, fixed_scenario: m.scenario }
      );
      switchInspectTab("hitl");
    } else {
      setChainFromStage(state.quote ? "QUOTE" : m.stage);
      if (state.quote) {
        var qi = CHAIN.indexOf("QUOTE");
        state.chain.forEach(function (s, i) {
          s.done = i <= qi && i !== CHAIN.indexOf("REPLY");
          s.active = i === CHAIN.indexOf("REPLY") ? false : s.active;
        });
        state.chain[CHAIN.indexOf("VERIFY")].done = true;
        state.chain[CHAIN.indexOf("REPLY")].active = true;
      }
      renderChain();
      msgAgent(
        "🛡 门禁 <b style=\"color:var(--ok)\">PASS</b> — " + esc(passText || "校验通过") + "<br>可在「审批」页签双确认批准。",
        ["verify_gate"],
        [{ k: "geometry", key: m.geometry.file }],
        { all_pass: true, risk: risk }
      );
      switchInspectTab("approval");
    }
    renderPanes();
  }

  function runDfm() {
    var m = cur();
    if (!m) { writeSys("先绑定邮件"); return; }
    var text = m.scenario === "blocked_fixed"
      ? "色差 ΔE=3.8 超工艺上限；建议换膜系或分色，当前 BLOCKED。"
      : "板厚/孔距主约束满足；注意共面度与发黑批次一致性，验收以 CMM 复测。";
    msgAgent("🔍 DFM：" + esc(text), ["check_dfm", "render_thumbnail"],
      [{ k: "geometry", key: m.geometry.file }],
      { scenario: m.scenario });
    setChainFromStage("DFM", m.scenario === "blocked_fixed" ? { flagAt: CHAIN.indexOf("DFM") } : {});
    renderPanes();
  }

  function runRag() {
    var m = cur();
    if (!m) { writeSys("先绑定邮件"); return; }
    msgAgent(
      "📚 RAG 召回（演示）：<br>1) 同类件历史成交与毛利带<br>2) postmortem：" + esc(m.evidence.pm) +
      "<br>3) 客户商务条款摘要",
      ["rag_recall", "context_lookup"],
      [{ k: "rag", key: m.evidence.rag }],
      { sources: ["crm_history", "postmortem", "rag_index"] }
    );
  }

  function runDraft() {
    var m = cur();
    if (!m) { writeSys("先绑定邮件"); return; }
    if (!state.quote) {
      writeSys("建议先算报价，草稿才能带上锁定价（仍可生成无价草稿）");
    }
    if (!state.gate) state.gate = { fail: null, risk: "0.20", passText: "草稿前门禁未显式执行" };
    state.draft = "Subject: RE: " + m.subject + "\n\nDear Sir,\n\n随附报价" +
      (state.quote ? "（" + state.quote.total + " · sha " + state.quote.sha + "）" : "（待锁）") +
      "与 DFM 意见。\n系统为 draft_only，不会自动发送。\n\nBest regards,\nUnion Export Agent";
    msgAgent(
      "📝 草稿已生成（suggest_reply）· <span class=\"tag acc\">draft_only</span><br>可在中栏「采纳 / 重生成 / 丢弃」；无发送按钮。",
      ["suggest_reply", "write_reply"],
      [{ k: "draft", key: "draft #" + m.id }],
      { locked: !!state.quote, can_send: false }
    );
    renderPanes();
    switchInspectTab("draft");
  }

  function requestApprove(fromQuick) {
    var m = cur();
    if (!m) { writeSys("先绑定邮件"); return; }
    if (!state.quote || !state.gate) {
      writeSys("请先完成「算报价」+「跑门禁」再批准");
      toast("缺少报价或门禁结果", "err");
      switchInspectTab("approval");
      return;
    }
    if (state.gate.fail) {
      writeSys("门禁 FAIL：禁止批准 → 请处理 HITL");
      toast("门禁 FAIL，已阻止批准", "err");
      switchInspectTab("hitl");
      renderPanes();
      return;
    }
    if (state.approved) {
      writeSys("本单已批准（幂等）");
      return;
    }
    if (!state.pendingApprove) {
      state.pendingApprove = true;
      state.confirmedApprove = true;
      writeSys("双确认：再次点击批准以提交 · sha16=" + state.quote.sha);
      toast("双确认：请再点一次批准");
      renderPanes();
      switchInspectTab("approval");
      var chk = $("#chkConfirm");
      if (chk) chk.checked = true;
      return;
    }
    doApprove("approved");
  }

  function doApprove(result) {
    var m = cur();
    if (!m) return;
    if (result === "approved") {
      state.approved = true;
      state.pendingApprove = false;
      setChainFromStage("CRM", { allDone: true });
      msgAgent(
        "✅ <b>已批准</b> — dispatch_id <span class=\"mono\">" + sha("ap-" + m.id) + "</span><br>audit +1 · 价格锁未改写 · draft 仍待人工外发",
        ["approve_gate"],
        [{ k: "geometry", key: m.geometry.file }],
        { double_confirm: true, sha: state.quote ? state.quote.sha : null }
      );
      toast("批准成功 · state=DONE", "ok");
    } else {
      state.pendingApprove = false;
      msgAgent("❌ <b>已拒绝</b> — 请业务跟进重报/改工艺；audit +1", ["approve_gate"], [], { rejected: true });
      toast("已拒绝", "err");
    }
    bumpAudit("approve_gate");
    renderPanes();
  }

  function runGolden() {
    var m = cur();
    if (!m) { writeSys("先绑定邮件"); return; }
    // deterministic demo path by scenario — no Math.random
    runQuote();
    setTimeout(function () {
      runVerify();
      setTimeout(function () {
        if (state.gate && !state.gate.fail && state.quote) {
          state.draft = state.draft || ("Subject: RE: " + m.subject + "\n\nDear Sir,\n\n随附锁定价报价。\n\nBest regards,\nUnion Export Agent");
          msgAgent(
            "🔗 黄金链演示完成：<b>INTAKE→RFQ→DFM→VERIFY→QUOTE→REPLY→CRM</b><br>" +
            (state.gate.fail ? "当前停在 VERIFY/HITL（场景固定）。" : "可到审批页签双确认批准。"),
            ["golden_chain", "audit_tail"],
            [{ k: "rag", key: "chain-trace" }],
            { chain: CHAIN, scenario: m.scenario }
          );
        } else {
          msgAgent(
            "🔗 黄金链在门禁处升级 HITL/BLOCKED（场景固定，可复现）。",
            ["golden_chain", "verify_gate", "hitl_explain"],
            [],
            { chain: CHAIN, stopped_at: state.gate ? "VERIFY" : "QUOTE" }
          );
        }
      }, 200);
    }, 200);
  }

  function runAudit() {
    msgAgent(
      "📜 最近审计（演示）：<br><span class=\"mono\">1. " + nowT() + " verify_gate / approve_gate<br>" +
      "2. calc_quote 🔒 iron-rule-1<br>3. parse_rfq ✓<br>4. context_lookup ✓<br>5. chat_understand · rules_only</span><br>" +
      '<span class="tag mut">source: skill_audit.jsonl（mock）</span>',
      ["audit_tail"], [{ k: "rag", key: "audit" }], { limit: 5, count: state.audit }
    );
  }

  function runSkill(id) {
    var map = {
      calc_quote: runQuote, verify_gate: runVerify, check_dfm: runDfm,
      suggest_reply: runDraft, write_reply: runDraft, approve_gate: requestApprove,
      golden_chain: runGolden, rag_recall: runRag, audit_tail: runAudit,
      hitl_explain: function () {
        var m = cur();
        msgAgent(
          "📖 hitl_explain：场景固定说明 — " +
          esc(m && m.scenario === "hitl_fixed" ? "共面度超差 + 索赔窗口 + 返工史，触发 hitl-required" :
            m && m.scenario === "blocked_fixed" ? "工艺色差硬冲突，verify BLOCKED" :
              "当前线索无强制 HITL 原因"),
          ["hitl_explain"], [], { scenario: m ? m.scenario : null }
        );
      },
      parse_rfq: function () { msgAgent("📧 parse_rfq：邮件槽位已结构化（演示）。", ["parse_rfq"], [], {}); }
    };
    if (map[id]) map[id]();
    else {
      msgAgent("已调用 <b>" + esc(id) + "</b>（mock 成功 · audit +1）", [id], [], { mock: true });
    }
  }

  function chatCmd(raw) {
    var c = raw.toLowerCase();
    if (/门禁|verify|gate/.test(c)) return runVerify();
    if (/报价|quote|价/.test(c)) return runQuote();
    if (/dfm|冲突|工艺/.test(c)) return runDfm();
    if (/草稿|回复|draft/.test(c)) return runDraft();
    if (/rag|历史|经验|记忆/.test(c)) return runRag();
    if (/批准|approve|确认/.test(c)) return requestApprove();
    if (/黄金|golden/.test(c)) return runGolden();
    if (/审计|audit/.test(c)) return runAudit();
    if (/skill|技能|console/.test(c)) { setChatMode("console"); return; }
    msgAgent(
      "意图「" + esc(raw) + "」未匹配 skill，按 <span class=\"tag\">_RULE_ROUTES</span> 回退。<br>可试：<b>算报价 / 跑门禁 / 起草回复 / 跑黄金链 / 看审计</b>",
      ["chat_understand"],
      [{ k: "rag", key: "fallback·rule_routes" }],
      { intent: "unknown", fallback: "_RULE_ROUTES" }
    );
  }

  function send() {
    var ta = $("#chatTa");
    var v = ta.value.trim();
    if (!v) return;
    msgUser(v);
    ta.value = "";
    chatCmd(v);
  }

  function switchInspectTab(tab) {
    var tabs = ["mail", "draft", "hist", "approval", "hitl"];
    tabs.forEach(function (t) {
      var b = document.querySelector('.insp-tab[data-tab="' + t + '"]');
      var p = $("#pane-" + t);
      if (b) b.classList.toggle("active", t === tab);
      if (b) b.setAttribute("aria-selected", t === tab ? "true" : "false");
      if (p) p.classList.toggle("active", t === tab);
    });
  }

  function jumpCite(kind, key) {
    if (kind === "draft") switchInspectTab("draft");
    else if (kind === "rag" || kind === "geometry") switchInspectTab("approval");
    else switchInspectTab("approval");
    toast("jumpCite → " + kind + " · " + key);
  }

  function bindApproval() {
    var chk = $("#chkConfirm");
    if (chk) {
      chk.addEventListener("change", function () {
        state.confirmedApprove = chk.checked;
        var ok = !!(state.quote && state.gate && !state.gate.fail && !state.approved && chk.checked);
        var btn = $("#btnApprove");
        if (btn) btn.disabled = !ok && !state.pendingApprove;
      });
    }
    var ap = $("#btnApprove");
    if (ap) ap.addEventListener("click", function () {
      if (!state.confirmedApprove && !state.pendingApprove) {
        toast("请先勾选确认风险与锁状态", "err");
        return;
      }
      requestApprove();
    });
    var rj = $("#btnReject");
    if (rj) rj.addEventListener("click", function () { doApprove("rejected"); });
  }

  function openPalette() {
    var pal = $("#palette");
    pal.classList.add("show");
    pal.setAttribute("aria-hidden", "false");
    renderPal("");
    setTimeout(function () { $("#palInput").focus(); }, 20);
  }
  function closePalette() {
    var pal = $("#palette");
    pal.classList.remove("show");
    pal.setAttribute("aria-hidden", "true");
  }
  function renderPal(kw) {
    var box = $("#palList");
    var items = PALETTE.filter(function (p) {
      return !kw || p.l.toLowerCase().indexOf(kw.toLowerCase()) >= 0;
    });
    box.innerHTML = items.map(function (p, i) {
      return '<div class="pal-item' + (i === 0 ? " sel" : "") + '" data-l="' + esc(p.l) + '">' +
        '<span class="pl">' + esc(p.l) + '</span><span class="pk">' + esc(p.k) + "</span></div>";
    }).join("");
  }

  function bind() {
    $("#mailList").addEventListener("click", function (e) {
      var b = e.target.closest(".mail");
      if (b) bindMail(b.getAttribute("data-id"));
    });
    $$(".insp-tab").forEach(function (b) {
      b.addEventListener("click", function () { switchInspectTab(b.getAttribute("data-tab")); });
    });
    $$(".st-seg button").forEach(function (b) {
      b.addEventListener("click", function () { setChatMode(b.getAttribute("data-mode")); });
    });
    $$(".chip").forEach(function (b) {
      b.addEventListener("click", function () {
        $$(".chip").forEach(function (x) { x.classList.remove("active"); });
        b.classList.add("active");
        runSkill(b.getAttribute("data-skill"));
      });
    });
    $("#btnSend").addEventListener("click", send);
    $("#chatTa").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
    });
    $("#btnPalette").addEventListener("click", openPalette);
    $("#palInput").addEventListener("input", function (e) { renderPal(e.target.value); });
    $("#palInput").addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        var s = $("#palList .pal-item.sel") || $("#palList .pal-item");
        if (s) s.click();
      }
      if (e.key === "Escape") closePalette();
    });
    $("#palette").addEventListener("click", function (e) {
      if (e.target.id === "palette") closePalette();
      var it = e.target.closest(".pal-item");
      if (it) {
        var l = it.getAttribute("data-l");
        var p = PALETTE.filter(function (x) { return x.l === l; })[0];
        closePalette();
        if (p) p.act();
      }
    });
    $("#mailSearch").addEventListener("input", function (e) {
      state.search = e.target.value;
      $("#mailSearch2").value = e.target.value;
      renderInbox();
    });
    $("#mailSearch2").addEventListener("input", function (e) {
      state.search = e.target.value;
      $("#mailSearch").value = e.target.value;
      renderInbox();
    });
    $("#mailFilter").addEventListener("change", function (e) {
      state.filter = e.target.value;
      renderInbox();
    });
    $("#btnRefresh").addEventListener("click", function () {
      renderInbox();
      toast("列表已刷新（演示数据）");
    });
    $$(".nav button").forEach(function (b) {
      if (b.disabled) return;
      b.addEventListener("click", function () {
        $$(".nav button").forEach(function (x) { x.classList.remove("active"); });
        b.classList.add("active");
        var n = b.getAttribute("data-nav");
        if (n === "skills") setChatMode("console");
        else if (n === "mailbox") toast("邮件台 = 本工作台左栏 + 检视器");
        else toast(n + "（演示聚焦工作台）");
      });
    });
    $$("[data-quick]").forEach(function (b) {
      b.addEventListener("click", function () {
        var a = b.getAttribute("data-quick");
        if (a === "verify") runVerify();
        else if (a === "quote") runQuote();
        else if (a === "approve") requestApprove(true);
        else if (a === "reject") doApprove("rejected");
        else if (a === "hitl_tab") switchInspectTab("hitl");
      });
    });
    $("#chatThread").addEventListener("click", function (e) {
      var c = e.target.closest("[data-cite-k]");
      if (c) jumpCite(c.getAttribute("data-cite-k"), c.getAttribute("data-cite-key"));
    });
    $("#skillConsole").addEventListener("click", function (e) {
      var it = e.target.closest(".sk-item");
      if (it) runSkill(it.getAttribute("data-skill"));
    });
    $("#pane-draft").addEventListener("click", function (e) {
      if (e.target.id === "btnDraftAdopt") {
        toast("草稿已采纳（仍需人工外发 · draft_only）", "ok");
        bumpAudit("draft_adopt");
      } else if (e.target.id === "btnDraftRegen") {
        runDraft();
      } else if (e.target.id === "btnDraftDrop") {
        state.draft = null;
        renderPanes();
        switchInspectTab("draft");
        toast("草稿已丢弃");
      }
    });
    $("#pane-hitl").addEventListener("click", function (e) {
      var id = e.target.id;
      if (id === "btnHitlExplain") runSkill("hitl_explain");
      else if (id === "btnHitlA") { toast("HITL 决策 A 已记录 · 请再审批报价", "ok"); bumpAudit("hitl_decision"); }
      else if (id === "btnHitlB") { toast("HITL 决策 B 已记录 · 商务确认中"); bumpAudit("hitl_decision"); }
      else if (id === "btnHitlHuman") { toast("已开人工工单（演示）"); }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { closePalette(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key >= "1" && e.key <= "5") {
        e.preventDefault();
        switchInspectTab(["mail", "draft", "hist", "approval", "hitl"][Number(e.key) - 1]);
      }
      var pal = $("#palette");
      if (pal.classList.contains("show") && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        var items = $$("#palList .pal-item");
        if (!items.length) return;
        var idx = items.findIndex(function (x) { return x.classList.contains("sel"); });
        idx = (idx + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach(function (x, i) { x.classList.toggle("sel", i === idx); });
      }
    });
  }

  function initQuickChips() {
    var chips = [
      ["🛡 跑门禁", "verify_gate"],
      ["💰 算报价", "calc_quote"],
      ["📝 起草回复", "suggest_reply"],
      ["🔗 跑黄金链", "golden_chain"],
      ["📜 审计", "audit_tail"]
    ];
    $("#quickChips").innerHTML = chips.map(function (c) {
      return '<button type="button" class="tag acc" data-skill="' + c[1] + '">' + c[0] + "</button>";
    }).join("");
    $("#quickChips").addEventListener("click", function (e) {
      var b = e.target.closest("[data-skill]");
      if (!b) return;
      msgUser(b.textContent.trim());
      runSkill(b.getAttribute("data-skill"));
    });
  }

  function init() {
    bind();
    initQuickChips();
    renderConsole();
    bindMail("M-2202"); // 默认 HITL 场景，便于演示决策面
  }

  window.Workbench = {
    send: send,
    openPalette: openPalette,
    switchInspectTab: switchInspectTab,
    setChatMode: setChatMode,
    runApprove: requestApprove,
    runDraft: runDraft,
    runVerify: runVerify,
    runQuote: runQuote,
    toast: toast,
    jumpCite: jumpCite
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
