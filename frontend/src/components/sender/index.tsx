import * as api from '@/api'
import IconSend from '@/components/icons/IconSend'
import { useLang } from '@/i18n'
import { LoadingOutlined, PaperClipOutlined } from '@ant-design/icons'
import { Button, Input, Space, Upload, UploadFile } from 'antd'
import classNames from 'classnames'
import { PropsWithChildren, useMemo, useState } from 'react'
import './index.scss'

const IconFile2 = (
  <svg
    className="com-sender__file-icon"
    xmlns="http://www.w3.org/2000/svg"
    width="24"
    height="24"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"></path>
    <path d="M14 2v4a2 2 0 0 0 2 2h4"></path>
    <path d="M10 9H8"></path>
    <path d="M16 13H8"></path>
    <path d="M16 17H8"></path>
  </svg>
)

export default function ComSender(
  props: PropsWithChildren<{
    className?: string
    loading?: boolean
    onSend?: (value: string, files: string[]) => void | Promise<void>
    onContract?: () => void
  }>,
) {
  const { className, onSend, loading, ...rest } = props
  const { t } = useLang()
  const [value, setValue] = useState('')
  const [fileList, setFileList] = useState<(UploadFile & { loading?: boolean })[]>([])

  const uploading = useMemo(() => fileList.some((f) => f.loading), [fileList])

  async function send() {
    if (uploading) return
    if (loading) return
    if (!value) return
    const msg = value
    setValue('')
    await onSend?.(msg, [])
  }

  async function upload(file: UploadFile & { loading?: boolean }) {
    file.loading = true
    setFileList((prev) => [...prev, file])
    try {
      await api.session.upload({ files: file as any })
      window.$app.message.success(`${file.name} 上传成功`)
    } catch {
      window.$app.message.error(`${file.name} 上传失败`)
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
