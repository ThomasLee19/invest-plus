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
    onSend?: (value: string, files: string[]) => void | Promise<void>
    onContract?: () => void
  }>,
) {
  const { className, onSend, loading, sessionId, ...rest } = props
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
    file.loading = true
    setFileList((prev) => [...prev, file])
    try {
      await api.session.upload({ files: file as any, session_id: sessionId })
      window.$app.message.success(`${file.name} ${t.uploadSuccess}`)
    } catch {
      window.$app.message.error(`${file.name} ${t.uploadFailed}`)
    } finally {
      file.loading = false
      setFileList((prev) => [...prev])
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
            if (!e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />

        <div className="com-sender__actions">
          <Space className="com-sender__actions-left" size={12}>
            <Upload
              accept=".txt,.md"
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
