// 尺码配对验收共用：读已构建站点的 size-match-data（与页面同一份 viewer-data.js 展开）、按页面规则搜索、解析 A1 CSV。
"use strict";
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const VIEWER_DATA = path.join("assets", "app", "viewer-data.js");
const MATCH_DATA = "data/generated/size-match-data.json";
const SOURCE_KINDS = { nonpick: "非皮卡", pick: "皮卡" };
const TABLES = { 非皮卡: "压缩尺码表.csv", 皮卡: "压缩尺码表_皮卡.csv" };

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

// 最小 CSV 解析（支持引号与引号内逗号/换行）
function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  text = text.replace(/^﻿/, "");
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { field += '"'; i += 1; } else if (char === '"') quoted = false; else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") { row.push(field); field = ""; } else if (char === "\n") { row.push(field.replace(/\r$/, "")); rows.push(row); row = []; field = ""; } else field += char;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const [header, ...body] = rows.filter((item) => item.length > 1 || item[0]);
  return body.map((item) => Object.fromEntries(header.map((key, index) => [key, item[index] ?? ""])));
}

class Site {
  // D：站点自己发布的 viewer-data.js（浏览器实际运行的代码）；站点里没有时退回 site_overrides
  constructor(root) {
    this.root = root;
    const published = path.join(root, VIEWER_DATA);
    this.D = require(fs.existsSync(published) ? published : path.join(ROOT, "site_overrides", VIEWER_DATA));
    this.manifest = readJson(path.join(root, MATCH_DATA));
    this.cache = new Map();
  }

  source(name) {
    return this.manifest.sources.find((source) => source.name === name);
  }

  // 一个数据源 + 类别的两种视图（与页面 loadConfiguredMatchSource 相同：逐个 MAKE 分片 expandMatchShard）
  views(name, kind) {
    const key = `${name}|${kind}`;
    if (!this.cache.has(key)) {
      const views = { full: [], compressed: [] };
      for (const group of this.source(name).make_groups.filter((item) => item.kind === kind)) {
        const shard = readJson(path.join(path.dirname(path.join(this.root, MATCH_DATA)), group.records_path));
        const expanded = this.D.expandMatchShard(shard);
        views.full.push(...expanded.full.records);
        views.compressed.push(...(expanded.compressed?.records || []));
      }
      this.cache.set(key, views);
    }
    return this.cache.get(key);
  }

  search(records, query) {
    const tokens = this.D.searchQueryTokens(query);
    return records.filter((record) => tokens.every((token) => this.D.recordMatchesSearchToken(record, token)));
  }
}

module.exports = { MATCH_DATA, SOURCE_KINDS, TABLES, readJson, parseCsv, Site };
