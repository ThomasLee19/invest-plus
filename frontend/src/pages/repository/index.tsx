import * as api from '@/api'
import IconDelete from '@/assets/repository/action/delete.svg'
import { useLang } from '@/i18n'
import { PlusOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { Button, Modal, Space, Table } from 'antd'
import { ColumnsType } from 'antd/es/table'
import { TableRowSelection } from 'antd/es/table/interface'
import dayjs from 'dayjs'
import { useMemo, useRef, useState } from 'react'
import { FileIcon } from './components/file-icon'
import { Status } from './components/status'
import RepositoryUpload, { RepositoryUploadRef } from './components/upload'
import styles from './index.module.scss'

type IRepository = API.Repository & {
  id: number
  $suffix: FileIcon
  method: string
  enable: boolean
  status: string
}

export default function Index() {
  const { t } = useLang()
  const { data, refresh } = useRequest(async () => {
    const { data } = await api.repository.list()
    return data?.map(
      (item, index) =>
        ({
          ...item,
          $suffix: item.file_name.split('.').pop() as FileIcon,
          id: index + 1,
          method: '优化分块',
          enable: true,
          status: 'success',
        }) satisfies IRepository,
    )
  })

  const deleteFile = async (file: IRepository) => {
    const {
      data: { message = '删除成功' },
    } =
      (await api.repository.deleteFile({
        file_name: file.file_name,
      })) || {}
    // 提示成功
    window.$app.message.success(message)
    refresh()
  }

  const columns = useMemo<ColumnsType<IRepository>>(
    () => [
      {
        title: t.repoColName,
        dataIndex: 'file_name',
        width: 200,
        render(value, row) {
          return (
            <div className={styles['repository-page__file-name']} title={value}>
              <FileIcon className={styles['icon']} suffix={row.$suffix} />
              {value}
            </div>
          )
        },
      },
      {
        title: t.repoColUpdated,
        dataIndex: 'updated_at',
        width: 200,
        render(value) {
          return dayjs(value).format('MM/DD/YYYY HH:mm:ss')
        },
      },
      {
        title: t.repoColMethod,
        dataIndex: 'method',
        width: 100,
        render(value) {
          return value ?? '优化分块'
        },
      },
      {
        title: t.repoColStatus,
        dataIndex: 'status',
        width: 100,
        render(value) {
          return <Status status={value} />
        },
      },
      {
        title: t.repoColAction,
        dataIndex: 'action',
        width: 100,
        render(_, row) {
          return (
            <Space>
              <Button
                color="default"
                variant="text"
                shape="circle"
                size="small"
                onClick={() => deleteFile(row)}
              >
                <img src={IconDelete} />
              </Button>
            </Space>
          )
        },
      },
    ],
    [],
  )
  const scroll = useMemo(() => {
    return {
      x: columns?.reduce((prev, current) => {
        return prev + parseInt(String(current.width ?? 0))
      }, 0),
    }
  }, [columns])

  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const onSelectChange = (newSelectedRowKeys: React.Key[]) => {
    setSelectedRowKeys(newSelectedRowKeys)
  }
  const rowSelection: TableRowSelection<IRepository> = {
    selectedRowKeys,
    onChange: onSelectChange,
  }

  /* 上传 */
  const [openUpload, setOpenUpload] = useState(false)
  const uploadRef = useRef<RepositoryUploadRef>(null)
  const [uploading, setUploading] = useState(false)

  return (
    <div className={styles['repository-page']}>
      <div className={styles['repository-page__header']}>
        <div className={styles['title']}>{t.repoTitle}</div>
        <div className={styles['desc']}>{t.repoDesc}</div>
      </div>

      <div className={styles['repository-page__body']}>
        <div className={styles['header']}>
          {/* <Input
            placeholder="搜索你的文件"
            prefix={<img src={IconSearch} />}
            style={{ width: 210 }}
          /> */}

          <Button type="primary" onClick={() => setOpenUpload(true)}>
            <PlusOutlined />
            {t.repoAddFile}
          </Button>
        </div>

        <Table<IRepository>
          rowKey="id"
          columns={columns}
          dataSource={data}
          rowSelection={rowSelection}
          scroll={scroll}
          pagination={false}
        />
      </div>

      <Modal
        title="Upload File"
        open={openUpload}
        okText="Confirm"
        width={400}
        destroyOnClose
        onCancel={() => {
          if (uploading) return
          setOpenUpload(false)
        }}
        onOk={async () => {
          setUploading(true)
          try {
            await uploadRef.current?.submit()
            setOpenUpload(false)
            refresh()
          } finally {
            setUploading(false)
          }
        }}
      >
        <RepositoryUpload beforeUpload={() => false} ref={uploadRef} />
      </Modal>
    </div>
  )
}
