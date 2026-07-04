import classNames from 'classnames'
import DOMPurify from 'dompurify'
import { Marked, Renderer, TokenizerAndRendererExtension } from 'marked'
import { useEffect, useMemo, useRef, useState } from 'react'
import './index.scss'

// target="_blank" 的链接强制加上 rel="noopener noreferrer"，避免反向 tabnabbing：
// 被打开的页面无法通过 window.opener 操纵原页面。注册一次即可（模块级）。
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.getAttribute('target') === '_blank') {
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

// 流式回答每收到一个 token 都会整段重新 marked.parse + DOMPurify.sanitize，
// 长回答时是 O(n²) 的重复解析，造成明显卡顿。这里对渲染做节流：底层原始文本
// 立即更新（不丢内容），但真正的解析/消毒最多每 THROTTLE_MS 提交一次，并在
// 停止变化后用 trailing 定时器补一次最终渲染。
const THROTTLE_MS = 100

export default function Markdown(props: {
  className?: string
  value?: string
  extensions?: TokenizerAndRendererExtension[]
  onClick?: React.MouseEventHandler<HTMLDivElement>
}) {
  const { value, extensions, className, ...otherProps } = props

  const [committed, setCommitted] = useState(value ?? '')
  const lastCommitRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    const next = value ?? ''
    const elapsed = Date.now() - lastCommitRef.current
    if (elapsed >= THROTTLE_MS) {
      lastCommitRef.current = Date.now()
      setCommitted(next)
    } else {
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        lastCommitRef.current = Date.now()
        setCommitted(next)
      }, THROTTLE_MS - elapsed)
    }
    return () => clearTimeout(timerRef.current)
  }, [value])

  const html = useMemo(() => {
    const renderer = new Renderer()

    const marked = new Marked({
      extensions,
    })
    const html = marked.parse(committed, {
      gfm: true,
      renderer,
    })

    return DOMPurify.sanitize(html as string)
  }, [committed, extensions])

  return (
    <div
      className={classNames('com-markdown', className)}
      {...otherProps}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
