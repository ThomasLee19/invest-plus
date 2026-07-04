import { PageTransportKey } from '@/utils'

export type ChatEnterData = {
  message: string
  attachments?: string[]
}

export const transportToChatEnter = Symbol() as PageTransportKey<{
  data: ChatEnterData
}>

let id = 0

export const createChatId = () => {
  return ++id
}
