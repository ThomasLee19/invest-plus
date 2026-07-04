import { Tag } from 'antd'
import Color from 'color'
import { useMemo } from 'react'
import { useLang } from '../../../i18n'

const colorMap = {
  unparsed: '#67C23A',
  cancel: '#E6A23C',
  success: '#3266f3',
  failed: '#F56C6C',
  Indexed: '#67C23A',
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

  const color = colorMap[status] ?? '#999'
  const text = textMap[status] ?? status

  const backgroundColor = useMemo(() => {
    return new Color(color).alpha(0.1).toString()
  }, [color])

  const borderColor = useMemo(() => {
    return new Color(color).alpha(0.3).toString()
  }, [color])

  return <Tag style={{ borderColor, color, backgroundColor }}>{text}</Tag>
}
