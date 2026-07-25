import { tokens } from '@/styles/tokens'
import { Tag } from 'antd'
import Color from 'color'
import { useMemo } from 'react'
import { useLang } from '../../../i18n'

// 原先的映射语义是乱的：unparsed 和 Indexed 都是绿色（未解析和已索引同色），
// 而 success 是蓝色。这里按状态语义重排，并全部改用 tokens.ts 的语义色。
//
// ⚠️ 取值必须是字面量色串。下面的 new Color(color) 在渲染期执行、位于 useMemo 内、
// 且没有 error boundary（App.tsx 的 AntdApp 不提供），传入 'var(--accent)' 会
// throw「Unable to parse color from string」，导致 /repository 整页白屏。
// tokens.ts 因此禁止出现 var(，由 scripts/check-tokens.mjs 强制。
const colorMap = {
  unparsed: tokens.statusNeutral, // 未解析 = 中性待处理态（原为绿，语义错）
  cancel: tokens.statusWarning, // 已取消
  success: tokens.statusSuccess, // 成功（原为蓝，语义错）
  failed: tokens.statusDanger, // 异常
  Indexed: tokens.statusSuccess, // 已索引 = 成功终态
}

export function Status(props: { status: keyof typeof colorMap }) {
  const { status } = props
  const { t } = useLang()
  const textMap = {
    unparsed: t.statusUnparsed,
    cancel: t.statusCancel,
    success: t.statusSuccess,
    failed: t.statusFailed,
    Indexed: 'Indexed',
  }

  const color = colorMap[status] ?? tokens.statusNeutral
  const text = textMap[status] ?? status

  const backgroundColor = useMemo(() => {
    return new Color(color).alpha(0.1).toString()
  }, [color])

  const borderColor = useMemo(() => {
    return new Color(color).alpha(0.3).toString()
  }, [color])

  return <Tag style={{ borderColor, color, backgroundColor }}>{text}</Tag>
}
