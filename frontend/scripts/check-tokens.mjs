#!/usr/bin/env node
/**
 * AC-30 —— design token 双文件漂移门禁。
 *
 * src/styles/tokens.css 是唯一真源，src/styles/tokens.ts 是 JS 侧镜像。
 * 两份手写文件之间的漂移，靠单条 grep 是抓不住的：
 * tokens.css 写错会在肉眼检查里显形，而 tokens.ts 写错只影响 antd 的派生色
 * （colorPrimaryHover 等由 @ant-design/colors 的 generate() 派生），
 * 表现为「按钮 hover 色略微不对」—— 正是肉眼最不可能抓到的一类偏差。
 *
 * 本脚本做三件事：
 *   1. 键集合必须完全一致（camelCase 映射，双向查漏）
 *   2. 每个键的值必须逐字相等（空白折叠、外层引号剥离后比较）
 *   3. tokens.ts 内禁止出现 var(  —— status.tsx 的 new Color() 会在渲染期 throw
 *
 * 用法：node scripts/check-tokens.mjs   （cwd = frontend/）
 * 退出码：0 通过，1 有漂移。
 */

import { readFileSync } from 'node:fs'

const CSS_PATH = 'src/styles/tokens.css'
const TS_PATH = 'src/styles/tokens.ts'

/** 折叠所有连续空白为单个空格，并去掉首尾空白。 */
const normalize = (s) => s.replace(/\s+/g, ' ').trim()

/** 去掉 /* *\/ 注释，避免注释里的示例值被误当成声明。 */
const stripBlockComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')

/** --foo-bar → fooBar；--font-xxl → fontXxl */
const toCamel = (name) =>
  name.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase())

function parseCss(text) {
  const body = stripBlockComments(text)
  const root = body.match(/:root\s*\{([\s\S]*?)\n\}/)
  if (!root) {
    console.error(`FAIL: ${CSS_PATH} 里找不到 :root { ... } 块`)
    process.exit(1)
  }
  const out = new Map()
  for (const m of root[1].matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) {
    out.set(toCamel(m[1]), normalize(m[2]))
  }
  return out
}

function parseTs(text) {
  const body = stripBlockComments(text)
  const obj = body.match(
    /export const tokens\s*=\s*\{([\s\S]*?)\n\}\s*as const/,
  )
  if (!obj) {
    console.error(
      `FAIL: ${TS_PATH} 里找不到 export const tokens = { ... } as const`,
    )
    process.exit(1)
  }
  const out = new Map()
  // 值可能换行后才开始（如 fontSans），故允许键冒号后出现换行与缩进。
  const re = /(\w+)\s*:\s*(?:\r?\n\s*)?('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")/g
  for (const m of obj[1].matchAll(re)) {
    out.set(m[1], normalize(m[2].slice(1, -1)))
  }
  return out
}

const cssText = readFileSync(CSS_PATH, 'utf8')
const tsText = readFileSync(TS_PATH, 'utf8')

const css = parseCss(cssText)
const ts = parseTs(tsText)

const problems = []

// 1) tokens.ts 内禁止 var(
if (/var\(/.test(stripBlockComments(tsText))) {
  problems.push(
    `${TS_PATH} 内出现 var( —— 禁止。status.tsx 的 new Color() 会在渲染期 throw，导致 /repository 白屏。`,
  )
}

// 2) 键集合双向查漏
for (const k of css.keys()) {
  if (!ts.has(k)) problems.push(`缺键: ${TS_PATH} 没有 ${k}（tokens.css 有）`)
}
for (const k of ts.keys()) {
  if (!css.has(k))
    problems.push(`多键: ${TS_PATH} 有 ${k}，但 tokens.css 没有对应变量`)
}

// 3) 逐键比值
for (const [k, cssVal] of css) {
  if (!ts.has(k)) continue
  const tsVal = ts.get(k)
  if (cssVal !== tsVal) {
    problems.push(
      `值漂移: ${k}\n    tokens.css: ${cssVal}\n    tokens.ts : ${tsVal}`,
    )
  }
}

if (problems.length) {
  console.error('TOKEN DRIFT DETECTED\n')
  for (const p of problems) console.error('  - ' + p)
  console.error(
    `\n共 ${problems.length} 处问题。tokens.css 是唯一真源，请以它为准修正 tokens.ts。`,
  )
  process.exit(1)
}

console.log(
  `tokens in sync: ${css.size} 个变量，键值逐一匹配，tokens.ts 无 var( 残留`,
)
