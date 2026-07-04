import * as api from '@/api'
import IconDelete from '@/assets/repository/action/delete.svg'
import { useLang } from '@/i18n'
import { PlusOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import { Button, Modal, Space, Table, Tag } from 'antd'
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
}

type IOfficialExample = API.OfficialExample & {
  id: number
  $suffix: FileIcon
}

export default function Index() {
  const { t } = useLang()
  const onListError = () => window.$app.message.error(t.genericError)

  const {
    data,
    loading: listLoading,
    refresh,
  } = useRequest(
    async () => {
      const { data } = await api.repository.list()
      return data?.map(
        (item, index) =>
          ({
            ...item,
            $suffix: item.file_name.split('.').pop() as FileIcon,
            id: index + 1,
          }) satisfies IRepository,
      )
    },
    { onError: onListError },
  )

  const { data: officialData, loading: officialLoading } = useRequest(
    async () => {
      const { data } = await api.repository.listOfficialExamples()
      return data?.map(
        (item, index) =>
          ({
            ...item,
            $suffix: item.file_name.split('.').pop() as FileIcon,
            id: index + 1,
          }) satisfies IOfficialExample,
      )
    },
    { onError: onListError },
  )

  const deleteFile = async (file: IRepository) => {
    await api.repository.deleteFile({
      file_name: file.file_name,
      session_id: file.session_id,
    })
    // 后端返回的 message 是中文提示，不随前端语言切换，因此提示统一使用
    // 前端 i18n 文案，不展示后端原始 message。
    window.$app.message.success(t.repoDeleteSuccess)
    refresh()
  }

  // 名称/更新时间/分块方法/状态四列在官方语料表和已上传文档表之间完全一致，
  // 只有"名称"列的渲染（是否显示 session 标签）和是否带操作列不同——用一个
  // 共享的基础列工厂避免两份表格定义重复维护。
  function buildBaseColumns<T extends IOfficialExample | IRepository>(
    renderName: (value: string, row: T) => React.ReactNode,
  ): ColumnsType<T> {
    return [
      {
        title: t.repoColName,
        dataIndex: 'file_name',
        width: 200,
        render: renderName,
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
        dataIndex: 'chunk_method',
        width: 100,
      },
      {
        title: t.repoColStatus,
        dataIndex: 'status',
        width: 100,
        render(value) {
          return <Status status={value} />
        },
      },
    ]
  }

  const officialColumns = useMemo<ColumnsType<IOfficialExample>>(
    () =>
      buildBaseColumns<IOfficialExample>((value, row) => (
        <div className={styles['repository-page__file-name']} title={value}>
          <FileIcon className={styles['icon']} suffix={row.$suffix} />
          {value}
        </div>
      )),
    [t],
  )

  const columns = useMemo<ColumnsType<IRepository>>(
    () => [
      ...buildBaseColumns<IRepository>((value, row) => (
        <div className={styles['repository-page__file-name']} title={value}>
          <FileIcon className={styles['icon']} suffix={row.$suffix} />
          {value}
          {row.session_id && (
            <Tag className={styles['repository-page__session-tag']}>
              {t.repoSessionTag}: {row.session_id}
            </Tag>
          )}
        </div>
      )),
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
    [t],
  )
  const scroll = useMemo(() => {
    return {
      x: columns?.reduce((prev, current) => {
        return prev + parseInt(String(current.width ?? 0))
      }, 0),
    }
  }, [columns])
  const officialScroll = useMemo(() => {
    return {
      x: officialColumns?.reduce((prev, current) => {
        return prev + parseInt(String(current.width ?? 0))
      }, 0),
    }
  }, [officialColumns])

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
        <div className={styles['repository-page__section']}>
          <div className={styles['repository-page__section-title']}>{t.repoOfficialTitle}</div>
          <div className={styles['repository-page__section-desc']}>{t.repoOfficialDesc}</div>
          <Table<IOfficialExample>
            rowKey="id"
            columns={officialColumns}
            dataSource={officialData}
            scroll={officialScroll}
            pagination={false}
            loading={officialLoading}
          />
        </div>

        <div className={styles['repository-page__section-title']}>{t.repoUploadedTitle}</div>

        <div className={styles['header']}>
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
          loading={listLoading}
        />
      </div>

      <Modal
        title={t.repoUploadModalTitle}
        open={openUpload}
        okText={t.repoUploadConfirm}
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
