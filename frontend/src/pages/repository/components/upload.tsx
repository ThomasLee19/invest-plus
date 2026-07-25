import * as api from '@/api'
import { ResponseError } from '@/api/request/error'
import IconUpload from '@/assets/repository/upload.svg'
import { useLang } from '@/i18n'
import { tokens } from '@/styles/tokens'
import { Upload, UploadFile, UploadProps } from 'antd'
import { forwardRef, useImperativeHandle, useState } from 'react'
import styles from './upload.module.scss'

export type RepositoryUploadRef = {
  submit: () => Promise<void>
}

export default forwardRef(function RepositoryUpload(
  props: UploadProps,
  ref?: React.Ref<RepositoryUploadRef>,
) {
  const { ...otherProps } = props
  const { t } = useLang()

  const [fileList, setFileList] = useState<UploadFile[]>([])

  useImperativeHandle(ref, () => {
    return {
      submit: async () => {
        let hasError = false

        for (const file of fileList) {
          if (file.status === 'done') continue

          setFileList((prev) =>
            prev.map((item) => {
              if (item.uid === file.uid) {
                return {
                  ...item,
                  status: 'uploading',
                }
              }
              return item
            }),
          )
          try {
            // 检查文件大小
            if ((file.size ?? 0) > 5 * 1024 * 1024) {
              throw new Error(t.fileTooLarge)
            }

            await api.session.upload({ files: file.originFileObj as File })

            setFileList((prev) =>
              prev.map((item) => {
                if (item.uid === file.uid) {
                  return {
                    ...item,
                    status: 'done',
                    url: '#',
                  }
                }
                return item
              }),
            )
          } catch (error: unknown) {
            // 后端错误（ResponseError）的 message 是未经 i18n 的原始文案，统一
            // 显示 t.uploadFailed；仅本地抛出的已翻译错误（如文件过大）才用其
            // message 展示。
            const msg =
              error instanceof ResponseError
                ? t.uploadFailed
                : (error as Error)?.message || t.uploadFailed
            window.$app.message.error(msg)
            hasError = true
            setFileList((prev) =>
              prev.map((item) => {
                if (item.uid === file.uid) {
                  return {
                    ...item,
                    status: 'error',
                    response: msg,
                  }
                }
                return item
              }),
            )
          }
        }

        if (hasError) {
          throw new Error('Upload failed')
        } else {
          window.$app.message.success(t.uploadSuccess)
        }
      },
    }
  })

  return (
    <div className={styles['repository-upload']}>
      <Upload.Dragger
        {...otherProps}
        accept=".txt,.md,.pdf"
        showUploadList={false}
        maxCount={10}
        fileList={fileList}
        onChange={(info) => setFileList(info.fileList)}
      >
        <img src={IconUpload} />
        <p
          className="ant-upload-text"
          style={{
            color: tokens.textSecondary,
          }}
        >
          {t.repoUploadDragText}{' '}
          <span style={{ color: tokens.accent }}>
            {t.repoUploadDragTextHighlight}
          </span>
        </p>
      </Upload.Dragger>

      <p className={styles['repository-upload__desc']}>{t.repoUploadDesc}</p>

      {/*
        这个 Upload 不是多余的：上面的 Dragger 设了 showUploadList={false}，
        已选/上传中文件列表（文件名、状态图标、删除按钮）由此组件渲染，
        与 Dragger 共享同一 fileList。scss 中 .ant-upload-list-item-progress
        即针对此处列表隐藏进度条。删除会导致用户看不到已选文件。
      */}
      <Upload
        fileList={fileList}
        onChange={(info) => setFileList(info.fileList)}
      />
    </div>
  )
})
