#!/usr/bin/env node
/**
 * AC-4 —— 硬编码色值门禁。
 *
 * 判据是「属性值里出现色字面量」，不是「文件里出现 # 号」。三个必须区分的情形：
 *
 *   1. 注释里的历史说明（`// 原先是 #D2ECED 薄荷绿底`）—— 是文档，不是硬编码。
 *      朴素的 `grep '#'` 会把它算成违规，逼得执行者要么删掉有价值的注释，
 *      要么给门禁加 grep -v 自削。
 *   2. 关键字色值（`background-color: white`）—— 朴素的 hex 正则完全看不见它。
 *      本仓库实际有 3 处（markdown/index.scss ×2、repository/index.module.scss ×1）。
 *   3. `\b(white|black)\b` 这种写法会撞上 `white-space: nowrap` —— 本仓库有 8 处，
 *      会让门禁永远无法返回 0。必须锚定在属性值位置。
 *
 * 排除项只有两个，都写死在这里、不需要人工判断：
 *   - src/styles/**       token 定义本身
 *   - *.svg               <img> 加载的 SVG 处于独立文档上下文，读不到 CSS 自定义属性，
 *                         必须硬编码（物理限制，非偏好）
 *
 * 用法：node scripts/check-hardcoded-colors.mjs   （cwd = frontend/）
 * 退出码：0 通过，1 有硬编码残留。
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = 'src'
const EXCLUDE_DIRS = [join('src', 'styles')]
const EXTENSIONS = ['.scss', '.css', '.ts', '.tsx']

/** 色字面量：hex / rgb() / rgba() / hsl() / 裸 white|black 关键字 */
const COLOR_LITERAL =
  /#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\(|\b(?:white|black)\b/

/** 只看「属性值」位置：CSS 的 `prop:` 之后，或 JS 的 `key:` / `=` 之后，到行尾或分隔符。 */
const DECLARATION = /(?:[\w-]+\s*:|=)\s*([^;{}\n]*)/g

function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '') // /* 块注释 */
    .replace(/(^|[^:])\/\/.*$/gm, '$1') // // 行注释（避开 http:// 里的双斜杠）
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (EXCLUDE_DIRS.some((d) => p === d || p.startsWith(d + '/'))) continue
    if (statSync(p).isDirectory()) walk(p, out)
    else if (EXTENSIONS.some((e) => name.endsWith(e))) out.push(p)
  }
  return out
}

const hits = []

for (const file of walk(ROOT)) {
  const lines = stripComments(readFileSync(file, 'utf8')).split('\n')
  lines.forEach((line, i) => {
    for (const m of line.matchAll(DECLARATION)) {
      const value = m[1]
      if (COLOR_LITERAL.test(value)) {
        hits.push(`${relative('.', file)}:${i + 1}  ${line.trim()}`)
        break
      }
    }
  })
}

if (hits.length) {
  console.error('HARDCODED COLORS FOUND\n')
  for (const h of hits) console.error('  - ' + h)
  console.error(
    `\n共 ${hits.length} 处。全部色值必须走 src/styles/tokens.css 的变量。`,
  )
  process.exit(1)
}

console.log('no hardcoded colors: src/ 下属性值中无色字面量（已排除 src/styles/ 与 *.svg）')
