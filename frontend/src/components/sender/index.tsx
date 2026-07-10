import * as api from '@/api'
import IconSend from '@/components/icons/IconSend'
import { useLang } from '@/i18n'
import { LoadingOutlined, PaperClipOutlined } from '@ant-design/icons'
import { Button, Input, Space, Upload, UploadFile } from 'antd'
import classNames from 'classnames'
import { PropsWithChildren, useMemo, useState } from 'react'
import './index.scss'

export default function ComSender(
  props: PropsWithChildren<{
    className?: string
    loading?: boolean
    sessionId?: string
    // 主页在首个附件上传前尚无会话；此回调懒创建并返回一个会话 id，
    // 让上传与后续发送/跳转复用同一个会话。聊天页已有 sessionId，无需传。
    ensureSessionId?: () => Promise<string | undefined>
    onSend?: (value: string, files: string[]) => void | Promise<void>
    onContract?: () => void
  }>,
) {
  const { className, onSend, loading, sessionId, ensureSessionId, ...rest } = props
  const { t } = useLang()
  const [value, setValue] = useState('')
  const [fileList, setFileList] = useState<(UploadFile & { loading?: boolean })[]>([])

  const uploading = useMemo(() => fileList.some((f) => f.loading), [fileList])

  async function send() {
    if (uploading) return
    if (loading) return
    if (!value) return
    const msg = value
    const attachmentNames = fileList.map((f) => f.name)
    try {
      await onSend?.(msg, attachmentNames)
      // 仅在发送成功后才清空输入框和已上传文件列表；发送失败时保留，
      // 避免用户输入的内容随一次失败的请求丢失。
      setValue('')
      setFileList([])
    } catch {
      // onSend 内部已经把错误记录到对应的 chat item 上，这里不需要再处理，
      // 只是不清空输入框/附件列表。
    }
  }

  async function upload(file: UploadFile & { loading?: boolean }) {
    setFileList((prev) => [...prev, { ...file, loading: true }])
    try {
      if ((file.size ?? 0) > 5 * 1024 * 1024) {
        throw new Error(t.fileTooLarge)
      }
      const session_id = ensureSessionId ? await ensureSessionId() : sessionId
      await api.session.upload({ files: file as unknown as File, session_id })
      window.$app.message.success(`${file.name} ${t.uploadSuccess}`)
    } catch (error) {
      const msg =
        error instanceof Error && error.message === t.fileTooLarge
          ? t.fileTooLarge
          : `${file.name} ${t.uploadFailed}`
      window.$app.message.error(msg)
      // 上传失败的文件不应作为附件出现在后续发送中，且 showUploadList={false}
      // 导致用户无法手动移除，因此直接从列表中剔除。
      setFileList((prev) => prev.filter((f) => f.uid !== file.uid))
    } finally {
      setFileList((prev) =>
        prev.map((f) => (f.uid === file.uid ? { ...f, loading: false } : f)),
      )
    }
  }

  return (
    <div className={classNames('com-sender', className)} {...rest}>
      <div className="com-sender__main">
        <Input.TextArea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t.placeholder}
          autoSize={{ minRows: 2 }}
          autoFocus
          onPressEnter={(e) => {
            if (e.nativeEvent.isComposing) return
            if (!e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />

        <div className="com-sender__actions">
          <Space className="com-sender__actions-left" size={12}>
            <Upload
              accept=".txt,.md,.pdf"
              showUploadList={false}
              beforeUpload={(file) => { upload(file); return false }}
            >
              <Button variant="text" color="default">
                {uploading ? <LoadingOutlined /> : <PaperClipOutlined />}
                {t.attachment}
              </Button>
            </Upload>
          </Space>
          <Space className="com-sender__actions-right" size={12}>
            <Button
              className="btn-send"
              color="primary"
              variant="filled"
              onClick={send}
              loading={loading}
              disabled={!value}
              icon={<IconSend />}
            ></Button>
          </Space>
        </div>
      </div>
    </div>
  )
}
