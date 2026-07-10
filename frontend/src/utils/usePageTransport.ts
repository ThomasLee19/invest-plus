import { useMount } from 'ahooks'
import { useRef, useState } from 'react'

export type PageTransportKey<T> = symbol & { readonly __brand?: T }

const tempMap = new Map<PageTransportKey<unknown>, unknown>()

/**
 * 用于页面间数据传输
 * 需要注意的是，仅在组件初始化时有效
 */
export function usePageTransport<T>(key: PageTransportKey<T>) {
  const [data, setData] = useState<T | undefined>(() => tempMap.get(key) as T | undefined)
  // StrictMode 下（仅开发环境）effect 会被双调用；用 ref 守卫保证只消费一次，
  // 否则第二次调用会读到已被删除的 undefined，导致首条消息重复处理或丢失。
  const consumedRef = useRef(false)

  useMount(() => {
    if (consumedRef.current) return
    consumedRef.current = true

    const tempData = tempMap.get(key) as T | undefined
    if (tempData !== undefined) {
      setData(tempData)
      tempMap.delete(key)
    }
  })

  return {
    data,
    setData,
  }
}

export function setPageTransport<T>(key: PageTransportKey<T>, data: T) {
  tempMap.set(key, data)
}
