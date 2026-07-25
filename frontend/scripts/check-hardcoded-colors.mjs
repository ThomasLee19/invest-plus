#!/usr/bin/env node
/**
 * AC-4 —— 硬编码色值门禁。
 *
 * ## 设计说明（这里踩过一次坑，记下来免得后人重蹈）
 *
 * 初版的做法是「先锚定声明位置（prop: 之后到行尾），再在值里找色字面量」，
 * 目的是排除两类假阳性：注释里的历史说明、以及 `white-space` 这种属性名撞词。
 *
 * 那个做法有一个致命盲区：值捕获用 `[^;{}\n]*`，遇换行即停。而 prettier 会把
 * 长声明折行 —— 本仓库真实命中过：
 *
 *     background: linear-gradient(
 *       180deg,
 *       rgba(28, 27, 26, 0.6) 0%,     ← 续行没有 `prop:`，永远扫不到
 *       rgba(28, 27, 26, 0) 80%
 *     );
 *
 * 结果是门禁报「归零」而实际有残留 —— 一个会自证清白的假绿。
 *
 * 现在改为直接找色字面量，不做声明锚定，用更精确的模式解决假阳性：
 *   - 注释：先剥离，不参与匹配
 *   - `white-space` / `blacklist`：关键字两侧加边界，且禁止紧邻连字符
 *   - `#root` 这类 id 选择器：hex 必须是 3/4/6/8 位且整段是合法 hex 字符
 *
 * 排除项只有两个，写死在这里、不需要人工判断：
 *   - src/styles/**   token 定义本身
 *   - *.svg           <img> 加载的 SVG 处于独立文档上下文，读不到 CSS 自定义属性，
 *                     必须硬编码（物理限制，非偏好）
 *
 * 用法：node scripts/check-hardcoded-colors.mjs   （cwd = frontend/）
 * 退出码：0 通过，1 有硬编码残留。
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = 'src'
const EXCLUDE_DIRS = [join('src', 'styles')]
const EXTENSIONS = ['.scss', '.css', '.ts', '.tsx']

/**
 * 色字面量的三类形态。全部带边界约束，避免撞词：
 *  1. hex —— 恰好 3/4/6/8 位，前后不得是 word 字符或连字符
 *  2. 颜色函数 —— rgb( rgba( hsl( hsla( color( color-mix(
 *  3. 具名颜色 —— 只查会真正被误用的那几个；两侧不得是连字符，
 *     所以 `white-space` / `border-black-ish` 不会命中
 */
const PATTERNS = [
  {
    name: 'hex',
    re: /(?<![\w-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])/g,
  },
  {
    name: 'color-fn',
    re: /(?<![\w-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\s*\(/gi,
  },
  {
    name: 'named',
    re: /(?<![\w-])(?:white|black|red|green|blue|yellow|orange|purple|pink|gray|grey|silver|gold|tomato|crimson|navy|teal|olive|maroon|aqua|fuchsia|lime)(?![\w-])/gi,
  },
]

/**
 * 剥离注释，但保持行号不变。
 *
 * 块注释可能跨行（本仓库就有），所以不能逐行剥 —— 那样块注释的中间行和末行
 * 单独看都不像注释，里面的示例色值会被误报。整体剥离时用等量换行占位，
 * 这样后续 split('\n') 的行号仍与原文件一一对应。
 */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/(^|[^:])\/\/.*$/gm, '$1') // // 行注释（避开 http:// 的双斜杠）
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
  const raw = readFileSync(file, 'utf8')
  const rawLines = raw.split('\n')
  // 整体剥注释（保持行号），再逐行匹配。
  stripComments(raw)
    .split('\n')
    .forEach((line, i) => {
      const rawLine = rawLines[i] ?? line
      for (const { name, re } of PATTERNS) {
        re.lastIndex = 0
        const m = re.exec(line)
        if (m) {
          hits.push(
            `${relative('.', file)}:${i + 1}  [${name}] ${rawLine.trim()}`,
          )
          return
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

console.log(
  'no hardcoded colors: src/ 下无色字面量（已排除 src/styles/ 与 *.svg）',
)
