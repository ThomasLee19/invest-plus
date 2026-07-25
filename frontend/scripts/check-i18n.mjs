#!/usr/bin/env node
/**
 * AC-27 —— i18n 中英键对齐门禁。
 *
 * src/i18n.tsx 的 zh 与 en 是两份手写对象。改文案时只改一边、漏掉另一边，
 * 是这类文件最常见的失误：TypeScript 不会报错（两边形状不同也能推断出联合类型），
 * 运行时表现为切到某个语言后界面上出现 undefined —— 而它只在切语言时才暴露，
 * 恰好是 18 格人工检查里最容易跳过的那一半。
 *
 * 本脚本比较两个语言块的顶层键集合，双向查漏。
 *
 * 用法：node scripts/check-i18n.mjs   （cwd = frontend/）
 * 退出码：0 通过，1 有缺口。
 */

import { readFileSync } from 'node:fs'

const PATH = 'src/i18n.tsx'
const text = readFileSync(PATH, 'utf8')

/** 抓出 `  <lang>: {` 到与之对齐的 `  },` 之间的整块。 */
function extractLocale(lang) {
  const start = text.indexOf(`\n  ${lang}: {`)
  if (start === -1) {
    console.error(`FAIL: ${PATH} 里找不到 ${lang} 语言块`)
    process.exit(1)
  }
  const end = text.indexOf('\n  },', start)
  if (end === -1) {
    console.error(`FAIL: ${PATH} 的 ${lang} 语言块没有闭合`)
    process.exit(1)
  }
  return text.slice(start, end)
}

/** 顶层键固定缩进 4 空格；嵌套内容（如 hotQuestions 的数组项）缩进更深，天然被排除。 */
function topLevelKeys(block) {
  return new Set([...block.matchAll(/^ {4}(\w+)\s*:/gm)].map((m) => m[1]))
}

const zh = topLevelKeys(extractLocale('zh'))
const en = topLevelKeys(extractLocale('en'))

const missingInEn = [...zh].filter((k) => !en.has(k))
const missingInZh = [...en].filter((k) => !zh.has(k))

if (missingInEn.length || missingInZh.length) {
  console.error('I18N KEY MISMATCH\n')
  for (const k of missingInEn) console.error(`  - en 缺少: ${k}（zh 有）`)
  for (const k of missingInZh) console.error(`  - zh 缺少: ${k}（en 有）`)
  console.error(`\nzh ${zh.size} 键 / en ${en.size} 键。两边必须完全一致。`)
  process.exit(1)
}

console.log(`i18n keys in sync: ${zh.size}（zh 与 en 顶层键集合完全一致）`)
